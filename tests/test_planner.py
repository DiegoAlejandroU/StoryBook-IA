"""Tests del planificador (estrategias a y b) con un LLM falso."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from storybook.config import LLMConfig
from storybook.schemas import Escena, PlanHistoria, StoryBible, StoryRequest, validar_entrada
from storybook.story.llm_client import LLMValidationError
from storybook.story.planner import Planificador, PlannerError, alinear_escena_con_plan
from tests.fake_llm import FakeLLM

CFG = LLMConfig(model="qwen3:4b-instruct-2507-q4_K_M", seed=42, num_ctx=8192)


@pytest.fixture
def solicitud() -> StoryRequest:
    return validar_entrada("Una niña investiga por qué el faro del pueblo se apagó", "misterio")


@pytest.fixture
def plan_dict(bible_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "titulo": bible_dict["titulo"],
        "genero": bible_dict["genero"],
        "tono": bible_dict["tono"],
        "estilo_visual": bible_dict["estilo_visual"],
        "escenario": bible_dict["escenario"],
        "personajes": bible_dict["personajes"],
        "plan_escenas": [
            {
                "numero": e["numero"],
                "fase": e["fase"],
                "resumen": e["resumen"],
                "personajes_presentes": e["personajes_presentes"],
            }
            for e in bible_dict["escenas"]
        ],
        "canon_inicial": ["El faro lleva veinte años apagado."],
    }


def escenas_de(bible_dict: dict[str, Any]) -> list[dict[str, Any]]:
    escenas = copy.deepcopy(bible_dict["escenas"])
    for e in escenas:
        e["hechos_nuevos"] = [f"Hecho único de la escena {e['numero']} en el faro."]
    return escenas


def test_estrategia_una_llamada(solicitud: StoryRequest, bible_dict: dict) -> None:
    llm = FakeLLM().encolar(StoryBible, bible_dict)
    resultado = Planificador(llm, CFG).generar(solicitud, "una_llamada")
    assert resultado.estrategia == "una_llamada"
    assert len(resultado.bible.escenas) == 5
    assert [r.etapa for r in resultado.llamadas] == ["bible"]
    llamada = llm.llamadas[0]
    assert llamada["temperature"] == CFG.temperature_narrativa
    assert llamada["num_ctx"] == 8192
    assert llamada["think"] is False
    assert llamada["max_reintentos"] == CFG.max_reintentos
    assert "misterio" in llamada["messages"][1]["content"]


def test_estrategia_por_defecto_viene_de_config(solicitud: StoryRequest, bible_dict: dict) -> None:
    llm = FakeLLM().encolar(StoryBible, bible_dict)
    assert Planificador(llm, CFG).generar(solicitud).estrategia == CFG.estrategia


def test_estrategia_por_etapas(solicitud: StoryRequest, bible_dict: dict, plan_dict: dict) -> None:
    llm = FakeLLM().encolar(PlanHistoria, plan_dict).encolar(Escena, *escenas_de(bible_dict))
    resultado = Planificador(llm, CFG).generar(solicitud, "por_etapas")

    assert resultado.estrategia == "por_etapas"
    assert [r.etapa for r in resultado.llamadas] == [
        "plan",
        *(f"escena_{n}" for n in range(1, 6)),
    ]
    assert resultado.intentos_totales == 6
    bible = resultado.bible
    assert [e.numero for e in bible.escenas] == [1, 2, 3, 4, 5]
    assert bible.canon[0] == "El faro lleva veinte años apagado."
    assert len(bible.canon) == 6

    # Cada escena recibe el canon acumulado y los resúmenes de las anteriores.
    llamadas_escena = llm.llamadas_de(Escena)
    texto_3 = llamadas_escena[2]["messages"][1]["content"]
    assert "Escena 1:" in texto_3 and "Escena 2:" in texto_3
    assert "Hecho único de la escena 2" in texto_3
    assert "Hecho único de la escena 3" not in texto_3
    assert "(ninguna, es la primera)" in llamadas_escena[0]["messages"][1]["content"]
    # Seeds deterministas y distintas por escena.
    seeds = [c["seed"] for c in llamadas_escena]
    assert len(set(seeds)) == 5


def test_por_etapas_corrige_numero_fase_y_personajes(
    solicitud: StoryRequest, bible_dict: dict, plan_dict: dict
) -> None:
    escenas = escenas_de(bible_dict)
    # El "LLM" devuelve todas como escena 1 y con solo la protagonista.
    for e in escenas:
        e["numero"], e["fase"], e["personajes_presentes"] = 1, "inicio", ["lucia"]
    llm = FakeLLM().encolar(PlanHistoria, plan_dict).encolar(Escena, *escenas)
    bible = Planificador(llm, CFG).generar(solicitud, "por_etapas").bible
    assert [e.numero for e in bible.escenas] == [1, 2, 3, 4, 5]
    assert [e.fase.value for e in bible.escenas] == [
        "inicio",
        "desarrollo",
        "desarrollo",
        "climax",
        "desenlace",
    ]
    assert bible.escena(1).personajes_presentes == ["lucia", "abuelo_tomas"]


def test_alinear_no_cambia_escena_correcta(bible_dict: dict, plan_dict: dict) -> None:
    plan = PlanHistoria.model_validate(plan_dict)
    escena = Escena.model_validate(bible_dict["escenas"][1])
    assert alinear_escena_con_plan(escena, plan, 2) is escena


def test_error_de_validacion_del_llm_se_propaga(solicitud: StoryRequest) -> None:
    llm = FakeLLM().encolar(StoryBible, LLMValidationError("inválido", [["x"]]))
    with pytest.raises(LLMValidationError):
        Planificador(llm, CFG).generar(solicitud, "una_llamada")


def test_estrategia_desconocida(solicitud: StoryRequest) -> None:
    with pytest.raises(PlannerError):
        Planificador(FakeLLM(), CFG).generar(solicitud, "tres_llamadas")  # type: ignore[arg-type]


def test_liberar_descarga_el_modelo() -> None:
    llm = FakeLLM()
    Planificador(llm, CFG).liberar()
    assert llm.descargados == [CFG.model]


def test_registro_a_dict(solicitud: StoryRequest, bible_dict: dict) -> None:
    llm = FakeLLM().encolar(StoryBible, bible_dict)
    resultado = Planificador(llm, CFG).generar(solicitud, "una_llamada")
    d = resultado.llamadas[0].a_dict()
    assert d["etapa"] == "bible" and d["intentos"] == 1 and d["output_tokens"] == 200
    assert resultado.segundos_totales >= 0


def test_config_por_defecto_incluye_estrategia_y_auditor() -> None:
    from storybook.config import load_config

    cfg = load_config("default").llm
    assert cfg.estrategia in {"una_llamada", "por_etapas"}
    assert cfg.auditar is True
    assert cfg.max_rondas_auditor >= 1
