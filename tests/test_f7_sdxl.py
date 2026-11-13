"""Prueba de SDXL frente a SD 1.5 (12 nov) con backends falsos: sin GPU, pesos ni CLIP."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from storybook import config
from storybook.image.generator import restaurar_almacenamiento_fp8
from storybook.mock import dependencias_simuladas
from storybook.pipeline import Pipeline
from tests.test_image_generator import FakeBackend

RAIZ = Path(__file__).resolve().parents[1]


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("f7", RAIZ / "scripts" / "f7_sdxl_prueba.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class FakeScorer:
    def imagen_imagen(self, rutas: list[Path]) -> dict[str, float]:
        return {"media": 0.8123, "minimo": 0.7011, "pares": len(rutas) * (len(rutas) - 1) // 2}

    def imagen_texto(self, imagen: Path, texto: str) -> float:
        assert texto  # siempre hay un prompt contra el cual medir
        return 0.31


def _historia_real(raiz: Path) -> Path:
    pipeline = Pipeline(config.load_config("rapido"), dependencias_simuladas(), raiz)
    historia = pipeline.generar("Un faro abandonado que se enciende solo cada noche", "misterio")
    ruta = historia.carpeta / "manifest.json"
    manifest = json.loads(ruta.read_text(encoding="utf-8"))
    manifest["etapas"]["texto"]["modelo"] = "qwen3:4b-instruct-2507-q4_K_M"
    ruta.write_text(json.dumps(manifest), encoding="utf-8")
    return historia.carpeta


@pytest.fixture
def f7(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    modulo = _modulo()
    monkeypatch.setattr(modulo, "SALIDA", tmp_path / "f7")
    monkeypatch.setattr(modulo, "EVIDENCIAS", tmp_path / "evidencias")
    monkeypatch.setattr(modulo, "_scorer", FakeScorer)
    monkeypatch.setattr(modulo, "liberar_ollama", list)
    return modulo


def test_el_perfil_sdxl_es_valido() -> None:
    img = config.load_config("sdxl").image
    assert img.arquitectura == "sdxl" and img.model_id == "Lykon/dreamshaper-xl-lightning"
    assert img.unet_fp8 and img.cpu_offload and img.scheduler == "dpmpp"
    assert (img.width, img.height, img.sheet_size) == (1152, 768, 832)
    assert img.ip_adapter.subfolder == "sdxl_models"
    assert img.personajes_prompt == "foco"
    # El perfil por defecto sigue siendo SD 1.5.
    assert config.load_config("rapido").image.arquitectura == "sd15"


def test_elige_la_historia_real_mas_reciente(tmp_path: Path, f7: ModuleType) -> None:
    with pytest.raises(FileNotFoundError):
        f7.historia_reciente(tmp_path / "outputs")
    real = _historia_real(tmp_path / "outputs")
    Pipeline(config.load_config("rapido"), dependencias_simuladas(), tmp_path / "outputs").generar(
        "El último dragón vive escondido en una biblioteca", "fantasia"
    )
    assert f7.historia_reciente(tmp_path / "outputs") == real


def test_compara_perfiles_y_escribe_evidencias(tmp_path: Path, f7: ModuleType) -> None:
    historia = _historia_real(tmp_path / "outputs")
    codigo = f7.main(
        ["--historia", str(historia), "--perfiles", "rapido", "sdxl"], fabrica_backend=FakeBackend
    )
    assert codigo == 0
    datos = json.loads((tmp_path / "evidencias" / "f7_sdxl.json").read_text(encoding="utf-8"))
    perfiles = [r["perfil"] for r in datos["resultados"]]
    assert perfiles == ["original", "rapido", "sdxl"]
    rapido, sdxl = datos["resultados"][1:]
    assert len(sdxl["escenas"]) == 5 and sdxl["respaldos"] == 0
    assert sdxl["clip_img_img_media"] == 0.8123 and sdxl["clip_img_txt_media"] == 0.31
    assert all(e["foco"] for e in rapido["escenas"])  # modo foco: un personaje por escena
    hojas = sorted(
        p.name.split("_", 2)[-1] for p in (tmp_path / "evidencias" / "f7_hojas").iterdir()
    )
    assert hojas == ["original.jpg", "rapido.jpg", "sdxl.jpg"]
    # Las imágenes de SDXL salen a 1152 × 768 y las de SD 1.5 a 768 × 512.
    corrida = next((tmp_path / "f7").iterdir())
    from PIL import Image

    with Image.open(corrida / "sdxl" / "scene_1.png") as img:
        assert img.size == (1152, 768)
    with Image.open(corrida / "rapido" / "scene_1.png") as img:
        assert img.size == (768, 512)
    md = (tmp_path / "evidencias" / "f7_sdxl.md").read_text(encoding="utf-8")
    assert "| `sdxl` |" in md and "personaje foco" in md


def test_un_perfil_que_falla_no_detiene_la_prueba(tmp_path: Path, f7: ModuleType) -> None:
    historia = _historia_real(tmp_path / "outputs")
    backends = iter([FakeBackend(fallar_carga=True), FakeBackend()])
    codigo = f7.main(
        ["--historia", str(historia), "--perfiles", "sdxl", "rapido"],
        fabrica_backend=lambda: next(backends),
    )
    assert codigo == 2
    datos = json.loads((tmp_path / "evidencias" / "f7_sdxl.json").read_text(encoding="utf-8"))
    sdxl, rapido = datos["resultados"][1:]
    assert "error" in sdxl and "ImageModelError" in sdxl["error"]
    assert "error" not in rapido and len(rapido["escenas"]) == 5
    assert "**falló**" in (tmp_path / "evidencias" / "f7_sdxl.md").read_text(encoding="utf-8")


class _Registro:
    def __init__(self, gancho: Any) -> None:
        self._gancho = gancho

    def get_hook(self, nombre: str) -> Any:
        return self._gancho if nombre == "layerwise_casting" else None


class _Modulo:
    def __init__(self, con_gancho: bool) -> None:
        self.dtype = "float16"
        if con_gancho:
            gancho = type("Gancho", (), {"storage_dtype": "float8_e4m3fn"})()
            self._diffusers_hook = _Registro(gancho)

    def to(self, *, dtype: str) -> _Modulo:
        self.dtype = dtype
        return self


def test_tras_cargar_ip_adapter_el_unet_vuelve_a_fp8() -> None:
    """load_ip_adapter deja el UNet en fp16 (5,1 GB en SDXL): las capas con hook vuelven a fp8."""
    capas = [_Modulo(con_gancho=True), _Modulo(con_gancho=True), _Modulo(con_gancho=False)]
    unet = type("Unet", (), {"modules": lambda self: iter(capas)})()
    assert restaurar_almacenamiento_fp8(unet) == 2
    assert [c.dtype for c in capas] == ["float8_e4m3fn", "float8_e4m3fn", "float16"]
