"""F2 y F3 · Tareas 2.3 y 3.3: imágenes y voz reales de una Story Bible de F1.

Toma una historia ya generada en F1 (por defecto, la primera válida de la última corrida
hecha con el LLM del perfil) y ejecuta las etapas reales:

1. **Imágenes (2.3):** ``GeneradorImagenes`` con la configuración del perfil: character sheet,
   IP-Adapter y 5 escenas. Mide tiempo de carga, por imagen y VRAM pico; registra prompts,
   tokens, truncamientos, nombres sustituidos y fallbacks (OOM, respaldo, sin IP-Adapter).
2. **CLIP:** similitud imagen-texto por escena y similitud imagen-imagen entre las 5.
3. **Voz (3.3):** ``Narrador`` con la voz del perfil y, si se piden, voces alternativas para
   escucharlas y elegir. Mide duración y RTF por escena.
4. **WER:** transcribe cada narración con faster-whisper y la compara con el texto.

Cada paso es independiente: si uno falla, se registra el error y se sigue con los demás.

Salidas:
- ``outputs/f2/<fecha_hora>/``: ``scene_N.png``, ``character_sheet.png``,
  ``voz/<voz>/voice_N.wav``, ``resultado.json``, ``resumen.md`` y ``run.log``.
- ``docs/evidencias/f2_f3_resumen.md`` y ``f2_f3.json`` (con sufijo si el perfil no es rapido).

Uso (PowerShell, desde la carpeta del proyecto):
    uv run python scripts/f2_f3_prueba.py
    uv run python scripts/f2_f3_prueba.py --perfil calidad
    uv run python scripts/f2_f3_prueba.py --story outputs/f1/20261110_085328/story_04.json
    uv run python scripts/f2_f3_prueba.py --voces es_MX-ald-medium es_ES-davefx-medium
    uv run python scripts/f2_f3_prueba.py --solo voz
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from storybook import config  # primero: fija HF_HOME y el modo offline
from storybook.logging_utils import get_logger, kv, setup_logging
from storybook.schemas import StoryBible

log = get_logger("f2_f3_prueba")

# Voces Piper en español para comparar en 3.3 (se descargan con download_models.py
# --voces-extra; si alguna no está descargada se informa y se sigue).
VOCES_ALTERNATIVAS: tuple[str, ...] = ("es_MX-ald-medium", "es_ES-davefx-medium")

FabricaImagen = Callable[[config.AppConfig], Any]
FabricaVoz = Callable[[config.VoiceConfig], Any]


# ---------------------------------------------------------------------------------------
# Selección de la historia
# ---------------------------------------------------------------------------------------
def elegir_story(raiz_f1: Path, modelo_llm: str) -> Path:
    """Primera Story Bible válida de la corrida más reciente de F1 hecha con ``modelo_llm``.

    Cada corrida guarda ``resumen.md`` con el modelo usado: así no se elige por error una
    historia del experimento con el 8B.
    """
    corridas = sorted((d for d in raiz_f1.iterdir() if d.is_dir()), reverse=True)
    for corrida in corridas:
        resumen = corrida / "resumen.md"
        if not resumen.is_file() or f"`{modelo_llm}`" not in resumen.read_text(encoding="utf-8"):
            continue
        for ruta in sorted(corrida.glob("story_*.json")):
            try:
                StoryBible.model_validate_json(ruta.read_text(encoding="utf-8"))
            except ValueError:
                continue
            return ruta
    raise FileNotFoundError(
        f"No hay historias válidas de F1 generadas con {modelo_llm} en {raiz_f1}. "
        "Ejecuta antes: setup_windows.ps1 -Paso f1"
    )


# ---------------------------------------------------------------------------------------
# Pasos
# ---------------------------------------------------------------------------------------
def _mediana(valores: Sequence[float]) -> float | None:
    return round(statistics.median(valores), 3) if valores else None


def _maximo(valores: Sequence[float | None]) -> float | None:
    presentes = [v for v in valores if v is not None]
    return round(max(presentes), 1) if presentes else None


def paso_imagen(
    cfg: config.AppConfig, bible: StoryBible, carpeta: Path, backend: Any = None
) -> tuple[Any, dict[str, Any]]:
    from storybook.image.generator import GeneradorImagenes

    etapa = GeneradorImagenes(cfg.image, cfg.consistency, backend=backend).generar(bible, carpeta)
    metricas = {m.etapa: m for m in etapa.metricas}
    validas = [r for r in etapa.imagenes if not r.respaldo]
    datos = {
        "parametros": etapa.parametros,
        "backend": etapa.backend,
        "segundos_carga": getattr(metricas.get("imagen_carga"), "segundos", None),
        "segundos_character_sheet": getattr(
            metricas.get("imagen_character_sheet"), "segundos", None
        ),
        "segundos_ip_adapter": getattr(metricas.get("imagen_ip_adapter"), "segundos", None),
        "segundos_por_imagen_mediana": _mediana([r.segundos for r in validas]),
        "segundos_total": round(sum(m.segundos for m in etapa.metricas), 2),
        "vram_torch_pico_mb": _maximo([m.vram_torch_pico_mb for m in etapa.metricas]),
        "vram_gpu_pico_mb": _maximo([m.vram_gpu_pico_mb for m in etapa.metricas]),
        "vram_gpu_total_mb": _maximo([m.vram_gpu_total_mb for m in etapa.metricas]),
        "respaldos": [r.escena for r in etapa.imagenes if r.respaldo],
        "fallbacks": etapa.fallbacks,
        "errores": etapa.errores,
        "ip_adapter": any(r.ip_adapter for r in etapa.imagenes),
        "escenas": [
            {
                "escena": r.escena,
                "archivo": r.ruta.name,
                "segundos": r.segundos,
                "seed": r.seed,
                "tokens": r.prompt.tokens,
                "truncado": r.prompt.truncado,
                "sustituciones": [s.a_dict() for s in r.prompt.sustituciones],
                "prompt": r.prompt.prompt,
                "respaldo": r.respaldo,
            }
            for r in etapa.imagenes
        ],
    }
    return etapa, datos


def paso_clip(cfg: config.AppConfig, etapa_imagen: Any) -> dict[str, Any]:
    from storybook.evaluation.clip_metrics import ClipScorer

    validas = [r for r in etapa_imagen.imagenes if not r.respaldo]
    if not validas:
        return {"error": "no hay imágenes válidas"}
    scorer = ClipScorer(cfg.evaluation.clip_model, cfg.evaluation.clip_pretrained)
    por_escena = {r.escena: scorer.imagen_texto(r.ruta, r.prompt.prompt) for r in validas}
    datos: dict[str, Any] = {
        "imagen_texto_por_escena": por_escena,
        "imagen_texto_media": round(statistics.mean(por_escena.values()), 4),
    }
    if len(validas) >= 2:
        datos["imagen_imagen"] = scorer.imagen_imagen([r.ruta for r in validas])
    return datos


def paso_voz(
    cfg: config.AppConfig,
    bible: StoryBible,
    carpeta: Path,
    voces: Sequence[str],
    fabrica: FabricaVoz | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Narra la historia con cada voz. Devuelve las etapas (por voz) y sus datos."""
    from storybook.voice.tts import Narrador

    etapas: dict[str, Any] = {}
    datos: dict[str, dict[str, Any]] = {}
    for voz in voces:
        cfg_voz = cfg.voice.model_copy(update={"piper_voice": voz})
        try:
            narrador = Narrador(cfg_voz, backend=fabrica(cfg_voz) if fabrica else None)
            etapa = narrador.narrar_bible(bible, carpeta / "voz" / voz)
        except Exception as exc:  # una voz no descargada no detiene las demás
            datos[voz] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
            log.warning("voz_fallida", extra=kv(voz=voz, error=datos[voz]["error"]))
            continue
        etapas[voz] = etapa
        rtfs = [n.rtf for n in etapa.narraciones if n.rtf is not None]
        datos[voz] = {
            "duracion_total_s": etapa.duracion_total_s,
            "rtf_mediana": _mediana(rtfs),
            "segundos_carga": etapa.metricas[0].segundos if etapa.metricas else None,
            "narraciones": [n.a_dict() for n in etapa.narraciones],
            "carpeta": str((carpeta / "voz" / voz).relative_to(carpeta)),
        }
    return etapas, datos


def paso_wer(
    cfg: config.AppConfig, bible: StoryBible, etapas_voz: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    from storybook.evaluation.asr_check import WhisperChecker

    e = cfg.evaluation
    checker = WhisperChecker(
        e.whisper_model, e.whisper_compute_type, e.whisper_language, e.cpu_threads
    )
    datos: dict[str, dict[str, Any]] = {}
    for voz, etapa in etapas_voz.items():
        por_escena: dict[int, dict[str, Any]] = {}
        for narracion in etapa.narraciones:
            referencia = bible.escena(narracion.escena).texto_narrativo
            resultado = checker.evaluar(narracion.ruta, referencia)
            por_escena[narracion.escena] = {
                "wer": round(resultado.wer, 4),
                "transcripcion": resultado.transcripcion,
            }
        wers = [d["wer"] for d in por_escena.values()]
        datos[voz] = {
            "wer_mediana": _mediana(wers),
            "wer_maximo": max(wers) if wers else None,
            "por_escena": por_escena,
        }
    return datos


# ---------------------------------------------------------------------------------------
# Orquestación y resumen
# ---------------------------------------------------------------------------------------
def ejecutar(
    cfg: config.AppConfig,
    bible: StoryBible,
    carpeta: Path,
    *,
    voces: Sequence[str],
    solo: str | None = None,
    evaluar: bool = True,
    backend_imagen: Any = None,
    fabrica_voz: FabricaVoz | None = None,
) -> dict[str, Any]:
    resultado: dict[str, Any] = {"errores": {}}

    def correr(nombre: str, funcion: Callable[[], Any]) -> Any:
        inicio = time.perf_counter()
        try:
            return funcion()
        except Exception as exc:
            mensaje = f"{type(exc).__name__}: {exc}"[:500]
            resultado["errores"][nombre] = mensaje
            log.exception("paso_fallido", extra=kv(paso=nombre, error=mensaje))
            return None
        finally:
            log.info("paso", extra=kv(paso=nombre, s=round(time.perf_counter() - inicio, 2)))

    if solo in (None, "imagen"):
        salida = correr("imagen", lambda: paso_imagen(cfg, bible, carpeta, backend_imagen))
        if salida is not None:
            etapa_imagen, resultado["imagen"] = salida
            if evaluar:
                resultado["clip"] = correr("clip", lambda: paso_clip(cfg, etapa_imagen))
    if solo in (None, "voz"):
        salida_voz = correr("voz", lambda: paso_voz(cfg, bible, carpeta, voces, fabrica_voz))
        if salida_voz is not None:
            etapas_voz, resultado["voz"] = salida_voz
            if evaluar and etapas_voz:
                resultado["wer"] = correr("wer", lambda: paso_wer(cfg, bible, etapas_voz))
    return resultado


def _f(valor: Any, sufijo: str = "") -> str:
    return "-" if valor is None else f"{valor}{sufijo}"


def resumen_md(resultado: dict[str, Any], perfil: str, story: Path, bible: StoryBible) -> str:
    lineas = [
        f"# F2/F3 · Imágenes y voz reales ({datetime.now():%Y-%m-%d %H:%M})",
        "",
        f'- Perfil `{perfil}` · historia `{story.as_posix()}`: "{bible.titulo}" ({bible.genero}),'
        f" {len(bible.personajes)} personajes.",
    ]
    imagen = resultado.get("imagen")
    if imagen:
        p = imagen["parametros"]
        lineas += [
            "",
            "## Imágenes (tarea 2.3)",
            "",
            f"- `{p['modelo']}` · {p['scheduler']} · {p['pasos']} pasos · CFG {p['guidance_scale']}"
            f" · {p['ancho']}×{p['alto']} · IP-Adapter {'sí' if imagen['ip_adapter'] else 'no'}"
            f" (escala {_f(p.get('ip_adapter_scale'))}).",
            f"- Tiempos: carga {_f(imagen['segundos_carga'], ' s')} · character sheet"
            f" {_f(imagen['segundos_character_sheet'], ' s')} · IP-Adapter"
            f" {_f(imagen['segundos_ip_adapter'], ' s')} · **por imagen (mediana)"
            f" {_f(imagen['segundos_por_imagen_mediana'], ' s')}** · total"
            f" {_f(imagen['segundos_total'], ' s')}.",
            f"- **VRAM pico:** GPU {_f(imagen['vram_gpu_pico_mb'], ' MB')} de"
            f" {_f(imagen['vram_gpu_total_mb'], ' MB')} · torch"
            f" {_f(imagen['vram_torch_pico_mb'], ' MB')}.",
            f"- Respaldos (OOM u otro error): {imagen['respaldos'] or 'ninguno'} · fallbacks:"
            f" {imagen['fallbacks'] or 'ninguno'}.",
        ]
        clip = resultado.get("clip") or {}
        por_escena = clip.get("imagen_texto_por_escena", {})
        if "imagen_imagen" in clip:
            ii = clip["imagen_imagen"]
            lineas.append(
                f"- CLIP imagen-texto (media): {clip['imagen_texto_media']} · CLIP imagen-imagen:"
                f" media {ii['media']}, mínimo {ii['minimo']} ({ii['pares']} pares)."
            )
        lineas += [
            "",
            "| Escena | s | Seed | Tokens | Truncado | Nombres sustituidos | CLIP texto |",
            "|---:|---:|---:|---:|---|---|---:|",
        ]
        for e in imagen["escenas"]:
            sust = ", ".join(f"{s['nombre']}→{s['por']}" for s in e["sustituciones"]) or "-"
            lineas.append(
                f"| {e['escena']} | {e['segundos']} | {e['seed']} | {e['tokens']} |"
                f" {'sí' if e['truncado'] else 'no'} | {sust} |"
                f" {_f(por_escena.get(e['escena']))} |"
            )
    voz = resultado.get("voz")
    if voz:
        wer = resultado.get("wer") or {}
        lineas += [
            "",
            "## Voz (tarea 3.3)",
            "",
            "| Voz | Duración total | RTF (mediana) | WER (mediana) | WER (máximo) | Carpeta |",
            "|---|---:|---:|---:|---:|---|",
        ]
        for nombre, d in voz.items():
            if "error" in d:
                lineas.append(f"| {nombre} | - | - | - | - | {d['error'][:80]} |")
                continue
            w = wer.get(nombre, {})
            lineas.append(
                f"| {nombre} | {d['duracion_total_s']} s | {_f(d['rtf_mediana'])} |"
                f" {_f(w.get('wer_mediana'))} | {_f(w.get('wer_maximo'))} | `{d['carpeta']}` |"
            )
        lineas += [
            "",
            "Escucha los `voice_N.wav` de cada carpeta y elige la voz (tarea 3.3).",
        ]
        principal = next(iter(wer.values()), None)
        if principal:
            peor = max(principal["por_escena"].items(), key=lambda kv_: kv_[1]["wer"])
            lineas += [
                "",
                f"Escena con más WER en la primera voz (escena {peor[0]}, WER {peor[1]['wer']}):",
                "",
                f"- Texto: {bible.escena(peor[0]).texto_narrativo}",
                f"- Whisper: {peor[1]['transcripcion']}",
            ]
    if resultado["errores"]:
        lineas += ["", "## Errores", ""]
        lineas += [f"- **{paso}:** {error}" for paso, error in resultado["errores"].items()]
    return "\n".join(lineas) + "\n"


def sufijo_evidencias(perfil: str) -> str:
    return "" if perfil == "rapido" else f"_{Path(perfil).stem}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--perfil", default="rapido")
    parser.add_argument("--story", type=Path, default=None, help="story_XX.json de F1")
    parser.add_argument(
        "--voces",
        nargs="*",
        default=list(VOCES_ALTERNATIVAS),
        help="voces Piper alternativas a comparar con la del perfil (vacío = solo la del perfil)",
    )
    parser.add_argument("--solo", choices=["imagen", "voz"], default=None)
    parser.add_argument("--sin-evaluacion", action="store_true", help="sin CLIP ni WER")
    parser.add_argument("--evidencias", type=Path, default=config.DOCS_DIR / "evidencias")
    args = parser.parse_args(argv)

    cfg = config.load_config(args.perfil)
    carpeta = config.OUTPUTS_DIR / "f2" / datetime.now().strftime("%Y%m%d_%H%M%S")
    carpeta.mkdir(parents=True, exist_ok=True)
    setup_logging(log_file=carpeta / "run.log")

    story = args.story or elegir_story(config.OUTPUTS_DIR / "f1", cfg.llm.model)
    bible = StoryBible.model_validate_json(story.read_text(encoding="utf-8"))
    voces = list(dict.fromkeys([cfg.voice.piper_voice, *args.voces]))
    log.info("f2_inicio", extra=kv(perfil=args.perfil, story=str(story), voces=voces))

    resultado = ejecutar(
        cfg,
        bible,
        carpeta,
        voces=voces,
        solo=args.solo,
        evaluar=not args.sin_evaluacion,
    )
    resultado.update(perfil=args.perfil, story=str(story), titulo=bible.titulo)
    resumen = resumen_md(resultado, args.perfil, story, bible)

    sufijo = sufijo_evidencias(args.perfil)
    texto_json = json.dumps(resultado, ensure_ascii=False, indent=2, default=str)
    (carpeta / "resultado.json").write_text(texto_json, encoding="utf-8")
    (carpeta / "resumen.md").write_text(resumen, encoding="utf-8")
    args.evidencias.mkdir(parents=True, exist_ok=True)
    (args.evidencias / f"f2_f3{sufijo}.json").write_text(texto_json, encoding="utf-8")
    (args.evidencias / f"f2_f3_resumen{sufijo}.md").write_text(resumen, encoding="utf-8")
    sys.stdout.write(resumen)
    sys.stdout.write(f"\nArchivos: {carpeta}\n")
    log.info("f2_fin", extra=kv(errores=list(resultado["errores"])))
    return 2 if resultado["errores"] else 0


if __name__ == "__main__":
    sys.exit(main())
