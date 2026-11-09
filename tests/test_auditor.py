"""Tests del auditor de coherencia con un LLM falso."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from storybook.config import LLMConfig
from storybook.schemas import AuditoriaCoherencia, Escena, StoryBible
from storybook.story.auditor import Auditor, AuditorError, reemplazar_escena
from storybook.story.llm_client import LLMValidationError
from tests.fake_llm import FakeLLM

CFG = LLMConfig(model="qwen3:4b", seed=42, max_rondas_auditor=1)

COHERENTE = {"coherente": True, "contradicciones": []}


def con_critica(escena: int, tipo: str = "nombre") -> dict[str, Any]:
    return {
        "coherente": False,
        "contradicciones": [
            {
                "escena": escena,
                "tipo": tipo,
                "severidad": "critica",
                "descripcion": "La protagonista aparece como Lucila en vez de Lucía.",
            },
            {
                "escena": 2,
                "tipo": "rasgo",
                "severidad": "menor",
                "descripcion": "Las gafas no se mencionan en esta escena.",
            },
        ],
    }


@pytest.fixture
def bible(bible_dict: dict) -> StoryBible:
    return StoryBible.model_validate(bible_dict).con_seeds(1234)


def escena_nueva(bible_dict: dict, numero: int) -> dict[str, Any]:
    e = copy.deepcopy(bible_dict["escenas"][numero - 1])
    e["resumen"] = f"Versión corregida de la escena {numero}."
    e["hechos_nuevos"] = [f"Hecho corregido de la escena {numero}."]
    e["personajes_presentes"] = ["lucia"]  # el auditor debe restaurar los originales
    return e


def test_bible_coherente_no_regenera(bible: StoryBible) -> None:
    llm = FakeLLM().encolar(AuditoriaCoherencia, COHERENTE)
    resultado = Auditor(llm, CFG).auditar_y_corregir(bible)
    assert resultado.bible is bible
    assert resultado.escenas_regeneradas == []
    assert resultado.coherente_final is True
    assert len(llm.llamadas) == 1
    assert llm.llamadas[0]["temperature"] == CFG.temperature_auditor


def test_contradiccion_menor_no_regenera(bible: StoryBible) -> None:
    menor = con_critica(3)
    menor["contradicciones"] = menor["contradicciones"][1:]
    llm = FakeLLM().encolar(AuditoriaCoherencia, menor)
    resultado = Auditor(llm, CFG).auditar_y_corregir(bible)
    assert resultado.escenas_regeneradas == []
    assert resultado.coherente_final is True


def test_critica_regenera_solo_la_escena_afectada(bible: StoryBible, bible_dict: dict) -> None:
    llm = (
        FakeLLM()
        .encolar(AuditoriaCoherencia, con_critica(3), COHERENTE)
        .encolar(Escena, escena_nueva(bible_dict, 3))
    )
    resultado = Auditor(llm, CFG).auditar_y_corregir(bible)

    assert resultado.escenas_regeneradas == [3]
    assert resultado.coherente_final is True
    nueva = resultado.bible
    assert nueva.escena(3).resumen == "Versión corregida de la escena 3."
    for n in (1, 2, 4, 5):
        assert nueva.escena(n) == bible.escena(n)
    # Se conservan personajes, seeds y el canon se recalcula.
    assert nueva.escena(3).personajes_presentes == bible.escena(3).personajes_presentes
    assert nueva.escena(3).seed_imagen == bible.escena(3).seed_imagen
    assert nueva.personajes == bible.personajes
    assert "Hecho corregido de la escena 3." in nueva.canon
    assert "Hecho establecido en la escena 3 sobre el faro." not in nueva.canon
    assert nueva.canon[0] == "El faro lleva veinte años apagado."
    # El prompt de regeneración incluye la contradicción y la escena actual.
    prompt = llm.llamadas_de(Escena)[0]["messages"][1]["content"]
    assert "Lucila" in prompt and "Escena 3 actual" in prompt
    assert "[rasgo]" not in prompt  # las menores no se envían
    assert [r.etapa for r in resultado.llamadas] == [
        "auditoria",
        "regenerar_escena_3",
        "auditoria",
    ]
    d = resultado.a_dict()
    assert d["rondas"] == 2 and d["escenas_regeneradas"] == [3]


def test_respeta_max_rondas(bible: StoryBible, bible_dict: dict) -> None:
    llm = (
        FakeLLM()
        .encolar(AuditoriaCoherencia, con_critica(4), con_critica(4))
        .encolar(Escena, escena_nueva(bible_dict, 4))
    )
    resultado = Auditor(llm, CFG).auditar_y_corregir(bible, max_rondas=1)
    assert resultado.coherente_final is False
    assert len(resultado.auditorias) == 2
    assert len(llm.llamadas_de(Escena)) == 1


def test_cero_rondas_solo_audita(bible: StoryBible) -> None:
    llm = FakeLLM().encolar(AuditoriaCoherencia, con_critica(2))
    resultado = Auditor(llm, CFG).auditar_y_corregir(bible, max_rondas=0)
    assert resultado.coherente_final is False
    assert resultado.escenas_regeneradas == []


def test_fallo_al_regenerar_conserva_la_escena(bible: StoryBible) -> None:
    llm = (
        FakeLLM()
        .encolar(AuditoriaCoherencia, con_critica(5), con_critica(5))
        .encolar(Escena, LLMValidationError("inválida", [["x"]]))
    )
    resultado = Auditor(llm, CFG).auditar_y_corregir(bible)
    assert resultado.bible.escena(5) == bible.escena(5)
    assert resultado.escenas_regeneradas == []
    assert resultado.errores and "escena 5" in resultado.errores[0]


def test_reemplazar_escena_numero_y_fase_los_fija_la_bible(
    bible: StoryBible, bible_dict: dict
) -> None:
    e = escena_nueva(bible_dict, 2)
    nueva = reemplazar_escena(bible, Escena.model_validate(e))
    assert nueva.escena(2).fase == bible.escena(2).fase
    assert nueva.escena(2).personajes_presentes == bible.escena(2).personajes_presentes


def test_reemplazar_escena_que_rompe_la_bible(bible: StoryBible, bible_dict: dict) -> None:
    # Si la Bible de partida ya no cumple las reglas de reparto (protagonista fuera de la
    # escena 1), el reemplazo no puede revalidarse y se informa con AuditorError.
    e = Escena.model_validate(escena_nueva(bible_dict, 1))
    rota = bible.model_copy(deep=True)
    rota.escenas[0].personajes_presentes = ["abuelo_tomas"]
    with pytest.raises(AuditorError):
        reemplazar_escena(rota, e)
