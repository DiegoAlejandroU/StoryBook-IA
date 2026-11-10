"""Script de las tareas 2.3 y 3.3 con backends falsos (sin GPU, pesos, CLIP ni Whisper)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from storybook import config
from storybook.schemas import StoryBible
from tests.test_image_generator import FakeBackend
from tests.test_tts import FakeTTS

RAIZ = Path(__file__).resolve().parents[1]
MODELO_4B = "qwen3:4b-instruct-2507-q4_K_M"


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("f2_f3", RAIZ / "scripts" / "f2_f3_prueba.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _corrida(raiz: Path, nombre: str, modelo: str, historias: dict[str, str]) -> Path:
    carpeta = raiz / nombre
    carpeta.mkdir(parents=True)
    (carpeta / "resumen.md").write_text(
        f"- Perfil `rapido` · modelo `{modelo}`\n", encoding="utf-8"
    )
    for archivo, contenido in historias.items():
        (carpeta / archivo).write_text(contenido, encoding="utf-8")
    return carpeta


def test_elige_la_primera_valida_de_la_ultima_corrida_del_modelo(
    tmp_path: Path, bible_dict: dict[str, Any]
) -> None:
    f2 = _modulo()
    valida = json.dumps(bible_dict, ensure_ascii=False)
    _corrida(tmp_path, "20261110_080000", MODELO_4B, {"story_01.json": valida})
    reciente = _corrida(
        tmp_path, "20261110_090000", MODELO_4B, {"story_01.json": "{}", "story_02.json": valida}
    )
    _corrida(tmp_path, "20261110_100000", "qwen3:8b", {"story_01.json": valida})  # experimento
    assert f2.elegir_story(tmp_path, MODELO_4B) == reciente / "story_02.json"
    with pytest.raises(FileNotFoundError, match=r"setup_windows\.ps1 -Paso f1"):
        f2.elegir_story(tmp_path, "otro-modelo")


def test_ejecuta_imagen_y_voces_con_backends_falsos(
    tmp_path: Path, bible_dict: dict[str, Any]
) -> None:
    f2 = _modulo()
    cfg = config.load_config("rapido")
    bible = StoryBible.model_validate(bible_dict)

    def fabrica_voz(cfg_voz: config.VoiceConfig) -> FakeTTS:
        # La segunda voz "no está descargada": no debe detener a las demás.
        return FakeTTS(fallar_carga=cfg_voz.piper_voice == "es_ES-falta-medium")

    resultado = f2.ejecutar(
        cfg,
        bible,
        tmp_path,
        voces=["es_MX-claude-high", "es_ES-falta-medium"],
        evaluar=False,
        backend_imagen=FakeBackend(),
        fabrica_voz=fabrica_voz,
    )
    assert resultado["errores"] == {}
    imagen = resultado["imagen"]
    assert len(imagen["escenas"]) == 5 and imagen["respaldos"] == []
    assert imagen["ip_adapter"] is True
    assert (tmp_path / "scene_5.png").is_file() and (tmp_path / "character_sheet.png").is_file()
    voz = resultado["voz"]
    assert len(voz["es_MX-claude-high"]["narraciones"]) == 5
    assert (tmp_path / "voz" / "es_MX-claude-high" / "voice_1.wav").is_file()
    assert "error" in voz["es_ES-falta-medium"]

    texto = f2.resumen_md(resultado, "rapido", tmp_path / "story_01.json", bible)
    assert "## Imágenes (tarea 2.3)" in texto and "## Voz (tarea 3.3)" in texto
    assert "| es_MX-claude-high |" in texto and "| es_ES-falta-medium | - |" in texto


def test_un_paso_que_falla_no_detiene_los_demas(tmp_path: Path, bible_dict: dict[str, Any]) -> None:
    f2 = _modulo()
    bible = StoryBible.model_validate(bible_dict)
    resultado = f2.ejecutar(
        config.load_config("rapido"),
        bible,
        tmp_path,
        voces=["es_MX-claude-high"],
        evaluar=False,
        backend_imagen=FakeBackend(fallar_carga=True),
        fabrica_voz=lambda _cfg: FakeTTS(),
    )
    assert "imagen" in resultado["errores"]
    assert len(resultado["voz"]["es_MX-claude-high"]["narraciones"]) == 5
    texto = f2.resumen_md(resultado, "rapido", tmp_path / "s.json", bible)
    assert "## Errores" in texto


def test_sufijo_de_evidencias() -> None:
    f2 = _modulo()
    assert f2.sufijo_evidencias("rapido") == ""
    assert f2.sufijo_evidencias("calidad") == "_calidad"


def test_aplicar_variante() -> None:
    f2 = _modulo()
    base = config.load_config("rapido").image
    v = f2.aplicar_variante(base, "ip=0.3+orden=accion_primero+pasos=8+cfg=2")
    assert v.ip_adapter.scale == 0.3 and v.ip_adapter.enabled
    assert v.prompt_orden == "accion_primero" and v.steps == 8 and v.guidance_scale == 2.0
    assert base.ip_adapter.scale == 0.4  # la configuración original (ajustada en 2.3) no cambia
    assert f2.aplicar_variante(base, "ip=0").ip_adapter.enabled is False
    with pytest.raises(ValueError, match="Variante desconocida"):
        f2.aplicar_variante(base, "resolucion=1024")
    with pytest.raises(ValueError):
        f2.aplicar_variante(base, "orden=al_azar")


def test_variantes_en_carpetas_separadas(tmp_path: Path, bible_dict: dict[str, Any]) -> None:
    f2 = _modulo()
    bible = StoryBible.model_validate(bible_dict)
    filas = f2.ejecutar_variantes(
        config.load_config("rapido"),
        bible,
        tmp_path,
        ["ip=0.6", "ip=0.3+orden=accion_primero", "nada=1"],
        evaluar=False,
        backend_imagen=FakeBackend(),
    )
    assert [f["carpeta"] for f in filas] == ["v1", "v2", "v3"]
    assert (tmp_path / "v2" / "scene_5.png").is_file()
    assert filas[1]["imagen"]["parametros"]["prompt_orden"] == "accion_primero"
    assert filas[1]["imagen"]["parametros"]["ip_adapter_scale"] == 0.3
    assert "error" in filas[2]
    texto = f2.resumen_variantes_md(filas, "rapido", tmp_path / "s.json", bible)
    assert "| 2 | `ip=0.3+orden=accion_primero` |" in texto
