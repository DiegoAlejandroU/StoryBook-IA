"""Tests del WER y de la verificación de la narración con un transcriptor falso.

No se carga faster-whisper: ``WhisperChecker`` se crea sin ``__init__`` y se le inyecta un
modelo falso con la misma interfaz (``transcribe`` -> segmentos, info).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from storybook.evaluation.asr_check import (
    FRECUENCIA_WHISPER,
    ASRError,
    ResultadoASR,
    WhisperChecker,
    calcular_wer,
    normalizar_texto_wer,
)


# -- normalización ---------------------------------------------------------------------
@pytest.mark.parametrize(
    ("entrada", "salida"),
    [
        ("¿Quién anda AHÍ?", "quien anda ahi"),
        ("¡Corre, Lucía!", "corre lucia"),
        ("El niño   vio\nla luz.", "el nino vio la luz"),
        ("«Ven» —dijo— ...", "ven dijo"),
        ("Pingüino, acción", "pinguino accion"),
        ("   ", ""),
    ],
)
def test_normalizar_texto_wer(entrada: str, salida: str) -> None:
    assert normalizar_texto_wer(entrada) == salida


# -- WER -------------------------------------------------------------------------------
def test_wer_identico_es_cero() -> None:
    texto = "Lucía caminó hacia el faro mientras el viento sacudía su impermeable."
    assert calcular_wer(texto, texto) == 0.0


def test_wer_ignora_tildes_signos_y_mayusculas() -> None:
    assert calcular_wer("¿Quién anda ahí?", "quien anda ahi") == 0.0
    assert calcular_wer("El faro, apagado.", "el faro apagado") == 0.0


def test_wer_una_sustitucion() -> None:
    assert calcular_wer("el faro estaba apagado", "el faro estaba encendido") == 0.25


def test_wer_borrado_e_insercion() -> None:
    assert calcular_wer("uno dos tres cuatro", "uno dos tres") == 0.25
    assert calcular_wer("uno dos", "uno dos tres cuatro") == 1.0  # puede superar 1


def test_wer_hipotesis_vacia_es_uno() -> None:
    assert calcular_wer("hola mundo", "") == 1.0


@pytest.mark.parametrize("referencia", ["", "   ", "¿?¡!..."])
def test_wer_referencia_vacia_es_error(referencia: str) -> None:
    with pytest.raises(ASRError):
        calcular_wer(referencia, "algo")


def test_wer_redondeado_a_4_decimales() -> None:
    wer = calcular_wer("a b c d e f g", "a b c d e f x")
    assert wer == round(1 / 7, 4)


# -- WhisperChecker con modelo falso ---------------------------------------------------
@dataclass
class _Segmento:
    text: str


@dataclass
class _Info:
    duration: float


class FakeWhisper:
    def __init__(self, textos: list[str], duracion: float = 2.0) -> None:
        self.textos = textos
        self.duracion = duracion
        self.llamadas: list[dict[str, Any]] = []

    def transcribe(self, audio: np.ndarray, **kwargs: Any) -> tuple[Any, _Info]:
        self.llamadas.append({"audio": audio, **kwargs})
        return (_Segmento(t) for t in self.textos), _Info(self.duracion)


def _checker(modelo: FakeWhisper, idioma: str = "es") -> WhisperChecker:
    checker = WhisperChecker.__new__(WhisperChecker)
    checker.idioma = idioma
    checker._modelo = modelo
    return checker


@pytest.fixture
def wav(tmp_path: Path) -> Path:
    frecuencia = 22_050
    t = np.arange(frecuencia * 2) / frecuencia
    ruta = tmp_path / "voice_1.wav"
    sf.write(ruta, (0.2 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), frecuencia)
    return ruta


def test_transcribir_une_segmentos_y_pasa_audio_16k(wav: Path) -> None:
    modelo = FakeWhisper([" El faro ", "estaba apagado. "])
    texto, duracion = _checker(modelo).transcribir(wav)
    assert texto == "El faro estaba apagado."
    assert duracion == 2.0
    llamada = modelo.llamadas[0]
    assert llamada["language"] == "es"
    audio = llamada["audio"]
    assert audio.dtype == np.float32 and audio.ndim == 1
    assert abs(len(audio) - 2 * FRECUENCIA_WHISPER) <= 2


def test_evaluar_devuelve_wer(wav: Path) -> None:
    modelo = FakeWhisper(["El faro estaba encendido."], duracion=2.5)
    resultado = _checker(modelo).evaluar(wav, "El faro estaba apagado.")
    assert isinstance(resultado, ResultadoASR)
    assert resultado.transcripcion == "El faro estaba encendido."
    assert resultado.wer == 0.25
    assert resultado.duracion_audio_s == 2.5


def test_evaluar_sin_transcripcion(wav: Path) -> None:
    resultado = _checker(FakeWhisper([])).evaluar(wav, "Había una vez.")
    assert resultado.transcripcion == "" and resultado.wer == 1.0


def test_evaluar_referencia_vacia(wav: Path) -> None:
    with pytest.raises(ASRError):
        _checker(FakeWhisper(["hola"])).evaluar(wav, "...")
