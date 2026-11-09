"""Cliente mínimo de la API local de Ollama (http://localhost:11434).

Solo acepta hosts locales: es una garantía de código de la restricción "nada remoto en
tiempo de ejecución". La salida estructurada se pide con ``format`` = JSON Schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from storybook.logging_utils import get_logger, kv

logger = get_logger(__name__)

HOSTS_LOCALES = frozenset({"localhost", "127.0.0.1", "::1"})
_NS = 1e9


class LLMError(Exception):
    """Error base del componente de texto."""


class LLMConnectionError(LLMError):
    """Ollama no responde."""


class LLMModelNotFoundError(LLMError):
    """El modelo no está descargado en Ollama."""


class LLMResponseError(LLMError):
    """Respuesta vacía, truncada o con error del servidor."""


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str
    prompt_tokens: int
    output_tokens: int
    total_s: float
    load_s: float
    eval_s: float
    done_reason: str

    @property
    def tokens_por_s(self) -> float:
        return round(self.output_tokens / self.eval_s, 2) if self.eval_s > 0 else 0.0


def _normalizar_nombre(modelo: str) -> str:
    return modelo if ":" in modelo else f"{modelo}:latest"


class OllamaClient:
    def __init__(self, host: str = "http://localhost:11434", timeout_s: float = 600.0) -> None:
        nombre_host = urlparse(host).hostname or ""
        if nombre_host not in HOSTS_LOCALES:
            raise LLMError(
                f"Host de Ollama no local ({host}). StoryBook solo permite inferencia local."
            )
        self.host = host.rstrip("/")
        self._http = httpx.Client(base_url=self.host, timeout=httpx.Timeout(timeout_s, connect=5.0))

    # ---- Ciclo de vida -------------------------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> OllamaClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ---- Infraestructura -----------------------------------------------------------------
    def _request(self, metodo: str, ruta: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._http.request(metodo, ruta, **kwargs)
        except httpx.ConnectError as exc:
            raise LLMConnectionError(
                f"Ollama no responde en {self.host}. Abre la app de Ollama o ejecuta "
                "'ollama serve' en otra terminal."
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMResponseError(f"Tiempo de espera agotado llamando a {ruta}") from exc

    def version(self) -> str:
        respuesta = self._request("GET", "/api/version")
        respuesta.raise_for_status()
        return str(respuesta.json().get("version", "desconocida"))

    def list_models(self) -> list[str]:
        respuesta = self._request("GET", "/api/tags")
        respuesta.raise_for_status()
        return [m["name"] for m in respuesta.json().get("models", [])]

    def has_model(self, modelo: str) -> bool:
        objetivo = _normalizar_nombre(modelo)
        return any(_normalizar_nombre(m) == objetivo for m in self.list_models())

    def running(self) -> list[dict[str, Any]]:
        """Modelos cargados (``/api/ps``); ``size_vram`` indica cuánto está en GPU."""
        respuesta = self._request("GET", "/api/ps")
        respuesta.raise_for_status()
        return list(respuesta.json().get("models", []))

    def gpu_fraction(self, modelo: str) -> float | None:
        """Fracción del modelo cargada en VRAM (1.0 = todo en GPU; <1 = offload a CPU)."""
        objetivo = _normalizar_nombre(modelo)
        for info in self.running():
            if _normalizar_nombre(info.get("name", "")) == objetivo and info.get("size"):
                return round(info.get("size_vram", 0) / info["size"], 3)
        return None

    # ---- Inferencia ----------------------------------------------------------------------
    def chat_json(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        temperature: float,
        num_ctx: int,
        think: bool | None = False,
        keep_alive: str | int = "5m",
        seed: int | None = None,
    ) -> ChatResult:
        """Chat no streaming con salida restringida a ``schema``."""
        opciones: dict[str, Any] = {"temperature": temperature, "num_ctx": num_ctx}
        if seed is not None:
            opciones["seed"] = seed
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "format": schema,
            "stream": False,
            "keep_alive": keep_alive,
            "options": opciones,
        }
        if think is not None:
            payload["think"] = think

        respuesta = self._request("POST", "/api/chat", json=payload)
        if (
            respuesta.status_code == 400
            and "think" in payload
            and "think" in respuesta.text.lower()
        ):
            logger.warning(
                "modelo_sin_soporte_think", extra=kv(modelo=model, detalle=respuesta.text[:200])
            )
            payload.pop("think")
            respuesta = self._request("POST", "/api/chat", json=payload)
        if respuesta.status_code == 404:
            raise LLMModelNotFoundError(
                f"El modelo '{model}' no está en Ollama. Ejecuta: ollama pull {model}"
            )
        if respuesta.status_code >= 400:
            raise LLMResponseError(
                f"Ollama devolvió {respuesta.status_code}: {respuesta.text[:300]}"
            )

        datos = respuesta.json()
        contenido = str(datos.get("message", {}).get("content", ""))
        razon = str(datos.get("done_reason", ""))
        if not contenido.strip():
            raise LLMResponseError("Ollama devolvió una respuesta vacía")
        if razon == "length":
            raise LLMResponseError(
                f"Respuesta truncada por longitud (num_ctx={num_ctx}). Aumenta num_ctx."
            )
        return ChatResult(
            content=contenido,
            model=str(datos.get("model", model)),
            prompt_tokens=int(datos.get("prompt_eval_count", 0)),
            output_tokens=int(datos.get("eval_count", 0)),
            total_s=round(datos.get("total_duration", 0) / _NS, 3),
            load_s=round(datos.get("load_duration", 0) / _NS, 3),
            eval_s=round(datos.get("eval_duration", 0) / _NS, 3),
            done_reason=razon,
        )

    def unload(self, modelo: str) -> None:
        """Descarga el modelo de la VRAM (``keep_alive=0``). Obligatorio al terminar la etapa."""
        respuesta = self._request("POST", "/api/generate", json={"model": modelo, "keep_alive": 0})
        if respuesta.status_code >= 400:
            logger.warning("unload_fallo", extra=kv(modelo=modelo, status=respuesta.status_code))
        else:
            logger.info("modelo_descargado_de_vram", extra=kv(modelo=modelo))

    def pull(self, modelo: str) -> None:
        """Descarga un modelo (solo durante la instalación). Registra progreso cada 10 %."""
        ultimo_decil = -1
        try:
            with self._http.stream(
                "POST", "/api/pull", json={"model": modelo, "stream": True}, timeout=None
            ) as respuesta:
                if respuesta.status_code >= 400:
                    raise LLMResponseError(f"pull falló ({respuesta.status_code}) para {modelo}")
                for linea in respuesta.iter_lines():
                    if not linea:
                        continue
                    evento = json.loads(linea)
                    if "error" in evento:
                        raise LLMResponseError(f"pull de {modelo}: {evento['error']}")
                    total, completado = evento.get("total"), evento.get("completed")
                    if total and completado:
                        decil = int(10 * completado / total)
                        if decil != ultimo_decil:
                            ultimo_decil = decil
                            logger.info(
                                "ollama_pull",
                                extra=kv(
                                    modelo=modelo,
                                    estado=evento.get("status"),
                                    progreso=f"{decil * 10}%",
                                ),
                            )
                    elif evento.get("status") == "success":
                        logger.info("ollama_pull_ok", extra=kv(modelo=modelo))
        except httpx.ConnectError as exc:
            raise LLMConnectionError(f"Ollama no responde en {self.host}") from exc
