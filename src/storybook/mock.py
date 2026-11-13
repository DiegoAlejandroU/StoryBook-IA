"""Dependencias simuladas: el pipeline completo sin GPU, Ollama ni modelos descargados.

Sirven para probar la UI (``StoryBook.cmd mock`` o ``streamlit run app/streamlit_app.py --
--mock``), para ``scripts/verify_offline.py`` y para los tests. El texto es siempre la misma
historia de ejemplo (generada de verdad en F1), las imágenes son tarjetas de color con el
número de escena, la voz es un tono modulado de duración proporcional al texto y el sonido es
la síntesis procedural real (CPU). La UI muestra un aviso de "modo simulado".
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Final

import numpy as np
from PIL import Image, ImageDraw

from storybook.config import ImageConfig, LLMConfig
from storybook.pipeline import Dependencias
from storybook.schemas import PlanEscena, PlanHistoria, StoryBible, StoryRequest
from storybook.sound.generator import ProceduralBackend
from storybook.story.llm_client import ChatResult, GeneracionValidada

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


class LLMSimulado:
    """LLM para la generación por escenas: el plan y las escenas de la historia de ejemplo.

    ``demora_s`` simula el tiempo de cada llamada (variable ``STORYBOOK_MOCK_DEMORA``) para
    ver en la interfaz cómo aparecen las escenas de a una.
    """

    def __init__(self, demora_s: float = 0.0) -> None:
        self.demora_s = demora_s
        self.bible = StoryBible.model_validate_json(HISTORIA_EJEMPLO.read_text(encoding="utf-8"))
        self.escritas = 0
        self.descargas = 0

    def _plan(self) -> PlanHistoria:
        b = self.bible
        hechos_escenas = {h for e in b.escenas for h in e.hechos_nuevos}
        return PlanHistoria(
            titulo=b.titulo,
            genero=b.genero,
            tono=b.tono,
            estilo_visual=b.estilo_visual,
            escenario=b.escenario,
            personajes=b.personajes,
            plan_escenas=[
                PlanEscena(
                    numero=e.numero,
                    fase=e.fase,
                    resumen=e.resumen,
                    personajes_presentes=list(e.personajes_presentes),
                )
                for e in b.escenas
            ],
            canon_inicial=[h for h in b.canon if h not in hechos_escenas],
        )

    def generar_validado(self, *, modelo_salida: type[Any], **_: Any) -> GeneracionValidada[Any]:
        if self.demora_s:
            time.sleep(self.demora_s)
        if modelo_salida is PlanHistoria:
            objeto: Any = self._plan()
        else:
            self.escritas = self.escritas % len(self.bible.escenas) + 1
            objeto = self.bible.escena(self.escritas).model_copy(deep=True)
        resultado = ChatResult(
            content=objeto.model_dump_json(),
            model="simulado",
            prompt_tokens=0,
            output_tokens=0,
            total_s=self.demora_s,
            load_s=0.0,
            eval_s=self.demora_s,
            done_reason="stop",
        )
        return GeneracionValidada(objeto=objeto, intentos=1, resultado=resultado)

    def unload(self, modelo: str) -> None:
        self.descargas += 1


def demora_simulada() -> float:
    try:
        return max(0.0, float(os.environ.get("STORYBOOK_MOCK_DEMORA", "0") or 0))
    except ValueError:
        return 0.0


def dependencias_simuladas(demora_s: float | None = None) -> Dependencias:
    return Dependencias(
        escribir=escribir_simulado,
        backend_imagen=ImagenSimulada(),
        backend_voz=VozSimulada(),
        fabrica_sonido=lambda _nombre: ProceduralBackend(),
        llm=LLMSimulado(demora_simulada() if demora_s is None else demora_s),
    )
