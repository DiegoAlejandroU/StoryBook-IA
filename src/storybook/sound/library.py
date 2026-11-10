"""Biblioteca local de sonidos (fallback B): clips CC0 de ``assets/sfx/`` indexados por etiqueta.

El índice es ``assets/sfx/index.json``::

    {"clips": [
        {"archivo": "rain_light.wav", "etiquetas": ["rain"], "licencia": "CC0",
         "fuente": "https://...", "autor": "..."}
    ]}

Solo se aceptan clips con licencia CC0 y archivo presente; el resto se ignora con un aviso
(su procedencia debe constar también en ``AUDIO_LICENSES.md``). Sin índice, la biblioteca
está vacía y la cadena de sonido pasa a la síntesis procedural.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import soundfile as sf

from storybook import config
from storybook.logging_utils import get_logger, kv

logger = get_logger(__name__)

NOMBRE_INDICE: Final = "index.json"
LICENCIAS_ACEPTADAS: Final = frozenset({"cc0", "cc0-1.0", "cc0 1.0"})


@dataclass(frozen=True)
class ClipBiblioteca:
    ruta: Path
    etiquetas: tuple[str, ...]
    licencia: str
    fuente: str
    autor: str

    def a_dict(self) -> dict[str, object]:
        return {
            "archivo": self.ruta.name,
            "etiquetas": list(self.etiquetas),
            "licencia": self.licencia,
            "fuente": self.fuente,
            "autor": self.autor,
        }


class BibliotecaSonidos:
    def __init__(self, raiz: Path | None = None) -> None:
        self.raiz = raiz or config.ASSETS_SFX_DIR
        self.clips: list[ClipBiblioteca] = self._cargar_indice()

    def _cargar_indice(self) -> list[ClipBiblioteca]:
        indice = self.raiz / NOMBRE_INDICE
        if not indice.is_file():
            return []
        try:
            entradas = json.loads(indice.read_text(encoding="utf-8")).get("clips", [])
        except (json.JSONDecodeError, AttributeError) as exc:
            logger.warning("biblioteca_indice_invalido", extra=kv(error=str(exc)))
            return []
        clips: list[ClipBiblioteca] = []
        for entrada in entradas:
            try:
                ruta = self.raiz / str(entrada["archivo"])
                licencia = str(entrada["licencia"])
                etiquetas = tuple(str(e) for e in entrada["etiquetas"])
            except (KeyError, TypeError):
                logger.warning("biblioteca_entrada_invalida", extra=kv(entrada=str(entrada)))
                continue
            if licencia.strip().lower() not in LICENCIAS_ACEPTADAS:
                logger.warning("biblioteca_licencia_rechazada", extra=kv(archivo=ruta.name))
                continue
            if not ruta.is_file():
                logger.warning("biblioteca_archivo_faltante", extra=kv(archivo=ruta.name))
                continue
            clips.append(
                ClipBiblioteca(
                    ruta=ruta,
                    etiquetas=etiquetas,
                    licencia=licencia,
                    fuente=str(entrada.get("fuente", "")),
                    autor=str(entrada.get("autor", "")),
                )
            )
        return clips

    def buscar(self, etiquetas: Sequence[str], seed: int = 0) -> ClipBiblioteca | None:
        """Clip de la primera etiqueta (en orden de prioridad) que tenga alguno.

        Si varios clips sirven, ``seed`` elige uno de forma reproducible.
        """
        for etiqueta in etiquetas:
            candidatos = [c for c in self.clips if str(etiqueta) in c.etiquetas]
            if candidatos:
                return candidatos[seed % len(candidatos)]
        return None


def cargar_audio_mono(ruta: Path) -> tuple[np.ndarray, int]:
    """WAV/FLAC/OGG -> (mono float32, frecuencia)."""
    datos, frecuencia = sf.read(str(ruta), dtype="float32", always_2d=True)
    return datos.mean(axis=1).astype(np.float32), int(frecuencia)
