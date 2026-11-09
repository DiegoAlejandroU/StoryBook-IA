"""Tests del cliente de Ollama con transporte HTTP simulado (sin red ni GPU)."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from storybook.schemas import StoryBible
from storybook.story.llm_client import (
    LLMConnectionError,
    LLMError,
    LLMModelNotFoundError,
    LLMResponseError,
    LLMValidationError,
    OllamaClient,
)
from tests.conftest import escena_dict

Handler = Callable[[httpx.Request], httpx.Response]


def respuesta_chat(contenido: str, *, done_reason: str = "stop", model: str = "m:1") -> dict:
    return {
        "model": model,
        "message": {"role": "assistant", "content": contenido},
        "done": True,
        "done_reason": done_reason,
        "prompt_eval_count": 120,
        "eval_count": 400,
        "total_duration": 5_000_000_000,
        "load_duration": 1_000_000_000,
        "eval_duration": 4_000_000_000,
    }


class Grabador:
    """Transporte simulado que responde en orden y guarda las peticiones."""

    def __init__(self, respuestas: list[httpx.Response | Handler]) -> None:
        self._respuestas = list(respuestas)
        self.peticiones: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.peticiones.append(request)
        siguiente = self._respuestas.pop(0)
        return siguiente(request) if callable(siguiente) else siguiente

    def payload(self, indice: int) -> dict[str, Any]:
        return json.loads(self.peticiones[indice].content)


def cliente(grabador: Grabador) -> OllamaClient:
    return OllamaClient(transport=httpx.MockTransport(grabador))


def ok(contenido: str, **kw: Any) -> httpx.Response:
    return httpx.Response(200, json=respuesta_chat(contenido, **kw))


def generar(c: OllamaClient, max_reintentos: int = 2, **kw: Any):
    return c.generar_validado(
        modelo_salida=StoryBible,
        model="qwen3:4b",
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        temperature=0.7,
        num_ctx=8192,
        max_reintentos=max_reintentos,
        **kw,
    )


# ---- Seguridad: solo hosts locales -------------------------------------------------------
@pytest.mark.parametrize("host", ["http://example.com:11434", "https://api.openai.com"])
def test_rechaza_host_remoto(host: str) -> None:
    with pytest.raises(LLMError, match="no local"):
        OllamaClient(host=host)


@pytest.mark.parametrize("host", ["http://localhost:11434", "http://127.0.0.1:11434/"])
def test_acepta_host_local(host: str) -> None:
    c = OllamaClient(host=host, transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    assert not c.host.endswith("/")
    c.close()


# ---- chat_json ---------------------------------------------------------------------------
def test_chat_json_payload_y_metricas() -> None:
    g = Grabador([ok('{"a": 1}')])
    with cliente(g) as c:
        r = c.chat_json(
            model="qwen3:4b",
            messages=[{"role": "user", "content": "hola"}],
            schema={"type": "object"},
            temperature=0.2,
            num_ctx=6144,
            think=False,
            keep_alive=0,
            seed=7,
        )
    p = g.payload(0)
    assert g.peticiones[0].url.path == "/api/chat"
    assert p["think"] is False
    assert p["keep_alive"] == 0
    assert p["stream"] is False
    assert p["format"] == {"type": "object"}
    assert p["options"] == {"temperature": 0.2, "num_ctx": 6144, "seed": 7}
    assert r.content == '{"a": 1}'
    assert (r.prompt_tokens, r.output_tokens) == (120, 400)
    assert (r.total_s, r.load_s, r.eval_s) == (5.0, 1.0, 4.0)
    assert r.tokens_por_s == 100.0


def test_think_none_no_se_envia() -> None:
    g = Grabador([ok("{}")])
    with cliente(g) as c:
        c.chat_json(model="m", messages=[], schema={}, temperature=0.7, num_ctx=4096, think=None)
    assert "think" not in g.payload(0)
    assert "seed" not in g.payload(0)["options"]


def test_modelo_sin_soporte_think_reintenta_sin_el() -> None:
    g = Grabador([httpx.Response(400, text='{"error":"model does not support think"}'), ok("{}")])
    with cliente(g) as c:
        c.chat_json(model="m", messages=[], schema={}, temperature=0.7, num_ctx=4096)
    assert g.payload(0)["think"] is False
    assert "think" not in g.payload(1)


def test_modelo_no_encontrado() -> None:
    g = Grabador([httpx.Response(404, json={"error": "model 'x' not found"})])
    with cliente(g) as c, pytest.raises(LLMModelNotFoundError, match="ollama pull x"):
        c.chat_json(model="x", messages=[], schema={}, temperature=0.7, num_ctx=4096)


def test_error_500() -> None:
    g = Grabador([httpx.Response(500, text="CUDA out of memory")])
    with cliente(g) as c, pytest.raises(LLMResponseError, match="500"):
        c.chat_json(model="m", messages=[], schema={}, temperature=0.7, num_ctx=4096)


def test_error_de_conexion() -> None:
    def falla(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with cliente(Grabador([falla])) as c, pytest.raises(LLMConnectionError, match="ollama serve"):
        c.chat_json(model="m", messages=[], schema={}, temperature=0.7, num_ctx=4096)


def test_timeout() -> None:
    def lento(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lento", request=request)

    with cliente(Grabador([lento])) as c, pytest.raises(LLMResponseError, match="espera"):
        c.chat_json(model="m", messages=[], schema={}, temperature=0.7, num_ctx=4096)


def test_conexion_cortada_a_mitad() -> None:
    def cortada(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("peer closed", request=request)

    with cliente(Grabador([cortada])) as c, pytest.raises(LLMConnectionError):
        c.chat_json(model="m", messages=[], schema={}, temperature=0.7, num_ctx=4096)


@pytest.mark.parametrize("contenido", ["", "   \n"])
def test_respuesta_vacia(contenido: str) -> None:
    with cliente(Grabador([ok(contenido)])) as c, pytest.raises(LLMResponseError, match="vac"):
        c.chat_json(model="m", messages=[], schema={}, temperature=0.7, num_ctx=4096)


def test_respuesta_truncada_por_longitud() -> None:
    g = Grabador([ok('{"titulo": "La', done_reason="length")])
    with cliente(g) as c, pytest.raises(LLMResponseError, match="num_ctx=4096"):
        c.chat_json(model="m", messages=[], schema={}, temperature=0.7, num_ctx=4096)


def test_cuerpo_http_no_json() -> None:
    g = Grabador([httpx.Response(200, text="<html>proxy</html>")])
    with cliente(g) as c, pytest.raises(LLMResponseError, match="no es JSON"):
        c.chat_json(model="m", messages=[], schema={}, temperature=0.7, num_ctx=4096)


# ---- generar_validado: Story Bible con reintentos ---------------------------------------
def test_bible_valida_al_primer_intento(bible_dict: dict) -> None:
    g = Grabador([ok(json.dumps(bible_dict))])
    with cliente(g) as c:
        r = generar(c, keep_alive="5m")
    assert r.intentos == 1
    assert r.errores_por_intento == []
    assert len(r.objeto.escenas) == 5
    p = g.payload(0)
    assert p["think"] is False
    assert p["keep_alive"] == "5m"
    assert p["format"]["type"] == "object"
    assert "$defs" not in json.dumps(p["format"])
    assert len(p["messages"]) == 2


def test_json_invalido_se_repara(bible_dict: dict) -> None:
    g = Grabador([ok('{"titulo": "roto",'), ok(json.dumps(bible_dict))])
    with cliente(g) as c:
        r = generar(c)
    assert r.intentos == 2
    assert len(r.errores_por_intento) == 1
    assert "json" in r.errores_por_intento[0][0].lower()
    mensajes = g.payload(1)["messages"]
    assert mensajes[-2] == {"role": "assistant", "content": '{"titulo": "roto",'}
    assert mensajes[-1]["role"] == "user"
    assert "no pasó la validación" in mensajes[-1]["content"]


@pytest.mark.parametrize("n_escenas", [4, 6])
def test_numero_incorrecto_de_escenas_se_repara(bible_dict: dict, n_escenas: int) -> None:
    malo = copy.deepcopy(bible_dict)
    if n_escenas == 4:
        malo["escenas"] = malo["escenas"][:4]
    else:
        extra = escena_dict(5)
        extra["numero"] = 6
        malo["escenas"].append(extra)
    g = Grabador([ok(json.dumps(malo)), ok(json.dumps(bible_dict))])
    with cliente(g) as c:
        r = generar(c)
    assert r.intentos == 2
    assert len(r.objeto.escenas) == 5
    reparacion = g.payload(1)["messages"][-1]["content"]
    assert "escenas" in reparacion


def test_solo_se_conserva_el_ultimo_intento_fallido(bible_dict: dict) -> None:
    g = Grabador([ok("{}"), ok("[1]"), ok(json.dumps(bible_dict))])
    with cliente(g) as c:
        r = generar(c, max_reintentos=3)
    assert r.intentos == 3
    tercero = g.payload(2)["messages"]
    assert len(tercero) == 4
    assert tercero[2]["content"] == "[1]"


def test_agota_reintentos(bible_dict: dict) -> None:
    malo = copy.deepcopy(bible_dict)
    malo["escenas"] = malo["escenas"][:4]
    g = Grabador([ok(json.dumps(malo))] * 3)
    with cliente(g) as c, pytest.raises(LLMValidationError) as info:
        generar(c, max_reintentos=2)
    assert len(g.peticiones) == 3
    assert len(info.value.errores_por_intento) == 3


def test_sin_reintentos_falla_de_inmediato() -> None:
    g = Grabador([ok("no es json")])
    with cliente(g) as c, pytest.raises(LLMValidationError):
        generar(c, max_reintentos=0)
    assert len(g.peticiones) == 1


def test_reparar_personalizado(bible_dict: dict) -> None:
    g = Grabador([ok("{}"), ok(json.dumps(bible_dict))])
    with cliente(g) as c:
        generar(c, reparar=lambda errores: {"role": "user", "content": f"N={len(errores)}"})
    assert g.payload(1)["messages"][-1]["content"].startswith("N=")


def test_modelo_no_encontrado_no_se_reintenta() -> None:
    g = Grabador([httpx.Response(404, json={"error": "not found"})])
    with cliente(g) as c, pytest.raises(LLMModelNotFoundError):
        generar(c)
    assert len(g.peticiones) == 1


# ---- Utilidades: modelos, VRAM y descarga de la GPU -------------------------------------
def test_has_model_normaliza_latest() -> None:
    tags = {"models": [{"name": "llama3:latest"}, {"name": "qwen3:4b"}]}
    g = Grabador([httpx.Response(200, json=tags)] * 3)
    with cliente(g) as c:
        assert c.has_model("llama3")
        assert c.has_model("qwen3:4b")
        assert not c.has_model("qwen3:8b")


def test_gpu_fraction() -> None:
    ps = {"models": [{"name": "qwen3:8b", "size": 6_000, "size_vram": 3_000}]}
    g = Grabador([httpx.Response(200, json=ps)] * 2)
    with cliente(g) as c:
        assert c.gpu_fraction("qwen3:8b") == 0.5
        assert c.gpu_fraction("otro") is None


def test_unload_envia_keep_alive_cero() -> None:
    g = Grabador([httpx.Response(200, json={})])
    with cliente(g) as c:
        c.unload("qwen3:4b")
    assert g.peticiones[0].url.path == "/api/generate"
    assert g.payload(0) == {"model": "qwen3:4b", "keep_alive": 0}


def test_version() -> None:
    with cliente(Grabador([httpx.Response(200, json={"version": "0.12.0"})])) as c:
        assert c.version() == "0.12.0"
