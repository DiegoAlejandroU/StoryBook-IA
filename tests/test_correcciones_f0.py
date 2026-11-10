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


def test_ids_de_personaje_se_normalizan(bible_dict: dict) -> None:
    """Ollama ordena las claves alfabéticamente: el LLM puede escribir 'Lucía' en vez de 'lucia'."""
    import copy

    datos = copy.deepcopy(bible_dict)
    datos["escenas"][0]["personajes_presentes"] = ["Lucía"]
    datos["personajes"][0]["id"] = "Lucia"
    bible = StoryBible.model_validate(datos)
    assert bible.personajes[0].id == "lucia"
    assert bible.escenas[0].personajes_presentes == ["lucia"]


def test_opciones_de_muestreo_se_envian() -> None:
    from storybook.config import LLMConfig

    enviados: list[dict] = []

    def responder(request: httpx.Request) -> httpx.Response:
        enviados.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "{}"}, "done_reason": "stop"})

    opciones = LLMConfig(model="m").opciones_muestreo()
    assert opciones["presence_penalty"] > 0 and opciones["top_k"] == 20
    with OllamaClient(transport=httpx.MockTransport(responder)) as c:
        c.chat_json(
            model="m",
            messages=[],
            schema={},
            temperature=0.7,
            num_ctx=4096,
            opciones_extra=opciones,
        )
    assert enviados[0]["options"]["presence_penalty"] == opciones["presence_penalty"]
    assert enviados[0]["options"]["num_ctx"] == 4096


def test_truncamiento_se_reintenta_sin_reenviar_la_salida(bible_dict: dict) -> None:
    peticiones: list[dict] = []
    bucle = '{"titulo": "' + "Ella lo sabe. " * 50
    respuestas = [
        {"message": {"content": bucle}, "done_reason": "length", "eval_count": 2048},
        {"message": {"content": json.dumps(bible_dict)}, "done_reason": "stop"},
    ]

    def responder(request: httpx.Request) -> httpx.Response:
        peticiones.append(json.loads(request.content))
        return httpx.Response(200, json=respuestas[len(peticiones) - 1])

    mensajes = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    with OllamaClient(transport=httpx.MockTransport(responder)) as c:
        r = c.generar_validado(
            modelo_salida=StoryBible,
            model="m",
            messages=mensajes,
            temperature=0.7,
            num_ctx=4096,
            max_reintentos=2,
            seed=42,
        )
    assert r.intentos == 2 and "cortó" in r.errores_por_intento[0][0]
    segundo = peticiones[1]
    assert len(segundo["messages"]) == 3  # sistema, usuario y reparación; sin la salida cortada
    assert all("Ella lo sabe" not in m["content"] for m in segundo["messages"])
    assert segundo["options"]["seed"] != peticiones[0]["options"]["seed"]
