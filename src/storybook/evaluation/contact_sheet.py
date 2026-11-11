"""Hoja de contactos de una historia (tarea 6.1): las ilustraciones en una sola imagen.

Cuadrícula de 3 × 2 con la character sheet (si existe) y las escenas 1-5, cada una con
su número y fase, y el título arriba. Se guarda como JPEG para que pese poco en git.
CLI: ``scripts/make_contact_sheet.py``.
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from PIL import Image, ImageDraw, ImageFont

NUM_ESCENAS: Final = 5
COLUMNAS: Final = 3
ANCHO_MINIATURA: Final = 384
MARGEN: Final = 12
ALTO_ETIQUETA: Final = 26
ALTO_TITULO: Final = 40
FONDO: Final = (24, 24, 28)
TEXTO: Final = (235, 235, 235)
TEXTO_TENUE: Final = (150, 150, 160)
NOMBRE_HOJA: Final = "contact_sheet.jpg"


# La fuente que trae Pillow no tiene tildes ("Clímax" sale "Cl?max"): primero se buscan
# fuentes del sistema (Windows: Arial/Segoe UI; Linux: DejaVu).
FUENTES_SISTEMA: Final = ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf")


@lru_cache(maxsize=8)
def _fuente(tamano: int) -> tuple[Any, bool]:
    """(fuente, admite_tildes)."""
    for nombre in FUENTES_SISTEMA:
        try:
            return ImageFont.truetype(nombre, tamano), True
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=tamano), False
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default(), False


def _texto(
    dibujo: ImageDraw.ImageDraw, xy: tuple[int, int], texto: str, color: Any, tamano: int
) -> None:
    fuente, tildes = _fuente(tamano)
    if not tildes:
        texto = "".join(
            c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
        )
    dibujo.text(xy, texto, fill=color, font=fuente)


def _datos_historia(carpeta: Path) -> tuple[str, dict[int, str]]:
    """Título y fase de cada escena (si la Bible es legible)."""
    try:
        from storybook.storage import cargar_bible
        from storybook.ui_logica import fase_legible

        bible = cargar_bible(carpeta)
    except Exception:  # carpeta sin story.json: solo números de escena
        return carpeta.name, {}
    return bible.titulo, {e.numero: fase_legible(e.fase) for e in bible.escenas}


def hoja_de_contactos(
    carpeta: Path,
    destino: Path | None = None,
    titulo: str | None = None,
    ancho_miniatura: int = ANCHO_MINIATURA,
) -> Path:
    """Arma la hoja de contactos de ``carpeta`` y devuelve la ruta del JPEG."""
    titulo_bible, fases = _datos_historia(carpeta)
    celdas: list[tuple[str, Path | None]] = []
    sheet = carpeta / "character_sheet.png"
    if sheet.is_file():
        celdas.append(("Personaje (referencia)", sheet))
    for numero in range(1, NUM_ESCENAS + 1):
        ruta = carpeta / f"scene_{numero}.png"
        etiqueta = f"Escena {numero}" + (f" · {fases[numero]}" if numero in fases else "")
        celdas.append((etiqueta, ruta if ruta.is_file() else None))
    if not any(ruta for _, ruta in celdas):
        raise FileNotFoundError(f"No hay ilustraciones en {carpeta}")

    alto_miniatura = ancho_miniatura * 2 // 3  # las escenas son 768 × 512 (3:2)
    filas = -(-len(celdas) // COLUMNAS)
    ancho = MARGEN + COLUMNAS * (ancho_miniatura + MARGEN)
    alto = ALTO_TITULO + filas * (alto_miniatura + ALTO_ETIQUETA + MARGEN) + MARGEN
    hoja = Image.new("RGB", (ancho, alto), FONDO)
    dibujo = ImageDraw.Draw(hoja)
    _texto(dibujo, (MARGEN, 10), titulo or titulo_bible, TEXTO, 20)
    for indice, (etiqueta, ruta) in enumerate(celdas):
        x = MARGEN + (indice % COLUMNAS) * (ancho_miniatura + MARGEN)
        y = ALTO_TITULO + (indice // COLUMNAS) * (alto_miniatura + ALTO_ETIQUETA + MARGEN)
        if ruta is None:
            dibujo.rectangle(
                (x, y, x + ancho_miniatura, y + alto_miniatura), outline=TEXTO_TENUE, width=1
            )
            _texto(dibujo, (x + 10, y + 10), "sin ilustración", TEXTO_TENUE, 15)
        else:
            with Image.open(ruta) as original:
                miniatura = original.convert("RGB")
            miniatura.thumbnail((ancho_miniatura, alto_miniatura))
            dx = (ancho_miniatura - miniatura.width) // 2
            dy = (alto_miniatura - miniatura.height) // 2
            hoja.paste(miniatura, (x + dx, y + dy))
        _texto(dibujo, (x, y + alto_miniatura + 5), etiqueta, TEXTO, 15)

    destino = destino or carpeta / NOMBRE_HOJA
    destino.parent.mkdir(parents=True, exist_ok=True)
    hoja.save(destino, "JPEG", quality=85, optimize=True)
    return destino
