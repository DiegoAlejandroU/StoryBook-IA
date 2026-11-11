# Modelos utilizados

Restricción de diseño: GPU de 4 GB de VRAM (RTX 3050 Laptop), 24 GB de RAM y ejecución
sin conexión. Se carga un único modelo pesado en la GPU por etapa; voz, ASR, CLIP y mezcla
se ejecutan en CPU. La revisión exacta (commit) y la licencia declarada de cada repositorio
descargado se registran automáticamente en `docs/models_registry.json`.

## Modelos seleccionados

| Modalidad | Modelo | Fuente | Licencia | Ejecución | Revisión y estado (11 nov 2026) |
|---|---|---|---|---|---|
| Texto | Qwen3-4B-Instruct-2507 (Q4_K_M, ~2,5 GB) | Ollama `qwen3:4b-instruct-2507-q4_K_M` | Apache 2.0 | GPU completa | **En uso** en los dos perfiles. Etiqueta verificada en Ollama. |
| Texto (experimento F6) | Qwen3-8B (Q4_K_M, ~5,2 GB) | Ollama `qwen3:8b` | Apache 2.0 | GPU + CPU (offload) | Razonamiento desactivado (`think: false`). Fue el LLM del perfil calidad hasta el 10 nov; la tarea 1.4 midió ~16 min por historia solo de texto, así que calidad usa el 4B (`configs/experiments/llm_8b.yaml`). |
| Imagen | DreamShaper 8 (fine-tune de SD 1.5) | HF `Lykon/dreamshaper-8` | CreativeML OpenRAIL-M | GPU fp16 | `a7e52b9`. **En uso**. |
| Imagen (aceleración) | LCM-LoRA SD 1.5 | HF `latent-consistency/lcm-lora-sdv1-5` | OpenRAIL++ | GPU fp16 | `cf2fced`. **En uso** (perfil rápido, 6 pasos). |
| Imagen (consistencia) | IP-Adapter SD 1.5 + encoder CLIP ViT-H | HF `h94/IP-Adapter` | Apache 2.0 | Adaptador en GPU; encoder en CPU | `018e402`. **En uso**, escala 0,4 y orden `accion_primero` (tarea 2.3). |
| Voz | Piper `es_MX-claude-high` | HF `rhasspy/piper-voices` | Código piper-tts: GPL-3.0-or-later; voz: según su MODEL_CARD | CPU (ONNX) | **En uso**. Diego la eligió al escuchar 3 voces en la tarea 3.3: `es_MX-claude-high`, `es_ES-davefx-medium` y `es_MX-ald-medium`. |
| Sonido (A, principal) | Stable Audio 3 Small-SFX (0,6 B) | HF `stabilityai/stable-audio-3-small-sfx` | Stability AI Community License; encoder T5Gemma bajo Gemma Terms of Use | GPU fp16 con offload | **No disponible** en el equipo de referencia: el repositorio exige aceptar la licencia con una cuenta. La cadena pasa sola a AudioLDM (`sonido:sa3:no_disponible`). |
| Sonido (A, alternativa) | Stable Audio Open 1.0 | HF `stabilityai/stable-audio-open-1.0` | Stability AI Community License (gated) | GPU fp16 con offload | No descargado (mismo motivo). Solo en el perfil calidad. |
| Sonido (A, sin token) | AudioLDM s-full (421M) — sugerido en el curso | HF `cvssp/audioldm` | CC BY-NC-SA 4.0 (uso académico no comercial) | GPU fp16 (sin offload) | `8ed5f64`. **En uso** en los dos perfiles. Se le agrega al prompt ", high quality, clear" (tarea 6.2: 20 de 20 escenas con ambiente apto, frente a 13 de 20 sin el sufijo). |
| Sonido (B y C) | Biblioteca CC0 curada y síntesis procedural propia | `assets/sfx/`, `src/storybook/sound/` | CC0 / código propio (MIT) | CPU | La biblioteca está vacía en el equipo de referencia. La síntesis procedural cubre las 21 etiquetas de sonido y es el último respaldo. |
| Evaluación (WER) | faster-whisper small (int8) | HF `Systran/faster-whisper-small` | MIT | CPU | `536b066`. |
| Evaluación (CLIP) | OpenCLIP ViT-B-32 `laion2b_s34b_b79k` | HF `laion/CLIP-ViT-B-32-laion2B-s34B-b79K` | MIT | CPU | — |

## Mediciones en el equipo de referencia

RTX 3050 Laptop de 4 GB y 24 GB de RAM. Fuentes: tareas 1.4, 2.3, 3.3, 4.4 y 6.2
(`docs/evidencias/` y [`docs/informe/analisis_experimentos.md`](docs/informe/analisis_experimentos.md)).

| Modelo | Tiempo | Memoria | Calidad medida |
|---|---|---|---|
| Qwen3 4B (Ollama, `num_ctx` 4096, `num_gpu` 99) | 75 s por Story Bible (mediana), 43 tok/s | ~2,5 GB, 100 % en GPU | 9/10 Story Bibles válidas, 1,07 intentos por llamada |
| Qwen3 8B (experimento) | 982 s por Story Bible, 3 tok/s | 39 % en GPU, resto en CPU | 9/10 válidas, 1,57 intentos por llamada |
| DreamShaper 8 + LCM-LoRA, 6 pasos, IP-Adapter 0,4 | 3,4 s por imagen; ~27 s por historia, con la *character sheet* | 3,16 GB asignados por torch (4,03 GB reservados) | CLIP img-img 0,765; CLIP img-texto 0,319 |
| DreamShaper 8, DPM++ 25 pasos (perfil calidad) | 8,2 s por imagen; ~55 s por historia | 3,01 GB asignados | CLIP img-img 0,778; CLIP img-texto 0,347 |
| Piper `es_MX-claude-high` | ~9 s para las 5 narraciones (CPU) | — | WER de 3,5 a 4,8 % en la batería 6.2 (8,3 % de mediana en la prueba de voces 3.3) |
| AudioLDM + sufijo de calidad | ~1,3 s por clip de 8 s | 0,94 GB asignados | 20/20 escenas con ambiente apto |
| faster-whisper small (int8) y OpenCLIP ViT-B-32 | Solo para evaluación | CPU | — |

## Alternativas descartadas

| Alternativa | Motivo |
|---|---|
| SDXL, FLUX | Exceden 4 GB de VRAM; requieren offload secuencial y tardan minutos por imagen. |
| LLM de más de 8B parámetros | No caben en 4 GB ni con offload parcial a tiempos aceptables. |
| Qwen3.5-4B | Modelo multimodal (proyector de visión adicional); ~5,5 GB de memoria total en 4 bits, y sus GGUF no eran compatibles con Ollama según la documentación de Unsloth. |
| Stable Audio Open Small (vía `stable-audio-tools`) | `stable-audio-tools` 0.0.20 exige Python < 3.11 y fija `torch==2.7.1`, incompatible con el entorno del proyecto (Python 3.12, PyTorch 2.15). |
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
| Qwen3-0.6B | No evaluado | La comparación de tamaño se hizo entre 4B y 8B (tarea 1.4). Con 0.6B se espera menos coherencia narrativa; queda como trabajo futuro. |
| Stable Diffusion v1.4 | Misma arquitectura que la base elegida (SD 1.x) | Se usa DreamShaper 8 (fine-tune de SD 1.5) por su estilo ilustrativo; LCM-LoRA e IP-Adapter SD1.5 son compatibles con la familia. SD v1.4 puede usarse como línea base en los experimentos. |
| Stable Diffusion XL Base 1.0 | Descartado | Con 4 GB requiere offload secuencial: minutos por imagen, inviable para 5 escenas en la demo. |
| FLUX.1-schnell | Descartado | Excede ampliamente 4 GB de VRAM (perfil "Avanzada"). |
| Piper TTS (voces en español) | **Principal** (voz `es_MX-claude-high`, CPU) | Rápido en CPU, no compite por la VRAM y es fácil de reproducir. |
| XTTS-v2 | Descartado | Compite por la VRAM, su licencia (CPML) restringe el uso y su función de clonación de voz no se necesita (ver ética). |
| AudioLDM | **Backend de sonido en uso** | 421M parámetros, cabe en 4 GB y no exige aceptar licencias; garantiza sonido generado aunque falte el acceso a Stable Audio. |
| MusicGen Small | No incluido | El enunciado pide ambientes y efectos por escena, no música; su licencia es CC BY-NC 4.0. Queda como trabajo futuro. |
| Stable Audio Open 1.0 | Incluido en la cadena del perfil calidad (no descargado) | Mejor calidad que AudioLDM, pero más lento con offload en 4 GB, y exige aceptar su licencia. |
| — (posterior al resumen) Stable Audio 3 Small-SFX | Primera opción de la cadena de sonido | Publicado en mayo de 2026 y pensado para efectos de sonido en portátiles de consumo. Exige aceptar su licencia: en el equipo de referencia no está, así que se usa AudioLDM. |

Herramientas del resumen usadas: Transformers, Diffusers, Ollama, Piper y Streamlit. No se usan
Pydub (requiere ffmpeg; se reemplaza por `soundfile`, `scipy` y `pyloudnorm`), Coqui TTS,
AudioCraft ni Stable Audio Tools (incompatibles con el entorno o innecesarios). Gradio y Pygame
son alternativas de interfaz; se eligió Streamlit.

