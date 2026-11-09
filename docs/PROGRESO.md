# Progreso del proyecto StoryBook IA

Este archivo es el estado compartido entre todas las sesiones de trabajo: Diego, Claude Code en Windows, la conversación del proyecto en Claude y las ejecuciones automáticas programadas. Cada sesión lo lee al empezar y lo actualiza al terminar (ver `CLAUDE.md` §3). El calendario día por día está en `docs/cronograma.md`: entrega y sustentación el lunes 23 de noviembre de 2026.

**Leyenda**
- `[ ]` pendiente · `[x]` hecha · `[~]` bloqueada (indicar el motivo)
- `[AUTO]`: se puede hacer en las ejecuciones automáticas (shell Linux, sin GPU ni pesos): código, tests con backends falsos y documentación.
- `[WINDOWS]`: requiere el portátil (GPU, Ollama, descargas de modelos, ejecución real, git). La hace Diego o Claude Code en Windows.
- `(dep: X)`: no empezar hasta que X esté hecha.
- Si una tarea `[ ]` dice "ya existe …", el archivo existe y hay que completarla (tests o partes faltantes), no reescribirla desde cero.

---

## F0 · Setup
- [x] 0.1 [WINDOWS] Inicializar git en esta carpeta (`git init -b main`), conectar `origin` (https://github.com/DiegoAlejandroU/StoryBook-IA.git) y hacer el primer commit con todo lo que no está en `.gitignore`. Push.
- [x] 0.2 [AUTO] Esqueleto del proyecto: `pyproject.toml`, `.gitignore`, `.env.example`, `.python-version`, `LICENSE`, `.streamlit/config.toml`, estructura de `src/storybook/`, `tests/`, `configs/`, `assets/`, `samples/` y `experiments/`. (ZIP F0)
- [x] 0.3 [AUTO] `config.py` (perfiles YAML con `extends`, modo offline, `HF_HOME`), `configs/*.yaml`, `logging_utils.py` y `hub.py`, con tests en `test_config_hub.py`. (ZIP F0)
- [x] 0.4 [AUTO] `scripts/check_env.py`, `scripts/download_models.py` (registra revisión y licencia en `docs/models_registry.json`) y `scripts/f0_hello.py` (prueba por modalidad con tiempos y VRAM). (ZIP F0)
- [x] 0.5 [WINDOWS] Instalar el entorno (ver README):
  1. Ejecutar `nvidia-smi` y anotar el "CUDA Version". Si es menor a 13.2, actualizar el driver con la NVIDIA App.
  2. `uv venv --python-preference only-system --python 3.12` y luego `uv sync`.
  3. Confirmar que torch ve la GPU: `torch.version.cuda` no es `None` y `torch.cuda.is_available()` es `True`.
  4. `uv run pytest` en verde.
  5. `uv run python scripts/check_env.py` sin FALLO. Guardar su salida en `docs/evidencias/`. (dep: 0.2, 0.4)
- [ ] 0.6 [WINDOWS] Descargar modelos y hacer la prueba por modalidad (descargas OK; repetir `f0_hello` tras las correcciones del 9-nov 17:45):
  1. Fijar `OLLAMA_FLASH_ATTENTION=1` y `OLLAMA_KV_CACHE_TYPE=q8_0` y reiniciar Ollama.
  2. Aceptar en Hugging Face las licencias de `stabilityai/stable-audio-3-small-sfx` y `stabilityai/stable-audio-open-1.0`, y poner `HF_TOKEN` en `.env`.
  3. `uv run python scripts/download_models.py`.
  4. `uv run python scripts/f0_hello.py all --ip-adapter`.
  5. Guardar `resumen.md` (tiempos y VRAM por etapa) en `docs/evidencias/` y ajustar `configs/` si algo no cabe en 4 GB. (dep: 0.5)

## F1 · Historia (texto)
- [x] 1.1 [AUTO] `schemas.py`: Story Bible en Pydantic v2 con validadores (exactamente 5 escenas, fases, ids de personajes, longitudes, límites de tokens), `StoryRequest` con la validación de entrada y JSON Schema para Ollama. Tests en `test_schemas.py` y `test_input_validation.py`. (ZIP F0)
- [x] 1.2 [AUTO] Ya existe `story/llm_client.py` (ZIP F0). Falta `tests/test_llm_client.py` con transporte HTTP simulado (`httpx.MockTransport`), que cubra:
  - respuesta válida;
  - JSON inválido;
  - 4 y 6 escenas;
  - reintentos devolviendo al modelo el error de validación;
  - `think=false` y `keep_alive` en el payload;
  - errores de conexión y de modelo no encontrado.

  Corregir el cliente si los tests revelan fallos. (dep: 1.1)
- [x] 1.3 [AUTO] Ya existe `story/prompts.py`. Falta:
  - `story/planner.py` con la estrategia (a), una llamada, y la (b), plan y luego escenas con canon y resúmenes;
  - `story/auditor.py`, que detecta contradicciones y regenera la escena afectada;
  - tests con un LLM falso. (dep: 1.2)
- [ ] 1.4 [WINDOWS] 10 generaciones reales con 4B y con 8B: tasa de JSON válido, tiempos, revisión de la calidad del español. (dep: 0.6, 1.3)

## F2 · Imágenes y consistencia visual
- [x] 2.1 [AUTO] `image/prompt_builder.py`: compone estilo + personajes presentes + acción, controla el límite de 77 tokens con un tokenizer inyectable (estimador heurístico en tests), recorta por prioridad y registra los truncamientos. Tests. (dep: 1.1)
- [ ] 2.2 [AUTO] Ya existe `gpu.py` (carga, liberación y medición de VRAM). Falta:
  - `image/generator.py`: diffusers con DreamShaper 8 + LCM-LoRA + IP-Adapter según `configs/`, imports perezosos y `hub.local_snapshot` para cargar offline;
  - `image/consistency.py`: character sheet del protagonista;
  - tests con un pipeline falso. (dep: 0.3, 2.1)
- [ ] 2.3 [WINDOWS] Prueba real: 5 imágenes de una historia, sin OOM; ajustar steps, CFG y resolución; medir tiempos y VRAM. (dep: 0.6, 2.2)

## F3 · Voz
- [ ] 3.1 [AUTO] `voice/tts.py`: Protocol `TTSBackend` con backends Piper (`hub.require_piper_voice`) y Kokoro (opcional), ambos con imports perezosos; voz y parámetros desde la configuración; salida WAV y duración. Tests con un backend falso. (dep: 0.3)
- [ ] 3.2 [AUTO] Ya existe `evaluation/asr_check.py`. Falta `tests/test_asr_check.py` con un transcriptor falso: WER, normalización del español y casos borde. (dep: 0.3)
- [ ] 3.3 [WINDOWS] Escuchar la voz `es_MX-claude-high` y 1–2 alternativas, elegir y medir el WER real. (dep: 0.6, 3.1, 3.2)

## F4 · Sonido y mezcla
- [ ] 4.1 [AUTO] `sound/procedural.py`: síntesis con numpy/scipy de viento, lluvia, fuego, latidos, drone oscuro, pasos, olas, bosque/pájaros y ambiente mágico. Mapeo desde `EtiquetaSonido` (schemas) a recetas. Tests: duración, sample rate, sin clipping, sin NaN. (dep: 0.3)
- [ ] 4.2 [AUTO] Sonido con fallback en cadena:
  - `sound/library.py`: índice JSON por etiquetas para `assets/sfx/`.
  - `sound/generator.py`: recorre `sound.backends` de la configuración (`sa3` → `sao` → `audioldm` → `library` → `procedural`), con imports perezosos de diffusers (`StableAudio3Pipeline`, `StableAudioPipeline`, `AudioLDMPipeline`; ver `scripts/f0_hello.py` como referencia), y registra el fallback usado.

  Tests con generadores falsos que fallan. (dep: 4.1)
- [ ] 4.3 [AUTO] `sound/mixer.py`: loop con crossfade hasta la duración de la voz, LUFS con pyloudnorm, ambiente 12–18 dB bajo la voz, ducking y exportación de `ambience_n.wav` y `mix_n.wav`. Tests con señales sintéticas. (dep: 4.1)
- [ ] 4.4 [WINDOWS] Prueba real de SA3 Small-SFX y de AudioLDM: confirmar el formato diffusers, medir VRAM y tiempo, y comparar la pertinencia del sonido. Si SA3 no cabe, probar SAO 1.0 con offload. (dep: 0.6, 4.2)

## F5 · Integración, persistencia y UI
- [ ] 5.1 [AUTO] `storage.py` (run_id, estructura de `outputs/`, `manifest.json`, cargar historias) y `pipeline.py` (orquestación por etapas, callback de progreso, fallbacks, regenerar una escena). `tests/test_pipeline_mock.py`: el pipeline completo con backends falsos produce 5 escenas con todos sus archivos y su manifest. (dep: 1.3, 2.2, 3.1, 4.3)
- [ ] 5.2 [AUTO] `app/streamlit_app.py`:
  - formulario validado y selector de perfil;
  - `st.status` por etapa;
  - visor con imagen, texto y tres reproductores;
  - Anterior/Siguiente con indicador n/5;
  - regenerar escena;
  - cargar historias de `outputs/` y `samples/`;
  - etiqueta "Contenido generado por IA".

  La lógica va en módulos testeables; Streamlit se importa solo en la app. Opción `--mock` para probar la UI sin GPU. (dep: 5.1)
- [ ] 5.3 [AUTO] `scripts/verify_offline.py`: bloquea sockets salvo localhost, corre el pipeline con backends falsos o reales según una bandera e informa cualquier intento de conexión externa. (dep: 5.1)
- [ ] 5.4 [WINDOWS] Prueba de punta a punta real con el Wi-Fi apagado; generar 2–3 historias para `samples/`. (dep: 2.3, 3.3, 4.4, 5.2)

## F6 · Experimentos
- [ ] 6.1 [AUTO] Ya existe `evaluation/clip_metrics.py`. Falta:
  - `evaluation/report.py`;
  - `scripts/run_experiment.py` (escribe en `experiments/results.csv` con las columnas existentes);
  - `scripts/make_contact_sheet.py`;
  - tests con datos falsos. (dep: 5.1)
- [ ] 6.2 [WINDOWS] Ejecutar la batería completa: C1/C2/C3 × 4 géneros, más 4B vs 8B (opcional: Qwen3-0.6B, del resumen de clase), LCM vs 25 pasos y SA3 vs AudioLDM → `experiments/results.csv` + evidencias. (dep: 5.4, 6.1)
- [ ] 6.3 [AUTO] Análisis de `results.csv`: gráficas, tablas y conclusiones en `docs/informe/`. (dep: 6.2)

## F7 · Documentación y video
- [ ] 7.1 [AUTO] Completar `README.md` (ya existe la base de F0), `MODELS.md` y `docs/arquitectura.md` con diagramas Mermaid de componentes y de flujo de datos. Marcar `[DATO PENDIENTE]` donde falten mediciones. (dep: 5.1)
- [ ] 7.2 [AUTO] Borrador del informe técnico en `docs/informe/informe.md` con las 12 secciones de CLAUDE.md §16, marcando `[DATO PENDIENTE]` donde falten resultados reales. (dep: 7.1)
- [ ] 7.3 [WINDOWS] Completar el informe con los datos reales y exportarlo a PDF; grabar el video demo. (dep: 6.2, 7.2)

## F8 · Sustentación
- [ ] 8.1 [AUTO] `docs/sustentacion.md`: guion de la demo, plan B, 30 preguntas probables del jurado con respuestas cortas y fundamentadas. (dep: 7.1)
- [ ] 8.2 [WINDOWS] Ensayo cronometrado con idea y género al azar. (dep: 5.4, 8.1)

---

## Pendientes para Diego
- **Hoy (lun 9, según el cronograma):** tareas 0.1 (git), 0.5 (entorno) y 0.6 (modelos + `f0_hello`). Las tres las hace `scripts/setup_windows.ps1` (PowerShell: `powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1`), que deja todo registrado en `docs/evidencias/`; luego Claude revisa las evidencias y marca las tareas. Las ejecuciones automáticas no usan git, así que el historial depende de los commits que se hagan en Windows.
- El ZIP original de F0 y las copias sueltas que quedaron en la raíz (`check_env.py`, `schemas.py`) se movieron a `.cache/f0-original/` (ignorado por git). Se pueden borrar cuando quieras.

---

## Bitácora

Entradas en orden cronológico. Formato:
`### AAAA-MM-DD HH:MM (hora Colombia) · entorno · tareas`
Seguido de: archivos creados o modificados · resultado de pytest y ruff · pendientes para Windows.

### 2026-11-09 12:00 · configuración inicial · —
- Se creó la carpeta del proyecto con `CLAUDE.md`, `docs/PROGRESO.md`, `.gitignore` y el enunciado en `docs/enunciado/` (ignorado por git).
- Hardware detectado: ASUS TUF F15 FX506HC, i5-11400H, 24 GB de RAM, RTX 3050 Laptop de 4 GB, Windows 11.
- Hallazgo: en `Documents/sd-turbo` torch quedó instalado como `2.14.1+cpu`, así que aquí hay que usar el índice CUDA (CLAUDE.md §5).

### 2026-11-09 13:00 · integración del ZIP F0 · 0.2, 0.3, 0.4, 1.1
- Se integró el ZIP "StoryBook-IA-F0", generado en la conversación del proyecto: código, configs, scripts, tests, README, MODELS.md, AUDIO_LICENSES.md y cronograma.
- Ajustes al integrarlo:
  - `requires-python` pasa de `>=3.11,<3.12` a `>=3.11` y `.python-version` a 3.12, porque el Python instalado es 3.12.10 y el Control inteligente de aplicaciones bloquea el Python que descarga uv.
  - README: paso `uv venv --python-preference only-system --python 3.12` y verificación de torch con CUDA.
  - pytest con `pythonpath = ["src"]`.
  - `.gitignore` unificado (se añadieron `docs/enunciado/`, `.cache/`, `_to_delete/` y `*.zip`).
  - `CLAUDE.md` alineado con `MODELS.md`: Qwen3-4B-Instruct-2507 y Qwen3-8B; SA3 Small-SFX y SAO 1.0 vía diffusers; Qwen3.5-4B y SAO Small descartados.
- Verificación con Python 3.12 sin GPU: **43 tests en verde**, `ruff check` sin errores, `ruff format --check` con 29 archivos ya formateados.
- Shell Linux de las ejecuciones automáticas: `.cache/vm-wheels/python312-bundle.tar.gz` es un Python 3.12 portátil con las dependencias de prueba. Reemplaza el venv 3.10 anterior.
- Pendiente en Windows: 0.1, 0.5, 0.6.

### 2026-11-09 16:40 · alineación con el resumen de modelos de clase · —
- Se revisó el documento "Resumen de modelos Storybook IA Generativa" entregado en clase. Coinciden: Qwen3-4B-Instruct-2507, Piper, Stable Audio Open 1.0, Diffusers, Ollama y Streamlit.
- Se agregó **AudioLDM** (`cvssp/audioldm`, 421M, CC BY-NC-SA 4.0), que no es gated, como backend de sonido generativo: `rapido` = sa3 → audioldm → library → procedural; `calidad` = sa3 → sao → audioldm → library → procedural.
  - Archivos: `config.py`, `configs/*.yaml`, `download_models.py` (se descarga aunque falte `HF_TOKEN`), `check_env.py`, `f0_hello.py` (`--sound-backends audioldm`) y `setup_windows.ps1`.
- `MODELS.md`: nueva sección "Relación con el resumen de modelos entregado en clase", con el uso o descarte de cada modelo y su motivo. SDXL, FLUX y XTTS-v2 quedan descartados por los 4 GB de VRAM; MusicGen queda como trabajo futuro.
- Verificación sin GPU: 44 tests en verde, ruff limpio.

### 2026-11-09 17:26 · automático (Linux) · 1.2, 1.3, 2.1
- **1.2 · Cliente Ollama.** Faltaban la inyección de transporte y la lógica de reintentos que pedía la tarea, así que se completó `story/llm_client.py` sin reescribirlo:
  - `OllamaClient(transport=...)` para usar `httpx.MockTransport` en los tests.
  - `generar_validado()`: pide JSON con el esquema de Pydantic, lo valida y, si falla, devuelve al modelo su respuesta y los errores (`mensaje_reparacion`) hasta `max_reintentos`. Solo se conserva el último intento fallido para no desbordar `num_ctx`. Devuelve `GeneracionValidada` con intentos y errores (para el manifest); si se agotan los intentos lanza `LLMValidationError`.
  - Correcciones: `httpx.TransportError` (conexión cortada) → `LLMConnectionError`; un cuerpo HTTP que no es JSON → `LLMResponseError`.
  - `tests/test_llm_client.py` (29 tests): respuesta válida, JSON inválido, 4 y 6 escenas, reintentos con el error de validación, `think=false` y `keep_alive` en el payload, conexión rechazada o cortada, timeout, modelo no encontrado (404, no se reintenta), respuesta vacía o truncada, hosts no locales rechazados, `unload` con `keep_alive=0`.
- **1.3 · Planificador y auditor.**
  - `story/planner.py`: `Planificador` con las estrategias (a) `una_llamada` y (b) `por_etapas` (plan → 5 escenas, cada una con el canon acumulado y los resúmenes previos). El número, la fase y los personajes presentes de cada escena los fija el plan, no el LLM (`alinear_escena_con_plan`). Registra cada llamada (`RegistroLlamada`: intentos, segundos, tokens) y tiene `liberar()` para descargar el modelo de la VRAM.
  - `story/auditor.py`: `Auditor.auditar_y_corregir()` audita a la temperatura del auditor, regenera solo las escenas con contradicciones críticas (conserva fase, personajes y seeds, y recalcula el canon) y vuelve a auditar hasta `max_rondas_auditor`. Si una regeneración falla, conserva la escena original y registra el error como fallback.
  - `story/prompts.py` (ya existía; solo se añadieron funciones): `mensajes_plan`, `mensajes_escena`, `mensajes_auditor` y `mensajes_regenerar_escena`. `mensaje_reparacion` acepta el nombre del objeto que se repara; el valor por defecto mantiene el comportamiento anterior.
  - Configuración: se agregaron `llm.estrategia` (`una_llamada`), `llm.auditar` (`true`) y `llm.max_rondas_auditor` (`1`) en `config.py` y `configs/default.yaml`. No cambia ningún modelo ni versión; son las perillas del experimento (a) vs (b).
  - Tests: `tests/fake_llm.py` (LLM falso), `tests/test_planner.py` (10) y `tests/test_auditor.py` (8).
- **2.1 · Prompt de imagen.**
  - `image/prompt_builder.py`: estilo + personajes presentes (protagonista primero) + acción, con un presupuesto de 75 tokens útiles (77 menos los 2 especiales de CLIP).
  - El contador es inyectable: `contador_desde_tokenizer(pipe.tokenizer)` en producción y `estimar_tokens_clip` en los tests.
  - Recorta frases completas en este orden: estilo → acción → secundarios → protagonista. Se conserva un mínimo por bloque y, como último recurso, se recortan palabras.
  - Negative prompt común: el de la Bible más `negative_prompt_base`, sin duplicados y también limitado.
  - Registra cada truncamiento (`PromptImagen.a_dict()` para el manifest). Con `usar_bible=False` se obtiene la línea base C1.
  - `tests/test_prompt_builder.py` (16 tests).
- **Verificación:** 107 tests en verde (antes 44); `ruff check` sin errores; `ruff format --check` con 38 archivos formateados.
- **Ningún archivo pidió acciones distintas a CLAUDE.md.**
- **Por validar en Windows/GPU:**
  - 1.4: tasa de JSON válido real y número de reintentos con Qwen3 4B y 8B, y comparar (a) frente a (b). Comprobar que el auditor no marca falsos positivos críticos con el 4B; si los marca, bajar `max_rondas_auditor` a 0.
  - 2.3: contar con el tokenizer real (`pipe.tokenizer`) cuántos prompts de una historia se truncan.
- **Siguiente [AUTO] disponible:** 2.2 (dep: 0.3 y 2.1 ya hechas), 3.1, 3.2 y 4.1.

### 2026-11-09 17:45 · Windows (setup_windows.ps1) + correcciones · 0.1, 0.5 (hechas), 0.6 (parcial)
- 0.1: repositorio en GitHub (`main`), `.gitattributes` con finales de línea LF.
- 0.5:
  - Driver 617.42 (CUDA 13.4).
  - **torch 2.15.0+cu132, CUDA 13.2, GPU True** (RTX 3050 Laptop).
  - 44 tests en verde en Windows.
  - Fue necesario desactivar el Control inteligente de aplicaciones de Windows, que bloqueaba `c10.dll`. Desde abril de 2026 se puede reactivar sin reinstalar.
- 0.6, descargas: todas OK y `check_env` con 0 fallos. Sin `HF_TOKEN`, Stable Audio quedó pendiente.
  - Tamaños: Qwen3 4B y 8B (Ollama), DreamShaper 8 2,0 GB, LCM-LoRA 0,1 GB, IP-Adapter 2,5 GB, Piper 60 MB, AudioLDM 1,4 GB, Whisper small 0,5 GB, OpenCLIP.
- 0.6, `f0_hello`: solo la voz funcionó (Piper RTF 0,064: 41 s de audio en 2,6 s). Fallos y correcciones:
  1. LLM: timeout de 600 s. La gramática JSON con `minLength`/`maxLength` en textos largos vuelve muy lenta la generación de llama.cpp y no había tope de tokens.
     - Corrección: esquema relajado para Ollama (las longitudes se validan con Pydantic) y `num_predict=5120`.
     - Además, el modelo se queda en la VRAM si falla; ahora se libera en un `finally`.
  2. Imagen y sonido marcados "no descargado": `huggingface_hub` 2.4 rechaza snapshots parciales en `snapshot_download(local_files_only=True)`.
     - Corrección: `hub.local_snapshot` lee `refs/main` → `snapshots/<commit>`, y los modelos se cargan desde la ruta local (pipeline, LCM-LoRA, IP-Adapter, sonido).
  3. Evaluación: faster-whisper 1.2.1 usa `av.open(metadata_errors=...)`, eliminado en PyAV 19.
     - Corrección: `asr_check.cargar_audio_16k` lee el WAV con soundfile y remuestrea a 16 kHz.
- Verificación sin GPU: 49 tests en verde, ruff limpio. Pendiente: repetir `setup_windows.ps1` para validar en GPU.
- **Corrección posterior (17:35):** al copiar estas correcciones se sobrescribieron por error tres archivos que la ejecución automática de las 17:26 había modificado sin commit:
  - `story/llm_client.py` (transporte inyectable, `generar_validado`, `GeneracionValidada`, `LLMValidationError`, `errores_validacion`, manejo de `TransportError` y de cuerpos no JSON);
  - `config.py` (`llm.estrategia`, `llm.auditar`, `llm.max_rondas_auditor`);
  - `configs/default.yaml` (las mismas tres claves).

  Se reconstruyeron a partir de sus 29 tests y del planificador y el auditor, y se integró `num_predict` en el cliente, el planificador y el auditor. Verificación: **112 tests en verde**, ruff limpio.
  **Regla para todas las sesiones:** antes de copiar archivos a esta carpeta, comprobar que no cambiaron desde que se leyeron (mtime o hash) y hacer commit en Windows con frecuencia.

### 2026-11-09 17:55 · Windows (2.ª corrida de setup) + correcciones · 0.6 (parcial)
- Medido en GPU:
  - Imagen: DreamShaper 8 + LCM a 768×512, 6 pasos → **4,95 s y 3,73 s por imagen**, VRAM pico 3,78 GB (torch 3,11 GB); carga 5,8 s.
  - Voz: Piper RTF 0,031.
  - **WER de la narración: 0,075.**
- Fallos y correcciones:
  1. LLM: 319 s y truncado a 5120 tokens (~16 tok/s).
     - El esquema permitía que el modelo escribiera `canon` (hasta 40 hechos), que el validador ya construye: ahora `canon` es `SkipJsonSchema`.
     - `num_predict` baja a 4096.
     - Se guarda `llm_raw_truncado.txt` si se trunca, y se registra la fracción del modelo en GPU aunque falle. Los ~16 tok/s sugieren offload parcial a CPU: verificar con el log `llm_en_gpu`.
  2. IP-Adapter: `SlicedAttnProcessor` sin `slice_size`, por ser incompatible con attention slicing.
     - `attention_slicing: false` (SDPA) y `disable_attention_slicing()` antes de `load_ip_adapter`.
  3. AudioLDM: faltaba el componente `vocoder`. `seleccionar_archivos_diffusers` ahora incluye cualquier carpeta con configuración, salvo `safety_checker`. Se descarga en la próxima corrida.
- Verificación sin GPU: 115 tests en verde, ruff limpio.

