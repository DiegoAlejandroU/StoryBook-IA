"""Exportación de ejemplos (5.4): ambientes débiles se rehacen; audios en OGG por bloques."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import numpy as np
import soundfile as sf

from storybook import config
from storybook.mock import dependencias_simuladas
from storybook.pipeline import Pipeline

RAIZ = Path(__file__).resolve().parents[1]


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exp", RAIZ / "scripts" / "exportar_muestras.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _pipeline(raiz: Path) -> Pipeline:
    cfg = config.load_config("rapido")
    cfg = cfg.model_copy(update={"sound": cfg.sound.model_copy(update={"duration_s": 2.0})})
    return Pipeline(cfg, dependencias_simuladas(), raiz)


def _marcar_como_real(carpeta: Path, escena_debil: int) -> None:
    """Simula una historia real con un ambiente de AudioLDM casi mudo en una escena."""
    ruta = carpeta / "manifest.json"
    manifest = json.loads(ruta.read_text(encoding="utf-8"))
    manifest["etapas"]["texto"]["modelo"] = "qwen3:4b-instruct-2507-q4_K_M"
    for sonido in manifest["etapas"]["sonido"]["sonidos"]:
        sonido["backend"] = "audioldm"
    ruta.write_text(json.dumps(manifest), encoding="utf-8")
    sr = 16_000
    ruido = np.random.default_rng(0).standard_normal(2 * sr) * 0.2
    for n in range(1, 6):
        audio = ruido * (10 ** (-60 / 20) / 0.2) if n == escena_debil else ruido
        sf.write(str(carpeta / f"sfx_{n}.wav"), audio, sr)


def test_rehace_el_ambiente_debil_y_exporta(tmp_path: Path) -> None:
    exp = _modulo()
    pipeline = _pipeline(tmp_path / "outputs")
    historia = pipeline.generar("Un faro abandonado que se enciende solo cada noche", "misterio")
    simulada = pipeline.generar("El último dragón vive escondido en una biblioteca", "fantasia")
    _marcar_como_real(historia.carpeta, escena_debil=3)

    assert exp.historias_reales_recientes(tmp_path / "outputs", 3) == [historia.carpeta]
    assert simulada.carpeta not in exp.historias_reales_recientes(tmp_path / "outputs", 3)
    assert exp.escenas_con_ambiente_debil(historia.carpeta) == [3]

    lineas, errores = exp.procesar(
        [historia.carpeta, tmp_path / "no_existe"], pipeline, tmp_path / "samples"
    )
    assert "ambiente rehecho en escenas [3]" in lineas[0]
    assert len(errores) == 1 and "no_existe" in errores[0]  # una historia rota no frena las demás
    assert exp.escenas_con_ambiente_debil(historia.carpeta) == []  # ahora es procedural
    manifest = json.loads((historia.carpeta / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["regeneraciones"][-1]["tipo"] == "sonido"
    sonido_3 = next(s for s in manifest["etapas"]["sonido"]["sonidos"] if s["escena"] == 3)
    assert sonido_3["backend"] == "procedural"
    destino = tmp_path / "samples" / historia.carpeta.name
    assert sf.info(str(destino / "mix_3.ogg")).format == "OGG"


def test_ogg_por_bloques_conserva_la_duracion(tmp_path: Path) -> None:
    from storybook.storage import _wav_a_ogg

    sr = 44_100
    audio = np.random.default_rng(1).standard_normal(sr * 50).astype(np.float32) * 0.1
    sf.write(str(tmp_path / "x.wav"), audio, sr)
    _wav_a_ogg(tmp_path / "x.wav", tmp_path / "x.ogg")
    info = sf.info(str(tmp_path / "x.ogg"))
    assert info.samplerate == sr and abs(info.frames - audio.size) < sr // 10
