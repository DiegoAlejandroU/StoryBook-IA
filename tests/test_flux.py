"""FLUX.1-schnell en 4 GB (perfil Avanzada, 18 nov): copia fp8, carga y pipeline.

La conversión y la carga se prueban con un FLUX y un T5 diminutos y aleatorios (en CPU);
se saltan si el entorno no tiene torch/diffusers (como la VM de pruebas).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from storybook import config
from storybook.image import flux
from storybook.image.generator import DiffusersBackend, GeneradorImagenes, backend_para


class _Componente:
    def __init__(self) -> None:
        self.dispositivos: list[str] = []

    def to(self, dispositivo: str) -> _Componente:
        self.dispositivos.append(dispositivo)
        return self


class _PipeFalso:
    def __init__(self) -> None:
        self.text_encoder = _Componente()
        self.text_encoder_2: Any = None
        self.vae = _Componente()
        self.tokenizer = "clip"
        self.tokenizer_2 = "t5"
        self.llamadas: list[dict[str, Any]] = []
        self.codificados: list[tuple[str, Any]] = []

    def encode_prompt(self, *, prompt: str, device: str, max_sequence_length: int) -> Any:
        self.codificados.append((prompt, self.text_encoder_2))
        return f"emb:{prompt}", "pooled", "ids"

    def __call__(self, **kwargs: Any) -> str:
        self.llamadas.append(kwargs)
        return "imagen"


def test_el_pipeline_flux_quita_lo_que_flux_no_usa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flux, "free_cuda_memory", lambda: None)
    pipe = _PipeFalso()
    cargas: list[str] = []

    def cargar_t5() -> str:
        cargas.append("t5")
        return "T5"

    envoltura = flux.PipelineFlux(pipe, 256, "cuda", cargar_t5=cargar_t5)
    assert envoltura.tokenizer == "t5"  # el prompt se mide con el tokenizer de T5
    resultado = envoltura(
        prompt="a dog", negative_prompt="x", ip_adapter_image_embeds=[1], num_inference_steps=4
    )
    assert resultado == "imagen"
    # 19 nov: T5 se carga solo para leer el prompt y se suelta antes de dibujar.
    assert cargas == ["t5"] and pipe.codificados == [("a dog", "T5")]
    assert pipe.text_encoder_2 is None
    assert pipe.llamadas == [
        {
            "prompt_embeds": "emb:a dog",
            "pooled_prompt_embeds": "pooled",
            "max_sequence_length": 256,
            "num_inference_steps": 4,
        }
    ]
    assert pipe.text_encoder.dispositivos == ["cuda"] and pipe.vae.dispositivos == ["cuda"]
    envoltura.estacionar()
    assert pipe.text_encoder.dispositivos[-1] == "cpu" and pipe.vae.dispositivos[-1] == "cpu"


def test_con_t5_residente_no_se_recarga(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flux, "free_cuda_memory", lambda: None)
    pipe = _PipeFalso()
    pipe.text_encoder_2 = "T5 residente"
    flux.PipelineFlux(pipe, 256, "cuda")(prompt="a cat")
    assert pipe.codificados == [("a cat", "T5 residente")]
    assert pipe.text_encoder_2 == "T5 residente"


def test_el_perfil_avanzada_usa_flux_sin_ip_adapter() -> None:
    cfg = config.load_config("avanzada")
    assert cfg.image.arquitectura == "flux" and not cfg.image.ip_adapter.enabled
    assert isinstance(backend_para(cfg.image), flux.FluxBackend)
    assert isinstance(backend_para(config.load_config("sdxl").image), DiffusersBackend)
    generador = GeneradorImagenes(cfg.image, cfg.consistency)
    assert generador.max_tokens_prompt == 254 and not generador.usar_ip_adapter
    assert flux.carpeta_fp8(cfg.image) == config.MODELS_DIR / "flux-schnell-fp8"
    assert cfg.image.t5_por_demanda and cfg.image.offload_stream
    with pytest.raises(ValueError, match="múltiplos de 16"):
        cfg.image.model_validate({**cfg.image.model_dump(), "width": 1048})


def test_sin_la_copia_fp8_explica_como_hacerla(tmp_path: Path) -> None:
    with pytest.raises(flux.FluxNoPreparadoError, match="convertir_flux_fp8"):
        flux.cargar_componente_fp8(tmp_path, "transformer")
    assert not flux.fp8_listo(tmp_path)


def test_convertir_y_cargar_un_flux_diminuto(tmp_path: Path) -> None:
    torch = pytest.importorskip("torch")
    pytest.importorskip("diffusers")
    from diffusers import FluxTransformer2DModel
    from diffusers.hooks import apply_group_offloading
    from transformers import T5Config, T5EncoderModel

    torch.manual_seed(0)
    origen, destino = tmp_path / "oficial", tmp_path / "fp8"
    transformer = FluxTransformer2DModel(
        patch_size=1, in_channels=16, num_layers=2, num_single_layers=2, attention_head_dim=16,
        num_attention_heads=2, joint_attention_dim=32, pooled_projection_dim=16,
        guidance_embeds=False, axes_dims_rope=(4, 6, 6),
    ).to(torch.bfloat16).eval()  # fmt: skip
    transformer.save_pretrained(origen / "transformer", max_shard_size="200KB")
    t5 = T5EncoderModel(
        T5Config(
            vocab_size=100, d_model=32, d_kv=8, d_ff=64, num_layers=2, num_heads=4,
            feed_forward_proj="gated-gelu", is_encoder_decoder=False,
        )
    ).to(torch.bfloat16).eval()  # fmt: skip
    t5.save_pretrained(origen / "text_encoder_2")

    for componente in flux.COMPONENTES_FP8:
        indice = flux.convertir_componente(origen, destino, componente)
        assert indice["tensores_fp8"] > 0 and indice["ignoradas"] == []
    assert flux.fp8_listo(destino)

    transformer8 = flux.cargar_componente_fp8(destino, "transformer")
    t58 = flux.cargar_componente_fp8(destino, "text_encoder_2")
    for modelo in (transformer8, t58):
        tipos = {p.dtype for p in modelo.parameters()}
        assert tipos == {torch.float8_e4m3fn, torch.bfloat16}
    assert t58.encoder.embed_tokens.weight is t58.shared.weight
    assert t58.dtype == torch.bfloat16  # lo que usa FluxPipeline para el prompt

    ids = torch.randint(0, 100, (1, 12))
    entrada = {
        "hidden_states": torch.randn(1, 64, 16, dtype=torch.bfloat16),
        "encoder_hidden_states": torch.randn(1, 8, 32, dtype=torch.bfloat16),
        "pooled_projections": torch.randn(1, 16, dtype=torch.bfloat16),
        "timestep": torch.tensor([0.5], dtype=torch.bfloat16),
        "img_ids": torch.zeros(64, 3),
        "txt_ids": torch.zeros(8, 3),
    }
    with torch.no_grad():
        base_t5, fp8_t5 = t5(ids)[0].float(), t58(ids)[0].float()
        base_tr = transformer(**entrada).sample.float()
        fp8_tr = transformer8(**entrada).sample.float()
    # fp8 pierde algo de precisión, no el resultado (un error de carga daría ~100 %).
    assert float((base_t5 - fp8_t5).norm() / base_t5.norm()) < 0.1
    assert float((base_tr - fp8_tr).norm() / base_tr.norm()) < 0.1
    assert {p.dtype for p in transformer8.parameters()} == {torch.float8_e4m3fn, torch.bfloat16}

    # Los mismos bloques con group offloading dan lo mismo (aquí CPU -> CPU).
    cpu = torch.device("cpu")
    apply_group_offloading(transformer8, onload_device=cpu, num_blocks_per_group=1)
    apply_group_offloading(t58.encoder, onload_device=cpu, num_blocks_per_group=1)
    with torch.no_grad():
        assert torch.equal(transformer8(**entrada).sample.float(), fp8_tr)
        assert torch.equal(t58(ids)[0].float(), fp8_t5)
