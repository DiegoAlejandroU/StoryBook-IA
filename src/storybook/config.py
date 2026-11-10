"""Configuración central de StoryBook: rutas, entorno offline y perfiles YAML.

IMPORTANTE: este módulo debe importarse ANTES que ``huggingface_hub``, ``transformers``,
``diffusers``, ``open_clip`` o ``faster_whisper``. Esas librerías leen ``HF_HOME`` y las
variables ``*_OFFLINE`` en el momento de importarse; si se fijan después, no tienen efecto.

Por defecto todo arranca en modo offline (requisito del enunciado). Solo
``scripts/download_models.py`` activa el modo en línea, fijando ``STORYBOOK_ONLINE=1``
antes de importar este módulo.
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------------------
# Rutas del proyecto (siempre relativas a la raíz del repositorio, nunca absolutas)
# ---------------------------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
CONFIGS_DIR: Path = PROJECT_ROOT / "configs"
MODELS_DIR: Path = PROJECT_ROOT / "models"
HF_HOME_DIR: Path = MODELS_DIR / "hf"
PIPER_DIR: Path = MODELS_DIR / "piper"
OUTPUTS_DIR: Path = PROJECT_ROOT / "outputs"
DOCS_DIR: Path = PROJECT_ROOT / "docs"
ASSETS_SFX_DIR: Path = PROJECT_ROOT / "assets" / "sfx"
SAMPLES_DIR: Path = PROJECT_ROOT / "samples"

ONLINE_ENV_VAR = "STORYBOOK_ONLINE"
PROFILE_ENV_VAR = "STORYBOOK_PROFILE"
OFFLINE_ENV_VARS: tuple[str, ...] = (
    "HF_HUB_OFFLINE",
    "TRANSFORMERS_OFFLINE",
    "HF_DATASETS_OFFLINE",
)
_LIBS_SENSIBLES: tuple[str, ...] = (
    "huggingface_hub",
    "transformers",
    "diffusers",
    "open_clip",
    "faster_whisper",
)


class ConfigError(Exception):
    """Error al cargar o validar la configuración YAML."""


def _bootstrap_environment() -> None:
    """Fija caché de Hugging Face, modo offline y telemetría desactivada."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    importadas = [lib for lib in _LIBS_SENSIBLES if lib in sys.modules]
    if importadas:
        warnings.warn(
            "storybook.config se importó después de "
            f"{importadas}; HF_HOME y el modo offline pueden no aplicarse.",
            RuntimeWarning,
            stacklevel=3,
        )

    HF_HOME_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(HF_HOME_DIR)

    flag = "0" if is_online_mode() else "1"
    for var in OFFLINE_ENV_VARS:
        os.environ[var] = flag

    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "0")
    os.environ.setdefault("DO_NOT_TRACK", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def is_online_mode() -> bool:
    """True solo durante la instalación/descarga de modelos."""
    return os.environ.get(ONLINE_ENV_VAR, "0") == "1"


def is_offline() -> bool:
    """True si las librerías de Hugging Face están forzadas a no usar la red."""
    return all(os.environ.get(var) == "1" for var in OFFLINE_ENV_VARS)


_bootstrap_environment()


# ---------------------------------------------------------------------------------------
# Esquema tipado de la configuración (valida los YAML al cargarlos)
# ---------------------------------------------------------------------------------------
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LLMConfig(_Strict):
    host: str = "http://localhost:11434"
    model: str
    think: bool | None = Field(
        default=False,
        description="False desactiva el razonamiento (Qwen3). None no envía el parámetro.",
    )
    num_ctx: int = Field(default=8192, ge=2048, le=32768)
    num_predict: int = Field(
        default=4096,
        ge=256,
        le=16384,
        description="Tope de tokens generados: evita bucles infinitos (p. ej. espacios en JSON).",
    )
    temperature_narrativa: float = Field(default=0.7, ge=0.0, le=2.0)
    temperature_auditor: float = Field(default=0.2, ge=0.0, le=2.0)
    max_reintentos: int = Field(default=3, ge=0, le=10)
    seed: int = 42
    timeout_s: float = Field(default=600.0, gt=0)
    keep_alive_etapa: str = "5m"
    # Muestreo recomendado por Qwen3-Instruct-2507 (top_p 0.8, top_k 20) y penalización de
    # presencia para evitar bucles de repetición (en F0 el 4B repitió una frase hasta agotar
    # num_predict). None = no se envía la opción.
    top_p: float | None = Field(default=0.8, ge=0.0, le=1.0)
    top_k: int | None = Field(default=20, ge=1, le=200)
    presence_penalty: float | None = Field(default=1.0, ge=0.0, le=2.0)
    repeat_penalty: float | None = Field(default=1.1, ge=1.0, le=2.0)
    num_gpu: int | None = Field(
        default=None,
        ge=0,
        le=999,
        description=(
            "Capas del LLM en GPU (Ollama). None = automático; 99 = todas. Con el 4B, el modo "
            "automático dejó el 72 % en GPU (~11 tok/s) y 99 el 100 % (~21 tok/s, F1)."
        ),
    )
    num_ctx_auditor: int = Field(
        default=8192,
        ge=2048,
        le=32768,
        description="El auditor recibe la Bible completa: necesita más contexto que una escena.",
    )
    # El valor de la clase se mantiene; los perfiles (configs/default.yaml) usan por_etapas.
    estrategia: Literal["una_llamada", "por_etapas"] = Field(
        default="una_llamada",
        description="Planificador: (a) una sola llamada o (b) plan y luego escena por escena.",
    )
    auditar: bool = Field(
        default=True, description="Segunda pasada del LLM que detecta contradicciones."
    )
    max_rondas_auditor: int = Field(
        default=1, ge=0, le=5, description="Rondas de auditoría y regeneración (0 = solo auditar)."
    )

    def opciones_muestreo(self) -> dict[str, float | int]:
        """Opciones extra de Ollama (``options``) para todas las llamadas del LLM."""
        valores: dict[str, float | int | None] = {
            "top_p": self.top_p,
            "top_k": self.top_k,
            "presence_penalty": self.presence_penalty,
            "repeat_penalty": self.repeat_penalty,
            "num_gpu": self.num_gpu,
        }
        return {k: v for k, v in valores.items() if v is not None}


class IPAdapterConfig(_Strict):
    enabled: bool = True
    repo_id: str = "h94/IP-Adapter"
    subfolder: str = "models"
    weight_name: str = "ip-adapter_sd15.safetensors"
    image_encoder_subfolder: str = "models/image_encoder"
    scale: float = Field(default=0.6, ge=0.0, le=1.5)


class ImageConfig(_Strict):
    model_id: str
    scheduler: Literal["lcm", "dpmpp_2m_karras"] = "lcm"
    lcm_lora_id: str = "latent-consistency/lcm-lora-sdv1-5"
    steps: int = Field(default=6, ge=1, le=100)
    guidance_scale: float = Field(default=1.5, ge=0.0, le=20.0)
    width: int = 768
    height: int = 512
    negative_prompt_base: str = ""
    attention_slicing: bool = True
    vae_slicing: bool = True
    cpu_offload: bool = False
    ip_adapter: IPAdapterConfig = IPAdapterConfig()

    @field_validator("width", "height")
    @classmethod
    def _multiplo_de_8(cls, valor: int) -> int:
        if valor % 8 != 0 or not 256 <= valor <= 1024:
            raise ValueError("width/height deben ser múltiplos de 8 entre 256 y 1024")
        return valor


class VoiceConfig(_Strict):
    backend: Literal["piper", "kokoro"] = "piper"
    piper_voice: str = "es_MX-claude-high"
    length_scale: float = Field(default=1.0, gt=0.3, lt=3.0)
    noise_scale: float = Field(default=0.667, ge=0.0, le=1.5)
    noise_w_scale: float = Field(default=0.8, ge=0.0, le=1.5)
    kokoro_voice: str = "ef_dora"
    kokoro_lang_code: str = "e"


SoundBackend = Literal["sa3", "sao", "audioldm", "library", "procedural"]


class SoundConfig(_Strict):
    backends: list[SoundBackend] = Field(
        default_factory=lambda: ["sa3", "sao", "audioldm", "library", "procedural"],
        description="Orden de fallback: el primero que funcione se usa y se registra.",
    )
    sa3_repo_id: str = "stabilityai/stable-audio-3-small-sfx"
    sa3_steps: int | None = None
    sao_repo_id: str = "stabilityai/stable-audio-open-1.0"
    sao_steps: int = Field(default=50, ge=4, le=250)
    sao_guidance: float = Field(default=7.0, ge=0.0, le=15.0)
    # AudioLDM (modelo sugerido en el curso): no es gated, cabe en 4 GB y sale a 16 kHz.
    audioldm_repo_id: str = "cvssp/audioldm"
    audioldm_steps: int = Field(default=25, ge=4, le=200)
    audioldm_guidance: float = Field(default=2.5, ge=0.0, le=15.0)
    duration_s: float = Field(default=8.0, ge=2.0, le=30.0)
    negative_prompt: str = "low quality, speech, voice, singing, music"
    cpu_offload: bool = True


class EvaluationConfig(_Strict):
    whisper_model: str = "small"
    whisper_repo_id: str = "Systran/faster-whisper-small"
    whisper_compute_type: str = "int8"
    whisper_language: str = "es"
    clip_model: str = "ViT-B-32"
    clip_pretrained: str = "laion2b_s34b_b79k"
    cpu_threads: int = Field(default=0, ge=0, le=64)


class ConsistencyConfig(_Strict):
    use_bible: bool = True
    fixed_seed: bool = True
    seed_policy: Literal["compartida", "por_escena"] = "compartida"
    base_seed: int = 1234


class AppConfig(_Strict):
    profile: str
    llm: LLMConfig
    image: ImageConfig
    voice: VoiceConfig = VoiceConfig()
    sound: SoundConfig = SoundConfig()
    evaluation: EvaluationConfig = EvaluationConfig()
    consistency: ConsistencyConfig = ConsistencyConfig()


# ---------------------------------------------------------------------------------------
# Carga de perfiles con herencia ("extends")
# ---------------------------------------------------------------------------------------
def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Mezcla recursiva: los valores de ``override`` reemplazan a los de ``base``."""
    resultado = dict(base)
    for clave, valor in override.items():
        if isinstance(valor, dict) and isinstance(resultado.get(clave), dict):
            resultado[clave] = deep_merge(resultado[clave], valor)
        else:
            resultado[clave] = valor
    return resultado


def _resolver_ruta(nombre_o_ruta: str) -> Path:
    candidato = Path(nombre_o_ruta)
    if candidato.suffix in {".yaml", ".yml"}:
        ruta = candidato if candidato.is_absolute() else PROJECT_ROOT / candidato
    else:
        ruta = CONFIGS_DIR / f"{nombre_o_ruta}.yaml"
    if not ruta.is_file():
        raise ConfigError(f"No existe el archivo de configuración: {ruta}")
    return ruta


def _cargar_cadena(nombre_o_ruta: str, visitados: tuple[Path, ...] = ()) -> dict[str, Any]:
    ruta = _resolver_ruta(nombre_o_ruta)
    if ruta in visitados:
        raise ConfigError(f"Herencia cíclica en configuración: {ruta}")
    with ruta.open(encoding="utf-8") as fh:
        datos = yaml.safe_load(fh) or {}
    if not isinstance(datos, dict):
        raise ConfigError(f"{ruta} debe contener un mapeo YAML en la raíz")
    padre = datos.pop("extends", None)
    if padre is None:
        return datos
    return deep_merge(_cargar_cadena(str(padre), (*visitados, ruta)), datos)


def load_config(profile: str | None = None) -> AppConfig:
    """Carga ``configs/default.yaml`` y aplica el perfil (nombre o ruta a un YAML).

    El perfil se toma, en orden, del argumento, de ``STORYBOOK_PROFILE`` o de ``default``.
    Los perfiles pueden declarar ``extends: <otro_perfil>`` (p. ej. los experimentos).
    """
    nombre = profile or os.environ.get(PROFILE_ENV_VAR) or "default"
    datos = _cargar_cadena(nombre)
    datos["profile"] = Path(nombre).stem
    try:
        return AppConfig.model_validate(datos)
    except Exception as exc:
        raise ConfigError(f"Configuración inválida en el perfil '{nombre}': {exc}") from exc
