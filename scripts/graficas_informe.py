"""Gráficas del informe (tarea 6.3) a partir de ``experiments/results.csv``.

Genera en ``docs/informe/graficas/``:

- ``consistencia.png``: CLIP img-img por historia y configuración;
- ``pertinencia.png``: CLIP img-texto por historia y configuración;
- ``costo_consistencia.png``: consistencia frente al tiempo de imágenes;
- ``tiempos_etapas.png``: segundos por etapa de cada historia completa (C3);
- ``audioldm.png``: la prueba de prompts de AudioLDM (si existe su JSON).

Uso (PowerShell, desde la carpeta del proyecto):
    uv run python scripts/graficas_informe.py
    uv run python scripts/graficas_informe.py --bateria 20261111_111458
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from storybook import config
from storybook.evaluation.graficas import barras_agrupadas, barras_apiladas, dispersion
from storybook.evaluation.report import leer_resultados, numero

RESULTADOS: Final = config.PROJECT_ROOT / "experiments" / "results.csv"
AUDIOLDM: Final = config.DOCS_DIR / "evidencias" / "f6_audioldm_prompts.json"
DESTINO: Final = config.DOCS_DIR / "informe" / "graficas"
ORDEN: Final = ("c1_baseline", "c2_bible", "c3_ipadapter", "calidad")
NOMBRES: Final = {
    "c1_baseline": "C1 · sin Bible",
    "c2_bible": "C2 · Bible",
    "c3_ipadapter": "C3 · Bible + IP-Adapter",
    "calidad": "C3 con 25 pasos",
}
VARIANTES_AUDIO: Final = {
    "base": "Prompt original",
    "sufijo": '+ "high quality, clear"',
    "guia_alta": "Guidance 4,0",
    "sufijo_guia": "Sufijo + guidance 4,0",
}
ETAPAS: Final = (
    ("Texto (LLM)", "t_llm_s"),
    ("Imágenes", "t_imagen_s"),
    ("Voz", "t_voz_s"),
    ("Sonido", "t_sonido_s"),
    ("Mezcla", "t_mezcla_s"),
)


def filas_de_bateria(
    filas: Sequence[Mapping[str, str]], bateria: str | None = None
) -> tuple[str, list[Mapping[str, str]]]:
    """Filas de una batería (por defecto, la de la última fila del CSV)."""
    if not filas:
        raise ValueError("results.csv no tiene filas")
    bateria = bateria or filas[-1]["id"][:15]
    elegidas = [f for f in filas if f["id"].startswith(bateria + "_")]
    if not elegidas:
        raise ValueError(f"No hay filas de la batería {bateria}")
    return bateria, elegidas


def _indice_idea(fila: Mapping[str, str]) -> int:
    return int(fila["id"].split("_")[2])


def _tabla(
    filas: Sequence[Mapping[str, str]],
) -> tuple[list[str], dict[tuple[int, str], Mapping[str, str]]]:
    generos: dict[int, str] = {}
    tabla: dict[tuple[int, str], Mapping[str, str]] = {}
    for fila in filas:
        indice = _indice_idea(fila)
        generos.setdefault(indice, fila["genero"].capitalize())
        tabla[(indice, fila["configuracion"])] = fila
    return [generos[i] for i in sorted(generos)], tabla


def graficas(
    filas: Sequence[Mapping[str, str]],
    audioldm: Mapping[str, Any] | None,
    destino: Path,
    bateria: str,
) -> list[Path]:
    generos, tabla = _tabla(filas)
    indices = sorted({i for i, _ in tabla})
    configs = [c for c in ORDEN if any((i, c) in tabla for i in indices)]

    def serie(columna: str, configuracion: str) -> list[float | None]:
        return [numero(tabla.get((i, configuracion), {}).get(columna)) for i in indices]

    nota = f"Batería {bateria} · {len(indices)} historias · RTX 3050 Laptop (4 GB)"
    rutas = [
        barras_agrupadas(
            generos,
            {NOMBRES[c]: serie("clip_img_img_media", c) for c in configs},
            "Consistencia visual entre las 5 ilustraciones",
            "CLIP img-img",
            destino / "consistencia.png",
            subtitulo=(
                "Similitud coseno media entre pares de ilustraciones (más alto = más consistente)"
            ),
            y_max=1.0,
        ),
        barras_agrupadas(
            generos,
            {NOMBRES[c]: serie("clip_img_txt_media", c) for c in configs},
            "Pertinencia de cada ilustración a su prompt",
            "CLIP img-texto",
            destino / "pertinencia.png",
            subtitulo="Similitud media entre cada ilustración y su prompt (más alto = más fiel)",
            decimales=3,
            y_max=0.5,
        ),
    ]
    puntos = []
    for c in configs:
        tiempos = [v for v in serie("t_imagen_s", c) if v is not None]
        clip = [v for v in serie("clip_img_img_media", c) if v is not None]
        if tiempos and clip:
            puntos.append((NOMBRES[c], statistics.median(tiempos), statistics.mean(clip)))
    rutas.append(
        dispersion(
            puntos,
            "Consistencia frente al tiempo de las imágenes",
            "segundos de imágenes por historia (mediana)",
            "CLIP img-img (media)",
            destino / "costo_consistencia.png",
            subtitulo=nota,
            y_rango=(0.4, 0.9),
        )
    )
    if "c3_ipadapter" in configs:
        rutas.append(
            barras_apiladas(
                generos,
                {nombre: [v or 0.0 for v in serie(col, "c3_ipadapter")] for nombre, col in ETAPAS},
                "Tiempo por etapa de cada historia completa (C3, perfil rápido)",
                "segundos",
                destino / "tiempos_etapas.png",
                subtitulo=nota,
            )
        )
    if audioldm:
        resumen = {r["variante"]: r for r in audioldm.get("resumen", [])}
        orden = [v for v in VARIANTES_AUDIO if v in resumen]
        escenas = max((r["escenas"] for r in resumen.values()), default=0)
        clips = max((r["clips"] for r in resumen.values()), default=0)
        rutas.append(
            barras_agrupadas(
                [f"Escenas con ambiente apto (de {escenas})", f"Clips aptos (de {clips})"],
                {
                    VARIANTES_AUDIO[v]: [resumen[v]["escenas_que_pasan"], resumen[v]["clips_aptos"]]
                    for v in orden
                },
                "AudioLDM: variantes de prompt y guidance",
                "cantidad",
                destino / "audioldm.png",
                subtitulo=(
                    f"Prompts de la batería {audioldm.get('bateria', '')} · 2 seeds por escena · "
                    "apto = nivel ≥ −45 dBFS y < 40 % del clip en silencio"
                ),
                decimales=0,
            )
        )
    return rutas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--resultados", type=Path, default=RESULTADOS)
    parser.add_argument("--audioldm", type=Path, default=AUDIOLDM)
    parser.add_argument("--destino", type=Path, default=DESTINO)
    parser.add_argument("--bateria")
    args = parser.parse_args(argv)
    bateria, filas = filas_de_bateria(leer_resultados(args.resultados), args.bateria)
    audioldm = (
        json.loads(args.audioldm.read_text(encoding="utf-8")) if args.audioldm.is_file() else None
    )
    for ruta in graficas(filas, audioldm, args.destino, bateria):
        sys.stdout.write(f"{ruta}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
