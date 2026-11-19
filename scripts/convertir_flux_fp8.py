"""Copia en fp8 de FLUX.1-schnell para la GPU de 4 GB (perfil Avanzada, 18 nov).

Lee los pesos oficiales en bf16 (``download_models.py --profiles avanzada``) tensor por
tensor y escribe en ``models/flux-schnell-fp8`` el transformer (~12 GB) y el encoder T5
(~4,9 GB) con las capas lineales en float8_e4m3fn. Se hace una sola vez (unos minutos; casi
todo es leer y escribir disco). Los originales no se tocan.

Uso (PowerShell, desde la carpeta del proyecto):
    uv run python scripts/convertir_flux_fp8.py
    uv run python scripts/convertir_flux_fp8.py --perfil avanzada --forzar
"""

from __future__ import annotations

import argparse
import sys
import time

from storybook import config
from storybook.hub import local_snapshot
from storybook.image.flux import COMPONENTES_FP8, carpeta_fp8, convertir_componente, fp8_listo
from storybook.logging_utils import get_logger, kv, setup_logging

log = get_logger("convertir_flux_fp8")


def avisar(texto: str) -> None:
    """Progreso en la consola (la conversión tarda unos minutos)."""
    sys.stdout.write(texto + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--perfil", default="avanzada")
    parser.add_argument("--forzar", action="store_true", help="Convertir aunque ya exista")
    args = parser.parse_args(argv)
    setup_logging()

    cfg = config.load_config(args.perfil).image
    if cfg.arquitectura != "flux":
        avisar(f"El perfil {args.perfil} no usa FLUX (arquitectura: {cfg.arquitectura}).")
        return 1
    destino = carpeta_fp8(cfg)
    if fp8_listo(destino) and not args.forzar:
        avisar(f"Ya está convertido en {destino}. Usa --forzar para repetir.")
        return 0
    origen = local_snapshot(cfg.model_id)
    avisar(f"Convirtiendo {cfg.model_id} a fp8 en {destino} (lee ~33 GB, escribe ~17 GB)...")
    inicio = time.perf_counter()
    for componente in COMPONENTES_FP8:
        indice = convertir_componente(origen, destino, componente, avisar=avisar)
        avisar(
            f"  {componente}: {indice['gb']} GB, {indice['tensores_fp8']} tensores en fp8, "
            f"{indice['valores_recortados']} valores recortados a ±448"
        )
    segundos = round(time.perf_counter() - inicio, 1)
    log.info("flux_fp8_listo", extra=kv(destino=str(destino), segundos=segundos))
    avisar(f"Listo en {segundos} s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
