"""Persistencia de historias: ``outputs/<run_id>/`` con la Bible, los medios y el manifest.

Estructura de una ejecución (CLAUDE.md §8)::

    outputs/<run_id>/
        story.json                 Story Bible final (con seeds)
        manifest.json              modelos, seeds, parámetros, hardware, tiempos, fallbacks
        scene_N.png                ilustración de la escena N (y character_sheet.png)
        voice_N.wav                narración
        sfx_N.wav                  clip de sonido tal como salió del backend
        ambience_N.wav             ambiente ajustado a la voz (sin ducking)
        mix_N.wav                  voz + ambiente con ducking

``manifest.json`` lleva ``"tipo": "storybook_historia"``: así ``listar_historias`` distingue
las historias de las carpetas de pruebas (``outputs/f1``, ``outputs/f2``…).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from storybook import config
from storybook.schemas import StoryBible

TIPO_MANIFEST: Final = "storybook_historia"
ARCHIVO_BIBLE: Final = "story.json"
ARCHIVO_MANIFEST: Final = "manifest.json"
NUM_ESCENAS: Final = 5


class StorageError(Exception):
    """Historia inexistente o incompleta."""


def slug(texto: str, maximo: int = 40) -> str:
    """'El faro que se enciende solo' -> 'el_faro_que_se_enciende_solo'."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    limpio = re.sub(r"[^a-z0-9]+", "_", sin_tildes.lower()).strip("_")
    return limpio[:maximo].rstrip("_") or "historia"


def nuevo_run_id(idea: str, ahora: datetime | None = None) -> str:
    return f"{(ahora or datetime.now()):%Y%m%d_%H%M%S}_{slug(idea, 30)}"


def crear_carpeta_run(idea: str, raiz: Path | None = None, ahora: datetime | None = None) -> Path:
    raiz = raiz or config.OUTPUTS_DIR
    base = nuevo_run_id(idea, ahora)
    carpeta = raiz / base
    sufijo = 2
    while carpeta.exists():  # dos historias en el mismo segundo
        carpeta = raiz / f"{base}_{sufijo}"
        sufijo += 1
    carpeta.mkdir(parents=True)
    return carpeta


def guardar_json(ruta: Path, datos: Any) -> None:
    """Escritura atómica: primero a un temporal y luego se reemplaza."""
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2, default=str), "utf-8")
    temporal.replace(ruta)


def guardar_bible(carpeta: Path, bible: StoryBible) -> Path:
    ruta = carpeta / ARCHIVO_BIBLE
    temporal = ruta.with_suffix(".json.tmp")
    temporal.write_text(bible.model_dump_json(indent=2), encoding="utf-8")
    temporal.replace(ruta)
    return ruta


def cargar_bible(carpeta: Path) -> StoryBible:
    ruta = carpeta / ARCHIVO_BIBLE
    if not ruta.is_file():
        raise StorageError(f"No hay {ARCHIVO_BIBLE} en {carpeta}")
    return StoryBible.model_validate_json(ruta.read_text(encoding="utf-8"))


def cargar_manifest(carpeta: Path) -> dict[str, Any]:
    ruta = carpeta / ARCHIVO_MANIFEST
    if not ruta.is_file():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return datos if isinstance(datos, dict) else {}


@dataclass(frozen=True)
class ArchivosEscena:
    imagen: Path | None
    voz: Path | None
    ambiente: Path | None
    mezcla: Path | None

    @property
    def completa(self) -> bool:
        return all((self.imagen, self.voz, self.ambiente or self.mezcla))


def _si_existe(ruta: Path) -> Path | None:
    return ruta if ruta.is_file() else None


# Las historias de outputs/ guardan WAV; las de samples/ (versionadas en git) usan OGG Vorbis,
# unas 10 veces más livianas (ver exportar_muestra).
EXTENSIONES_AUDIO: Final = (".wav", ".ogg")


def _audio(carpeta: Path, base: str) -> Path | None:
    for extension in EXTENSIONES_AUDIO:
        ruta = carpeta / f"{base}{extension}"
        if ruta.is_file():
            return ruta
    return None


def archivos_escena(carpeta: Path, numero: int) -> ArchivosEscena:
    return ArchivosEscena(
        imagen=_si_existe(carpeta / f"scene_{numero}.png"),
        voz=_audio(carpeta, f"voice_{numero}"),
        ambiente=_audio(carpeta, f"ambience_{numero}") or _audio(carpeta, f"sfx_{numero}"),
        mezcla=_audio(carpeta, f"mix_{numero}"),
    )


def exportar_muestra(carpeta: Path, destino: Path | None = None) -> Path:
    """Copia una historia a ``samples/`` para versionarla: Bible, manifest, imágenes y los
    audios de narración, ambiente y mezcla convertidos a OGG Vorbis.

    En WAV una historia pesa ~55 MB; en OGG, unos 6-8 MB. Los clips ``sfx_N`` (intermedios)
    no se copian.
    """
    import shutil

    destino = (destino or config.SAMPLES_DIR) / carpeta.name
    destino.mkdir(parents=True, exist_ok=True)
    for nombre in (ARCHIVO_BIBLE, ARCHIVO_MANIFEST, "character_sheet.png"):
        if (carpeta / nombre).is_file():
            shutil.copy2(carpeta / nombre, destino / nombre)
    for numero in range(1, NUM_ESCENAS + 1):
        imagen = carpeta / f"scene_{numero}.png"
        if imagen.is_file():
            shutil.copy2(imagen, destino / imagen.name)
        for base in (f"voice_{numero}", f"ambience_{numero}", f"mix_{numero}"):
            wav = carpeta / f"{base}.wav"
            if wav.is_file():
                _wav_a_ogg(wav, destino / f"{base}.ogg")
    return destino


# Se escribe por bloques: en Windows, escribir un OGG largo de una sola vez desborda la pila
# del codificador Vorbis de libsndfile (el proceso terminó con 0xC00000FD en la tarea 5.4).
BLOQUE_OGG: Final = 16_384


def _wav_a_ogg(origen: Path, destino: Path) -> None:
    import soundfile as sf

    with (
        sf.SoundFile(str(origen)) as entrada,
        sf.SoundFile(
            str(destino),
            "w",
            samplerate=entrada.samplerate,
            channels=entrada.channels,
            format="OGG",
            subtype="VORBIS",
        ) as salida,
    ):
        for bloque in entrada.blocks(blocksize=BLOQUE_OGG, dtype="float32"):
            salida.write(bloque)


@dataclass
class HistoriaGuardada:
    carpeta: Path
    bible: StoryBible
    manifest: dict[str, Any]

    @property
    def run_id(self) -> str:
        return self.carpeta.name

    @property
    def titulo(self) -> str:
        return self.bible.titulo

    def escena(self, numero: int) -> ArchivosEscena:
        return archivos_escena(self.carpeta, numero)

    @property
    def completa(self) -> bool:
        return all(self.escena(n).completa for n in range(1, NUM_ESCENAS + 1))


def cargar_historia(carpeta: Path) -> HistoriaGuardada:
    return HistoriaGuardada(carpeta, cargar_bible(carpeta), cargar_manifest(carpeta))


@dataclass(frozen=True)
class EntradaHistoria:
    carpeta: Path
    titulo: str
    genero: str
    fecha: str
    origen: str  # "outputs" o "samples"
    perfil: str


def listar_historias(raices: list[Path] | None = None) -> list[EntradaHistoria]:
    """Historias guardadas (las de ``outputs/`` y ``samples/``), las más recientes primero."""
    raices = raices or [config.OUTPUTS_DIR, config.SAMPLES_DIR]
    entradas: list[EntradaHistoria] = []
    for raiz in raices:
        if not raiz.is_dir():
            continue
        for carpeta in raiz.iterdir():
            manifest = cargar_manifest(carpeta) if carpeta.is_dir() else {}
            if manifest.get("tipo") != TIPO_MANIFEST or not (carpeta / ARCHIVO_BIBLE).is_file():
                continue
            entradas.append(
                EntradaHistoria(
                    carpeta=carpeta,
                    titulo=str(manifest.get("titulo") or carpeta.name),
                    genero=str(manifest.get("genero", "")),
                    fecha=str(manifest.get("creado", "")),
                    origen=raiz.name,
                    perfil=str(manifest.get("perfil", "")),
                )
            )
    return sorted(entradas, key=lambda e: e.fecha, reverse=True)
