"""Tarea 6.1: results.csv, resumen Markdown, hojas de contactos y batería con backends falsos."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from PIL import Image

from storybook import config
from storybook.evaluation.contact_sheet import hoja_de_contactos
from storybook.evaluation.report import (
    COLUMNAS,
    ReportError,
    agregar_filas,
    leer_resultados,
    reporte_md,
    resumir,
)
from storybook.mock import dependencias_simuladas
from storybook.pipeline import Pipeline

RAIZ = Path(__file__).resolve().parents[1]


def _modulo(nombre: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(nombre, RAIZ / "scripts" / f"{nombre}.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class PuntuadorFalso:
    def __init__(self) -> None:
        self.textos: list[str] = []

    def imagen_texto(self, imagen: Path, texto: str) -> float:
        assert imagen.is_file()
        self.textos.append(texto)
        return 0.3

    def imagen_imagen(self, rutas: list[Path]) -> dict[str, float]:
        return {"media": 0.8, "minimo": 0.7, "pares": len(rutas) * (len(rutas) - 1) // 2}


class VerificadorFalso:
    def evaluar(self, wav: Path, texto_referencia: str) -> SimpleNamespace:
        assert wav.is_file() and texto_referencia
        return SimpleNamespace(wer=0.1)


def _fila(configuracion: str, idea: str, **valores: object) -> dict[str, object]:
    return {"id": f"x_{configuracion}", "idea": idea, "genero": "terror", **valores} | {
        "configuracion": configuracion
    }


# ---------------------------------------------------------------------------------------
# results.csv y resumen
# ---------------------------------------------------------------------------------------
def test_el_encabezado_del_repositorio_coincide_con_columnas() -> None:
    with (RAIZ / "experiments" / "results.csv").open(encoding="utf-8") as archivo:
        assert tuple(next(csv.reader(archivo))) == COLUMNAS


def test_agregar_y_leer_resultados(tmp_path: Path) -> None:
    ruta = tmp_path / "results.csv"
    ruta.write_text(",".join(COLUMNAS), encoding="utf-8")  # encabezado sin salto de línea final
    agregar_filas(ruta, [_fila("c1", "Idea A", clip_img_img_media=0.61234567, t_total_s=None)])
    agregar_filas(ruta, [_fila("c3", "Idea A", clip_img_img_media=0.8, cambios="a\nb")])
    filas = leer_resultados(ruta)
    assert [f["configuracion"] for f in filas] == ["c1", "c3"]
    assert filas[0]["clip_img_img_media"] == "0.6123" and filas[0]["t_total_s"] == ""
    assert filas[1]["cambios"] == "a b"
    with pytest.raises(ReportError, match="desconocidas"):
        agregar_filas(ruta, [{"columna_rara": 1}])
    otra = tmp_path / "otra.csv"
    otra.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ReportError, match="inesperadas"):
        agregar_filas(otra, [_fila("c1", "Idea")])


def test_resumen_por_configuracion_y_reporte() -> None:
    filas = [
        _fila(
            "c1",
            "Idea A",
            clip_img_img_media="0.6",
            clip_img_img_min="0.4",
            escenas_completas="5",
            t_total_s="100",
        ),
        _fila(
            "c1",
            "Idea B",
            clip_img_img_media="0.7",
            clip_img_img_min="0.5",
            escenas_completas="4",
            t_total_s="120",
        ),
        _fila(
            "c3",
            "Idea A",
            clip_img_img_media="0.9",
            clip_img_img_min="0.8",
            escenas_completas="5",
            vram_pico_mb="3100",
            fallbacks="sonido:sa3:no_disponible",
        ),
    ]
    filas = [{k: str(v) for k, v in f.items()} for f in filas]
    c1, c3 = resumir(filas)
    assert (c1.configuracion, c1.pruebas, c1.completas) == ("c1", 2, 1)
    assert c1.clip_img_img_media == 0.65 and c1.clip_img_img_min == 0.4
    assert c1.t_total_mediana == 110 and c3.vram_pico_max == 3100
    texto = reporte_md(filas, "Prueba")
    assert "| `c3` | 1 | 1 | 0.900 |" in texto
    assert "| Idea A | terror | 0.600 | 0.900 |" in texto
    assert "| Idea B | terror | 0.700 | — |" in texto
    assert "sonido:sa3:no_disponible" in texto
    assert "Sin resultados" in reporte_md([], "Vacío")


# ---------------------------------------------------------------------------------------
# Hoja de contactos y batería
# ---------------------------------------------------------------------------------------
def test_hoja_de_contactos(tmp_path: Path) -> None:
    historia = Pipeline(config.load_config("rapido"), dependencias_simuladas(), tmp_path).generar(
        "Un faro abandonado que se enciende solo cada noche", "misterio"
    )
    (historia.carpeta / "scene_4.png").unlink()
    hoja = hoja_de_contactos(historia.carpeta)
    assert hoja.name == "contact_sheet.jpg"
    with Image.open(hoja) as imagen:
        assert imagen.format == "JPEG" and imagen.width > 1000
    with pytest.raises(FileNotFoundError):
        hoja_de_contactos(tmp_path / "vacia")


def test_bateria_con_backends_falsos(tmp_path: Path) -> None:
    exp = _modulo("run_experiment")
    puntuador = PuntuadorFalso()
    filas, hojas = exp.ejecutar_bateria(
        exp.IDEAS[:1],
        "experiments/c3_ipadapter",
        ["experiments/c1_baseline", "experiments/c2_bible", "no_existe"],
        tmp_path / "runs",
        dependencias=dependencias_simuladas(),
        puntuador=lambda: puntuador,
        verificador=VerificadorFalso,
        id_experimento="exp",
    )
    completa, c1, c2, rota = filas
    assert [f["id"] for f in filas] == [
        "exp_1_c3_ipadapter",
        "exp_1_c1_baseline",
        "exp_1_c2_bible",
        "exp_1_no_existe",
    ]
    assert completa["escenas_completas"] == 5 and completa["wer_medio"] == 0.1
    assert completa["clip_img_img_media"] == 0.8 and completa["clip_img_txt_media"] == 0.3
    assert completa["t_llm_s"] is not None and "IP-Adapter 0.4" in completa["imagen"]
    assert c1["seed_base"] == "aleatoria" and "sin Bible" in c1["imagen"]
    assert c2["seed_base"] == 1234 and "IP-Adapter" not in c2["imagen"]
    assert c1["escenas_completas"] == 5 and "t_llm_s" not in c1
    assert c1["cambios"] == "solo imágenes, con el texto de exp_1_c3_ipadapter"
    assert rota["escenas_completas"] == 0 and "no_existe" in rota["fallos"]
    assert len(puntuador.textos) == 15  # 5 prompts por cada una de las 3 pruebas válidas
    assert len(hojas) == 3 and all(h.is_file() for h in hojas)

    carpeta_c1 = tmp_path / "runs" / "c1_baseline"
    (variante,) = list(carpeta_c1.iterdir())
    assert (variante / "story.json").is_file() and (variante / "manifest.json").is_file()

    csv_ = tmp_path / "results.csv"
    agregar_filas(csv_, filas)
    assert len(leer_resultados(csv_)) == 4
    resumen = exp.guardar_evidencias(filas, hojas, "exp", tmp_path / "evidencias")
    texto = resumen.read_text(encoding="utf-8")
    assert "`c1_baseline`" in texto and "f6_hojas/exp_" in texto
    assert len(list((tmp_path / "evidencias" / "f6_hojas").glob("*.jpg"))) == 3


def test_cli_hoja_de_contactos(tmp_path: Path) -> None:
    cli = _modulo("make_contact_sheet")
    historia = Pipeline(config.load_config("rapido"), dependencias_simuladas(), tmp_path).generar(
        "El último dragón vive escondido en una biblioteca", "fantasia"
    )
    assert cli.main([str(historia.carpeta), "--destino", str(tmp_path / "h.jpg")]) == 0
    assert (tmp_path / "h.jpg").is_file()


def test_hoja_sin_fuentes_del_sistema_quita_tildes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from storybook.evaluation import contact_sheet

    monkeypatch.setattr(contact_sheet, "FUENTES_SISTEMA", ("no_existe.ttf",))
    contact_sheet._fuente.cache_clear()
    try:
        assert contact_sheet._fuente(15)[1] is False
        historia = Pipeline(
            config.load_config("rapido"), dependencias_simuladas(), tmp_path
        ).generar("Un faro abandonado que se enciende solo cada noche", "misterio")
        assert hoja_de_contactos(historia.carpeta).is_file()
    finally:
        contact_sheet._fuente.cache_clear()
