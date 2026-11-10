"""Script de la tarea 4.4 con voz y sonido falsos (sin GPU ni modelos)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import soundfile as sf

from storybook import config
from storybook.schemas import StoryBible
from storybook.sound.generator import ProceduralBackend
from tests.test_sound import FakeSonido
from tests.test_tts import FakeTTS

RAIZ = Path(__file__).resolve().parents[1]


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("f4", RAIZ / "scripts" / "f4_sonido.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_cadena_y_variante_con_mezcla(tmp_path: Path, bible_dict: dict[str, Any]) -> None:
    f4 = _modulo()
    bible = StoryBible.model_validate(bible_dict)
    cfg = config.load_config("rapido")
    cfg = cfg.model_copy(update={"sound": cfg.sound.model_copy(update={"duration_s": 2.0})})
    falsos: dict[str, Any] = {
        "sa3": FakeSonido("sa3", fallar_carga=True),
        "audioldm": FakeSonido("audioldm", fallar_en={3}),
        "library": FakeSonido("library", fallar_carga=True),
        "procedural": ProceduralBackend(),
    }
    resultado = f4.ejecutar(
        cfg,
        bible,
        tmp_path,
        ["cadena", "procedural"],
        backend_voz=FakeTTS(),
        fabrica_sonido=lambda nombre: falsos[nombre],
    )
    assert resultado["errores"] == {}
    cadena, procedural = resultado["variantes"]
    assert cadena["backend_por_escena"][1] == "audioldm"
    assert cadena["backend_por_escena"][3] == "procedural"  # la escena que falló
    assert "sonido:sa3:no_disponible" in cadena["fallbacks"]
    assert set(procedural["backend_por_escena"].values()) == {"procedural"}
    for n in range(1, 6):
        assert sf.info(str(tmp_path / "cadena" / f"mix_{n}.wav")).samplerate == 44_100
        assert (tmp_path / "procedural" / f"ambience_{n}.wav").is_file()
    texto = f4.resumen_md(resultado, "rapido", tmp_path / "s.json", bible)
    assert "| `cadena` | audioldm · audioldm · procedural · audioldm · audioldm |" in texto


def test_sin_voz_no_hay_mezcla(tmp_path: Path, bible_dict: dict[str, Any]) -> None:
    f4 = _modulo()
    bible = StoryBible.model_validate(bible_dict)
    resultado = f4.ejecutar(
        config.load_config("rapido"),
        bible,
        tmp_path,
        ["procedural"],
        backend_voz=FakeTTS(fallar_carga=True),
    )
    assert "voz" in resultado["errores"] and resultado["variantes"] == []
