"""Gráficas del informe (tarea 6.3) dibujadas con Pillow, sin dependencias nuevas.

Tres tipos: barras agrupadas, barras horizontales apiladas y dispersión con etiquetas.
Fondo blanco, para que se impriman bien en el PDF del informe, y una paleta apta para
daltonismo (Okabe-Ito). Cada gráfica rotula sus valores, así se lee sin leyenda de colores.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw

from storybook.evaluation.contact_sheet import _fuente, _texto

ANCHO: Final = 1400
ALTO: Final = 800
FONDO: Final = (255, 255, 255)
TINTA: Final = (34, 34, 34)
TENUE: Final = (110, 110, 110)
REJILLA: Final = (225, 225, 225)
PALETA: Final = (
    (0, 114, 178),
    (230, 159, 0),
    (0, 158, 115),
    (204, 121, 167),
    (86, 180, 233),
    (213, 94, 0),
)
MARGEN_IZQ: Final = 110
MARGEN_DER: Final = 40
MARGEN_SUP: Final = 110
MARGEN_INF: Final = 120


def _ancho_texto(texto: str, tamano: int) -> int:
    fuente, _ = _fuente(tamano)
    caja = fuente.getbbox(texto)
    return int(caja[2] - caja[0])


def _paso_rejilla(maximo: float) -> float:
    """Paso "redondo" (1, 2 o 5 × 10^n) para unas 5 líneas de rejilla."""
    if maximo <= 0:
        return 1.0
    bruto = maximo / 5
    potencia = 10 ** math.floor(math.log10(bruto))
    return next(m * potencia for m in (1, 2, 5, 10) if m * potencia >= bruto)


def _encabezado(dibujo: ImageDraw.ImageDraw, titulo: str, subtitulo: str) -> None:
    _texto(dibujo, (MARGEN_IZQ, 24), titulo, TINTA, 30)
    if subtitulo:
        _texto(dibujo, (MARGEN_IZQ, 64), subtitulo, TENUE, 19)


def _leyenda(dibujo: ImageDraw.ImageDraw, nombres: Sequence[str], y: int) -> None:
    x = MARGEN_IZQ
    for indice, nombre in enumerate(nombres):
        color = PALETA[indice % len(PALETA)]
        dibujo.rectangle((x, y + 4, x + 18, y + 22), fill=color)
        _texto(dibujo, (x + 26, y), nombre, TINTA, 19)
        x += 26 + _ancho_texto(nombre, 19) + 36


def barras_agrupadas(
    categorias: Sequence[str],
    series: Mapping[str, Sequence[float | None]],
    titulo: str,
    eje_y: str,
    ruta: Path,
    *,
    subtitulo: str = "",
    decimales: int = 2,
    y_max: float | None = None,
) -> Path:
    """Una agrupación por categoría y una barra por serie, con el valor encima."""
    imagen = Image.new("RGB", (ANCHO, ALTO), FONDO)
    dibujo = ImageDraw.Draw(imagen)
    _encabezado(dibujo, titulo, subtitulo)
    valores = [v for vs in series.values() for v in vs if v is not None]
    tope = y_max if y_max is not None else (max(valores) * 1.15 if valores else 1.0)
    paso = _paso_rejilla(tope)
    tope = math.ceil(tope / paso) * paso
    x0, x1 = MARGEN_IZQ, ANCHO - MARGEN_DER
    y0, y1 = ALTO - MARGEN_INF, MARGEN_SUP + 20

    def y_de(valor: float) -> float:
        return y0 - (valor / tope) * (y0 - y1)

    marca = 0.0
    while marca <= tope + 1e-9:
        y = y_de(marca)
        dibujo.line((x0, y, x1, y), fill=REJILLA, width=1)
        etiqueta = f"{marca:.{max(decimales - 1, 0)}f}"
        _texto(dibujo, (x0 - 12 - _ancho_texto(etiqueta, 17), int(y) - 11), etiqueta, TENUE, 17)
        marca += paso
    _texto(dibujo, (12, MARGEN_SUP - 10), eje_y, TENUE, 17)

    nombres = list(series)
    ancho_grupo = (x1 - x0) / max(len(categorias), 1)
    ancho_barra = min(70.0, ancho_grupo * 0.8 / max(len(nombres), 1))
    for i, categoria in enumerate(categorias):
        centro = x0 + ancho_grupo * (i + 0.5)
        inicio = centro - ancho_barra * len(nombres) / 2
        for j, nombre in enumerate(nombres):
            valor = series[nombre][i]
            if valor is None:
                continue
            xa = inicio + j * ancho_barra + 3
            xb = inicio + (j + 1) * ancho_barra - 3
            dibujo.rectangle((xa, y_de(valor), xb, y0), fill=PALETA[j % len(PALETA)])
            texto = f"{valor:.{decimales}f}"
            _texto(
                dibujo,
                (int((xa + xb) / 2 - _ancho_texto(texto, 15) / 2), int(y_de(valor)) - 22),
                texto,
                TINTA,
                15,
            )
        _texto(
            dibujo, (int(centro - _ancho_texto(categoria, 19) / 2), y0 + 12), categoria, TINTA, 19
        )
    dibujo.line((x0, y0, x1, y0), fill=TINTA, width=2)
    _leyenda(dibujo, nombres, ALTO - 50)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    imagen.save(ruta, "PNG", optimize=True)
    return ruta


def barras_apiladas(
    categorias: Sequence[str],
    componentes: Mapping[str, Sequence[float]],
    titulo: str,
    eje_x: str,
    ruta: Path,
    *,
    subtitulo: str = "",
) -> Path:
    """Barras horizontales apiladas (p. ej. segundos por etapa), con el total a la derecha."""
    imagen = Image.new("RGB", (ANCHO, ALTO), FONDO)
    dibujo = ImageDraw.Draw(imagen)
    _encabezado(dibujo, titulo, subtitulo)
    nombres = list(componentes)
    totales = [sum(componentes[n][i] for n in nombres) for i in range(len(categorias))]
    margen_etiquetas = max((_ancho_texto(c, 19) for c in categorias), default=0) + 30
    x0, x1 = MARGEN_IZQ + margen_etiquetas - 90, ANCHO - MARGEN_DER - 90
    y0, y1 = MARGEN_SUP + 20, ALTO - MARGEN_INF
    tope = max(totales, default=1.0) * 1.02
    paso = _paso_rejilla(tope)
    tope = math.ceil(tope / paso) * paso

    def x_de(valor: float) -> float:
        return x0 + (valor / tope) * (x1 - x0)

    marca = 0.0
    while marca <= tope + 1e-9:
        x = x_de(marca)
        dibujo.line((x, y0, x, y1), fill=REJILLA, width=1)
        etiqueta = f"{marca:.0f}"
        _texto(dibujo, (int(x - _ancho_texto(etiqueta, 17) / 2), y1 + 8), etiqueta, TENUE, 17)
        marca += paso
    _texto(dibujo, (int(x1 - _ancho_texto(eje_x, 17)), y1 + 34), eje_x, TENUE, 17)

    alto_fila = (y1 - y0) / max(len(categorias), 1)
    alto_barra = min(60.0, alto_fila * 0.65)
    for i, categoria in enumerate(categorias):
        centro = y0 + alto_fila * (i + 0.5)
        _texto(
            dibujo,
            (int(x0 - 16 - _ancho_texto(categoria, 19)), int(centro) - 12),
            categoria,
            TINTA,
            19,
        )
        acumulado = 0.0
        for j, nombre in enumerate(nombres):
            valor = componentes[nombre][i]
            xa, xb = x_de(acumulado), x_de(acumulado + valor)
            dibujo.rectangle(
                (xa, centro - alto_barra / 2, xb, centro + alto_barra / 2),
                fill=PALETA[j % len(PALETA)],
            )
            texto = f"{valor:.0f}"
            if xb - xa > _ancho_texto(texto, 15) + 8:
                _texto(
                    dibujo,
                    (int((xa + xb) / 2 - _ancho_texto(texto, 15) / 2), int(centro) - 10),
                    texto,
                    FONDO,
                    15,
                )
            acumulado += valor
        total = f"{totales[i]:.0f} s"
        _texto(dibujo, (int(x_de(acumulado)) + 10, int(centro) - 12), total, TINTA, 19)
    _leyenda(dibujo, nombres, ALTO - 50)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    imagen.save(ruta, "PNG", optimize=True)
    return ruta


def dispersion(
    puntos: Sequence[tuple[str, float, float]],
    titulo: str,
    eje_x: str,
    eje_y: str,
    ruta: Path,
    *,
    subtitulo: str = "",
    y_rango: tuple[float, float] | None = None,
) -> Path:
    """Puntos (etiqueta, x, y) con su etiqueta al lado."""
    imagen = Image.new("RGB", (ANCHO, ALTO), FONDO)
    dibujo = ImageDraw.Draw(imagen)
    _encabezado(dibujo, titulo, subtitulo)
    xs = [x for _, x, _ in puntos] or [0.0, 1.0]
    ys = [y for _, _, y in puntos] or [0.0, 1.0]
    x_max = max(xs) * 1.2 or 1.0
    y_min, y_max = y_rango or (min(ys) - 0.1, max(ys) + 0.1)
    if y_max <= y_min:
        y_max = y_min + 1.0
    x0, x1 = MARGEN_IZQ, ANCHO - MARGEN_DER - 160
    y0, y1 = ALTO - MARGEN_INF, MARGEN_SUP + 20

    def xy(x: float, y: float) -> tuple[float, float]:
        return (
            x0 + (x / x_max) * (x1 - x0),
            y0 - (y - y_min) / (y_max - y_min) * (y0 - y1),
        )

    paso_y = _paso_rejilla(y_max - y_min)
    marca = math.ceil(y_min / paso_y) * paso_y
    while marca <= y_max + 1e-9:
        _, y = xy(0, marca)
        dibujo.line((x0, y, x1, y), fill=REJILLA, width=1)
        etiqueta = f"{marca:.2f}"
        _texto(dibujo, (x0 - 12 - _ancho_texto(etiqueta, 17), int(y) - 11), etiqueta, TENUE, 17)
        marca += paso_y
    paso_x = _paso_rejilla(x_max)
    marca = 0.0
    while marca <= x_max + 1e-9:
        x, _ = xy(marca, y_min)
        dibujo.line((x, y0, x, y1), fill=REJILLA, width=1)
        etiqueta = f"{marca:.0f}"
        _texto(dibujo, (int(x - _ancho_texto(etiqueta, 17) / 2), y0 + 8), etiqueta, TENUE, 17)
        marca += paso_x
    _texto(dibujo, (int(x1 - _ancho_texto(eje_x, 17)), y0 + 34), eje_x, TENUE, 17)
    _texto(dibujo, (12, MARGEN_SUP - 10), eje_y, TENUE, 17)
    dibujo.line((x0, y0, x1, y0), fill=TINTA, width=2)
    dibujo.line((x0, y0, x0, y1), fill=TINTA, width=2)
    for indice, (etiqueta, x, y) in enumerate(puntos):
        px, py = xy(x, y)
        color = PALETA[indice % len(PALETA)]
        dibujo.ellipse((px - 11, py - 11, px + 11, py + 11), fill=color)
        _texto(dibujo, (int(px) + 18, int(py) - 13), etiqueta, TINTA, 19)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    imagen.save(ruta, "PNG", optimize=True)
    return ruta
