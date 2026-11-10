"""Consistencia visual: "character sheet" del protagonista para IP-Adapter (C3).

Estrategia (CLAUDE.md §12): antes de las 5 escenas se genera un retrato de cuerpo entero
del protagonista, con el estilo fijo de la Bible, fondo neutro y la seed del personaje. Esa
imagen es la referencia que IP-Adapter inyecta en cada escena (sus embeddings CLIP de
imagen), de modo que la cara, el pelo y la ropa se mantienen aunque cambien la acción y el
encuadre. Aquí solo se construye el prompt; la generación la hace ``image.generator``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from storybook.image.prompt_builder import (
    TOKENS_CLIP_UTILES,
    ContadorTokens,
    Truncamiento,
    _Bloque,
    ajustar_a_presupuesto,
    construir_negativo,
    frases,
)
from storybook.schemas import StoryBible, estimar_tokens_clip

NOMBRE_ARCHIVO_SHEET: Final = "character_sheet.png"
# El encoder de IP-Adapter (CLIP ViT-H/14) recorta al centro a 224x224: una imagen cuadrada
# con el personaje centrado conserva todo el cuerpo. 512 es la resolución nativa de SD 1.5.
TAMANO_SHEET: Final = 512
COMPOSICION_SHEET: Final = (
    "full body character portrait, front view, standing, centered, plain light background"
)
NEGATIVO_SHEET: Final = "multiple people, crowd, cropped, cut off, busy background"


@dataclass(frozen=True)
class PromptSheet:
    personaje: str
    prompt: str
    negative_prompt: str
    tokens: int
    seed: int
    ancho: int = TAMANO_SHEET
    alto: int = TAMANO_SHEET
    truncamientos: list[Truncamiento] = field(default_factory=list)

    def a_dict(self) -> dict[str, Any]:
        return {
            "personaje": self.personaje,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "tokens": self.tokens,
            "seed": self.seed,
            "ancho": self.ancho,
            "alto": self.alto,
            "truncamientos": [t.a_dict() for t in self.truncamientos],
        }


def construir_prompt_sheet(
    bible: StoryBible,
    *,
    seed_por_defecto: int,
    contar: ContadorTokens = estimar_tokens_clip,
    negative_base: str = "",
    max_tokens: int = TOKENS_CLIP_UTILES,
) -> PromptSheet:
    """Prompt del retrato de referencia: estilo + descriptor del protagonista + composición.

    Si no cabe en 77 tokens se recorta primero el estilo, luego la composición y por último
    el descriptor (que conserva al menos dos frases: es lo que IP-Adapter debe fijar).
    """
    prota = bible.protagonista()
    bloques = [
        _Bloque("estilo", frases(bible.estilo_visual.prompt())),
        _Bloque("personajes", frases(prota.descripcion_visual_fija), minimo=2),
        _Bloque("accion", frases(COMPOSICION_SHEET)),
    ]
    prompt, truncamientos = ajustar_a_presupuesto(bloques, contar, max_tokens)
    base = ", ".join(x for x in (negative_base, NEGATIVO_SHEET) if x)
    negativo, trunc_neg = construir_negativo(bible, base, contar, max_tokens)
    return PromptSheet(
        personaje=prota.id,
        prompt=prompt,
        negative_prompt=negativo,
        tokens=contar(prompt),
        seed=prota.seed if prota.seed is not None else seed_por_defecto,
        truncamientos=truncamientos + trunc_neg,
    )
