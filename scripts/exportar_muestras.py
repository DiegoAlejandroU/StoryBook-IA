"""Tarea 5.4: revisa las historias reales más recientes y las exporta a ``samples/``.

Para cada historia:

1. Revisa el ambiente de cada escena hecho con un backend generativo (AudioLDM, Stable
   Audio). Si el clip es demasiado bajo o está casi todo en silencio, lo rehace
   (``Pipeline.rehacer_sonido``: mismo texto, imágenes y voz; necesita la GPU).
2. La exporta a ``samples/<run_id>/`` con los audios en OGG (``storage.exportar_muestra``),
   sobrescribiendo una exportación anterior incompleta.

Uso (PowerShell, desde la carpeta del proyecto):
    uv run python scripts/exportar_muestras.py          # las 3 historias reales más recientes
    uv run python scripts/exportar_muestras.py --n 2
    uv run python scripts/exportar_muestras.py outputs/<carpeta_de_la_historia>
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from storybook import config  # primero: fija HF_HOME y el modo offline
from storybook.logging_utils import get_logger, kv, setup_logging
from storybook.sound.generator import GENERATIVOS, problema_de_ambiente
from storybook.sound.library import cargar_audio_mono
from storybook.storage import NUM_ESCENAS, cargar_manifest, exportar_muestra, listar_historias

log = get_logger("exportar_muestras")


def historias_reales_recientes(raiz: Path, n: int) -> list[Path]:
    """Las ``n`` historias completas más recientes generadas con modelos reales."""
    elegidas: list[Path] = []
    for entrada in listar_historias([raiz]):
        manifest = cargar_manifest(entrada.carpeta)
        texto = manifest.get("etapas", {}).get("texto", {})
        if texto.get("modelo") == "simulado" or not str(manifest.get("estado", "")).startswith(
            "completa"
        ):
            continue
        elegidas.append(entrada.carpeta)
        if len(elegidas) == n:
            break
    return elegidas


def escenas_con_ambiente_debil(carpeta: Path) -> list[int]:
    """Escenas cuyo ambiente generativo es demasiado bajo o casi silencio (o falta)."""
    manifest = cargar_manifest(carpeta)
    backends = {
        int(s["escena"]): str(s.get("backend", ""))
        for s in manifest.get("etapas", {}).get("sonido", {}).get("sonidos", [])
    }
    debiles: list[int] = []
    for numero in range(1, NUM_ESCENAS + 1):
        ruta = carpeta / f"sfx_{numero}.wav"
        if not ruta.is_file():
            debiles.append(numero)
            continue
        if backends.get(numero) not in GENERATIVOS:
            continue  # procedural o biblioteca: intermitentes a propósito (reloj, pasos)
        audio, frecuencia = cargar_audio_mono(ruta)
        problema = problema_de_ambiente(audio, frecuencia)
        if problema:
            log.warning(
                "ambiente_debil", extra=kv(historia=carpeta.name, escena=numero, problema=problema)
            )
            debiles.append(numero)
    return debiles


def procesar(
    carpetas: Sequence[Path], pipeline: Any, destino: Path | None = None
) -> tuple[list[str], list[str]]:
    """Rehace los ambientes débiles y exporta cada historia. Devuelve (líneas, errores)."""
    lineas: list[str] = []
    errores: list[str] = []
    for carpeta in carpetas:
        try:
            debiles = escenas_con_ambiente_debil(carpeta)
            if debiles:
                historia = pipeline.rehacer_sonido(carpeta, debiles)
                nuevos = historia.manifest["regeneraciones"][-1]["backends"]
                lineas.append(
                    f"- {carpeta.name}: ambiente rehecho en escenas {debiles} -> {nuevos}"
                )
            else:
                lineas.append(f"- {carpeta.name}: ambientes correctos, no se rehace nada")
            salida = exportar_muestra(carpeta, destino)
        except Exception as exc:  # se informa y se sigue con la siguiente historia
            errores.append(f"{carpeta.name}: {type(exc).__name__}: {exc}")
            log.exception("exportacion_fallida", extra=kv(historia=carpeta.name))
            continue
        peso = sum(f.stat().st_size for f in salida.iterdir()) / 1_000_000
        lineas.append(f"  exportada a {salida} ({peso:.1f} MB)")
    return lineas, errores


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("carpetas", nargs="*", type=Path)
    parser.add_argument("--n", type=int, default=3)
    parser.add_argument("--perfil", default="rapido")
    args = parser.parse_args(argv)
    setup_logging()
    from storybook.pipeline import Pipeline

    carpetas = args.carpetas or historias_reales_recientes(config.OUTPUTS_DIR, args.n)
    if not carpetas:
        sys.stdout.write("No hay historias reales completas en outputs/.\n")
        return 1
    lineas, errores = procesar(carpetas, Pipeline(config.load_config(args.perfil)))
    salida = ["", "Historias de ejemplo:", *lineas, *(f"- ERROR: {e}" for e in errores), ""]
    sys.stdout.write("\n".join(salida))
    return 2 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
