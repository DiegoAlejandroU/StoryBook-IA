"""El LLM escribe la historia de a una escena, para ilustrarla y narrarla antes de la siguiente.

Lo usa ``Pipeline.generar_por_escenas`` (pedido del docente, 12 nov): la escena 1 se muestra
apenas tiene texto, imagen, voz y ambiente, y la 2 se genera mientras el usuario la lee.

Es la estrategia (b) del planificador partida en pasos: primero el plan (título, estilo,
personajes y el resumen de las 5 escenas) y luego cada escena con el canon y los resúmenes de
las anteriores. Diferencias con la generación completa:

* Entre escena y escena el modelo se descarga de la VRAM (``keep_alive=0``): en 4 GB no caben
  a la vez el LLM y el modelo de imagen o de sonido.
* No hay auditor: revisaría las 5 escenas juntas y podría cambiar una que el usuario ya está
  leyendo. La continuidad se apoya en el canon que recibe cada escena.
* Desde la escena 2 el proceso ya tiene un contexto de CUDA abierto (torch) y queda menos
  VRAM libre. Si Ollama no puede poner todas las capas en GPU (``num_gpu: 99``), se reintenta
  una vez en modo automático (más lento, pero no se detiene la historia) y queda registrado.
"""

from __future__ import annotations

from typing import Any, Final

from storybook.config import LLMConfig
from storybook.logging_utils import get_logger, kv
from storybook.schemas import Escena, PlanHistoria, StoryRequest
from storybook.story.llm_client import (
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMResponseError,
    OllamaClient,
)
from storybook.story.planner import Planificador, RegistroLlamada

logger = get_logger(__name__)

ESTRATEGIA: Final = "por_escenas"
FALLBACK_NUM_GPU_AUTO: Final = "texto:num_gpu_automatico"


class EscritorError(Exception):
    """El LLM no está disponible; el mensaje es apto para la UI."""


class EscritorPorEscenas:
    """Plan + una escena por llamada, con el LLM fuera de la VRAM entre llamadas.

    ``cliente`` permite inyectar un LLM falso (tests y modo simulado); si es ``None`` se abre
    un ``OllamaClient`` con la configuración.
    """

    def __init__(self, cfg: LLMConfig, cliente: Any = None) -> None:
        self.cfg = cfg
        self._cliente = cliente
        self._propio = cliente is None
        self._planificador: Planificador | None = None
        self.llamadas: list[RegistroLlamada] = []
        self.fraccion_gpu: dict[str, float | None] = {}
        self.fallbacks: list[str] = []
        self.version = "desconocida"

    # -- ciclo de vida ----------------------------------------------------------------------
    def __enter__(self) -> EscritorPorEscenas:
        if self._cliente is None:
            self._cliente = OllamaClient(self.cfg.host, self.cfg.timeout_s)
        try:
            tiene = getattr(self._cliente, "has_model", None)
            if callable(tiene) and not tiene(self.cfg.model):
                raise EscritorError(
                    f"Falta el modelo de texto {self.cfg.model}. "
                    f"Ejecuta: ollama pull {self.cfg.model}"
                )
            version = getattr(self._cliente, "version", None)
            self.version = str(version()) if callable(version) else "simulado"
        except LLMConnectionError as exc:
            self._cerrar()
            raise EscritorError(
                f"Ollama no responde en {self.cfg.host}. Abre la aplicación de Ollama y "
                "vuelve a intentarlo."
            ) from exc
        except BaseException:
            self._cerrar()
            raise
        self._planificador = Planificador(self._cliente, self.cfg)
        return self

    def __exit__(self, *_: object) -> None:
        try:
            self.liberar_vram()
        finally:
            self._cerrar()

    def _cerrar(self) -> None:
        if self._propio and self._cliente is not None:
            self._cliente.close()
            self._cliente = None

    def liberar_vram(self) -> None:
        """Descarga el modelo (``keep_alive=0``) para dejar la GPU a la imagen y el sonido."""
        if self._cliente is None:
            return
        try:
            self._cliente.unload(self.cfg.model)
        except Exception as exc:  # Ollama cerrado: no ocupa VRAM
            logger.warning("unload_fallo", extra=kv(error=str(exc)))

    # -- escritura ------------------------------------------------------------------------
    def planificar(self, solicitud: StoryRequest) -> PlanHistoria:
        plan, _ = self._con_reintento("plan", lambda p: p.planificar(solicitud))
        return plan

    def escena(self, plan: PlanHistoria, numero: int, previas: list[Escena], genero: str) -> Escena:
        escena, _ = self._con_reintento(
            f"escena_{numero}", lambda p: p.escribir_escena(plan, numero, previas, genero)
        )
        return escena

    def _con_reintento(self, etapa: str, llamar: Any) -> tuple[Any, RegistroLlamada]:
        if self._planificador is None:
            raise EscritorError("El escritor no está abierto (usar con 'with')")
        try:
            objeto, registro = llamar(self._planificador)
        except LLMModelNotFoundError as exc:
            raise EscritorError(str(exc)) from exc
        except LLMConnectionError as exc:
            raise EscritorError(
                f"Se perdió la conexión con Ollama ({self.cfg.host}). Revisa que siga abierto."
            ) from exc
        except LLMResponseError as exc:
            if self.cfg.num_gpu is None:
                raise
            # Desde la escena 2 hay un contexto de CUDA abierto: si no caben todas las capas,
            # Ollama elige cuántas poner en GPU.
            logger.warning("llm_num_gpu_automatico", extra=kv(etapa=etapa, error=str(exc)))
            self.cfg = self.cfg.model_copy(update={"num_gpu": None})
            self._planificador = Planificador(self._cliente, self.cfg)
            self.fallbacks.append(FALLBACK_NUM_GPU_AUTO)
            objeto, registro = llamar(self._planificador)
        self.llamadas.append(registro)
        fraccion = getattr(self._cliente, "gpu_fraction", None)
        if callable(fraccion):
            try:
                self.fraccion_gpu[etapa] = fraccion(self.cfg.model)
            except Exception:  # solo informativo
                self.fraccion_gpu[etapa] = None
        return objeto, registro

    def info(self) -> dict[str, Any]:
        """``manifest["etapas"]["texto"]``, con el mismo formato que la generación completa."""
        return {
            "modelo": self.cfg.model,
            "ollama": self.version,
            "estrategia": ESTRATEGIA,
            "fraccion_gpu": self.fraccion_gpu,
            "num_gpu": self.cfg.num_gpu,
            "llamadas": [r.a_dict() for r in self.llamadas],
            "auditoria": None,
            "auditor": "omitido en la generación por escenas",
            "fallbacks": self.fallbacks,
        }
