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
from enum import StrEnum
from typing import Annotated, Any, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

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


def _exigir_ingles(valor: str, campo: str) -> str:
    if _PATRON_NO_INGLES.search(valor):
        raise ValueError(f"{campo} debe estar escrito en inglés (sin tildes, ñ ni ¿¡)")
    return valor


def _exigir_tokens(valor: str, campo: str, maximo: int) -> str:
    tokens = estimar_tokens_clip(valor)
    if tokens > maximo:
        raise ValueError(
            f"{campo} tiene ~{tokens} tokens CLIP y el máximo es {maximo}; acórtalo "
            "usando frases nominales breves separadas por comas"
        )
    return valor


def _sin_duplicados(valores: list[Any], campo: str) -> list[Any]:
    if len(set(valores)) != len(valores):
        raise ValueError(f"{campo} contiene elementos repetidos")
    return valores


# ---------------------------------------------------------------------------------------
# Tipos base
# ---------------------------------------------------------------------------------------
IdPersonaje = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z][a-z0-9_]{1,31}$"),
    Field(description="Identificador en minúsculas, sin espacios. Ej.: 'lucia', 'capitan_ruiz'."),
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
        max_length=80,
        description="En inglés. Técnica de ilustración, ej.: 'watercolor storybook illustration'.",
    )
    paleta: str = Field(
        max_length=60, description="En inglés. Paleta de color, ej.: 'muted teal and amber'."
    )
    iluminacion: str = Field(
        max_length=60, description="En inglés. Iluminación, ej.: 'soft moonlight'."
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
            "En inglés, frases breves separadas por comas: edad, complexión, cabello, ropa y "
            "un rasgo distintivo. Ej.: 'girl age 10, slim, curly red hair, yellow raincoat, "
            "round glasses'. Se repite idéntica en todas las imágenes."
        ),
    )
    rasgos_personalidad: list[TextoCorto] = Field(min_length=1, max_length=5)
    seed: SkipJsonSchema[int | None] = Field(default=None, ge=0, le=SEED_MAX)

    @field_validator("descripcion_visual_fija")
    @classmethod
    def _descriptor_valido(cls, valor: str) -> str:
        _exigir_ingles(valor, "descripcion_visual_fija")
        return _exigir_tokens(valor, "descripcion_visual_fija", TOKENS_MAX_DESCRIPTOR)


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
        palabras = contar_palabras(valor)
        if not PALABRAS_MIN_ESCENA <= palabras <= PALABRAS_MAX_ESCENA:
            raise ValueError(
                f"texto_narrativo tiene {palabras} palabras; debe tener entre "
                f"{PALABRAS_MIN_ESCENA} y {PALABRAS_MAX_ESCENA}"
            )
        return valor

    @field_validator("resumen")
    @classmethod
    def _resumen_breve(cls, valor: str) -> str:
        if contar_palabras(valor) > PALABRAS_MAX_RESUMEN:
            raise ValueError(
                f"resumen debe ser una frase de máximo {PALABRAS_MAX_RESUMEN} palabras"
            )
        return valor

    @field_validator("prompt_imagen")
    @classmethod
    def _prompt_imagen_valido(cls, valor: str) -> str:
        _exigir_ingles(valor, "prompt_imagen")
        return _exigir_tokens(valor, "prompt_imagen", TOKENS_MAX_PROMPT_IMAGEN)

    @field_validator("prompt_sonido")
    @classmethod
    def _prompt_sonido_valido(cls, valor: str) -> str:
        _exigir_ingles(valor, "prompt_sonido")
        if contar_palabras(valor) > PALABRAS_MAX_PROMPT_SONIDO:
            raise ValueError(f"prompt_sonido supera {PALABRAS_MAX_PROMPT_SONIDO} palabras")
        return valor

    @field_validator("personajes_presentes")
    @classmethod
    def _ids_unicos(cls, valor: list[str]) -> list[str]:
        return _sin_duplicados(valor, "personajes_presentes")

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


class StoryBible(_Base):
    titulo: str = Field(min_length=3, max_length=80)
    genero: str = Field(min_length=3, max_length=GENERO_OTRO_MAX_CHARS)
    tono: str = Field(min_length=3, max_length=80, description="En español. Ej.: 'inquietante'.")
    idioma: Literal["es"] = "es"
    estilo_visual: EstiloVisual
    escenario: Escenario
    personajes: list[Personaje] = Field(min_length=1, max_length=MAX_PERSONAJES)
    escenas: list[Escena] = Field(min_length=NUM_ESCENAS, max_length=NUM_ESCENAS)
    canon: list[Hecho] = Field(
        default_factory=list,
        max_length=40,
        description="Hechos establecidos que ninguna escena posterior puede contradecir.",
    )

    @model_validator(mode="after")
    def _coherencia_estructural(self) -> StoryBible:
        _validar_numeracion([e.numero for e in self.escenas])
        _validar_reparto(
            self.personajes, [(e.numero, e.personajes_presentes) for e in self.escenas]
        )
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

    @model_validator(mode="after")
    def _fase_coherente(self) -> PlanEscena:
        if self.fase is not FASE_POR_NUMERO[self.numero]:
            raise ValueError(
                f"la escena {self.numero} debe tener fase '{FASE_POR_NUMERO[self.numero].value}'"
            )
        return self


class PlanHistoria(_Base):
    titulo: str = Field(min_length=3, max_length=80)
    genero: str = Field(min_length=3, max_length=GENERO_OTRO_MAX_CHARS)
    tono: str = Field(min_length=3, max_length=80)
    idioma: Literal["es"] = "es"
    estilo_visual: EstiloVisual
    escenario: Escenario
    personajes: list[Personaje] = Field(min_length=1, max_length=MAX_PERSONAJES)
    plan_escenas: list[PlanEscena] = Field(min_length=NUM_ESCENAS, max_length=NUM_ESCENAS)
    canon_inicial: list[Hecho] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _coherencia(self) -> PlanHistoria:
        _validar_numeracion([e.numero for e in self.plan_escenas])
        _validar_reparto(
            self.personajes, [(e.numero, e.personajes_presentes) for e in self.plan_escenas]
        )
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
