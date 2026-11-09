"""Descarga de todos los pesos y recursos (ÚNICO paso que usa Internet).

Descarga en ``models/`` (fuera de git) los modelos de los perfiles indicados y registra
repo, revisión (commit), licencia declarada y tamaño en ``docs/models_registry.json``,
que es la base de MODELS.md.

Requisitos previos:
  * Ollama abierto (para descargar el LLM).
  * Para Stable Audio (licencia gated): aceptar la licencia en la página del modelo con tu
    cuenta de Hugging Face y poner HF_TOKEN en .env.

Uso (PowerShell):
    uv run python scripts/download_models.py                      # rapido + calidad
    uv run python scripts/download_models.py --profiles rapido    # solo lo de la demo
    uv run python scripts/download_models.py --only image voice   # por modalidad
    uv run python scripts/download_models.py --skip-gated         # sin Stable Audio
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

os.environ["STORYBOOK_ONLINE"] = "1"  # debe ir ANTES de importar storybook.config

from storybook import config
from storybook.hub import piper_repo_subpath, seleccionar_archivos_diffusers
from storybook.logging_utils import get_logger, kv, setup_logging
from storybook.story.llm_client import LLMError, OllamaClient

log = get_logger("download_models")
MODALIDADES = ("llm", "image", "voice", "sound", "eval")
REGISTRO = config.DOCS_DIR / "models_registry.json"
PIPER_REPO = "rhasspy/piper-voices"
KOKORO_REPO = "hexgrad/Kokoro-82M"


@dataclass
class Entrada:
    repo_id: str
    modalidad: str
    estado: str = "pendiente"
    revision: str | None = None
    licencia: str | None = None
    gated: Any = None
    tamano_mb: float | None = None
    archivos: int = 0
    nota: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _token() -> str | None:
    return os.environ.get("HF_TOKEN") or None


def _tamano_mb(ruta: Path) -> float:
    total = sum(p.stat().st_size for p in ruta.rglob("*") if p.is_file())
    return round(total / 1024**2, 1)


def _metadatos(entrada: Entrada) -> None:
    from huggingface_hub import model_info

    try:
        info = model_info(entrada.repo_id, token=_token())
        entrada.revision = info.sha
        entrada.gated = info.gated
        card = info.card_data
        entrada.licencia = (card.get("license") if card else None) or entrada.licencia
        if card and card.get("license_name"):
            entrada.licencia = f"{entrada.licencia} ({card.get('license_name')})"
    except Exception as exc:
        log.warning("metadatos_no_disponibles", extra=kv(repo=entrada.repo_id, error=str(exc)))


def _manejar_error(entrada: Entrada, exc: Exception) -> None:
    from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

    if isinstance(exc, GatedRepoError):
        entrada.estado = "gated_sin_acceso"
        entrada.nota = (
            f"Acepta la licencia en https://huggingface.co/{entrada.repo_id} con tu cuenta, "
            "verifica HF_TOKEN en .env y vuelve a ejecutar."
        )
    elif isinstance(exc, RepositoryNotFoundError):
        entrada.estado = "no_encontrado"
        entrada.nota = "El repositorio no existe o requiere token."
    else:
        entrada.estado = "error"
        entrada.nota = f"{type(exc).__name__}: {exc}"
    log.error(
        "descarga_fallida", extra=kv(repo=entrada.repo_id, estado=entrada.estado, nota=entrada.nota)
    )


def descargar_diffusers(repo_id: str, modalidad: str, opcional: bool = False) -> Entrada:
    """Pipeline en formato diffusers con el mínimo de archivos (prefiere fp16)."""
    from huggingface_hub import list_repo_files, snapshot_download

    entrada = Entrada(repo_id, modalidad)
    try:
        archivos = list_repo_files(repo_id, token=_token())
        if "model_index.json" not in archivos:
            entrada.estado = "formato_no_soportado"
            entrada.nota = "El repo no está en formato diffusers (sin model_index.json)."
            nivel = log.warning if opcional else log.error
            nivel("repo_no_diffusers", extra=kv(repo=repo_id))
            return entrada
        seleccion = seleccionar_archivos_diffusers(archivos)
        log.info("descargando", extra=kv(repo=repo_id, archivos=len(seleccion)))
        ruta = Path(snapshot_download(repo_id, allow_patterns=seleccion, token=_token()))
        entrada.estado = "ok"
        entrada.archivos = len(seleccion)
        entrada.tamano_mb = _tamano_mb(ruta)
        entrada.extra["variante"] = "fp16" if any(".fp16." in a for a in seleccion) else "fp32"
    except Exception as exc:
        _manejar_error(entrada, exc)
    _metadatos(entrada)
    return entrada


def descargar_patrones(repo_id: str, modalidad: str, patrones: list[str]) -> Entrada:
    from huggingface_hub import snapshot_download

    entrada = Entrada(repo_id, modalidad)
    try:
        log.info("descargando", extra=kv(repo=repo_id, patrones=patrones))
        ruta = Path(snapshot_download(repo_id, allow_patterns=patrones, token=_token()))
        entrada.estado = "ok"
        entrada.archivos = sum(1 for p in ruta.rglob("*") if p.is_file())
        entrada.tamano_mb = _tamano_mb(ruta)
    except Exception as exc:
        _manejar_error(entrada, exc)
    _metadatos(entrada)
    return entrada


def descargar_ip_adapter(perfil: config.AppConfig) -> Entrada:
    from huggingface_hub import list_repo_files

    ip = perfil.image.ip_adapter
    try:
        archivos = list_repo_files(ip.repo_id, token=_token())
    except Exception as exc:
        entrada = Entrada(ip.repo_id, "image")
        _manejar_error(entrada, exc)
        return entrada
    peso = f"{ip.subfolder}/{ip.weight_name}"
    if peso not in archivos:
        alternativo = peso.replace(".safetensors", ".bin")
        if alternativo not in archivos:
            entrada = Entrada(ip.repo_id, "image", estado="error", nota=f"No existe {peso}")
            log.error("ip_adapter_sin_pesos", extra=kv(peso=peso))
            return entrada
        log.warning(
            "ip_adapter_usa_bin",
            extra=kv(
                peso=alternativo,
                accion="cambia image.ip_adapter.weight_name en configs/default.yaml",
            ),
        )
        peso = alternativo
    encoder = [
        a
        for a in archivos
        if a.startswith(f"{ip.image_encoder_subfolder}/")
        and (a.endswith(".json") or a.endswith(".safetensors"))
    ]
    entrada = descargar_patrones(ip.repo_id, "image", [peso, *encoder])
    entrada.extra["peso"] = peso
    return entrada


def descargar_piper(voz: str) -> Entrada:
    from huggingface_hub import hf_hub_download

    entrada = Entrada(f"{PIPER_REPO}:{voz}", "voice")
    subruta = piper_repo_subpath(voz)
    try:
        for nombre in (f"{voz}.onnx", f"{voz}.onnx.json", "MODEL_CARD"):
            hf_hub_download(
                PIPER_REPO, f"{subruta}/{nombre}", local_dir=config.PIPER_DIR, token=_token()
            )
        carpeta = config.PIPER_DIR / subruta
        entrada.estado = "ok"
        entrada.archivos = 3
        entrada.tamano_mb = _tamano_mb(carpeta)
        tarjeta = (carpeta / "MODEL_CARD").read_text(encoding="utf-8", errors="ignore")
        entrada.extra["model_card"] = tarjeta[:1500]
        entrada.nota = "Revisar licencia del dataset en MODEL_CARD (código Piper: GPL-3.0)."
        log.info("piper_model_card", extra=kv(voz=voz, extracto=tarjeta[:300].replace("\n", " ")))
    except Exception as exc:
        _manejar_error(entrada, exc)
    entrada.licencia = "voz: ver MODEL_CARD; código piper-tts: GPL-3.0-or-later"
    return entrada


def descargar_open_clip(perfil: config.AppConfig) -> Entrada:
    entrada = Entrada(
        f"open_clip:{perfil.evaluation.clip_model}/{perfil.evaluation.clip_pretrained}", "eval"
    )
    try:
        import open_clip

        open_clip.create_model_and_transforms(
            perfil.evaluation.clip_model, pretrained=perfil.evaluation.clip_pretrained
        )
        entrada.estado = "ok"
        entrada.licencia = "MIT (open_clip y pesos LAION)"
    except Exception as exc:
        _manejar_error(entrada, exc)
    return entrada


def descargar_llm(modelos: list[str], host: str) -> list[Entrada]:
    entradas: list[Entrada] = []
    try:
        with OllamaClient(host, timeout_s=30) as cliente:
            for modelo in modelos:
                entrada = Entrada(f"ollama:{modelo}", "llm", licencia="Apache-2.0 (Qwen3)")
                try:
                    if cliente.has_model(modelo):
                        entrada.estado = "ok"
                        entrada.nota = "ya estaba descargado"
                    else:
                        cliente.pull(modelo)
                        entrada.estado = "ok"
                except LLMError as exc:
                    entrada.estado = "error"
                    entrada.nota = str(exc)
                entradas.append(entrada)
    except LLMError as exc:
        log.error("ollama_no_disponible", extra=kv(error=str(exc)))
        entradas.extend(Entrada(f"ollama:{m}", "llm", "error", nota=str(exc)) for m in modelos)
    return entradas


# ---------------------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Descarga de modelos de StoryBook")
    parser.add_argument("--profiles", nargs="+", default=["rapido", "calidad"])
    parser.add_argument("--only", nargs="+", choices=MODALIDADES, default=list(MODALIDADES))
    parser.add_argument(
        "--skip-gated", action="store_true", help="Omitir Stable Audio (AudioLDM sí se descarga)"
    )
    parser.add_argument("--with-kokoro", action="store_true", help="Voces Kokoro (experimento)")
    args = parser.parse_args()

    setup_logging()
    perfiles = [config.load_config(p) for p in args.profiles]
    base = perfiles[0]
    if not _token():
        log.warning("sin_hf_token", extra=kv(efecto="los modelos gated (Stable Audio) fallarán"))

    entradas: list[Entrada] = []
    if "llm" in args.only:
        modelos = sorted({p.llm.model for p in perfiles})
        entradas += descargar_llm(modelos, base.llm.host)

    if "image" in args.only:
        for repo in sorted({p.image.model_id for p in perfiles}):
            entradas.append(descargar_diffusers(repo, "image"))
        entradas.append(
            descargar_patrones(base.image.lcm_lora_id, "image", ["*.safetensors", "*.json"])
        )
        entradas.append(descargar_ip_adapter(base))

    if "voice" in args.only:
        for voz in sorted({p.voice.piper_voice for p in perfiles}):
            entradas.append(descargar_piper(voz))
        if args.with_kokoro:
            patrones = ["config.json", "*.pth", f"voices/{base.voice.kokoro_voice}.pt"]
            entradas.append(descargar_patrones(KOKORO_REPO, "voice", patrones))

    if "sound" in args.only:
        backends = {b for p in perfiles for b in p.sound.backends}
        if not args.skip_gated:
            if "sa3" in backends:
                entradas.append(descargar_diffusers(base.sound.sa3_repo_id, "sound", opcional=True))
            if "sao" in backends:
                entradas.append(descargar_diffusers(base.sound.sao_repo_id, "sound", opcional=True))
        if "audioldm" in backends:
            # No es gated: se descarga aunque falte HF_TOKEN (sonido generativo garantizado).
            entradas.append(
                descargar_diffusers(base.sound.audioldm_repo_id, "sound", opcional=True)
            )

    if "eval" in args.only:
        entradas.append(descargar_patrones(base.evaluation.whisper_repo_id, "eval", ["*"]))
        entradas.append(descargar_open_clip(base))

    # Registro acumulativo (no se pierde lo descargado en ejecuciones anteriores).
    registro: dict[str, Any] = {}
    if REGISTRO.is_file():
        registro = json.loads(REGISTRO.read_text(encoding="utf-8"))
    marca = datetime.now().isoformat(timespec="seconds")
    for entrada in entradas:
        registro[entrada.repo_id] = {**asdict(entrada), "actualizado": marca}
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    REGISTRO.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")

    for entrada in entradas:
        log.info(
            "resumen",
            extra=kv(
                repo=entrada.repo_id,
                estado=entrada.estado,
                mb=entrada.tamano_mb,
                licencia=entrada.licencia,
            ),
        )
    errores_criticos = [e for e in entradas if e.estado != "ok" and e.modalidad != "sound"]
    log.info(
        "descarga_fin",
        extra=kv(total=len(entradas), criticos=len(errores_criticos), registro=str(REGISTRO)),
    )
    return 1 if errores_criticos else 0


if __name__ == "__main__":
    sys.exit(main())
