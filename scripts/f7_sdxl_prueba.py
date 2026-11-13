"""Prueba del modelo de imagen más grande (12 nov): SDXL frente a SD 1.5 en la misma historia.

El docente pidió un modelo de imágenes más grande, y en las historias del 12 nov las
imágenes mezclaban personajes (un jaguar con la camisa del niño, clones del protagonista).
Este script toma una historia ya generada (su Story Bible, sin volver a llamar al LLM) y
genera sus ilustraciones con cada perfil pedido, por defecto:

- ``rapido``: SD 1.5 (DreamShaper 8 + LCM), ya con la corrección del personaje foco.
- ``sdxl``: DreamShaper XL Lightning con el UNet en fp8 y model CPU offload.

Mide tiempos, VRAM (torch y NVML), CLIP img-img (consistencia) y CLIP img-texto
(pertinencia), y arma una hoja de contactos por perfil, incluida la original de la historia
(código anterior). Si un perfil falla (por ejemplo, falta de memoria), se registra y se sigue
con el siguiente.

Uso (PowerShell, desde la carpeta del proyecto; primero la descarga):
    uv run python scripts/download_models.py --profiles sdxl --only image
    uv run python scripts/f7_sdxl_prueba.py                       # la historia real más reciente
    uv run python scripts/f7_sdxl_prueba.py --historia outputs/<carpeta> --perfiles sdxl
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from storybook import config  # primero: fija HF_HOME y el modo offline
from storybook.evaluation.contact_sheet import hoja_de_contactos
from storybook.logging_utils import get_logger, kv, setup_logging
from storybook.schemas import StoryBible
from storybook.storage import cargar_bible, cargar_manifest, listar_historias

log = get_logger("f7_sdxl")

PERFILES: Final = ("rapido", "sdxl")
SALIDA: Final = config.OUTPUTS_DIR / "f7"
EVIDENCIAS: Final = config.DOCS_DIR / "evidencias"


def historia_reciente(raiz: Path = config.OUTPUTS_DIR) -> Path:
    for entrada in listar_historias([raiz]):
        texto = cargar_manifest(entrada.carpeta).get("etapas", {}).get("texto", {})
        if texto.get("modelo") != "simulado":
            return entrada.carpeta
    raise FileNotFoundError(f"No hay historias reales en {raiz}")


def liberar_ollama() -> list[str]:
    """Saca de la VRAM los modelos que Ollama tenga cargados (si está abierto)."""
    from storybook.story.llm_client import OllamaClient

    cfg = config.load_config()
    try:
        cliente = OllamaClient(cfg.llm.host, timeout_s=30)
        try:
            nombres = [m.get("name", "") for m in cliente.running()]
            for nombre in nombres:
                cliente.unload(nombre)
            return nombres
        finally:
            cliente.close()
    except Exception:  # Ollama cerrado: no ocupa VRAM
        return []


def _vram(metricas: Sequence[Any], campo: str) -> float | None:
    valores = [getattr(m, campo, None) for m in metricas]
    numeros = [v for v in valores if isinstance(v, int | float)]
    return round(max(numeros), 1) if numeros else None


def resumen_etapa(perfil: str, etapa: Any, segundos: float) -> dict[str, Any]:
    escenas = [m for m in etapa.metricas if m.etapa.startswith("imagen_escena_")]
    carga = next((m.segundos for m in etapa.metricas if m.etapa == "imagen_carga"), None)
    sheet = next((m.segundos for m in etapa.metricas if m.etapa == "imagen_character_sheet"), None)
    return {
        "perfil": perfil,
        "total_s": round(segundos, 2),
        "carga_s": carga,
        "sheet_s": sheet,
        "por_imagen_mediana_s": round(statistics.median(m.segundos for m in escenas), 2)
        if escenas
        else None,
        "vram_torch_pico_mb": _vram(etapa.metricas, "vram_torch_pico_mb"),
        "vram_torch_reservada_mb": _vram(etapa.metricas, "vram_torch_reservada_pico_mb"),
        "vram_gpu_pico_mb": _vram(etapa.metricas, "vram_gpu_pico_mb"),
        "respaldos": sum(r.respaldo for r in etapa.imagenes),
        "fallbacks": list(etapa.fallbacks),
        "errores": list(etapa.errores),
        "escenas": [
            {
                "escena": r.escena,
                "foco": r.prompt.foco,
                "ip_escala": r.ip_escala,
                "segundos": r.segundos,
                "prompt": r.prompt.prompt,
            }
            for r in etapa.imagenes
        ],
        "backend": etapa.backend,
    }


def generar_con_perfil(
    perfil: str, bible: StoryBible, carpeta: Path, backend: Any = None
) -> dict[str, Any]:
    """Ilustraciones de la Bible con el perfil (``backend`` falso en los tests)."""
    from storybook.image.generator import GeneradorImagenes

    cfg = config.load_config(perfil)
    inicio = time.perf_counter()
    try:
        etapa = GeneradorImagenes(cfg.image, cfg.consistency, backend).generar(bible, carpeta)
    except Exception as exc:  # p. ej. el modelo no está descargado: se informa y se sigue
        log.exception("perfil_fallido", extra=kv(perfil=perfil))
        return {"perfil": perfil, "error": f"{type(exc).__name__}: {exc}"[:500]}
    resumen = resumen_etapa(perfil, etapa, time.perf_counter() - inicio)
    (carpeta / "story.json").write_text(etapa.bible.model_dump_json(indent=2), encoding="utf-8")
    return resumen


@lru_cache(maxsize=1)
def _scorer() -> Any:
    from storybook.evaluation.clip_metrics import ClipScorer

    e = config.load_config().evaluation
    return ClipScorer(e.clip_model, e.clip_pretrained)


def metricas_clip(carpeta: Path, bible: StoryBible, prompts: dict[int, str]) -> dict[str, Any]:
    """CLIP img-img entre las escenas y CLIP img-texto contra el prompt de cada una."""
    escenas = {n: carpeta / f"scene_{n}.png" for n in range(1, 6)}
    escenas = {n: ruta for n, ruta in escenas.items() if ruta.is_file()}
    if len(escenas) < 2:
        return {}
    try:
        scorer = _scorer()
    except Exception as exc:  # open_clip sin pesos en caché: el resto del informe sigue
        log.warning("clip_no_disponible", extra=kv(error=str(exc)))
        return {}
    pares = scorer.imagen_imagen(list(escenas.values()))
    textos = [
        scorer.imagen_texto(ruta, prompts.get(n) or bible.escena(n).prompt_imagen)
        for n, ruta in escenas.items()
    ]
    return {
        "clip_img_img_media": round(pares["media"], 4),
        "clip_img_img_min": round(pares["minimo"], 4),
        "clip_img_txt_media": round(statistics.mean(textos), 4),
    }


def reporte_md(historia: Path, bible: StoryBible, resultados: list[dict[str, Any]]) -> str:
    lineas = [
        f"# F7 · Modelo de imagen más grande: SDXL frente a SD 1.5 ({datetime.now():%Y-%m-%d})",
        "",
        f'Historia: "{bible.titulo}" (`{historia.name}`). Mismo texto, mismas seeds; '
        "solo cambia el modelo de imagen. `original` son las imágenes de la historia tal como "
        "se generaron (antes de la corrección del personaje foco).",
        "",
        "| Perfil | Total | Carga | Por imagen | VRAM torch (pico / reservada) | VRAM GPU | "
        "CLIP img-img (media / mín.) | CLIP img-texto | Respaldos |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in resultados:
        if "error" in r:
            lineas.append(f"| `{r['perfil']}` | **falló**: {r['error'][:120]} | | | | | | | |")
            continue

        def f(clave: str, sufijo: str = "", r: dict[str, Any] = r) -> str:
            valor = r.get(clave)
            return "—" if valor is None else f"{valor}{sufijo}"

        lineas.append(
            f"| `{r['perfil']}` | {f('total_s', ' s')} | {f('carga_s', ' s')} "
            f"| {f('por_imagen_mediana_s', ' s')} "
            f"| {f('vram_torch_pico_mb', ' MB')} / {f('vram_torch_reservada_mb', ' MB')} "
            f"| {f('vram_gpu_pico_mb', ' MB')} "
            f"| {f('clip_img_img_media')} / {f('clip_img_img_min')} | {f('clip_img_txt_media')} "
            f"| {f('respaldos')} |"
        )
    for r in resultados:
        if "escenas" not in r:
            continue
        lineas += ["", f"## `{r['perfil']}`: personaje foco e IP-Adapter por escena", ""]
        lineas += ["| Escena | Foco | IP-Adapter | s | Prompt |", "|---|---|---|---|---|"]
        for e in r["escenas"]:
            lineas.append(
                f"| {e['escena']} | {e['foco'] or '—'} | {e['ip_escala']} | {e['segundos']} "
                f"| {e['prompt'][:110]} |"
            )
        if r.get("fallbacks"):
            lineas.append(f"\nAlternativas usadas: {', '.join(r['fallbacks'])}")
    lineas += ["", "Hojas de contactos: `docs/evidencias/f7_hojas/`.", ""]
    return "\n".join(lineas)


def main(argv: list[str] | None = None, fabrica_backend: Callable[[], Any] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--historia", type=Path, help="carpeta de una historia (outputs/...)")
    parser.add_argument("--perfiles", nargs="+", default=list(PERFILES))
    args = parser.parse_args(argv)
    setup_logging()

    historia = args.historia or historia_reciente()
    bible = cargar_bible(historia)
    descargados = liberar_ollama()
    if descargados:
        log.info("ollama_liberado", extra=kv(modelos=descargados))
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    raiz = SALIDA / marca
    hojas = EVIDENCIAS / "f7_hojas"
    hojas.mkdir(parents=True, exist_ok=True)

    resultados: list[dict[str, Any]] = []
    original = {"perfil": "original"}
    manifest = cargar_manifest(historia)
    prompts_originales = {
        int(i["escena"]): i.get("prompt", {}).get("prompt", "")
        for i in manifest.get("etapas", {}).get("imagen", {}).get("imagenes", [])
    }
    original.update(metricas_clip(historia, bible, prompts_originales))
    resultados.append(original)
    shutil.copy2(
        hoja_de_contactos(historia, raiz / "original.jpg", titulo=f"{bible.titulo} · original"),
        hojas / f"{marca}_original.jpg",
    )

    for perfil in args.perfiles:
        carpeta = raiz / perfil
        backend = fabrica_backend() if fabrica_backend else None
        resultado = generar_con_perfil(perfil, bible, carpeta, backend)
        if "error" not in resultado:
            prompts = {e["escena"]: e["prompt"] for e in resultado["escenas"]}
            resultado.update(metricas_clip(carpeta, bible, prompts))
            hoja = hoja_de_contactos(carpeta, titulo=f"{bible.titulo} · {perfil}")
            shutil.copy2(hoja, hojas / f"{marca}_{perfil}.jpg")
        resultados.append(resultado)
        log.info("perfil_terminado", extra=kv(perfil=perfil, ok="error" not in resultado))

    texto = reporte_md(historia, bible, resultados)
    (EVIDENCIAS / "f7_sdxl.md").write_text(texto, encoding="utf-8")
    (EVIDENCIAS / "f7_sdxl.json").write_text(
        json.dumps(
            {"historia": historia.name, "resultados": resultados}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    sys.stdout.write(texto)
    fallidos = [r for r in resultados if "error" in r]
    return 2 if fallidos else 0


if __name__ == "__main__":
    sys.exit(main())
