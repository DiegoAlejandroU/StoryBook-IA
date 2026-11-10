"""Story Bible y esquemas de datos de StoryBook (Pydantic v2).

La Story Bible es la ÚNICA fuente de verdad del pipeline: el LLM la produce, se valida
aquí y todas las etapas posteriores (imagen, voz, sonido, UI, evaluación) leen de ella.

Garantías que se imponen por validación de esquema (no por confianza en el LLM):

* Exactamente 5 escenas, numeradas 1..5, con el arco inicio/desarrollo/desarrollo/
  clímax/desenlace.
* Texto narrativo de 90 a 160 palabras por escena.
* Campos para el modelo de imagen y de sonido en inglés y dentro del presupuesto de
  tokens de CLIP (77 en total; ver ``image/prompt_builder.py`` para el conteo exacto).
* Un único protagonista, presente en la escena 1 y en al menos 3 escenas.
* Personajes referenciados por id existente; canon acumulado con todos los hechos.

Los campos de seed se excluyen del JSON Schema que recibe el LLM (``SkipJsonSchema``):
las seeds las asigna el código de forma determinista, no el modelo.
"""

from __future__ import annotations

import copy
import hashlib
import re
import secrets
import unicodedata
from enum import StrEnum
from typing import Annotated, Any, Final, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

from storybook.logging_utils import get_logger, kv

logger = get_logger(__name__)

# ---------------------------------------------------------------------------------------
# Límites (únicos en todo el proyecto: los prompts y los tests los importan de aquí)
# ---------------------------------------------------------------------------------------
NUM_ESCENAS: Final = 5
PALABRAS_MIN_ESCENA: Final = 90
PALABRAS_MAX_ESCENA: Final = 160
PALABRAS_MAX_RESUMEN: Final = 40
TOKENS_MAX_ESTILO: Final = 20
TOKENS_MAX_DESCRIPTOR: Final = 25
TOKENS_MAX_PROMPT_IMAGEN: Final = 25
PALABRAS_MAX_PROMPT_SONIDO: Final = 30
MAX_PERSONAJES: Final = 4
MIN_ESCENAS_PROTAGONISTA: Final = 3
MAX_HECHOS_POR_ESCENA: Final = 5
MAX_ETIQUETAS_SONIDO: Final = 3
IDEA_MIN_CHARS: Final = 10
IDEA_MAX_CHARS: Final = 600
GENERO_OTRO_MIN_CHARS: Final = 3
GENERO_OTRO_MAX_CHARS: Final = 40
SEED_MAX: Final = 2**32 - 1

_PATRON_NO_INGLES = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡]")
_PATRON_PALABRA = re.compile(r"\w+(?:[-']\w+)*", re.UNICODE)
_PATRON_TOKEN_CLIP = re.compile(r"\w+|[^\w\s]", re.UNICODE)

# Palabras funcionales frecuentes y exclusivas de cada idioma (se excluyen las que existen en
# ambos, como "a", "no", "me", "he", "has", "sin", "era" o "hay"). Bastan para distinguir
# español de inglés sin otra dependencia.
_TEXTO_FUNCIONALES_ES = (
    "el la los las del de que y en un una unos unas por con para se su sus es al lo como más "
    "pero sobre entre cuando muy ya le les este esta estos estas fue donde"
)
_TEXTO_FUNCIONALES_EN = (
    "the and of to in is are was were with his her its their that this these from into for at "
    "by it an be been have had they she you on"
)
_FUNCIONALES_ES: Final = frozenset(_TEXTO_FUNCIONALES_ES.split())
_FUNCIONALES_EN: Final = frozenset(_TEXTO_FUNCIONALES_EN.split())


# ---------------------------------------------------------------------------------------
# Enumeraciones
# ---------------------------------------------------------------------------------------
class Genero(StrEnum):
    TERROR = "terror"
    FANTASIA = "fantasia"
    MISTERIO = "misterio"
    AVENTURA = "aventura"
    CIENCIA_FICCION = "ciencia_ficcion"
    INFANTIL = "infantil"
    OTRO = "otro"


GENERO_ETIQUETA: Final[dict[Genero, str]] = {
    Genero.TERROR: "terror",
    Genero.FANTASIA: "fantasía",
    Genero.MISTERIO: "misterio",
    Genero.AVENTURA: "aventura",
    Genero.CIENCIA_FICCION: "ciencia ficción",
    Genero.INFANTIL: "infantil",
    Genero.OTRO: "otro",
}


class Fase(StrEnum):
    INICIO = "inicio"
    DESARROLLO = "desarrollo"
    CLIMAX = "climax"
    DESENLACE = "desenlace"


FASE_POR_NUMERO: Final[dict[int, Fase]] = {
    1: Fase.INICIO,
    2: Fase.DESARROLLO,
    3: Fase.DESARROLLO,
    4: Fase.CLIMAX,
    5: Fase.DESENLACE,
}


class RolPersonaje(StrEnum):
    PROTAGONISTA = "protagonista"
    ANTAGONISTA = "antagonista"
    SECUNDARIO = "secundario"


class EtiquetaSonido(StrEnum):
    """Vocabulario cerrado: cada etiqueta tiene respaldo en la biblioteca CC0 y/o en la
    síntesis procedural, así el fallback de sonido siempre encuentra algo pertinente."""

    WIND = "wind"
    RAIN = "rain"
    THUNDER = "thunder"
    FIRE = "fire"
    WATER_STREAM = "water_stream"
    OCEAN_WAVES = "ocean_waves"
    FOREST = "forest"
    BIRDS = "birds"
    NIGHT_INSECTS = "night_insects"
    FOOTSTEPS = "footsteps"
    HEARTBEAT = "heartbeat"
    DOOR_CREAK = "door_creak"
    CROWD = "crowd"
    CITY = "city"
    MACHINERY = "machinery"
    SPACESHIP_HUM = "spaceship_hum"
    DARK_DRONE = "dark_drone"
    MAGIC_SHIMMER = "magic_shimmer"
    BELLS = "bells"
    CAVE_DRIPS = "cave_drips"
    CLOCK_TICKING = "clock_ticking"


# ---------------------------------------------------------------------------------------
# Utilidades de conteo (aproximaciones explicables; el conteo exacto de CLIP se hace con
# el tokenizer real en image/prompt_builder.py)
# ---------------------------------------------------------------------------------------
def contar_palabras(texto: str) -> int:
    """Cuenta palabras (secuencias alfanuméricas, admite guiones y apóstrofes internos)."""
    return len(_PATRON_PALABRA.findall(texto))


def estimar_tokens_clip(texto: str) -> int:
    """Estimación rápida de tokens CLIP: cada palabra y cada signo cuentan como uno.

    Subestima palabras raras (BPE las parte en varios tokens), por eso los límites del
    esquema dejan margen respecto a los 77 tokens reales.
    """
    return len(_PATRON_TOKEN_CLIP.findall(texto))


def derivar_seed(base_seed: int, *partes: str | int) -> int:
    """Seed determinista de 32 bits a partir de una seed base y etiquetas.

    Se usa SHA-256 (y no ``hash()``) porque ``hash()`` de Python cambia entre ejecuciones.
    """
    clave = "|".join([str(base_seed), *map(str, partes)]).encode("utf-8")
    return int.from_bytes(hashlib.sha256(clave).digest()[:4], "big")


def parece_ingles(texto: str) -> bool:
    """True si ``texto`` tiene más palabras funcionales inglesas que españolas.

    En F1 el 4B escribió una historia de ciencia ficción entera en inglés (título, resúmenes
    y narración) porque los campos para el ilustrador van en inglés; Piper la habría leído con
    voz española. En textos cortos (títulos, resúmenes) basta una palabra inglesa; en textos
    largos se exigen al menos tres para tolerar nombres propios o una cita aislada.
    """
    palabras = [p.lower() for p in _PATRON_PALABRA.findall(texto)]
    ingles = sum(p in _FUNCIONALES_EN for p in palabras)
    espanol = sum(p in _FUNCIONALES_ES for p in palabras)
    minimo = 1 if len(palabras) <= 20 else 3
    return ingles >= minimo and ingles > espanol


def _exigir_espanol(valor: str, campo: str) -> str:
    if parece_ingles(valor):
        raise ValueError(
            f"{campo} parece estar en inglés; escríbelo en español (solo los campos para el "
            "ilustrador y el sonidista van en inglés)"
        )
    return valor


def parece_espanol(texto: str) -> bool:
    """Simétrico de :func:`parece_ingles`, para los campos que deben ir en inglés."""
    palabras = [p.lower() for p in _PATRON_PALABRA.findall(texto)]
    ingles = sum(p in _FUNCIONALES_EN for p in palabras)
    espanol = sum(p in _FUNCIONALES_ES for p in palabras)
    minimo = 1 if len(palabras) <= 20 else 3
    return espanol >= minimo and espanol > ingles


def _sin_tildes(texto: str) -> str:
    """'Tomás, niña' -> 'Tomas, nina'; quita también ¿ y ¡."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    limpio = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return limpio.replace("¿", "").replace("¡", "")


def _exigir_ingles(valor: str, campo: str) -> str:
    """Rechaza el campo si está en español; si solo tiene tildes (un nombre como 'Tomás'),
    las quita. En F1 rechazar por una tilde agotó los 4 intentos de una escena: el modelo
    repetía el nombre del personaje en ``prompt_imagen``."""
    if parece_espanol(valor):
        raise ValueError(f"{campo} debe estar en inglés (parece español)")
    return _sin_tildes(valor) if _PATRON_NO_INGLES.search(valor) else valor


def _exigir_tokens(valor: str, campo: str, maximo: int) -> str:
    tokens = estimar_tokens_clip(valor)
    if tokens > maximo:
        raise ValueError(
            f"{campo} tiene ~{tokens} tokens CLIP y el máximo es {maximo}; acórtalo "
            "usando frases nominales breves separadas por comas"
        )
    return valor


# 'age: 12, hair: short and black' -> 'age 12, short and black hair'. En F1 la mitad de los
# descriptores llegaron con etiquetas, a veces en español ('edad: 30, cabello: ...'): para
# CLIP son tokens sin contenido visual. Solo se tocan etiquetas conocidas.
_ETIQUETAS_DESCRIPTOR: Final[dict[str, str]] = {
    **dict.fromkeys(("age", "edad"), "age {}"),
    **dict.fromkeys(("hair", "cabello", "pelo"), "{} hair"),
    **dict.fromkeys(("eyes", "ojos"), "{} eyes"),
    **dict.fromkeys(("build", "complexion", "complexión", "body"), "{} build"),
    **dict.fromkeys(
        (
            "clothes",
            "clothing",
            "outfit",
            "ropa",
            "vestimenta",
            "feature",
            "distinct feature",
            "distinctive feature",
            "distinguishing feature",
            "rasgo",
            "rasgo distintivo",
        ),
        "{}",
    ),
}
_PATRON_ETIQUETA = re.compile(r"^([^\W\d][\w ]{0,30}?)\s*:\s*(\S.*)$", re.UNICODE)


def quitar_etiquetas_descriptor(valor: str) -> str:
    frases: list[str] = []
    for frase in _frases(valor):
        limpia = frase
        coincidencia = _PATRON_ETIQUETA.match(frase)
        if coincidencia:
            etiqueta = coincidencia.group(1).replace("_", " ").strip().lower()
            plantilla = _ETIQUETAS_DESCRIPTOR.get(etiqueta)
            if plantilla:
                limpia = plantilla.format(coincidencia.group(2).strip())
        frases.append(limpia)
    return ", ".join(frases)


def _frases(valor: str) -> list[str]:
    return [f.strip() for f in valor.split(",") if f.strip()]


def _ajustar_tokens(valor: str, campo: str, maximo: int) -> str:
    """Si el campo se pasa del presupuesto CLIP, quita frases del final (separadas por comas)
    hasta que quepa; solo es error si ni la primera frase cabe.

    En F1, 14 de 31 reintentos fueron por pasarse 1-5 tokens; cada reintento del plan cuesta
    ~16 s. Las primeras frases son las importantes (los prompts piden ese orden) y
    ``image/prompt_builder.py`` vuelve a verificar los 77 tokens con el tokenizer real.
    """
    if estimar_tokens_clip(valor) <= maximo:
        return valor
    frases = _frases(valor)
    while len(frases) > 1 and estimar_tokens_clip(", ".join(frases)) > maximo:
        frases.pop()
    recortado = _exigir_tokens(", ".join(frases), campo, maximo)
    logger.info("campo_recortado_a_presupuesto_clip", extra=kv(campo=campo, antes=valor))
    return recortado


def _sin_duplicados(valores: list[Any], campo: str) -> list[Any]:
    if len(set(valores)) != len(valores):
        raise ValueError(f"{campo} contiene elementos repetidos")
    return valores


# ---------------------------------------------------------------------------------------
# Tipos base
# ---------------------------------------------------------------------------------------
def _normalizar_id(valor: Any) -> Any:
    """'Lucía Pérez' -> 'lucia_perez'. Ollama ordena las claves del JSON alfabéticamente, así
    que el LLM escribe ``escenas`` antes que ``personajes`` y a veces usa el nombre en vez del
    id; normalizar evita rechazar la Bible por mayúsculas, tildes o espacios."""
    if not isinstance(valor, str):
        return valor
    texto = unicodedata.normalize("NFKD", valor.strip().lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9]+", "_", texto).strip("_")
    return f"p_{texto}" if texto[:1].isdigit() else texto


IdPersonaje = Annotated[
    str,
    BeforeValidator(_normalizar_id),
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z][a-z0-9_]{1,31}$"),
    # Sin nombres de ejemplo: en F1 el 4B copió los del prompt ('lena', 'capitan_ruiz') en la
    # mitad de las historias.
    Field(description="El nombre del personaje en minúsculas, sin tildes y con '_' por espacios."),
]
TextoCorto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
Hecho = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=220)]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------------------
# Entrada del usuario
# ---------------------------------------------------------------------------------------
class StoryRequest(_Base):
    """Las DOS únicas entradas de la aplicación: idea y género."""

    idea: str = Field(min_length=IDEA_MIN_CHARS, max_length=IDEA_MAX_CHARS)
    genero: Genero
    genero_otro: str | None = Field(default=None, max_length=GENERO_OTRO_MAX_CHARS)

    @field_validator("idea")
    @classmethod
    def _normalizar_idea(cls, valor: str) -> str:
        valor = re.sub(r"\s+", " ", valor).strip()
        if sum(c.isalpha() for c in valor) < 5:
            raise ValueError("la idea debe contener texto descriptivo (al menos 5 letras)")
        return valor

    @model_validator(mode="after")
    def _validar_genero_otro(self) -> StoryRequest:
        if self.genero is Genero.OTRO:
            texto = re.sub(r"\s+", " ", self.genero_otro or "").strip()
            if len(texto) < GENERO_OTRO_MIN_CHARS:
                raise ValueError(
                    f"si el género es 'otro', escribe cuál (mínimo {GENERO_OTRO_MIN_CHARS} "
                    "caracteres)"
                )
            self.genero_otro = texto
        else:
            self.genero_otro = None
        return self

    @property
    def genero_efectivo(self) -> str:
        """Etiqueta legible que recibe el LLM (incluye el texto libre si es 'otro')."""
        if self.genero is Genero.OTRO and self.genero_otro:
            return self.genero_otro
        return GENERO_ETIQUETA[self.genero]


class InputValidationError(ValueError):
    """Entrada inválida, con mensajes en español listos para mostrar en la UI."""

    def __init__(self, mensajes: list[str]) -> None:
        super().__init__("; ".join(mensajes))
        self.mensajes = mensajes


_CAMPOS_ES = {"idea": "La idea", "genero": "El género", "genero_otro": "El género 'otro'"}


def validar_entrada(idea: str, genero: str, genero_otro: str | None = None) -> StoryRequest:
    """Valida las entradas del formulario y traduce los errores al español."""
    try:
        return StoryRequest(idea=idea, genero=genero, genero_otro=genero_otro)  # type: ignore[arg-type]
    except ValidationError as exc:
        mensajes: list[str] = []
        for error in exc.errors():
            campo = str(error["loc"][0]) if error["loc"] else ""
            nombre = _CAMPOS_ES.get(campo, "La entrada")
            tipo = error["type"]
            ctx = error.get("ctx") or {}
            if tipo == "string_too_short":
                mensajes.append(
                    f"{nombre} es obligatoria (mínimo {ctx.get('min_length')} caracteres)."
                )
            elif tipo == "string_too_long":
                mensajes.append(f"{nombre} supera el máximo de {ctx.get('max_length')} caracteres.")
            elif tipo == "enum":
                opciones = ", ".join(g.value for g in Genero)
                mensajes.append(f"{nombre} no es válido. Opciones: {opciones}.")
            elif tipo in {"missing", "string_type"}:
                mensajes.append(f"{nombre} es obligatorio.")
            else:
                texto = str(error["msg"]).removeprefix("Value error, ")
                mensajes.append(texto[:1].upper() + texto[1:])
        raise InputValidationError(mensajes) from exc


# ---------------------------------------------------------------------------------------
# Story Bible
# ---------------------------------------------------------------------------------------
class EstiloVisual(_Base):
    """Estilo fijo para TODA la historia. Va al inicio de cada prompt de imagen."""

    tecnica: str = Field(
        max_length=120,
        description="En inglés. Técnica de ilustración, ej.: 'watercolor storybook illustration'.",
    )
    # Los límites de caracteres son holgados: el que manda es TOKENS_MAX_ESTILO, que se ajusta
    # quitando frases. En F1 el 8B escribió una iluminación de 62 caracteres en 4 intentos.
    paleta: str = Field(
        max_length=120, description="En inglés. Paleta de color, ej.: 'muted teal and amber'."
    )
    iluminacion: str = Field(
        max_length=120, description="En inglés. Iluminación, ej.: 'soft moonlight'."
    )
    negative_prompt: str = Field(
        max_length=300,
        description="En inglés. Elementos a evitar en todas las imágenes, separados por comas.",
    )

    @field_validator("tecnica", "paleta", "iluminacion", "negative_prompt")
    @classmethod
    def _en_ingles(cls, valor: str, info: Any) -> str:
        return _exigir_ingles(valor, f"estilo_visual.{info.field_name}")

    def prompt(self) -> str:
        return f"{self.tecnica}, {self.paleta}, {self.iluminacion}"

    @model_validator(mode="after")
    def _presupuesto_tokens(self) -> EstiloVisual:
        # Si se pasa, se quita la última frase del campo más largo que tenga varias.
        campos = ("tecnica", "paleta", "iluminacion")
        while estimar_tokens_clip(self.prompt()) > TOKENS_MAX_ESTILO:
            recortables = [c for c in campos if len(_frases(getattr(self, c))) > 1]
            if not recortables:
                break
            campo = max(recortables, key=lambda c: estimar_tokens_clip(getattr(self, c)))
            setattr(self, campo, ", ".join(_frases(getattr(self, campo))[:-1]))
            logger.info("campo_recortado_a_presupuesto_clip", extra=kv(campo=campo))
        _exigir_tokens(
            self.prompt(), "estilo_visual (tecnica+paleta+iluminacion)", TOKENS_MAX_ESTILO
        )
        return self


class Escenario(_Base):
    lugar: TextoCorto = Field(description="En español. Lugar principal de la historia.")
    epoca: TextoCorto = Field(description="En español. Época o momento histórico.")
    rasgos_constantes: list[TextoCorto] = Field(
        min_length=1,
        max_length=5,
        description="En español. Rasgos del escenario que no cambian entre escenas.",
    )


class Personaje(_Base):
    id: IdPersonaje
    nombre: str = Field(min_length=2, max_length=40)
    rol: RolPersonaje
    descripcion_visual_fija: str = Field(
        max_length=200,
        description=(
            "En inglés, frases breves separadas por comas, de la más a la menos importante: "
            "edad, cabello, ropa, rasgo distintivo y complexión. Ej.: 'girl age 10, curly red "
            "hair, yellow raincoat, round glasses, slim'. Se repite idéntica en todas las "
            "imágenes."
        ),
    )
    rasgos_personalidad: list[TextoCorto] = Field(min_length=1, max_length=5)
    seed: SkipJsonSchema[int | None] = Field(default=None, ge=0, le=SEED_MAX)

    @field_validator("descripcion_visual_fija")
    @classmethod
    def _descriptor_valido(cls, valor: str) -> str:
        valor = quitar_etiquetas_descriptor(valor)
        valor = _exigir_ingles(valor, "descripcion_visual_fija")
        return _ajustar_tokens(valor, "descripcion_visual_fija", TOKENS_MAX_DESCRIPTOR)


class Escena(_Base):
    numero: int = Field(ge=1, le=NUM_ESCENAS)
    fase: Fase = Field(description="1=inicio, 2=desarrollo, 3=desarrollo, 4=climax, 5=desenlace.")
    texto_narrativo: str = Field(
        description=(
            f"En español, narración de {PALABRAS_MIN_ESCENA} a {PALABRAS_MAX_ESCENA} palabras, "
            "acorde al género."
        )
    )
    resumen: str = Field(max_length=260, description="En español, una sola frase.")
    personajes_presentes: list[IdPersonaje] = Field(max_length=MAX_PERSONAJES)
    hechos_nuevos: list[Hecho] = Field(
        max_length=MAX_HECHOS_POR_ESCENA,
        description="En español. Hechos que esta escena establece y que no pueden contradecirse.",
    )
    prompt_imagen: str = Field(
        max_length=200,
        description=(
            "En inglés: SOLO acción, composición y entorno (sin describir personajes ni estilo, "
            "eso se añade aparte)."
        ),
    )
    prompt_sonido: str = Field(
        max_length=220,
        description="En inglés: un ambiente de fondo y 1-2 efectos. Sin voces ni música.",
    )
    etiquetas_sonido: list[EtiquetaSonido] = Field(min_length=1, max_length=MAX_ETIQUETAS_SONIDO)
    seed_imagen: SkipJsonSchema[int | None] = Field(default=None, ge=0, le=SEED_MAX)

    @field_validator("texto_narrativo")
    @classmethod
    def _longitud_texto(cls, valor: str) -> str:
        _exigir_espanol(valor, "texto_narrativo")
        palabras = contar_palabras(valor)
        if not PALABRAS_MIN_ESCENA <= palabras <= PALABRAS_MAX_ESCENA:
            raise ValueError(
                f"texto_narrativo tiene {palabras} palabras; debe tener entre "
                f"{PALABRAS_MIN_ESCENA} y {PALABRAS_MAX_ESCENA} (escribe de 10 a 12 oraciones)"
            )
        return valor

    @field_validator("resumen")
    @classmethod
    def _resumen_breve(cls, valor: str) -> str:
        _exigir_espanol(valor, "resumen")
        if contar_palabras(valor) > PALABRAS_MAX_RESUMEN:
            raise ValueError(
                f"resumen debe ser una frase de máximo {PALABRAS_MAX_RESUMEN} palabras"
            )
        return valor

    @field_validator("prompt_imagen")
    @classmethod
    def _prompt_imagen_valido(cls, valor: str) -> str:
        valor = _exigir_ingles(valor, "prompt_imagen")
        return _ajustar_tokens(valor, "prompt_imagen", TOKENS_MAX_PROMPT_IMAGEN)

    @field_validator("prompt_sonido")
    @classmethod
    def _prompt_sonido_valido(cls, valor: str) -> str:
        valor = _exigir_ingles(valor, "prompt_sonido")
        if contar_palabras(valor) > PALABRAS_MAX_PROMPT_SONIDO:
            raise ValueError(f"prompt_sonido supera {PALABRAS_MAX_PROMPT_SONIDO} palabras")
        return valor

    @field_validator("personajes_presentes")
    @classmethod
    def _ids_unicos(cls, valor: list[str]) -> list[str]:
        # Tras normalizar, 'Lucía' y 'lucia' son el mismo id: se quitan los repetidos.
        return list(dict.fromkeys(valor))

    @field_validator("etiquetas_sonido")
    @classmethod
    def _etiquetas_unicas(cls, valor: list[EtiquetaSonido]) -> list[EtiquetaSonido]:
        return _sin_duplicados(valor, "etiquetas_sonido")

    @model_validator(mode="after")
    def _fase_coherente(self) -> Escena:
        esperada = FASE_POR_NUMERO[self.numero]
        if self.fase is not esperada:
            raise ValueError(
                f"la escena {self.numero} debe tener fase '{esperada.value}', "
                f"no '{self.fase.value}'"
            )
        return self


def resolver_ids_por_nombre(personajes: list[Personaje], presentes: list[str]) -> list[str]:
    """Cambia ids desconocidos por el id del personaje cuyo nombre coincide sin ambigüedad.

    En F1 el 4B dio ids genéricos ('protagonista', 'p_1') y luego, en las escenas, escribió el
    nombre ('lena', 'nexo_7'): la Bible se rechazaba en las 3 historias. Se acepta el nombre
    completo normalizado o una palabra de él (de 3 letras o más) si identifica a un solo
    personaje; lo demás sigue siendo un error de validación.
    """
    conocidos = {p.id for p in personajes}
    alias: dict[str, set[str]] = {}
    for personaje in personajes:
        nombre = _normalizar_id(personaje.nombre)
        for clave in {nombre, *nombre.split("_")}:
            if len(clave) >= 3:
                alias.setdefault(clave, set()).add(personaje.id)
    resueltos: list[str] = []
    for valor in presentes:
        candidatos = alias.get(valor, set()) if valor not in conocidos else {valor}
        nuevo = next(iter(candidatos)) if len(candidatos) == 1 else valor
        if nuevo not in resueltos:
            resueltos.append(nuevo)
    return resueltos


def normalizar_protagonista(
    personajes: list[Personaje], presencias: list[tuple[int, list[str]]]
) -> None:
    """Deja exactamente un protagonista: el que está en la escena 1 y en más escenas.

    En F1 el 4B insistió en dos protagonistas (un robot y una científica) durante los 4
    intentos. El rol es una etiqueta que el código puede fijar: la consistencia visual se
    mide sobre el protagonista, así que se elige el personaje más presente desde el inicio
    y los demás protagonistas pasan a secundarios.
    """
    protagonistas = [p for p in personajes if p.rol is RolPersonaje.PROTAGONISTA]
    if len(protagonistas) == 1:
        return
    candidatos = protagonistas or personajes

    def presencia(personaje: Personaje) -> tuple[bool, int]:
        en_escenas = [n for n, presentes in presencias if personaje.id in presentes]
        return 1 in en_escenas, len(en_escenas)

    elegido = max(candidatos, key=presencia)  # max conserva el primero si hay empate
    for personaje in protagonistas:
        if personaje is not elegido:
            personaje.rol = RolPersonaje.SECUNDARIO
    elegido.rol = RolPersonaje.PROTAGONISTA
    logger.info(
        "protagonista_normalizado",
        extra=kv(elegido=elegido.id, antes=[p.id for p in protagonistas]),
    )


def _validar_reparto(personajes: list[Personaje], presencias: list[tuple[int, list[str]]]) -> None:
    """Reglas de personajes compartidas por StoryBible y PlanHistoria."""
    ids = [p.id for p in personajes]
    _sin_duplicados(ids, "ids de personajes")
    protagonistas = [p for p in personajes if p.rol is RolPersonaje.PROTAGONISTA]
    if len(protagonistas) != 1:
        raise ValueError(f"debe haber exactamente 1 protagonista y hay {len(protagonistas)}")
    conocidos = set(ids)
    for numero, presentes in presencias:
        desconocidos = sorted(set(presentes) - conocidos)
        if desconocidos:
            raise ValueError(
                f"la escena {numero} usa ids de personaje inexistentes: {desconocidos}"
            )
    prota = protagonistas[0].id
    apariciones = [numero for numero, presentes in presencias if prota in presentes]
    if 1 not in apariciones:
        raise ValueError(f"el protagonista '{prota}' debe aparecer en la escena 1")
    if len(apariciones) < MIN_ESCENAS_PROTAGONISTA:
        raise ValueError(
            f"el protagonista '{prota}' aparece en {len(apariciones)} escenas; mínimo "
            f"{MIN_ESCENAS_PROTAGONISTA} (la consistencia visual se mide sobre él)"
        )


def _validar_numeracion(numeros: list[int]) -> None:
    if numeros != list(range(1, NUM_ESCENAS + 1)):
        raise ValueError(f"las escenas deben estar numeradas 1..{NUM_ESCENAS} en orden: {numeros}")


# El género lo elige el usuario: el código lo copia de la solicitud y el LLM no lo escribe.
# En F1 el 4B escribió géneros de más de 40 caracteres ("terror psicológico con ...") en los
# 4 intentos y dos historias de terror se perdieron por eso.
GeneroBible = SkipJsonSchema[str]


class StoryBible(_Base):
    titulo: str = Field(min_length=3, max_length=80)
    genero: GeneroBible = Field(default="", max_length=GENERO_OTRO_MAX_CHARS)
    tono: str = Field(min_length=3, max_length=80, description="En español. Ej.: 'inquietante'.")
    idioma: Literal["es"] = "es"
    estilo_visual: EstiloVisual
    escenario: Escenario
    personajes: list[Personaje] = Field(min_length=1, max_length=MAX_PERSONAJES)
    escenas: list[Escena] = Field(min_length=NUM_ESCENAS, max_length=NUM_ESCENAS)
    # Fuera del esquema del LLM: el validador lo construye con los hechos_nuevos de cada
    # escena. Si el modelo lo escribe, duplica todos los hechos y agota num_predict (F0).
    canon: SkipJsonSchema[list[Hecho]] = Field(
        default_factory=list,
        max_length=40,
        description="Hechos establecidos que ninguna escena posterior puede contradecir.",
    )

    @field_validator("titulo")
    @classmethod
    def _titulo_en_espanol(cls, valor: str) -> str:
        return _exigir_espanol(valor, "titulo")

    @model_validator(mode="after")
    def _coherencia_estructural(self) -> StoryBible:
        _validar_numeracion([e.numero for e in self.escenas])
        for escena in self.escenas:
            escena.personajes_presentes[:] = resolver_ids_por_nombre(
                self.personajes, escena.personajes_presentes
            )
        presencias = [(e.numero, e.personajes_presentes) for e in self.escenas]
        normalizar_protagonista(self.personajes, presencias)
        _validar_reparto(self.personajes, presencias)
        # El canon siempre contiene todos los hechos nuevos, en orden y sin duplicados.
        acumulado: list[str] = []
        for hecho in [*self.canon, *(h for e in self.escenas for h in e.hechos_nuevos)]:
            if hecho not in acumulado:
                acumulado.append(hecho)
        self.canon = acumulado
        return self

    # ---- Consultas que usan las etapas posteriores -------------------------------------
    def protagonista(self) -> Personaje:
        return next(p for p in self.personajes if p.rol is RolPersonaje.PROTAGONISTA)

    def personaje(self, personaje_id: str) -> Personaje:
        for personaje in self.personajes:
            if personaje.id == personaje_id:
                return personaje
        raise KeyError(personaje_id)

    def escena(self, numero: int) -> Escena:
        return self.escenas[numero - 1]

    def canon_hasta(self, numero: int) -> list[str]:
        """Hechos vigentes ANTES de la escena ``numero`` (contexto para generarla)."""
        posteriores = {h for e in self.escenas if e.numero >= numero for h in e.hechos_nuevos}
        return [h for h in self.canon if h not in posteriores]

    def resumenes_previos(self, numero: int) -> list[str]:
        return [f"Escena {e.numero}: {e.resumen}" for e in self.escenas if e.numero < numero]

    def con_seeds(
        self,
        base_seed: int,
        fija: bool = True,
        politica: Literal["compartida", "por_escena"] = "compartida",
    ) -> StoryBible:
        """Copia con seeds asignadas por el código (reproducibles y registradas).

        * ``fija=False`` (línea base C1): seeds aleatorias, igualmente registradas.
        * ``politica="compartida"``: todas las escenas usan la seed del protagonista
          (mismo ruido inicial: favorece la consistencia visual).
        * ``politica="por_escena"``: seed derivada por número de escena.
        """
        copia = self.model_copy(deep=True)

        def _seed(*partes: str | int) -> int:
            return derivar_seed(base_seed, *partes) if fija else secrets.randbelow(SEED_MAX)

        for personaje in copia.personajes:
            personaje.seed = _seed("personaje", personaje.id)
        seed_prota = copia.protagonista().seed
        for escena in copia.escenas:
            if fija and politica == "compartida":
                escena.seed_imagen = seed_prota
            else:
                escena.seed_imagen = _seed("escena", escena.numero)
        return copia

    @classmethod
    def desde_plan(cls, plan: PlanHistoria, escenas: list[Escena]) -> StoryBible:
        """Ensambla la Bible en la estrategia (b): plan + escenas expandidas una a una."""
        return cls(
            titulo=plan.titulo,
            genero=plan.genero,
            tono=plan.tono,
            estilo_visual=plan.estilo_visual,
            escenario=plan.escenario,
            personajes=plan.personajes,
            escenas=escenas,
            canon=list(plan.canon_inicial),
        )


# ---------------------------------------------------------------------------------------
# Estrategia (b): plan primero, luego expansión escena por escena
# ---------------------------------------------------------------------------------------
class PlanEscena(_Base):
    numero: int = Field(ge=1, le=NUM_ESCENAS)
    fase: Fase
    resumen: str = Field(max_length=260, description="En español, una frase.")
    personajes_presentes: list[IdPersonaje] = Field(max_length=MAX_PERSONAJES)

    @field_validator("resumen")
    @classmethod
    def _resumen_en_espanol(cls, valor: str) -> str:
        return _exigir_espanol(valor, "resumen")

    @model_validator(mode="after")
    def _fase_coherente(self) -> PlanEscena:
        if self.fase is not FASE_POR_NUMERO[self.numero]:
            raise ValueError(
                f"la escena {self.numero} debe tener fase '{FASE_POR_NUMERO[self.numero].value}'"
            )
        return self


class PlanHistoria(_Base):
    titulo: str = Field(min_length=3, max_length=80)
    genero: GeneroBible = Field(default="", max_length=GENERO_OTRO_MAX_CHARS)
    tono: str = Field(min_length=3, max_length=80)
    idioma: Literal["es"] = "es"
    estilo_visual: EstiloVisual
    escenario: Escenario
    personajes: list[Personaje] = Field(min_length=1, max_length=MAX_PERSONAJES)
    plan_escenas: list[PlanEscena] = Field(min_length=NUM_ESCENAS, max_length=NUM_ESCENAS)
    canon_inicial: list[Hecho] = Field(default_factory=list, max_length=10)

    @field_validator("titulo")
    @classmethod
    def _titulo_en_espanol(cls, valor: str) -> str:
        return _exigir_espanol(valor, "titulo")

    @model_validator(mode="after")
    def _coherencia(self) -> PlanHistoria:
        _validar_numeracion([e.numero for e in self.plan_escenas])
        for escena in self.plan_escenas:
            escena.personajes_presentes[:] = resolver_ids_por_nombre(
                self.personajes, escena.personajes_presentes
            )
        presencias = [(e.numero, e.personajes_presentes) for e in self.plan_escenas]
        normalizar_protagonista(self.personajes, presencias)
        _validar_reparto(self.personajes, presencias)
        return self


# ---------------------------------------------------------------------------------------
# Auditor de coherencia
# ---------------------------------------------------------------------------------------
class Contradiccion(_Base):
    escena: int = Field(ge=1, le=NUM_ESCENAS)
    tipo: Literal["nombre", "rasgo", "hecho", "escenario", "estilo", "secuencia"]
    severidad: Literal["critica", "menor"]
    descripcion: str = Field(min_length=5, max_length=300)


class AuditoriaCoherencia(_Base):
    coherente: bool
    contradicciones: list[Contradiccion] = Field(default_factory=list, max_length=15)

    @property
    def escenas_criticas(self) -> list[int]:
        """Escenas que deben regenerarse (contradicciones críticas)."""
        return sorted({c.escena for c in self.contradicciones if c.severidad == "critica"})


# ---------------------------------------------------------------------------------------
# JSON Schema para la salida estructurada de Ollama
# ---------------------------------------------------------------------------------------
def _inline_refs(nodo: Any, defs: dict[str, Any]) -> Any:
    if isinstance(nodo, dict):
        if "$ref" in nodo:
            nombre = nodo["$ref"].rsplit("/", 1)[-1]
            resuelto = _inline_refs(copy.deepcopy(defs[nombre]), defs)
            hermanos = {k: v for k, v in nodo.items() if k != "$ref"}
            return {**resuelto, **_inline_refs(hermanos, defs)}
        if "allOf" in nodo and len(nodo["allOf"]) == 1:
            base = _inline_refs(nodo["allOf"][0], defs)
            hermanos = {k: v for k, v in nodo.items() if k != "allOf"}
            return {**base, **_inline_refs(hermanos, defs)}
        return {k: _inline_refs(v, defs) for k, v in nodo.items() if k != "$defs"}
    if isinstance(nodo, list):
        return [_inline_refs(v, defs) for v in nodo]
    return nodo


_CLAVES_LONGITUD = frozenset({"minLength", "maxLength", "pattern"})


def _sin_restricciones_de_texto(nodo: Any) -> Any:
    if isinstance(nodo, dict):
        return {
            k: _sin_restricciones_de_texto(v) for k, v in nodo.items() if k not in _CLAVES_LONGITUD
        }
    if isinstance(nodo, list):
        return [_sin_restricciones_de_texto(v) for v in nodo]
    return nodo


def esquema_json_llm(modelo: type[BaseModel], relajado: bool = True) -> dict[str, Any]:
    """JSON Schema autocontenido (sin ``$ref``) para el parámetro ``format`` de Ollama.

    Con ``relajado=True`` (por defecto) se quitan ``minLength``, ``maxLength`` y ``pattern``:
    llama.cpp convierte cada límite de longitud en una repetición expandida de la gramática y,
    con textos de cientos de caracteres, la generación se vuelve extremadamente lenta (en F0 se
    agotaron 600 s sin terminar). Las longitudes se siguen validando con Pydantic al recibir la
    respuesta, y los errores se devuelven al modelo en el reintento. Se conservan la estructura,
    ``required``, ``enum``, ``const`` y ``minItems``/``maxItems`` (exactamente 5 escenas).

    Se expanden las referencias porque la conversión de JSON Schema a gramática de
    algunos motores no resuelve ``$defs`` de forma fiable.
    """
    esquema = modelo.model_json_schema()
    defs = esquema.get("$defs", {})
    completo = _inline_refs(esquema, defs)
    return _sin_restricciones_de_texto(completo) if relajado else completo
