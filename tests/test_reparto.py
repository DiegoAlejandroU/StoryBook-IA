"""El reparto del plan respeta la idea (13 nov: "amigos animales" planeados como niño, anciano
y robot)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from storybook import config
from storybook.schemas import Personaje, validar_entrada
from storybook.story.planner import AVISO_REPARTO, Planificador
from storybook.story.por_escenas import EscritorPorEscenas
from storybook.story.reparto import especies_pedidas, problemas_reparto, solo_animales, tipo
from tests.fake_llm import FakeLLM

IDEA = "Un grupo de amigos animales en la selva"


def _personaje(pid: str, nombre: str, descriptor: str, rol: str = "secundario") -> Personaje:
    return Personaje.model_validate(
        {
            "id": pid,
            "nombre": nombre,
            "rol": rol,
            "descripcion_visual_fija": descriptor,
            "rasgos_personalidad": ["curioso"],
        }
    )


HUMANOS = [
    _personaje("kai", "Kai", "boy age 10, curly brown hair, leaf shirt", "protagonista"),
    _personaje("toro", "Toro", "old man age 60, white beard, woven hat"),
    _personaje("mira", "Mira", "robot age 200, metallic gray body"),
    _personaje("julio", "Julio", "monkey age 8, bright red fur, tiny cap"),
]
ANIMALES = [
    _personaje("kai", "Kai", "young jaguar age 4, golden fur, black rosettes", "protagonista"),
    _personaje("toro", "Toro", "tapir age 20, dark gray hide, long snout"),
    _personaje("julio", "Julio", "monkey age 8, bright red fur, tiny cap"),
]


def test_tipo_del_personaje() -> None:
    assert tipo(HUMANOS[0]) == "boy" and tipo(HUMANOS[1]) == "old man"
    assert tipo(ANIMALES[0]) == "young jaguar"


@pytest.mark.parametrize(
    ("idea", "esperado"),
    [
        (IDEA, True),
        ("Los animalitos del bosque preparan una fiesta", True),
        ("Un zorro y un búho resuelven un misterio", True),
        ("Un niño y su perro buscan un tesoro", False),  # pide también una persona
        ("Un faro abandonado que se enciende solo cada noche", False),
        ("Un niño perezoso aprende a cocinar", False),  # "perezoso" no es la especie
    ],
)
def test_cuando_la_idea_pide_solo_animales(idea: str, esperado: bool) -> None:
    assert solo_animales(idea) is esperado


def test_especies_de_la_idea() -> None:
    assert [e for e, _ in especies_pedidas("Un zorro y un búho resuelven un misterio")] == [
        "zorro",
        "buho",
    ]
    assert especies_pedidas("Una tortuga que quería volar")[0][1] >= {"turtle", "tortoise"}


def test_problemas_del_reparto() -> None:
    problemas = problemas_reparto(IDEA, HUMANOS)
    assert len(problemas) == 1
    assert "'Kai' es 'boy'" in problemas[0] and "'Mira' es 'robot'" in problemas[0]
    assert "Julio" not in problemas[0]  # el mono sí es un animal
    assert problemas_reparto(IDEA, ANIMALES) == []
    falta = problemas_reparto("Un zorro curioso en la selva", ANIMALES)
    assert falta == [
        "La idea nombra 'zorro', pero ningún personaje lo es. Uno de los personajes (el "
        "protagonista, si la idea gira en torno a él) debe ser 'fox'."
    ]
    assert problemas_reparto("Un niño y su mono en la selva", HUMANOS) == []


# ---------------------------------------------------------------------------------------
# El planificador pide una corrección
# ---------------------------------------------------------------------------------------
def _plan(bible_dict: dict[str, Any], personajes: list[Personaje]) -> dict[str, Any]:
    ids = [p.id for p in personajes]
    return {
        **{k: bible_dict[k] for k in ("titulo", "genero", "tono", "estilo_visual", "escenario")},
        "personajes": [json.loads(p.model_dump_json()) for p in personajes],
        "plan_escenas": [
            {
                "numero": e["numero"],
                "fase": e["fase"],
                "resumen": e["resumen"],
                "personajes_presentes": ids[:2] if e["numero"] > 1 else ids[:1],
            }
            for e in bible_dict["escenas"]
        ],
    }


def test_el_planificador_corrige_un_reparto_que_no_es_el_de_la_idea(
    bible_dict: dict[str, Any],
) -> None:
    llm = FakeLLM().encolar("PlanHistoria", _plan(bible_dict, HUMANOS), _plan(bible_dict, ANIMALES))
    planificador = Planificador(llm, config.load_config("rapido").llm)
    plan, _ = planificador.planificar(validar_entrada(IDEA, "aventura"))
    assert [tipo(p) for p in plan.personajes] == ["young jaguar", "tapir", "monkey"]
    assert [r.etapa for r in planificador.registro] == ["plan", "plan_reparto"]
    assert planificador.avisos == []
    correccion = llm.llamadas[1]["messages"]
    assert correccion[-2]["role"] == "assistant" and "boy age 10" in correccion[-2]["content"]
    assert "'Kai' es 'boy'" in correccion[-1]["content"]


def test_si_la_correccion_no_sirve_queda_un_aviso(bible_dict: dict[str, Any]) -> None:
    llm = FakeLLM().encolar("PlanHistoria", _plan(bible_dict, HUMANOS), _plan(bible_dict, HUMANOS))
    planificador = Planificador(llm, config.load_config("rapido").llm)
    plan, _ = planificador.planificar(validar_entrada(IDEA, "aventura"))
    assert tipo(plan.personajes[0]) == "boy"  # la historia sigue, con aviso
    assert planificador.avisos == [AVISO_REPARTO]


def test_una_idea_sin_animales_no_hace_llamadas_extra(bible_dict: dict[str, Any]) -> None:
    llm = FakeLLM().encolar("PlanHistoria", _plan(bible_dict, HUMANOS))
    planificador = Planificador(llm, config.load_config("rapido").llm)
    planificador.planificar(validar_entrada("Un faro abandonado que se enciende solo", "misterio"))
    assert [r.etapa for r in planificador.registro] == ["plan"]


def test_el_escritor_por_escenas_registra_la_correccion(bible_dict: dict[str, Any]) -> None:
    llm = FakeLLM().encolar("PlanHistoria", _plan(bible_dict, HUMANOS), _plan(bible_dict, HUMANOS))
    with EscritorPorEscenas(config.load_config("rapido").llm, llm) as escritor:
        escritor.planificar(validar_entrada(IDEA, "aventura"))
    info = escritor.info()
    assert [r["etapa"] for r in info["llamadas"]] == ["plan", "plan_reparto"]
    assert info["fallbacks"] == [AVISO_REPARTO]


# ---------------------------------------------------------------------------------------
# Grupos que pide la idea (13 nov: "un perro rodeado de gatos" salía con un solo gato)
# ---------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("idea", "frases"),
    [
        ("Un perro rodeado de gatos en una ciudad", ["surrounded by many cats"]),
        ("Una manada de lobos protege a un cachorro", ["with several wolves"]),
        (IDEA, ["with a group of animal friends"]),
        ("Dos zorros buscan comida", []),  # número exacto: el LLM los nombra uno a uno
        ("Un par de gatos curiosos", []),
        ("Un perro que busca a su dueño", []),
        ("Un faro abandonado que se enciende solo", []),
    ],
)
def test_grupos_que_pide_la_idea(idea: str, frases: list[str]) -> None:
    from storybook.story.reparto import grupos_pedidos

    assert [g.frase for g in grupos_pedidos(idea)] == frases


def test_el_plan_lleva_los_grupos_y_la_escena_los_pide(bible_dict: dict[str, Any]) -> None:
    from storybook.story.prompts import mensajes_escena

    gatos = [
        _personaje("martillo", "Martillo", "dog age 3, silver fur, red scarf", "protagonista"),
        _personaje("pulpo", "Pulpo", "cat age 1, gray fur, blue eyes"),
    ]
    llm = FakeLLM().encolar("PlanHistoria", _plan(bible_dict, gatos))
    planificador = Planificador(llm, config.load_config("rapido").llm)
    plan, _ = planificador.planificar(
        validar_entrada("Un perro rodeado de gatos en una ciudad", "aventura")
    )
    assert [g.model_dump() for g in plan.grupos] == [
        {"frase": "surrounded by many cats", "especie": "cat", "plural": "cats"}
    ]
    mensaje = mensajes_escena(plan, 1, [], [], "regla")[-1]["content"]
    assert '"surrounded by many cats"' in mensaje
    # El LLM no ve el campo: lo pone el código.
    from storybook.schemas import PlanHistoria, esquema_json_llm

    assert "grupos" not in json.dumps(esquema_json_llm(PlanHistoria))


def test_el_descriptor_sin_simbolos() -> None:
    """13 nov: con el formato "<tipo> age <edad>" el 4B escribió "<dog> age 3"."""
    perro = _personaje("martillo", "Martillo", "<dog> age 3, silver fur, red scarf")
    assert perro.descripcion_visual_fija == "dog age 3, silver fur, red scarf"
    assert tipo(perro) == "dog"


# ---------------------------------------------------------------------------------------
# 18 nov: animales donde la idea no los pide ("Un niño en un parque" -> un zorrito)
# ---------------------------------------------------------------------------------------
ZORRITOS = [
    _personaje("pip", "Pip", "a young fox cub age 5, pink fur, leaf scarf", "protagonista"),
    _personaje("bolt", "Bolt", "robot squirrel age 3, silver bark-like body"),
]


def test_tipo_sin_articulo() -> None:
    assert tipo(ZORRITOS[0]) == "young fox cub"
    assert ZORRITOS[0].descripcion_visual_fija.startswith("young fox cub age 5")


@pytest.mark.parametrize(
    ("idea", "esperado"),
    [
        (
            "Un niño en un parque infantil super feliz",
            [
                "La idea no menciona animales, pero 'Pip' es 'young fox cub'. Esos personajes "
                "deben ser personas (o lo que la idea nombra).",
                "La idea nombra 'niño', pero ningún personaje lo es. El protagonista debe ser "
                "'boy' (el tipo en inglés al inicio del descriptor).",
            ],
        ),
        (
            "Una biblioteca super grande",
            [
                "La idea no menciona animales, pero 'Pip' es 'young fox cub'. Esos personajes "
                "deben ser personas (o lo que la idea nombra)."
            ],
        ),
    ],
)
def test_sin_animales_si_la_idea_no_los_pide(idea: str, esperado: list[str]) -> None:
    assert problemas_reparto(idea, ZORRITOS) == esperado


def test_las_personas_que_nombra_la_idea() -> None:
    chica = [
        _personaje("ana", "Ana", "young woman age 19, black hair", "protagonista"),
        _personaje("tom", "Tom", "old man age 70, gray beard"),
    ]
    assert problemas_reparto("Una chica en un edificio con demasiadas puertas", chica) == []
    assert problemas_reparto("Un anciano y una chica en un tren", chica) == []
    assert problemas_reparto("Un niño y su perro buscan un tesoro", HUMANOS) == [
        "La idea nombra 'perro', pero ningún personaje lo es. Uno de los personajes (el "
        "protagonista, si la idea gira en torno a él) debe ser 'dog'."
    ]
    piloto = problemas_reparto("Un avión pilotado por una piloto cae al mar", chica)
    assert piloto and "'piloto'" in piloto[0] and "'pilot'" in piloto[0]
    # El dragón de la idea es un animal pedido: el dron con forma de zorro no se marca.
    dragon = [
        _personaje("alex", "Alex", "biomechanical dragon age 120, obsidian scales", "protagonista"),
        _personaje("luna", "Luna", "small fox-like drone age 5, silver fur"),
    ]
    assert problemas_reparto("Un dragón quemando un castillo antiguo", dragon) == []


def test_la_regla_del_prompt_habla_de_personas_y_de_animales() -> None:
    from storybook.story.prompts import REGLA_REPARTO

    assert "si NO menciona animales, los personajes son personas" in REGLA_REPARTO
    assert "si nombra una persona" in REGLA_REPARTO
