"""Tests de la composición del prompt de imagen y del control de 77 tokens de CLIP."""

from __future__ import annotations

import copy

import pytest

from storybook.image.prompt_builder import (
    TOKENS_CLIP_UTILES,
    PromptBuilderError,
    _Bloque,
    ajustar_a_presupuesto,
    construir_prompt,
    construir_prompts,
    contador_desde_tokenizer,
    frases,
)
from storybook.schemas import StoryBible, estimar_tokens_clip

NEG_BASE = "lowres, blurry, text, watermark, nsfw, gore"


@pytest.fixture
def bible(bible_dict: dict) -> StoryBible:
    return StoryBible.model_validate(bible_dict)


def test_orden_estilo_personajes_accion(bible: StoryBible) -> None:
    p = construir_prompt(bible, 1, negative_base=NEG_BASE)
    estilo = bible.estilo_visual.prompt()
    prota = bible.personaje("lucia").descripcion_visual_fija
    abuelo = bible.personaje("abuelo_tomas").descripcion_visual_fija
    accion = bible.escena(1).prompt_imagen
    assert p.prompt == ", ".join([estilo, prota, abuelo, accion])
    assert p.personajes == ["lucia", "abuelo_tomas"]
    assert p.tokens <= TOKENS_CLIP_UTILES
    assert not p.truncado


def test_protagonista_va_primero(bible_dict: dict) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["escenas"][0]["personajes_presentes"] = ["abuelo_tomas", "lucia"]
    p = construir_prompt(StoryBible.model_validate(datos), 1)
    assert p.personajes == ["lucia", "abuelo_tomas"]
    assert p.prompt.index("curly red hair") < p.prompt.index("white beard")


def test_solo_personajes_presentes(bible: StoryBible) -> None:
    p = construir_prompt(bible, 2)
    assert "white beard" not in p.prompt
    assert p.personajes == ["lucia"]


def test_negativo_combina_y_deduplica(bible: StoryBible) -> None:
    p = construir_prompt(bible, 1, negative_base="text, Watermark, lowres")
    partes = frases(p.negative_prompt)
    assert [x.lower() for x in partes].count("watermark") == 1
    assert "photo" in partes and "lowres" in partes


def test_linea_base_c1_sin_bible(bible: StoryBible) -> None:
    p = construir_prompt(bible, 3, usar_bible=False, negative_base=NEG_BASE)
    assert p.prompt == bible.escena(3).prompt_imagen
    assert p.personajes == []
    assert "photo" not in p.negative_prompt  # el negativo de la Bible no se usa en C1
    assert "watermark" in p.negative_prompt


def test_recorta_primero_el_estilo(bible: StoryBible) -> None:
    completo = construir_prompt(bible, 2)
    p = construir_prompt(bible, 2, max_tokens=completo.tokens - 3)
    assert p.truncado
    assert {t.segmento for t in p.truncamientos} == {"estilo"}
    assert "watercolor storybook illustration" in p.prompt  # al menos una frase de estilo
    assert bible.personaje("lucia").descripcion_visual_fija in p.prompt
    assert p.tokens <= completo.tokens - 3


def test_prioridad_personajes_sobre_accion_y_estilo(bible: StoryBible) -> None:
    p = construir_prompt(bible, 2, max_tokens=22)
    segmentos = [t.segmento for t in p.truncamientos]
    assert segmentos.index("estilo") < segmentos.index("accion")
    # La acción se recorta antes que el protagonista.
    if "personajes" in segmentos:
        assert segmentos.index("accion") < segmentos.index("personajes")
    assert "girl age 10" in p.prompt and "slim" in p.prompt
    assert p.tokens <= 22


def test_secundario_se_recorta_antes_que_protagonista(bible: StoryBible) -> None:
    p = construir_prompt(bible, 1, max_tokens=26)
    eliminados_personajes = [t.eliminado for t in p.truncamientos if t.segmento == "personajes"]
    assert eliminados_personajes, "debía recortar personajes con 26 tokens"
    assert eliminados_personajes[0] == "wooden cane"
    assert "girl age 10" in p.prompt


def test_ultimo_recurso_recorta_palabras(bible: StoryBible) -> None:
    p = construir_prompt(bible, 1, max_tokens=6)
    assert p.tokens <= 6
    ultimo = [t for t in p.truncamientos if t.segmento != "negativo"][-1]
    assert ultimo.motivo == "palabras"
    assert ultimo.segmento == "accion"  # se corta por la derecha: la acción va al final
    assert p.prompt.startswith("watercolor")


def test_negativo_largo_se_recorta(bible: StoryBible) -> None:
    largo = ", ".join(f"artifact{i}" for i in range(60))
    p = construir_prompt(bible, 1, negative_base=largo)
    assert p.tokens_negativo <= TOKENS_CLIP_UTILES
    assert any(t.segmento == "negativo" for t in p.truncamientos)
    assert p.negative_prompt.startswith("photo")  # se conserva primero el de la Bible


def test_contador_inyectable_mas_estricto(bible: StoryBible) -> None:
    def contador_bpe(texto: str) -> int:  # simula un BPE que parte cada palabra en dos
        return 2 * estimar_tokens_clip(texto)

    p = construir_prompt(bible, 1, contar=contador_bpe)
    assert p.tokens <= TOKENS_CLIP_UTILES
    assert p.truncado


def test_contador_desde_tokenizer() -> None:
    class TokenizerFalso:
        def __call__(self, texto: str, add_special_tokens: bool = True) -> dict:
            ids = texto.replace(",", " ,").split()
            if add_special_tokens:
                ids = ["<s>", *ids, "</s>"]
            return {"input_ids": ids}

    contar = contador_desde_tokenizer(TokenizerFalso())
    assert contar("red hair, glasses") == 4


def test_cinco_prompts(bible: StoryBible) -> None:
    prompts = construir_prompts(bible, negative_base=NEG_BASE)
    assert [p.escena for p in prompts] == [1, 2, 3, 4, 5]
    assert all(p.tokens <= TOKENS_CLIP_UTILES for p in prompts)
    assert len({p.negative_prompt for p in prompts}) == 1  # negativo común


def test_a_dict_para_manifest(bible: StoryBible) -> None:
    d = construir_prompt(bible, 2, max_tokens=20).a_dict()
    assert d["escena"] == 2 and d["tokens"] <= 20
    assert d["truncamientos"] and set(d["truncamientos"][0]) == {"segmento", "eliminado", "motivo"}


def test_escena_inexistente(bible: StoryBible) -> None:
    with pytest.raises(PromptBuilderError):
        construir_prompt(bible, 6)


def test_ajustar_respeta_minimos() -> None:
    bloques = [_Bloque("estilo", ["a b c", "d e"]), _Bloque("accion", ["f g", "h i"])]
    texto, trunc = ajustar_a_presupuesto(bloques, estimar_tokens_clip, 6)
    assert texto == "a b c, f g"
    assert [t.eliminado for t in trunc] == ["d e", "h i"]


def test_orden_accion_primero(bible: StoryBible) -> None:
    from storybook.image.prompt_builder import construir_prompt

    normal = construir_prompt(bible, 1)
    invertido = construir_prompt(bible, 1, orden="accion_primero")
    accion = bible.escena(1).prompt_imagen
    estilo = bible.estilo_visual.prompt()
    assert normal.prompt.startswith(estilo.split(",")[0])
    assert invertido.prompt.startswith(accion.split(",")[0])
    assert invertido.prompt.rstrip().endswith(estilo.split(",")[-1].strip())
    assert sorted(normal.prompt.split(", ")) == sorted(invertido.prompt.split(", "))
