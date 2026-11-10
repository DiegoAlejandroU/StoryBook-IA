"""Narración de las escenas con voz sintética en español (CPU).

Una sola voz narradora para toda la historia, con parámetros constantes (``length_scale``,
``noise_scale``, ``noise_w_scale``), tomados de ``configs/`` (CLAUDE.md §10). El TTS corre
en CPU para no competir por los 4 GB de VRAM con el LLM, las imágenes y el sonido.

Backends intercambiables con la configuración (``voice.backend``) detrás del Protocol
``TTSBackend``:

* ``piper`` (principal): Piper ``es_MX-claude-high`` (ONNX), cargado desde ``models/piper``
  con ``hub.require_piper_voice``. Medido en F0: RTF ~0,03-0,07 (40 s de audio en ~2 s).
* ``kokoro`` (opcional, experimento Piper vs Kokoro): ``KPipeline`` con la voz ``ef_dora``.

Las librerías (``piper``, ``kokoro``) se importan dentro de los backends (CLAUDE.md §6); los
tests usan un backend falso.
"""

from __future__ import annotations

import io
import re
import time
import wave
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np
import soundfile as sf

from storybook.config import VoiceConfig
from storybook.gpu import StageMetrics, track_stage
from storybook.hub import require_piper_voice
from storybook.logging_utils import get_logger, kv
from storybook.schemas import StoryBible

logger = get_logger(__name__)

SILENCIO_FINAL_S: Final = 0.35  # respiro al final de cada escena (lo usa la mezcla)
FRECUENCIA_KOKORO: Final = 24_000
SUBTIPO_WAV: Final = "PCM_16"
_REEMPLAZOS_TEXTO: Final = {
    "«": '"',
    "»": '"',
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "—": ", ",
    "–": ", ",
    "…": "...",
}


class TTSError(Exception):
    """Error al sintetizar la narración."""


class TTSModelError(TTSError):
    """La voz no se pudo cargar (no descargada, librería ausente...)."""


class TTSBackend(Protocol):
    nombre: str

    def cargar(self) -> None:
        """Carga la voz (una vez por historia)."""
        ...

    def sintetizar(self, texto: str) -> tuple[np.ndarray, int]:
        """Devuelve (muestras mono float32 en [-1, 1], frecuencia de muestreo)."""
        ...

    def liberar(self) -> None: ...

    def info(self) -> dict[str, Any]:
        """Voz, parámetros y versiones (para el manifest)."""
        ...


# ---------------------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------------------
def normalizar_texto_tts(texto: str) -> str:
    """Prepara la narración para el TTS sin cambiar lo que se muestra en pantalla.

    Unifica comillas y rayas (Piper las pronuncia mal o hace pausas raras), colapsa espacios
    y saltos de línea y asegura un signo final para que la entonación cierre la frase.
    """
    for original, reemplazo in _REEMPLAZOS_TEXTO.items():
        texto = texto.replace(original, reemplazo)
    texto = re.sub(r"\s+", " ", texto).strip()
    texto = re.sub(r"\s+([,.;:!?])", r"\1", texto)
    if not texto:
        raise TTSError("El texto de la narración está vacío")
    if texto[-1] not in ".!?…\"'":
        texto += "."
    return texto


def a_mono_float32(muestras: Any) -> np.ndarray:
    """Tensor o array (1D, o 2D canales×muestras / muestras×canales) -> mono float32."""
    if hasattr(muestras, "detach"):
        muestras = muestras.detach().float().cpu().numpy()
    datos = np.asarray(muestras, dtype=np.float32)
    if datos.ndim == 2:
        eje = 0 if datos.shape[0] < datos.shape[1] else 1
        datos = datos.mean(axis=eje)
    if datos.ndim != 1:
        raise TTSError(f"Forma de audio inesperada: {datos.shape}")
    datos = np.nan_to_num(datos, nan=0.0, posinf=0.0, neginf=0.0)
    return np.clip(datos, -1.0, 1.0).astype(np.float32)


def leer_wav_pcm(contenido: bytes) -> tuple[np.ndarray, int]:
    """WAV PCM de 16 bits en memoria (lo que escribe Piper) -> (float32 mono, frecuencia)."""
    with wave.open(io.BytesIO(contenido), "rb") as wav:
        frecuencia = wav.getframerate()
        canales = wav.getnchannels()
        if wav.getsampwidth() != 2:
            raise TTSError("Piper debe producir PCM de 16 bits")
        datos = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    muestras = datos.astype(np.float32) / 32768.0
    if canales > 1:
        muestras = muestras.reshape(-1, canales).mean(axis=1)
    return muestras, frecuencia


def nombre_archivo_voz(numero: int) -> str:
    return f"voice_{numero}.wav"


# ---------------------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------------------
@dataclass
class ResultadoVoz:
    escena: int
    ruta: Path
    duracion_s: float
    sample_rate: int
    segundos_sintesis: float
    caracteres: int

    @property
    def rtf(self) -> float | None:
        """Real-time factor: segundos de cómputo por segundo de audio (<1 = más rápido)."""
        return round(self.segundos_sintesis / self.duracion_s, 4) if self.duracion_s else None

    def a_dict(self) -> dict[str, Any]:
        return {
            "escena": self.escena,
            "archivo": self.ruta.name,
            "duracion_s": self.duracion_s,
            "sample_rate": self.sample_rate,
            "segundos_sintesis": self.segundos_sintesis,
            "rtf": self.rtf,
            "caracteres": self.caracteres,
        }


@dataclass
class EtapaVoz:
    narraciones: list[ResultadoVoz]
    backend: dict[str, Any] = field(default_factory=dict)
    metricas: list[StageMetrics] = field(default_factory=list)

    @property
    def duracion_total_s(self) -> float:
        return round(sum(n.duracion_s for n in self.narraciones), 3)

    def a_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "duracion_total_s": self.duracion_total_s,
            "narraciones": [n.a_dict() for n in self.narraciones],
            "metricas": [m.as_dict() for m in self.metricas],
        }


# ---------------------------------------------------------------------------------------
# Narrador (orquesta la etapa de voz)
# ---------------------------------------------------------------------------------------
class Narrador:
    def __init__(self, cfg: VoiceConfig, backend: TTSBackend | None = None) -> None:
        self.cfg = cfg
        self.backend: TTSBackend = backend or crear_backend(cfg)

    def narrar(self, textos: Sequence[tuple[int, str]], carpeta: Path) -> EtapaVoz:
        """Sintetiza ``(numero_escena, texto)`` con la misma voz y guarda ``voice_n.wav``."""
        carpeta.mkdir(parents=True, exist_ok=True)
        etapa = EtapaVoz(narraciones=[])
        try:
            with track_stage("voz_carga") as m_carga:
                try:
                    self.backend.cargar()
                except TTSError:
                    raise
                except Exception as exc:
                    raise TTSModelError(
                        f"No se pudo cargar la voz '{self.backend.nombre}': {exc}"
                    ) from exc
            etapa.metricas.append(m_carga)
            etapa.backend = self.backend.info()
            for numero, texto in textos:
                resultado, metrica = self._narrar_escena(numero, texto, carpeta)
                etapa.narraciones.append(resultado)
                etapa.metricas.append(metrica)
        finally:
            self.backend.liberar()
        logger.info(
            "etapa_voz_terminada",
            extra=kv(escenas=[n.escena for n in etapa.narraciones], total_s=etapa.duracion_total_s),
        )
        return etapa

    def narrar_bible(
        self, bible: StoryBible, carpeta: Path, numeros: Sequence[int] | None = None
    ) -> EtapaVoz:
        elegidas = set(numeros) if numeros is not None else None
        textos = [
            (e.numero, e.texto_narrativo)
            for e in bible.escenas
            if elegidas is None or e.numero in elegidas
        ]
        return self.narrar(textos, carpeta)

    def _narrar_escena(
        self, numero: int, texto: str, carpeta: Path
    ) -> tuple[ResultadoVoz, StageMetrics]:
        texto_tts = normalizar_texto_tts(texto)
        with track_stage(f"voz_escena_{numero}") as metrica:
            inicio = time.perf_counter()
            try:
                crudo, frecuencia = self.backend.sintetizar(texto_tts)
            except Exception as exc:
                raise TTSError(f"Falló la narración de la escena {numero}: {exc}") from exc
            segundos = time.perf_counter() - inicio
            muestras = a_mono_float32(crudo)
            if muestras.size == 0 or not np.any(muestras):
                raise TTSError(f"La narración de la escena {numero} salió vacía")
            silencio = np.zeros(int(SILENCIO_FINAL_S * frecuencia), dtype=np.float32)
            muestras = np.concatenate([muestras, silencio])
            ruta = carpeta / nombre_archivo_voz(numero)
            sf.write(str(ruta), muestras, frecuencia, subtype=SUBTIPO_WAV)
            duracion = round(muestras.size / frecuencia, 3)
            metrica.extra.update(duracion_audio_s=duracion, sample_rate=frecuencia)
        resultado = ResultadoVoz(
            escena=numero,
            ruta=ruta,
            duracion_s=duracion,
            sample_rate=frecuencia,
            segundos_sintesis=round(segundos, 3),
            caracteres=len(texto_tts),
        )
        metrica.extra["rtf"] = resultado.rtf
        return resultado, metrica


# ---------------------------------------------------------------------------------------
# Backends reales (imports perezosos)
# ---------------------------------------------------------------------------------------
class PiperBackend:
    """Piper (ONNX Runtime en CPU). La voz se valida en disco antes de importar ``piper``."""

    nombre = "piper"

    def __init__(self, cfg: VoiceConfig) -> None:
        self.cfg = cfg
        self._voz: Any = None
        self._sintesis: Any = None
        self._version: str | None = None

    def cargar(self) -> None:
        archivos = require_piper_voice(self.cfg.piper_voice)
        try:
            from piper import PiperVoice, SynthesisConfig
        except ImportError as exc:
            raise TTSModelError("piper-tts no está instalado: ejecuta 'uv sync'") from exc
        self._voz = PiperVoice.load(archivos.onnx, config_path=archivos.config, use_cuda=False)
        self._sintesis = SynthesisConfig(
            length_scale=self.cfg.length_scale,
            noise_scale=self.cfg.noise_scale,
            noise_w_scale=self.cfg.noise_w_scale,
            normalize_audio=True,
            volume=1.0,
        )
        try:
            from importlib.metadata import version

            self._version = version("piper-tts")
        except Exception:
            self._version = None

    def sintetizar(self, texto: str) -> tuple[np.ndarray, int]:
        if self._voz is None:
            raise TTSError("La voz Piper no está cargada")
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            self._voz.synthesize_wav(texto, wav, syn_config=self._sintesis)
        return leer_wav_pcm(buffer.getvalue())

    def liberar(self) -> None:
        self._voz = None

    def info(self) -> dict[str, Any]:
        return {
            "backend": self.nombre,
            "voz": self.cfg.piper_voice,
            "length_scale": self.cfg.length_scale,
            "noise_scale": self.cfg.noise_scale,
            "noise_w_scale": self.cfg.noise_w_scale,
            "piper_tts": self._version,
            "dispositivo": "cpu",
        }


class KokoroBackend:
    """Kokoro-82M (opcional, extra ``kokoro``) para el experimento Piper vs Kokoro.

    ``speed`` se deriva de ``length_scale`` (1/length_scale) para que ambas voces usen el
    mismo parámetro de ritmo en la comparación.
    """

    nombre = "kokoro"

    def __init__(self, cfg: VoiceConfig) -> None:
        self.cfg = cfg
        self._pipeline: Any = None

    def cargar(self) -> None:
        try:
            from kokoro import KPipeline
        except ImportError as exc:
            raise TTSModelError("Kokoro no está instalado: 'uv sync --extra kokoro'") from exc
        self._pipeline = KPipeline(lang_code=self.cfg.kokoro_lang_code, device="cpu")

    def sintetizar(self, texto: str) -> tuple[np.ndarray, int]:
        if self._pipeline is None:
            raise TTSError("Kokoro no está cargado")
        velocidad = 1.0 / self.cfg.length_scale
        trozos = [
            a_mono_float32(resultado[2])
            for resultado in self._pipeline(texto, voice=self.cfg.kokoro_voice, speed=velocidad)
            if resultado[2] is not None
        ]
        if not trozos:
            raise TTSError("Kokoro no devolvió audio")
        return np.concatenate(trozos), FRECUENCIA_KOKORO

    def liberar(self) -> None:
        self._pipeline = None

    def info(self) -> dict[str, Any]:
        return {
            "backend": self.nombre,
            "voz": self.cfg.kokoro_voice,
            "lang_code": self.cfg.kokoro_lang_code,
            "speed": round(1.0 / self.cfg.length_scale, 3),
            "dispositivo": "cpu",
        }


def crear_backend(cfg: VoiceConfig) -> TTSBackend:
    """Backend según ``voice.backend`` (sin importar todavía la librería de TTS)."""
    if cfg.backend == "kokoro":
        return KokoroBackend(cfg)
    return PiperBackend(cfg)
