"""Resultados de los experimentos (tarea 6.1): ``experiments/results.csv`` y su resumen.

Una fila por historia y configuración. Las columnas son las de CLAUDE.md §13:
identificación, reproducibilidad, rendimiento, calidad (CLIP, WER y la lista 1-5 de las
4 dimensiones del enunciado, que se llena a mano) y seguimiento.

Uso (resumen en Markdown de un CSV ya escrito):
    uv run python -m storybook.evaluation.report experiments/results.csv
"""

from __future__ import annotations

import csv
import statistics
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

COLUMNAS: Final = (
    "id",
    "fecha",
    "idea",
    "genero",
    "configuracion",
    "perfil",
    "llm",
    "imagen",
    "voz",
    "sonido",
    "seed_base",
    "t_llm_s",
    "t_imagen_s",
    "t_voz_s",
    "t_sonido_s",
    "t_mezcla_s",
    "t_total_s",
    "vram_pico_mb",
    "clip_img_img_media",
    "clip_img_img_min",
    "clip_img_txt_media",
    "wer_medio",
    "narrativa_1a5",
    "visual_1a5",
    "audio_1a5",
    "funcionamiento_1a5",
    "escenas_completas",
    "fallbacks",
    "fallos",
    "cambios",
)


class ReportError(Exception):
    """CSV con columnas inesperadas o fila inválida."""


def leer_resultados(ruta: Path) -> list[dict[str, str]]:
    if not ruta.is_file() or not ruta.read_text(encoding="utf-8").strip():
        return []
    with ruta.open(encoding="utf-8", newline="") as archivo:
        lector = csv.DictReader(archivo)
        if tuple(lector.fieldnames or ()) != COLUMNAS:
            raise ReportError(f"Columnas inesperadas en {ruta}: {lector.fieldnames}")
        return list(lector)


def _celda(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float):
        return f"{valor:.4f}".rstrip("0").rstrip(".")
    return str(valor).replace("\r", " ").replace("\n", " ")


def agregar_filas(ruta: Path, filas: Iterable[Mapping[str, Any]]) -> int:
    """Agrega filas al CSV (lo crea con el encabezado si no existe). Devuelve cuántas."""
    filas = list(filas)
    for fila in filas:
        sobrantes = set(fila) - set(COLUMNAS)
        if sobrantes:
            raise ReportError(f"Columnas desconocidas: {sorted(sobrantes)}")
    texto = ruta.read_text(encoding="utf-8") if ruta.is_file() else ""
    existente = bool(texto.strip())
    if existente:
        leer_resultados(ruta)  # valida el encabezado antes de escribir
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a" if existente else "w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, lineterminator="\n")
        if not existente:
            escritor.writeheader()
        elif not texto.endswith("\n"):
            archivo.write("\n")
        for fila in filas:
            escritor.writerow({c: _celda(fila.get(c)) for c in COLUMNAS})
    return len(filas)


def numero(valor: Any) -> float | None:
    try:
        return float(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _media(valores: Sequence[float | None]) -> float | None:
    limpios = [v for v in valores if v is not None]
    return round(statistics.mean(limpios), 4) if limpios else None


def _mediana(valores: Sequence[float | None]) -> float | None:
    limpios = [v for v in valores if v is not None]
    return round(statistics.median(limpios), 2) if limpios else None


@dataclass(frozen=True)
class ResumenConfiguracion:
    configuracion: str
    pruebas: int
    completas: int  # pruebas con las 5 escenas
    t_total_mediana: float | None
    t_imagen_mediana: float | None
    vram_pico_max: float | None
    clip_img_img_media: float | None
    clip_img_img_min: float | None  # el peor par de imágenes de todas las pruebas
    clip_img_txt_media: float | None
    wer_medio: float | None


def resumir(filas: Sequence[Mapping[str, str]]) -> list[ResumenConfiguracion]:
    """Resumen por configuración, en el orden en que aparecen en las filas."""
    grupos: dict[str, list[Mapping[str, str]]] = {}
    for fila in filas:
        grupos.setdefault(fila["configuracion"], []).append(fila)
    resumenes = []
    for nombre, grupo in grupos.items():

        def col(columna: str, g: list[Mapping[str, str]] = grupo) -> list[float | None]:
            return [numero(f.get(columna)) for f in g]

        minimos = [v for v in col("clip_img_img_min") if v is not None]
        vram = [v for v in col("vram_pico_mb") if v is not None]
        resumenes.append(
            ResumenConfiguracion(
                configuracion=nombre,
                pruebas=len(grupo),
                completas=sum(1 for v in col("escenas_completas") if v == 5),
                t_total_mediana=_mediana(col("t_total_s")),
                t_imagen_mediana=_mediana(col("t_imagen_s")),
                vram_pico_max=max(vram) if vram else None,
                clip_img_img_media=_media(col("clip_img_img_media")),
                clip_img_img_min=round(min(minimos), 4) if minimos else None,
                clip_img_txt_media=_media(col("clip_img_txt_media")),
                wer_medio=_media(col("wer_medio")),
            )
        )
    return resumenes


def _f(valor: float | None, decimales: int = 3, sufijo: str = "") -> str:
    return "—" if valor is None else f"{valor:.{decimales}f}{sufijo}"


def tabla_resumen(resumenes: Sequence[ResumenConfiguracion]) -> str:
    lineas = [
        "| Configuración | Pruebas | Con 5 escenas | CLIP img-img (media) | CLIP img-img (mín.) "
        "| CLIP img-texto | WER | Imágenes (mediana) | Total (mediana) | VRAM pico |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in resumenes:
        lineas.append(
            f"| `{r.configuracion}` | {r.pruebas} | {r.completas} | {_f(r.clip_img_img_media)} "
            f"| {_f(r.clip_img_img_min)} | {_f(r.clip_img_txt_media)} | {_f(r.wer_medio)} "
            f"| {_f(r.t_imagen_mediana, 1, ' s')} | {_f(r.t_total_mediana, 1, ' s')} "
            f"| {_f(r.vram_pico_max, 0, ' MB')} |"
        )
    return "\n".join(lineas)


def tabla_por_historia(filas: Sequence[Mapping[str, str]], columna: str) -> str:
    """Una fila por idea y una columna por configuración con el valor de ``columna``."""
    configuraciones = list(dict.fromkeys(f["configuracion"] for f in filas))
    ideas = list(dict.fromkeys((f["idea"], f["genero"]) for f in filas))
    valores = {(f["idea"], f["configuracion"]): numero(f.get(columna)) for f in filas}
    lineas = [
        "| Idea | Género | " + " | ".join(f"`{c}`" for c in configuraciones) + " |",
        "|---|---|" + "---|" * len(configuraciones),
    ]
    for idea, genero in ideas:
        celdas = " | ".join(_f(valores.get((idea, c))) for c in configuraciones)
        lineas.append(f"| {idea[:60]} | {genero} | {celdas} |")
    return "\n".join(lineas)


def reporte_md(filas: Sequence[Mapping[str, str]], titulo: str = "Resultados") -> str:
    if not filas:
        return f"# {titulo}\n\nSin resultados.\n"
    partes = [
        f"# {titulo}",
        "",
        "## Resumen por configuración",
        "",
        tabla_resumen(resumir(filas)),
        "",
        "- CLIP img-img: similitud coseno media entre las 5 ilustraciones de una historia "
        "(consistencia visual). El mínimo es el par menos parecido.",
        "- CLIP img-texto: similitud entre cada ilustración y su prompt (pertinencia).",
        "- WER: error de palabras de Whisper small sobre la narración (inteligibilidad).",
        "",
        "## Consistencia visual por historia (CLIP img-img, media)",
        "",
        tabla_por_historia(filas, "clip_img_img_media"),
        "",
        "## Pertinencia por historia (CLIP img-texto, media)",
        "",
        tabla_por_historia(filas, "clip_img_txt_media"),
        "",
    ]
    con_avisos = [f for f in filas if f.get("fallos") or f.get("fallbacks")]
    if con_avisos:
        partes += ["## Fallos y alternativas automáticas", ""]
        for f in con_avisos:
            detalle = "; ".join(x for x in (f.get("fallos"), f.get("fallbacks")) if x)
            partes.append(f"- `{f['id']}`: {detalle}")
        partes.append("")
    return "\n".join(partes)


def main(argv: list[str] | None = None) -> int:
    argumentos = argv if argv is not None else sys.argv[1:]
    ruta = Path(argumentos[0]) if argumentos else Path("experiments/results.csv")
    sys.stdout.write(reporte_md(leer_resultados(ruta), f"Resultados de {ruta.name}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
