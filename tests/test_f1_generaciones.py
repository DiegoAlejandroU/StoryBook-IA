"""Script de la tarea 1.4: ideas válidas para todos los géneros y resumen legible."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import ModuleType

from storybook.config import LLMConfig
from storybook.schemas import Genero, validar_entrada

RAIZ = Path(__file__).resolve().parents[1]


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("f1_gen", RAIZ / "scripts" / "f1_generaciones.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_ideas_validas_y_cubren_los_seis_generos() -> None:
    f1 = _modulo()
    generos = {genero for _, genero in f1.IDEAS}
    assert generos == {g.value for g in Genero} - {"otro"}
    for idea, genero in f1.IDEAS:
        validar_entrada(idea, genero)


def test_resumen_cuenta_validas() -> None:
    f1 = _modulo()
    base = dict.fromkeys(f1.COLUMNAS, "")
    filas = [
        {
            **base,
            "n": 1,
            "genero": "terror",
            "valida": True,
            "llamadas": 6,
            "intentos": 7,
            "segundos_total": 80.0,
            "tokens_por_s": 30.0,
            "fraccion_gpu": 1.0,
            "titulo": "A",
        },
        {
            **base,
            "n": 2,
            "genero": "infantil",
            "valida": False,
            "llamadas": 2,
            "intentos": 6,
            "segundos_total": 60.0,
            "tokens_por_s": 28.0,
            "fraccion_gpu": 1.0,
            "error": "X",
        },
    ]
    args = argparse.Namespace(perfil="rapido", sin_auditor=False)
    texto = f1.resumen_md(filas, args, LLMConfig(model="m"))
    assert "Story Bibles válidas: 1/2" in texto
    assert "| 2 | infantil | NO |" in texto


def test_causa_reintento_agrupa_por_campo_y_tipo() -> None:
    f1 = _modulo()
    assert (
        f1.causa_reintento(
            "personajes.0.descripcion_visual_fija: Value error, descripcion_visual_fija tiene "
            "~28 tokens CLIP y el máximo es 25"
        )
        == "personajes.descripcion_visual_fija · presupuesto CLIP"
    )
    assert (
        f1.causa_reintento("texto_narrativo: Value error, texto_narrativo tiene 70 palabras")
        == "texto_narrativo · longitud"
    )
    assert (
        f1.causa_reintento("Value error, la escena 1 usa ids de personaje inexistentes: ['lena']")
        == "(modelo) · id de personaje"
    )


def test_resumen_lista_causas_de_reintento() -> None:
    from collections import Counter

    f1 = _modulo()
    fila = {
        **dict.fromkeys(f1.COLUMNAS, ""),
        "n": 1,
        "genero": "terror",
        "valida": True,
        "llamadas": 7,
        "intentos": 9,
        "segundos_total": 70.0,
        "titulo": "La casa",
        "_causas": Counter({"texto_narrativo · longitud": 2}),
    }
    args = argparse.Namespace(perfil="rapido", sin_auditor=False)
    texto = f1.resumen_md([fila], args, LLMConfig(model="m"))
    assert "| texto_narrativo · longitud | 2 |" in texto


def test_evidencias_por_perfil_no_se_pisan() -> None:
    f1 = _modulo()
    assert f1.sufijo_evidencias("rapido") == ""
    assert f1.sufijo_evidencias("calidad") == "_calidad"


def test_generacion_fallida_registra_causas_y_ultima_salida(tmp_path: Path) -> None:
    from storybook.story.llm_client import LLMValidationError
    from tests.fake_llm import FakeLLM

    f1 = _modulo()

    class Cliente(FakeLLM):
        def gpu_fraction(self, modelo: str) -> float:
            return 1.0

    errores = [["genero: String should have at most 40 characters"]] * 4
    cliente = Cliente().encolar(
        "PlanHistoria", LLMValidationError("PlanHistoria: inválida", errores, "{...}")
    )
    cfg = LLMConfig(model="m", estrategia="por_etapas", auditar=False)
    fila = f1.generar_una(
        1, "Una casa que cambia de habitaciones", "terror", cliente, cfg, False, tmp_path
    )
    assert fila["valida"] is False
    assert fila["intentos"] == 4 and fila["llamadas"] == 1
    assert "genero · otro ×4" in fila["causas_reintento"]
    assert (tmp_path / "fallo_01.json").exists()
