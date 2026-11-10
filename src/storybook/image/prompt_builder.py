"""Composición del prompt de imagen con control del límite de 77 tokens de CLIP.

Prompt final = estilo_visual + descriptores de los personajes presentes + prompt_imagen
(CLAUDE.md §10). El codificador de texto de SD 1.5 (CLIP ViT-L/14) solo ve 77 tokens,
incluidos los especiales de inicio y fin: lo que sobra se descarta EN SILENCIO por la
derecha. Por eso aquí se cuenta antes de generar y, si no cabe, se recorta por frases
completas con esta prioridad de conservación: personajes > acción > estilo. Cada recorte
se registra (va al manifest) para poder explicarlo en el informe.

Los nombres propios de los personajes que el LLM deja en ``prompt_imagen`` ("Max and Luna
walking...") no significan nada para CLIP y gastan tokens: se sustituyen por el sujeto del
descriptor fijo (su primera frase, p. ej. "girl age 10") y la sustitución se registra.

El contador de tokens se inyecta: en producción, el tokenizer real del pipeline
(``contador_desde_tokenizer(pipe.tokenizer)``); en los tests, la estimación heurística
``schemas.estimar_tokens_clip`` (sin transformers).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from storybook.logging_utils import get_logger, kv
from storybook.schemas import Personaje, RolPersonaje, StoryBible, estimar_tokens_clip

logger = get_logger(__name__)

TOKENS_CLIP_TOTAL: Final = 77
TOKENS_ESPECIALES: Final = 2  # <|startoftext|> y <|endoftext|>
TOKENS_CLIP_UTILES: Final = TOKENS_CLIP_TOTAL - TOKENS_ESPECIALES
SEPARADOR: Final = ", "
SUJETO_GENERICO: Final = "a person"  # línea base C1: sin descriptores de la Bible
_LETRAS_MIN_PALABRA_NOMBRE: Final = 3

ContadorTokens = Callable[[str], int]
Segmento = Literal["estilo", "personajes", "accion", "negativo"]


class PromptBuilderError(Exception):
    """El prompt no puede construirse (escena o personaje inexistente)."""


def contador_desde_tokenizer(tokenizer: Any) -> ContadorTokens:
    """Adapta un ``CLIPTokenizer`` (``pipe.tokenizer``) a ``ContadorTokens``.

    No importa transformers: recibe el objeto ya cargado por el generador de imágenes.
    """

    def contar(texto: str) -> int:
        return len(tokenizer(texto, add_special_tokens=False)["input_ids"])

    return contar


def frases(texto: str) -> list[str]:
    """Divide un texto en frases separadas por comas, sin vacíos ni espacios sobrantes."""
    return [f.strip() for f in texto.split(",") if f.strip()]


@dataclass(frozen=True)
class Truncamiento:
    segmento: Segmento
    eliminado: str
    motivo: Literal["frase", "palabras"] = "frase"

    def a_dict(self) -> dict[str, str]:
        return {"segmento": self.segmento, "eliminado": self.eliminado, "motivo": self.motivo}


@dataclass(frozen=True)
class Sustitucion:
    """Nombre propio de un personaje reemplazado en ``prompt_imagen``."""

    personaje: str
    nombre: str
    por: str

    def a_dict(self) -> dict[str, str]:
        return {"personaje": self.personaje, "nombre": self.nombre, "por": self.por}


@dataclass(frozen=True)
class PromptImagen:
    prompt: str
    negative_prompt: str
    tokens: int
    tokens_negativo: int
    escena: int
    personajes: list[str] = field(default_factory=list)
    truncamientos: list[Truncamiento] = field(default_factory=list)
    sustituciones: list[Sustitucion] = field(default_factory=list)

    @property
    def truncado(self) -> bool:
        return bool(self.truncamientos)

    def a_dict(self) -> dict[str, Any]:
        return {
            "escena": self.escena,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "tokens": self.tokens,
            "tokens_negativo": self.tokens_negativo,
            "personajes": self.personajes,
            "truncamientos": [t.a_dict() for t in self.truncamientos],
            "sustituciones": [s.a_dict() for s in self.sustituciones],
        }


@dataclass
class _Bloque:
    """Grupo de frases que se recorta como unidad (estilo, un personaje o la acción)."""

    segmento: Segmento
    frases: list[str]
    minimo: int = 1

    def texto(self) -> str:
        return SEPARADOR.join(self.frases)


def _componer(bloques: Sequence[_Bloque]) -> str:
    return SEPARADOR.join(b.texto() for b in bloques if b.frases)


def _recortar_palabras(
    texto: str, segmento: Segmento, contar: ContadorTokens, maximo: int
) -> tuple[str, list[Truncamiento]]:
    """Último recurso: quita palabras por la derecha hasta caber."""
    palabras = texto.split()
    eliminadas: list[str] = []
    while palabras and contar(" ".join(palabras)) > maximo:
        eliminadas.insert(0, palabras.pop())
    if not eliminadas:
        return texto, []
    restante = " ".join(palabras).rstrip(" ,")
    return restante, [Truncamiento(segmento, " ".join(eliminadas), "palabras")]


def ajustar_a_presupuesto(
    bloques: list[_Bloque], contar: ContadorTokens, maximo: int
) -> tuple[str, list[Truncamiento]]:
    """Quita frases finales de los bloques de menor prioridad hasta que el prompt cabe.

    ``bloques`` va en orden de APARICIÓN; el orden de recorte es: estilo, luego acción,
    luego personajes secundarios (del último al primero) y por último el protagonista.
    Cada bloque conserva al menos ``minimo`` frases; si aun así no cabe, se recortan
    palabras al final del prompt completo.
    """
    orden: dict[Segmento, int] = {"estilo": 0, "accion": 1, "personajes": 2, "negativo": 0}
    prioridad = sorted(
        range(len(bloques)), key=lambda i: (orden[bloques[i].segmento], -i)
    )  # a igual segmento, primero el que aparece más tarde (personaje secundario)
    truncamientos: list[Truncamiento] = []
    while contar(_componer(bloques)) > maximo:
        candidato = next(
            (bloques[i] for i in prioridad if len(bloques[i].frases) > bloques[i].minimo), None
        )
        if candidato is None:
            # Se corta por la derecha: se registra el último bloque con contenido.
            ultimo = next(b.segmento for b in reversed(bloques) if b.frases)
            texto, extra = _recortar_palabras(_componer(bloques), ultimo, contar, maximo)
            return texto, truncamientos + extra
        truncamientos.append(Truncamiento(candidato.segmento, candidato.frases.pop()))
    return _componer(bloques), truncamientos


def _sin_tildes(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def sujeto_personaje(personaje: Personaje) -> str:
    """Primera frase del descriptor fijo (edad y tipo de persona: lo más importante)."""
    partes = frases(personaje.descripcion_visual_fija)
    return partes[0] if partes else SUJETO_GENERICO


def _variantes(texto: str) -> set[str]:
    return {texto, _sin_tildes(texto)}


def _patron_personaje(personaje: Personaje, palabras_compartidas: set[str]) -> str | None:
    """Regex de los nombres con que el LLM puede referirse a un personaje.

    * El nombre completo de varias palabras y el id con ``_`` se buscan sin distinguir
      mayúsculas (``capitan ruiz``, ``abuelo_tomas``).
    * Los nombres de una sola palabra y cada palabra de un nombre compuesto solo cuentan si
      empiezan en mayúscula: así no se reemplazan palabras comunes en inglés ("rose", "sky").
    * Las palabras que comparten dos personajes (un apellido) se omiten: serían ambiguas.
    """
    insensibles: set[str] = set()
    sensibles: set[str] = set()
    nombre = personaje.nombre.strip()
    if " " in nombre:
        insensibles |= _variantes(nombre)
    if "_" in personaje.id:
        insensibles.add(personaje.id)
        insensibles.add(personaje.id.replace("_", " "))
    for palabra in nombre.split():
        palabra = palabra.strip(".,;:")
        if (
            len(palabra) >= _LETRAS_MIN_PALABRA_NOMBRE
            and palabra[0].isupper()
            and _sin_tildes(palabra).lower() not in palabras_compartidas
        ):
            sensibles |= _variantes(palabra)
    alternativas = [
        *(f"(?i:{re.escape(t)})" for t in sorted(insensibles, key=len, reverse=True)),
        *(re.escape(t) for t in sorted(sensibles, key=len, reverse=True)),
    ]
    return "|".join(alternativas) if alternativas else None


def sustituir_nombres(
    texto: str, bible: StoryBible, *, usar_bible: bool = True
) -> tuple[str, list[Sustitucion]]:
    """Cambia los nombres de personajes de ``texto`` por su sujeto visual.

    Con ``usar_bible=False`` (línea base C1) se usa un sujeto genérico, para no filtrar los
    descriptores de la Bible en la configuración que debe prescindir de ella.
    """
    conteo: dict[str, int] = {}
    for p in bible.personajes:
        for palabra in {_sin_tildes(w).lower() for w in p.nombre.split()}:
            conteo[palabra] = conteo.get(palabra, 0) + 1
    compartidas = {w for w, n in conteo.items() if n > 1}

    grupos: list[str] = []
    por_grupo: dict[str, Personaje] = {}
    for i, personaje in enumerate(bible.personajes):
        patron = _patron_personaje(personaje, compartidas)
        if patron is None:
            continue
        grupo = f"p{i}"
        grupos.append(f"(?P<{grupo}>{patron})")
        por_grupo[grupo] = personaje
    if not grupos:
        return texto, []

    regex = re.compile(r"(?<![\w])(?:" + "|".join(grupos) + r")(?![\w])")
    sustituciones: list[Sustitucion] = []

    def reemplazar(coincidencia: re.Match[str]) -> str:
        personaje = por_grupo[str(coincidencia.lastgroup)]
        sujeto = sujeto_personaje(personaje) if usar_bible else SUJETO_GENERICO
        sustituciones.append(Sustitucion(personaje.id, coincidencia.group(0), sujeto))
        return sujeto

    resultado = regex.sub(reemplazar, texto)
    resultado = re.sub(r"\s{2,}", " ", resultado).strip()
    return resultado, sustituciones


def _ids_ordenados(bible: StoryBible, presentes: Sequence[str]) -> list[str]:
    """Protagonista primero (mayor peso en CLIP por ir antes), luego el orden de la escena."""
    prota = bible.protagonista().id
    return sorted(presentes, key=lambda pid: (pid != prota, list(presentes).index(pid)))


def construir_negativo(
    bible: StoryBible | None, base: str, contar: ContadorTokens, maximo: int
) -> tuple[str, list[Truncamiento]]:
    """Negative prompt común: el de la Bible más el base de la configuración, sin repetir."""
    unicas: list[str] = []
    fuentes = [bible.estilo_visual.negative_prompt if bible else "", base]
    for frase in (f for fuente in fuentes for f in frases(fuente)):
        if frase.lower() not in {u.lower() for u in unicas}:
            unicas.append(frase)
    bloque = _Bloque("negativo", unicas, minimo=1)
    return ajustar_a_presupuesto([bloque], contar, maximo)


def construir_prompt(
    bible: StoryBible,
    numero: int,
    *,
    contar: ContadorTokens = estimar_tokens_clip,
    negative_base: str = "",
    usar_bible: bool = True,
    max_tokens: int = TOKENS_CLIP_UTILES,
) -> PromptImagen:
    """Prompt y negative prompt de la escena ``numero``.

    ``usar_bible=False`` es la línea base C1 (experimentos): solo el ``prompt_imagen`` de la
    escena, sin estilo fijo ni descriptores de personajes.
    """
    try:
        escena = bible.escena(numero)
    except IndexError as exc:
        raise PromptBuilderError(f"La Bible no tiene escena {numero}") from exc
    if escena.numero != numero:
        raise PromptBuilderError(f"La escena en la posición {numero} tiene número {escena.numero}")

    bloques: list[_Bloque] = []
    ids: list[str] = []
    if usar_bible:
        bloques.append(_Bloque("estilo", frases(bible.estilo_visual.prompt())))
        ids = _ids_ordenados(bible, escena.personajes_presentes)
        for pid in ids:
            try:
                personaje = bible.personaje(pid)
            except KeyError as exc:
                raise PromptBuilderError(
                    f"Personaje inexistente en la escena {numero}: {pid}"
                ) from exc
            minimo = 2 if personaje.rol is RolPersonaje.PROTAGONISTA else 1
            bloques.append(_Bloque("personajes", frases(personaje.descripcion_visual_fija), minimo))
    accion, sustituciones = sustituir_nombres(escena.prompt_imagen, bible, usar_bible=usar_bible)
    bloques.append(_Bloque("accion", frases(accion)))

    prompt, truncamientos = ajustar_a_presupuesto(bloques, contar, max_tokens)
    negativo, trunc_neg = construir_negativo(
        bible if usar_bible else None, negative_base, contar, max_tokens
    )
    truncamientos += trunc_neg
    resultado = PromptImagen(
        prompt=prompt,
        negative_prompt=negativo,
        tokens=contar(prompt),
        tokens_negativo=contar(negativo),
        escena=numero,
        personajes=ids,
        truncamientos=truncamientos,
        sustituciones=sustituciones,
    )
    if sustituciones:
        logger.info(
            "prompt_imagen_nombres_sustituidos",
            extra=kv(escena=numero, cambios=[f"{s.nombre}->{s.por}" for s in sustituciones]),
        )
    if truncamientos:
        logger.warning(
            "prompt_imagen_truncado",
            extra=kv(
                escena=numero,
                tokens=resultado.tokens,
                eliminados=[f"{t.segmento}:{t.eliminado}" for t in truncamientos],
            ),
        )
    else:
        logger.info("prompt_imagen", extra=kv(escena=numero, tokens=resultado.tokens))
    return resultado


def construir_prompts(bible: StoryBible, **kwargs: Any) -> list[PromptImagen]:
    """Los 5 prompts de la historia (la etapa de imágenes los procesa en bloque)."""
    return [construir_prompt(bible, e.numero, **kwargs) for e in bible.escenas]
