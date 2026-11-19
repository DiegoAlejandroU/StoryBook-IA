"""La mejor de N versiones de una ilustración (17 nov: "faltan o sobran personajes").

SDXL a veces dibuja un solo gato cuando la escena pide varios, o un segundo perro que nadie
pidió, y el mismo prompt con otra seed suele salir bien. Por eso cada escena se genera
``image.candidatos`` veces (seeds derivadas de la de la escena) y OpenCLIP, en CPU, elige la
versión donde mejor se ve lo que pide el prompt:

* ``verificar`` son las figuras que deben verse ("a dog", "many cats"). Cada versión se
  compara con "a picture of <figura>"; pesa más la figura peor representada (la que falta).
* ``evitar`` son figuras de más ("two dogs" cuando hay un solo perro). Si se parecen a la
  imagen más que el personaje principal, la versión se castiga.

El puntaje solo sirve para comparar versiones de la misma escena (no es una nota absoluta).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean
from typing import Any, Final, Protocol

from PIL import Image

from storybook.schemas import derivar_seed

PLANTILLA_TEXTO: Final = "a picture of {}"
PESO_MINIMO: Final = 0.6  # la figura peor representada
PESO_MEDIA: Final = 0.4
PESO_SOBRA: Final = 0.5  # castigo si "two dogs" se parece más que "a dog"


class EvaluadorCandidatos(Protocol):
    """Lo que la selección usa de ``ClipScorer`` (o de uno falso en los tests)."""

    def similitudes(
        self, imagenes: Sequence[Image.Image], textos: Sequence[str]
    ) -> list[list[float]]:
        """Coseno imagen-texto: una fila por imagen, una columna por texto."""
        ...


def seeds_candidatos(seed: int, n: int) -> list[int]:
    """La primera versión usa la seed de la escena (igual que con una sola versión)."""
    return [seed] + [derivar_seed(seed, "candidato", k) for k in range(1, n)]


def puntuar(presencias: Sequence[float], sobras: Sequence[float] = ()) -> float:
    """``presencias``: similitud con cada figura pedida (la primera es el principal)."""
    if not presencias:
        return 0.0
    puntaje = PESO_MINIMO * min(presencias) + PESO_MEDIA * mean(presencias)
    if sobras:
        puntaje -= PESO_SOBRA * max(0.0, max(sobras) - presencias[0])
    return round(puntaje, 4)


@dataclass(frozen=True)
class Eleccion:
    elegida: int  # índice en la lista de versiones
    detalle: list[dict[str, Any]]  # por versión: puntaje y similitud con cada figura
    segundos: float = 0.0  # lo que tardó CLIP en comparar


def elegir(
    evaluador: EvaluadorCandidatos,
    imagenes: Sequence[Image.Image],
    verificar: Sequence[str],
    evitar: Sequence[str] = (),
) -> Eleccion:
    """Elige la versión con mejor puntaje (en empate, la primera)."""
    figuras = list(dict.fromkeys(verificar))
    sobras = [s for s in dict.fromkeys(evitar) if s not in figuras]
    textos = [PLANTILLA_TEXTO.format(f) for f in [*figuras, *sobras]]
    filas = evaluador.similitudes(list(imagenes), textos)
    detalle: list[dict[str, Any]] = []
    for fila in filas:
        presencias = [float(x) for x in fila[: len(figuras)]]
        de_mas = [float(x) for x in fila[len(figuras) :]]
        detalle.append(
            {
                "puntaje": puntuar(presencias, de_mas),
                "presencia": {f: round(s, 4) for f, s in zip(figuras, presencias, strict=True)},
                "sobra": {f: round(s, 4) for f, s in zip(sobras, de_mas, strict=True)},
            }
        )
    puntajes = [d["puntaje"] for d in detalle]
    return Eleccion(elegida=puntajes.index(max(puntajes)), detalle=detalle)
