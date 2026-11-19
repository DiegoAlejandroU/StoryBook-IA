"""FLUX.1-schnell en la RTX 3050 de 4 GB (perfil Avanzada, 18 nov).

FLUX.1-schnell tiene un transformer de 12B de parámetros y usa T5-XXL (4,7B) como encoder de
texto: en bf16 son ~33 GB, ni la GPU (4 GB) ni la RAM (24 GB) los aguantan enteros. Cómo
se hace caber:

1. **fp8 en la RAM.** ``scripts/convertir_flux_fp8.py`` lee una vez los pesos oficiales en
   bf16, tensor por tensor, y guarda en ``models/<fp8_dir>`` una copia con las capas
   lineales en ``float8_e4m3fn`` (la mitad). Normas, embeddings y capas de entrada/salida
   siguen en bf16 (las mismas que salta *layerwise casting* de diffusers). Transformer
   ~12 GB y T5 ~4,9 GB en la RAM.
2. **Cálculo en bf16, capa por capa** (``enable_layerwise_casting``): cada capa pasa a
   bf16 solo mientras calcula. En T5 el bloque de la red feed-forward se convierte entero,
   porque su ``forward`` compara el dtype de ``wo`` antes de llamarlo y, si viera fp8,
   pasaría las activaciones a fp8.
3. **Bloques a la GPU solo mientras se usan** (group offloading de diffusers, un bloque a
   la vez; con ``offload_stream`` el siguiente se copia mientras se calcula el actual).
   El encoder CLIP-L y el VAE son pequeños: van a la GPU solo durante cada imagen.

Sin IP-Adapter (no hay uno oficial para FLUX) y sin negative prompt (schnell está destilado
sin CFG): la consistencia viene del descriptor del personaje, que FLUX sigue mucho mejor
que SD porque entiende el prompt con T5 (hasta 256 tokens en vez de 77).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from PIL import Image

from storybook import config
from storybook.config import ImageConfig
from storybook.gpu import free_cuda_memory
from storybook.hub import local_snapshot
from storybook.logging_utils import get_logger, kv

logger = get_logger(__name__)

COMPONENTES_FP8: Final = ("transformer", "text_encoder_2")
INDICE_FP8: Final = "fp8_index.json"
MAX_BYTES_ARCHIVO: Final = 2 * 1024**3  # archivos de ~2 GB (lectura y escritura por partes)
FP8_MAX: Final = 448.0  # máximo representable en float8_e4m3fn (más allá sería NaN)
# T5: lo que queda en bf16 (normas, embeddings, sesgo de posición relativa) y el bloque
# feed-forward, que recibe su propio hook (ver docstring del módulo).
SALTAR_T5: Final = ("norm", "shared", "embed_tokens", "relative_attention_bias", "DenseReluDense")
COMANDO_CONVERSION: Final = "uv run python scripts/convertir_flux_fp8.py"


class FluxNoPreparadoError(Exception):
    """Falta la copia en fp8 (hay que correr la conversión)."""


def carpeta_fp8(cfg: ImageConfig) -> Path:
    return config.MODELS_DIR / (cfg.fp8_dir or "flux-fp8")


# ---------------------------------------------------------------------------------------
# Modelos vacíos con fp8 (lo mismo al convertir que al cargar)
# ---------------------------------------------------------------------------------------
def modelo_vacio(componente: str, carpeta_config: Path) -> Any:
    """El componente sin pesos (en el dispositivo "meta"), en bf16."""
    import torch

    if componente == "transformer":
        from diffusers import FluxTransformer2DModel

        cfg_modelo = FluxTransformer2DModel.load_config(str(carpeta_config))
        with torch.device("meta"):
            modelo = FluxTransformer2DModel.from_config(cfg_modelo)
    elif componente == "text_encoder_2":
        from transformers import T5Config, T5EncoderModel

        cfg_t5 = T5Config.from_pretrained(str(carpeta_config))
        with torch.device("meta"):
            modelo = T5EncoderModel(cfg_t5)
    else:
        raise ValueError(f"Componente sin fp8: {componente}")
    return modelo.to(torch.bfloat16)


def preparar_fp8(modelo: Any, componente: str) -> Any:
    """Hooks de *layerwise casting*: almacenamiento en fp8, cálculo en bf16."""
    import torch
    from diffusers.hooks import apply_layerwise_casting
    from diffusers.hooks.layerwise_casting import apply_layerwise_casting_hook

    fp8, bf16 = torch.float8_e4m3fn, torch.bfloat16
    if componente == "transformer":
        modelo.enable_layerwise_casting(storage_dtype=fp8, compute_dtype=bf16)
    else:
        apply_layerwise_casting(modelo, fp8, bf16, skip_modules_pattern=SALTAR_T5)
        for nombre, sub in modelo.named_modules():
            if nombre.endswith("DenseReluDense"):
                apply_layerwise_casting_hook(sub, fp8, bf16, non_blocking=False)
    return modelo


def tipos_fp8(componente: str, carpeta_config: Path) -> dict[str, Any]:
    """dtype de cada tensor del componente ya preparado (fp8 o bf16)."""
    modelo = preparar_fp8(modelo_vacio(componente, carpeta_config), componente)
    return {clave: tensor.dtype for clave, tensor in modelo.state_dict().items()}


# ---------------------------------------------------------------------------------------
# Conversión (una vez, en scripts/convertir_flux_fp8.py)
# ---------------------------------------------------------------------------------------
def convertir_componente(
    origen: Path, destino: Path, componente: str, avisar: Callable[[str], None] | None = None
) -> dict[str, Any]:
    """Copia ``origen/<componente>`` (bf16, oficial) a ``destino/<componente>`` en fp8.

    Lee tensor por tensor (sin cargar el modelo entero) y escribe archivos de ~2 GB.
    Devuelve el índice guardado (archivo de cada tensor, cuántos quedaron en fp8, valores
    recortados a ±448).
    """
    import torch
    from safetensors import safe_open
    from safetensors.torch import save_file

    carpeta = origen / componente
    tipos = tipos_fp8(componente, carpeta)
    salida = destino / componente
    if salida.exists():
        shutil.rmtree(salida)
    salida.mkdir(parents=True)
    for archivo in carpeta.glob("*.json"):
        if not archivo.name.endswith(".index.json"):
            shutil.copy2(archivo, salida / archivo.name)

    mapa: dict[str, str] = {}
    lote: dict[str, Any] = {}
    estado = {"bytes": 0, "archivos": 0, "fp8": 0, "bf16": 0, "recortados": 0}
    ignoradas: list[str] = []

    def guardar() -> None:
        if not lote:
            return
        nombre = f"model-{estado['archivos'] + 1:05d}.safetensors"
        save_file(lote, str(salida / nombre), metadata={"format": "pt"})
        for clave in lote:
            mapa[clave] = nombre
        estado["archivos"] += 1
        if avisar:
            avisar(f"{componente}: {nombre} ({estado['bytes'] / 1024**3:.1f} GB)")
        lote.clear()

    fuentes = sorted(carpeta.glob("*.safetensors"))
    if not fuentes:
        raise FluxNoPreparadoError(f"No hay pesos .safetensors en {carpeta}")
    for fuente in fuentes:
        with safe_open(str(fuente), framework="pt", device="cpu") as f:
            for clave in f.keys():  # noqa: SIM118 (safe_open no es un dict)
                if clave not in tipos:
                    ignoradas.append(clave)
                    continue
                tensor = f.get_tensor(clave)
                if tipos[clave] == torch.float8_e4m3fn:
                    estado["recortados"] += int((tensor.abs() > FP8_MAX).sum())
                    tensor = tensor.clamp(-FP8_MAX, FP8_MAX).to(torch.float8_e4m3fn)
                    estado["fp8"] += 1
                else:
                    tensor = tensor.to(tipos[clave])
                    estado["bf16"] += 1
                lote[clave] = tensor.contiguous()
                estado["bytes"] += tensor.numel() * tensor.element_size()
                if sum(t.numel() * t.element_size() for t in lote.values()) >= MAX_BYTES_ARCHIVO:
                    guardar()
    guardar()
    # En T5 el embedding del encoder es el mismo que "shared" (pesos atados).
    faltan = sorted(set(tipos) - set(mapa) - {"encoder.embed_tokens.weight"})
    if faltan:
        raise FluxNoPreparadoError(f"{componente}: faltan {len(faltan)} tensores ({faltan[:3]})")
    indice = {
        "componente": componente,
        "origen": str(carpeta),
        "weight_map": mapa,
        "tensores_fp8": estado["fp8"],
        "tensores_bf16": estado["bf16"],
        "valores_recortados": estado["recortados"],
        "gb": round(estado["bytes"] / 1024**3, 2),
        "ignoradas": ignoradas,
    }
    (salida / INDICE_FP8).write_text(json.dumps(indice, indent=2), encoding="utf-8")
    logger.info(
        "flux_fp8_convertido",
        extra=kv(componente=componente, gb=indice["gb"], recortados=estado["recortados"]),
    )
    return indice


def fp8_listo(destino: Path) -> bool:
    return all((destino / c / INDICE_FP8).is_file() for c in COMPONENTES_FP8)


def cargar_componente_fp8(destino: Path, componente: str) -> Any:
    """El componente en la RAM con los pesos fp8 de la conversión y los hooks puestos."""
    carpeta = destino / componente
    indice_ruta = carpeta / INDICE_FP8
    if not indice_ruta.is_file():
        raise FluxNoPreparadoError(
            f"Falta la copia en fp8 de FLUX ({carpeta}). Ejecuta: {COMANDO_CONVERSION}"
        )
    from safetensors.torch import load_file

    indice = json.loads(indice_ruta.read_text(encoding="utf-8"))
    modelo = preparar_fp8(modelo_vacio(componente, carpeta), componente)
    estado: dict[str, Any] = {}
    for archivo in sorted(set(indice["weight_map"].values())):
        estado.update(load_file(str(carpeta / archivo), device="cpu"))
    faltan, sobran = modelo.load_state_dict(estado, strict=False, assign=True)
    del estado
    if componente == "text_encoder_2":
        modelo.encoder.embed_tokens.weight = modelo.shared.weight  # pesos atados
        faltan = [k for k in faltan if k != "encoder.embed_tokens.weight"]
    vacios = [n for n, t in [*modelo.named_parameters(), *modelo.named_buffers()] if t.is_meta]
    if faltan or sobran or vacios:
        raise FluxNoPreparadoError(
            f"{componente}: la copia fp8 no coincide con el modelo "
            f"(faltan {faltan[:3]}, sobran {sobran[:3]}, vacíos {vacios[:3]}). "
            f"Vuelve a ejecutar: {COMANDO_CONVERSION}"
        )
    modelo.eval()
    modelo.requires_grad_(False)
    return modelo


# ---------------------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------------------
class PipelineFlux:
    """``FluxPipeline`` con lo que espera el generador de imágenes.

    * ``tokenizer`` es el de T5: el prompt se mide contra los 256 tokens de FLUX.
    * Recibe los mismos argumentos que SD y quita los que FLUX no usa (negative prompt,
      embeddings de IP-Adapter).
    * CLIP-L y el VAE suben a la GPU solo durante cada imagen (``estacionar`` los baja).
    """

    def __init__(self, pipe: Any, max_sequence_length: int, dispositivo: str) -> None:
        self.pipe = pipe
        self.tokenizer = pipe.tokenizer_2
        self.max_sequence_length = max_sequence_length
        self.dispositivo = dispositivo

    def __call__(self, **kwargs: Any) -> Any:
        kwargs.pop("negative_prompt", None)
        kwargs.pop("ip_adapter_image_embeds", None)
        kwargs.setdefault("max_sequence_length", self.max_sequence_length)
        self.pipe.text_encoder.to(self.dispositivo)
        self.pipe.vae.to(self.dispositivo)
        return self.pipe(**kwargs)

    def estacionar(self) -> None:
        self.pipe.text_encoder.to("cpu")
        self.pipe.vae.to("cpu")
        free_cuda_memory()

    def set_progress_bar_config(self, **kwargs: Any) -> None:
        self.pipe.set_progress_bar_config(**kwargs)


class FluxBackend:
    """Backend de imagen para ``arquitectura: flux`` (ver docstring del módulo)."""

    nombre = "flux"

    def __init__(self) -> None:
        self._dispositivo = "cpu"
        self._info: dict[str, Any] = {}

    def cargar(self, cfg: ImageConfig) -> PipelineFlux:
        import diffusers
        import torch
        from diffusers import FluxPipeline
        from diffusers.hooks import apply_group_offloading

        if not torch.cuda.is_available():
            raise FluxNoPreparadoError("FLUX en este equipo necesita la GPU (CUDA no disponible)")
        self._dispositivo = "cuda"
        snapshot = local_snapshot(cfg.model_id)
        destino = carpeta_fp8(cfg)
        transformer = cargar_componente_fp8(destino, "transformer")
        t5 = cargar_componente_fp8(destino, "text_encoder_2")
        pipe = FluxPipeline.from_pretrained(
            str(snapshot), transformer=transformer, text_encoder_2=t5, torch_dtype=torch.bfloat16
        )
        opciones: dict[str, Any] = {
            "onload_device": torch.device("cuda"),
            "offload_device": torch.device("cpu"),
            "offload_type": "block_level",
            "num_blocks_per_group": 1,
            "use_stream": cfg.offload_stream,
            # Con streams no se duplica la RAM: se fija (pin) cada bloque al copiarlo.
            "low_cpu_mem_usage": True,
        }
        apply_group_offloading(transformer, **opciones)
        apply_group_offloading(t5.encoder, **opciones)
        if cfg.vae_slicing:
            pipe.vae.enable_slicing()
        pipe.vae.enable_tiling()  # decodificar ~1 MP sin pico de memoria
        pipe.set_progress_bar_config(disable=True)
        self._info = {
            "backend": self.nombre,
            "dispositivo": self._dispositivo,
            "dtype": "bfloat16 (pesos fp8)",
            "torch": torch.__version__,
            "diffusers": diffusers.__version__,
            "modelo_revision": snapshot.name,
            "arquitectura": "flux",
            "fp8_dir": str(destino.name),
            "offload": "grupos" + (" + stream" if cfg.offload_stream else ""),
            "max_sequence_length": cfg.max_sequence_length,
        }
        return PipelineFlux(pipe, cfg.max_sequence_length, self._dispositivo)

    def preparar_ip_adapter(self, pipe: Any, cfg: ImageConfig, referencia: Image.Image) -> Any:
        raise NotImplementedError("FLUX no usa IP-Adapter en este proyecto")

    def generador(self, seed: int) -> Any:
        import torch

        # En CPU: el ruido inicial no depende de la GPU (misma seed, misma imagen).
        return torch.Generator("cpu").manual_seed(seed)

    def es_oom(self, exc: BaseException) -> bool:
        try:
            import torch
        except ImportError:
            return False
        return isinstance(exc, torch.cuda.OutOfMemoryError)

    def liberar(self) -> None:
        free_cuda_memory()

    def info(self) -> dict[str, Any]:
        return dict(self._info)
