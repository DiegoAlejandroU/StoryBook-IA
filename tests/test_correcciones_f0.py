"""Regresiones de los fallos encontrados en la prueba real de la Fase 0 (9-nov-2026)."""

from __future__ import annotations

import json

import httpx
import pytest

from storybook.hub import seleccionar_archivos_diffusers
from storybook.schemas import StoryBible, esquema_json_llm
from storybook.story.llm_client import LLMResponseError, OllamaClient


def test_canon_no_va_en_el_esquema_del_llm(bible_dict: dict) -> None:
    """El canon lo calcula el validador; si el LLM lo escribe, duplica hechos y se trunca."""
    assert "canon" not in esquema_json_llm(StoryBible)["properties"]
    bible = StoryBible.model_validate(bible_dict)
    hechos = [h for e in bible.escenas for h in e.hechos_nuevos]
    assert all(h in bible.canon for h in hechos)


def test_seleccion_incluye_vocoder_de_audioldm() -> None:
    archivos = [
        "model_index.json",
        "unet/config.json",
        "unet/diffusion_pytorch_model.safetensors",
        "vocoder/config.json",
        "vocoder/model.safetensors",
        "safety_checker/config.json",
        "safety_checker/model.safetensors",
    ]
    seleccion = seleccionar_archivos_diffusers(archivos)
    assert "vocoder/model.safetensors" in seleccion and "vocoder/config.json" in seleccion
    assert not any(s.startswith("safety_checker/") for s in seleccion)


def test_truncamiento_conserva_la_salida_parcial() -> None:
    cuerpo = {
        "model": "m",
        "message": {"role": "assistant", "content": '{"titulo": "La luz'},
        "done": True,
        "done_reason": "length",
        "eval_count": 4096,
        "eval_duration": 128_000_000_000,
    }
    transporte = httpx.MockTransport(lambda r: httpx.Response(200, json=cuerpo))
    with OllamaClient(transport=transporte) as c, pytest.raises(LLMResponseError) as info:
        c.chat_json(model="m", messages=[], schema={}, temperature=0.7, num_ctx=8192)
    assert info.value.contenido.startswith('{"titulo"')
    assert info.value.output_tokens == 4096 and info.value.eval_s == 128.0
    assert json.dumps(cuerpo)  # el cuerpo de prueba es JSON válido
