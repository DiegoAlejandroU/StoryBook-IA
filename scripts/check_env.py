"""Diagnóstico del entorno de StoryBook (F0).

Reporta CPU, RAM, energía, disco, GPU/VRAM (NVML), PyTorch + CUDA, versiones de
librerías, caché de modelos y Ollama. Guarda un JSON en outputs/env/ que alimenta la
sección "Hardware, versiones y reproducibilidad" del informe.

Uso (PowerShell, desde la raíz del repo):
    uv run python scripts/check_env.py
    uv run python scripts/check_env.py --profile calidad
    uv run python scripts/check_env.py --allow-cpu      # no falla si no hay CUDA
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Literal

from storybook import config  # primero: fija HF_HOME y el modo offline
from storybook.gpu import NvmlReader
from storybook.hub import is_diffusers_repo, piper_voice_files
from storybook.logging_utils import get_logger, kv, setup_logging
from storybook.story.llm_client import LLMError, OllamaClient

log = get_logger("check_env")

Estado = Literal["OK", "AVISO", "FALLO", "INFO"]
GB = 1024**3
DISCO_MIN_GB = 25.0
RAM_MIN_GB = 16.0
VRAM_MIN_MB = 3800.0
PAQUETES = (
    "torch",
    "torchvision",
    "diffusers",
    "transformers",
    "accelerate",
    "peft",
    "safetensors",
    "huggingface-hub",
    "piper-tts",
    "onnxruntime",
    "faster-whisper",
    "ctranslate2",
    "open-clip-torch",
    "jiwer",
    "streamlit",
    "pydantic",
    "numpy",
    "scipy",
    "soundfile",
    "pyloudnorm",
    "nvidia-ml-py",
    "httpx",
)


@dataclass
class Check:
    categoria: str
    nombre: str
    estado: Estado
    detalle: str
    datos: dict[str, Any] = field(default_factory=dict)


class Reporte:
    def __init__(self) -> None:
        self.checks: list[Check] = []
        self.hardware: dict[str, Any] = {}

    def add(self, categoria: str, nombre: str, estado: Estado, detalle: str, **datos: Any) -> None:
        self.checks.append(Check(categoria, nombre, estado, detalle, datos))
        nivel = {"OK": 20, "INFO": 20, "AVISO": 30, "FALLO": 40}[estado]
        log.log(nivel, f"[{estado}] {categoria} / {nombre}: {detalle}")

    def conteo(self) -> dict[str, int]:
        return {
            e: sum(c.estado == e for c in self.checks) for e in ("OK", "AVISO", "FALLO", "INFO")
        }


# ---------------------------------------------------------------------------------------
def nombre_cpu() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            clave = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            )
            valor, _ = winreg.QueryValueEx(clave, "ProcessorNameString")
            return str(valor).strip()
        except OSError:
            return platform.processor()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for linea in cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if linea.startswith("model name"):
                return linea.split(":", 1)[1].strip()
    return platform.processor() or "desconocida"


def nombre_so() -> str:
    if sys.platform == "win32":
        build = sys.getwindowsversion().build
        edicion = "Windows 11" if build >= 22000 else "Windows 10"
        return f"{edicion} (build {build}) {platform.machine()}"
    return platform.platform()


def check_sistema(rep: Reporte) -> None:
    import psutil

    rep.hardware["so"] = nombre_so()
    rep.add("sistema", "SO", "INFO", rep.hardware["so"])

    en_venv = sys.prefix != sys.base_prefix
    rep.hardware["python"] = platform.python_version()
    estado: Estado = "OK" if sys.version_info[:2] == (3, 11) and en_venv else "AVISO"
    rep.add(
        "sistema",
        "Python",
        estado,
        f"{platform.python_version()} ({'venv' if en_venv else 'SIN venv'}) en {sys.executable}",
    )

    cpu = nombre_cpu()
    fisicos = psutil.cpu_count(logical=False)
    logicos = psutil.cpu_count(logical=True)
    frecuencia = psutil.cpu_freq()
    rep.hardware["cpu"] = {
        "nombre": cpu,
        "nucleos": fisicos,
        "hilos": logicos,
        "mhz_max": round(frecuencia.max) if frecuencia else None,
    }
    rep.add("hardware", "CPU", "INFO", f"{cpu} - {fisicos} núcleos / {logicos} hilos")

    memoria = psutil.virtual_memory()
    total_gb = round(memoria.total / GB, 1)
    rep.hardware["ram_gb"] = total_gb
    rep.add(
        "hardware",
        "RAM",
        "OK" if total_gb >= RAM_MIN_GB else "AVISO",
        f"{total_gb} GB total, {round(memoria.available / GB, 1)} GB disponibles",
    )

    bateria = psutil.sensors_battery()
    if bateria is None:
        rep.add("energia", "Alimentación", "INFO", "Sin batería detectada (equipo de escritorio)")
    else:
        conectado = bool(bateria.power_plugged)
        rep.hardware["conectado_corriente"] = conectado
        rep.add(
            "energia",
            "Alimentación",
            "OK" if conectado else "AVISO",
            f"{'Conectado a la corriente' if conectado else 'EN BATERÍA: la GPU se limita'} "
            f"({bateria.percent:.0f} %). Usa modo Turbo/Rendimiento en Armoury Crate.",
        )

    libre_gb = round(shutil.disk_usage(config.PROJECT_ROOT).free / GB, 1)
    rep.add(
        "hardware",
        "Disco",
        "OK" if libre_gb >= DISCO_MIN_GB else "AVISO",
        f"{libre_gb} GB libres en la unidad del proyecto (mínimo recomendado {DISCO_MIN_GB} GB)",
    )


def check_gpu_nvml(rep: Reporte) -> dict[str, Any]:
    lector = NvmlReader()
    try:
        if not lector.available:
            rep.add("gpu", "NVML", "FALLO", "No se detecta GPU NVIDIA/driver (nvidia-smi)")
            return {}
        info = lector.info()
    finally:
        lector.close()
    rep.hardware["gpu"] = info
    total = info.get("vram_total_mb") or 0
    rep.add(
        "gpu",
        "GPU",
        "OK" if total >= VRAM_MIN_MB else "AVISO",
        f"{info['nombre']} - {total:.0f} MB VRAM ({info.get('vram_usada_mb')} MB en uso)",
    )
    rep.add(
        "gpu",
        "Driver",
        "INFO",
        f"Driver {info['driver']} - soporta CUDA hasta {info.get('cuda_driver')}",
    )
    if info.get("pstate") is not None or info.get("potencia_limite_w") is not None:
        rep.add(
            "gpu",
            "Estado",
            "INFO",
            f"P-state P{info.get('pstate')}, límite {info.get('potencia_limite_w')} W, "
            f"{info.get('temperatura_c')} °C",
        )
    return info


def _version_tupla(texto: str | None) -> tuple[int, int]:
    if not texto:
        return (0, 0)
    partes = [*texto.split("."), "0"][:2]
    return (int(partes[0]), int(partes[1]))


def check_torch(rep: Reporte, info_gpu: dict[str, Any], allow_cpu: bool) -> None:
    try:
        import torch
    except ImportError as exc:
        rep.add("pytorch", "Import", "FALLO", f"No se pudo importar torch: {exc}. Ejecuta uv sync")
        return

    runtime = torch.version.cuda
    rep.hardware["torch"] = {"version": torch.__version__, "cuda_runtime": runtime}
    rep.add("pytorch", "Versión", "INFO", f"torch {torch.__version__} (CUDA runtime {runtime})")

    if runtime is None:
        rep.add(
            "pytorch",
            "Build",
            "AVISO" if allow_cpu else "FALLO",
            "Se instaló torch SOLO-CPU. Revisa [tool.uv.sources] en pyproject.toml y ejecuta "
            "uv sync --reinstall-package torch",
        )
        return

    driver_cuda = info_gpu.get("cuda_driver")
    if driver_cuda and _version_tupla(runtime)[0] > _version_tupla(driver_cuda)[0]:
        rep.add(
            "pytorch",
            "Compatibilidad",
            "FALLO",
            f"torch usa CUDA {runtime} pero el driver soporta {driver_cuda}. Actualiza el "
            "driver con NVIDIA App o usa el índice alternativo cu126 (torch 2.14).",
        )
    elif driver_cuda and _version_tupla(runtime) > _version_tupla(driver_cuda):
        rep.add(
            "pytorch",
            "Compatibilidad",
            "AVISO",
            f"CUDA runtime {runtime} > driver {driver_cuda}: funciona por compatibilidad de "
            "versión menor, pero conviene actualizar el driver.",
        )

    if not torch.cuda.is_available():
        rep.add(
            "pytorch",
            "torch.cuda.is_available()",
            "AVISO" if allow_cpu else "FALLO",
            "False: PyTorch no ve la GPU",
        )
        return

    propiedades = torch.cuda.get_device_properties(0)
    capacidad = f"{propiedades.major}.{propiedades.minor}"
    rep.add(
        "pytorch",
        "torch.cuda.is_available()",
        "OK",
        f"True - {propiedades.name}, compute capability {capacidad}, "
        f"{propiedades.total_memory / 1024**2:.0f} MB",
    )
    rep.hardware["torch"].update(
        {
            "dispositivo": propiedades.name,
            "compute_capability": capacidad,
            "cudnn": torch.backends.cudnn.version(),
            "bf16": bool(torch.cuda.is_bf16_supported()),
        }
    )

    # Prueba real de fp16 en GPU (matmul 2048x2048).
    try:
        a = torch.randn(2048, 2048, device="cuda", dtype=torch.float16)
        torch.cuda.synchronize()
        inicio = time.perf_counter()
        for _ in range(10):
            b = a @ a
        torch.cuda.synchronize()
        segundos = time.perf_counter() - inicio
        tflops = 10 * 2 * 2048**3 / segundos / 1e12
        ok = bool(torch.isfinite(b).all())
        del a, b
        torch.cuda.empty_cache()
        rep.add(
            "pytorch",
            "fp16",
            "OK" if ok else "FALLO",
            f"matmul fp16 {'correcto' if ok else 'con NaN/Inf'} - ~{tflops:.1f} TFLOPS",
        )
        rep.hardware["torch"]["fp16_tflops"] = round(tflops, 2)
    except RuntimeError as exc:
        rep.add("pytorch", "fp16", "FALLO", f"Error ejecutando en GPU: {exc}")


def check_paquetes(rep: Reporte) -> None:
    versiones: dict[str, str | None] = {}
    faltantes: list[str] = []
    for paquete in PAQUETES:
        try:
            versiones[paquete] = metadata.version(paquete)
        except metadata.PackageNotFoundError:
            versiones[paquete] = None
            faltantes.append(paquete)
    rep.hardware["paquetes"] = versiones
    texto = ", ".join(f"{p}={v}" for p, v in versiones.items() if v)
    rep.add("librerias", "Versiones", "INFO", texto)
    if faltantes:
        rep.add("librerias", "Faltantes", "FALLO", f"{faltantes}. Ejecuta: uv sync")


def check_modelos(rep: Reporte, perfil: config.AppConfig) -> None:
    import os

    rep.add(
        "modelos",
        "Modo offline",
        "OK" if config.is_offline() else "AVISO",
        f"HF_HUB_OFFLINE={os.environ.get('HF_HUB_OFFLINE')} - HF_HOME={config.HF_HOME_DIR}",
    )
    try:
        from huggingface_hub import scan_cache_dir

        cache = scan_cache_dir(config.HF_HOME_DIR / "hub")
        repos = {r.repo_id: r for r in cache.repos}
        tamano_gb = round(cache.size_on_disk / GB, 2)
    except Exception as exc:  # caché inexistente o corrupta
        repos, tamano_gb = {}, 0.0
        log.debug("cache_hf_no_legible", extra=kv(error=str(exc)))

    rep.add(
        "modelos", "Caché HF", "INFO", f"{len(repos)} repos, {tamano_gb} GB en {config.HF_HOME_DIR}"
    )

    requeridos = {
        perfil.image.model_id: "imagen",
        perfil.image.lcm_lora_id: "imagen (LCM)",
        perfil.image.ip_adapter.repo_id: "imagen (IP-Adapter)",
        perfil.evaluation.whisper_repo_id: "evaluación (WER)",
    }
    for repo_id, uso in requeridos.items():
        estado: Estado = "OK" if repo_id in repos else "FALLO"
        rep.add("modelos", repo_id, estado, f"{uso}: {'descargado' if estado == 'OK' else 'falta'}")

    sonido = (
        ("sa3", perfil.sound.sa3_repo_id),
        ("sao", perfil.sound.sao_repo_id),
        ("audioldm", perfil.sound.audioldm_repo_id),
    )
    for backend, repo_id in sonido:
        if backend not in perfil.sound.backends:
            continue
        if repo_id not in repos:
            motivo = "falta" if backend == "audioldm" else "falta (gated)"
            rep.add("modelos", repo_id, "AVISO", f"sonido ({backend}): {motivo}. Habrá fallback")
            continue
        snapshot = Path(next(iter(repos[repo_id].revisions)).snapshot_path)
        formato = "diffusers" if is_diffusers_repo(snapshot) else "NO diffusers"
        rep.add(
            "modelos",
            repo_id,
            "OK" if formato == "diffusers" else "AVISO",
            f"sonido ({backend}): descargado, formato {formato}",
        )

    voz = piper_voice_files(perfil.voice.piper_voice)
    rep.add(
        "modelos",
        f"Piper {perfil.voice.piper_voice}",
        "OK" if voz.existen() else "FALLO",
        str(voz.onnx.parent) if voz.existen() else "falta la voz (download_models.py)",
    )


def check_ollama(rep: Reporte, perfil: config.AppConfig) -> None:
    import os

    try:
        with OllamaClient(perfil.llm.host, timeout_s=10) as cliente:
            version = cliente.version()
            modelos = cliente.list_models()
            tiene = cliente.has_model(perfil.llm.model)
    except LLMError as exc:
        rep.add("ollama", "Servidor", "FALLO", str(exc))
        return
    rep.hardware["ollama"] = {"version": version, "modelos": modelos}
    rep.add("ollama", "Servidor", "OK", f"Ollama {version} en {perfil.llm.host}")
    rep.add(
        "ollama",
        perfil.llm.model,
        "OK" if tiene else "FALLO",
        "descargado" if tiene else f"falta: ollama pull {perfil.llm.model}",
    )
    for variable, recomendado in (
        ("OLLAMA_FLASH_ATTENTION", "1"),
        ("OLLAMA_KV_CACHE_TYPE", "q8_0"),
    ):
        valor = os.environ.get(variable)
        rep.add(
            "ollama",
            variable,
            "OK" if valor == recomendado else "INFO",
            f"{valor or 'no definida'} (recomendado {recomendado}: reduce la VRAM del KV cache)",
        )


# ---------------------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default=None, help="rapido | calidad | ruta a YAML")
    parser.add_argument("--allow-cpu", action="store_true", help="No fallar si no hay CUDA")
    args = parser.parse_args()

    setup_logging()
    perfil = config.load_config(args.profile)
    rep = Reporte()
    log.info("check_env_inicio", extra=kv(perfil=perfil.profile, raiz=str(config.PROJECT_ROOT)))

    check_sistema(rep)
    info_gpu = check_gpu_nvml(rep)
    check_torch(rep, info_gpu, args.allow_cpu)
    check_paquetes(rep)
    check_modelos(rep, perfil)
    check_ollama(rep, perfil)

    conteo = rep.conteo()
    salida_dir = config.OUTPUTS_DIR / "env"
    salida_dir.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    reporte = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "perfil": perfil.profile,
        "resumen": conteo,
        "hardware": rep.hardware,
        "checks": [asdict(c) for c in rep.checks],
    }
    texto = json.dumps(reporte, ensure_ascii=False, indent=2, default=str)
    (salida_dir / f"env_report_{marca}.json").write_text(texto, encoding="utf-8")
    (salida_dir / "env_report.json").write_text(texto, encoding="utf-8")

    log.info(
        "check_env_fin",
        extra=kv(
            ok=conteo["OK"],
            avisos=conteo["AVISO"],
            fallos=conteo["FALLO"],
            reporte=str(salida_dir / "env_report.json"),
        ),
    )
    return 1 if conteo["FALLO"] else 0


if __name__ == "__main__":
    sys.exit(main())
