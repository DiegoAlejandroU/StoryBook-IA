"""Gestión de la GPU: medición de tiempo y VRAM por etapa, y liberación de memoria.

Dos fuentes de medición complementarias (ambas se guardan en el manifest):

* ``torch.cuda.max_memory_allocated``: memoria pico que reservaron los tensores de ESTE
  proceso de Python (diffusers, transformers). No ve la VRAM de Ollama.
* NVML (``nvidia-ml-py``, lo mismo que reporta ``nvidia-smi``): memoria usada en TODA la
  GPU, muestreada en un hilo. Incluye Ollama, el contexto CUDA y otros procesos.

Regla del proyecto con 4 GB: un modelo pesado a la vez. Patrón obligatorio al terminar
una etapa::

    del pipe
    free_cuda_memory()
"""

from __future__ import annotations

import gc
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any

from storybook.logging_utils import get_logger, kv

logger = get_logger(__name__)
MB = 1024**2


class GPUError(Exception):
    """Errores de gestión de la GPU (falta CUDA, OOM no recuperable, etc.)."""


def torch_cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return bool(torch.cuda.is_available())


def free_cuda_memory() -> None:
    """Recolecta basura y devuelve al driver la memoria cacheada por PyTorch."""
    gc.collect()
    if torch_cuda_available():
        import torch

        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


class NvmlReader:
    """Lectura de la GPU NVIDIA vía NVML. Si no hay driver/GPU, ``available`` es False."""

    def __init__(self, index: int = 0) -> None:
        self._nvml: Any = None
        self._handle: Any = None
        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml = pynvml
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(index)
        except Exception as exc:  # NVML lanza excepciones propias según la plataforma
            logger.debug("nvml_no_disponible", extra=kv(error=str(exc)))
            self._handle = None

    @property
    def available(self) -> bool:
        return self._handle is not None

    def used_mb(self) -> float | None:
        if not self.available:
            return None
        return round(self._nvml.nvmlDeviceGetMemoryInfo(self._handle).used / MB, 1)

    def total_mb(self) -> float | None:
        if not self.available:
            return None
        return round(self._nvml.nvmlDeviceGetMemoryInfo(self._handle).total / MB, 1)

    def info(self) -> dict[str, Any]:
        """Datos estáticos y de estado de la GPU para check_env y el manifest."""
        if not self.available:
            return {}
        nvml = self._nvml
        datos: dict[str, Any] = {
            "nombre": _texto(nvml.nvmlDeviceGetName(self._handle)),
            "driver": _texto(nvml.nvmlSystemGetDriverVersion()),
            "vram_total_mb": self.total_mb(),
            "vram_usada_mb": self.used_mb(),
        }
        try:
            cuda_driver = int(nvml.nvmlSystemGetCudaDriverVersion_v2())
            datos["cuda_driver"] = f"{cuda_driver // 1000}.{(cuda_driver % 1000) // 10}"
        except Exception:
            datos["cuda_driver"] = None
        for clave, funcion, escala in (
            ("temperatura_c", lambda h: nvml.nvmlDeviceGetTemperature(h, 0), 1),
            ("potencia_limite_w", nvml.nvmlDeviceGetEnforcedPowerLimit, 1000),
            ("potencia_actual_w", nvml.nvmlDeviceGetPowerUsage, 1000),
            ("pstate", nvml.nvmlDeviceGetPerformanceState, 1),
        ):
            try:
                valor = funcion(self._handle)
                datos[clave] = round(valor / escala, 1) if escala != 1 else valor
            except Exception:
                datos[clave] = None
        return datos

    def close(self) -> None:
        if self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()
            except Exception as exc:
                logger.debug("nvml_shutdown_fallo", extra=kv(error=str(exc)))
        self._handle = None
        self._nvml = None


def _texto(valor: bytes | str) -> str:
    return valor.decode() if isinstance(valor, bytes) else str(valor)


class VramSampler(threading.Thread):
    """Muestrea la VRAM usada (NVML) a intervalos fijos y conserva el pico."""

    def __init__(self, reader: NvmlReader, interval_s: float = 0.2) -> None:
        super().__init__(daemon=True, name="vram-sampler")
        self._reader = reader
        self._interval = interval_s
        self._stop_event = threading.Event()
        self.peak_mb: float | None = reader.used_mb()

    def run(self) -> None:
        while not self._stop_event.is_set():
            actual = self._reader.used_mb()
            if actual is not None and (self.peak_mb is None or actual > self.peak_mb):
                self.peak_mb = actual
            self._stop_event.wait(self._interval)

    def stop(self) -> float | None:
        self._stop_event.set()
        self.join(timeout=2.0)
        return self.peak_mb


@dataclass
class StageMetrics:
    """Métricas de una etapa del pipeline (van al manifest y a results.csv)."""

    etapa: str
    segundos: float = 0.0
    dispositivo: str = "cpu"
    vram_torch_pico_mb: float | None = None
    vram_torch_reservada_pico_mb: float | None = None
    vram_gpu_base_mb: float | None = None
    vram_gpu_pico_mb: float | None = None
    vram_gpu_total_mb: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@contextmanager
def track_stage(etapa: str, sample_interval_s: float = 0.2) -> Iterator[StageMetrics]:
    """Mide tiempo de pared y VRAM pico (torch + NVML) de un bloque de código.

    Ejemplo::

        with track_stage("imagen") as m:
            imagen = pipe(prompt).images[0]
            m.extra["pasos"] = 6
    """
    metricas = StageMetrics(etapa=etapa)
    usa_cuda = torch_cuda_available()
    if usa_cuda:
        import torch

        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        metricas.dispositivo = "cuda"

    lector = NvmlReader()
    muestreador: VramSampler | None = None
    if lector.available:
        metricas.vram_gpu_base_mb = lector.used_mb()
        metricas.vram_gpu_total_mb = lector.total_mb()
        muestreador = VramSampler(lector, sample_interval_s)
        muestreador.start()

    inicio = time.perf_counter()
    try:
        yield metricas
    finally:
        if usa_cuda:
            import torch

            torch.cuda.synchronize()
            metricas.vram_torch_pico_mb = round(torch.cuda.max_memory_allocated() / MB, 1)
            metricas.vram_torch_reservada_pico_mb = round(torch.cuda.max_memory_reserved() / MB, 1)
        metricas.segundos = round(time.perf_counter() - inicio, 3)
        if muestreador is not None:
            metricas.vram_gpu_pico_mb = muestreador.stop()
        lector.close()
        resumen = {k: v for k, v in metricas.as_dict().items() if k != "extra"}
        resumen.update({f"extra.{k}": v for k, v in metricas.extra.items()})
        logger.info("etapa_medida", extra=kv(**resumen))


def gpu_used_mb() -> float | None:
    """Lectura puntual de VRAM usada en toda la GPU (útil para comprobar liberaciones)."""
    lector = NvmlReader()
    try:
        return lector.used_mb()
    finally:
        lector.close()
