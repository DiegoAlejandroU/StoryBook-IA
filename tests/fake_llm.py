"""LLM falso para los tests del planificador y del auditor (sin Ollama ni GPU).

Responde en orden con los objetos encolados por tipo de salida y registra cada llamada.
Un elemento de la cola puede ser un ``dict`` (se valida con el modelo pedido) o una
excepción (se lanza, para simular fallos del LLM).
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from pydantic import BaseModel

from storybook.story.llm_client import ChatResult, GeneracionValidada


class FakeLLM:
    def __init__(self) -> None:
        self.colas: dict[str, deque[Any]] = defaultdict(deque)
        self.llamadas: list[dict[str, Any]] = []
        self.descargados: list[str] = []

    def encolar(self, salida: type[BaseModel] | str, *respuestas: Any) -> FakeLLM:
        nombre = salida if isinstance(salida, str) else salida.__name__
        self.colas[nombre].extend(respuestas)
        return self

    def llamadas_de(self, salida: type[BaseModel]) -> list[dict[str, Any]]:
        return [c for c in self.llamadas if c["modelo_salida"] is salida]

    def generar_validado(self, *, modelo_salida: type[BaseModel], **kwargs: Any):
        self.llamadas.append({"modelo_salida": modelo_salida, **kwargs})
        cola = self.colas[modelo_salida.__name__]
        if not cola:
            raise AssertionError(f"FakeLLM sin respuestas para {modelo_salida.__name__}")
        respuesta = cola.popleft()
        if isinstance(respuesta, Exception):
            raise respuesta
        objeto = modelo_salida.model_validate(respuesta)
        resultado = ChatResult(
            content=objeto.model_dump_json(),
            model=kwargs.get("model", "fake"),
            prompt_tokens=100,
            output_tokens=200,
            total_s=1.0,
            load_s=0.1,
            eval_s=0.9,
            done_reason="stop",
        )
        return GeneracionValidada(objeto=objeto, intentos=1, resultado=resultado)

    def unload(self, modelo: str) -> None:
        self.descargados.append(modelo)
