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
- [x] 0.6 [WINDOWS] Descargar modelos y hacer la prueba por modalidad (completa el 10-nov 06:40: las 5 modalidades en GPU, ver bitácora):
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
- [x] 1.4 [WINDOWS] 10 generaciones reales con 4B y con 8B: tasa de JSON válido, tiempos, revisión de la calidad del español. (dep: 0.6, 1.3)
  - Se ejecuta con `setup_windows.ps1 -Paso f1 -Generaciones 10` (el 4B ya va 100 % en GPU por defecto). Genera `docs/evidencias/f1_generaciones.csv` y `f1_resumen.md`, con las causas de cada reintento.
  - Prueba de 3 generaciones (10 nov, 07:04): 3/3 válidas, pero una salió en inglés.
  - Corrida de 10 (10 nov, 08:00): 6/10 válidas; los 4 fallos ya están corregidos.
  - Corrida de 10 (10 nov, 08:23): **10/10 válidas**, 85 s por historia, 1,14 intentos por llamada. Se corrigieron los nombres copiados del prompt y los descriptores con etiquetas.
  - **Corrida definitiva (10 nov, 08:53 y 09:06):** 4B 9/10 (75 s por historia) y 8B 9/10 (~16 min por historia). Evidencias en `docs/evidencias/f1_resumen.md` y `f1_resumen_calidad.md` (perfil calidad = Qwen3 8B en esa fecha).

## F2 · Imágenes y consistencia visual
- [x] 2.1 [AUTO] `image/prompt_builder.py`: compone estilo + personajes presentes + acción, controla el límite de 77 tokens con un tokenizer inyectable (estimador heurístico en tests), recorta por prioridad y registra los truncamientos. Tests. (dep: 1.1)
- [x] 2.2 [AUTO] Ya existe `gpu.py` (carga, liberación y medición de VRAM). Falta:
  - `image/generator.py`: diffusers con DreamShaper 8 + LCM-LoRA + IP-Adapter según `configs/`, imports perezosos y `hub.local_snapshot` para cargar offline;
  - `image/consistency.py`: character sheet del protagonista;
  - en `prompt_builder`, cambiar los nombres de personajes que aparezcan en `prompt_imagen` ("Max and Luna walking...") por su descriptor, o quitarlos: CLIP no conoce esos nombres (visto en F1);
  - tests con un pipeline falso. (dep: 0.3, 2.1)
- [ ] 2.3 [WINDOWS] Prueba real: 5 imágenes de una historia, sin OOM; ajustar steps, CFG y resolución; medir tiempos y VRAM. (dep: 0.6, 2.2)
  - Se ejecuta con `setup_windows.ps1 -Paso f2` (rápido); `-Paso f2 -Perfil calidad` mide solo las imágenes con DPM++ 25 pasos. Usa `scripts/f2_f3_prueba.py` con la primera historia válida de la última corrida de F1 hecha con el 4B. Evidencias en `docs/evidencias/f2_f3_resumen*.md`.

## F3 · Voz
- [x] 3.1 [AUTO] `voice/tts.py`: Protocol `TTSBackend` con backends Piper (`hub.require_piper_voice`) y Kokoro (opcional), ambos con imports perezosos; voz y parámetros desde la configuración; salida WAV y duración. Tests con un backend falso. (dep: 0.3)
- [x] 3.2 [AUTO] Ya existe `evaluation/asr_check.py`. Falta `tests/test_asr_check.py` con un transcriptor falso: WER, normalización del español y casos borde. (dep: 0.3)
- [ ] 3.3 [WINDOWS] Escuchar la voz `es_MX-claude-high` y 1–2 alternativas, elegir y medir el WER real. (dep: 0.6, 3.1, 3.2)
  - `setup_windows.ps1 -Paso f2` descarga `es_MX-ald-medium` y `es_ES-davefx-medium` (`download_models.py --voces-extra`) y narra la historia con las 3 voces. Los WAV quedan en `outputs/f2/<fecha>/voz/<voz>/`, con el WER de cada voz en el resumen. Diego escucha y elige.

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
- **Siguiente (2.3 y 3.3):** `powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1 -Paso f2` y después `... -Paso f2 -Perfil calidad`. Al terminar, escuchar las 3 voces en `outputs/f2/<fecha>/voz/` y decirle a Claude cuál suena mejor. Las ejecuciones automáticas no usan git: el historial depende de los commits que hace `setup_windows.ps1` en Windows.
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

### 2026-11-09 18:10 · Windows (3.ª corrida de setup) + correcciones del LLM · 0.6 (parcial)
- **Ya funcionan en GPU:**
  - Imagen: 4,0 y 2,9 s por imagen; VRAM pico 4,08 GB de la GPU (torch 3,11 GB).
  - IP-Adapter: 4,0 s; embeddings en CPU 4,5 s.
  - AudioLDM: 1,2–1,6 s por clip de 8 s, VRAM 1,27 GB.
  - Piper: RTF 0,032.
  - **WER 0,056**, CLIP imagen-texto 0,408, CLIP imagen-imagen media 0,82 (mínimo 0,74).
- **El LLM sigue fallando** y se diagnosticó con `llm_raw_truncado.txt` y `ollama ps`:
  1. **Bucle de repetición:** "Ella lo sabe." repetido cientos de veces dentro de `texto_narrativo`. Fue la causa real de los truncamientos y del timeout de 600 s.
  2. **Ollama ordena alfabéticamente las claves del JSON:** las `escenas` salen antes que los `personajes` y el modelo usó "Luisa" como id.
  3. **Solo el 66 % del 4B estaba en GPU** con `num_ctx` 8192, lo que daba ~16 tok/s.
- **Correcciones:**
  - Muestreo de Qwen3-Instruct-2507 (`top_p` 0.8, `top_k` 20) con `presence_penalty` 1.0 y `repeat_penalty` 1.1 (`LLMConfig.opciones_muestreo()`), en el cliente, el planificador y el auditor.
  - `generar_validado` reintenta los truncamientos sin reenviar la salida cortada y con otra seed.
  - Ids de personaje normalizados (`'Lucía'` → `lucia`).
  - Perfiles con `estrategia: por_etapas`, `num_ctx` 4096, `num_predict` 2048 y `num_ctx_auditor` 8192. La clase mantiene `una_llamada` por defecto.
  - `f0_hello.py llm` ahora usa el `Planificador` real del proyecto y guarda `story.json`, `llm_llamadas.json` y la salida inválida si falla.
- Verificación sin GPU: **118 tests en verde**, ruff limpio.

### 2026-11-10 06:50 · Windows (4.ª corrida de setup) · 0.6 hecha → **Fase 0 completa**
- **Las 5 modalidades funcionan en GPU** (`outputs/f0/20261110_063941`, 285 s en total):
  - LLM por etapas: Story Bible válida "El Faro que Escucha" (misterio, 2 personajes, 5 escenas de 96–121 palabras, canon de 14 hechos). 6 llamadas y 14 intentos, 227 s, 11,4 tok/s, **72 % del modelo en GPU**.
  - Imagen: 4,3 y 2,8 s; IP-Adapter 3,9 s; VRAM pico 4,08 GB.
  - Piper RTF 0,067. AudioLDM 1,4–1,6 s por clip de 8 s.
  - **WER 0,0084**; CLIP imagen-texto 0,41; CLIP imagen-imagen 0,81 (mínimo 0,79).
- Causas de los reintentos: las 5 escenas fueron demasiado cortas al primer intento (48–64 palabras, mínimo 90), y en el plan una descripción visual pasó de 25 tokens CLIP y un id de personaje no coincidió.
- Ajustes para F1:
  - El prompt pide la longitud como "7 a 10 oraciones completas".
  - `llm.num_gpu` es opcional, para probar el modelo 100 % en GPU (`-NumGpu 99`).
  - Nuevo `scripts/f1_generaciones.py` (tarea 1.4): 10 ideas que cubren los 6 géneros, planificador + auditor, con CSV y resumen en `docs/evidencias/`.
- La tarea automática no corrió anoche (PC apagado): las ejecuciones requieren el PC encendido con la app de Claude abierta.
- Verificación sin GPU: 120 tests en verde, ruff limpio.

### 2026-11-10 07:45 · Windows (prueba F1, 3 generaciones con `-NumGpu 99`) + correcciones · 1.4 (parcial)
- **3/3 Story Bibles válidas**. Mediana: 126 s por historia (plan ~50 s, escenas ~70 s, auditor ~5 s), 20,8 tok/s, **100 % del modelo en GPU** y 0 contradicciones del auditor.
- `num_gpu: 99` duplica la velocidad (11 → 21 tok/s) y cabe junto con el contexto del auditor (8192). Queda por defecto en `default.yaml`; `calidad.yaml` lo deja automático porque el 8B no cabe.
- **Problema encontrado:** la historia 3 (ciencia ficción, "Rooted in Orbit") salió **entera en inglés** (título, resúmenes y narración) y pasó la validación. Piper la habría leído con voz española.
- Causas de los ~2 intentos por llamada (20 reintentos en total):
  - 14 · escenas demasiado cortas al primer intento (56–88 palabras; mínimo 90).
  - 8 · descriptores y `prompt_imagen` por encima del presupuesto CLIP (~28 tokens de 25).
  - 3 · el plan usaba ids genéricos (`protagonista`, `p_1`) y las escenas los nombres (`lena`, `nexo_7`).
  - 1 · fase equivocada en el plan.
- Correcciones:
  - `schemas.py`:
    - `parece_ingles()` (palabras funcionales) rechaza `titulo`, `resumen` y `texto_narrativo` en inglés y devuelve el error al modelo. Probado con las 3 historias reales: rechaza solo la de inglés.
    - `resolver_ids_por_nombre()`: un nombre que identifica a un solo personaje se cambia por su id. Los ids repetidos en `personajes_presentes` se eliminan en lugar de rechazarse.
  - `prompts.py`:
    - Pide 10 a 12 oraciones (unas 120 palabras) y lo repite al final del mensaje de cada escena.
    - Pide los campos en inglés con el 60 % del presupuesto CLIP (antes 75 %), el título y los resúmenes en español, y ids iguales al nombre.
  - `f1_generaciones.py`: nueva columna `causas_reintento` y tabla de causas en `f1_resumen.md`.
  - `setup_windows.ps1 -Perfil calidad` corre la comparación con el 8B; sus evidencias llevan sufijo `_calidad` y no pisan las del 4B.
- Verificación sin GPU: **140 tests en verde** (contenedor y bundle Linux), ruff limpio.
- **Siguiente [WINDOWS]:** `setup_windows.ps1 -Paso f1 -Generaciones 10` (evidencia de 1.4). Esperado: menos intentos por llamada y unos 60–80 s por historia.
- **Siguiente [AUTO]:** 2.2 (generador de imágenes), 3.1, 3.2 y 4.1.

### 2026-11-10 08:40 · Windows (corrida F1 de 10 historias) + correcciones · 1.4 (parcial)
- **6/10 Story Bibles válidas** (`outputs/f1/20261110_080023`). Las válidas mejoraron mucho con las correcciones de las 07:45:
  - Mediana de 84 s por historia (antes 126 s) y 33 tok/s.
  - 1,21 intentos por llamada (antes 2,0) y escenas de 100–125 palabras al primer intento.
  - Todas en español y 100 % en GPU; el auditor no encontró contradicciones.
- **Los 4 fallos** agotaron los 4 intentos repitiendo el mismo error:
  - Historias 4 y 10 (terror): `genero` de más de 40 caracteres en el plan, las dos.
  - Historia 3 (ciencia ficción): dos protagonistas, un robot y una científica.
  - Historia 8 (fantasía): `prompt_imagen` con tilde, por el nombre de un personaje. La validación anterior rechazaba cualquier tilde.
- Otras causas de reintento:
  - 14 · presupuesto CLIP, por 1–5 tokens de más.
  - 17 · idioma. En la historia 7, al pedirle un descriptor en inglés, el modelo pasó todo el plan al inglés y necesitó 4 intentos.
- Correcciones (lo que el código ya sabe no lo decide el LLM; lo que se puede arreglar sin perder información no se reintenta):
  - `genero` sale del esquema del LLM; el planificador lo copia de la solicitud.
  - Con 0 o 2+ protagonistas, queda el personaje de la escena 1 con más apariciones; los demás pasan a secundarios.
  - Campos en inglés:
    - Se quitan las tildes ("Tomás" → "Tomas").
    - Solo se rechazan si parecen español (`parece_espanol`).
  - Descriptor, estilo y `prompt_imagen`:
    - Si se pasan del presupuesto CLIP, se quitan frases del final.
    - El descriptor se pide de lo más a lo menos importante.
  - El mensaje de reparación recuerda qué campos van en español y cuáles en inglés.
  - `f1_generaciones.py`:
    - Si una generación falla, guarda `fallo_XX.json` (errores y última salida).
    - Cuenta sus intentos y causas en el resumen.
  - `setup_windows.ps1 -Paso f1` hace primero el commit del código, para que la evidencia corresponda a un commit. En la corrida anterior el código no se había subido.
- Verificación sin GPU: **147 tests en verde**, ruff limpio. Las 9 Story Bibles reales en español (F0 y F1) siguen validando; solo se rechaza la que está en inglés.
- **Siguiente [WINDOWS]:** repetir `setup_windows.ps1 -Paso f1 -Generaciones 10`.

### 2026-11-10 08:55 · Windows (corrida F1 de 10 historias, 3.ª) + correcciones · 1.4 (parcial)
- **10/10 Story Bibles válidas** (`outputs/f1/20261110_082340`, commit de evidencias `0430a90`, código `chore: codigo usado...`):
  - Mediana de 85 s por historia y 35 tok/s.
  - **1,14 intentos por llamada**; 4 historias sin ningún reintento.
  - 100 % en GPU; el auditor no encontró contradicciones.
- Causas de reintento que quedan:
  - 13 · descriptores en español en el primer intento del plan. El modelo escribía `edad: 30, cabello: ...`.
  - 1 · `prompt_imagen` con 3 tokens CLIP de más.
- **Revisión de la calidad (lectura de 4 escenas de géneros distintos):**
  - El español es fluido y coherente con el plan, y el arco de 5 escenas se respeta.
  - El 4B comete errores sueltos de concordancia y algún extranjerismo: "un piedra", "sus ojos brilla", "ventana rotta", "montaña isolada", "la luz no ha encendido". Hay que medirlo frente al 8B.
  - **Nombres copiados del prompt:** 'Lena' en 5 de 10 historias y 'Capitán Ruiz' en 5, incluso en fantasía y ciencia ficción. Venían del ejemplo de id que se añadió a las 07:45.
  - **Descriptores con etiquetas** (`age:18, hair:...`) en 5 de 10, una con etiquetas en español (`edad: 30, cabello: ...`). Para CLIP son tokens sin contenido.
  - `tono` a veces copia la indicación del género ("atmósfera inquietante y suspenso; sin gore...").
  - Para F4, el sonido no siempre encaja con el lugar: `forest` en una biblioteca y `water_stream` + `forest` en una estación espacial. Revisarlo en 4.1–4.3, por ejemplo derivar etiquetas también del escenario.
  - En algunas historias `prompt_imagen` nombra a los personajes ("Max and Luna walking..."). CLIP no conoce esos nombres; `prompt_builder` debería quitarlos o sustituirlos por el descriptor (anotar en 2.2).
- Correcciones:
  - Prompts y esquema sin nombres de ejemplo. El plan pide inventar nombres que encajen con la historia, un `tono` de 2 a 4 adjetivos y descriptores como frases sueltas, sin etiquetas.
  - `quitar_etiquetas_descriptor()`: `age: 12, hair: black, distinct_feature: green eyes` → `age 12, black hair, green eyes`. Solo actúa sobre etiquetas conocidas, también en español.
- Verificación sin GPU: **154 tests en verde** (contenedor y bundle Linux), ruff limpio. Las 18 Story Bibles reales en español de F1 siguen validando.
- **Siguiente [WINDOWS]:** corrida definitiva de 1.4: 10 historias con el 4B y 10 con el 8B, con los mismos prompts. El 8B tarda bastante más; se puede dejar corriendo.
- **Siguiente [AUTO]:** 2.2 (generador de imágenes; incluir el tratamiento de nombres en `prompt_imagen`), 3.1, 3.2 y 4.1.

### 2026-11-10 11:44 · automático (Linux) · 2.2, 3.1, 3.2
- **2.2 · Generador de imágenes y consistencia.**
  - `image/generator.py` (nuevo): `GeneradorImagenes` con el Protocol `BackendImagen` y `DiffusersBackend` (imports perezosos; mismo procedimiento validado en F0 por `f0_hello.py`: fp16, `hub.local_snapshot`, LCM-LoRA o DPM++ 2M Karras, SDPA sin attention slicing, VAE slicing, encoder de IP-Adapter en CPU).
    - Una carga para todas las escenas; asigna seeds con `consistency` si la Bible no las tiene; cuenta tokens con el tokenizer real (`contador_desde_tokenizer`).
    - Fallbacks: si la character sheet o IP-Adapter fallan, sigue sin IP-Adapter (`imagen:sin_ip_adapter`); un OOM se reintenta una vez tras liberar memoria; si una escena sigue fallando recibe una imagen de respaldo (`imagen:respaldo:n`). Siempre salen 5 imágenes.
    - `numeros=[n]` regenera una escena con la misma Bible y seeds, reutilizando `character_sheet.png`.
    - `EtapaImagen.a_dict()` deja en el manifest parámetros, seeds, prompts (tokens, truncamientos, sustituciones), versiones, revisión de los pesos, métricas por etapa, fallbacks y errores.
  - `image/consistency.py` (nuevo): prompt de la character sheet del protagonista (estilo + descriptor + retrato de cuerpo entero sobre fondo neutro, 512×512, seed del protagonista).
  - `image/prompt_builder.py`: `sustituir_nombres()` cambia los nombres de personajes en `prompt_imagen` por la primera frase de su descriptor ("Lucia and Tomas…" → "girl age 10 and old man…"). Nombres de una palabra solo si van en mayúscula (no toca "rose", "sky"); nombres compuestos e ids con `_` sin distinguir mayúsculas; se omiten palabras compartidas por dos personajes. En C1 usa "a person". Las sustituciones se registran en `PromptImagen.sustituciones`.
  - Tests: `tests/test_image_generator.py` (15) y `tests/test_image_consistency.py` (12).
- **3.1 · Voz.** `voice/tts.py` (nuevo): `Narrador` + Protocol `TTSBackend`, con `PiperBackend` (valida la voz con `hub.require_piper_voice` antes de importar piper) y `KokoroBackend` (opcional, `speed = 1/length_scale`). Una carga por historia, texto normalizado para el TTS (comillas, rayas, signo final), `voice_n.wav` PCM 16 bits con 0,35 s de silencio final, duración y RTF por escena. Tests: `tests/test_tts.py` (18).
- **3.2 · ASR.** `tests/test_asr_check.py` (19): normalización del español (tildes, ñ, ¿¡, comillas), WER (sustitución, borrado, inserción > 1, hipótesis vacía, referencia vacía) y `WhisperChecker` con un modelo falso. `asr_check.py` no necesitó cambios.
- **Verificación (bundle Python 3.12):** **218 tests en verde** (antes 154); `ruff check` sin errores; `ruff format --check` con 51 archivos formateados.
- No se cambió ningún modelo, versión ni configuración. Ningún archivo pidió acciones distintas a CLAUDE.md.
- **Por validar en Windows/GPU:**
  - 2.3: `GeneradorImagenes(cfg.image, cfg.consistency).generar(bible, carpeta)` con una Story Bible real de F1: 5 imágenes + character sheet sin OOM, tiempos y VRAM (`EtapaImagen.metricas`). Confirmar con diffusers real que `ip_adapter_image_embeds` con LCM (CFG 1,5) da imágenes correctas, y cuántos prompts se truncan con el tokenizer real.
  - 3.3: `Narrador(cfg.voice).narrar_bible(bible, carpeta)` con Piper real (comprobar que `synthesize_wav` sobre un `BytesIO` funciona igual que sobre archivo) y medir el WER real con `WhisperChecker`.
- **Siguiente [AUTO]:** 4.1 (síntesis procedural), luego 4.2 y 4.3.

### 2026-11-10 12:15 · Windows (corrida definitiva de 1.4: 4B y 8B) + correcciones · 1.4 hecha
- **4B** (`outputs/f1/20261110_085328`):
  - **9/10 válidas**. Mediana de 75 s por historia, 43 tok/s, 1,07 intentos por llamada y 100 % en GPU.
  - 0 contradicciones; 5 historias sin ningún reintento.
  - Nombres variados: ya no se repiten Lena ni Capitán Ruiz.
- **8B** (`outputs/f1/20261110_090633`, perfil calidad):
  - **9/10 válidas**, pero **mediana de 982 s (~16 min) por historia solo de texto**. 3 tok/s, 39 % del modelo en GPU con `num_ctx` 8192 y 1,57 intentos por llamada.
  - El auditor encontró 3 contradicciones en una historia.
- **Fallos:**
  - 4B, historia 9: el primer plan traía los descriptores en español; al repararlo, el modelo pasó los 5 resúmenes al inglés y se quedó así en 3 reparaciones seguidas. Quedó en `fallo_09.json`.
  - 8B, historia 1: `iluminacion` de 62 caracteres (límite 60) en los 4 intentos; la reparación no lo corrigió.
- **El 8B escribe más a menudo en español los campos para el ilustrador y el sonidista:** 31 descriptores, 21 `prompt_imagen` y 17 `prompt_sonido`, frente a 5, 4 y 2 del 4B.
- **Calidad del español** (misma idea, terror, escena 2 de cada modelo):
  - Ambos son fluidos y respetan el plan.
  - El 8B tiene frases algo más elaboradas, con algún cambio de tiempo verbal ("soplaba").
  - El 4B mantiene errores sueltos de concordancia y alguna incoherencia ("al amanecer, mientras el cielo se oscurece").
  - Ninguno es claramente superior en lo narrativo; la diferencia decisiva es el tiempo: 13 veces más lento.
- Correcciones:
  - `generar_validado`: si una reparación falla, el intento siguiente empieza de cero con otra seed (`seed + intento`). Con 4 intentos queda: limpio → reparación → limpio → reparación.
  - `EstiloVisual`: límite de 120 caracteres por campo; el que manda es el presupuesto CLIP, que ya recorta frases.
- **Integración con lo automático de las 11:44 (2.2, 3.1 y 3.2):** sincronizado sin conflictos. **220 tests en verde** (contenedor y bundle Linux), ruff limpio.
- **Decisión pendiente (Diego):** el perfil calidad con el 8B no puede cumplir "< 12 min por historia completa", porque el texto solo ya tarda ~16 min. Ver "Pendientes para Diego".
- **Siguiente [WINDOWS]:** 2.3 (imágenes reales de una historia de F1) y 3.3 (voz real con WER), ya desbloqueadas por 2.2, 3.1 y 3.2.

### 2026-11-10 12:30 · decisión del perfil calidad + preparación de 2.3 y 3.3 · —
- **Decisión de Diego: opción (a).**
  - `calidad.yaml` usa el mismo Qwen3 4B que rápido (100 % en GPU, ~75 s por historia) y gasta el tiempo extra en imágenes (DPM++ 25 pasos) y sonido (SAO 1.0).
  - El 8B pasa a `configs/experiments/llm_8b.yaml` (`-Perfil llm_8b` en el script; `download_models.py --profiles experiments/llm_8b`).
  - Las evidencias `f1_*_calidad.*` de hoy corresponden al 8B; su encabezado lo dice.
  - Actualizados CLAUDE.md, MODELS.md y los tests de perfiles.
- **Nuevo `scripts/f2_f3_prueba.py` (2.3 y 3.3):** con una Story Bible real de F1 ejecuta:
  - `GeneradorImagenes`: character sheet, IP-Adapter y 5 escenas.
  - CLIP: imagen-texto por escena e imagen-imagen.
  - `Narrador` con la voz del perfil y las alternativas.
  - WER con faster-whisper.

  Cada paso es independiente: si uno falla, se registra y se sigue. Guarda `resultado.json` y `resumen.md` con tiempos, VRAM pico, tokens, truncamientos, nombres sustituidos, fallbacks, RTF y WER por voz.
- `download_models.py --voces-extra` descarga voces Piper adicionales. Un nombre inválido ya no aborta la descarga.
- `setup_windows.ps1 -Paso f2`:
  1. Hace commit del código.
  2. Descarga las 2 voces alternativas (si falla, sigue).
  3. Ejecuta la prueba y guarda las evidencias.

  Con `-Perfil calidad` mide solo las imágenes.
- Verificación sin GPU: **224 tests en verde** (contenedor y bundle Linux), ruff limpio. Con los datos reales, la historia elegida sería `outputs/f1/20261110_085328/story_01.json` ("El Faro de las Noches", 2 personajes).
- **Siguiente [WINDOWS]:** `setup_windows.ps1 -Paso f2` y después `-Paso f2 -Perfil calidad`.
