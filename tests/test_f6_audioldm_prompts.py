"""Complemento de 6.2: variantes de prompt y guidance para AudioLDM, con un backend falso."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

from storybook.config import SoundConfig
from storybook.schemas import Escena, StoryBible
from storybook.sound.generator import preparar_prompt_audio

RAIZ = Path(__file__).resolve().parents[1]
EJEMPLO = RAIZ / "src" / "storybook" / "datos" / "historia_ejemplo.json"


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "f6a", RAIZ / "scripts" / "f6_audioldm_prompts.py"
    )
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class AudioLDMFalso:
    """Clip audible solo si el prompt lleva el sufijo de calidad; si no, casi mudo."""

    nombre = "audioldm"

    def __init__(self) -> None:
        self.cfg = SoundConfig()
        self.guias: list[float] = []
        self.sufijos: set[str] = set()

    def generar(self, escena: Escena, duracion_s: float, seed: int) -> tuple[np.ndarray, int]:
        self.guias.append(self.cfg.audioldm_guidance)
        self.sufijos.add(self.cfg.audioldm_sufijo)
        sr = 16_000
        ruido = np.random.default_rng(seed).standard_normal(int(duracion_s * sr)) * 0.1
        audible = "high quality" in escena.prompt_sonido
        return (ruido if audible else ruido * 10 ** (-55 / 20)).astype(np.float32), sr


@pytest.fixture
def bible() -> StoryBible:
    return StoryBible.model_validate_json(EJEMPLO.read_text(encoding="utf-8"))


def test_sufijo_y_prompt_efectivo(bible: StoryBible) -> None:
    f6a = _modulo()
    escena = bible.escenas[0]
    assert f6a.con_sufijo(escena, "") is escena
    modificada = f6a.con_sufijo(escena, f6a.SUFIJO)
    assert modificada.prompt_sonido.endswith(", high quality, clear")
    assert preparar_prompt_audio(modificada.prompt_sonido).endswith("high quality, clear")


def test_ablacion_resumen_y_reporte(bible: StoryBible, tmp_path: Path) -> None:
    f6a = _modulo()
    backend = AudioLDMFalso()
    escenas = [("20261111_111458_historia_de_prueba", e) for e in bible.escenas[:2]]
    filas = f6a.ablacion(backend, escenas, 1.0, carpeta=tmp_path)
    assert len(filas) == 4 * 2 * 2  # variantes × escenas × seeds
    assert backend.cfg.audioldm_guidance == 2.5  # se restaura al terminar
    assert backend.cfg.audioldm_sufijo == ", high quality, clear"
    assert backend.sufijos == {""}  # la prueba apaga el sufijo de producción
    assert set(backend.guias) == {2.5, 4.0}
    resumen = {r["variante"]: r for r in f6a.resumir(filas)}
    assert resumen["base"]["escenas_que_pasan"] == 0 and resumen["guia_alta"]["clips_aptos"] == 0
    assert (
        resumen["sufijo"]["escenas_que_pasan"] == 2 and resumen["sufijo_guia"]["clips_aptos"] == 4
    )
    assert len(list((tmp_path / "sufijo").glob("*.wav"))) == 4
    texto = f6a.reporte_md(filas, "20261111_111458")
    assert "| `sufijo` | 2/2 | 4/4 |" in texto and "| `base` | 0/2 | 0/4 |" in texto
    assert "✗" in texto


def test_ultima_bateria_y_escenas(tmp_path: Path) -> None:
    f6a = _modulo()
    for bateria in ("20261101_090000", "20261111_111458"):
        carpeta = tmp_path / bateria / "c3_ipadapter" / "historia"
        carpeta.mkdir(parents=True)
        shutil.copy(EJEMPLO, carpeta / "story.json")
    (tmp_path / "sin_c3").mkdir()
    ultima = f6a.ultima_bateria(tmp_path)
    assert ultima.name == "20261111_111458"
    escenas = f6a.recolectar_escenas(ultima)
    assert [e.numero for _, e in escenas] == [1, 2, 3, 4, 5]
    with pytest.raises(FileNotFoundError):
        f6a.ultima_bateria(tmp_path / "sin_c3")
