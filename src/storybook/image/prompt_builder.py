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
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal

from storybook.config import OrdenPromptImagen as OrdenPrompt
from storybook.logging_utils import get_logger, kv
from storybook.schemas import (
    GrupoVisual,
    Personaje,
    RolPersonaje,
    StoryBible,
    estimar_tokens_clip,
)
from storybook.story.reparto import NO_ANIMALES, singular_ingles

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
    foco: str | None = None  # personaje con descriptor completo (modo "foco")
    mencionados: list[str] = field(default_factory=list)  # personajes que nombra la acción
    ip_factor: float = 1.0  # multiplica la escala de IP-Adapter en esta escena (0 = sin él)
    # Quiénes deben verse ("a dog", "many cats"): con varias versiones, CLIP elige la imagen
    # donde mejor se ven todos (generator.py).
    verificar: list[str] = field(default_factory=list)
    evitar: list[str] = field(default_factory=list)  # figuras de más ("two dogs")

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
            "foco": self.foco,
            "mencionados": self.mencionados,
            "ip_factor": self.ip_factor,
            "verificar": self.verificar,
            "evitar": self.evitar,
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
    bloques: list[_Bloque],
    contar: ContadorTokens,
    maximo: int,
    orden: dict[Segmento, int] | None = None,
) -> tuple[str, list[Truncamiento]]:
    """Quita frases finales de los bloques de menor prioridad hasta que el prompt cabe.

    ``bloques`` va en orden de APARICIÓN; el orden de recorte es: estilo, luego acción,
    luego personajes secundarios (del último al primero) y por último el protagonista.
    Cada bloque conserva al menos ``minimo`` frases; si aun así no cabe, se recortan
    palabras al final del prompt completo.
    """
    orden = orden or {"estilo": 0, "accion": 1, "personajes": 2, "negativo": 0}
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
    texto: str,
    bible: StoryBible,
    *,
    usar_bible: bool = True,
    sujeto: Callable[[Personaje], str] | None = None,
) -> tuple[str, list[Sustitucion]]:
    """Cambia los nombres de personajes de ``texto`` por su sujeto visual.

    Con ``usar_bible=False`` (línea base C1) se usa un sujeto genérico, para no filtrar los
    descriptores de la Bible en la configuración que debe prescindir de ella. ``sujeto``
    cambia cómo se nombra a cada personaje (el modo foco usa "the boy", "a monkey").
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
        if not usar_bible:
            nuevo = SUJETO_GENERICO
        elif sujeto is not None:
            nuevo = sujeto(personaje)
        else:
            nuevo = sujeto_personaje(personaje)
        sustituciones.append(Sustitucion(personaje.id, coincidencia.group(0), nuevo))
        return nuevo

    resultado = regex.sub(reemplazar, texto)
    resultado = re.sub(r"\s{2,}", " ", resultado).strip()
    return resultado, sustituciones


# ---------------------------------------------------------------------------------------
# Personaje foco (corrección del 12 nov). Con los descriptores de todos los personajes
# presentes, SD mezclaba sujetos (un jaguar con la camisa del niño) y la acción se recortaba;
# y con IP-Adapter en todas las escenas, cualquier sujeto tomaba la cara del protagonista o
# salían clones. Ahora cada escena tiene UN personaje foco con su descriptor completo.
# ---------------------------------------------------------------------------------------
PersonajesPrompt = Literal["presentes", "foco"]
_GRUPO: Final = re.compile(
    r"\b(?:group|friends|crowd|together|family|team|everyone|people|children|kids|villagers|"
    r"surrounded|several|many|herd|pack|flock)\b",
    re.IGNORECASE,
)
IP_FACTOR_IMPLICITO: Final = 0.5  # el protagonista está en la escena, pero la acción no lo nombra
IP_FACTOR_CON_OTROS: Final = 0.6  # la acción también nombra a otro personaje
IP_FACTOR_GRUPO: Final = 0.5  # "group of friends": con escala alta salen clones


def tipo_personaje(personaje: Personaje) -> str:
    """'boy age 10' -> 'boy'; 'young jaguar age 4' -> 'young jaguar'; 'old man' -> 'old man'."""
    sujeto = sujeto_personaje(personaje)
    # Historias guardadas antes del 18 nov pueden traer "a biomechanical dragon age 120".
    sujeto = re.sub(r"^(?:a|an|the)\s+", "", sujeto, flags=re.IGNORECASE)
    return re.split(r"\s+age\b", sujeto, maxsplit=1)[0].strip() or sujeto


# Palabras del inicio del descriptor que no nombran el tipo de personaje ("25 years old").
_NO_SUSTANTIVOS: Final = frozenset(
    {"old", "young", "years", "year", "aged", "age", "little", "small", "big", "tall", "teen"}
)


def _sustantivo(personaje: Personaje) -> str:
    """Tipo de personaje con el que la acción lo puede nombrar: "jaguar", "man", "boy"."""
    palabras = re.findall(r"[a-z]+", _sin_tildes(tipo_personaje(personaje)).lower())
    palabras = [w for w in palabras if w not in _NO_SUSTANTIVOS]
    return palabras[-1] if palabras else ""


NEGATIVO_CLONES: Final = "duplicate character, clone, twins"
# En una escena de grupo de otra especie, el descriptor del foco se acorta (tipo, edad y
# color) para que no tape al grupo.
DESCRIPTOR_EN_GRUPO: Final = 3
# Personas que pueden ser la misma figura en el negative (ver ``misma_familia``).
_NINOS: Final = frozenset({"boy", "girl", "child", "kid", "toddler", "baby"})
_NINOS_GENERICOS: Final = frozenset({"child", "kid", "toddler", "baby"})
_HUMANOS: Final = NO_ANIMALES - {"robot", "android", "cyborg", "machine"}


def _personaje_o_none(bible: StoryBible, pid: str | None) -> Personaje | None:
    if pid is None:
        return None
    try:
        return bible.personaje(pid)
    except KeyError:
        return None


def sujeto_corto(personaje: Personaje, *, foco: bool = False) -> str:
    """Cómo nombra la acción a un personaje en modo foco: "the boy", "an old man"."""
    # "25 years old, short black hair" no dice qué es: "a person" (no "a 25 years old").
    nombre = tipo_personaje(personaje) if _sustantivo(personaje) else "person"
    if foco:
        return f"the {nombre}"
    articulo = "an" if nombre[:1].lower() in "aeiou" else "a"
    return f"{articulo} {nombre}"


def grupo_de_escena(bible: StoryBible, numero: int, accion: str) -> tuple[GrupoVisual, bool] | None:
    """El grupo que pide la idea (``bible.grupos``) si corresponde a la escena, y si el LLM
    ya lo nombró en plural.

    Corresponde si en la escena hay alguien de esa especie o la acción la nombra (o, para un
    grupo sin especie, si hay al menos dos personajes).
    """
    escena = bible.escena(numero)
    texto = accion.lower()
    for grupo in bible.grupos:
        nombrado = grupo.frase.lower() in texto or bool(
            grupo.plural and re.search(rf"\b{re.escape(grupo.plural)}\b", texto)
        )
        if grupo.especie is None:
            if nombrado or len(escena.personajes_presentes) >= 2:
                return grupo, nombrado
            continue
        especie = re.compile(rf"\b{re.escape(grupo.especie)}\b", re.IGNORECASE)
        presentes = []
        for pid in escena.personajes_presentes:
            try:
                presentes.append(bible.personaje(pid))
            except KeyError:
                continue
        if (
            nombrado
            or especie.search(texto)
            or any(especie.search(tipo_personaje(p)) for p in presentes)
        ):
            return grupo, nombrado
    return None


@dataclass(frozen=True)
class Composicion:
    """Cómo queda la parte de la acción del prompt a partir del plano visual."""

    accion: str
    foco: FocoEscena
    limite_descriptor: int | None
    extra_negativo: str
    verificar: list[str]
    evitar: list[str]


def _figura(bible: StoryBible, quien: str, cantidad: str) -> tuple[str, str]:
    """(texto, sustantivo): ('a cat', 'cat'), ('many cats', 'cat'), ('two foxes', 'fox')."""
    personaje = _personaje_o_none(bible, quien)
    if personaje is not None:
        sustantivo = _sustantivo(personaje) or "person"
        uno = sujeto_corto(personaje)
    else:
        palabras = re.findall(r"[a-z]+", _sin_tildes(quien).lower().replace("_", " "))
        palabras = [w for w in palabras if w not in {"a", "an", "the", "some", "many", "two"}]
        if palabras:
            palabras[-1] = singular_ingles(palabras[-1])  # el LLM a veces escribe "cats"
        sustantivo = " ".join(palabras[-2:]) or SUJETO_GENERICO
        articulo = "an" if sustantivo[:1] in "aeiou" else "a"
        uno = f"{articulo} {sustantivo}"
    nucleo = sustantivo.split()[-1]
    if cantidad == "one":
        return uno, nucleo
    numero = "two" if cantidad == "two" else "many"
    plural = " ".join([*sustantivo.split()[:-1], plural_ingles(nucleo)])
    return f"{numero} {plural}", nucleo


def _con_rasgos(bible: StoryBible, quien: str, texto: str, cantidad: str) -> str:
    """'a cat' -> 'a cat (short fur, grey coat)' (acompañante con nombre, FLUX)."""
    personaje = _personaje_o_none(bible, quien)
    if personaje is None or cantidad != "one":
        return texto
    rasgos = frases(personaje.descripcion_visual_fija)[1:3]
    return f"{texto} ({', '.join(rasgos)})" if rasgos else texto


def _agrupar_iguales(textos: list[str]) -> list[str]:
    """["a cat", "a cat", "a bird"] -> ["two cats", "a bird"] (dos gatos sin nombre en el
    prompt no se distinguen: "with a cat and a cat" se lee peor que "with two cats")."""
    salida = []
    for texto in dict.fromkeys(textos):
        veces = textos.count(texto)
        palabras = texto.split()
        if veces == 1 or palabras[0] not in {"a", "an"}:  # "many cats" dos veces: una basta
            salida.append(texto)
        else:
            plural = " ".join([*palabras[1:-1], plural_ingles(palabras[-1])])
            salida.append(f"{'two' if veces == 2 else 'many'} {plural}")
    return salida


def misma_familia(a: str, b: str) -> bool:
    """¿Dos sustantivos pueden ser la misma figura? 'child' cubre a 'girl' y a 'boy', y
    'person' a cualquier persona.

    20 nov: "Un niño en un parque" con el principal 'child' y una niña al lado puso "two
    children" en el negative y en lo que se evita al elegir versión: justo la escena pedida.
    """
    if a == b:
        return True
    par = {a, b}
    if par & _NINOS_GENERICOS and par <= _NINOS:
        return True
    return "person" in par and (par - {"person"}) <= _HUMANOS


def componer_plano(bible: StoryBible, numero: int, encoder_largo: bool = False) -> Composicion:
    """El inicio del prompt según el plano del ilustrador (17 nov: "faltan o sobran personajes").

    "wide shot, a dog surrounded by many cats, with a cat, looks up at the rooftops, a narrow
    street at dusk": primero quiénes se ven (y cuántos), luego qué hace el principal y dónde.
    El descriptor completo va solo para el principal y se acorta si hay más figuras. Las
    reglas de IP-Adapter y del negative son las del 13 nov: sin referencia si hay un grupo de
    otra especie (la referencia es el protagonista solo) y nada de "clones" si hay figuras de
    su misma especie.

    ``encoder_largo`` (FLUX, 18 nov): el prompt puede tener hasta 256 tokens y el modelo
    asocia bien rasgos a cada figura, así que el descriptor del principal va completo y cada
    acompañante con nombre lleva dos rasgos ("a cat (short fur, grey coat)").
    """
    escena = bible.escena(numero)
    plano = escena.plano_visual
    if plano is None:
        raise PromptBuilderError(f"La escena {numero} no tiene plano visual")
    principal = bible.personaje(plano.principal)
    nucleo_principal = _sustantivo(principal) or "person"
    figuras = [_figura(bible, f.quien, f.cantidad) for f in plano.acompanantes]
    cantidades = [f.cantidad for f in plano.acompanantes]
    quienes = [f.quien for f in plano.acompanantes]

    # El grupo que pide la idea ("rodeado de gatos"), si su especie está en la escena.
    frase_grupo = ""
    for grupo in bible.grupos:
        especies = {n for _, n in figuras} | {
            _sustantivo(p) or "person"
            for p in (_personaje_o_none(bible, pid) for pid in escena.personajes_presentes)
            if p is not None
        }
        if grupo.especie is None and (figuras or len(escena.personajes_presentes) >= 2):
            frase_grupo = grupo.frase
        elif grupo.especie and grupo.especie in especies:
            frase_grupo = grupo.frase
            # La figura "many cats" ya la cubre la frase del grupo.
            quedan = [
                i for i, (f, c) in enumerate(zip(figuras, cantidades, strict=True))
                if not (f[1] == grupo.especie and c != "one")
            ]  # fmt: skip
            figuras = [figuras[i] for i in quedan]
            cantidades = [cantidades[i] for i in quedan]
            quienes = [quienes[i] for i in quedan]
        if frase_grupo:
            break

    sujeto = sujeto_corto(principal)
    inicio = f"{sujeto} {frase_grupo}" if frase_grupo else sujeto
    textos_con = [texto for texto, _ in figuras]
    if encoder_largo:
        textos_con = [
            _con_rasgos(bible, quien, texto, cantidad)
            for (texto, _), quien, cantidad in zip(figuras, quienes, cantidades, strict=True)
        ]
    con = " and ".join(_agrupar_iguales(textos_con))
    accion_texto, _ = sustituir_nombres(plano.accion, bible, sujeto=lambda p: sujeto_corto(p))
    # "the dog looks up" / "he looks up" -> "looks up": el sujeto ya va al inicio.
    accion_texto = re.sub(
        rf"^(?:(?:the|a|an)\s+(?:[a-z]+\s+){{0,2}}?{re.escape(nucleo_principal)}|he|she|it|they)\s+",
        "",
        accion_texto,
        flags=re.I,
    )
    lugar_texto, _ = sustituir_nombres(plano.lugar, bible, sujeto=lambda p: sujeto_corto(p))
    partes = [plano.plano, inicio]
    if con:
        partes.append(f"with {con}")
    partes += [accion_texto, lugar_texto]
    accion = ", ".join(p.strip() for p in partes if p.strip())

    grupo_usado = next((g for g in bible.grupos if g.frase == frase_grupo), None)
    especie_grupo = grupo_usado.especie if grupo_usado else None
    # Varios de la especie del principal (dos perros, una manada, un grupo sin especie) no
    # son clones: ahí no van "two dogs" ni "clone" en el negative.
    misma_especie = any(misma_familia(n, nucleo_principal) for _, n in figuras) or bool(
        grupo_usado and especie_grupo in (None, nucleo_principal)
    )
    grupo_otra_especie = bool(especie_grupo and especie_grupo != nucleo_principal)
    varios_de_otra = any(
        c != "one" and not misma_familia(n, nucleo_principal)
        for (_, n), c in zip(figuras, cantidades, strict=True)
    )
    hay_mas = bool(figuras or frase_grupo)
    es_protagonista = principal.rol is RolPersonaje.PROTAGONISTA
    if not es_protagonista or grupo_otra_especie or varios_de_otra:
        ip_factor = 0.0
    elif hay_mas:
        ip_factor = IP_FACTOR_CON_OTROS
    else:
        ip_factor = 1.0

    plural = plural_ingles(nucleo_principal)
    negativos = [] if misma_especie else [f"two {plural}", f"multiple {plural}"]
    if not hay_mas:
        negativos.append(NEGATIVO_CLONES)
    # Dos figuras iguales ("a girl" y "a girl") se verifican como "two girls".
    verificar = _agrupar_iguales([sujeto, *(texto for texto, _ in figuras)])
    if grupo_usado is not None and grupo_usado.plural:
        verificar.append(f"many {grupo_usado.plural}")
    mencionados = [principal.id] + [
        f.quien for f in plano.acompanantes if _personaje_o_none(bible, f.quien) is not None
    ]
    foco = FocoEscena(
        foco=principal.id, mencionados=mencionados, grupo=hay_mas, ip_factor=ip_factor
    )
    return Composicion(
        accion=accion,
        foco=foco,
        limite_descriptor=DESCRIPTOR_EN_GRUPO if hay_mas and not encoder_largo else None,
        extra_negativo=", ".join(negativos),
        verificar=verificar,
        evitar=[] if misma_especie else [f"two {plural}"],
    )


def plural_ingles(sustantivo: str) -> str:
    """'dog' -> 'dogs', 'fox' -> 'foxes', 'wolf' -> 'wolves' (para el negative prompt)."""
    irregulares = {
        "wolf": "wolves", "mouse": "mice", "fish": "fish", "deer": "deer", "sheep": "sheep",
        "person": "people", "man": "men", "woman": "women", "child": "children",
    }  # fmt: skip
    if sustantivo in irregulares:
        return irregulares[sustantivo]
    if sustantivo.endswith(("s", "x", "ch", "sh")):
        return sustantivo + "es"
    return sustantivo + "s"


def quitar_aposiciones(accion: str, sustituciones: Sequence[Sustitucion]) -> str:
    """El LLM suele repetir el tipo tras el nombre; se deja una sola mención:
    "the boy, a boy with curly hair" -> "the boy with curly hair";
    "a robot, a robot, walks" -> "a robot walks";
    "a cat, a orange cat with red spots" -> "a orange cat with red spots"."""
    for sustitucion in {s.por for s in sustituciones}:
        articulo, _, sustantivo = sustitucion.partition(" ")
        nucleo = sustantivo.split()[-1] if sustantivo else articulo
        patron = (
            rf"\b{re.escape(sustitucion)},\s+an?\s+((?:[\w-]+\s+){{0,3}}?)"
            rf"{re.escape(nucleo)}\b(,(?=\s+[a-z]+s\b))?"
        )

        def unir(m: re.Match[str], articulo: str = articulo, nucleo: str = nucleo) -> str:
            return f"{articulo} {m.group(1)}{nucleo}"

        accion = re.sub(patron, unir, accion, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", accion).strip()


@dataclass(frozen=True)
class FocoEscena:
    foco: str | None
    mencionados: list[str]
    grupo: bool
    ip_factor: float


def analizar_foco(
    bible: StoryBible, numero: int, accion: str, sustituciones: Sequence[Sustitucion] = ()
) -> FocoEscena:
    """Personaje foco de la escena y cuánto IP-Adapter usar.

    - Mencionados: los personajes presentes que la acción nombra (por nombre o por su tipo:
      "jaguar", "parrot", "man").
    - Foco: el protagonista si está mencionado; si no, el primer mencionado; si la acción no
      nombra a nadie, el protagonista (si está presente).
    - IP-Adapter (la referencia es del protagonista): completo si el foco es el protagonista
      y la acción lo nombra; reducido si es implícito, si hay otro personaje o un grupo;
      nulo si el foco es otro personaje.
    """
    escena = bible.escena(numero)
    presentes = list(escena.personajes_presentes)
    prota = bible.protagonista().id
    texto = _sin_tildes(accion).lower()
    nombrados = {s.personaje for s in sustituciones}
    mencionados: list[str] = []
    for pid in presentes:
        try:
            personaje = bible.personaje(pid)
        except KeyError:
            continue
        nombre = _sustantivo(personaje)
        if pid in nombrados or (nombre and re.search(rf"\b{re.escape(nombre)}e?s?\b", texto)):
            mencionados.append(pid)
    grupo = bool(_GRUPO.search(accion))
    if mencionados:
        foco: str | None = prota if prota in mencionados else mencionados[0]
    else:
        foco = prota if prota in presentes else (presentes[0] if presentes else None)

    if foco != prota:
        factor = 0.0
    else:
        factor = 1.0 if prota in mencionados else IP_FACTOR_IMPLICITO
        if len(mencionados) > 1:
            factor = min(factor, IP_FACTOR_CON_OTROS)
        if grupo:
            factor = min(factor, IP_FACTOR_GRUPO)
    return FocoEscena(foco=foco, mencionados=mencionados, grupo=grupo, ip_factor=factor)


def _ids_ordenados(bible: StoryBible, presentes: Sequence[str]) -> list[str]:
    """Protagonista primero (mayor peso en CLIP por ir antes), luego el orden de la escena."""
    prota = bible.protagonista().id
    return sorted(presentes, key=lambda pid: (pid != prota, list(presentes).index(pid)))


def construir_negativo(
    bible: StoryBible | None,
    base: str,
    contar: ContadorTokens,
    maximo: int,
    extra: str = "",
) -> tuple[str, list[Truncamiento]]:
    """Negative prompt común: el de la Bible, ``extra`` y el base de la configuración, sin
    repetir (lo último es lo primero que se recorta)."""
    unicas: list[str] = []
    fuentes = [bible.estilo_visual.negative_prompt if bible else "", extra, base]
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
    orden: OrdenPrompt = "estilo_primero",
    personajes: PersonajesPrompt = "presentes",
    encoder_largo: bool = False,
) -> PromptImagen:
    """Prompt y negative prompt de la escena ``numero``.

    ``usar_bible=False`` es la línea base C1 (experimentos): solo el ``prompt_imagen`` de la
    escena, sin estilo fijo ni descriptores de personajes.

    ``orden`` decide qué va primero (CLIP pesa más los primeros tokens): ``estilo_primero``
    (estilo, personajes, acción) o ``accion_primero`` (acción, personajes, estilo). En la
    prueba real de 2.3, con el estilo primero y IP-Adapter, todas las escenas salieron como
    retratos de frente del protagonista y la acción casi no se notaba. El orden de recorte
    (estilo, acción, personajes) no cambia.

    ``personajes="foco"`` (producción desde el 12 nov) pone el descriptor completo solo del
    personaje foco (``analizar_foco``) y recorta antes el descriptor que la acción; además
    devuelve ``ip_factor`` para ajustar IP-Adapter en esta escena. ``"presentes"`` es el
    comportamiento de la batería 6.2 (descriptores de todos los presentes).
    """
    try:
        escena = bible.escena(numero)
    except IndexError as exc:
        raise PromptBuilderError(f"La Bible no tiene escena {numero}") from exc
    if escena.numero != numero:
        raise PromptBuilderError(f"La escena en la posición {numero} tiene número {escena.numero}")

    bloques: list[_Bloque] = []
    ids: list[str] = []
    accion, sustituciones = sustituir_nombres(escena.prompt_imagen, bible, usar_bible=usar_bible)
    foco = analizar_foco(bible, numero, accion, sustituciones) if usar_bible else None
    extra_negativo = ""
    limite_descriptor: int | None = None
    verificar: list[str] = []
    evitar: list[str] = []
    if personajes == "foco" and foco is not None and escena.plano_visual is not None:
        # 17 nov: el ilustrador (LLM) ya dijo quién se ve, cuántos, qué hace y dónde.
        composicion = componer_plano(bible, numero, encoder_largo)
        accion, sustituciones, foco = composicion.accion, [], composicion.foco
        limite_descriptor = composicion.limite_descriptor
        extra_negativo = composicion.extra_negativo
        verificar = composicion.verificar
        evitar = composicion.evitar
    elif personajes == "foco" and foco is not None:
        # 13 nov: "boy age 10, a boy with curly hair, boy age 10, curly brown hair..." hacía
        # clones del protagonista (dos niños) y "robot age 200" no aportaba nada. En la acción
        # cada personaje queda como un sustantivo corto ("the boy", "a monkey"); la edad y
        # los rasgos van solo en el descriptor del foco.
        id_foco = foco.foco
        accion, sustituciones = sustituir_nombres(
            escena.prompt_imagen,
            bible,
            sujeto=lambda p: sujeto_corto(p, foco=p.id == id_foco),
        )
        accion = quitar_aposiciones(accion, sustituciones)
        en_grupo = grupo_de_escena(bible, numero, accion)
        foco_personaje = _personaje_o_none(bible, foco.foco)
        if en_grupo is None:
            extra_negativo = NEGATIVO_CLONES
        else:
            grupo, nombrado = en_grupo
            otra_especie = bool(
                grupo.especie
                and foco_personaje is not None
                and not re.search(
                    rf"\b{re.escape(grupo.especie)}\b", tipo_personaje(foco_personaje), re.I
                )
            )
            if otra_especie and foco_personaje is not None:
                # 13 nov (2): con "surrounded by many cats" a mitad del prompt, SDXL dibujó
                # solo perros (hasta dos). El descriptor largo del perro y la referencia del
                # IP-Adapter (un perro solo) arrastran a todos los animales hacia el perro.
                # La composición va primero, el descriptor del foco se acorta, no se usa la
                # referencia y el negative evita un segundo perro (no a los gatos).
                accion = f"{sujeto_corto(foco_personaje)} {grupo.frase}, {accion}"
                foco = replace(foco, grupo=True, ip_factor=0.0)
                limite_descriptor = DESCRIPTOR_EN_GRUPO
                sustantivo = _sustantivo(foco_personaje) or tipo_personaje(foco_personaje)
                plural = plural_ingles(sustantivo)
                extra_negativo = f"multiple {plural}, two {plural}"
            else:
                # Mismo tipo que el foco ("una manada de lobos") o grupo sin especie: varios
                # parecidos no son clones, así que no va el negative de clones.
                if not nombrado:
                    primera, _, resto = accion.partition(",")
                    accion = f"{primera}, {grupo.frase}" + (f",{resto}" if resto else "")
                foco = replace(foco, grupo=True, ip_factor=min(foco.ip_factor, IP_FACTOR_GRUPO))
                extra_negativo = ""
        if foco_personaje is not None:
            verificar = [sujeto_corto(foco_personaje)]
            if "two " in extra_negativo or extra_negativo == NEGATIVO_CLONES:
                nucleo = _sustantivo(foco_personaje) or "person"
                evitar = [f"two {plural_ingles(nucleo)}"]
        if en_grupo is not None and en_grupo[0].plural:
            verificar.append(f"many {en_grupo[0].plural}")
    bloque_tecnica: _Bloque | None = None
    if usar_bible:
        estilo = frases(bible.estilo_visual.prompt())
        if encoder_largo and orden == "accion_primero":
            # 20 nov (FLUX): con todo el estilo al final, una de cinco escenas salió como
            # foto y no como acuarela. La técnica ("watercolor with fine linework") abre el
            # prompt y no se recorta; paleta e iluminación siguen al final.
            tecnica = frases(bible.estilo_visual.tecnica)
            bloque_tecnica = _Bloque("estilo", tecnica, len(tecnica))
            estilo = estilo[len(tecnica) :]
        bloques.append(_Bloque("estilo", estilo))
        ids = _ids_ordenados(bible, escena.personajes_presentes)
        if personajes == "foco" and foco is not None:
            ids = [foco.foco] if foco.foco else []
        for pid in ids:
            try:
                personaje = bible.personaje(pid)
            except KeyError as exc:
                raise PromptBuilderError(
                    f"Personaje inexistente en la escena {numero}: {pid}"
                ) from exc
            minimo = 2 if personaje.rol is RolPersonaje.PROTAGONISTA else 1
            descriptor = frases(personaje.descripcion_visual_fija)
            if limite_descriptor:
                descriptor = descriptor[:limite_descriptor]
            bloques.append(_Bloque("personajes", descriptor, min(minimo, len(descriptor))))
    bloque_accion = _Bloque("accion", frases(accion))
    if orden == "accion_primero":
        bloques = [bloque_accion, *(b for b in bloques if b.segmento == "personajes")] + [
            b for b in bloques if b.segmento == "estilo"
        ]
        if bloque_tecnica is not None:
            bloques.insert(0, bloque_tecnica)
    else:
        bloques.append(bloque_accion)

    # En modo foco la acción es lo último que se recorta (es lo que cuenta la escena).
    prioridad = (
        {"estilo": 0, "personajes": 1, "accion": 2, "negativo": 0} if personajes == "foco" else None
    )
    prompt, truncamientos = ajustar_a_presupuesto(bloques, contar, max_tokens, prioridad)
    negativo, trunc_neg = construir_negativo(
        bible if usar_bible else None, negative_base, contar, max_tokens, extra_negativo
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
        foco=foco.foco if foco else None,
        mencionados=foco.mencionados if foco else [],
        ip_factor=foco.ip_factor if (foco and personajes == "foco") else 1.0,
        verificar=verificar,
        evitar=evitar,
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
