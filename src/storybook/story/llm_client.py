"""Cliente mínimo de la API local de Ollama (http://localhost:11434).

Solo acepta hosts locales: es una garantía de código de la restricción "nada remoto en
tiempo de ejecución". La salida estructurada se pide con ``format`` = JSON Schema.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from storybook.logging_utils import get_logger, kv
from storybook.schemas import esquema_json_llm
from storybook.story.prompts import mensaje_reparacion

logger = get_logger(__name__)

M = TypeVar("M", bound=BaseModel)
Reparador = Callable[[list[str]], dict[str, str]]

HOSTS_LOCALES = frozenset({"localhost", "127.0.0.1", "::1"})
_NS = 1e9


class LLMError(Exception):
    """Error base del componente de texto."""


class LLMConnectionError(LLMError):
    """Ollama no responde."""


class LLMModelNotFoundError(LLMError):
    """El modelo no está descargado en Ollama."""


class LLMResponseError(LLMError):
    """Respuesta vacía, truncada o con error del servidor.

    En truncamientos conserva la salida parcial y los tokens para diagnosticar (bucles,
    campos demasiado largos).
    """

    def __init__(
        self, mensaje: str, *, contenido: str = "", output_tokens: int = 0, eval_s: float = 0.0
    ) -> None:
        super().__init__(mensaje)
        self.contenido = contenido
        self.output_tokens = output_tokens
        self.eval_s = eval_s


class LLMValidationError(LLMError):
    """El modelo no produjo una salida válida tras agotar los reintentos."""

    def __init__(
        self, mensaje: str, errores_por_intento: list[list[str]], ultimo_contenido: str = ""
    ) -> None:
        super().__init__(mensaje)
        self.errores_por_intento = errores_por_intento
        self.ultimo_contenido = ultimo_contenido


def errores_validacion(exc: ValidationError) -> list[str]:
    """Errores de Pydantic en texto legible (``campo.subcampo: mensaje``) para el reintento."""
    errores: list[str] = []
    for error in exc.errors():
        ruta = ".".join(str(parte) for parte in error.get("loc", ()))
        errores.append(f"{ruta}: {error['msg']}" if ruta else str(error["msg"]))
    return errores


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


@dataclass(frozen=True)
class GeneracionValidada(Generic[M]):
    """Objeto validado más la trazabilidad de la generación (va al manifest)."""

    objeto: M
    intentos: int
    resultado: ChatResult
    errores_por_intento: list[list[str]] = field(default_factory=list)


def _normalizar_nombre(modelo: str) -> str:
    return modelo if ":" in modelo else f"{modelo}:latest"


class OllamaClient:
    def __init__(
        self,
        host: str = "http://localhost:11434",
        timeout_s: float = 600.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        nombre_host = urlparse(host).hostname or ""
        if nombre_host not in HOSTS_LOCALES:
            raise LLMError(
                f"Host de Ollama no local ({host}). StoryBook solo permite inferencia local."
            )
        self.host = host.rstrip("/")
        # ``transport`` permite inyectar httpx.MockTransport en los tests (sin red).
        self._http = httpx.Client(
            base_url=self.host, timeout=httpx.Timeout(timeout_s, connect=5.0), transport=transport
        )

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
        except httpx.TransportError as exc:
            raise LLMConnectionError(
                f"Se cortó la conexión con Ollama en {ruta} ({type(exc).__name__}). "
                "Revisa que Ollama siga abierto."
            ) from exc

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
        num_predict: int | None = None,
        opciones_extra: dict[str, Any] | None = None,
    ) -> ChatResult:
        """Chat no streaming con salida restringida a ``schema``."""
        opciones: dict[str, Any] = {"temperature": temperature, "num_ctx": num_ctx}
        if opciones_extra:
            opciones.update(opciones_extra)
        if seed is not None:
            opciones["seed"] = seed
        if num_predict is not None:
            opciones["num_predict"] = num_predict
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

        try:
            datos = respuesta.json()
        except ValueError as exc:
            raise LLMResponseError(
                f"La respuesta de Ollama no es JSON: {respuesta.text[:200]}"
            ) from exc
        contenido = str(datos.get("message", {}).get("content", ""))
        razon = str(datos.get("done_reason", ""))
        if not contenido.strip():
            raise LLMResponseError("Ollama devolvió una respuesta vacía")
        if razon == "length":
            raise LLMResponseError(
                f"Respuesta truncada por longitud (num_ctx={num_ctx}, num_predict={num_predict}). "
                "Si el JSON quedó incompleto, aumenta num_predict; si se repetía, "
                "revisa el prompt.",
                contenido=contenido,
                output_tokens=int(datos.get("eval_count", 0)),
                eval_s=round(datos.get("eval_duration", 0) / _NS, 3),
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

    def generar_validado(
        self,
        *,
        modelo_salida: type[M],
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        num_ctx: int,
        max_reintentos: int,
        think: bool | None = False,
        keep_alive: str | int = "5m",
        seed: int | None = None,
        reparar: Reparador | None = None,
        num_predict: int | None = None,
        opciones_extra: dict[str, Any] | None = None,
    ) -> GeneracionValidada[M]:
        """Pide JSON con el esquema de ``modelo_salida`` y lo valida con Pydantic.

        Si la validación falla, devuelve al modelo su respuesta y los errores (``reparar``,
        por defecto ``mensaje_reparacion``) hasta ``max_reintentos`` veces. Solo se conserva el
        último intento fallido para no desbordar ``num_ctx``. Si una reparación también falla,
        el intento siguiente empieza de cero con otra seed: en F1 el 4B quedó atrapado en el
        mismo error (resúmenes en inglés) durante 3 reparaciones seguidas, mientras que los
        intentos limpios casi siempre pasan. Los errores de conexión o de
        modelo no encontrado no se reintentan. Si la respuesta se corta por longitud (bucle de
        repetición), se reintenta sin reenviar la salida cortada (no cabría en ``num_ctx``) y
        con otra seed. Si se agotan los intentos lanza ``LLMValidationError`` con los errores
        de cada intento y la última salida.
        """
        reparador = reparar or mensaje_reparacion
        esquema = esquema_json_llm(modelo_salida)
        errores_por_intento: list[list[str]] = []
        reparacion: list[dict[str, str]] = []
        ultimo_contenido = ""
        semilla = seed
        for intento in range(1, max_reintentos + 2):
            era_reparacion = bool(reparacion)
            try:
                resultado = self.chat_json(
                    model=model,
                    messages=[*messages, *reparacion],
                    schema=esquema,
                    temperature=temperature,
                    num_ctx=num_ctx,
                    think=think,
                    keep_alive=keep_alive,
                    seed=semilla,
                    num_predict=num_predict,
                    opciones_extra=opciones_extra,
                )
            except LLMResponseError as exc:
                if not exc.contenido:
                    raise
                errores = [
                    "La respuesta se cortó por longitud antes de cerrar el JSON (probablemente "
                    "repetía frases). Escribe textos más breves, sin repetir frases, y cierra el "
                    "JSON."
                ]
                errores_por_intento.append(errores)
                ultimo_contenido = exc.contenido
                logger.warning(
                    "salida_truncada",
                    extra=kv(
                        salida=modelo_salida.__name__, intento=intento, tokens=exc.output_tokens
                    ),
                )
                reparacion = [reparador(errores)]
                if seed is not None:
                    semilla = seed + intento
                continue
            ultimo_contenido = resultado.content
            try:
                objeto = modelo_salida.model_validate_json(resultado.content)
            except ValidationError as exc:
                errores = errores_validacion(exc)
                errores_por_intento.append(errores)
                logger.warning(
                    "salida_invalida",
                    extra=kv(
                        salida=modelo_salida.__name__,
                        intento=intento,
                        errores=len(errores),
                        primero=errores[0] if errores else "",
                    ),
                )
                if era_reparacion:
                    reparacion = []  # la reparación no funcionó: se empieza de cero
                    if seed is not None:
                        semilla = seed + intento
                else:
                    reparacion = [
                        {"role": "assistant", "content": resultado.content},
                        reparador(errores),
                    ]
                continue
            return GeneracionValidada(
                objeto=objeto,
                intentos=intento,
                resultado=resultado,
                errores_por_intento=errores_por_intento,
            )
        raise LLMValidationError(
            f"{modelo_salida.__name__}: salida inválida tras {max_reintentos + 1} intentos",
            errores_por_intento,
            ultimo_contenido,
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
