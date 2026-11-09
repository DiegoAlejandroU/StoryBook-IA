"""Acceso a los pesos descargados: rutas locales, variantes y selección de archivos.

En ejecución todo es offline (``local_files_only``); si falta un modelo, el error indica
el comando de instalación en lugar de intentar descargarlo.
"""

from __future__ import annotations

import os
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


def cache_repo_dir(repo_id: str) -> Path:
    """Carpeta del repo en la caché de Hugging Face (``<HF_HOME>/hub/models--org--nombre``)."""
    raiz = Path(os.environ.get("HF_HUB_CACHE") or (config.HF_HOME_DIR / "hub"))
    return raiz / ("models--" + repo_id.replace("/", "--"))


def local_snapshot(repo_id: str, revision: str = "main") -> Path:
    """Ruta local del snapshot de un repo de Hugging Face, sin usar la red.

    No usa ``snapshot_download(local_files_only=True)``: desde huggingface_hub 2.x esa función
    compara el snapshot con el listado completo del repositorio y rechaza las descargas
    parciales, y aquí se descargan a propósito solo los archivos necesarios (fp16, sin
    safety checker). Se resuelve con la estructura documentada de la caché:
    ``refs/<revision>`` -> ``snapshots/<commit>``.
    """
    carpeta = cache_repo_dir(repo_id)
    ref = carpeta / "refs" / revision
    if ref.is_file():
        snapshot = carpeta / "snapshots" / ref.read_text(encoding="utf-8").strip()
        if snapshot.is_dir() and any(snapshot.iterdir()):
            return snapshot
    raise ModelNotDownloadedError(
        f"'{repo_id}' no está descargado en {config.HF_HOME_DIR}. Ejecuta: {_COMANDO_DESCARGA}"
    )


def lora_weight_name(snapshot: Path) -> str:
    """Archivo de pesos de un repo LoRA (prefiere ``pytorch_lora_weights.safetensors``)."""
    preferido = snapshot / "pytorch_lora_weights.safetensors"
    if preferido.is_file():
        return preferido.name
    candidatos = sorted(p.name for p in snapshot.glob("*.safetensors"))
    if not candidatos:
        raise ModelNotDownloadedError(f"No hay pesos .safetensors en {snapshot}")
    return candidatos[0]


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
