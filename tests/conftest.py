"""Fixtures compartidas: una Story Bible válida construida a mano (sin LLM ni GPU)."""

from __future__ import annotations

from typing import Any

import pytest

from storybook.schemas import FASE_POR_NUMERO

_FRASES = (
    "Lucía caminó hacia el faro mientras el viento del norte sacudía su impermeable amarillo.",
    "Las olas golpeaban las rocas con un ritmo lento y paciente, como un reloj antiguo.",
    "Desde lo alto, una luz cálida giraba sobre el mar buscando algo entre la niebla.",
    "Su abuelo le había contado historias del último farero y de la tormenta de aquel invierno.",
    "Cada paso sobre las piedras mojadas sonaba distinto y ella contaba los destellos.",
    "Nadie en el pueblo quería hablar del faro, pero todos cerraban las cortinas al anochecer.",
)


def texto_narrativo(palabras_objetivo: int = 110) -> str:
    """Texto en español con aproximadamente ``palabras_objetivo`` palabras."""
    partes: list[str] = []
    contador = 0
    indice = 0
    while contador < palabras_objetivo:
        frase = _FRASES[indice % len(_FRASES)]
        partes.append(frase)
        contador += len(frase.split())
        indice += 1
    return " ".join(partes)


def escena_dict(numero: int, presentes: list[str] | None = None) -> dict[str, Any]:
    return {
        "numero": numero,
        "fase": FASE_POR_NUMERO[numero].value,
        "texto_narrativo": texto_narrativo(),
        "resumen": f"Lucía avanza en su investigación del faro en la escena {numero}.",
        "personajes_presentes": presentes if presentes is not None else ["lucia"],
        "hechos_nuevos": [f"Hecho establecido en la escena {numero} sobre el faro."],
        "prompt_imagen": "girl walking toward an old lighthouse, wide shot, stormy night sea",
        "prompt_sonido": "strong wind, ocean waves on rocks, distant seagulls",
        "etiquetas_sonido": ["wind", "ocean_waves"],
    }


@pytest.fixture
def bible_dict() -> dict[str, Any]:
    return {
        "titulo": "La luz del faro",
        "genero": "misterio",
        "tono": "inquietante y tierno",
        "idioma": "es",
        "estilo_visual": {
            "tecnica": "watercolor storybook illustration",
            "paleta": "muted teal and amber",
            "iluminacion": "soft moonlight",
            "negative_prompt": "photo, 3d render, text, watermark",
        },
        "escenario": {
            "lugar": "Pueblo pesquero junto a un acantilado",
            "epoca": "Años cincuenta",
            "rasgos_constantes": ["Faro blanco con franjas rojas", "Niebla constante"],
        },
        "personajes": [
            {
                "id": "lucia",
                "nombre": "Lucía",
                "rol": "protagonista",
                "descripcion_visual_fija": (
                    "girl age 10, slim, curly red hair, yellow raincoat, round glasses"
                ),
                "rasgos_personalidad": ["curiosa", "valiente"],
            },
            {
                "id": "abuelo_tomas",
                "nombre": "Tomás",
                "rol": "secundario",
                "descripcion_visual_fija": "old man, white beard, grey wool sweater, wooden cane",
                "rasgos_personalidad": ["protector", "nostálgico"],
            },
        ],
        "escenas": [
            escena_dict(1, ["lucia", "abuelo_tomas"]),
            escena_dict(2),
            escena_dict(3),
            escena_dict(4),
            escena_dict(5, ["lucia", "abuelo_tomas"]),
        ],
        "canon": ["El faro lleva veinte años apagado."],
    }
