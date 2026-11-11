"""Sonido y mezcla (tareas 4.1-4.3) con señales sintéticas y backends falsos (sin GPU)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from storybook.config import MixConfig, SoundConfig, load_config
from storybook.schemas import Escena, EtiquetaSonido, StoryBible
from storybook.sound.generator import (
    BibliotecaBackend,
    GeneradorSonido,
    ProceduralBackend,
    SoundError,
    a_mono,
    crear_backend,
    negativo_compatible,
    nombre_archivo_sonido,
    preparar_prompt_audio,
)
from storybook.sound.library import BibliotecaSonidos
from storybook.sound.mixer import (
    MixError,
    actividad_voz,
    ajustar_duracion,
    medir_lufs,
    mezclar,
    mezclar_historia,
)
from storybook.sound.procedural import FRECUENCIA, PICO_SALIDA, RECETAS, sintetizar


@pytest.fixture
def bible(bible_dict: dict[str, Any]) -> StoryBible:
    return StoryBible.model_validate(bible_dict)


# ---------------------------------------------------------------------------------------
# 4.1 · Síntesis procedural
# ---------------------------------------------------------------------------------------
def test_hay_receta_para_cada_etiqueta_del_esquema() -> None:
    assert set(RECETAS) == set(EtiquetaSonido)


@pytest.mark.parametrize("etiqueta", list(EtiquetaSonido))
def test_cada_receta_suena_sin_clipping_ni_nan(etiqueta: EtiquetaSonido) -> None:
    audio = sintetizar([etiqueta], 3.0, seed=7)
    assert audio.dtype == np.float32
    assert audio.size == 3 * FRECUENCIA
    assert np.all(np.isfinite(audio))
    assert float(np.max(np.abs(audio))) <= PICO_SALIDA + 1e-6
    assert float(np.sqrt(np.mean(audio**2))) > 1e-3  # no es silencio


def test_sintesis_reproducible_y_por_capas() -> None:
    a = sintetizar(["rain", "thunder"], 2.0, seed=3)
    b = sintetizar(["rain", "thunder"], 2.0, seed=3)
    c = sintetizar(["rain", "thunder"], 2.0, seed=4)
    assert np.array_equal(a, b) and not np.array_equal(a, c)
    assert sintetizar([], 1.0).size == FRECUENCIA  # sin etiquetas: viento
    assert sintetizar(["wind"], 1.0, frecuencia=16_000).size == 16_000
    with pytest.raises(ValueError):
        sintetizar(["no_existe"], 1.0)
    with pytest.raises(ValueError):
        sintetizar(["wind"], 0)


# ---------------------------------------------------------------------------------------
# 4.2 · Biblioteca CC0
# ---------------------------------------------------------------------------------------
def _clip(ruta: Path, segundos: float = 1.0, sr: int = 22_050) -> None:
    t = np.arange(int(segundos * sr)) / sr
    sf.write(str(ruta), 0.3 * np.sin(2 * np.pi * 330 * t), sr)


def test_biblioteca_solo_cc0_y_por_prioridad(tmp_path: Path) -> None:
    for nombre in ("lluvia.wav", "lluvia2.wav", "mar.wav", "cc_by.wav"):
        _clip(tmp_path / nombre)
    indice = {
        "clips": [
            {"archivo": "lluvia.wav", "etiquetas": ["rain"], "licencia": "CC0"},
            {"archivo": "lluvia2.wav", "etiquetas": ["rain", "wind"], "licencia": "cc0-1.0"},
            {"archivo": "mar.wav", "etiquetas": ["ocean_waves"], "licencia": "CC0"},
            {"archivo": "cc_by.wav", "etiquetas": ["fire"], "licencia": "CC-BY-4.0"},
            {"archivo": "falta.wav", "etiquetas": ["fire"], "licencia": "CC0"},
            {"etiquetas": ["roto"]},
        ]
    }
    (tmp_path / "index.json").write_text(json.dumps(indice), encoding="utf-8")
    biblioteca = BibliotecaSonidos(tmp_path)
    assert [c.ruta.name for c in biblioteca.clips] == ["lluvia.wav", "lluvia2.wav", "mar.wav"]
    assert biblioteca.buscar(["fire"]) is None  # el CC-BY y el faltante se ignoran
    assert biblioteca.buscar(["ocean_waves", "rain"]).ruta.name == "mar.wav"  # type: ignore[union-attr]
    assert biblioteca.buscar(["rain"], seed=1).ruta.name == "lluvia2.wav"  # type: ignore[union-attr]


def test_biblioteca_sin_indice_esta_vacia(tmp_path: Path) -> None:
    assert BibliotecaSonidos(tmp_path).clips == []
    (tmp_path / "index.json").write_text("{no es json", encoding="utf-8")
    assert BibliotecaSonidos(tmp_path).clips == []
    with pytest.raises(SoundError, match="biblioteca vacía"):
        BibliotecaBackend(tmp_path).cargar()


# ---------------------------------------------------------------------------------------
# 4.2 · Cadena de fallback
# ---------------------------------------------------------------------------------------
class FakeSonido:
    def __init__(
        self,
        nombre: str,
        *,
        fallar_carga: bool = False,
        fallar_en: set[int] | None = None,
        oom_en: int | None = None,
        silencio: bool = False,
    ) -> None:
        self.nombre = nombre
        self.fallar_carga = fallar_carga
        self.fallar_en = fallar_en or set()
        self.oom_en = oom_en
        self.silencio = silencio
        self.cargas = 0
        self.liberado = 0
        self.generadas: list[int] = []

    def cargar(self) -> None:
        if self.fallar_carga:
            raise FileNotFoundError(f"'{self.nombre}' no está descargado")
        self.cargas += 1

    def generar(self, escena: Escena, duracion_s: float, seed: int) -> tuple[np.ndarray, int]:
        if escena.numero == self.oom_en:
            raise MemoryError("CUDA out of memory")
        if escena.numero in self.fallar_en:
            raise RuntimeError("fallo del modelo")
        self.generadas.append(escena.numero)
        sr = 16_000
        if self.silencio:
            return np.zeros(int(duracion_s * sr), dtype=np.float32), sr
        audio = np.random.default_rng(seed).standard_normal((2, int(duracion_s * sr))) * 0.1
        return audio.astype(np.float32), sr  # estéreo (canales, muestras) como diffusers

    def liberar(self) -> None:
        self.liberado += 1

    def es_oom(self, exc: BaseException) -> bool:
        return isinstance(exc, MemoryError)

    def info(self) -> dict[str, Any]:
        return {"backend": self.nombre}


def _generador(backends: dict[str, FakeSonido], orden: list[str]) -> GeneradorSonido:
    cfg = SoundConfig(backends=orden, duration_s=2.0)  # type: ignore[arg-type]
    return GeneradorSonido(cfg, seed_base=10, fabrica=lambda nombre: backends[nombre])


def test_primer_backend_que_funciona_hace_todas_las_escenas(
    bible: StoryBible, tmp_path: Path
) -> None:
    falsos = {"sa3": FakeSonido("sa3", fallar_carga=True), "audioldm": FakeSonido("audioldm")}
    etapa = _generador(falsos, ["sa3", "audioldm"]).generar(bible, tmp_path)
    assert [s.backend for s in etapa.sonidos] == ["audioldm"] * 5
    assert falsos["audioldm"].cargas == 1 and falsos["audioldm"].liberado == 1
    assert etapa.fallbacks == ["sonido:sa3:no_disponible"]
    assert etapa.backends["sa3"]["estado"] == "no_disponible"
    for s in etapa.sonidos:
        datos, sr = sf.read(tmp_path / nombre_archivo_sonido(s.escena))
        assert sr == 16_000 and datos.ndim == 1  # se guardó en mono
        assert s.duracion_s == 2.0 and s.prompt and s.etiquetas


def test_escena_que_falla_pasa_al_siguiente_backend(bible: StoryBible, tmp_path: Path) -> None:
    falsos = {
        "audioldm": FakeSonido("audioldm", fallar_en={2}),
        "library": FakeSonido("library", silencio=True),  # el silencio también es fallo
        "procedural": ProceduralBackend(),  # type: ignore[dict-item]
    }
    etapa = _generador(falsos, ["audioldm", "library", "procedural"]).generar(bible, tmp_path)
    usados = {s.escena: s.backend for s in etapa.sonidos}
    assert usados == {1: "audioldm", 2: "procedural", 3: "audioldm", 4: "audioldm", 5: "audioldm"}
    assert "sonido:escena_2:audioldm_fallo" in etapa.fallbacks
    assert "sonido:escena_2:library_fallo" in etapa.fallbacks
    assert any("silencio" in e for e in etapa.errores)


def test_oom_abandona_el_backend_y_procedural_es_la_ultima_red(
    bible: StoryBible, tmp_path: Path
) -> None:
    falsos = {"sao": FakeSonido("sao", oom_en=3), "procedural": ProceduralBackend()}  # type: ignore[dict-item]
    # Aunque la configuración no liste "procedural", siempre se agrega al final.
    etapa = _generador(falsos, ["sao"]).generar(bible, tmp_path)  # type: ignore[arg-type]
    usados = {s.escena: s.backend for s in etapa.sonidos}
    assert usados == {1: "sao", 2: "sao", 3: "procedural", 4: "procedural", 5: "procedural"}
    assert falsos["sao"].generadas == [1, 2]


def test_regenerar_una_escena(bible: StoryBible, tmp_path: Path) -> None:
    falsos = {"procedural": ProceduralBackend()}
    etapa = _generador(falsos, ["procedural"]).generar(bible, tmp_path, numeros=[4])  # type: ignore[arg-type]
    assert [s.escena for s in etapa.sonidos] == [4]
    assert etapa.por_escena(4).backend == "procedural"
    assert etapa.a_dict()["sonidos"][0]["archivo"] == "sfx_4.wav"


def test_sin_gpu_ni_modelos_la_configuracion_real_cae_a_procedural(
    bible: StoryBible, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con la cadena real de rápido: sin pesos descargados ni biblioteca, procedural."""
    monkeypatch.setattr("storybook.config.HF_HOME_DIR", tmp_path / "hf")
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf" / "hub"))
    cfg = load_config("rapido").sound.model_copy(update={"duration_s": 2.0})
    fabrica = lambda nombre: crear_backend(nombre, cfg, raiz_biblioteca=tmp_path / "sfx")  # noqa: E731
    etapa = GeneradorSonido(cfg, fabrica=fabrica).generar(bible, tmp_path / "out")
    assert {s.backend for s in etapa.sonidos} == {"procedural"}
    assert etapa.fallbacks[: len(cfg.backends) - 1] == [
        f"sonido:{b}:no_disponible" for b in cfg.backends if b != "procedural"
    ]


def test_a_mono_acepta_las_formas_de_diffusers() -> None:
    estereo_cm = np.ones((2, 100), dtype=np.float32)
    estereo_mc = np.ones((100, 2), dtype=np.float32)
    assert a_mono(estereo_cm).shape == (100,) and a_mono(estereo_mc).shape == (100,)
    assert a_mono(np.array([np.nan, 1.0])).tolist() == [0.0, 1.0]


# ---------------------------------------------------------------------------------------
# 4.3 · Mezcla
# ---------------------------------------------------------------------------------------
def _voz_sintetica(sr: int = 22_050) -> np.ndarray:
    """1,5 s de "habla" (tono con vibrato), 1 s de pausa y 1,5 s de habla."""
    t = np.arange(int(1.5 * sr)) / sr
    habla = 0.4 * np.sin(2 * np.pi * (220 + 20 * np.sin(2 * np.pi * 5 * t)) * t)
    return np.concatenate([habla, np.zeros(sr), habla]).astype(np.float32)


def _ambiente_sintetico(segundos: float = 2.0, sr: int = 16_000) -> np.ndarray:
    return (np.random.default_rng(0).standard_normal(int(segundos * sr)) * 0.2).astype(np.float32)


def test_loop_con_crossfade_sin_saltos() -> None:
    sr = 16_000
    t = np.arange(sr) / sr
    tono = np.sin(2 * np.pi * 200 * t)  # 1 s: el loop debe empalmar sin clic
    largo = ajustar_duracion(tono, 5 * sr + 123, crossfade=int(0.25 * sr))
    assert largo.size == 5 * sr + 123
    salto_max_original = float(np.max(np.abs(np.diff(tono))))
    assert float(np.max(np.abs(np.diff(largo)))) <= salto_max_original * 1.5
    assert ajustar_duracion(tono, 100, 10).size == 100
    with pytest.raises(MixError):
        ajustar_duracion(np.array([]), 10, 2)


def test_mezcla_niveles_ducking_y_duracion() -> None:
    cfg = MixConfig()
    escena = mezclar(_voz_sintetica(), 22_050, _ambiente_sintetico(), 16_000, cfg)
    m = escena.metricas
    sr = cfg.sample_rate
    assert escena.sample_rate == 44_100
    assert m["duracion_s"] == pytest.approx(4.0 + cfg.pre_roll_s + cfg.post_roll_s, abs=0.01)
    assert escena.mezcla.size == escena.ambiente.size
    assert m["lufs_voz"] == pytest.approx(cfg.voz_lufs, abs=0.5)
    assert 12.0 - 0.5 <= m["ambiente_bajo_voz_db"] <= 18.0 + 0.5
    assert m["ambiente_bajo_voz_hablando_db"] <= 18.0 + 0.5
    assert float(np.max(np.abs(escena.mezcla))) <= 0.98 + 1e-6
    assert np.all(np.isfinite(escena.mezcla))

    # Ducking: el ambiente dentro de la mezcla baja mientras se habla.
    pre = int(cfg.pre_roll_s * sr)
    hablando = slice(pre + int(0.5 * sr), pre + int(1.2 * sr))
    en_pausa = slice(pre + int(1.9 * sr), pre + int(2.4 * sr))
    ambiente_en_mezcla = escena.mezcla - _voz_normalizada(cfg)
    rms = lambda x: float(np.sqrt(np.mean(np.square(x))))  # noqa: E731
    caida_db = 20 * math.log10(
        rms(ambiente_en_mezcla[en_pausa]) / rms(ambiente_en_mezcla[hablando])
    )
    assert caida_db == pytest.approx(cfg.ducking_db, abs=1.5)


def _voz_normalizada(cfg: MixConfig) -> np.ndarray:
    """La voz tal como entra a la mezcla (remuestreada, con márgenes y a ``voz_lufs``)."""
    from storybook.sound.mixer import ajustar_lufs, remuestrear

    sr = cfg.sample_rate
    voz = remuestrear(_voz_sintetica(), 22_050, sr)
    voz = np.concatenate(
        [np.zeros(int(cfg.pre_roll_s * sr)), voz, np.zeros(int(cfg.post_roll_s * sr))]
    )
    return ajustar_lufs(voz, sr, cfg.voz_lufs)[0]


def test_actividad_de_voz() -> None:
    sr = 22_050
    actividad = actividad_voz(_voz_sintetica(sr), sr)
    assert actividad.size == _voz_sintetica(sr).size
    assert actividad[int(1.0 * sr)] > 0.9  # hablando
    assert actividad[int(2.4 * sr)] < 0.2  # al final de la pausa
    assert actividad.min() >= 0.0 and actividad.max() <= 1.0


def test_medir_lufs_casos_borde() -> None:
    assert medir_lufs(np.zeros(44_100), 44_100) == float("-inf")
    corto = 0.1 * np.ones(1000)
    assert math.isfinite(medir_lufs(corto, 44_100))


def test_configuracion_de_mezcla_respeta_12_a_18_db() -> None:
    with pytest.raises(ValueError):
        MixConfig(ambiente_bajo_voz_db=15.0, ducking_db=6.0)
    with pytest.raises(ValueError):
        MixConfig(ambiente_bajo_voz_db=10.0)
    assert load_config("rapido").mix.ambiente_bajo_voz_db == 12.0


def test_mezclar_historia_escribe_ambience_y_mix(tmp_path: Path) -> None:
    narraciones, sonidos = {}, {}
    for n in (1, 2):
        voz, amb = tmp_path / f"voice_{n}.wav", tmp_path / f"sfx_{n}.wav"
        sf.write(str(voz), _voz_sintetica(), 22_050, subtype="PCM_16")
        sf.write(str(amb), _ambiente_sintetico(), 16_000, subtype="PCM_16")
        narraciones[n], sonidos[n] = voz, (amb, "procedural")
    etapa = mezclar_historia(narraciones, sonidos, tmp_path / "out", MixConfig())
    assert [m.escena for m in etapa.mezclas] == [1, 2]
    for m in etapa.mezclas:
        for ruta in (m.ambiente, m.mezcla):
            info = sf.info(str(ruta))
            assert info.samplerate == 44_100 and info.subtype == "PCM_16"
        assert m.a_dict()["fuente_sonido"] == "procedural"
    with pytest.raises(MixError, match="sin ambiente"):
        mezclar_historia({3: narraciones[1]}, sonidos, tmp_path / "out", MixConfig())


# ---------------------------------------------------------------------------------------
# 4.4 · Clips generativos con huecos (AudioLDM concentra a veces el sonido al principio)
# ---------------------------------------------------------------------------------------
class ConHuecos(FakeSonido):
    """Con la seed base da un clip que se apaga tras 1 s; con otra seed, uno continuo."""

    def __init__(self, nombre: str, *, siempre: bool = False) -> None:
        super().__init__(nombre)
        self.siempre = siempre
        self.seeds: list[int] = []

    def generar(self, escena: Escena, duracion_s: float, seed: int) -> tuple[np.ndarray, int]:
        self.seeds.append(seed)
        sr = 16_000
        audio = np.random.default_rng(seed).standard_normal(int(duracion_s * sr)) * 0.2
        if self.siempre or len(self.seeds) % 2 == 1:
            audio[sr:] *= 0.001  # -60 dB después del primer segundo
        return audio.astype(np.float32), sr


def test_fraccion_en_silencio() -> None:
    from storybook.sound.generator import fraccion_en_silencio

    sr = 16_000
    continuo = np.random.default_rng(0).standard_normal(4 * sr)
    con_hueco = continuo.copy()
    con_hueco[sr:] *= 0.001
    assert fraccion_en_silencio(continuo, sr) < 0.05
    assert fraccion_en_silencio(con_hueco, sr) > 0.7
    assert fraccion_en_silencio(np.zeros(10), sr) == 1.0


def test_clip_con_huecos_se_reintenta_con_otra_seed(bible: StoryBible, tmp_path: Path) -> None:
    falso = ConHuecos("audioldm")
    etapa = _generador({"audioldm": falso}, ["audioldm"]).generar(bible, tmp_path, numeros=[1])
    (sonido,) = etapa.sonidos
    assert sonido.backend == "audioldm"
    assert falso.seeds == [11, 1011]  # seed_base 10 + escena 1, y el reintento
    assert sonido.detalle["intentos"] == 2 and sonido.detalle["seed"] == 1011


def test_clip_siempre_con_huecos_pasa_a_procedural(bible: StoryBible, tmp_path: Path) -> None:
    falsos = {"audioldm": ConHuecos("audioldm", siempre=True), "procedural": ProceduralBackend()}
    etapa = _generador(falsos, ["audioldm", "procedural"]).generar(bible, tmp_path, numeros=[2])  # type: ignore[arg-type]
    assert etapa.por_escena(2).backend == "procedural"
    assert any("casi en silencio" in e for e in etapa.errores)


def test_clip_generativo_demasiado_bajo_se_rechaza(bible: StoryBible, tmp_path: Path) -> None:
    """AudioLDM dio clips a -72 dBFS en la tarea 5.4: el ambiente no se oía."""

    class Mudo(FakeSonido):
        def generar(self, escena: Escena, duracion_s: float, seed: int) -> tuple[np.ndarray, int]:
            audio = np.random.default_rng(seed).standard_normal(int(duracion_s * 16_000))
            return (audio * 10 ** (-72 / 20)).astype(np.float32), 16_000

    falsos = {"audioldm": Mudo("audioldm"), "procedural": ProceduralBackend()}
    etapa = _generador(falsos, ["audioldm", "procedural"]).generar(bible, tmp_path, numeros=[1])  # type: ignore[arg-type]
    assert etapa.por_escena(1).backend == "procedural"
    assert any("demasiado bajo" in e for e in etapa.errores)


def test_medir_lufs_bajo_la_compuerta_absoluta() -> None:
    muy_bajo = np.random.default_rng(0).standard_normal(44_100 * 3) * 10 ** (-80 / 20)
    valor = medir_lufs(muy_bajo, 44_100)
    assert math.isfinite(valor) and valor < -70


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        (
            "Soft wind blows through trees, birds sing gently.",
            "Wind blows through trees, birds sing.",
        ),
        (
            "Faint water stream in forest, slow heartbeat beneath silence",
            "Water stream in forest, slow heartbeat",
        ),
        (
            "Wind whispers through old stones. A slow heartbeat pulses under the silence. "
            "Distant forest sounds fade into stillness.",
            "Wind whispers through old stones. A slow heartbeat pulses. "
            "Distant forest sounds fade.",
        ),
        ("Ocean waves crash against rocks.", "Ocean waves crash against rocks."),
        ("Silence.", "Silence."),  # si no queda nada útil, se deja el original
    ],
)
def test_preparar_prompt_audio_quita_intensidad_baja(entrada: str, esperado: str) -> None:
    """En 5.4 los prompts con "soft"/"gently"/"faint" dieron clips casi mudos en AudioLDM."""
    assert preparar_prompt_audio(entrada) == esperado


def test_negativo_compatible_no_contradice_al_prompt() -> None:
    negativo = "low quality, speech, voice, singing, music"
    assert negativo_compatible(negativo, "Birds sing in the trees.") == (
        "low quality, speech, voice, music"
    )
    assert negativo_compatible(negativo, "A music box plays, children's voices echo.") == (
        "low quality, speech, singing"
    )
    assert negativo_compatible(negativo, "Ocean waves crash.") == negativo
