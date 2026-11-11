"""Etapa de sonido: un ambiente por escena con fallback automático en cadena.

Orden (``sound.backends`` de la configuración; CLAUDE.md §8):

* **A · generación local** en GPU desde ``prompt_sonido``: Stable Audio 3 Small-SFX (``sa3``),
  Stable Audio Open 1.0 (``sao``) o AudioLDM (``audioldm``), vía diffusers con imports
  perezosos. Mismo procedimiento validado en F0 por ``scripts/f0_hello.py``.
* **B · biblioteca** CC0 de ``assets/sfx/`` por ``etiquetas_sonido`` (``library``).
* **C · síntesis procedural** con numpy/scipy por ``etiquetas_sonido`` (``procedural``):
  nunca falla, así la historia siempre tiene 5 ambientes.

Se procesa por etapas: cada backend se carga una sola vez y genera todas las escenas
pendientes. Si no carga (no descargado, sin GPU, gated sin token), se pasa al siguiente. Si
falla en una escena, esa escena pasa al siguiente backend. Un OOM abandona el backend para
las escenas que falten. Cada escena registra el backend que la produjo y la etapa registra
los fallbacks y errores (van al manifest).
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np
import soundfile as sf

from storybook.config import SoundConfig
from storybook.gpu import StageMetrics, free_cuda_memory, track_stage
from storybook.hub import (
    ModelNotDownloadedError,
    diffusers_variant,
    is_diffusers_repo,
    local_snapshot,
)
from storybook.logging_utils import get_logger, kv
from storybook.schemas import Escena, StoryBible
from storybook.sound.library import BibliotecaSonidos, cargar_audio_mono
from storybook.sound.procedural import FRECUENCIA, sintetizar

logger = get_logger(__name__)

GENERATIVOS: Final = ("sa3", "sao", "audioldm")
DURACION_MINIMA_S: Final = 0.5
RMS_MINIMO: Final = 1e-4
# Continuidad de los clips generativos (tarea 4.4): AudioLDM a veces concentra el sonido en el
# primer segundo y deja el resto casi en silencio (2 de 5 escenas en la prueba real); en loop
# eso son huecos periódicos. Si más del 40 % del clip está 20 dB por debajo de su parte más
# fuerte, se reintenta con otra seed y, si sigue igual, la escena pasa al siguiente backend.
UMBRAL_HUECO_DB: Final = 20.0
FRACCION_HUECO_MAX: Final = 0.4
# Nivel absoluto mínimo de un clip generativo. En la corrida de ejemplos (5.4) AudioLDM dio
# clips a -72 dBFS ("soft wind… birds sing gently"): en la mezcla el ambiente no se oía.
NIVEL_MINIMO_DBFS: Final = -45.0
VENTANA_HUECO_S: Final = 0.05
# Demostración en vivo del respaldo (sustentación): con esta variable en "1" los modelos de
# sonido generativos se tratan como no disponibles y la cadena pasa a biblioteca y procedural.
# StoryBook.cmd la activa con el argumento "respaldo".
SIN_AUDIO_GENERATIVO: Final = "STORYBOOK_SIN_AUDIO_GENERATIVO"
# Prompts para los modelos de audio. En 5.4, 5 de los 6 prompt_sonido con adjetivos de
# intensidad baja ("soft wind", "birds sing gently", "faint water") dieron clips casi mudos en
# todos los intentos; los 9 prompts sin ellos salieron bien. El volumen lo fija la mezcla
# (12-18 dB bajo la voz), así que esos adjetivos y las menciones de silencio se quitan.
_INTENSIDAD_BAJA: Final = re.compile(
    r"\b(?:soft|softly|gentle|gently|faint|faintly|quiet|quietly|subtle|subtly|barely|"
    r"slight|slightly|hushed|muted)\b",
    re.IGNORECASE,
)
_SILENCIO: Final = re.compile(
    r"\b(?:(?:beneath|under|into|in|through)\s+(?:the\s+)?)?(?:silence|stillness)\b",
    re.IGNORECASE,
)
DESFASE_SEED_REINTENTO: Final = 1000
SUBTIPO_WAV: Final = "PCM_16"


class SoundError(Exception):
    """Error de un backend de sonido (se recupera pasando al siguiente)."""


def audio_generativo_desactivado() -> bool:
    return os.environ.get(SIN_AUDIO_GENERATIVO, "") == "1"


def preparar_prompt_audio(prompt: str) -> str:
    """Quita adjetivos de intensidad baja y menciones de silencio de un ``prompt_sonido``.

    "Soft wind blows through trees, birds sing gently." -> "Wind blows through trees, birds sing."
    """
    texto = _SILENCIO.sub(" ", _INTENSIDAD_BAJA.sub(" ", prompt))
    texto = re.sub(r"\s+", " ", texto)
    texto = re.sub(r"\s+([,.;:!?])", r"\1", texto)  # "trees ," -> "trees,"
    texto = re.sub(r"([,;:])\s*(?=[.!?]|$)", "", texto)  # coma colgando antes del punto
    texto = re.sub(r"(^|[.!?]\s*)[,;:]\s*", r"\1", texto)  # coma al inicio de una frase
    texto = re.sub(r"(?:^|(?<=[.!?]))\s*[.!?]", "", texto).strip()  # frases vacías
    frases = re.split(r"(?<=[.!?])\s+", texto)
    texto = " ".join(f[:1].upper() + f[1:] for f in frases if f.strip(" .!?,;:"))
    return texto if re.search(r"[a-zA-Z]{3,}", texto) else prompt


def prompts_para_backend(nombre: str, prompt_sonido: str, cfg: SoundConfig) -> tuple[str, str]:
    """(prompt, negative prompt) que recibe el modelo de audio ``nombre``.

    A AudioLDM se le agrega ``cfg.audioldm_sufijo`` (", high quality, clear"). Como el
    negativo se calcula después, "low quality" sale del negativo para no contradecir al
    sufijo: así se midió en la prueba de 6.2.
    """
    prompt = preparar_prompt_audio(prompt_sonido)
    if nombre == "audioldm" and cfg.audioldm_sufijo:
        prompt = prompt.rstrip(" .;,") + cfg.audioldm_sufijo
    return prompt, negativo_compatible(cfg.negative_prompt, prompt)


def negativo_compatible(negativo: str, prompt: str) -> str:
    """Quita del negative prompt los términos que el prompt pide.

    Con "birds sing" y el negativo "singing", AudioLDM recibe órdenes opuestas.
    Se comparan raíces de 4 letras: "sing"/"singing", "voice"/"voices".
    """
    raices = {p[:4] for p in re.findall(r"[a-z]+", prompt.lower()) if len(p) >= 3}
    terminos = [t.strip() for t in negativo.split(",") if t.strip()]
    conservados = [
        t for t in terminos if not any(p[:4] in raices for p in re.findall(r"[a-z]+", t.lower()))
    ]
    return ", ".join(conservados)


class BackendSonido(Protocol):
    nombre: str

    def cargar(self) -> None:
        """Prepara el backend una vez por historia. Lanza si no está disponible."""

    def generar(self, escena: Escena, duracion_s: float, seed: int) -> tuple[np.ndarray, int]:
        """Audio (mono o (muestras, canales)) y su frecuencia de muestreo."""

    def liberar(self) -> None: ...

    def es_oom(self, exc: BaseException) -> bool: ...

    def info(self) -> dict[str, Any]:
        """Datos del backend para el manifest."""


def nombre_archivo_sonido(numero: int) -> str:
    """Clip tal como sale del backend (el mezclador produce ``ambience_n`` y ``mix_n``)."""
    return f"sfx_{numero}.wav"


def a_mono(audio: Any) -> np.ndarray:
    """Tensor o array (canales, muestras), (muestras, canales) o 1D -> mono float32."""
    if hasattr(audio, "detach"):
        audio = audio.detach().float().cpu().numpy()
    datos = np.asarray(audio, dtype=np.float32)
    if datos.ndim == 2:
        eje_canales = 0 if datos.shape[0] <= 8 and datos.shape[0] < datos.shape[1] else 1
        datos = datos.mean(axis=eje_canales)
    return np.nan_to_num(datos.reshape(-1)).astype(np.float32)


def fraccion_en_silencio(
    audio: np.ndarray, frecuencia: int, umbral_db: float = UMBRAL_HUECO_DB
) -> float:
    """Fracción de ventanas de 50 ms que están ``umbral_db`` por debajo de la más fuerte."""
    ventana = max(1, int(VENTANA_HUECO_S * frecuencia))
    n = audio.size // ventana
    if n == 0:
        return 1.0
    rms = np.sqrt(np.mean(np.square(audio[: n * ventana].reshape(n, ventana)), axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-9))
    return float(np.mean(db < db.max() - umbral_db))


def nivel_dbfs(audio: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
    return 20 * float(np.log10(max(rms, 1e-12)))


def problema_de_ambiente(audio: np.ndarray, frecuencia: int) -> str | None:
    """Motivo por el que un clip generativo no sirve como ambiente, o None si sirve."""
    nivel = nivel_dbfs(audio)
    if nivel < NIVEL_MINIMO_DBFS:
        return f"clip demasiado bajo ({nivel:.0f} dBFS)"
    silencio = fraccion_en_silencio(audio, frecuencia)
    if silencio > FRACCION_HUECO_MAX:
        return f"clip casi en silencio el {silencio:.0%} del tiempo"
    return None


def validar_audio(audio: np.ndarray, frecuencia: int) -> None:
    if frecuencia <= 0:
        raise SoundError(f"frecuencia de muestreo inválida: {frecuencia}")
    if audio.size < DURACION_MINIMA_S * frecuencia:
        raise SoundError(f"audio demasiado corto ({audio.size / frecuencia:.2f} s)")
    if not np.all(np.isfinite(audio)):
        raise SoundError("audio con valores no finitos")
    if float(np.sqrt(np.mean(np.square(audio)))) < RMS_MINIMO:
        raise SoundError("audio en silencio")


# ---------------------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------------------
@dataclass
class ResultadoSonido:
    escena: int
    ruta: Path
    backend: str
    duracion_s: float
    sample_rate: int
    segundos: float
    prompt: str
    etiquetas: list[str]
    detalle: dict[str, Any] = field(default_factory=dict)

    def a_dict(self) -> dict[str, Any]:
        return {
            "escena": self.escena,
            "archivo": self.ruta.name,
            "backend": self.backend,
            "duracion_s": self.duracion_s,
            "sample_rate": self.sample_rate,
            "segundos": self.segundos,
            "prompt": self.prompt,
            "etiquetas": self.etiquetas,
            "detalle": self.detalle,
        }


@dataclass
class EtapaSonido:
    sonidos: list[ResultadoSonido]
    backends: dict[str, dict[str, Any]] = field(default_factory=dict)
    fallbacks: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    metricas: list[StageMetrics] = field(default_factory=list)

    def por_escena(self, numero: int) -> ResultadoSonido:
        for sonido in self.sonidos:
            if sonido.escena == numero:
                return sonido
        raise KeyError(numero)

    def a_dict(self) -> dict[str, Any]:
        return {
            "sonidos": [s.a_dict() for s in sorted(self.sonidos, key=lambda s: s.escena)],
            "backends": self.backends,
            "fallbacks": self.fallbacks,
            "errores": self.errores,
            "metricas": [m.as_dict() for m in self.metricas],
        }


# ---------------------------------------------------------------------------------------
# Generador (orquesta la cadena)
# ---------------------------------------------------------------------------------------
class GeneradorSonido:
    def __init__(
        self,
        cfg: SoundConfig,
        seed_base: int = 1234,
        fabrica: Callable[[str], BackendSonido] | None = None,
    ) -> None:
        self.cfg = cfg
        self.seed_base = seed_base
        self.fabrica = fabrica or (lambda nombre: crear_backend(nombre, cfg))

    def generar(
        self, bible: StoryBible, carpeta: Path, numeros: Sequence[int] | None = None
    ) -> EtapaSonido:
        carpeta.mkdir(parents=True, exist_ok=True)
        elegidas = set(numeros) if numeros is not None else None
        pendientes = [e for e in bible.escenas if elegidas is None or e.numero in elegidas]
        etapa = EtapaSonido(sonidos=[])
        backends = list(dict.fromkeys(self.cfg.backends))
        if "procedural" not in backends:
            backends.append("procedural")  # la última red: la historia siempre tiene sonido

        for nombre in backends:
            if not pendientes:
                break
            pendientes = self._con_backend(nombre, pendientes, carpeta, etapa)
        if pendientes:
            raise SoundError(f"Escenas sin sonido: {[e.numero for e in pendientes]}")

        etapa.sonidos.sort(key=lambda s: s.escena)
        logger.info(
            "etapa_sonido_terminada",
            extra=kv(
                backends={s.escena: s.backend for s in etapa.sonidos}, fallbacks=etapa.fallbacks
            ),
        )
        return etapa

    def _con_backend(
        self, nombre: str, pendientes: list[Escena], carpeta: Path, etapa: EtapaSonido
    ) -> list[Escena]:
        """Genera con ``nombre`` las escenas pendientes; devuelve las que siguen sin sonido."""
        try:
            if nombre in GENERATIVOS and audio_generativo_desactivado():
                raise SoundError(
                    f"desactivado para demostrar el respaldo ({SIN_AUDIO_GENERATIVO}=1)"
                )
            backend = self.fabrica(nombre)
            with track_stage(f"sonido_{nombre}_carga") as m_carga:
                backend.cargar()
            etapa.metricas.append(m_carga)
            etapa.backends[nombre] = {"estado": "cargado", **backend.info()}
        except Exception as exc:
            mensaje = f"{type(exc).__name__}: {exc}"[:400]
            etapa.backends[nombre] = {"estado": "no_disponible", "detalle": mensaje}
            etapa.fallbacks.append(f"sonido:{nombre}:no_disponible")
            etapa.errores.append(f"{nombre}: {mensaje}")
            logger.warning("sonido_backend_no_disponible", extra=kv(backend=nombre, error=mensaje))
            return pendientes

        restantes: list[Escena] = []
        try:
            for i, escena in enumerate(pendientes):
                try:
                    etapa.sonidos.append(self._escena(backend, escena, carpeta, etapa))
                except Exception as exc:
                    mensaje = f"{type(exc).__name__}: {exc}"[:400]
                    etapa.fallbacks.append(f"sonido:escena_{escena.numero}:{nombre}_fallo")
                    etapa.errores.append(f"Escena {escena.numero} con {nombre}: {mensaje}")
                    logger.error(
                        "sonido_escena_fallo",
                        extra=kv(escena=escena.numero, backend=nombre, error=mensaje),
                    )
                    restantes.append(escena)
                    if backend.es_oom(exc):
                        free_cuda_memory()
                        restantes.extend(pendientes[i + 1 :])  # sin memoria: siguiente backend
                        break
        finally:
            backend.liberar()
        return restantes

    def _escena(
        self, backend: BackendSonido, escena: Escena, carpeta: Path, etapa: EtapaSonido
    ) -> ResultadoSonido:
        seed = self.seed_base + escena.numero
        detalle: dict[str, Any] = {}
        with track_stage(f"sonido_escena_{escena.numero}") as metrica:
            inicio = time.perf_counter()
            for intento in (1, 2):
                crudo, frecuencia = backend.generar(escena, self.cfg.duration_s, seed)
                audio = a_mono(crudo)
                validar_audio(audio, frecuencia)
                if backend.nombre not in GENERATIVOS:
                    break
                problema = problema_de_ambiente(audio, frecuencia)
                detalle.update(
                    intentos=intento,
                    fraccion_silencio=round(fraccion_en_silencio(audio, frecuencia), 3),
                    nivel_dbfs=round(nivel_dbfs(audio), 1),
                )
                if problema is None:
                    break
                logger.warning(
                    "sonido_clip_no_apto",
                    extra=kv(escena=escena.numero, backend=backend.nombre, problema=problema),
                )
                if intento == 2:
                    raise SoundError(f"{problema} (2 intentos)")
                seed += DESFASE_SEED_REINTENTO
            segundos = time.perf_counter() - inicio
            ruta = carpeta / nombre_archivo_sonido(escena.numero)
            sf.write(str(ruta), np.clip(audio, -1.0, 1.0), frecuencia, subtype=SUBTIPO_WAV)
            duracion = round(audio.size / frecuencia, 3)
            metrica.extra.update(backend=backend.nombre, duracion_audio_s=duracion, seed=seed)
        etapa.metricas.append(metrica)
        return ResultadoSonido(
            escena=escena.numero,
            ruta=ruta,
            backend=backend.nombre,
            duracion_s=duracion,
            sample_rate=frecuencia,
            segundos=round(segundos, 3),
            prompt=escena.prompt_sonido,
            etiquetas=[str(e) for e in escena.etiquetas_sonido],
            detalle={**(getattr(backend, "ultimo_detalle", {}) or {}), **detalle, "seed": seed},
        )


# ---------------------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------------------
class ProceduralBackend:
    """C · síntesis propia (CPU). No necesita nada descargado."""

    nombre = "procedural"

    def cargar(self) -> None:
        return None

    def generar(self, escena: Escena, duracion_s: float, seed: int) -> tuple[np.ndarray, int]:
        return sintetizar(escena.etiquetas_sonido, duracion_s, FRECUENCIA, seed), FRECUENCIA

    def liberar(self) -> None:
        return None

    def es_oom(self, exc: BaseException) -> bool:
        return False

    def info(self) -> dict[str, Any]:
        return {"backend": self.nombre, "frecuencia": FRECUENCIA}


class BibliotecaBackend:
    """B · clips CC0 locales por etiqueta."""

    nombre = "library"

    def __init__(self, raiz: Path | None = None) -> None:
        self.raiz = raiz
        self.biblioteca: BibliotecaSonidos | None = None
        self.ultimo_detalle: dict[str, Any] = {}

    def cargar(self) -> None:
        self.biblioteca = BibliotecaSonidos(self.raiz)
        if not self.biblioteca.clips:
            raise SoundError(f"biblioteca vacía o sin clips CC0 en {self.biblioteca.raiz}")

    def generar(self, escena: Escena, duracion_s: float, seed: int) -> tuple[np.ndarray, int]:
        if self.biblioteca is None:
            raise SoundError("la biblioteca no está cargada")
        clip = self.biblioteca.buscar([str(e) for e in escena.etiquetas_sonido], seed)
        if clip is None:
            raise SoundError(f"sin clip para {[str(e) for e in escena.etiquetas_sonido]}")
        self.ultimo_detalle = clip.a_dict()
        return cargar_audio_mono(clip.ruta)

    def liberar(self) -> None:
        self.biblioteca = None

    def es_oom(self, exc: BaseException) -> bool:
        return False

    def info(self) -> dict[str, Any]:
        clips = len(self.biblioteca.clips) if self.biblioteca else 0
        return {"backend": self.nombre, "clips": clips}


class DiffusersSonidoBackend:
    """A · Stable Audio 3 Small-SFX, Stable Audio Open 1.0 o AudioLDM en GPU (fp16)."""

    def __init__(self, nombre: str, cfg: SoundConfig) -> None:
        if nombre not in GENERATIVOS:
            raise ValueError(f"Backend generativo desconocido: {nombre}")
        self.nombre = nombre
        self.cfg = cfg
        self.repo = {
            "sa3": cfg.sa3_repo_id,
            "sao": cfg.sao_repo_id,
            "audioldm": cfg.audioldm_repo_id,
        }[nombre]
        self.pipe: Any = None
        self.snapshot: Path | None = None
        self.ultimo_detalle: dict[str, Any] = {}

    def cargar(self) -> None:
        snapshot = local_snapshot(self.repo)  # ModelNotDownloadedError si falta
        if not is_diffusers_repo(snapshot):
            raise ModelNotDownloadedError(f"'{self.repo}' no está en formato diffusers")
        import torch

        if not torch.cuda.is_available():
            raise SoundError("CUDA no disponible para el sonido generativo")
        if self.nombre == "sa3":
            from diffusers import StableAudio3Pipeline as Pipeline
        elif self.nombre == "audioldm":
            from diffusers import AudioLDMPipeline as Pipeline
        else:
            from diffusers import StableAudioPipeline as Pipeline
        pipe = Pipeline.from_pretrained(
            str(snapshot), torch_dtype=torch.float16, variant=diffusers_variant(snapshot)
        )
        # AudioLDM (421M) cabe entero en 4 GB; Stable Audio necesita offload (F0).
        if self.cfg.cpu_offload and self.nombre != "audioldm":
            pipe.enable_model_cpu_offload()
        else:
            pipe.to("cuda")
        pipe.set_progress_bar_config(disable=True)
        self.pipe, self.snapshot = pipe, snapshot

    def generar(self, escena: Escena, duracion_s: float, seed: int) -> tuple[np.ndarray, int]:
        import torch

        generador = torch.Generator("cuda").manual_seed(seed)
        cfg, pipe = self.cfg, self.pipe
        prompt, negativo = prompts_para_backend(self.nombre, escena.prompt_sonido, cfg)
        self.ultimo_detalle = {"prompt_efectivo": prompt, "negativo_efectivo": negativo}
        if self.nombre == "audioldm":
            salida = pipe(
                prompt,
                negative_prompt=negativo,
                audio_length_in_s=duracion_s,
                num_inference_steps=cfg.audioldm_steps,
                guidance_scale=cfg.audioldm_guidance,
                generator=generador,
            )
            return a_mono(salida.audios[0]), int(pipe.vocoder.config.sampling_rate)
        if self.nombre == "sa3":
            salida = pipe(
                prompt,
                duration=duracion_s,
                num_inference_steps=cfg.sa3_steps,
                generator=generador,
            )
            return a_mono(salida.audios[0]), int(pipe.vae.config.sampling_rate)
        salida = pipe(
            prompt,
            negative_prompt=negativo,
            audio_end_in_s=duracion_s,
            num_inference_steps=cfg.sao_steps,
            guidance_scale=cfg.sao_guidance,
            generator=generador,
        )
        return a_mono(salida.audios[0]), int(pipe.vae.sampling_rate)

    def liberar(self) -> None:
        self.pipe = None
        free_cuda_memory()

    def es_oom(self, exc: BaseException) -> bool:
        try:
            import torch
        except ImportError:  # pragma: no cover - sin torch no hay OOM de CUDA
            return False
        return isinstance(exc, torch.cuda.OutOfMemoryError)

    def info(self) -> dict[str, Any]:
        return {
            "backend": self.nombre,
            "repo": self.repo,
            "revision": self.snapshot.name if self.snapshot else None,
        }


def crear_backend(
    nombre: str, cfg: SoundConfig, raiz_biblioteca: Path | None = None
) -> BackendSonido:
    if nombre in GENERATIVOS:
        return DiffusersSonidoBackend(nombre, cfg)
    if nombre == "library":
        return BibliotecaBackend(raiz_biblioteca)
    if nombre == "procedural":
        return ProceduralBackend()
    raise ValueError(f"Backend de sonido desconocido: {nombre}")
