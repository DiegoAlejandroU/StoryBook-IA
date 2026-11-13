"""Generación por escenas en segundo plano, para que la interfaz muestre cada escena al llegar.

Streamlit vuelve a ejecutar el script en cada interacción, así que la historia se genera en un
hilo aparte y la interfaz consulta su estado cada segundo (``st.fragment(run_every=…)``). Este
módulo no depende de Streamlit (se prueba sin él): el hilo escribe con un candado y la interfaz
lee una ``Instantanea`` inmutable.

Solo puede haber una generación a la vez en el equipo (una sola GPU): ``CANDADO_GPU`` lo
comparten todas las sesiones del navegador.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final

from storybook.logging_utils import get_logger, kv
from storybook.progresivo import EscenaLista, PlanListo

logger = get_logger(__name__)

CANDADO_GPU: Final = threading.Lock()
MENSAJE_OCUPADO: Final = (
    "Ya se está generando otra historia en este equipo (quizá en otra pestaña). "
    "Espera a que termine e inténtalo de nuevo."
)


@dataclass(frozen=True)
class Instantanea:
    """Estado de la generación en un instante (lo que dibuja la interfaz)."""

    activa: bool = False
    terminada: bool = False
    error: str | None = None
    etapa: str = "texto"
    avance: float = 0.0
    mensaje: str = "Preparando"
    transcurrido_s: float = 0.0
    plan: PlanListo | None = None
    listas: dict[int, EscenaLista] = field(default_factory=dict)
    carpeta: Path | None = None
    perfil: str = "rapido"
    idea: str = ""

    @property
    def en_curso(self) -> int | None:
        """La escena que se está generando ahora (``None`` si no hay ninguna)."""
        if not self.activa or self.terminada:
            return None
        siguiente = len(self.listas) + 1
        return siguiente if siguiente <= 5 else None


class GeneracionEnCurso:
    """Ejecuta ``generar(progreso, al_estar_lista, al_planificar)`` en un hilo.

    ``generar`` es normalmente ``Pipeline.generar_por_escenas`` con la idea y el género ya
    puestos (``functools.partial``); devuelve la historia guardada.
    """

    def __init__(
        self,
        generar: Callable[..., Any],
        *,
        perfil: str,
        idea: str,
        candado: threading.Lock = CANDADO_GPU,
    ) -> None:
        self._generar = generar
        self._candado_gpu = candado
        self._candado = threading.Lock()
        self._inicio = time.monotonic()
        self._fin: float | None = None
        self._estado = Instantanea(activa=True, perfil=perfil, idea=idea)
        self._hilo = threading.Thread(target=self._correr, name="storybook-generacion", daemon=True)

    # -- hilo -----------------------------------------------------------------------------
    def iniciar(self) -> GeneracionEnCurso:
        self._hilo.start()
        return self

    def esperar(self, timeout: float | None = None) -> None:
        self._hilo.join(timeout)

    def _actualizar(self, **cambios: Any) -> None:
        with self._candado:
            self._estado = replace(self._estado, **cambios)

    def _progreso(self, etapa: str, avance: float, mensaje: str) -> None:
        self._actualizar(etapa=etapa, avance=max(self._estado.avance, avance), mensaje=mensaje)

    def _al_planificar(self, plan: PlanListo) -> None:
        self._actualizar(plan=plan, carpeta=plan.carpeta)

    def _al_estar_lista(self, lista: EscenaLista) -> None:
        with self._candado:
            listas = {**self._estado.listas, lista.numero: lista}
            self._estado = replace(self._estado, listas=listas, carpeta=lista.carpeta)

    def _correr(self) -> None:
        if not self._candado_gpu.acquire(blocking=False):
            self._terminar(error=MENSAJE_OCUPADO)
            return
        try:
            historia = self._generar(
                progreso=self._progreso,
                al_estar_lista=self._al_estar_lista,
                al_planificar=self._al_planificar,
            )
            carpeta = getattr(historia, "carpeta", None)
            self._terminar(carpeta=carpeta, avance=1.0, mensaje="Historia completa")
        except Exception as exc:  # el mensaje de PipelineError ya es apto para la interfaz
            logger.exception("generacion_en_segundo_plano_fallida")
            self._terminar(error=str(exc) or type(exc).__name__)
        finally:
            self._candado_gpu.release()

    def _terminar(self, **cambios: Any) -> None:
        self._fin = time.monotonic()
        self._actualizar(terminada=True, **cambios)
        logger.info(
            "generacion_terminada", extra=kv(error=cambios.get("error"), s=self.transcurrido())
        )

    # -- lectura --------------------------------------------------------------------------
    def transcurrido(self) -> float:
        fin = self._fin if self._fin is not None else time.monotonic()
        return round(fin - self._inicio, 1)

    def instantanea(self) -> Instantanea:
        with self._candado:
            return replace(self._estado, transcurrido_s=self.transcurrido())
