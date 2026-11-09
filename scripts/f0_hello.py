"""F0 - "Hola mundo" de cada modalidad, midiendo tiempo y VRAM.

Con ``all`` forma un mini vertical slice: la Story Bible del LLM (si es válida) alimenta
el prompt de imagen, el texto de la voz y el prompt de sonido de la escena 1. Respeta la
regla de 4 GB: un modelo pesado en GPU a la vez y liberación entre etapas.

Salidas en outputs/f0/<fecha_hora>/: imágenes, WAV, story.json, f0_results.json,
resumen.md (tabla lista para el informe) y run.log (JSON Lines).

Uso (PowerShell):
    uv run python scripts/f0_hello.py all
    uv run python scripts/f0_hello.py llm
    uv run python scripts/f0_hello.py image --ip-adapter
    uv run python scripts/f0_hello.py voice
    uv run python scripts/f0_hello.py sound --sound-backends sa3 sao
    uv run python scripts/f0_hello.py eval --out outputs/f0/20261110_090000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from storybook import config  # primero: fija HF_HOME y el modo offline
from storybook.gpu import GPUError, NvmlReader, free_cuda_memory, gpu_used_mb, track_stage
from storybook.hub import (
    ModelNotDownloadedError,
    diffusers_variant,
    is_diffusers_repo,
    local_snapshot,
    lora_weight_name,
    require_piper_voice,
)
from storybook.logging_utils import get_logger, kv, setup_logging
from storybook.schemas import StoryBible, esquema_json_llm, validar_entrada
from storybook.story.llm_client import LLMError, LLMResponseError, OllamaClient
from storybook.story.prompts import mensajes_bible

log = get_logger("f0_hello")

IDEA_POR_DEFECTO = "Una niña descubre que el viejo faro de su pueblo se enciende solo cada noche"
GENERO_POR_DEFECTO = "misterio"
PROMPT_IMAGEN_POR_DEFECTO = (
    "watercolor storybook illustration, muted teal and amber, soft moonlight, girl age 10, "
    "curly red hair, yellow raincoat, standing at the door of an old lighthouse at night"
)
PROMPT_IMAGEN_IP_POR_DEFECTO = (
    "watercolor storybook illustration, muted teal and amber, soft moonlight, girl age 10, "
    "curly red hair, yellow raincoat, climbing a spiral staircase holding a lantern"
)
PROMPT_SONIDO_POR_DEFECTO = "night ocean waves crashing on rocks, gentle wind, distant seagulls"
TEXTO_VOZ_POR_DEFECTO = (
    "Cada noche, cuando el pueblo dormía, el viejo faro se encendía sin que nadie subiera "
    "sus escaleras. Lucía lo observaba desde su ventana, envuelta en su impermeable amarillo, "
    "contando los destellos que barrían el mar. Su abuelo decía que el faro llevaba veinte "
    "años apagado, desde la tormenta que se llevó al último farero. Pero Lucía sabía lo que "
    "veía: una luz cálida, paciente, que giraba como si buscara a alguien entre las olas. "
    "Aquella noche, decidida a descubrir la verdad, tomó la linterna de la cocina, se puso "
    "las botas y salió en silencio por la puerta trasera, siguiendo el camino de piedras "
    "hacia el acantilado."
)
PASOS = ("llm", "image", "voice", "sound", "eval")


class Sesion:
    """Estado compartido entre pasos, persistido en ``f0_results.json``."""

    def __init__(self, carpeta: Path) -> None:
        self.dir = carpeta
        self.dir.mkdir(parents=True, exist_ok=True)
        self.archivo = carpeta / "f0_results.json"
        if self.archivo.is_file():
            self.datos: dict[str, Any] = json.loads(self.archivo.read_text(encoding="utf-8"))
        else:
            self.datos = {"creado": datetime.now().isoformat(timespec="seconds"), "pasos": {}}

    def registrar(self, paso: str, metricas: list[dict[str, Any]], **datos: Any) -> None:
        self.datos["pasos"][paso] = {"metricas": metricas, **datos}
        self.archivo.write_text(
            json.dumps(self.datos, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )

    def paso(self, nombre: str) -> dict[str, Any] | None:
        return self.datos["pasos"].get(nombre)

    @property
    def bible(self) -> StoryBible | None:
        ruta = self.dir / "story.json"
        if not ruta.is_file():
            return None
        return StoryBible.model_validate_json(ruta.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------
# LLM (GPU vía Ollama)
# ---------------------------------------------------------------------------------------
def _esperar_descarga(cliente: OllamaClient, modelo: str, max_s: float = 15.0) -> None:
    limite = time.monotonic() + max_s
    while time.monotonic() < limite:
        if cliente.gpu_fraction(modelo) is None:
            return
        time.sleep(0.5)
    log.warning("ollama_no_libero_a_tiempo", extra=kv(modelo=modelo, espera_s=max_s))


def paso_llm(cfg: config.AppConfig, ses: Sesion, args: argparse.Namespace) -> None:
    from pydantic import ValidationError

    solicitud = validar_entrada(args.idea, args.genero)
    esquema = esquema_json_llm(StoryBible)
    with OllamaClient(cfg.llm.host, cfg.llm.timeout_s) as cliente:
        if not cliente.has_model(cfg.llm.model):
            raise ModelNotDownloadedError(f"Falta el modelo. Ejecuta: ollama pull {cfg.llm.model}")
        fraccion_gpu: float | None = None
        vram_cargado: float | None = None
        try:
            with track_stage("llm_bible") as metrica:
                try:
                    resultado = cliente.chat_json(
                        model=cfg.llm.model,
                        messages=mensajes_bible(solicitud),
                        schema=esquema,
                        temperature=cfg.llm.temperature_narrativa,
                        num_ctx=cfg.llm.num_ctx,
                        think=cfg.llm.think,
                        keep_alive=cfg.llm.keep_alive_etapa,
                        seed=cfg.llm.seed,
                        num_predict=cfg.llm.num_predict,
                    )
                except LLMResponseError as exc:
                    if exc.contenido:
                        parcial = ses.dir / "llm_raw_truncado.txt"
                        parcial.write_text(exc.contenido, encoding="utf-8")
                        metrica.extra.update(
                            tokens_salida=exc.output_tokens,
                            tokens_por_s=round(exc.output_tokens / exc.eval_s, 2)
                            if exc.eval_s
                            else 0.0,
                            salida_parcial=str(parcial),
                        )
                    raise
                metrica.extra.update(
                    tokens_prompt=resultado.prompt_tokens,
                    tokens_salida=resultado.output_tokens,
                    tokens_por_s=resultado.tokens_por_s,
                    carga_modelo_s=resultado.load_s,
                )
        finally:
            # Medir cuánto del modelo quedó en GPU (Ollama hace offload a CPU si no cabe) y
            # liberar la VRAM aunque la generación falle: si el modelo queda cargado, las
            # etapas de imagen y sonido se quedan sin memoria en 4 GB.
            try:
                fraccion_gpu = cliente.gpu_fraction(cfg.llm.model)
                vram_cargado = gpu_used_mb()
                log.info("llm_en_gpu", extra=kv(fraccion=fraccion_gpu, vram_mb=vram_cargado))
            except LLMError as exc:
                log.warning("ollama_ps_fallido", extra=kv(error=str(exc)))
            try:
                cliente.unload(cfg.llm.model)
                _esperar_descarga(cliente, cfg.llm.model)
            except LLMError as exc:
                log.warning("ollama_unload_fallido", extra=kv(error=str(exc)))
        vram_liberado = gpu_used_mb()

    (ses.dir / "llm_raw.json").write_text(resultado.content, encoding="utf-8")
    errores: list[str] = []
    try:
        bible = StoryBible.model_validate_json(resultado.content).con_seeds(
            cfg.consistency.base_seed, cfg.consistency.fixed_seed, cfg.consistency.seed_policy
        )
        (ses.dir / "story.json").write_text(bible.model_dump_json(indent=2), encoding="utf-8")
        titulo = bible.titulo
    except ValidationError as exc:
        errores = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        titulo = None
    metrica.extra.update(bible_valida=not errores, errores_validacion=len(errores))
    log.info(
        "llm_resultado",
        extra=kv(
            valida=not errores,
            titulo=titulo,
            errores=len(errores),
            fraccion_en_gpu=fraccion_gpu,
            vram_cargado_mb=vram_cargado,
            vram_tras_unload_mb=vram_liberado,
        ),
    )
    for error in errores[:8]:
        log.warning("bible_error_validacion", extra=kv(detalle=error))
    ses.registrar(
        "llm",
        [metrica.as_dict()],
        modelo=cfg.llm.model,
        idea=solicitud.idea,
        genero=solicitud.genero_efectivo,
        bible_valida=not errores,
        titulo=titulo,
        errores=errores[:20],
        fraccion_modelo_en_gpu=fraccion_gpu,
        vram_cargado_mb=vram_cargado,
        vram_tras_unload_mb=vram_liberado,
    )


# ---------------------------------------------------------------------------------------
# Imagen (GPU, SD 1.5 fp16 + LCM-LoRA, IP-Adapter opcional)
# ---------------------------------------------------------------------------------------
def _prompts_imagen(cfg: config.AppConfig, ses: Sesion) -> tuple[str, str, str, int]:
    """(prompt escena 1, prompt escena 2 para IP-Adapter, negativo, seed)."""
    bible = ses.bible
    if bible is None:
        return (
            PROMPT_IMAGEN_POR_DEFECTO,
            PROMPT_IMAGEN_IP_POR_DEFECTO,
            cfg.image.negative_prompt_base,
            cfg.consistency.base_seed,
        )

    def construir(numero: int) -> str:
        escena = bible.escena(numero)
        descriptores = [
            bible.personaje(i).descripcion_visual_fija for i in escena.personajes_presentes
        ]
        return ", ".join([bible.estilo_visual.prompt(), *descriptores, escena.prompt_imagen])

    negativo = f"{cfg.image.negative_prompt_base}, {bible.estilo_visual.negative_prompt}"
    seed = bible.escena(1).seed_imagen or cfg.consistency.base_seed
    return construir(1), construir(2), negativo, seed


def paso_imagen(cfg: config.AppConfig, ses: Sesion, args: argparse.Namespace) -> None:
    import torch
    from diffusers import DPMSolverMultistepScheduler, LCMScheduler, StableDiffusionPipeline

    if not torch.cuda.is_available():
        raise GPUError("CUDA no disponible: revisa scripts/check_env.py")
    icfg = cfg.image
    snapshot_modelo = local_snapshot(icfg.model_id)
    variante = diffusers_variant(snapshot_modelo)
    prompt, prompt_ip, negativo, seed = _prompts_imagen(cfg, ses)
    metricas: list[dict[str, Any]] = []
    rutas: list[Path] = []
    datos: dict[str, Any] = {"modelo": icfg.model_id, "variante": variante, "prompt": prompt}
    pipe = None
    try:
        with track_stage("imagen_carga") as m_carga:
            pipe = StableDiffusionPipeline.from_pretrained(
                str(snapshot_modelo),
                torch_dtype=torch.float16,
                variant=variante,
                safety_checker=None,
                requires_safety_checker=False,
            )
            if icfg.scheduler == "lcm":
                snapshot_lora = local_snapshot(icfg.lcm_lora_id)
                pipe.load_lora_weights(
                    str(snapshot_lora),
                    weight_name=lora_weight_name(snapshot_lora),
                    adapter_name="lcm",
                )
                pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
            else:
                pipe.scheduler = DPMSolverMultistepScheduler.from_config(
                    pipe.scheduler.config, use_karras_sigmas=True, algorithm_type="dpmsolver++"
                )
            if icfg.attention_slicing:
                pipe.enable_attention_slicing()
            if icfg.vae_slicing and hasattr(pipe.vae, "enable_slicing"):
                pipe.vae.enable_slicing()
            if icfg.cpu_offload:
                pipe.enable_model_cpu_offload()
            else:
                pipe.to("cuda")
            pipe.set_progress_bar_config(disable=True)
        metricas.append(m_carga.as_dict())

        tokens = len(pipe.tokenizer(prompt).input_ids)
        datos.update(tokens_clip=tokens, truncado=tokens > pipe.tokenizer.model_max_length)
        if datos["truncado"]:
            log.warning(
                "prompt_truncado", extra=kv(tokens=tokens, limite=pipe.tokenizer.model_max_length)
            )

        for i in range(args.repeticiones):
            with track_stage(f"imagen_gen_{i + 1}") as metrica:
                generador = torch.Generator("cuda").manual_seed(seed + i)
                imagen = pipe(
                    prompt=prompt,
                    negative_prompt=negativo,
                    num_inference_steps=icfg.steps,
                    guidance_scale=icfg.guidance_scale,
                    width=icfg.width,
                    height=icfg.height,
                    generator=generador,
                ).images[0]
                metrica.extra.update(pasos=icfg.steps, seed=seed + i, scheduler=icfg.scheduler)
            ruta = ses.dir / f"hello_imagen_{i + 1}.png"
            imagen.save(ruta)
            rutas.append(ruta)
            metricas.append(metrica.as_dict())

        if args.ip_adapter:
            metricas += _probar_ip_adapter(cfg, pipe, rutas[0], prompt_ip, negativo, seed, ses)
            rutas.append(ses.dir / "hello_imagen_ip.png")
            datos["prompt_ip"] = prompt_ip
    except torch.cuda.OutOfMemoryError:
        log.error("oom_imagen", extra=kv(sugerencia="activa image.cpu_offload: true en el perfil"))
        raise
    finally:
        del pipe
        free_cuda_memory()
    datos["imagenes"] = [str(r) for r in rutas]
    datos["vram_tras_liberar_mb"] = gpu_used_mb()
    ses.registrar("image", metricas, **datos)


def _probar_ip_adapter(
    cfg: config.AppConfig,
    pipe: Any,
    referencia: Path,
    prompt: str,
    negativo: str,
    seed: int,
    ses: Sesion,
) -> list[dict[str, Any]]:
    """IP-Adapter sin encoder en GPU: los embeddings de la imagen de referencia se calculan
    en CPU y se pasan precomputados (ahorra ~1,2 GB de VRAM del CLIP ViT-H)."""
    import torch
    from PIL import Image
    from transformers import CLIPImageProcessor, CLIPVisionModelWithProjection

    ipc = cfg.image.ip_adapter
    snapshot_ip = local_snapshot(ipc.repo_id)
    metricas: list[dict[str, Any]] = []
    with track_stage("ip_adapter_embeds_cpu") as m_emb:
        encoder = CLIPVisionModelWithProjection.from_pretrained(
            str(snapshot_ip), subfolder=ipc.image_encoder_subfolder, torch_dtype=torch.float32
        )
        pixeles = CLIPImageProcessor()(
            images=Image.open(referencia).convert("RGB"), return_tensors="pt"
        ).pixel_values
        with torch.no_grad():
            embedding = encoder(pixel_values=pixeles).image_embeds  # (1, dim)
        del encoder
    metricas.append(m_emb.as_dict())

    with track_stage("ip_adapter_carga") as m_carga:
        # IP-Adapter reemplaza los procesadores de atención; con attention slicing activo
        # diffusers 0.42 falla (SlicedAttnProcessor sin slice_size). Con SDPA no hace falta.
        pipe.disable_attention_slicing()
        pipe.load_ip_adapter(
            str(snapshot_ip),
            subfolder=ipc.subfolder,
            weight_name=ipc.weight_name,
            image_encoder_folder=None,
        )
        pipe.set_ip_adapter_scale(ipc.scale)
    metricas.append(m_carga.as_dict())

    positivo = embedding.unsqueeze(1).to("cuda", torch.float16)  # (batch, n_imagenes, dim)
    usa_cfg = cfg.image.guidance_scale > 1.0 and pipe.unet.config.time_cond_proj_dim is None
    embeds = torch.cat([torch.zeros_like(positivo), positivo]) if usa_cfg else positivo
    with track_stage("imagen_gen_ip_adapter") as metrica:
        imagen = pipe(
            prompt=prompt,
            negative_prompt=negativo,
            num_inference_steps=cfg.image.steps,
            guidance_scale=cfg.image.guidance_scale,
            width=cfg.image.width,
            height=cfg.image.height,
            ip_adapter_image_embeds=[embeds],
            generator=torch.Generator("cuda").manual_seed(seed),
        ).images[0]
        metrica.extra.update(ip_scale=ipc.scale, seed=seed)
    imagen.save(ses.dir / "hello_imagen_ip.png")
    metricas.append(metrica.as_dict())
    return metricas


# ---------------------------------------------------------------------------------------
# Voz (CPU, Piper)
# ---------------------------------------------------------------------------------------
def paso_voz(cfg: config.AppConfig, ses: Sesion, args: argparse.Namespace) -> None:
    from piper import PiperVoice, SynthesisConfig

    archivos = require_piper_voice(cfg.voice.piper_voice)
    bible = ses.bible
    texto = bible.escena(1).texto_narrativo if bible else TEXTO_VOZ_POR_DEFECTO
    with track_stage("voz_carga") as m_carga:
        voz = PiperVoice.load(archivos.onnx, config_path=archivos.config, use_cuda=False)
    sintesis = SynthesisConfig(
        length_scale=cfg.voice.length_scale,
        noise_scale=cfg.voice.noise_scale,
        noise_w_scale=cfg.voice.noise_w_scale,
        normalize_audio=True,
        volume=1.0,
    )
    ruta = ses.dir / "hello_voz.wav"
    with track_stage("voz_sintesis") as metrica, wave.open(str(ruta), "wb") as wav:
        voz.synthesize_wav(texto, wav, syn_config=sintesis)
    with wave.open(str(ruta), "rb") as wav:
        frecuencia = wav.getframerate()
        duracion = wav.getnframes() / frecuencia
    metrica.extra.update(
        duracion_audio_s=round(duracion, 2),
        rtf=round(metrica.segundos / duracion, 3) if duracion else None,
        sample_rate=frecuencia,
    )
    ses.registrar(
        "voice",
        [m_carga.as_dict(), metrica.as_dict()],
        voz=cfg.voice.piper_voice,
        texto=texto,
        wav=str(ruta),
        duracion_s=round(duracion, 2),
    )


# ---------------------------------------------------------------------------------------
# Sonido generativo (GPU, Stable Audio vía diffusers, con offload)
# ---------------------------------------------------------------------------------------
def _a_numpy(audio: Any) -> Any:
    """Tensor (canales, muestras) o array 1D -> numpy float32 listo para soundfile."""
    import numpy as np

    if hasattr(audio, "detach"):
        audio = audio.detach().float().cpu().numpy()
    datos = np.asarray(audio, dtype=np.float32)
    return datos.T if datos.ndim == 2 else datos


def _generar_audio(
    cfg: config.AppConfig, backend: str, pipe: Any, prompt: str, gen: Any
) -> tuple[Any, int]:
    if backend == "audioldm":
        salida = pipe(
            prompt,
            negative_prompt=cfg.sound.negative_prompt,
            audio_length_in_s=cfg.sound.duration_s,
            num_inference_steps=cfg.sound.audioldm_steps,
            guidance_scale=cfg.sound.audioldm_guidance,
            generator=gen,
        )
        return salida.audios[0], int(pipe.vocoder.config.sampling_rate)
    if backend == "sa3":
        salida = pipe(
            prompt,
            duration=cfg.sound.duration_s,
            num_inference_steps=cfg.sound.sa3_steps,
            generator=gen,
        )
        return salida.audios[0], int(pipe.vae.config.sampling_rate)
    salida = pipe(
        prompt,
        negative_prompt=cfg.sound.negative_prompt,
        audio_end_in_s=cfg.sound.duration_s,
        num_inference_steps=cfg.sound.sao_steps,
        guidance_scale=cfg.sound.sao_guidance,
        generator=gen,
    )
    return salida.audios[0], int(pipe.vae.sampling_rate)


def paso_sonido(cfg: config.AppConfig, ses: Sesion, args: argparse.Namespace) -> None:
    import soundfile as sf
    import torch

    if not torch.cuda.is_available():
        raise GPUError("CUDA no disponible: revisa scripts/check_env.py")
    bible = ses.bible
    prompt = bible.escena(1).prompt_sonido if bible else PROMPT_SONIDO_POR_DEFECTO
    generativos = ("sa3", "sao", "audioldm")
    backends = args.sound_backends or [b for b in cfg.sound.backends if b in generativos]
    repos = {
        "sa3": cfg.sound.sa3_repo_id,
        "sao": cfg.sound.sao_repo_id,
        "audioldm": cfg.sound.audioldm_repo_id,
    }
    metricas: list[dict[str, Any]] = []
    resultados: dict[str, Any] = {}

    for backend in backends:
        repo = repos[backend]
        try:
            snapshot = local_snapshot(repo)
        except ModelNotDownloadedError as exc:
            resultados[backend] = {"estado": "no_descargado", "detalle": str(exc)}
            log.warning("sonido_no_descargado", extra=kv(backend=backend, repo=repo))
            continue
        if not is_diffusers_repo(snapshot):
            resultados[backend] = {"estado": "formato_no_diffusers"}
            log.warning("sonido_formato_no_soportado", extra=kv(backend=backend, repo=repo))
            continue

        pipe = None
        try:
            with track_stage(f"sonido_{backend}_carga") as m_carga:
                if backend == "sa3":
                    from diffusers import StableAudio3Pipeline as Pipeline
                elif backend == "audioldm":
                    from diffusers import AudioLDMPipeline as Pipeline
                else:
                    from diffusers import StableAudioPipeline as Pipeline
                pipe = Pipeline.from_pretrained(
                    str(snapshot), torch_dtype=torch.float16, variant=diffusers_variant(snapshot)
                )
                # AudioLDM (421M) cabe entero en 4 GB; Stable Audio necesita offload.
                if cfg.sound.cpu_offload and backend != "audioldm":
                    pipe.enable_model_cpu_offload()
                else:
                    pipe.to("cuda")
                pipe.set_progress_bar_config(disable=True)
            metricas.append(m_carga.as_dict())
            archivos: list[str] = []
            for i in range(args.repeticiones):
                with track_stage(f"sonido_{backend}_gen_{i + 1}") as metrica:
                    generador = torch.Generator("cuda").manual_seed(cfg.consistency.base_seed + i)
                    audio, frecuencia = _generar_audio(cfg, backend, pipe, prompt, generador)
                    datos_audio = _a_numpy(audio)
                duracion = datos_audio.shape[0] / frecuencia
                ruta = ses.dir / f"hello_sonido_{backend}_{i + 1}.wav"
                sf.write(ruta, datos_audio, frecuencia)
                archivos.append(str(ruta))
                metrica.extra.update(
                    duracion_audio_s=round(duracion, 2),
                    rtf=round(metrica.segundos / duracion, 3),
                    sample_rate=frecuencia,
                )
                metricas.append(metrica.as_dict())
            resultados[backend] = {"estado": "ok", "repo": repo, "wav": archivos}
        except torch.cuda.OutOfMemoryError as exc:
            resultados[backend] = {"estado": "oom", "detalle": str(exc)[:300]}
            log.error("oom_sonido", extra=kv(backend=backend))
        except Exception as exc:
            resultados[backend] = {
                "estado": "error",
                "detalle": f"{type(exc).__name__}: {exc}"[:500],
            }
            log.exception("sonido_error", extra=kv(backend=backend))
        finally:
            del pipe
            free_cuda_memory()

    ses.registrar(
        "sound", metricas, prompt=prompt, backends=resultados, vram_tras_liberar_mb=gpu_used_mb()
    )
    if not any(r.get("estado") == "ok" for r in resultados.values()):
        raise GPUError(f"Ningún backend generativo de sonido funcionó: {resultados}")


# ---------------------------------------------------------------------------------------
# Evaluación (CPU): WER de la narración y similitud CLIP de las imágenes
# ---------------------------------------------------------------------------------------
def paso_eval(cfg: config.AppConfig, ses: Sesion, args: argparse.Namespace) -> None:
    from storybook.evaluation.asr_check import WhisperChecker
    from storybook.evaluation.clip_metrics import ClipScorer

    ecfg = cfg.evaluation
    metricas: list[dict[str, Any]] = []
    datos: dict[str, Any] = {}

    voz = ses.paso("voice")
    if voz and voz.get("wav"):
        with track_stage("eval_whisper_carga") as m_carga:
            checker = WhisperChecker(
                ecfg.whisper_model,
                ecfg.whisper_compute_type,
                ecfg.whisper_language,
                ecfg.cpu_threads,
            )
        with track_stage("eval_wer") as metrica:
            resultado = checker.evaluar(Path(voz["wav"]), voz["texto"])
            metrica.extra.update(wer=resultado.wer)
        metricas += [m_carga.as_dict(), metrica.as_dict()]
        datos.update(wer=resultado.wer, transcripcion=resultado.transcripcion)
    else:
        log.warning("eval_sin_voz", extra=kv(accion="ejecuta antes el paso voice"))

    imagen = ses.paso("image")
    if imagen and imagen.get("imagenes"):
        rutas = [Path(r) for r in imagen["imagenes"]]
        with track_stage("eval_clip_carga") as m_carga:
            scorer = ClipScorer(ecfg.clip_model, ecfg.clip_pretrained)
        with track_stage("eval_clip") as metrica:
            datos["clip_imagen_texto"] = scorer.imagen_texto(rutas[0], imagen["prompt"])
            if len(rutas) >= 2:
                datos["clip_imagen_imagen"] = scorer.imagen_imagen(rutas)
            metrica.extra.update(clip_imagen_texto=datos["clip_imagen_texto"])
        metricas += [m_carga.as_dict(), metrica.as_dict()]
    else:
        log.warning("eval_sin_imagenes", extra=kv(accion="ejecuta antes el paso image"))

    ses.registrar("eval", metricas, **datos)


# ---------------------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------------------
def _fmt(valor: Any) -> str:
    return "-" if valor is None else str(valor)


def escribir_resumen(ses: Sesion, cfg: config.AppConfig, total_s: float) -> Path:
    lector = NvmlReader()
    gpu = lector.info()
    lector.close()
    lineas = [
        f"# Resultados F0 - {ses.datos['creado']}",
        "",
        f"- Perfil: `{cfg.profile}` - GPU: {gpu.get('nombre', 'n/d')} "
        f"({_fmt(gpu.get('vram_total_mb'))} MB), driver {gpu.get('driver', 'n/d')}",
        f"- Tiempo total del script: {total_s:.1f} s",
        "",
        "| Etapa | Segundos | Dispositivo | VRAM torch pico (MB) | VRAM GPU pico (MB) | Datos |",
        "|---|---:|---|---:|---:|---|",
    ]
    for paso in PASOS:
        registro = ses.paso(paso)
        if not registro:
            continue
        if registro.get("error"):
            lineas.append(f"| {paso} | - | - | - | - | ERROR: {registro['error'][:80]} |")
        for m in registro.get("metricas", []):
            extra = ", ".join(f"{k}={v}" for k, v in m.get("extra", {}).items())
            lineas.append(
                f"| {m['etapa']} | {m['segundos']} | {m['dispositivo']} | "
                f"{_fmt(m['vram_torch_pico_mb'])} | {_fmt(m['vram_gpu_pico_mb'])} | {extra} |"
            )
    llm = ses.paso("llm") or {}
    evaluacion = ses.paso("eval") or {}
    lineas += [
        "",
        f"- Story Bible válida al primer intento: {_fmt(llm.get('bible_valida'))} "
        f"(errores: {len(llm.get('errores', []))}); fracción del LLM en GPU: "
        f"{_fmt(llm.get('fraccion_modelo_en_gpu'))}",
        f"- WER narración: {_fmt(evaluacion.get('wer'))} - CLIP imagen-texto: "
        f"{_fmt(evaluacion.get('clip_imagen_texto'))} - CLIP imagen-imagen: "
        f"{_fmt(evaluacion.get('clip_imagen_imagen'))}",
    ]
    ruta = ses.dir / "resumen.md"
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return ruta


# ---------------------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="F0: hola mundo por modalidad")
    parser.add_argument("paso", choices=[*PASOS, "all"])
    parser.add_argument("--profile", default="rapido")
    parser.add_argument("--out", type=Path, default=None, help="Carpeta de una sesión previa")
    parser.add_argument("--idea", default=IDEA_POR_DEFECTO)
    parser.add_argument("--genero", default=GENERO_POR_DEFECTO)
    parser.add_argument("--ip-adapter", action="store_true", help="Probar también IP-Adapter")
    parser.add_argument(
        "--sound-backends", nargs="+", choices=["sa3", "sao", "audioldm"], default=None
    )
    parser.add_argument(
        "--repeticiones",
        type=int,
        default=2,
        help="Generaciones por modelo (la 2.ª mide el tiempo 'en caliente')",
    )
    args = parser.parse_args()

    carpeta = args.out or config.OUTPUTS_DIR / "f0" / datetime.now().strftime("%Y%m%d_%H%M%S")
    if not carpeta.is_absolute():
        carpeta = config.PROJECT_ROOT / carpeta
    ses = Sesion(carpeta)
    setup_logging(log_file=carpeta / "run.log")
    cfg = config.load_config(args.profile)
    log.info("f0_inicio", extra=kv(paso=args.paso, perfil=cfg.profile, salida=str(carpeta)))

    funciones: dict[str, Callable[[config.AppConfig, Sesion, argparse.Namespace], None]] = {
        "llm": paso_llm,
        "image": paso_imagen,
        "voice": paso_voz,
        "sound": paso_sonido,
        "eval": paso_eval,
    }
    pasos = PASOS if args.paso == "all" else (args.paso,)
    fallidos: list[str] = []
    inicio = time.perf_counter()
    for paso in pasos:
        try:
            funciones[paso](cfg, ses, args)
        except (LLMError, ModelNotDownloadedError, GPUError) as exc:
            fallidos.append(paso)
            log.error("paso_fallido", extra=kv(paso=paso, causa=str(exc)))
            ses.registrar(paso, [], error=f"{type(exc).__name__}: {exc}")
        except Exception as exc:
            fallidos.append(paso)
            log.exception("paso_fallido", extra=kv(paso=paso))
            ses.registrar(paso, [], error=f"{type(exc).__name__}: {exc}")
    total = time.perf_counter() - inicio
    resumen = escribir_resumen(ses, cfg, total)
    log.info("f0_fin", extra=kv(total_s=round(total, 1), fallidos=fallidos, resumen=str(resumen)))
    return 1 if fallidos else 0


if __name__ == "__main__":
    sys.exit(main())
