"""Hoja de contactos de una historia (tarea 6.1): las 5 ilustraciones en una sola imagen.

Uso (PowerShell, desde la carpeta del proyecto):
    uv run python scripts/make_contact_sheet.py samples/<carpeta_de_la_historia>
    uv run python scripts/make_contact_sheet.py outputs/<carpeta> --destino hoja.jpg

Por defecto se guarda como ``contact_sheet.jpg`` dentro de cada carpeta.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from storybook.evaluation.contact_sheet import hoja_de_contactos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("carpetas", nargs="+", type=Path)
    parser.add_argument("--destino", type=Path, help="solo con una carpeta")
    args = parser.parse_args(argv)
    if args.destino and len(args.carpetas) > 1:
        parser.error("--destino solo se puede usar con una carpeta")
    for carpeta in args.carpetas:
        sys.stdout.write(f"{hoja_de_contactos(carpeta, args.destino)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
