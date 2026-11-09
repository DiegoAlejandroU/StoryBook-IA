"""Verificación de la narración: transcripción local (faster-whisper, CPU int8) y WER.

El WER (Word Error Rate) compara el texto mostrado en pantalla con lo que un ASR entiende
del audio sintetizado: WER = (sustituciones + borrados + inserciones) / palabras de
referencia. Un WER bajo indica que la voz corresponde al texto (dimensión "Audio y
contenido" del enunciado).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import jiwer


class ASRError(Exception):
    """Errores de transcripción o de cálculo de WER."""


def normalizar_texto_wer(texto: str) -> str:
    """Minúsculas, sin tildes ni signos, espacios simples.

    Se quitan tildes porque el ASR a veces las omite y eso no es un error de la voz.
    """
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^\w\s]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def calcular_wer(referencia: str, hipotesis: str) -> float:
    ref = normalizar_texto_wer(referencia)
    hip = normalizar_texto_wer(hipotesis)
    if not ref:
        raise ASRError("La referencia está vacía tras normalizar")
    return round(float(jiwer.wer(ref, hip)), 4)


@dataclass(frozen=True)
class ResultadoASR:
    transcripcion: str
    wer: float
    duracion_audio_s: float


class WhisperChecker:
    """Carga faster-whisper una vez y transcribe varios WAV (CPU, int8)."""

    def __init__(
        self,
        modelo: str = "small",
        compute_type: str = "int8",
        idioma: str = "es",
        cpu_threads: int = 0,
    ) -> None:
        from faster_whisper import WhisperModel

        self.idioma = idioma
        self._modelo = WhisperModel(
            modelo,
            device="cpu",
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            local_files_only=True,
        )

    def transcribir(self, wav: Path) -> tuple[str, float]:
        segmentos, info = self._modelo.transcribe(
            str(wav), language=self.idioma, beam_size=5, vad_filter=False
        )
        texto = " ".join(s.text.strip() for s in segmentos)
        return texto.strip(), float(info.duration)

    def evaluar(self, wav: Path, texto_referencia: str) -> ResultadoASR:
        transcripcion, duracion = self.transcribir(wav)
        return ResultadoASR(transcripcion, calcular_wer(texto_referencia, transcripcion), duracion)
