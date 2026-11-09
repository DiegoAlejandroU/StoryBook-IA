"""Pruebas de la Story Bible: las garantías se imponen por esquema, no por el LLM."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from pydantic import ValidationError

from storybook.schemas import (
    NUM_ESCENAS,
    AuditoriaCoherencia,
    PlanHistoria,
    StoryBible,
    contar_palabras,
    derivar_seed,
    esquema_json_llm,
    estimar_tokens_clip,
)
from tests.conftest import escena_dict, texto_narrativo


def test_bible_valida(bible_dict: dict[str, Any]) -> None:
    bible = StoryBible.model_validate(bible_dict)
    assert len(bible.escenas) == NUM_ESCENAS
    assert bible.protagonista().id == "lucia"
    assert bible.estilo_visual.prompt().startswith("watercolor")


@pytest.mark.parametrize("cantidad", [4, 6])
def test_exactamente_cinco_escenas(bible_dict: dict[str, Any], cantidad: int) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["escenas"] = [escena_dict(min(i, 5)) for i in range(1, cantidad + 1)]
    with pytest.raises(ValidationError):
        StoryBible.model_validate(datos)


def test_numeracion_en_orden(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["escenas"][0], datos["escenas"][1] = datos["escenas"][1], datos["escenas"][0]
    with pytest.raises(ValidationError, match="numeradas"):
        StoryBible.model_validate(datos)


def test_fase_debe_coincidir_con_numero(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["escenas"][3]["fase"] = "desarrollo"  # la escena 4 es el clímax
    with pytest.raises(ValidationError, match="climax"):
        StoryBible.model_validate(datos)


@pytest.mark.parametrize("palabras", [40, 220])
def test_longitud_texto_narrativo(bible_dict: dict[str, Any], palabras: int) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["escenas"][2]["texto_narrativo"] = texto_narrativo(palabras)
    with pytest.raises(ValidationError, match="palabras"):
        StoryBible.model_validate(datos)


def test_personaje_inexistente(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["escenas"][1]["personajes_presentes"] = ["lucia", "fantasma"]
    with pytest.raises(ValidationError, match="inexistentes"):
        StoryBible.model_validate(datos)


def test_un_solo_protagonista(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["personajes"][1]["rol"] = "protagonista"
    with pytest.raises(ValidationError, match="exactamente 1 protagonista"):
        StoryBible.model_validate(datos)


def test_protagonista_en_suficientes_escenas(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    for numero in (2, 3, 4):
        datos["escenas"][numero - 1]["personajes_presentes"] = ["abuelo_tomas"]
    with pytest.raises(ValidationError, match="mínimo 3"):
        StoryBible.model_validate(datos)


def test_campos_visuales_en_ingles(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["escenas"][0]["prompt_imagen"] = "niña caminando hacia el faro"
    with pytest.raises(ValidationError, match="inglés"):
        StoryBible.model_validate(datos)


def test_presupuesto_tokens_prompt_imagen(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["escenas"][0]["prompt_imagen"] = ", ".join(
        ["old stone lighthouse"] * 7
    )  # ~27 tokens, <200 caracteres
    with pytest.raises(ValidationError, match="tokens CLIP"):
        StoryBible.model_validate(datos)


def test_etiqueta_de_sonido_fuera_de_vocabulario(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["escenas"][0]["etiquetas_sonido"] = ["explosion"]
    with pytest.raises(ValidationError):
        StoryBible.model_validate(datos)


def test_canon_acumula_hechos(bible_dict: dict[str, Any]) -> None:
    bible = StoryBible.model_validate(bible_dict)
    assert bible.canon[0] == "El faro lleva veinte años apagado."
    for escena in bible.escenas:
        assert all(h in bible.canon for h in escena.hechos_nuevos)
    previos = bible.canon_hasta(3)
    assert "Hecho establecido en la escena 2 sobre el faro." in previos
    assert "Hecho establecido en la escena 3 sobre el faro." not in previos
    assert len(bible.resumenes_previos(3)) == 2


def test_seeds_deterministas(bible_dict: dict[str, Any]) -> None:
    bible = StoryBible.model_validate(bible_dict)
    a = bible.con_seeds(1234)
    b = bible.con_seeds(1234)
    c = bible.con_seeds(999)
    assert [p.seed for p in a.personajes] == [p.seed for p in b.personajes]
    assert a.protagonista().seed != c.protagonista().seed
    assert {e.seed_imagen for e in a.escenas} == {a.protagonista().seed}
    por_escena = bible.con_seeds(1234, politica="por_escena")
    assert len({e.seed_imagen for e in por_escena.escenas}) == NUM_ESCENAS
    assert bible.protagonista().seed is None  # la original no se modifica


def test_derivar_seed_rango() -> None:
    assert 0 <= derivar_seed(1, "x") < 2**32
    assert derivar_seed(1, "x") == derivar_seed(1, "x")


def test_esquema_llm_sin_refs_ni_seeds() -> None:
    esquema = esquema_json_llm(StoryBible)
    texto = json.dumps(esquema)
    assert "$ref" not in texto and "$defs" not in texto
    assert '"seed"' not in texto and "seed_imagen" not in texto
    escenas = esquema["properties"]["escenas"]
    assert escenas["minItems"] == NUM_ESCENAS == escenas["maxItems"]


def test_roundtrip_json(bible_dict: dict[str, Any]) -> None:
    bible = StoryBible.model_validate(bible_dict).con_seeds(7)
    recargada = StoryBible.model_validate_json(bible.model_dump_json())
    assert recargada == bible


def test_plan_historia(bible_dict: dict[str, Any]) -> None:
    plan = PlanHistoria.model_validate(
        {
            **{
                k: bible_dict[k]
                for k in ("titulo", "genero", "tono", "estilo_visual", "escenario", "personajes")
            },
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
    )
    escenas = StoryBible.model_validate(bible_dict).escenas
    bible = StoryBible.desde_plan(plan, escenas)
    assert bible.titulo == plan.titulo
    assert bible.canon[0] == "El faro lleva veinte años apagado."


def test_auditoria_escenas_criticas() -> None:
    auditoria = AuditoriaCoherencia.model_validate(
        {
            "coherente": False,
            "contradicciones": [
                {
                    "escena": 4,
                    "tipo": "nombre",
                    "severidad": "critica",
                    "descripcion": "Lucía aparece como Lucila.",
                },
                {
                    "escena": 2,
                    "tipo": "rasgo",
                    "severidad": "menor",
                    "descripcion": "El impermeable cambia de tono.",
                },
                {
                    "escena": 4,
                    "tipo": "hecho",
                    "severidad": "critica",
                    "descripcion": "El faro estaba encendido antes.",
                },
            ],
        }
    )
    assert auditoria.escenas_criticas == [4]


def test_utilidades_de_conteo() -> None:
    assert contar_palabras("Hola, ¿qué tal? Bien-estar y d'Artagnan") == 6
    assert estimar_tokens_clip("girl, red hair") == 4
