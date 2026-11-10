"""Dependencias simuladas: el pipeline completo sin GPU, Ollama ni modelos descargados.

Sirven para probar la UI (``StoryBook.cmd mock`` o ``streamlit run app/streamlit_app.py --
--mock``), para ``scripts/verify_offline.py`` y para los tests. El texto es siempre la misma
historia de ejemplo (generada de verdad en F1), las imágenes son tarjetas de color con el
número de escena, la voz es un tono modulado de duración proporcional al texto y el sonido es
la síntesis procedural real (CPU). La UI muestra un aviso de "modo simulado".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import numpy as np
from PIL import Image, ImageDraw

from storybook.config import ImageConfig, LLMConfig
from storybook.pipeline import Dependencias
from storybook.schemas import StoryBible, StoryRequest
from storybook.sound.generator import ProceduralBackend

HISTORIA_EJEMPLO: Final = Path(__file__).parent / "datos" / "historia_ejemplo.json"
FRECUENCIA_VOZ: Final = 22_050
SEGUNDOS_POR_CARACTER: Final = 0.06  # ~16 caracteres por segundo, como una narración


def escribir_simulado(
    solicitud: StoryRequest, cfg_llm: LLMConfig
) -> tuple[StoryBible, dict[str, Any]]:
    bible = StoryBible.model_validate_json(HISTORIA_EJEMPLO.read_text(encoding="utf-8"))
    return bible, {"modelo": "simulado", "idea_recibida": solicitud.idea, "llamadas": []}


class _SalidaImagen:
    def __init__(self, imagen: Image.Image) -> None:
        self.images = [imagen]


class _PipeSimulado:
    tokenizer = None  # el contador de tokens usa la estimación heurística

    def __init__(self) -> None:
        self.llamadas = 0

    def __call__(self, **kwargs: Any) -> _SalidaImagen:
        self.llamadas += 1
        ancho, alto = int(kwargs["width"]), int(kwargs["height"])
        semilla = int(kwargs.get("generator") or 0) + self.llamadas
        rng = np.random.default_rng(semilla)
        a, b = rng.integers(40, 200, size=3), rng.integers(40, 200, size=3)
        gradiente = np.linspace(0, 1, alto)[:, None, None]
        pixeles = (a * (1 - gradiente) + b * gradiente).astype(np.uint8)
        imagen = Image.fromarray(np.broadcast_to(pixeles, (alto, ancho, 3)).copy())
        dibujo = ImageDraw.Draw(imagen)
        dibujo.text((24, 24), "Imagen simulada", fill=(255, 255, 255))
        dibujo.text((24, alto - 60), str(kwargs.get("prompt", ""))[:110], fill=(255, 255, 255))
        return _SalidaImagen(imagen)


class ImagenSimulada:
    nombre = "simulado"

    def cargar(self, cfg: ImageConfig) -> _PipeSimulado:
        return _PipeSimulado()

    def preparar_ip_adapter(self, pipe: Any, cfg: ImageConfig, referencia: Image.Image) -> Any:
        return "embeds_simulados"

    def generador(self, seed: int) -> int:
        return seed

    def es_oom(self, exc: BaseException) -> bool:
        return False

    def liberar(self) -> None:
        return None

    def info(self) -> dict[str, Any]:
        return {"backend": self.nombre}


class VozSimulada:
    nombre = "simulado"

    def cargar(self) -> None:
        return None

    def sintetizar(self, texto: str) -> tuple[np.ndarray, int]:
        n = max(FRECUENCIA_VOZ, int(len(texto) * SEGUNDOS_POR_CARACTER * FRECUENCIA_VOZ))
        t = np.arange(n) / FRECUENCIA_VOZ
        silabas = (np.sin(2 * np.pi * 4 * t) > -0.2).astype(np.float32)  # habla y pausas
        tono = np.sin(2 * np.pi * (180 + 30 * np.sin(2 * np.pi * 3 * t)) * t)
        return (0.3 * tono * silabas).astype(np.float32), FRECUENCIA_VOZ

    def liberar(self) -> None:
        return None

    def info(self) -> dict[str, Any]:
        return {"backend": self.nombre, "voz": "simulada"}


def dependencias_simuladas() -> Dependencias:
    return Dependencias(
        escribir=escribir_simulado,
        backend_imagen=ImagenSimulada(),
        backend_voz=VozSimulada(),
        fabrica_sonido=lambda _nombre: ProceduralBackend(),
    )
