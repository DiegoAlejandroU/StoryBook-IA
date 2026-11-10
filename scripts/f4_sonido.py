"""F4 · Tarea 4.4: sonido y mezcla reales de una Story Bible de F1.

Narra la historia con la voz del perfil (Piper) y, para cada variante de sonido, genera los
5 ambientes y los mezcla con la voz:

* ``cadena``: la cadena real del perfil (``sound.backends``: SA3 → … → procedural), tal como
  la usará la app; registra qué backend produjo cada escena y por qué se saltó cada uno.
* ``audioldm``, ``sa3``, ``sao``, ``library`` o ``procedural``: un solo backend (con
  procedural como red), para comparar tiempo, VRAM y pertinencia del sonido.

Salidas:
- ``outputs/f4/<fecha_hora>/voz/voice_N.wav`` y, por variante, ``<variante>/sfx_N.wav``,
  ``ambience_N.wav`` y ``mix_N.wav`` (escuchar los ``mix_N.wav``), más ``resultado.json``,
  ``resumen.md`` y ``run.log``.
- ``docs/evidencias/f4_sonido.md`` y ``f4_sonido.json`` (con sufijo si el perfil no es rapido).

Uso (PowerShell, desde la carpeta del proyecto):
    uv run python scripts/f4_sonido.py
    uv run python scripts/f4_sonido.py --variantes cadena audioldm procedural
    uv run python scripts/f4_sonido.py --perfil calidad --variantes cadena
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from storybook import config  # primero: fija HF_HOME y el modo offline
from storybook.logging_utils import get_logger, kv, setup_logging
from storybook.schemas import StoryBible
from storybook.story.muestras import elegir_story

log = get_logger("f4_sonido")

VARIANTES_POR_DEFECTO: tuple[str, ...] = ("cadena", "procedural")
VARIANTES_VALIDAS: tuple[str, ...] = ("cadena", "sa3", "sao", "audioldm", "library", "procedural")


def _maximo(valores: Sequence[float | None]) -> float | None:
    presentes = [v for v in valores if v is not None]
    return round(max(presentes), 1) if presentes else None


def narrar(cfg: config.AppConfig, bible: StoryBible, carpeta: Path, backend: Any = None) -> Any:
    from storybook.voice.tts import Narrador

    return Narrador(cfg.voice, backend=backend).narrar_bible(bible, carpeta)


def sonido_y_mezcla(
    cfg: config.AppConfig,
    bible: StoryBible,
    narraciones: dict[int, Path],
    carpeta: Path,
    variante: str,
    fabrica: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    from storybook.sound.generator import GeneradorSonido
    from storybook.sound.mixer import mezclar_historia

    backends = list(cfg.sound.backends) if variante == "cadena" else [variante]
    cfg_sonido = cfg.sound.model_copy(update={"backends": backends})
    etapa = GeneradorSonido(cfg_sonido, cfg.consistency.base_seed, fabrica=fabrica).generar(
        bible, carpeta
    )
    sonidos = {s.escena: (s.ruta, s.backend) for s in etapa.sonidos}
    mezcla = mezclar_historia(narraciones, sonidos, carpeta, cfg.mix)
    generados = [s.segundos for s in etapa.sonidos]
    return {
        "variante": variante,
        "carpeta": carpeta.name,
        "backends_configurados": backends,
        "backend_por_escena": {s.escena: s.backend for s in etapa.sonidos},
        "segundos_por_clip_mediana": round(statistics.median(generados), 3) if generados else None,
        "segundos_carga": {
            m.etapa.removeprefix("sonido_").removesuffix("_carga"): m.segundos
            for m in etapa.metricas
            if m.etapa.endswith("_carga")
        },
        "vram_gpu_pico_mb": _maximo([m.vram_gpu_pico_mb for m in etapa.metricas]),
        "vram_torch_pico_mb": _maximo([m.vram_torch_pico_mb for m in etapa.metricas]),
        "fallbacks": etapa.fallbacks,
        "errores": etapa.errores,
        "sonido": etapa.a_dict(),
        "mezcla": mezcla.a_dict(),
    }


def ejecutar(
    cfg: config.AppConfig,
    bible: StoryBible,
    carpeta: Path,
    variantes: Sequence[str],
    *,
    backend_voz: Any = None,
    fabrica_sonido: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    resultado: dict[str, Any] = {"variantes": [], "errores": {}}
    try:
        voz = narrar(cfg, bible, carpeta / "voz", backend_voz)
    except Exception as exc:
        resultado["errores"]["voz"] = f"{type(exc).__name__}: {exc}"[:500]
        log.exception("voz_fallida")
        return resultado
    resultado["voz"] = voz.a_dict()
    narraciones = {n.escena: n.ruta for n in voz.narraciones}
    for variante in variantes:
        try:
            resultado["variantes"].append(
                sonido_y_mezcla(
                    cfg, bible, narraciones, carpeta / variante, variante, fabrica_sonido
                )
            )
        except Exception as exc:
            resultado["errores"][variante] = f"{type(exc).__name__}: {exc}"[:500]
            log.exception("variante_fallida", extra=kv(variante=variante))
    return resultado


def _f(valor: Any, sufijo: str = "") -> str:
    return "-" if valor is None else f"{valor}{sufijo}"


def resumen_md(resultado: dict[str, Any], perfil: str, story: Path, bible: StoryBible) -> str:
    lineas = [
        f"# F4 · Sonido y mezcla reales ({datetime.now():%Y-%m-%d %H:%M})",
        "",
        f'- Perfil `{perfil}` · historia `{story.as_posix()}`: "{bible.titulo}" ({bible.genero}).',
    ]
    voz = resultado.get("voz")
    if voz:
        lineas.append(
            f"- Voz `{voz['backend'].get('voz', '-')}`: {voz['duracion_total_s']} s de narración."
        )
    lineas += [
        "",
        "| Variante | Backend por escena (1-5) | s/clip | VRAM pico GPU | LUFS voz / ambiente |"
        " Ambiente bajo la voz (pausas / habla) | Fallbacks |",
        "|---|---|---:|---:|---|---|---|",
    ]
    for v in resultado["variantes"]:
        mezclas = v["mezcla"]["mezclas"]
        lufs_voz = statistics.median(m["lufs_voz"] for m in mezclas)
        lufs_amb = statistics.median(m["lufs_ambiente"] for m in mezclas)
        pausa = statistics.median(m["ambiente_bajo_voz_db"] for m in mezclas)
        habla = statistics.median(m["ambiente_bajo_voz_hablando_db"] for m in mezclas)
        por_escena = " · ".join(v["backend_por_escena"][n] for n in sorted(v["backend_por_escena"]))
        lineas.append(
            f"| `{v['variante']}` | {por_escena} | {_f(v['segundos_por_clip_mediana'])} |"
            f" {_f(v['vram_gpu_pico_mb'], ' MB')} | {lufs_voz:.1f} / {lufs_amb:.1f} |"
            f" {pausa:.1f} / {habla:.1f} dB | {', '.join(v['fallbacks']) or 'ninguno'} |"
        )
    lineas += ["", "Prompts y etiquetas de sonido de cada escena:", ""]
    for e in bible.escenas:
        etiquetas = ", ".join(str(x) for x in e.etiquetas_sonido)
        lineas.append(f"{e.numero}. `{e.prompt_sonido}` ({etiquetas})")
    lineas += [
        "",
        "Escucha `mix_N.wav` de cada carpeta de variante: ¿se distingue el ambiente de la voz?"
        " ¿encaja con la escena?",
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
        "--variantes", nargs="+", choices=VARIANTES_VALIDAS, default=list(VARIANTES_POR_DEFECTO)
    )
    parser.add_argument("--evidencias", type=Path, default=config.DOCS_DIR / "evidencias")
    args = parser.parse_args(argv)

    cfg = config.load_config(args.perfil)
    carpeta = config.OUTPUTS_DIR / "f4" / datetime.now().strftime("%Y%m%d_%H%M%S")
    carpeta.mkdir(parents=True, exist_ok=True)
    setup_logging(log_file=carpeta / "run.log")
    story = args.story or elegir_story(config.OUTPUTS_DIR / "f1", cfg.llm.model)
    bible = StoryBible.model_validate_json(story.read_text(encoding="utf-8"))
    log.info("f4_inicio", extra=kv(perfil=args.perfil, story=str(story), variantes=args.variantes))

    resultado = ejecutar(cfg, bible, carpeta, args.variantes)
    resultado.update(perfil=args.perfil, story=str(story), titulo=bible.titulo)
    resumen = resumen_md(resultado, args.perfil, story, bible)
    texto_json = json.dumps(resultado, ensure_ascii=False, indent=2, default=str)
    sufijo = sufijo_evidencias(args.perfil)
    args.evidencias.mkdir(parents=True, exist_ok=True)
    (carpeta / "resultado.json").write_text(texto_json, encoding="utf-8")
    (carpeta / "resumen.md").write_text(resumen, encoding="utf-8")
    (args.evidencias / f"f4_sonido{sufijo}.json").write_text(texto_json, encoding="utf-8")
    (args.evidencias / f"f4_sonido{sufijo}.md").write_text(resumen, encoding="utf-8")
    sys.stdout.write(resumen + f"\nArchivos: {carpeta}\n")
    log.info("f4_fin", extra=kv(errores=list(resultado["errores"])))
    return 2 if resultado["errores"] else 0


if __name__ == "__main__":
    sys.exit(main())
