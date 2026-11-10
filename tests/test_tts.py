"""Tests de la etapa de voz con un backend TTS falso (sin piper ni kokoro)."""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from storybook.config import VoiceConfig
from storybook.schemas import StoryBible
from storybook.voice.tts import (
    SILENCIO_FINAL_S,
    KokoroBackend,
    Narrador,
    PiperBackend,
    TTSError,
    TTSModelError,
    a_mono_float32,
    crear_backend,
    leer_wav_pcm,
    nombre_archivo_voz,
    normalizar_texto_tts,
)

FRECUENCIA = 22_050


class FakeTTS:
    """Un tono cuya duración es proporcional al número de caracteres."""

    nombre = "fake"

    def __init__(self, *, fallar_carga: bool = False, fallar_en: str | None = None) -> None:
        self.cargas = 0
        self.liberado = 0
        self.textos: list[str] = []
        self.fallar_carga = fallar_carga
        self.fallar_en = fallar_en

    def cargar(self) -> None:
        if self.fallar_carga:
            raise RuntimeError("onnxruntime no disponible")
        self.cargas += 1

    def sintetizar(self, texto: str) -> tuple[np.ndarray, int]:
        if self.fallar_en and self.fallar_en in texto:
            raise RuntimeError("fonemizador")
        self.textos.append(texto)
        n = len(texto) * 100
        t = np.arange(n) / FRECUENCIA
        return (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), FRECUENCIA

    def liberar(self) -> None:
        self.liberado += 1

    def info(self) -> dict[str, Any]:
        return {"backend": self.nombre}


@pytest.fixture
def bible(bible_dict: dict) -> StoryBible:
    return StoryBible.model_validate(bible_dict)


def test_narra_las_cinco_escenas_con_una_carga(bible: StoryBible, tmp_path: Path) -> None:
    backend = FakeTTS()
    etapa = Narrador(VoiceConfig(), backend).narrar_bible(bible, tmp_path)

    assert backend.cargas == 1 and backend.liberado == 1
    assert [n.escena for n in etapa.narraciones] == [1, 2, 3, 4, 5]
    for n in etapa.narraciones:
        assert n.ruta == tmp_path / nombre_archivo_voz(n.escena)
        info = sf.info(str(n.ruta))
        assert info.samplerate == FRECUENCIA and info.channels == 1
        assert info.subtype == "PCM_16"
        assert n.duracion_s == pytest.approx(info.duration, abs=1e-3)
        esperado = n.caracteres * 100 / FRECUENCIA + SILENCIO_FINAL_S
        assert n.duracion_s == pytest.approx(esperado, abs=0.01)
        assert n.rtf is not None and n.rtf >= 0
    assert etapa.duracion_total_s == pytest.approx(sum(n.duracion_s for n in etapa.narraciones))
    datos = etapa.a_dict()
    assert datos["backend"] == {"backend": "fake"}
    assert datos["narraciones"][0]["archivo"] == "voice_1.wav"


def test_termina_en_silencio(bible: StoryBible, tmp_path: Path) -> None:
    etapa = Narrador(VoiceConfig(), FakeTTS()).narrar_bible(bible, tmp_path, numeros=[2])
    datos, fr = sf.read(str(etapa.narraciones[0].ruta))
    cola = datos[-int(SILENCIO_FINAL_S * fr) :]
    assert np.max(np.abs(cola)) == 0.0


def test_regenerar_una_escena(bible: StoryBible, tmp_path: Path) -> None:
    backend = FakeTTS()
    etapa = Narrador(VoiceConfig(), backend).narrar_bible(bible, tmp_path, numeros=[4])
    assert [n.escena for n in etapa.narraciones] == [4]
    assert len(backend.textos) == 1
    assert not (tmp_path / "voice_1.wav").exists()


def test_error_de_carga(tmp_path: Path) -> None:
    backend = FakeTTS(fallar_carga=True)
    with pytest.raises(TTSModelError, match="onnxruntime"):
        Narrador(VoiceConfig(), backend).narrar([(1, "Hola.")], tmp_path)
    assert backend.liberado == 1


def test_error_de_sintesis_indica_la_escena(tmp_path: Path) -> None:
    backend = FakeTTS(fallar_en="dragón")
    with pytest.raises(TTSError, match="escena 2"):
        Narrador(VoiceConfig(), backend).narrar([(1, "Hola."), (2, "El dragón.")], tmp_path)
    assert backend.liberado == 1


def test_audio_vacio_es_error(tmp_path: Path) -> None:
    class Mudo(FakeTTS):
        def sintetizar(self, texto: str) -> tuple[np.ndarray, int]:
            return np.zeros(1000, dtype=np.float32), FRECUENCIA

    with pytest.raises(TTSError, match="vacía"):
        Narrador(VoiceConfig(), Mudo()).narrar([(1, "Hola.")], tmp_path)


@pytest.mark.parametrize(
    ("entrada", "salida"),
    [
        ("«Hola» —dijo ella—  y   se fue", '"Hola", dijo ella, y se fue.'),
        ("Línea uno\nlínea dos", "Línea uno línea dos."),
        ("¿Quién anda ahí?", "¿Quién anda ahí?"),
        ("Esperó…", "Esperó..."),
        ("Fin , dijo .", "Fin, dijo."),
    ],
)
def test_normalizar_texto_tts(entrada: str, salida: str) -> None:
    assert normalizar_texto_tts(entrada) == salida


def test_normalizar_texto_vacio() -> None:
    with pytest.raises(TTSError):
        normalizar_texto_tts("   \n ")


def test_a_mono_float32_estereo_y_recorte() -> None:
    estereo = np.stack([np.full(100, 2.0), np.full(100, 0.0)])  # (canales, muestras)
    mono = a_mono_float32(estereo)
    assert mono.shape == (100,) and mono.dtype == np.float32
    assert np.allclose(mono, 1.0)
    assert np.allclose(a_mono_float32(np.array([np.nan, -3.0])), [0.0, -1.0])


def test_leer_wav_pcm() -> None:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(FRECUENCIA)
        wav.writeframes(np.array([0, 16384, -32768], dtype=np.int16).tobytes())
    muestras, fr = leer_wav_pcm(buffer.getvalue())
    assert fr == FRECUENCIA
    assert np.allclose(muestras, [0.0, 0.5, -1.0])


def test_crear_backend_segun_configuracion() -> None:
    assert isinstance(crear_backend(VoiceConfig()), PiperBackend)
    assert isinstance(crear_backend(VoiceConfig(backend="kokoro")), KokoroBackend)


def test_piper_sin_voz_descargada_no_importa_piper() -> None:
    backend = PiperBackend(VoiceConfig(piper_voice="es_ES-inexistente-low"))
    with pytest.raises(FileNotFoundError, match="no está en"):
        backend.cargar()
    with pytest.raises(TTSError):
        backend.sintetizar("Hola.")


def test_piper_info_registra_parametros() -> None:
    cfg = VoiceConfig(length_scale=1.1)
    info = PiperBackend(cfg).info()
    assert info["voz"] == "es_MX-claude-high" and info["length_scale"] == 1.1


def test_narrador_por_defecto_usa_la_configuracion() -> None:
    assert isinstance(Narrador(VoiceConfig()).backend, PiperBackend)
