"""Acceso a los pesos descargados: rutas locales, variantes y selección de archivos.

En ejecución todo es offline (``local_files_only``); si falta un modelo, el error indica
el comando de instalación en lugar de intentar descargarlo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from storybook import config

_PATRON_VOZ_PIPER = re.compile(
    r"^(?P<familia>[a-z]{2,3})_(?P<region>[A-Z]{2})-(?P<nombre>[^-]+)-(?P<calidad>.+)$"
)
_COMPONENTES_DIFFUSERS = (
    "scheduler",
    "text_encoder",
    "text_encoder_2",
    "tokenizer",
    "tokenizer_2",
    "unet",
    "transformer",
    "vae",
    "feature_extractor",
    "projection_model",
    "duration_embedder",
)
_EXT_CONFIG = (".json", ".txt", ".model", ".tiktoken")
_COMANDO_DESCARGA = "uv run python scripts/download_models.py"


class ModelNotDownloadedError(FileNotFoundError):
    """El modelo no está en la caché local."""


def local_snapshot(repo_id: str) -> Path:
    """Ruta local del snapshot de un repo de Hugging Face, sin usar la red."""
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        return Path(snapshot_download(repo_id, local_files_only=True))
    except LocalEntryNotFoundError as exc:
        raise ModelNotDownloadedError(
            f"'{repo_id}' no está descargado en {config.HF_HOME_DIR}. Ejecuta: {_COMANDO_DESCARGA}"
        ) from exc


def is_diffusers_repo(snapshot: Path) -> bool:
    return (snapshot / "model_index.json").is_file()


def diffusers_variant(snapshot: Path) -> str | None:
    """'fp16' si el snapshot trae pesos ``*.fp16.safetensors``; si no, None."""
    return "fp16" if any(snapshot.glob("*/*.fp16.safetensors")) else None


def seleccionar_archivos_diffusers(archivos: list[str]) -> list[str]:
    """Elige el mínimo de archivos de un repo diffusers.

    * Incluye ``model_index.json`` y los configs/tokenizers de cada componente.
    * Por componente, prefiere ``*.fp16.safetensors``; si no existen, ``*.safetensors``;
      ``.bin`` solo si el componente no tiene safetensors.
    * Excluye pesos en la raíz (formatos originales de un solo archivo) y el
      ``safety_checker`` (se omite para ahorrar ~600 MB de VRAM; ver informe, ética).
    """
    seleccion = ["model_index.json"] if "model_index.json" in archivos else []
    for componente in _COMPONENTES_DIFFUSERS:
        propios = [a for a in archivos if a.startswith(f"{componente}/")]
        if not propios:
            continue
        seleccion += [a for a in propios if a.endswith(_EXT_CONFIG)]
        fp16 = [a for a in propios if a.endswith(".fp16.safetensors")]
        normales = [
            a for a in propios if a.endswith(".safetensors") and not a.endswith(".fp16.safetensors")
        ]
        binarios = [a for a in propios if a.endswith(".bin") and ".fp16." not in a]
        seleccion += fp16 or normales or binarios
    return sorted(set(seleccion))


@dataclass(frozen=True)
class PiperVoiceFiles:
    onnx: Path
    config: Path
    model_card: Path

    def existen(self) -> bool:
        return self.onnx.is_file() and self.config.is_file()


def piper_repo_subpath(voz: str) -> str:
    """'es_MX-claude-high' -> 'es/es_MX/claude/high' (estructura de rhasspy/piper-voices)."""
    coincidencia = _PATRON_VOZ_PIPER.match(voz)
    if coincidencia is None:
        raise ValueError(f"Nombre de voz Piper inválido: {voz} (formato: es_MX-nombre-calidad)")
    familia, region = coincidencia["familia"], coincidencia["region"]
    return f"{familia}/{familia}_{region}/{coincidencia['nombre']}/{coincidencia['calidad']}"


def piper_voice_files(voz: str) -> PiperVoiceFiles:
    carpeta = config.PIPER_DIR / piper_repo_subpath(voz)
    return PiperVoiceFiles(
        onnx=carpeta / f"{voz}.onnx",
        config=carpeta / f"{voz}.onnx.json",
        model_card=carpeta / "MODEL_CARD",
    )


def require_piper_voice(voz: str) -> PiperVoiceFiles:
    archivos = piper_voice_files(voz)
    if not archivos.existen():
        raise ModelNotDownloadedError(
            f"La voz Piper '{voz}' no está en {archivos.onnx.parent}. Ejecuta: {_COMANDO_DESCARGA}"
        )
    return archivos
