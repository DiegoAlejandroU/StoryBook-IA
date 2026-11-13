"""Etapa de imágenes: SD 1.5 (DreamShaper 8) + LCM-LoRA + IP-Adapter, por lotes.

Flujo de la etapa (una sola carga del modelo para las 5 escenas, CLAUDE.md §4):

1. Asigna seeds a la Bible si no las tiene (``consistency``: compartida o por escena).
2. Carga el pipeline desde la caché local (``hub.local_snapshot``; nunca descarga).
3. Si IP-Adapter está activo (C3): genera la character sheet del protagonista, calcula sus
   embeddings en CPU y carga el adaptador. Si algo de esto falla, sigue sin IP-Adapter y
   lo registra como fallback.
4. Genera cada escena con el prompt de ``prompt_builder`` (tokens contados con el tokenizer
   real del pipeline). Un OOM se reintenta una vez tras liberar memoria; si vuelve a fallar
   la escena recibe una imagen de respaldo y el error queda registrado: la historia
   siempre tiene 5 ilustraciones.
5. Libera la VRAM (``del`` + ``free_cuda_memory``) pase lo que pase.

El modelo real está detrás del Protocol ``BackendImagen``: ``DiffusersBackend`` importa
torch/diffusers/transformers solo al usarse (imports perezosos, CLAUDE.md §6) y los tests
usan un backend falso.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

from PIL import Image, ImageDraw

from storybook.config import ConsistencyConfig, ImageConfig
from storybook.gpu import StageMetrics, free_cuda_memory, track_stage
from storybook.hub import diffusers_variant, local_snapshot, lora_weight_name
from storybook.image.consistency import (
    NOMBRE_ARCHIVO_SHEET,
    PromptSheet,
    construir_prompt_sheet,
)
from storybook.image.prompt_builder import (
    ContadorTokens,
    PromptImagen,
    construir_prompt,
    contador_desde_tokenizer,
)
from storybook.logging_utils import get_logger, kv
from storybook.schemas import StoryBible, estimar_tokens_clip

logger = get_logger(__name__)

FALLBACK_SIN_IP_ADAPTER: Final = "imagen:sin_ip_adapter"
FALLBACK_RESPALDO: Final = "imagen:respaldo"
COLOR_RESPALDO: Final = (38, 44, 58)
COLOR_TEXTO_RESPALDO: Final = (220, 220, 230)


class ImageError(Exception):
    """Error de la etapa de imágenes."""


class ImageModelError(ImageError):
    """El modelo no se pudo cargar (no descargado, sin CUDA, versión incompatible...)."""


class PipelineImagen(Protocol):
    """Lo que el generador usa de un ``StableDiffusionPipeline`` (o de uno falso)."""

    tokenizer: Any

    def __call__(self, **kwargs: Any) -> Any: ...


class BackendImagen(Protocol):
    nombre: str

    def cargar(self, cfg: ImageConfig) -> PipelineImagen:
        """Carga el pipeline listo para generar (scheduler, LoRA, memoria, dispositivo)."""
        ...

    def preparar_ip_adapter(
        self, pipe: PipelineImagen, cfg: ImageConfig, referencia: Image.Image
    ) -> Any:
        """Carga IP-Adapter y devuelve el valor de ``ip_adapter_image_embeds``."""
        ...

    def generador(self, seed: int) -> Any:
        """``torch.Generator`` con la seed (lo que espera ``generator=``)."""
        ...

    def es_oom(self, exc: BaseException) -> bool: ...

    def liberar(self) -> None:
        """Devuelve la VRAM tras borrar el pipeline."""
        ...

    def info(self) -> dict[str, Any]:
        """Versiones, dispositivo y revisión de los pesos (para el manifest)."""
        ...


# ---------------------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------------------
@dataclass
class ResultadoImagen:
    escena: int
    ruta: Path
    seed: int
    prompt: PromptImagen
    ip_adapter: bool
    segundos: float
    respaldo: bool = False
    intentos: int = 1
    error: str | None = None
    ip_escala: float = 0.0

    def a_dict(self) -> dict[str, Any]:
        return {
            "escena": self.escena,
            "archivo": self.ruta.name,
            "seed": self.seed,
            "ip_adapter": self.ip_adapter,
            "ip_escala": self.ip_escala,
            "segundos": self.segundos,
            "respaldo": self.respaldo,
            "intentos": self.intentos,
            "error": self.error,
            "prompt": self.prompt.a_dict(),
        }


@dataclass
class EtapaImagen:
    """Salida de la etapa: la Bible con seeds, las imágenes y lo que va al manifest."""

    bible: StoryBible
    imagenes: list[ResultadoImagen]
    parametros: dict[str, Any]
    character_sheet: Path | None = None
    prompt_sheet: PromptSheet | None = None
    metricas: list[StageMetrics] = field(default_factory=list)
    fallbacks: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    backend: dict[str, Any] = field(default_factory=dict)

    @property
    def rutas(self) -> list[Path]:
        return [r.ruta for r in self.imagenes]

    def a_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "parametros": self.parametros,
            "character_sheet": self.character_sheet.name if self.character_sheet else None,
            "prompt_sheet": self.prompt_sheet.a_dict() if self.prompt_sheet else None,
            "imagenes": [r.a_dict() for r in self.imagenes],
            "metricas": [m.as_dict() for m in self.metricas],
            "fallbacks": self.fallbacks,
            "errores": self.errores,
        }


def nombre_archivo_escena(numero: int) -> str:
    return f"scene_{numero}.png"


def imagen_respaldo(ancho: int, alto: int, numero: int) -> Image.Image:
    """Ilustración de respaldo (lisa, con aviso) para no dejar una escena sin imagen."""
    imagen = Image.new("RGB", (ancho, alto), COLOR_RESPALDO)
    dibujo = ImageDraw.Draw(imagen)
    texto = f"Escena {numero}: ilustración no disponible"
    caja = dibujo.textbbox((0, 0), texto)
    posicion = ((ancho - (caja[2] - caja[0])) // 2, (alto - (caja[3] - caja[1])) // 2)
    dibujo.text(posicion, texto, fill=COLOR_TEXTO_RESPALDO)
    return imagen


def restaurar_almacenamiento_fp8(unet: Any) -> int:
    """Devuelve a fp8 las capas con *layerwise casting* tras cargar IP-Adapter.

    ``load_ip_adapter`` termina con ``unet.to(dtype=unet.dtype)``, y con layerwise casting
    ``unet.dtype`` es el de cálculo (fp16): el UNet de SDXL volvería a ocupar 5,1 GB y no
    cabría en la GPU de 4 GB. Las capas nuevas de IP-Adapter no tienen el hook y siguen en
    fp16. Devuelve cuántas capas se restauraron.
    """
    restauradas = 0
    for modulo in unet.modules():
        registro = getattr(modulo, "_diffusers_hook", None)
        gancho = registro.get_hook("layerwise_casting") if registro is not None else None
        if gancho is not None:
            modulo.to(dtype=gancho.storage_dtype)
            restauradas += 1
    return restauradas


# ---------------------------------------------------------------------------------------
# Generador
# ---------------------------------------------------------------------------------------
class GeneradorImagenes:
    def __init__(
        self,
        cfg: ImageConfig,
        consistencia: ConsistencyConfig,
        backend: BackendImagen | None = None,
    ) -> None:
        self.cfg = cfg
        self.consistencia = consistencia
        self.backend: BackendImagen = backend or DiffusersBackend()

    # -- utilidades ---------------------------------------------------------------------
    def asegurar_seeds(self, bible: StoryBible) -> StoryBible:
        """Asigna seeds según ``consistency`` si alguna escena o personaje no la tiene."""
        sin_seed = any(e.seed_imagen is None for e in bible.escenas) or any(
            p.seed is None for p in bible.personajes
        )
        if not sin_seed:
            return bible
        c = self.consistencia
        return bible.con_seeds(c.base_seed, fija=c.fixed_seed, politica=c.seed_policy)

    @property
    def usar_bible(self) -> bool:
        return self.consistencia.use_bible

    @property
    def usar_ip_adapter(self) -> bool:
        return self.cfg.ip_adapter.enabled and self.usar_bible

    def parametros(self) -> dict[str, Any]:
        c = self.cfg
        return {
            "modelo": c.model_id,
            "scheduler": c.scheduler,
            "lcm_lora": c.lcm_lora_id if c.scheduler == "lcm" else None,
            "pasos": c.steps,
            "guidance_scale": c.guidance_scale,
            "ancho": c.width,
            "alto": c.height,
            "usar_bible": self.usar_bible,
            "ip_adapter": self.usar_ip_adapter,
            "ip_adapter_scale": c.ip_adapter.scale if self.usar_ip_adapter else None,
            "prompt_orden": c.prompt_orden,
            "personajes_prompt": c.personajes_prompt,
            "arquitectura": c.arquitectura,
            "seed_policy": self.consistencia.seed_policy,
            "seed_fija": self.consistencia.fixed_seed,
        }

    def _llamar(
        self,
        pipe: PipelineImagen,
        *,
        prompt: str,
        negativo: str,
        seed: int,
        ancho: int,
        alto: int,
        ip_embeds: Any = None,
    ) -> Image.Image:
        kwargs: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": negativo,
            "num_inference_steps": self.cfg.steps,
            "guidance_scale": self.cfg.guidance_scale,
            "width": ancho,
            "height": alto,
            "generator": self.backend.generador(seed),
        }
        if ip_embeds is not None:
            kwargs["ip_adapter_image_embeds"] = ip_embeds
        salida = pipe(**kwargs)
        return salida.images[0]

    # -- etapa ----------------------------------------------------------------------------
    def generar(
        self,
        bible: StoryBible,
        carpeta: Path,
        numeros: Sequence[int] | None = None,
        *,
        reutilizar_sheet: bool = True,
    ) -> EtapaImagen:
        """Genera las escenas ``numeros`` (por defecto las 5) en ``carpeta``.

        Para regenerar una sola escena se pasa ``numeros=[n]``: la Bible y sus seeds no
        cambian y, si existe, se reutiliza la character sheet de la ejecución original.
        """
        bible = self.asegurar_seeds(bible)
        numeros = list(numeros) if numeros is not None else [e.numero for e in bible.escenas]
        with self.sesion(bible, carpeta, reutilizar_sheet=reutilizar_sheet) as sesion:
            for numero in numeros:
                sesion.escena(bible, numero)
        etapa = sesion.etapa
        logger.info(
            "etapa_imagen_terminada",
            extra=kv(
                escenas=numeros,
                respaldos=sum(r.respaldo for r in etapa.imagenes),
                fallbacks=etapa.fallbacks,
            ),
        )
        return etapa

    def sesion(
        self, bible: StoryBible, carpeta: Path, *, reutilizar_sheet: bool = True
    ) -> SesionImagen:
        """Modelo cargado una vez para ilustrar escena por escena (``with``).

        ``generar`` la usa para las 5 escenas seguidas; la generación por escenas la mantiene
        abierta mientras el LLM escribe la siguiente (con ``cpu_offload`` la VRAM queda libre
        entre llamadas). ``bible`` debe traer al menos el protagonista y el estilo: con ellos
        se hace la character sheet.
        """
        return SesionImagen(self, self.asegurar_seeds(bible), carpeta, reutilizar_sheet)

    def _contador(self, pipe: PipelineImagen) -> ContadorTokens:
        tokenizer = getattr(pipe, "tokenizer", None)
        if tokenizer is None:
            logger.warning("imagen_sin_tokenizer", extra=kv(contador="estimacion_heuristica"))
            return estimar_tokens_clip
        return contador_desde_tokenizer(tokenizer)

    def _preparar_ip_adapter(
        self,
        pipe: PipelineImagen,
        bible: StoryBible,
        carpeta: Path,
        contar: ContadorTokens,
        etapa: EtapaImagen,
        reutilizar_sheet: bool,
    ) -> Any:
        """Character sheet + IP-Adapter. Si falla, se sigue sin él (fallback registrado)."""
        ruta = carpeta / NOMBRE_ARCHIVO_SHEET
        prompt_sheet = construir_prompt_sheet(
            bible,
            seed_por_defecto=self.consistencia.base_seed,
            contar=contar,
            negative_base=self.cfg.negative_prompt_base,
        )
        etapa.prompt_sheet = prompt_sheet
        try:
            if reutilizar_sheet and ruta.is_file():
                referencia = Image.open(ruta).convert("RGB")
                logger.info("character_sheet_reutilizada", extra=kv(archivo=ruta.name))
            else:
                with track_stage("imagen_character_sheet") as m_sheet:
                    referencia = self._llamar(
                        pipe,
                        prompt=prompt_sheet.prompt,
                        negativo=prompt_sheet.negative_prompt,
                        seed=prompt_sheet.seed,
                        ancho=self.cfg.sheet_size,
                        alto=self.cfg.sheet_size,
                    )
                    m_sheet.extra.update(seed=prompt_sheet.seed, tokens=prompt_sheet.tokens)
                referencia.save(ruta)
                etapa.metricas.append(m_sheet)
            etapa.character_sheet = ruta
            with track_stage("imagen_ip_adapter") as m_ip:
                embeds = self.backend.preparar_ip_adapter(pipe, self.cfg, referencia)
                m_ip.extra.update(scale=self.cfg.ip_adapter.scale)
            etapa.metricas.append(m_ip)
            return embeds
        except Exception as exc:
            if self.backend.es_oom(exc):
                free_cuda_memory()
            mensaje = f"IP-Adapter desactivado: {type(exc).__name__}: {exc}"
            logger.warning("ip_adapter_fallback", extra=kv(error=mensaje))
            etapa.fallbacks.append(FALLBACK_SIN_IP_ADAPTER)
            etapa.errores.append(mensaje)
            return None

    def _ajustar_ip(self, pipe: PipelineImagen, ip_embeds: Any, factor: float) -> float:
        """Escala de IP-Adapter para esta escena (0 si no hay IP-Adapter o el foco es otro).

        La referencia es del protagonista: en una escena del loro o del jaguar, aplicarla
        convierte al animal en el niño. Con escala 0 se siguen pasando los embeddings.
        """
        if ip_embeds is None:
            return 0.0
        escala = round(self.cfg.ip_adapter.scale * factor, 3)
        ajustar = getattr(pipe, "set_ip_adapter_scale", None)
        if callable(ajustar):
            ajustar(escala)
        return escala

    def _generar_escena(
        self,
        pipe: PipelineImagen,
        bible: StoryBible,
        numero: int,
        carpeta: Path,
        contar: ContadorTokens,
        ip_embeds: Any,
        etapa: EtapaImagen,
    ) -> ResultadoImagen:
        escena = bible.escena(numero)
        seed = escena.seed_imagen if escena.seed_imagen is not None else self.consistencia.base_seed
        prompt = construir_prompt(
            bible,
            numero,
            contar=contar,
            negative_base=self.cfg.negative_prompt_base,
            usar_bible=self.usar_bible,
            orden=self.cfg.prompt_orden,
            personajes=self.cfg.personajes_prompt,
        )
        escala_ip = self._ajustar_ip(pipe, ip_embeds, prompt.ip_factor)
        ruta = carpeta / nombre_archivo_escena(numero)
        ultimo_error: str | None = None
        intentos = 0
        for intento in (1, 2):
            intentos = intento
            try:
                with track_stage(f"imagen_escena_{numero}") as metrica:
                    imagen = self._llamar(
                        pipe,
                        prompt=prompt.prompt,
                        negativo=prompt.negative_prompt,
                        seed=seed,
                        ancho=self.cfg.width,
                        alto=self.cfg.height,
                        ip_embeds=ip_embeds,
                    )
                    metrica.extra.update(
                        seed=seed,
                        tokens=prompt.tokens,
                        intento=intento,
                        ip=ip_embeds is not None,
                        ip_escala=escala_ip,
                        foco=prompt.foco,
                    )
                imagen.save(ruta)
                etapa.metricas.append(metrica)
                return ResultadoImagen(
                    escena=numero,
                    ruta=ruta,
                    seed=seed,
                    prompt=prompt,
                    ip_adapter=ip_embeds is not None and escala_ip > 0,
                    segundos=metrica.segundos,
                    intentos=intento,
                    ip_escala=escala_ip,
                )
            except Exception as exc:
                ultimo_error = f"{type(exc).__name__}: {exc}"
                oom = self.backend.es_oom(exc)
                logger.error(
                    "imagen_escena_fallo",
                    extra=kv(escena=numero, intento=intento, oom=oom, error=ultimo_error),
                )
                if not oom:
                    break
                free_cuda_memory()

        imagen_respaldo(self.cfg.width, self.cfg.height, numero).save(ruta)
        etapa.fallbacks.append(f"{FALLBACK_RESPALDO}:{numero}")
        etapa.errores.append(f"Escena {numero}: {ultimo_error}")
        return ResultadoImagen(
            escena=numero,
            ruta=ruta,
            seed=seed,
            prompt=prompt,
            ip_adapter=False,
            segundos=0.0,
            respaldo=True,
            intentos=intentos,
            error=ultimo_error,
        )


class SesionImagen:
    """Pipeline de imagen abierto: carga, character sheet e IP-Adapter una sola vez.

    Al entrar carga el modelo (``ImageModelError`` si no se puede) y prepara la referencia
    del protagonista; ``escena`` ilustra una escena y la agrega a ``etapa``; al salir libera
    la VRAM. ``estacionar`` devuelve a la GPU la memoria en caché de torch para que otro
    modelo (el LLM de Ollama) pueda cargarse mientras la sesión sigue abierta.
    """

    def __init__(
        self,
        generador: GeneradorImagenes,
        bible: StoryBible,
        carpeta: Path,
        reutilizar_sheet: bool = True,
    ) -> None:
        self.generador = generador
        self.carpeta = carpeta
        self.reutilizar_sheet = reutilizar_sheet
        self.etapa = EtapaImagen(bible=bible, imagenes=[], parametros=generador.parametros())
        self._pipe: PipelineImagen | None = None
        self._contar: ContadorTokens = estimar_tokens_clip
        self._ip_embeds: Any = None

    def __enter__(self) -> SesionImagen:
        gen = self.generador
        self.carpeta.mkdir(parents=True, exist_ok=True)
        try:
            with track_stage("imagen_carga") as m_carga:
                try:
                    self._pipe = gen.backend.cargar(gen.cfg)
                except Exception as exc:
                    raise ImageModelError(
                        f"No se pudo cargar el modelo de imagen '{gen.cfg.model_id}': {exc}"
                    ) from exc
            self.etapa.metricas.append(m_carga)
            self.etapa.backend = gen.backend.info()
            self._contar = gen._contador(self._pipe)
            if gen.usar_ip_adapter:
                self._ip_embeds = gen._preparar_ip_adapter(
                    self._pipe,
                    self.etapa.bible,
                    self.carpeta,
                    self._contar,
                    self.etapa,
                    self.reutilizar_sheet,
                )
        except BaseException:
            self._cerrar()
            raise
        return self

    def escena(self, bible: StoryBible, numero: int) -> ResultadoImagen:
        """Ilustra la escena ``numero`` de ``bible`` (puede traer solo las escenas escritas)."""
        if self._pipe is None:
            raise ImageError("La sesión de imagen no está abierta")
        bible = self.generador.asegurar_seeds(bible)
        self.etapa.bible = bible
        resultado = self.generador._generar_escena(
            self._pipe, bible, numero, self.carpeta, self._contar, self._ip_embeds, self.etapa
        )
        self.etapa.imagenes = [r for r in self.etapa.imagenes if r.escena != numero]
        self.etapa.imagenes.append(resultado)
        self.etapa.imagenes.sort(key=lambda r: r.escena)
        return resultado

    def estacionar(self) -> None:
        free_cuda_memory()

    def _cerrar(self) -> None:
        self._pipe = None
        self._ip_embeds = None
        self.generador.backend.liberar()

    def __exit__(self, *_: object) -> None:
        self._cerrar()


# ---------------------------------------------------------------------------------------
# Backend real (diffusers). Imports perezosos: solo se ejecuta en Windows con GPU.
# ---------------------------------------------------------------------------------------
class DiffusersBackend:
    """SD 1.5 en fp16 desde la caché local, con LCM-LoRA o DPM++ 2M Karras e IP-Adapter.

    Mismo procedimiento que validó ``scripts/f0_hello.py`` en la RTX 3050 (F0): SDPA sin
    attention slicing (incompatible con IP-Adapter), VAE slicing y el encoder de imagen de
    IP-Adapter en CPU (ahorra ~1,2 GB de VRAM: solo se pasan los embeddings).
    """

    nombre = "diffusers"

    def __init__(self) -> None:
        self._dispositivo = "cpu"
        self._info: dict[str, Any] = {}

    def cargar(self, cfg: ImageConfig) -> PipelineImagen:
        import diffusers
        import torch
        from diffusers import (
            AutoencoderKL,
            DPMSolverMultistepScheduler,
            LCMScheduler,
            StableDiffusionPipeline,
            StableDiffusionXLPipeline,
        )

        cuda = torch.cuda.is_available()
        self._dispositivo = "cuda" if cuda else "cpu"
        if not cuda:
            logger.warning("imagen_en_cpu", extra=kv(aviso="sin CUDA: fp32 y minutos por imagen"))
        dtype = torch.float16 if cuda else torch.float32
        snapshot = local_snapshot(cfg.model_id)
        variante = diffusers_variant(snapshot) if cuda else None
        vae_revision = None
        if cfg.arquitectura == "sdxl":
            extra: dict[str, Any] = {}
            if cfg.vae_id:
                snapshot_vae = local_snapshot(cfg.vae_id)
                extra["vae"] = AutoencoderKL.from_pretrained(str(snapshot_vae), torch_dtype=dtype)
                vae_revision = snapshot_vae.name
            pipe: Any = StableDiffusionXLPipeline.from_pretrained(
                str(snapshot), torch_dtype=dtype, variant=variante, **extra
            )
        else:
            pipe = StableDiffusionPipeline.from_pretrained(
                str(snapshot),
                torch_dtype=dtype,
                variant=variante,
                safety_checker=None,
                requires_safety_checker=False,
            )
        lora_revision = None
        if cfg.scheduler == "lcm":
            snapshot_lora = local_snapshot(cfg.lcm_lora_id)
            pipe.load_lora_weights(
                str(snapshot_lora),
                weight_name=lora_weight_name(snapshot_lora),
                adapter_name="lcm",
            )
            pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
            lora_revision = snapshot_lora.name
        elif cfg.scheduler == "dpmpp":
            # Recomendado para DreamShaper XL Lightning (4-6 pasos, CFG 2).
            pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
        else:
            pipe.scheduler = DPMSolverMultistepScheduler.from_config(
                pipe.scheduler.config, use_karras_sigmas=True, algorithm_type="dpmsolver++"
            )
        if cfg.attention_slicing and not cfg.ip_adapter.enabled:
            pipe.enable_attention_slicing()
        if cfg.vae_slicing and hasattr(pipe.vae, "enable_slicing"):
            pipe.vae.enable_slicing()
        if cfg.arquitectura == "sdxl" and hasattr(pipe.vae, "enable_tiling"):
            pipe.vae.enable_tiling()  # decodificar 1152x768 sin pico de memoria
        if cfg.unet_fp8 and cuda:
            # Pesos en fp8 (la mitad de memoria) y cálculo en fp16, capa por capa.
            pipe.unet.enable_layerwise_casting(
                storage_dtype=torch.float8_e4m3fn, compute_dtype=torch.float16
            )
        if cfg.cpu_offload and cuda:
            pipe.enable_model_cpu_offload()
        else:
            pipe.to(self._dispositivo)
        pipe.set_progress_bar_config(disable=True)
        self._info = {
            "backend": self.nombre,
            "dispositivo": self._dispositivo,
            "dtype": str(dtype).replace("torch.", ""),
            "variante": variante,
            "torch": torch.__version__,
            "diffusers": diffusers.__version__,
            "modelo_revision": snapshot.name,
            "lcm_lora_revision": lora_revision,
            "arquitectura": cfg.arquitectura,
            "vae_revision": vae_revision,
            "unet_fp8": cfg.unet_fp8,
            "cpu_offload": bool(cfg.cpu_offload and cuda),
        }
        return pipe

    def preparar_ip_adapter(
        self, pipe: PipelineImagen, cfg: ImageConfig, referencia: Image.Image
    ) -> Any:
        import torch
        from transformers import CLIPImageProcessor, CLIPVisionModelWithProjection

        ipc = cfg.ip_adapter
        snapshot = local_snapshot(ipc.repo_id)
        encoder = CLIPVisionModelWithProjection.from_pretrained(
            str(snapshot), subfolder=ipc.image_encoder_subfolder, torch_dtype=torch.float32
        )
        pixeles = CLIPImageProcessor()(images=referencia, return_tensors="pt").pixel_values
        with torch.no_grad():
            embedding = encoder(pixel_values=pixeles).image_embeds  # (1, dim)
        del encoder

        sd_pipe: Any = pipe
        sd_pipe.disable_attention_slicing()
        sd_pipe.load_ip_adapter(
            str(snapshot),
            subfolder=ipc.subfolder,
            weight_name=ipc.weight_name,
            image_encoder_folder=None,
        )
        if cfg.unet_fp8 and self._dispositivo == "cuda":
            capas = restaurar_almacenamiento_fp8(sd_pipe.unet)
            logger.info("unet_fp8_restaurado", extra=kv(capas=capas))
        sd_pipe.set_ip_adapter_scale(ipc.scale)
        dtype = torch.float16 if self._dispositivo == "cuda" else torch.float32
        positivo = embedding.unsqueeze(1).to(self._dispositivo, dtype)  # (batch, n_img, dim)
        # Con CFG real el pipeline espera [negativo, positivo]; LCM con time_cond no usa CFG.
        usa_cfg = cfg.guidance_scale > 1.0 and sd_pipe.unet.config.time_cond_proj_dim is None
        embeds = torch.cat([torch.zeros_like(positivo), positivo]) if usa_cfg else positivo
        self._info["ip_adapter_revision"] = snapshot.name
        return [embeds]

    def generador(self, seed: int) -> Any:
        import torch

        return torch.Generator(self._dispositivo).manual_seed(seed)

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
