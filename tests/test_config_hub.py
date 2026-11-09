"""Configuración por perfiles, modo offline y selección de archivos de modelos."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from storybook import config
from storybook.evaluation.asr_check import calcular_wer, normalizar_texto_wer
from storybook.hub import piper_repo_subpath, seleccionar_archivos_diffusers


def test_offline_por_defecto() -> None:
    assert config.is_offline()
    assert os.environ["HF_HOME"] == str(config.HF_HOME_DIR)


@pytest.mark.parametrize("perfil", ["default", "rapido", "calidad"])
def test_perfiles_validos(perfil: str) -> None:
    cfg = config.load_config(perfil)
    assert cfg.profile == perfil
    assert cfg.llm.num_ctx >= 6144
    assert cfg.image.width == 768 and cfg.image.height == 512


def test_herencia_de_perfiles() -> None:
    rapido = config.load_config("rapido")
    calidad = config.load_config("calidad")
    assert rapido.image.scheduler == "lcm" and rapido.image.steps <= 8
    assert calidad.image.scheduler == "dpmpp_2m_karras" and calidad.image.steps >= 20
    assert calidad.llm.model != rapido.llm.model
    assert rapido.llm.host == calidad.llm.host  # heredado de default


@pytest.mark.parametrize(
    ("ruta", "bible", "ip"),
    [
        ("configs/experiments/c1_baseline.yaml", False, False),
        ("configs/experiments/c2_bible.yaml", True, False),
        ("configs/experiments/c3_ipadapter.yaml", True, True),
    ],
)
def test_configs_experimentos(ruta: str, bible: bool, ip: bool) -> None:
    cfg = config.load_config(ruta)
    assert cfg.consistency.use_bible is bible
    assert cfg.image.ip_adapter.enabled is ip


def test_perfil_inexistente() -> None:
    with pytest.raises(config.ConfigError):
        config.load_config("no_existe")


def test_seleccion_diffusers_prefiere_fp16() -> None:
    archivos = [
        "model_index.json",
        "model.safetensors",
        "safety_checker/model.safetensors",
        "unet/config.json",
        "unet/diffusion_pytorch_model.safetensors",
        "unet/diffusion_pytorch_model.fp16.safetensors",
        "vae/config.json",
        "vae/diffusion_pytorch_model.bin",
        "tokenizer/vocab.json",
        "tokenizer/merges.txt",
    ]
    seleccion = seleccionar_archivos_diffusers(archivos)
    assert "unet/diffusion_pytorch_model.fp16.safetensors" in seleccion
    assert "unet/diffusion_pytorch_model.safetensors" not in seleccion
    assert "vae/diffusion_pytorch_model.bin" in seleccion  # único peso disponible
    assert "model.safetensors" not in seleccion and not any(
        s.startswith("safety_checker/") for s in seleccion
    )


def test_ruta_voz_piper() -> None:
    assert piper_repo_subpath("es_MX-claude-high") == "es/es_MX/claude/high"
    with pytest.raises(ValueError):
        piper_repo_subpath("voz-invalida")


def test_wer_normalizado() -> None:
    assert normalizar_texto_wer("¡Hola, Lucía!  ¿Qué  tal?") == "hola lucia que tal"
    assert calcular_wer("La niña vio el faro.", "la nina vio el faro") == 0.0
    assert calcular_wer("uno dos tres cuatro", "uno dos tres") == 0.25


def test_audioldm_en_la_cadena_de_sonido() -> None:
    """AudioLDM (no gated) va después de SA3 y antes de los fallbacks no generativos."""
    for perfil in ("rapido", "calidad"):
        backends = config.load_config(perfil).sound.backends
        assert "audioldm" in backends
        assert backends.index("sa3") < backends.index("audioldm") < backends.index("library")
        assert backends[-1] == "procedural"
    assert config.load_config("rapido").sound.audioldm_repo_id == "cvssp/audioldm"


def test_local_snapshot_lee_la_cache_sin_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from storybook.hub import ModelNotDownloadedError, local_snapshot, lora_weight_name

    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    repo = tmp_path / "models--org--modelo"
    (repo / "refs").mkdir(parents=True)
    (repo / "refs" / "main").write_text("abc123", encoding="utf-8")
    snapshot = repo / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (snapshot / "pytorch_lora_weights.safetensors").write_bytes(b"x")

    assert local_snapshot("org/modelo") == snapshot
    assert lora_weight_name(snapshot) == "pytorch_lora_weights.safetensors"
    with pytest.raises(ModelNotDownloadedError):
        local_snapshot("org/no-existe")


def test_num_predict_en_perfiles() -> None:
    assert config.load_config("rapido").llm.num_predict < config.load_config("rapido").llm.num_ctx
