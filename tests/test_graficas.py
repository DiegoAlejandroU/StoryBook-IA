"""Tarea 6.3: gráficas del informe (Pillow) a partir de results.csv, con datos falsos."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image

from storybook.evaluation.graficas import ALTO, ANCHO, barras_agrupadas, barras_apiladas, dispersion

RAIZ = Path(__file__).resolve().parents[1]


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gi", RAIZ / "scripts" / "graficas_informe.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _png(ruta: Path) -> tuple[int, int]:
    with Image.open(ruta) as imagen:
        assert imagen.format == "PNG"
        return imagen.size


def test_tres_tipos_de_grafica(tmp_path: Path) -> None:
    rutas = [
        barras_agrupadas(
            ["Terror", "Fantasía"],
            {"C1": [0.5, None], "C3": [0.8, 0.73]},  # un valor faltante no rompe la gráfica
            "Consistencia",
            "CLIP",
            tmp_path / "a.png",
            y_max=1.0,
        ),
        barras_apiladas(
            ["Terror", "Fantasía"],
            {"Texto": [90.0, 76.0], "Imágenes": [65.0, 26.0]},
            "Tiempos",
            "segundos",
            tmp_path / "b.png",
        ),
        dispersion(
            [("C1", 17.0, 0.5), ("C3", 27.0, 0.77)], "Costo", "s", "CLIP", tmp_path / "c.png"
        ),
        dispersion([("único", 0.0, 0.5)], "Un punto en x = 0", "s", "CLIP", tmp_path / "d.png"),
    ]
    assert all(_png(r) == (ANCHO, ALTO) for r in rutas)


def _fila(bateria: str, indice: int, genero: str, configuracion: str, **valores: str) -> dict:
    return {
        "id": f"{bateria}_{indice}_{configuracion}",
        "genero": genero,
        "configuracion": configuracion,
        **valores,
    }


@pytest.fixture
def filas() -> list[dict[str, str]]:
    vieja = [_fila("20261101_090000", 1, "terror", "c3_ipadapter", clip_img_img_media="0.1")]
    nueva = []
    for indice, genero in ((1, "terror"), (2, "fantasía")):
        for configuracion, clip in (
            ("c3_ipadapter", "0.8"),
            ("c1_baseline", "0.5"),
            ("c2_bible", "0.6"),
            ("calidad", "0.78"),
        ):
            tiempos = {"t_llm_s": "75", "t_voz_s": "9", "t_sonido_s": "12", "t_mezcla_s": "2"}
            nueva.append(
                _fila(
                    "20261111_111458",
                    indice,
                    genero,
                    configuracion,
                    clip_img_img_media=clip,
                    clip_img_txt_media="0.33",
                    t_imagen_s="55" if configuracion == "calidad" else "27",
                    **(tiempos if configuracion == "c3_ipadapter" else {}),
                )
            )
    return vieja + nueva


def test_filas_de_bateria(filas: list[dict[str, str]]) -> None:
    gi = _modulo()
    bateria, elegidas = gi.filas_de_bateria(filas)
    assert bateria == "20261111_111458" and len(elegidas) == 8
    assert len(gi.filas_de_bateria(filas, "20261101_090000")[1]) == 1
    with pytest.raises(ValueError, match="no tiene filas"):
        gi.filas_de_bateria([])
    with pytest.raises(ValueError, match="No hay filas"):
        gi.filas_de_bateria(filas, "19990101_000000")


def test_graficas_del_informe(filas: list[dict[str, str]], tmp_path: Path) -> None:
    gi = _modulo()
    bateria, elegidas = gi.filas_de_bateria(filas)
    audioldm = {
        "bateria": bateria,
        "resumen": [
            {
                "variante": "base",
                "escenas": 20,
                "clips": 40,
                "escenas_que_pasan": 13,
                "clips_aptos": 24,
            },
            {
                "variante": "sufijo",
                "escenas": 20,
                "clips": 40,
                "escenas_que_pasan": 20,
                "clips_aptos": 39,
            },
        ],
    }
    rutas = gi.graficas(elegidas, audioldm, tmp_path, bateria)
    assert [r.name for r in rutas] == [
        "consistencia.png",
        "pertinencia.png",
        "costo_consistencia.png",
        "tiempos_etapas.png",
        "audioldm.png",
    ]
    assert all(_png(r) == (ANCHO, ALTO) for r in rutas)
    sin_audio = gi.graficas(elegidas, None, tmp_path / "otra", bateria)
    assert len(sin_audio) == 4


def test_cli(tmp_path: Path, filas: list[dict[str, str]]) -> None:
    from storybook.evaluation.report import agregar_filas

    gi = _modulo()
    csv_ = tmp_path / "results.csv"
    agregar_filas(csv_, filas)
    codigo = gi.main(
        [
            "--resultados",
            str(csv_),
            "--audioldm",
            str(tmp_path / "no.json"),
            "--destino",
            str(tmp_path / "g"),
        ]
    )
    assert codigo == 0 and len(list((tmp_path / "g").glob("*.png"))) == 4
