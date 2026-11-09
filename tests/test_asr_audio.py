"""Carga de audio para Whisper sin PyAV (soundfile + remuestreo a 16 kHz)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from storybook.evaluation.asr_check import FRECUENCIA_WHISPER, cargar_audio_16k


def test_cargar_audio_16k_estereo_22050(tmp_path: Path) -> None:
    frecuencia, segundos = 22_050, 1.5
    t = np.arange(int(frecuencia * segundos)) / frecuencia
    tono = 0.3 * np.sin(2 * np.pi * 440 * t)
    ruta = tmp_path / "voz.wav"
    sf.write(ruta, np.stack([tono, tono], axis=1), frecuencia)

    audio = cargar_audio_16k(ruta)

    assert audio.dtype == np.float32 and audio.ndim == 1
    assert abs(len(audio) - int(segundos * FRECUENCIA_WHISPER)) <= 2
    assert np.isfinite(audio).all() and np.abs(audio).max() <= 1.0


def test_cargar_audio_16k_sin_remuestreo(tmp_path: Path) -> None:
    ruta = tmp_path / "ya16k.wav"
    sf.write(ruta, np.zeros(FRECUENCIA_WHISPER, dtype=np.float32), FRECUENCIA_WHISPER)
    assert len(cargar_audio_16k(ruta)) == FRECUENCIA_WHISPER
