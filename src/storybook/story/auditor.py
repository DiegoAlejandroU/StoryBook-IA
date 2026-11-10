"""Auditor de coherencia narrativa (segunda pasada del LLM a temperatura baja).

Detecta contradicciones de nombres, rasgos, hechos, escenario, estilo y secuencia. Si
alguna es crítica, regenera SOLO la escena afectada manteniendo su número, fase y
personajes, y vuelve a auditar hasta ``max_rondas_auditor`` veces. Todo queda registrado
para el manifest (evidencia del criterio de coherencia de la rúbrica).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from storybook.config import LLMConfig
from storybook.logging_utils import get_logger, kv
from storybook.schemas import AuditoriaCoherencia, Contradiccion, Escena, StoryBible, derivar_seed
from storybook.story.llm_client import LLMError, errores_validacion
from storybook.story.planner import LLMBackend, RegistroLlamada
from storybook.story.prompts import mensaje_reparacion, mensajes_auditor, mensajes_regenerar_escena

logger = get_logger(__name__)


class AuditorError(Exception):
    """La escena regenerada no encaja en la Bible."""


@dataclass
class ResultadoAuditoria:
    bible: StoryBible
    auditorias: list[AuditoriaCoherencia] = field(default_factory=list)
    escenas_regeneradas: list[int] = field(default_factory=list)
    llamadas: list[RegistroLlamada] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)

    @property
    def coherente_final(self) -> bool | None:
        if not self.auditorias:
            return None
        return not self.auditorias[-1].escenas_criticas

    def a_dict(self) -> dict[str, Any]:
        return {
            "rondas": len(self.auditorias),
            "coherente_final": self.coherente_final,
            "escenas_regeneradas": self.escenas_regeneradas,
            "contradicciones": [
                [c.model_dump(mode="json") for c in a.contradicciones] for a in self.auditorias
            ],
            "errores": self.errores,
        }


def reemplazar_escena(bible: StoryBible, nueva: Escena) -> StoryBible:
    """Nueva Bible con la escena sustituida; el canon se recalcula y las seeds se conservan."""
    numero = nueva.numero
    actual = bible.escena(numero)
    nueva = nueva.model_copy(
        update={
            "fase": actual.fase,
            "personajes_presentes": list(actual.personajes_presentes),
            "seed_imagen": actual.seed_imagen,
        }
    )
    datos = bible.model_dump()
    datos["escenas"] = [
        nueva.model_dump() if e.numero == numero else e.model_dump() for e in bible.escenas
    ]
    datos["canon"] = bible.canon_hasta(1)  # canon inicial; el validador añade los hechos
    try:
        return StoryBible.model_validate(datos)
    except ValidationError as exc:
        raise AuditorError(
            f"La escena {numero} regenerada rompe la Bible: " + "; ".join(errores_validacion(exc))
        ) from exc


class Auditor:
    def __init__(self, llm: LLMBackend, cfg: LLMConfig) -> None:
        self.llm = llm
        self.cfg = cfg

    def auditar(self, bible: StoryBible) -> tuple[AuditoriaCoherencia, RegistroLlamada]:
        inicio = time.perf_counter()
        gen = self.llm.generar_validado(
            modelo_salida=AuditoriaCoherencia,
            model=self.cfg.model,
            messages=mensajes_auditor(bible),
            temperature=self.cfg.temperature_auditor,
            num_ctx=self.cfg.num_ctx_auditor,
            max_reintentos=self.cfg.max_reintentos,
            think=self.cfg.think,
            keep_alive=self.cfg.keep_alive_etapa,
            seed=self.cfg.seed,
            reparar=lambda e: mensaje_reparacion(e, objeto="la auditoría completa"),
            num_predict=self.cfg.num_predict,
            opciones_extra=self.cfg.opciones_muestreo(),
        )
        registro = RegistroLlamada.desde("auditoria", gen, time.perf_counter() - inicio)
        auditoria = gen.objeto
        logger.info(
            "auditoria",
            extra=kv(
                contradicciones=len(auditoria.contradicciones),
                criticas=auditoria.escenas_criticas,
            ),
        )
        return auditoria, registro

    def regenerar_escena(
        self, bible: StoryBible, numero: int, contradicciones: list[Contradiccion]
    ) -> tuple[StoryBible, RegistroLlamada]:
        inicio = time.perf_counter()
        gen = self.llm.generar_validado(
            modelo_salida=Escena,
            model=self.cfg.model,
            messages=mensajes_regenerar_escena(bible, numero, contradicciones),
            temperature=self.cfg.temperature_narrativa,
            num_ctx=self.cfg.num_ctx_auditor,
            max_reintentos=self.cfg.max_reintentos,
            think=self.cfg.think,
            keep_alive=self.cfg.keep_alive_etapa,
            seed=derivar_seed(self.cfg.seed, "regenerar", numero),
            reparar=lambda e: mensaje_reparacion(e, objeto="la escena completa"),
            num_predict=self.cfg.num_predict,
            opciones_extra=self.cfg.opciones_muestreo(),
        )
        registro = RegistroLlamada.desde(
            f"regenerar_escena_{numero}", gen, time.perf_counter() - inicio
        )
        escena = gen.objeto
        if escena.numero != numero:
            escena = escena.model_copy(update={"numero": numero})
        return reemplazar_escena(bible, escena), registro

    def auditar_y_corregir(
        self, bible: StoryBible, max_rondas: int | None = None
    ) -> ResultadoAuditoria:
        """Audita; si hay contradicciones críticas regenera esas escenas y vuelve a auditar.

        Un fallo del LLM al regenerar no detiene el pipeline: se conserva la escena
        original y el error queda registrado (fallback documentado).
        """
        rondas = self.cfg.max_rondas_auditor if max_rondas is None else max_rondas
        resultado = ResultadoAuditoria(bible=bible)
        auditoria, registro = self.auditar(bible)
        resultado.auditorias.append(auditoria)
        resultado.llamadas.append(registro)
        for _ in range(rondas):
            criticas = auditoria.escenas_criticas
            if not criticas:
                break
            for numero in criticas:
                problemas = [
                    c
                    for c in auditoria.contradicciones
                    if c.escena == numero and c.severidad == "critica"
                ]
                try:
                    nueva, registro = self.regenerar_escena(resultado.bible, numero, problemas)
                except (LLMError, AuditorError) as exc:
                    mensaje = f"escena {numero}: {exc}"
                    resultado.errores.append(mensaje)
                    logger.warning("regeneracion_fallida", extra=kv(detalle=mensaje))
                    continue
                resultado.bible = nueva
                resultado.llamadas.append(registro)
                if numero not in resultado.escenas_regeneradas:
                    resultado.escenas_regeneradas.append(numero)
            auditoria, registro = self.auditar(resultado.bible)
            resultado.auditorias.append(auditoria)
            resultado.llamadas.append(registro)
        return resultado
