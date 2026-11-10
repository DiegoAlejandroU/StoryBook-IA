"""Correcciones tras las primeras generaciones reales de F1 (tarea 1.4, 10 de noviembre).

* Una historia salió entera en inglés (título, resúmenes y narración) y pasó la validación.
* Las 3 historias se rechazaron una vez porque las escenas usaban el nombre ('lena') en vez
  del id del personaje ('protagonista').
* Con el modo automático de Ollama el 4B quedaba al 72 % en GPU; con ``num_gpu: 99`` al 100 %.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from storybook import config
from storybook.schemas import (
    PlanHistoria,
    StoryBible,
    parece_ingles,
    resolver_ids_por_nombre,
)
from storybook.story import prompts
from storybook.story.prompts import mensajes_escena

TEXTO_EN = (
    "NEXO-7 moves through Sector Gamma, its joints silent as breath. It checks the soil with a "
    "thermal sensor, then adjusts a small irrigation line. The garden glows faintly under the "
    "artificial light, fed by solar energy. Each leaf is touched only once, never too fast and "
    "never too slow. The air hums with the soft flow of water through the pipes. Its movements "
    "are patient, like watching roots grow in dark soil. It knows every crack in the pot. This "
    "garden is all that remains of the green of Earth in orbit, and the robot is its keeper."
)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Rooted in Orbit", True),
        ("Dr. Elira visits the garden, worried about its survival.", True),
        (TEXTO_EN, True),
        ("La Llamada del Faro", False),
        ("Lila", False),  # sin palabras funcionales: no se puede decidir y se acepta
        ("Raíces en órbita", False),
        ("El robot y The Garden", False),  # un nombre propio en inglés no basta
        ("Has visto la luz", False),  # 'has' existe en ambos idiomas
        ("Lena descubre que el faro se enciende cada noche a las 23:07.", False),
    ],
)
def test_parece_ingles(texto: str, esperado: bool) -> None:
    assert parece_ingles(texto) is esperado


def test_bible_con_narracion_en_ingles_se_rechaza(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["escenas"][0]["texto_narrativo"] = TEXTO_EN
    with pytest.raises(ValidationError, match="texto_narrativo parece estar en inglés"):
        StoryBible.model_validate(datos)


def test_titulo_y_resumen_en_ingles_se_rechazan(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["titulo"] = "Rooted in Orbit"
    datos["escenas"][1]["resumen"] = "The robot finds the last garden of the station."
    with pytest.raises(ValidationError) as info:
        StoryBible.model_validate(datos)
    mensaje = str(info.value)
    assert "titulo parece estar en inglés" in mensaje
    assert "resumen parece estar en inglés" in mensaje


def test_ids_por_nombre_se_resuelven(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["escenas"][1]["personajes_presentes"] = ["lucia", "tomas"]  # id: abuelo_tomas
    datos["escenas"][2]["personajes_presentes"] = ["Lucía", "lucia"]  # duplicado tras resolver
    bible = StoryBible.model_validate(datos)
    assert bible.escena(2).personajes_presentes == ["lucia", "abuelo_tomas"]
    assert bible.escena(3).personajes_presentes == ["lucia"]


def test_ids_genericos_del_plan_se_resuelven(bible_dict: dict[str, Any]) -> None:
    """Caso real de F1: ids 'protagonista'/'secundario' y escenas con los nombres."""
    datos = copy.deepcopy(bible_dict)
    datos["personajes"][0]["id"] = "protagonista"
    datos["personajes"][1]["id"] = "secundario"
    plan = {
        **{k: datos[k] for k in ("titulo", "genero", "tono", "estilo_visual", "escenario")},
        "personajes": datos["personajes"],
        "plan_escenas": [
            {
                "numero": e["numero"],
                "fase": e["fase"],
                "resumen": e["resumen"],
                "personajes_presentes": ["lucia", "tomas"] if e["numero"] > 1 else ["lucia"],
            }
            for e in datos["escenas"]
        ],
    }
    resultado = PlanHistoria.model_validate(plan)
    assert resultado.plan_escenas[0].personajes_presentes == ["protagonista"]
    assert resultado.plan_escenas[4].personajes_presentes == ["protagonista", "secundario"]


def test_nombre_ambiguo_o_desconocido_sigue_siendo_error(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["escenas"][1]["personajes_presentes"] = ["lucia", "fantasma"]
    with pytest.raises(ValidationError, match="inexistentes"):
        StoryBible.model_validate(datos)
    ambiguo = copy.deepcopy(bible_dict)
    ambiguo["personajes"][0]["nombre"] = "Lucía Ruiz"
    ambiguo["personajes"][1]["nombre"] = "Tomás Ruiz"
    ambiguo["escenas"][1]["personajes_presentes"] = ["lucia", "ruiz"]  # ¿cuál de los dos?
    with pytest.raises(ValidationError, match=r"inexistentes: \['ruiz'\]"):
        StoryBible.model_validate(ambiguo)
    personajes = StoryBible.model_validate(bible_dict).personajes
    # 'lu' es demasiado corto para ser alias; se deja igual (y luego falla la validación)
    assert resolver_ids_por_nombre(personajes, ["lu"]) == ["lu"]


def test_prompts_piden_espanol_y_mas_longitud(bible_dict: dict[str, Any]) -> None:
    assert "10 a 12 oraciones" in prompts.SISTEMA_ESCENA
    assert "ESPAÑOL" in prompts.SISTEMA_PLAN
    assert "nombre en minúsculas" in prompts.SISTEMA_PLAN
    plan = PlanHistoria.model_validate(
        {
            **{k: bible_dict[k] for k in ("titulo", "genero", "tono", "estilo_visual")},
            "escenario": bible_dict["escenario"],
            "personajes": bible_dict["personajes"],
            "plan_escenas": [
                {k: e[k] for k in ("numero", "fase", "resumen", "personajes_presentes")}
                for e in bible_dict["escenas"]
            ],
        }
    )
    usuario = mensajes_escena(plan, 2, [], [], "regla")[-1]["content"]
    assert usuario.rstrip().endswith(f"texto_narrativo en español, {prompts.LONGITUD_ESCENA}.")


def test_presupuesto_clip_del_prompt_deja_margen() -> None:
    # En F1 el modelo se pasó ~20 % con 0,75; el prompt pide como máximo el 60 % del límite.
    assert prompts._palabras(25) == 15
    assert prompts._palabras(20) == 12


def test_num_gpu_por_perfil() -> None:
    assert config.load_config("default").llm.num_gpu == 99
    assert config.load_config("rapido").llm.opciones_muestreo()["num_gpu"] == 99
    calidad = config.load_config("calidad").llm
    assert calidad.num_gpu is None  # el 8B no cabe entero: reparto automático
    assert "num_gpu" not in calidad.opciones_muestreo()


# ---------------------------------------------------------------------------------------
# Segunda corrida (10 historias, 6 válidas): causas de los 4 fallos
# ---------------------------------------------------------------------------------------
def test_genero_lo_fija_el_codigo(bible_dict: dict[str, Any]) -> None:
    from storybook.schemas import esquema_json_llm, validar_entrada
    from storybook.story.planner import Planificador
    from tests.fake_llm import FakeLLM

    for modelo in (PlanHistoria, StoryBible):
        assert "genero" not in esquema_json_llm(modelo)["properties"]
    datos = copy.deepcopy(bible_dict)
    datos.pop("genero")
    llm = FakeLLM().encolar(StoryBible, datos)
    cfg = config.LLMConfig(model="m", estrategia="una_llamada", auditar=False)
    solicitud = validar_entrada("Un faro que se enciende solo cada noche en la costa", "terror")
    bible = Planificador(llm, cfg).generar(solicitud).bible
    assert bible.genero == "terror"


def test_cero_protagonistas_se_elige_el_de_la_escena_1(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["personajes"][0]["rol"] = "secundario"
    bible = StoryBible.model_validate(datos)
    assert bible.protagonista().id == "lucia"


def test_campos_en_ingles_con_tildes_se_normalizan(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["escenas"][2]["prompt_imagen"] = "Tomás opens the old door, wide shot"
    datos["personajes"][1]["descripcion_visual_fija"] = "old man named Tomás, white beard"
    bible = StoryBible.model_validate(datos)
    assert bible.escena(3).prompt_imagen == "Tomas opens the old door, wide shot"
    assert bible.personaje("abuelo_tomas").descripcion_visual_fija.startswith("old man named Tomas")


def test_campos_en_ingles_escritos_en_espanol_se_rechazan(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["escenas"][0]["prompt_sonido"] = "viento fuerte y el sonido de las olas"
    with pytest.raises(ValidationError, match="prompt_sonido debe estar en inglés"):
        StoryBible.model_validate(datos)


def test_descriptor_y_estilo_largos_se_recortan_por_frases(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["personajes"][0]["descripcion_visual_fija"] = (
        "young girl age 10, long curly red hair, bright yellow raincoat, round silver glasses, "
        "small silver locket, slim build, light freckles"
    )  # ~27 tokens: sobra la última frase
    datos["estilo_visual"]["tecnica"] = "watercolor storybook illustration, soft paper texture"
    datos["estilo_visual"]["iluminacion"] = "soft moonlight, gentle rim light, misty glow"
    bible = StoryBible.model_validate(datos)
    descriptor = bible.protagonista().descripcion_visual_fija
    assert descriptor.endswith("small silver locket, slim build")
    assert "freckles" not in descriptor
    from storybook.schemas import TOKENS_MAX_DESCRIPTOR, TOKENS_MAX_ESTILO, estimar_tokens_clip

    assert estimar_tokens_clip(descriptor) <= TOKENS_MAX_DESCRIPTOR
    assert estimar_tokens_clip(bible.estilo_visual.prompt()) <= TOKENS_MAX_ESTILO
    assert bible.estilo_visual.tecnica.startswith("watercolor storybook illustration")


def test_reparacion_recuerda_los_idiomas() -> None:
    contenido = prompts.mensaje_reparacion(["prompt_imagen: debe estar en inglés"])["content"]
    assert "siguen en español" in contenido


# ---------------------------------------------------------------------------------------
# Tercera corrida (10/10 válidas): calidad de los descriptores y variedad de nombres
# ---------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        (
            "age:18, hair:frizzy blonde, clothes:white cotton t-shirt and jeans",
            "age 18, frizzy blonde hair, white cotton t-shirt and jeans",
        ),
        (
            "edad: 30, cabello: silver strands, ropa: utility suit with green panels",
            "age 30, silver strands hair, utility suit with green panels",
        ),
        (
            "age: 12, hair: short and black, distinct_feature: glowing green eyes",
            "age 12, short and black hair, glowing green eyes",
        ),
        ("10 years old, black braid, leather boots", "10 years old, black braid, leather boots"),
        ("wears a cloak: stitched pages", "wears a cloak: stitched pages"),  # etiqueta desconocida
    ],
)
def test_descriptor_sin_etiquetas(entrada: str, esperado: str) -> None:
    from storybook.schemas import quitar_etiquetas_descriptor

    assert quitar_etiquetas_descriptor(entrada) == esperado


def test_descriptor_con_etiquetas_en_la_bible(bible_dict: dict[str, Any]) -> None:
    datos = copy.deepcopy(bible_dict)
    datos["personajes"][1]["descripcion_visual_fija"] = "edad: 70, cabello: white, ropa: grey coat"
    bible = StoryBible.model_validate(datos)
    assert bible.personaje("abuelo_tomas").descripcion_visual_fija == (
        "age 70, white hair, grey coat"
    )


def test_prompts_sin_nombres_de_ejemplo() -> None:
    """En F1 el 4B copió 'lena' y 'capitan_ruiz' del prompt en 5 de 10 historias."""
    from storybook.schemas import esquema_json_llm

    textos = [prompts.SISTEMA_PLAN, prompts.SISTEMA_ESCENA, prompts.SISTEMA_BIBLE]
    textos.append(str(esquema_json_llm(PlanHistoria)))
    for texto in textos:
        for nombre in ("lena", "capitan_ruiz", "lucia"):
            assert nombre not in texto.lower()
