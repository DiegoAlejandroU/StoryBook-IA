# Modelos utilizados

Restricción de diseño: GPU de 4 GB de VRAM (RTX 3050 Laptop), 24 GB de RAM y ejecución
sin conexión. Se carga un único modelo pesado en la GPU por etapa; voz, ASR, CLIP y mezcla
se ejecutan en CPU. La revisión exacta (commit) y la licencia declarada de cada repositorio
descargado se registran automáticamente en `docs/models_registry.json`.

## Modelos seleccionados

| Modalidad | Modelo | Fuente | Licencia | Ejecución | Estado de verificación |
|---|---|---|---|---|---|
| Texto | Qwen3-4B-Instruct-2507 (Q4_K_M, ~2,5 GB) | Ollama `qwen3:4b-instruct-2507-q4_K_M` | Apache 2.0 | GPU completa | Etiqueta verificada |
| Texto (perfil calidad) | Qwen3-8B (Q4_K_M, ~5,2 GB) | Ollama `qwen3:8b` | Apache 2.0 | GPU + CPU (offload) | Razonamiento desactivado (`think: false`) |
| Imagen | DreamShaper 8 (fine-tune de SD 1.5) | HF `Lykon/dreamshaper-8` | CreativeML OpenRAIL-M | GPU fp16 | Confirmar en el registro |
| Imagen (aceleración) | LCM-LoRA SD 1.5 | HF `latent-consistency/lcm-lora-sdv1-5` | Ver registro | GPU fp16 | Confirmar en el registro |
| Imagen (consistencia) | IP-Adapter SD 1.5 + encoder CLIP ViT-H | HF `h94/IP-Adapter` | Apache 2.0 | Adaptador en GPU; encoder en CPU | Confirmar en el registro |
| Voz | Piper `es_MX-claude-high` | HF `rhasspy/piper-voices` | Código piper-tts: GPL-3.0-or-later; voz: según su MODEL_CARD | CPU (ONNX) | Revisar MODEL_CARD descargado |
| Sonido (A, principal) | Stable Audio 3 Small-SFX (0,6 B) | HF `stabilityai/stable-audio-3-small-sfx` | Stability AI Community License; encoder T5Gemma bajo Gemma Terms of Use | GPU fp16 con offload | Pendiente: confirmar formato diffusers |
| Sonido (A, alternativa) | Stable Audio Open 1.0 | HF `stabilityai/stable-audio-open-1.0` | Stability AI Community License (gated) | GPU fp16 con offload | Soportado por `StableAudioPipeline` |
| Sonido (A, sin token) | AudioLDM s-full (421M) — sugerido en el curso | HF `cvssp/audioldm` | CC BY-NC-SA 4.0 (uso académico no comercial) | GPU fp16 (sin offload) | Soportado por `AudioLDMPipeline`; no es gated, se descarga sin `HF_TOKEN` |
| Sonido (B y C) | Biblioteca CC0 curada y síntesis procedural propia | `assets/sfx/`, `src/storybook/sound/` | CC0 / código propio (MIT) | CPU | Fase 4 |
| Evaluación (WER) | faster-whisper small (int8) | HF `Systran/faster-whisper-small` | MIT | CPU | — |
| Evaluación (CLIP) | OpenCLIP ViT-B-32 `laion2b_s34b_b79k` | HF `laion/CLIP-ViT-B-32-laion2B-s34B-b79K` | MIT | CPU | — |

## Alternativas descartadas

| Alternativa | Motivo |
|---|---|
| SDXL, FLUX | Exceden 4 GB de VRAM; requieren offload secuencial y tardan minutos por imagen. |
| LLM de más de 8B parámetros | No caben en 4 GB ni con offload parcial a tiempos aceptables. |
| Qwen3.5-4B | Modelo multimodal (proyector de visión adicional); ~5,5 GB de memoria total en 4 bits, y sus GGUF no eran compatibles con Ollama según la documentación de Unsloth. |
| Stable Audio Open Small (vía `stable-audio-tools`) | `stable-audio-tools` 0.0.20 exige Python < 3.11 y fija `torch==2.7.1`, incompatible con el entorno del proyecto (Python 3.11, PyTorch 2.15). |
| XTTS-v2 en GPU | Compite por la VRAM con imagen y sonido; además su licencia (CPML) restringe el uso. |
| PyTorch con CUDA 12.x | PyTorch 2.15 ya no publica ruedas cu12x; se usa cu132 (o torch 2.14 + cu126 si el driver no admite CUDA 13). |
| `torchaudio` | Congelado en 2.11.x; el audio se maneja con `soundfile`, `scipy` y `pyloudnorm`. |
| Safety checker de SD 1.5 | Consume ~600 MB de VRAM; se sustituye por prompts negativos, reglas de contenido por género y revisión humana (ver informe, sección de ética). |

## Relación con el resumen de modelos entregado en clase

El curso entregó un resumen orientativo de modelos y combinaciones ("Accesible", "Equilibrada" y
"Avanzada"). Esta tabla deja trazado qué se tomó de esa lista y por qué, con la restricción de
4 GB de VRAM del equipo de referencia.

| Modelo del resumen | Uso en StoryBook | Justificación |
|---|---|---|
| Qwen3-4B-Instruct-2507 | **Principal** (texto, perfil rápido), vía Ollama Q4_K_M | ~2,5 GB: cabe completo en VRAM y genera JSON estructurado en español. |
| Qwen3-0.6B | Candidato para el experimento de tamaño de LLM (0.6B vs 4B vs 8B) | Muy rápido, pero con menor coherencia narrativa; sirve para mostrar el trade-off con datos. |
| Stable Diffusion v1.4 | Misma arquitectura que la base elegida (SD 1.x) | Se usa DreamShaper 8 (fine-tune de SD 1.5) por su estilo ilustrativo; LCM-LoRA e IP-Adapter SD1.5 son compatibles con la familia. SD v1.4 puede usarse como línea base en los experimentos. |
| Stable Diffusion XL Base 1.0 | Descartado | Con 4 GB requiere offload secuencial: minutos por imagen, inviable para 5 escenas en la demo. |
| FLUX.1-schnell | Descartado | Excede ampliamente 4 GB de VRAM (perfil "Avanzada"). |
| Piper TTS (voces en español) | **Principal** (voz `es_MX-claude-high`, CPU) | Rápido en CPU, no compite por la VRAM y es fácil de reproducir. |
| XTTS-v2 | Descartado | Compite por la VRAM, su licencia (CPML) restringe el uso y su función de clonación de voz no se necesita (ver ética). |
| AudioLDM | **Incluido** como backend generativo sin token | 421M parámetros, cabe en 4 GB y no exige aceptar licencias; garantiza sonido generado aunque falte el acceso a Stable Audio. |
| MusicGen Small | No incluido | El enunciado pide ambientes y efectos por escena, no música; su licencia es CC BY-NC 4.0. Queda como trabajo futuro. |
| Stable Audio Open 1.0 | **Incluido** (perfil calidad) | Mejor calidad que AudioLDM, pero más lento con offload en 4 GB. |
| — (posterior al resumen) Stable Audio 3 Small-SFX | **Principal** de sonido | Publicado en mayo de 2026 y pensado para efectos de sonido en portátiles de consumo. |

Herramientas del resumen usadas: Transformers, Diffusers, Ollama, Piper y Streamlit. No se usan
Pydub (requiere ffmpeg; se reemplaza por `soundfile`, `scipy` y `pyloudnorm`), Coqui TTS,
AudioCraft ni Stable Audio Tools (incompatibles con el entorno o innecesarios). Gradio y Pygame
son alternativas de interfaz; se eligió Streamlit.

