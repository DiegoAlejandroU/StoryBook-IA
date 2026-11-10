"""Mezcla en CPU: ambiente a la duración de la voz, loudness y ducking (CLAUDE.md §8).

Por escena:

1. Voz y ambiente se remuestrean a ``mix.sample_rate`` (Piper sale a 22,05 kHz, AudioLDM a
   16 kHz, Stable Audio a 44,1 kHz).
2. La voz se rodea de ``pre_roll_s`` y ``post_roll_s`` de silencio, y el ambiente se repite
   con *crossfade* de igual potencia hasta esa duración, con fundidos de entrada y salida.
3. Loudness (pyloudnorm, ITU-R BS.1770): voz a ``voz_lufs`` y ambiente
   ``ambiente_bajo_voz_db`` por debajo.
4. Ducking: mientras hay voz, el ambiente baja ``ducking_db`` más (envolvente con ataque
   rápido y relajación lenta). Así queda entre 12 y 18 dB bajo la voz.
5. Exporta ``ambience_n.wav`` (ambiente al nivel relativo, sin ducking: la UI lo reproduce
   con su propio control) y ``mix_n.wav`` (voz + ambiente con ducking), PCM 16 bits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from storybook.config import MixConfig
from storybook.gpu import StageMetrics, track_stage
from storybook.logging_utils import get_logger, kv
from storybook.sound.library import cargar_audio_mono

logger = get_logger(__name__)

PICO_MAXIMO: Final = 0.98
VENTANA_ENVOLVENTE_S: Final = 0.02
ATAQUE_S: Final = 0.03
RELAJACION_S: Final = 0.35
UMBRAL_VOZ_DB: Final = -35.0  # respecto al máximo de la envolvente de la voz
FUNDIDO_ENTRADA_S: Final = 0.5
FUNDIDO_SALIDA_S: Final = 1.5
SUBTIPO_WAV: Final = "PCM_16"


class MixError(Exception):
    """Error al mezclar una escena."""


def nombre_archivo_ambiente(numero: int) -> str:
    return f"ambience_{numero}.wav"


def nombre_archivo_mezcla(numero: int) -> str:
    return f"mix_{numero}.wav"


# ---------------------------------------------------------------------------------------
# Utilidades de señal
# ---------------------------------------------------------------------------------------
def remuestrear(audio: np.ndarray, origen: int, destino: int) -> np.ndarray:
    if origen == destino:
        return audio.astype(np.float64)
    divisor = math.gcd(origen, destino)
    return resample_poly(audio.astype(np.float64), destino // divisor, origen // divisor)


def ajustar_duracion(ambiente: np.ndarray, n: int, crossfade: int) -> np.ndarray:
    """Repite ``ambiente`` con crossfade de igual potencia hasta ``n`` muestras."""
    if ambiente.size == 0:
        raise MixError("ambiente vacío")
    if ambiente.size >= n:
        return ambiente[:n].astype(np.float64)
    cf = max(1, min(crossfade, ambiente.size // 2))
    angulo = np.linspace(0.0, np.pi / 2, cf)
    sale, entra = np.cos(angulo), np.sin(angulo)
    salida = ambiente.astype(np.float64)
    while salida.size < n:
        solape = salida[-cf:] * sale + ambiente[:cf] * entra
        salida = np.concatenate([salida[:-cf], solape, ambiente[cf:]])
    return salida[:n]


def aplicar_fundidos(audio: np.ndarray, sr: int, entrada_s: float, salida_s: float) -> np.ndarray:
    resultado = audio.copy()
    n_in = min(int(entrada_s * sr), resultado.size // 2)
    n_out = min(int(salida_s * sr), resultado.size // 2)
    if n_in:
        resultado[:n_in] *= np.linspace(0.0, 1.0, n_in)
    if n_out:
        resultado[-n_out:] *= np.linspace(1.0, 0.0, n_out)
    return resultado


def medir_lufs(audio: np.ndarray, sr: int) -> float:
    """Loudness integrado (LUFS). ``-inf`` si es silencio; RMS si dura menos de un bloque."""
    import pyloudnorm

    if not np.any(audio):
        return float("-inf")
    medidor = pyloudnorm.Meter(sr)
    if audio.size < int(medidor.block_size * sr) + 1:
        rms = float(np.sqrt(np.mean(np.square(audio))))
        return 20 * math.log10(rms) - 0.691 if rms > 0 else float("-inf")
    return float(medidor.integrated_loudness(audio))


def ajustar_lufs(audio: np.ndarray, sr: int, objetivo: float) -> tuple[np.ndarray, float]:
    """Escala ``audio`` a ``objetivo`` LUFS. Devuelve el audio y el loudness original."""
    medido = medir_lufs(audio, sr)
    if not math.isfinite(medido):
        return audio, medido
    return audio * 10 ** ((objetivo - medido) / 20), medido


def actividad_voz(voz: np.ndarray, sr: int) -> np.ndarray:
    """Envolvente 0..1 de "hay voz", por muestra, con ataque rápido y relajación lenta."""
    ventana = max(1, int(VENTANA_ENVOLVENTE_S * sr))
    tramas = math.ceil(voz.size / ventana)
    relleno = np.pad(voz, (0, tramas * ventana - voz.size))
    rms = np.sqrt(np.mean(np.square(relleno.reshape(tramas, ventana)), axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-9))
    activa = (db > db.max() + UMBRAL_VOZ_DB).astype(float)
    a_sube = 1 - math.exp(-VENTANA_ENVOLVENTE_S / ATAQUE_S)
    a_baja = 1 - math.exp(-VENTANA_ENVOLVENTE_S / RELAJACION_S)
    suave = np.empty_like(activa)
    nivel = 0.0
    for i, valor in enumerate(activa):
        nivel += (a_sube if valor > nivel else a_baja) * (valor - nivel)
        suave[i] = nivel
    return np.repeat(suave, ventana)[: voz.size]


def limitar(audio: np.ndarray, pico: float = PICO_MAXIMO) -> tuple[np.ndarray, float]:
    """Si el pico supera ``pico``, baja la señal completa. Devuelve audio y ganancia en dB."""
    actual = float(np.max(np.abs(audio))) if audio.size else 0.0
    if actual <= pico:
        return audio, 0.0
    return audio * (pico / actual), 20 * math.log10(pico / actual)


# ---------------------------------------------------------------------------------------
# Mezcla
# ---------------------------------------------------------------------------------------
@dataclass
class MezclaEscena:
    ambiente: np.ndarray
    mezcla: np.ndarray
    sample_rate: int
    metricas: dict[str, Any]


def mezclar(
    voz: np.ndarray, sr_voz: int, ambiente: np.ndarray, sr_ambiente: int, cfg: MixConfig
) -> MezclaEscena:
    """Mezcla una escena en memoria (sin archivos): lo usan ``mezclar_historia`` y los tests."""
    sr = cfg.sample_rate
    voz_r = remuestrear(voz, sr_voz, sr)
    amb_r = remuestrear(ambiente, sr_ambiente, sr)
    if not np.any(voz_r):
        raise MixError("la voz está en silencio")
    voz_r = np.concatenate(
        [np.zeros(int(cfg.pre_roll_s * sr)), voz_r, np.zeros(int(cfg.post_roll_s * sr))]
    )
    amb_r = ajustar_duracion(amb_r, voz_r.size, int(cfg.crossfade_s * sr))
    amb_r = aplicar_fundidos(amb_r, sr, FUNDIDO_ENTRADA_S, FUNDIDO_SALIDA_S)

    voz_n, lufs_voz_original = ajustar_lufs(voz_r, sr, cfg.voz_lufs)
    amb_n, lufs_amb_original = ajustar_lufs(amb_r, sr, cfg.voz_lufs - cfg.ambiente_bajo_voz_db)
    actividad = actividad_voz(voz_n, sr)
    amb_duck = amb_n * 10 ** (-cfg.ducking_db * actividad / 20)
    mezcla, limitacion_db = limitar(voz_n + amb_duck)
    ambiente_final, _ = limitar(amb_n)

    lufs_voz, lufs_amb = medir_lufs(voz_n, sr), medir_lufs(amb_n, sr)
    metricas = {
        "duracion_s": round(mezcla.size / sr, 3),
        "lufs_voz_original": round(lufs_voz_original, 2),
        "lufs_ambiente_original": round(lufs_amb_original, 2),
        "lufs_voz": round(lufs_voz, 2),
        "lufs_ambiente": round(lufs_amb, 2),
        "ambiente_bajo_voz_db": round(lufs_voz - lufs_amb, 2),
        "ambiente_bajo_voz_hablando_db": round(lufs_voz - lufs_amb + cfg.ducking_db, 2),
        "ducking_db": cfg.ducking_db,
        "fraccion_con_voz": round(float(np.mean(actividad > 0.5)), 3),
        "limitacion_db": round(limitacion_db, 2),
        "pico_mezcla": round(float(np.max(np.abs(mezcla))), 4),
    }
    return MezclaEscena(ambiente_final, mezcla, sr, metricas)


@dataclass
class ResultadoMezcla:
    escena: int
    ambiente: Path
    mezcla: Path
    sample_rate: int
    fuente_sonido: str
    metricas: dict[str, Any]

    def a_dict(self) -> dict[str, Any]:
        return {
            "escena": self.escena,
            "ambiente": self.ambiente.name,
            "mezcla": self.mezcla.name,
            "sample_rate": self.sample_rate,
            "fuente_sonido": self.fuente_sonido,
            **self.metricas,
        }


@dataclass
class EtapaMezcla:
    mezclas: list[ResultadoMezcla]
    metricas: list[StageMetrics] = field(default_factory=list)

    def a_dict(self) -> dict[str, Any]:
        return {
            "mezclas": [m.a_dict() for m in self.mezclas],
            "metricas": [m.as_dict() for m in self.metricas],
        }


def mezclar_historia(
    narraciones: dict[int, Path],
    sonidos: dict[int, tuple[Path, str]],
    carpeta: Path,
    cfg: MixConfig,
) -> EtapaMezcla:
    """Mezcla cada escena: ``narraciones[n]`` = ``voice_n.wav``; ``sonidos[n]`` =
    (``sfx_n.wav``, backend que lo produjo). Escribe ``ambience_n.wav`` y ``mix_n.wav``."""
    carpeta.mkdir(parents=True, exist_ok=True)
    faltan = sorted(set(narraciones) - set(sonidos))
    if faltan:
        raise MixError(f"Escenas sin ambiente para mezclar: {faltan}")
    etapa = EtapaMezcla(mezclas=[])
    for numero in sorted(narraciones):
        ruta_sonido, fuente = sonidos[numero]
        with track_stage(f"mezcla_escena_{numero}") as metrica:
            voz, sr_voz = cargar_audio_mono(narraciones[numero])
            ambiente, sr_amb = cargar_audio_mono(ruta_sonido)
            escena = mezclar(voz, sr_voz, ambiente, sr_amb, cfg)
            ruta_amb = carpeta / nombre_archivo_ambiente(numero)
            ruta_mix = carpeta / nombre_archivo_mezcla(numero)
            sf.write(str(ruta_amb), escena.ambiente, escena.sample_rate, subtype=SUBTIPO_WAV)
            sf.write(str(ruta_mix), escena.mezcla, escena.sample_rate, subtype=SUBTIPO_WAV)
            metrica.extra.update(escena.metricas)
        etapa.metricas.append(metrica)
        etapa.mezclas.append(
            ResultadoMezcla(numero, ruta_amb, ruta_mix, escena.sample_rate, fuente, escena.metricas)
        )
        logger.info("mezcla_escena", extra=kv(escena=numero, fuente=fuente, **escena.metricas))
    return etapa
