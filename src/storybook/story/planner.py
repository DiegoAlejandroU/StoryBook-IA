"""Planificador de la Story Bible con el LLM local.

Dos estrategias (experimento de F6, CLAUDE.md §10):

* ``una_llamada`` (a): una sola llamada produce la Bible completa. Menos latencia, pero el
  modelo debe mantener 5 escenas coherentes en una sola salida larga.
* ``por_etapas`` (b): primero el plan (título, estilo, escenario, personajes, resumen de las
  5 escenas) y luego cada escena por separado, recibiendo el canon acumulado y los resúmenes
  previos. Más llamadas, pero cada salida es corta y el contexto de continuidad es explícito.

En ambas, el número de escenas, las fases y los personajes presentes los garantiza el
código (validación Pydantic + datos del plan), no la confianza en el LLM.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from storybook.config import LLMConfig
from storybook.logging_utils import get_logger, kv
from storybook.schemas import (
    NUM_ESCENAS,
    Escena,
    PlanHistoria,
    PlanoVisual,
    StoryBible,
    StoryRequest,
    derivar_seed,
)
from storybook.story.llm_client import GeneracionValidada, errores_validacion
from storybook.story.prompts import (
    REGLAS_GENERO,
    mensaje_reparacion,
    mensajes_bible,
    mensajes_escena,
    mensajes_plan,
    mensajes_plano_visual,
)
from storybook.story.reparto import (
    grupos_pedidos,
    mencionado,
    mensaje_correccion,
    precisar_personas,
    problemas_reparto,
    singular_ingles,
)

logger = get_logger(__name__)

Estrategia = Literal["una_llamada", "por_etapas"]
M = TypeVar("M", bound=BaseModel)


AVISO_REPARTO = "texto:reparto_no_coincide"
AVISO_PLANO = "texto:plano_visual_fallido"
TEMPERATURA_PLANO = 0.3  # describe lo que ya está escrito: poca creatividad


def ajustar_plano(plano: PlanoVisual, escena: Escena, plan: PlanHistoria) -> PlanoVisual:
    """Deja en el plano solo a quien está en la escena.

    El principal debe ser un personaje presente (si no, el protagonista si está, o el primero
    presente). Un acompañante con id que no está en la escena, o que repite al principal, se
    quita. Una figura sin nombre (una especie, un objeto) se deja solo si la escena la nombra
    o es el grupo que pide la idea (18 nov: aparecían gatos en la historia de un dragón).
    """
    presentes = list(escena.personajes_presentes)
    ids = {p.id for p in plan.personajes}
    # El 4B a veces pone el nombre ("pulpo" por "pulpo", "Don Pulpo" por "don_pulpo").
    por_nombre = {p.nombre.strip().lower(): p.id for p in plan.personajes}

    def _id(quien: str) -> str:
        return quien if quien in ids else por_nombre.get(quien.replace("_", " "), quien)

    principal = _id(plano.principal)
    if principal not in presentes:
        protagonista = next((p.id for p in plan.personajes if p.rol.value == "protagonista"), None)
        principal = protagonista if protagonista in presentes else (presentes or [principal])[0]
    acompanantes = []
    for figura in plano.acompanantes:
        figura = figura.model_copy(update={"quien": _id(figura.quien)})
        if figura.quien == principal or (figura.quien in ids and figura.quien not in presentes):
            continue
        if any(f.quien == figura.quien for f in acompanantes):
            continue
        if figura.quien not in ids and not (
            mencionado(figura.quien, escena.texto_narrativo, escena.prompt_imagen)
            or any(g.especie and g.especie == singular_ingles(figura.quien) for g in plan.grupos)
        ):
            continue
        acompanantes.append(figura)
    return plano.model_copy(update={"principal": principal, "acompanantes": acompanantes})


class PlannerError(Exception):
    """La historia no pudo ensamblarse en una Story Bible válida."""


class LLMBackend(Protocol):
    """Interfaz mínima del LLM que usan el planificador y el auditor (``OllamaClient``)."""

    def generar_validado(
        self,
        *,
        modelo_salida: type[M],
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        num_ctx: int,
        max_reintentos: int,
        think: bool | None = ...,
        keep_alive: str | int = ...,
        seed: int | None = ...,
        reparar: Any = ...,
        num_predict: int | None = ...,
        opciones_extra: dict[str, Any] | None = ...,
    ) -> GeneracionValidada[M]: ...

    def unload(self, modelo: str) -> None: ...


@dataclass(frozen=True)
class RegistroLlamada:
    """Trazabilidad de una llamada al LLM (va al manifest y al reporte de experimentos)."""

    etapa: str
    intentos: int
    segundos: float
    prompt_tokens: int
    output_tokens: int
    errores_por_intento: list[list[str]] = field(default_factory=list)

    @classmethod
    def desde(cls, etapa: str, gen: GeneracionValidada[Any], segundos: float) -> RegistroLlamada:
        return cls(
            etapa=etapa,
            intentos=gen.intentos,
            segundos=round(segundos, 3),
            prompt_tokens=gen.resultado.prompt_tokens,
            output_tokens=gen.resultado.output_tokens,
            errores_por_intento=gen.errores_por_intento,
        )

    def a_dict(self) -> dict[str, Any]:
        return {
            "etapa": self.etapa,
            "intentos": self.intentos,
            "segundos": self.segundos,
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "errores_por_intento": self.errores_por_intento,
        }


@dataclass
class ResultadoPlan:
    bible: StoryBible
    estrategia: Estrategia
    llamadas: list[RegistroLlamada]

    @property
    def intentos_totales(self) -> int:
        return sum(r.intentos for r in self.llamadas)

    @property
    def segundos_totales(self) -> float:
        return round(sum(r.segundos for r in self.llamadas), 3)


def _reparar_escena(errores: list[str]) -> dict[str, str]:
    return mensaje_reparacion(errores, objeto="la escena completa")


def _reparar_plan(errores: list[str]) -> dict[str, str]:
    return mensaje_reparacion(errores, objeto="el plan completo")


class Planificador:
    def __init__(self, llm: LLMBackend, cfg: LLMConfig) -> None:
        self.llm = llm
        self.cfg = cfg
        # Llamadas completadas de la última generación (sirve para medir aunque luego falle).
        self.registro: list[RegistroLlamada] = []
        # Códigos de fallback del texto (p. ej. un reparto que no coincide con la idea).
        self.avisos: list[str] = []

    # ---- Infraestructura -----------------------------------------------------------------
    def _llamar(
        self,
        etapa: str,
        modelo_salida: type[M],
        mensajes: list[dict[str, str]],
        *,
        temperature: float,
        seed: int,
        reparar: Any = mensaje_reparacion,
    ) -> tuple[M, RegistroLlamada]:
        inicio = time.perf_counter()
        gen = self.llm.generar_validado(
            modelo_salida=modelo_salida,
            model=self.cfg.model,
            messages=mensajes,
            temperature=temperature,
            num_ctx=self.cfg.num_ctx,
            max_reintentos=self.cfg.max_reintentos,
            think=self.cfg.think,
            keep_alive=self.cfg.keep_alive_etapa,
            seed=seed,
            reparar=reparar,
            num_predict=self.cfg.num_predict,
            opciones_extra=self.cfg.opciones_muestreo(),
        )
        registro = RegistroLlamada.desde(etapa, gen, time.perf_counter() - inicio)
        self.registro.append(registro)
        logger.info(
            "llm_llamada", extra=kv(etapa=etapa, intentos=gen.intentos, s=registro.segundos)
        )
        return gen.objeto, registro

    # ---- API pública ---------------------------------------------------------------------
    def liberar(self) -> None:
        """Descarga el modelo de la VRAM (``keep_alive=0``) al terminar la etapa de texto."""
        self.llm.unload(self.cfg.model)

    def generar(
        self, solicitud: StoryRequest, estrategia: Estrategia | None = None
    ) -> ResultadoPlan:
        elegida: Estrategia = estrategia or self.cfg.estrategia
        self.registro = []
        self.avisos = []
        logger.info("planificador_inicio", extra=kv(estrategia=elegida, modelo=self.cfg.model))
        if elegida == "una_llamada":
            return self._una_llamada(solicitud)
        if elegida == "por_etapas":
            return self._por_etapas(solicitud)
        raise PlannerError(f"Estrategia desconocida: {elegida}")

    def _una_llamada(self, solicitud: StoryRequest) -> ResultadoPlan:
        bible, registro = self._llamar(
            "bible",
            StoryBible,
            mensajes_bible(solicitud),
            temperature=self.cfg.temperature_narrativa,
            seed=self.cfg.seed,
        )
        bible.genero = solicitud.genero_efectivo  # lo eligió el usuario, no el LLM
        bible.grupos = grupos_pedidos(solicitud.idea)
        bible.personajes = precisar_personas(solicitud.idea, bible.personajes)
        return ResultadoPlan(bible=bible, estrategia="una_llamada", llamadas=[registro])

    def planificar(self, solicitud: StoryRequest) -> tuple[PlanHistoria, RegistroLlamada]:
        """Estrategia (b), paso 1: título, estilo, personajes y resumen de las 5 escenas.

        Si el reparto no coincide con la idea (animales pedidos y personas en el plan, o una
        especie nombrada que no aparece; ver ``reparto``), se le pide al LLM una corrección
        una vez. Si sigue sin coincidir, se usa el plan con menos problemas y queda un aviso.
        """
        mensajes = mensajes_plan(solicitud)
        plan, registro = self._llamar(
            "plan",
            PlanHistoria,
            mensajes,
            temperature=self.cfg.temperature_narrativa,
            seed=self.cfg.seed,
            reparar=_reparar_plan,
        )
        problemas = problemas_reparto(solicitud.idea, plan.personajes)
        if problemas:
            logger.warning("reparto_no_coincide", extra=kv(problemas=problemas))
            correccion = [
                *mensajes,
                {"role": "assistant", "content": plan.model_dump_json()},
                {"role": "user", "content": mensaje_correccion(problemas)},
            ]
            try:
                corregido, registro_corr = self._llamar(
                    "plan_reparto",
                    PlanHistoria,
                    correccion,
                    temperature=self.cfg.temperature_narrativa,
                    seed=derivar_seed(self.cfg.seed, "reparto", 1),
                    reparar=_reparar_plan,
                )
            except Exception as exc:  # la corrección es una mejora: si falla, sigue el plan
                logger.warning("reparto_correccion_fallida", extra=kv(error=str(exc)))
            else:
                restantes = problemas_reparto(solicitud.idea, corregido.personajes)
                if len(restantes) < len(problemas):
                    plan, registro, problemas = corregido, registro_corr, restantes
            if problemas:
                self.avisos.append(AVISO_REPARTO)
        plan.personajes = precisar_personas(solicitud.idea, plan.personajes)  # 'child' -> 'boy'
        plan.genero = solicitud.genero_efectivo  # lo eligió el usuario, no el LLM
        plan.grupos = grupos_pedidos(solicitud.idea)  # "rodeado de gatos": lo pone el código
        return plan, registro

    def escribir_escena(
        self, plan: PlanHistoria, numero: int, previas: list[Escena], genero: str
    ) -> tuple[Escena, RegistroLlamada]:
        """Estrategia (b), paso 2: la escena ``numero`` con el canon y los resúmenes previos.

        La usa también la generación por escenas (``Pipeline.generar_por_escenas``), que
        ilustra y narra cada escena antes de escribir la siguiente.
        """
        canon = list(plan.canon_inicial)
        for previa in previas:
            canon.extend(h for h in previa.hechos_nuevos if h not in canon)
        resumenes = [f"Escena {e.numero}: {e.resumen}" for e in previas]
        regla = REGLAS_GENERO.get(genero, REGLAS_GENERO["otro"])
        escena, registro = self._llamar(
            f"escena_{numero}",
            Escena,
            mensajes_escena(plan, numero, resumenes, canon, regla),
            temperature=self.cfg.temperature_narrativa,
            seed=derivar_seed(self.cfg.seed, "escena", numero),
            reparar=_reparar_escena,
        )
        escena = alinear_escena_con_plan(escena, plan, numero)
        if self.cfg.plano_visual:
            plano = self.plano_visual(plan, escena)
            if plano is not None:
                escena = escena.model_copy(update={"plano_visual": plano})
        return escena, registro

    def plano_visual(self, plan: PlanHistoria, escena: Escena) -> PlanoVisual | None:
        """El ilustrador (17 nov): qué se ve en la imagen de ``escena``, en una llamada aparte.

        Con el texto ya escrito, el LLM elige el personaje principal, hasta 2 acompañantes
        (y cuántos), la acción, el lugar y el plano; el código arma el prompt de imagen con
        eso (``prompt_builder``). Si falla, la escena sigue con su ``prompt_imagen``.
        """
        try:
            plano, _ = self._llamar(
                f"plano_{escena.numero}",
                PlanoVisual,
                mensajes_plano_visual(plan, escena),
                temperature=TEMPERATURA_PLANO,
                seed=derivar_seed(self.cfg.seed, "plano", escena.numero),
            )
        except Exception as exc:  # una mejora: sin ella la escena tiene su prompt_imagen
            logger.warning("plano_visual_fallido", extra=kv(escena=escena.numero, error=str(exc)))
            self.avisos.append(f"{AVISO_PLANO}:{escena.numero}")
            return None
        return ajustar_plano(plano, escena, plan)

    def _por_etapas(self, solicitud: StoryRequest) -> ResultadoPlan:
        plan, _ = self.planificar(solicitud)
        escenas: list[Escena] = []
        for numero in range(1, NUM_ESCENAS + 1):
            escena, _ = self.escribir_escena(plan, numero, escenas, solicitud.genero)
            escenas.append(escena)
        llamadas = list(self.registro)  # incluye la corrección del reparto, si la hubo
        try:
            bible = StoryBible.desde_plan(plan, escenas)
        except ValidationError as exc:
            raise PlannerError(
                "No se pudo ensamblar la Bible desde el plan: " + "; ".join(errores_validacion(exc))
            ) from exc
        return ResultadoPlan(bible=bible, estrategia="por_etapas", llamadas=llamadas)


def alinear_escena_con_plan(escena: Escena, plan: PlanHistoria, numero: int) -> Escena:
    """El número, la fase y los personajes presentes los fija el plan, no el LLM.

    Así un modelo pequeño que se equivoque de número o invente un id no rompe la Bible.
    """
    objetivo = plan.plan_escenas[numero - 1]
    cambios: dict[str, Any] = {}
    if escena.numero != numero:
        cambios["numero"] = numero
    if escena.fase is not objetivo.fase:
        cambios["fase"] = objetivo.fase
    if list(escena.personajes_presentes) != list(objetivo.personajes_presentes):
        cambios["personajes_presentes"] = list(objetivo.personajes_presentes)
    if cambios:
        logger.warning("escena_alineada_con_plan", extra=kv(escena=numero, campos=sorted(cambios)))
        escena = escena.model_copy(update=cambios)
    return escena
