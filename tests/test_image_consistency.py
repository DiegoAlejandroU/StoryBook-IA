"""Tests de la character sheet y de la sustitución de nombres en ``prompt_imagen``."""

from __future__ import annotations

import copy

import pytest

from storybook.image.consistency import (
    COMPOSICION_SHEET,
    TAMANO_SHEET,
    construir_prompt_sheet,
)
from storybook.image.prompt_builder import (
    SUJETO_GENERICO,
    TOKENS_CLIP_UTILES,
    construir_prompt,
    sustituir_nombres,
)
from storybook.schemas import StoryBible, estimar_tokens_clip


@pytest.fixture
def bible(bible_dict: dict) -> StoryBible:
    return StoryBible.model_validate(bible_dict)


def _con_prompt(bible_dict: dict, numero: int, prompt: str) -> StoryBible:
    datos = copy.deepcopy(bible_dict)
    datos["escenas"][numero - 1]["prompt_imagen"] = prompt
    return StoryBible.model_validate(datos)


# -- character sheet -------------------------------------------------------------------
def test_sheet_estilo_descriptor_y_composicion(bible: StoryBible) -> None:
    con_seeds = bible.con_seeds(7)
    p = construir_prompt_sheet(con_seeds, seed_por_defecto=1)
    prota = con_seeds.protagonista()
    assert p.personaje == prota.id
    assert prota.descripcion_visual_fija in p.prompt
    assert p.prompt.startswith(con_seeds.estilo_visual.prompt())
    assert "full body character portrait" in p.prompt
    assert p.seed == prota.seed
    assert (p.ancho, p.alto) == (TAMANO_SHEET, TAMANO_SHEET)
    assert p.tokens <= TOKENS_CLIP_UTILES
    assert "multiple people" in p.negative_prompt


def test_sheet_sin_seed_usa_la_por_defecto(bible: StoryBible) -> None:
    assert construir_prompt_sheet(bible, seed_por_defecto=1234).seed == 1234


def test_sheet_recorta_composicion_antes_que_descriptor(bible: StoryBible) -> None:
    p = construir_prompt_sheet(bible, seed_por_defecto=1, max_tokens=30)
    assert estimar_tokens_clip(p.prompt) <= 30
    assert "girl age 10" in p.prompt and "curly red hair" in p.prompt
    segmentos = {t.segmento for t in p.truncamientos}
    assert "estilo" in segmentos
    assert COMPOSICION_SHEET.split(",")[0] in p.prompt  # la acción conserva su primera frase
    assert p.a_dict()["truncamientos"]


# -- sustitución de nombres ------------------------------------------------------------
def test_nombre_simple_se_cambia_por_sujeto(bible: StoryBible) -> None:
    texto, cambios = sustituir_nombres("Lucia climbing the lighthouse stairs", bible)
    assert texto == "girl age 10 climbing the lighthouse stairs"
    assert [(c.personaje, c.nombre, c.por) for c in cambios] == [("lucia", "Lucia", "girl age 10")]


def test_varios_nombres_y_tildes(bible: StoryBible) -> None:
    texto, cambios = sustituir_nombres("Lucía and Tomas walking on the pier", bible)
    assert texto == "girl age 10 and old man walking on the pier"
    assert {c.personaje for c in cambios} == {"lucia", "abuelo_tomas"}


def test_id_con_guion_bajo(bible: StoryBible) -> None:
    texto, _ = sustituir_nombres("abuelo_tomas holding a lantern", bible)
    assert texto == "old man holding a lantern"


def test_minusculas_de_una_palabra_no_se_tocan(bible: StoryBible) -> None:
    texto, cambios = sustituir_nombres("lucia flowers on a table", bible)
    assert texto == "lucia flowers on a table" and cambios == []


def test_no_reemplaza_dentro_de_otra_palabra(bible: StoryBible) -> None:
    texto, cambios = sustituir_nombres("Lucias lantern, Tomasito boat", bible)
    assert cambios == [] and texto == "Lucias lantern, Tomasito boat"


def test_sin_bible_usa_sujeto_generico(bible: StoryBible) -> None:
    texto, _ = sustituir_nombres("Lucia running", bible, usar_bible=False)
    assert texto == f"{SUJETO_GENERICO} running"


def test_nombre_compuesto_y_palabra_compartida(bible_dict: dict) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["personajes"][1]["nombre"] = "Capitán Ruiz"
    datos["personajes"].append(
        {
            "id": "marta",
            "nombre": "Marta Ruiz",
            "rol": "secundario",
            "descripcion_visual_fija": "woman age 40, short black hair, navy coat",
            "rasgos_personalidad": ["seria"],
        }
    )
    bible = StoryBible.model_validate(datos)
    texto, cambios = sustituir_nombres("capitan ruiz greets Marta near Ruiz boat", bible)
    # "Ruiz" suelto es ambiguo (dos personajes): se deja.
    assert texto == "old man greets woman age 40 near Ruiz boat"
    assert len(cambios) == 2


def test_construir_prompt_registra_sustituciones(bible_dict: dict) -> None:
    bible = _con_prompt(bible_dict, 1, "Lucia and Tomas on the cliff, wide shot")
    p = construir_prompt(bible, 1)
    assert "Lucia" not in p.prompt and "Tomas" not in p.prompt
    assert p.prompt.endswith("girl age 10 and old man on the cliff, wide shot")
    assert len(p.sustituciones) == 2
    assert p.a_dict()["sustituciones"][0]["por"] == "girl age 10"


def test_sin_nombres_no_hay_sustituciones(bible: StoryBible) -> None:
    p = construir_prompt(bible, 2)
    assert p.sustituciones == [] and p.a_dict()["sustituciones"] == []
