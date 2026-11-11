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
- [x] 2.3 [WINDOWS] Prueba real: 5 imágenes de una historia, sin OOM; ajustar steps, CFG y resolución; medir tiempos y VRAM. (dep: 0.6, 2.2)
  - **Hecha (10 nov):**
    - 5 imágenes sin OOM: 3,4 s por imagen en rápido y 8,2 s en calidad; VRAM pico de 4066 de 4096 MB.
    - Ajuste elegido con 5 variantes reales: **IP-Adapter 0,4 + acción primero** (`docs/evidencias/f2_variantes.md`).
  - Se ejecuta con `setup_windows.ps1 -Paso f2` (rápido); `-Paso f2 -Perfil calidad` mide solo las imágenes con DPM++ 25 pasos. Usa `scripts/f2_f3_prueba.py` con la primera historia válida de la última corrida de F1 hecha con el 4B. Evidencias en `docs/evidencias/f2_f3_resumen*.md`.

## F3 · Voz
- [x] 3.1 [AUTO] `voice/tts.py`: Protocol `TTSBackend` con backends Piper (`hub.require_piper_voice`) y Kokoro (opcional), ambos con imports perezosos; voz y parámetros desde la configuración; salida WAV y duración. Tests con un backend falso. (dep: 0.3)
- [x] 3.2 [AUTO] Ya existe `evaluation/asr_check.py`. Falta `tests/test_asr_check.py` con un transcriptor falso: WER, normalización del español y casos borde. (dep: 0.3)
- [x] 3.3 [WINDOWS] Escuchar la voz `es_MX-claude-high` y 1–2 alternativas, elegir y medir el WER real. (dep: 0.6, 3.1, 3.2)
  - `setup_windows.ps1 -Paso f2` descarga `es_MX-ald-medium` y `es_ES-davefx-medium` (`download_models.py --voces-extra`) y narra la historia con las 3 voces. Los WAV quedan en `outputs/f2/<fecha>/voz/<voz>/`, con el WER de cada voz en el resumen. Diego escucha y elige.
  - **Hecha (10 nov):** Diego eligió `es_MX-claude-high` al escucharlas.
    - WER (mediana): claude-high 8,3 % (máximo 9,7 %); ald-medium 4,7 %; davefx-medium 6,8 %.
    - RTF de 0,03: ~216 s de audio en ~7 s.
    - Los errores son sobre todo de Whisper: nombres ("Helias" por Elias) y palabras unidas o separadas ("si sea" por sisea).

## F4 · Sonido y mezcla
- [x] 4.1 [AUTO] `sound/procedural.py`: síntesis con numpy/scipy de viento, lluvia, fuego, latidos, drone oscuro, pasos, olas, bosque/pájaros y ambiente mágico. Mapeo desde `EtiquetaSonido` (schemas) a recetas. Tests: duración, sample rate, sin clipping, sin NaN. (dep: 0.3)
- [x] 4.2 [AUTO] Sonido con fallback en cadena:
  - `sound/library.py`: índice JSON por etiquetas para `assets/sfx/`.
  - `sound/generator.py`: recorre `sound.backends` de la configuración (`sa3` → `sao` → `audioldm` → `library` → `procedural`), con imports perezosos de diffusers (`StableAudio3Pipeline`, `StableAudioPipeline`, `AudioLDMPipeline`; ver `scripts/f0_hello.py` como referencia), y registra el fallback usado.

  Tests con generadores falsos que fallan. (dep: 4.1)
- [x] 4.3 [AUTO] `sound/mixer.py`: loop con crossfade hasta la duración de la voz, LUFS con pyloudnorm, ambiente 12–18 dB bajo la voz, ducking y exportación de `ambience_n.wav` y `mix_n.wav`. Tests con señales sintéticas. (dep: 4.1)
- [x] 4.4 [WINDOWS] Prueba real de SA3 Small-SFX y de AudioLDM: confirmar el formato diffusers, medir VRAM y tiempo, y comparar la pertinencia del sonido. Si SA3 no cabe, probar SAO 1.0 con offload. (dep: 0.6, 4.2)
  - Se ejecuta con `setup_windows.ps1 -Paso f4` (`scripts/f4_sonido.py`): narra la historia de prueba y genera y mezcla los 5 ambientes con la cadena real del perfil y con procedural. Evidencias en `docs/evidencias/f4_sonido.md`; se escuchan los `mix_N.wav` de `outputs/f4/<fecha>/<variante>/`.

## F5 · Integración, persistencia y UI
- [x] 5.1 [AUTO] `storage.py` (run_id, estructura de `outputs/`, `manifest.json`, cargar historias) y `pipeline.py` (orquestación por etapas, callback de progreso, fallbacks, regenerar una escena). `tests/test_pipeline_mock.py`: el pipeline completo con backends falsos produce 5 escenas con todos sus archivos y su manifest. (dep: 1.3, 2.2, 3.1, 4.3)
- [x] 5.2 [AUTO] `app/streamlit_app.py`:
  - formulario validado y selector de perfil;
  - `st.status` por etapa;
  - visor con imagen, texto y tres reproductores;
  - Anterior/Siguiente con indicador n/5;
  - regenerar escena;
  - cargar historias de `outputs/` y `samples/`;
  - etiqueta "Contenido generado por IA".

  La lógica va en módulos testeables; Streamlit se importa solo en la app. Opción `--mock` para probar la UI sin GPU. (dep: 5.1)
  - Lanzador de doble clic `StoryBook.cmd` en la raíz (pedido por Diego para probar la app sin escribir comandos):
    - comprueba que Ollama responde en localhost:11434 y, si no, lo abre y espera;
    - ejecuta `uv run streamlit run app/streamlit_app.py` y abre el navegador en http://localhost:8501;
    - ASCII y compatible con cmd de Windows.
    - Con `StoryBook.cmd mock` abre la UI con backends falsos.
    - Documentarlo en el README.
- [x] 5.3 [AUTO] `scripts/verify_offline.py`: bloquea sockets salvo localhost, corre el pipeline con backends falsos o reales según una bandera e informa cualquier intento de conexión externa. (dep: 5.1)
- [x] 5.4 [WINDOWS] Prueba de punta a punta real con el Wi-Fi apagado; generar 2–3 historias para `samples/`. (dep: 2.3, 3.3, 4.4, 5.2)
  - Con el Wi-Fi apagado: `setup_windows.ps1 -Paso offline` (1 historia real con la red vigilada); con `-Muestras` hace 3 y las copia a `samples/`.
  - `samples/` se versiona con los audios en OGG Vorbis (`storage.exportar_muestra`): unos 7 MB por historia, frente a ~55 MB en WAV.
  - **Prueba sin Internet hecha (10 nov, 13:58):** "El Faro de Lucian", completa en **133 s** (texto 73 s, imágenes 40 s, voz 8 s, sonido 10 s, mezcla 2 s). Ninguna conexión fuera del equipo. Falta generar las 2–3 historias de `samples/`.
  - **3 historias reales generadas sin Internet (10 nov, 14:17–14:24),** entre 126 y 138 s cada una. La exportación a `samples/` falló (ver bitácora de las 14:45).
  - **Ejemplos en `samples/` (10 nov, 14:42, `-Paso muestras`):** "El Faro de Lucian", "La Biblia del Dragón" y "El Camino de los Amigos", de 7,3 a 7,9 MB cada una y 23 archivos (15 audios OGG). Subidos a GitHub (commit 83460fc).

## F6 · Experimentos
- [x] 6.1 [AUTO] Ya existe `evaluation/clip_metrics.py`. Falta:
  - `evaluation/report.py`;
  - `scripts/run_experiment.py` (escribe en `experiments/results.csv` con las columnas existentes);
  - `scripts/make_contact_sheet.py`;
  - tests con datos falsos. (dep: 5.1)
  - Hecho en la sesión interactiva del 10 nov (ver la bitácora de las 14:54). Para 6.2: `setup_windows.ps1 -Paso experimentos`.
- [x] 6.2 [WINDOWS] Ejecutar la batería completa: C1/C2/C3 × 4 géneros, más 4B vs 8B (opcional: Qwen3-0.6B, del resumen de clase), LCM vs 25 pasos y SA3 vs AudioLDM → `experiments/results.csv` + evidencias. (dep: 5.4, 6.1)
  - **Hecha el 11 nov, 11:15–11:33:** 16 pruebas (4 ideas × C3, C1, C2 y `calidad`), todas con 5 escenas. Resumen en `docs/evidencias/f6_experimentos_20261111_111458.md` y hojas de contactos en `docs/evidencias/f6_hojas/`.
  - 4B frente a 8B: se usa lo medido en 1.4. SA3 no está disponible (acceso restringido), así que la comparación de sonido es AudioLDM frente a procedural.
  - Complemento (`-Paso audioldm`, 11 nov, 11:42): con el sufijo ", high quality, clear", AudioLDM da un ambiente apto en 20 de 20 escenas (sin él, 13 de 20). Adoptado en la configuración.
- [x] 6.3 [AUTO] Análisis de `results.csv`: gráficas, tablas y conclusiones en `docs/informe/`. (dep: 6.2)
  - Hecho en la sesión interactiva del 11 nov: `docs/informe/analisis_experimentos.md` y 5 gráficas en `docs/informe/graficas/` (`scripts/graficas_informe.py`).

## F7 · Documentación y video
- [x] 7.1 [AUTO] Completar `README.md` (ya existe la base de F0), `MODELS.md` y `docs/arquitectura.md` con diagramas Mermaid de componentes y de flujo de datos. Marcar `[DATO PENDIENTE]` donde falten mediciones. (dep: 5.1)
  - Hecho en la sesión interactiva del 11 nov (ver la bitácora). Sin `[DATO PENDIENTE]`: las mediciones ya existen.
- [x] 7.2 [AUTO] Borrador del informe técnico en `docs/informe/informe.md` con las 12 secciones de CLAUDE.md §16, marcando `[DATO PENDIENTE]` donde falten resultados reales. (dep: 7.1)
  - Hecho el 11 nov: `docs/informe/informe.md` y un primer `informe.pdf` (21 páginas). Quedan 3 `[DATO PENDIENTE]`: nombre del docente, lista 1–5 y enlace del video.
- [ ] 7.3 [WINDOWS] Completar el informe con los datos reales y exportarlo a PDF; grabar el video demo. (dep: 6.2, 7.2)

## F8 · Sustentación
- [x] 8.1 [AUTO] `docs/sustentacion.md`: guion de la demo, plan B, 30 preguntas probables del jurado con respuestas cortas y fundamentadas. (dep: 7.1)
  - Hecho el 11 nov: `docs/sustentacion.md`. Para el respaldo en vivo: `StoryBook.cmd respaldo`.
- [ ] 8.2 [WINDOWS] Ensayo cronometrado con idea y género al azar. (dep: 5.4, 8.1)

---

## Pendientes para Diego
- **Siguiente (Diego):**
  1. Con el Wi-Fi encendido, `setup_windows.ps1 -Paso git`, para subir 7.2, 8.1 y el modo respaldo.
  2. Probar `StoryBook.cmd respaldo`: el aviso amarillo debe aparecer y una escena regenerada debe salir con sonido procedural.
  3. Para 7.3, dar el nombre del docente, revisar la lista 1–5 y grabar el video siguiendo el guion de `docs/sustentacion.md`; Claude regenera el PDF con esos datos.
  4. Después, el ensayo cronometrado (8.2).
  - Las ejecuciones automáticas no usan git: el historial depende de los commits que hace `setup_windows.ps1` en Windows.
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

### 2026-11-10 12:50 · Windows (prueba real de imágenes y voz: 2.3 y 3.3) + ajustes · 3.3 hecha, 2.3 parcial
- Historia: `outputs/f1/20261110_085328/story_01.json`, "El Faro de las Noches" (2 personajes). Sin errores en ningún paso. Evidencias: `docs/evidencias/f2_f3_resumen.md` y `f2_f3_resumen_calidad.md`.
- **Imágenes, rápido** (LCM, 6 pasos, CFG 1,5, 768×512, IP-Adapter 0,6):
  - Carga 30 s la primera vez (7 s con la caché del disco caliente), 3,4 s por imagen, 55 s la etapa completa.
  - **VRAM pico: 4066 de 4096 MB en la GPU** (incluye Windows), 3156 MB de torch. Sin OOM, pero al límite.
  - CLIP imagen-texto 0,35; imagen-imagen 0,81 (mínimo 0,74).
- **Imágenes, calidad** (DPM++ 25 pasos, CFG 7): 8,2 s por imagen (2,4 veces más) y 57 s en total. CLIP texto 0,37 e imagen-imagen 0,78: algo más fiel al texto y menos consistente.
- **Revisión visual de las 12 imágenes (Claude):**
  - El protagonista es muy consistente: misma cara, pelo y chaqueta.
  - **Pero todas las escenas salen como un retrato de frente y de cuerpo entero, igual que la character sheet.** IP-Adapter 0,6 domina la composición: la acción ("toca un interruptor", "camina entre árboles") casi no se ve y el segundo personaje (Elias, 50 años) no aparece en ninguna.
  - Calidad no se ve mejor y en una escena cambia de personaje.
  - 3 de 5 prompts se truncan (71–74 tokens): se pierde la iluminación del estilo.
- **El descriptor no decía quién es el personaje:** empezaba por "25 years old", sin "woman". Al cambiar el nombre por el descriptor, la escena 5 quedó "25 years old touching a switch".
- Correcciones y preparación del ajuste:
  - Prompt de la Bible: la primera frase del descriptor es "<tipo> age <edad>" (woman, boy, old man, robot…). `prompt_builder` la usa como sujeto al sustituir nombres.
  - `image.prompt_orden` (`estilo_primero` | `accion_primero`) en la configuración y en `construir_prompt`. El orden de recorte no cambia y el valor por defecto sigue siendo el de siempre hasta tener datos.
  - `f2_f3_prueba.py --variantes`: genera solo las imágenes con cada combinación (`ip=`, `orden=`, `pasos=`, `cfg=`) en `v1/…vN/` y compara tiempo, VRAM, truncados y CLIP en `docs/evidencias/f2_variantes.md`.
  - `setup_windows.ps1 -Paso f2v` ejecuta 5 variantes: IP 0,6, 0,4 y 0,25, y 0,4 y 0,25 con la acción primero.
- **Presupuesto de tiempo (rápido) con lo medido:** texto ~75 s + imágenes ~55 s + voz ~7 s ≈ 2,3 min antes de sonido y mezcla. Objetivo < 5 min alcanzable.
- Verificación sin GPU: **227 tests en verde** (contenedor y bundle Linux), ruff limpio.
- **Siguiente [WINDOWS]:** `setup_windows.ps1 -Paso f2v`. Luego Claude revisa las imágenes de cada variante y fija la escala y el orden.

### 2026-11-10 13:00 · Windows (variantes de imagen) · 2.3 hecha → **F1, F2 y F3 completas**
- 5 variantes de la misma Bible y seeds (`outputs/f2/20261110_124150/v1..v5`, `docs/evidencias/f2_variantes.md`). Todas a ~3,5 s por imagen, con la misma VRAM y 3/5 prompts truncados.

  | Variante | CLIP texto | CLIP img-img (media / mín.) | Revisión visual |
  |---|---:|---|---|
  | ip=0.6 (anterior) | 0,350 | 0,81 / 0,74 | todas son el mismo retrato de frente; 2 fondos vacíos |
  | ip=0.4 | 0,365 | 0,75 / 0,62 | más escena; la escena 5 sigue con el fondo vacío |
  | ip=0.25 | 0,346 | 0,73 / 0,58 | más variedad, menos parecido |
  | **ip=0.4 + acción primero** | 0,355 | 0,75 / 0,62 | **la mejor:** protagonista reconocible, cada escena con su lugar y acción, sin fondos vacíos |
  | ip=0.25 + acción primero | 0,346 | 0,62 / 0,39 | la protagonista desaparece en la escena 1 |

- **Decisión:** `image.ip_adapter.scale: 0.4` y `image.prompt_orden: accion_primero` en `default.yaml`. Rápido y calidad lo heredan; C3 usa la misma escala.
- **Limitación conocida, anotada en CLAUDE.md:** IP-Adapter aplica la identidad de la protagonista a cualquier persona del cuadro, y Elias (50 años) sale joven y con su chaqueta.
  - Mitigación ya hecha: el descriptor empieza por el tipo ("old man age 50"); se notará en las historias nuevas.
  - Mitigación posible: bajar la escala en escenas cuyo sujeto no es el protagonista. Evaluarla en F6 si hay tiempo.
- Verificación sin GPU: **228 tests en verde** (contenedor y bundle Linux), ruff limpio.
- **Estado frente al cronograma:** F1 (mar 10), F2 (mié 11) y F3 (jue 12) terminadas el martes 10. Falta F4 (sonido y mezcla: 4.1–4.3 [AUTO] y luego 4.4 [WINDOWS]) y F5 (pipeline y UI, con el lanzador `StoryBook.cmd`).

### 2026-11-10 13:30 · sesión interactiva (Claude, a pedido de Diego) · 4.1, 4.2, 4.3
- Diego pidió adelantar el sonido sin esperar la ejecución automática. **La tarea programada se pausó** mientras tanto, para que no trabajaran dos sesiones a la vez sobre los mismos archivos.
- **4.1 · `sound/procedural.py`:** una receta numpy/scipy por cada `EtiquetaSonido` (21): ruido filtrado, osciladores, envolventes y eventos de Poisson.
  - Deterministas con la seed, 44,1 kHz, pico a −3 dBFS, fundidos.
  - Hasta 3 etiquetas por escena en capas (la primera manda).
  - Unos 2 s para los 5 ambientes de una historia en CPU.
- **4.2 · cadena de fallback:**
  - `sound/library.py`: índice `assets/sfx/index.json`. Solo acepta clips CC0 con archivo presente; sin índice, la biblioteca queda vacía. Hoy no hay clips, así que la cadena salta de los generativos a procedural.
  - `sound/generator.py`: `GeneradorSonido` recorre `sound.backends`.
    - Backends: `DiffusersSonidoBackend` (SA3, SAO y AudioLDM, con imports perezosos y el mismo procedimiento de `f0_hello.py`), `BibliotecaBackend` y `ProceduralBackend`.
    - Cada backend se carga una vez; si una escena falla, pasa al siguiente; un OOM abandona el backend; el audio silencioso o corto cuenta como fallo; procedural siempre va al final.
    - Registra el backend de cada escena, los fallbacks (`sonido:sa3:no_disponible`, `sonido:escena_N:<backend>_fallo`), errores y métricas.
    - Guarda `sfx_N.wav` en mono.
- **4.3 · `sound/mixer.py` + `mix` en la configuración:**
  - Remuestreo a 44,1 kHz; loop con crossfade de igual potencia hasta la duración de la voz más 0,5 s antes y 1 s después; fundidos.
  - pyloudnorm: voz a −18 LUFS y ambiente 12 dB por debajo.
  - Ducking de 6 dB con ataque de 30 ms y relajación de 350 ms: el ambiente queda a 12 dB bajo la voz en las pausas y a 18 dB mientras se habla.
  - Exporta `ambience_N.wav` (nivel relativo, sin ducking, para el reproductor separado de la UI) y `mix_N.wav`, PCM de 16 bits.
  - `MixConfig` valida que `ambiente_bajo_voz_db + ducking_db` no pase de 18.
- **Prueba con la voz real de F2** (Linux, procedural; `outputs/f4_preview/procedural_20261110_180543`): 5 mezclas de 40–50 s.
  - Voz a −18,0 LUFS, ambiente a −30,0 LUFS (12 / 18 dB), sin limitación y con picos de 0,72–0,82.
  - Sonido en 2 s y mezcla en 16 s en la VM.
- Nuevo `scripts/f4_sonido.py` + `setup_windows.ps1 -Paso f4` (4.4):
  - Narra y mezcla la historia de prueba con la cadena real del perfil (SA3 sin token → AudioLDM) y con procedural, para comparar.
  - `story/muestras.elegir_story` ahora es compartida por los scripts de F2 y F4.
- Tests: `tests/test_sound.py` (37) y `tests/test_f4_sonido.py` (2). **267 tests en verde** (contenedor y bundle Linux), ruff limpio.
- **Por validar en Windows (4.4):** AudioLDM real dentro de la cadena (tiempo y VRAM por clip), pertinencia del sonido al escuchar y niveles de la mezcla al oído.

### 2026-11-10 14:05 · Windows (4.4) + sesión interactiva · 4.4, 5.1, 5.2, 5.3 → **F4 completa; F5 lista salvo 5.4**
- **4.4 · prueba real** (`outputs/f4/20261110_130910`, `docs/evidencias/f4_sonido.md`):
  - Cadena real de rápido: SA3 no disponible (gated, sin token) → **AudioLDM en las 5 escenas**, a 1,34 s por clip de 8 s y 1,27 GB de VRAM pico.
  - Procedural: 0,09 s por clip.
  - Mezclas a −18,0 / −30,0 LUFS (12 / 18 dB), sin limitación. Unos 40 s en total, con narración.
  - Falta que Diego elija entre AudioLDM y procedural al escuchar; no bloquea nada.
- **5.1 · `storage.py` + `pipeline.py`:**
  - `Pipeline.generar(idea, genero, …, progreso)`: texto → imágenes → voz → sonido → mezcla, por etapas y liberando cada modelo.
    - Sin modelo de imagen: 5 ilustraciones de respaldo. Sin voz: queda el ambiente (`sfx_N`) y no hay mezcla.
    - Si el texto falla, la ejecución termina con un mensaje claro (por ejemplo, "Ollama no responde…") y el manifest queda en `fallida`.
  - `manifest.json`: tipo, perfil, idea, género, título, estado, etapas completas, segundos por etapa, fallbacks, errores, hardware, configuración y regeneraciones.
  - `regenerar_escena(carpeta, n)`: nueva seed de imagen (reutiliza la character sheet) y de sonido, y vuelve a mezclar; el texto y la voz no cambian.
  - `storage`: `listar_historias` (de `outputs/` y `samples/`, solo con manifest de tipo `storybook_historia`), escritura atómica y `archivos_escena`.
  - `mock.py`: historia de ejemplo real de F1 (`datos/historia_ejemplo.json`), imágenes de tarjeta de color, voz de tono y sonido procedural.
- **5.2 · UI** (`app/streamlit_app.py` + `ui_logica.py` + `StoryBook.cmd`):
  - Contenido:
    - Formulario validado (idea, género con "Otro" y perfil).
    - `st.status` con barra de progreso y etapas.
    - Visor con imagen, texto y 3 reproductores (narración, ambiente y mezcla), Anterior/Siguiente con n/5 y fase.
    - Regenerar escena, historias guardadas, etiqueta "Contenido generado por IA", detalles técnicos (backend del sonido, tiempo y alternativas usadas) y aviso de modo simulado.
  - **Probada en el contenedor** con Streamlit 1.67 y Playwright en modo simulado: generar, navegar, 3 audios, abrir guardada y regenerar, sin errores de página.
  - `StoryBook.cmd` (doble clic): comprueba uv y `.venv`, abre Ollama si no responde y espera hasta 60 s, arranca Streamlit y abre el navegador cuando la app responde. Con `mock`, modo simulado.
  - **`.streamlit/config.toml`: lo sobrescribí sin revisarlo antes** (error mío; ya existía desde F0). Lo recuperé del índice de git y lo fusioné:
    - Se conservan `gatherUsageStats = false`, `address = "localhost"` y el tema oscuro.
    - Cambia `headless = true`, para que Streamlit no pregunte un correo en la consola; el lanzador abre el navegador.
- **5.3 · `scripts/verify_offline.py`:**
  - Parchea `socket.connect`, `connect_ex` y `getaddrinfo`: bloquea y registra todo lo que no sea localhost.
  - Corre el pipeline simulado o real (`--real`), 1–3 ideas, y opcionalmente copia a `samples/`.
  - Test: el pipeline simulado no hace ninguna conexión.
  - `setup_windows.ps1 -Paso offline [-Muestras]` lo corre con `uv run --offline`.
- README: sección "Usar la aplicación". CLAUDE.md: notas de sonido e integración.
- Verificación: **284 tests en verde** (contenedor y bundle Linux), ruff limpio.
- **Estado frente al cronograma:** F0–F4 terminadas y F5 lista salvo la prueba real sin Wi-Fi (5.4), planeada para el sábado 14.
- **Queda para la tarea automática:** F6 (experimentos: `run_experiment.py`, `make_contact_sheet.py`, C1/C2/C3) y F7 (documentación). La tarea programada se reactiva al cerrar esta sesión.

### 2026-11-10 14:30 · Windows (5.4, prueba sin Internet) + decisiones · 5.4 parcial
- **5.4:**
  - `-Paso offline` con la red vigilada: "El Faro de Lucian" (`outputs/20261110_135837_…`), completa en 133 s, **0 conexiones externas**. El único fallback fue SA3, no disponible.
  - Los descriptores ya empiezan por el tipo ("boy age 12", "old man age 70"), gracias al cambio de prompt de las 12:50.
  - El presupuesto del perfil rápido (< 5 min) se cumple con margen: 2 min 13 s.
- **Sonido, decisión de Claude a pedido de Diego:** se mantiene **AudioLDM como backend principal** (generación desde `prompt_sonido`, la opción que valora el enunciado), con procedural como red.
  - Análisis de los 5 clips reales (espectrogramas): AudioLDM es pertinente pero irregular. Las escenas 1 y 3 concentran el sonido al principio y dejan el 47–55 % del clip 20 dB por debajo de su parte más fuerte, lo que en loop daría huecos periódicos.
  - Corrección en `sound/generator.py` (`fraccion_en_silencio`): si un clip generativo tiene más del 40 % en silencio, se reintenta con otra seed (+1000); si persiste, la escena pasa al siguiente backend. Procedural y biblioteca quedan exentos, porque reloj y pasos son intermitentes a propósito. 3 tests nuevos.
- **Git, pedido explícito de Diego:** Claude no debe aparecer como colaborador.
  - `setup_windows.ps1` ya no agrega `Co-Authored-By` en ningún commit. Regla en CLAUDE.md §3: el único autor es Diego, sin menciones a asistentes en commits, PR ni tags.
  - Nuevos `scripts/quitar_coautor.ps1` + `scripts/filtro_mensaje_commit.py`:
    1. Hacen commit de lo pendiente.
    2. Crean la rama local `respaldo-antes-de-quitar-coautor`.
    3. Reescriben los mensajes de `main` con `git filter-branch --msg-filter`, quitando solo las líneas `Co-Authored-By: Claude…` y `Claude-Session:`.
    4. Verifican que quedan 0 y suben con `--force-with-lease`.
  - Probado en un repositorio de prueba en el contenedor: 3 → 0 y el coautor humano se conserva. 3 tests del filtro.
- Verificación: **290 tests en verde** (contenedor y bundle Linux), ruff limpio.

### 2026-11-10 14:40 · historial limpio + ejemplos livianos · —
- **Historial de git limpio** (`quitar_coautor.ps1`, ejecutado por Diego a las 14:13):
  - Verificado leyendo los objetos de git: 32 commits en `main`, **0 con Claude como coautor** y un único autor (Diego Alejandro Urbano Pira).
  - `origin/main` coincide con `main`: ya está en GitHub.
  - Queda la rama local `respaldo-antes-de-quitar-coautor` (y `refs/original`) por seguridad. No se sube y se puede borrar cuando Diego quiera.
- **Ejemplos para `samples/`:**
  - `storage.exportar_muestra` copia la Bible, el manifest y las imágenes, y convierte narración, ambiente y mezcla a OGG Vorbis. Los `sfx_N` intermedios no se copian.
  - `archivos_escena` acepta `.wav` u `.ogg`; la UI reproduce ambos.
  - En los ejemplos no se ofrece "regenerar escena", para no mezclar WAV nuevos en una historia de muestra.
  - `-Paso offline -Muestras` también hace commit de `samples/`.
- Verificación: **290 tests en verde** (contenedor y bundle Linux), ruff limpio.

### 2026-11-10 14:45 · Windows (`-Paso offline -Muestras`) + correcciones · 5.4 parcial
- **Resultado de la corrida:**
  - Las 3 historias se generaron completas y sin conexiones externas:
    - "El Faro de Lucian" (`outputs/20261110_141757_…`), 138 s;
    - "La Biblia del Dragón" (`outputs/20261110_142017_…`), 126 s;
    - "El Camino de los Amigos" (`outputs/20261110_142223_…`), 126 s.
  - Al exportarlas a `samples/`, Python terminó con el código −1073741571 (0xC00000FD, desbordamiento de pila en Windows). Solo llegaron archivos sueltos de la primera historia (`voice_1.ogg` cortado, de 3 KB), y quedaron en un commit local.
- **Causa 1, exportación a OGG:** `soundfile` escribía cada audio de 40–50 s a OGG Vorbis de una sola vez. En Windows eso desborda la pila del codificador Vorbis de libsndfile.
  - Corrección en `storage._wav_a_ogg`: se lee el WAV y se escribe el OGG por bloques de 16 384 muestras. Con eso el codificador nunca recibe un bloque grande.
- **Causa 2, ambientes de AudioLDM casi mudos:**
  - Algunos clips pasaron el control de huecos, que es relativo a la parte más fuerte del clip, pero eran casi silencio absoluto:
    - "El Camino de los Amigos", escenas 2, 4 y 5: alrededor de −72 dBFS, ambiente en −inf LUFS;
    - "La Biblia del Dragón", escena 2: −68,9 LUFS.
  - En la mezcla esos ambientes no se oían.
  - Correcciones:
    - `sound/generator.py`: nuevo `problema_de_ambiente`, que además de los huecos exige un nivel mínimo de −45 dBFS (`NIVEL_MINIMO_DBFS`). Si un clip generativo no lo cumple, se reintenta con otra seed y, si persiste, la escena pasa al siguiente backend (biblioteca → procedural). El manifest registra `nivel_dbfs` e `intentos`.
    - `sound/mixer.py`: `medir_lufs` ya no devuelve −inf para señales muy bajas pero no nulas (todo bajo la compuerta absoluta de −70 LUFS). En ese caso estima el nivel por RMS.
- **Nuevo, para no regenerar las historias:**
  - `Pipeline.rehacer_sonido(carpeta, escenas)` hace un nuevo ambiente y una nueva mezcla solo para esas escenas. Texto, imágenes y voz no cambian, y queda registrado en `regeneraciones` del manifest con `tipo: sonido`.
  - `scripts/exportar_muestras.py` toma las 3 historias reales completas más recientes. Revisa cada ambiente generativo con `problema_de_ambiente` y rehace los débiles en GPU (unos segundos por escena). Luego exporta cada historia a `samples/` y sobrescribe la exportación parcial. Si una historia falla, informa el error y sigue con las demás.
  - `setup_windows.ps1 -Paso muestras` hace commit del código, ejecuta `exportar_muestras.py` y versiona `samples/` con las evidencias. La salida queda en `docs/evidencias/exportar_muestras.txt`.
- Verificación: **294 tests en verde**, ruff limpio. Tests nuevos:
  - clip generativo demasiado bajo → reintento y fallback a procedural;
  - `medir_lufs` finito bajo la compuerta;
  - rehacer y exportar con un ambiente débil simulado;
  - OGG por bloques que conserva la duración.

### 2026-11-10 14:50 · Windows (`-Paso muestras`) · 5.4 hecha → **F5 completa**
- **Resultado** (`docs/evidencias/exportar_muestras.txt`):
  - "El Camino de los Amigos": ambiente rehecho en las escenas 2, 4 y 5. AudioLDM volvió a dar clips de −67 a −75 dBFS en los dos intentos de cada escena, y las tres pasaron a procedural.
  - "La Biblia del Dragón": escena 2 rehecha, también con procedural (−71/−72 dBFS en AudioLDM).
  - "El Faro de Lucian": sin cambios.
  - Las 3 historias quedaron exportadas a `samples/` (7,3–7,9 MB cada una) y subidas a GitHub: commit del código 8e36591 y commit de los ejemplos 83460fc, que también subió el commit local de la prueba sin Internet.
- **Revisión de los 15 OGG de cada historia** (leídos con soundfile en el shell Linux):
  - Todos decodifican.
  - Duraciones: voz de 39,5 a 50,2 s; ambiente y mezcla, 1,5 s más largos (pre-roll y post-roll).
  - Niveles RMS: voz de −14,3 a −15,4 dB, ambiente de −26 a −34 dB y mezcla de −17,7 a −17,9 dB. El ambiente queda audible en las 15 escenas de cada historia.
  - En total, 9 escenas con AudioLDM y 6 con procedural.
- **Hallazgo sobre AudioLDM:** 5 de los 6 `prompt_sonido` con adjetivos de intensidad baja ("soft", "gently", "faint") dieron clips casi mudos en todos los intentos. Los 9 prompts sin esos adjetivos salieron bien. Se corrige a continuación (ver la siguiente entrada).

### 2026-11-10 14:54 · sesión interactiva (Claude) · 6.1 hecha + corrección del sonido
- **AudioLDM, prompts sin intensidad baja** (`sound/generator.py`):
  - `preparar_prompt_audio` quita "soft", "gently", "faint", "quiet" y similares, y las menciones de silencio ("beneath silence", "into stillness"). El volumen lo fija la mezcla, así que esas palabras no aportan nada.
  - Ejemplo: "Soft wind blows through trees, birds sing gently." → "Wind blows through trees, birds sing.".
  - `negativo_compatible` quita del negative prompt lo que el prompt pide. Con "birds sing" y el negativo "singing", AudioLDM recibía órdenes opuestas.
  - El prompt y el negativo efectivos quedan en el manifest (`prompt_efectivo`, `negativo_efectivo`).
  - Se valida en la batería 6.2: la columna `sonido` de `results.csv` muestra cuántas escenas quedaron con AudioLDM.
- **6.1, batería de experimentos:**
  - `scripts/run_experiment.py`. Para cada idea (4 por defecto: terror, fantasía, ciencia ficción e infantil):
    1. Genera la historia completa con `experiments/c3_ipadapter`, la configuración de producción. Mide tiempos por etapa, VRAM pico, CLIP (img-img e img-texto) y el WER de la narración con Whisper small.
    2. Sobre el mismo texto (la Bible sin seeds), genera solo las imágenes con C1 (sin Bible, seeds aleatorias), C2 (Bible sin IP-Adapter) y `calidad` (DPM++ 25 pasos). Así la única diferencia entre configuraciones es la estrategia de imagen, y sale también LCM frente a 25 pasos.
    - Cada prueba es una fila de `experiments/results.csv`; las columnas `*_1a5` se llenan a mano.
    - Si una idea o una variante falla, queda como fila con el error y la batería sigue.
    - El resumen va a `docs/evidencias/f6_experimentos_<id>.md` y las hojas de contactos a `docs/evidencias/f6_hojas/`.
    - Opciones: `--ideas N`, `--variantes …`, `--completa experiments/llm_8b` (8B, opcional), `--sin-clip`, `--sin-wer`.
  - `src/storybook/evaluation/report.py`: lectura y escritura de `results.csv` (valida el encabezado), resumen por configuración y tablas por historia en Markdown. También se puede usar sola: `uv run python -m storybook.evaluation.report`.
  - `src/storybook/evaluation/contact_sheet.py` y su CLI `scripts/make_contact_sheet.py`: cuadrícula JPEG con la character sheet y las 5 escenas, con número y fase. Usa Arial o DejaVu para las tildes y, si no hay ninguna, las quita.
  - `setup_windows.ps1 -Paso experimentos [-Ideas N]`: commit del código, batería y commit de `results.csv` con las evidencias.
  - Comparaciones que no se repiten en la batería:
    - 4B frente a 8B ya está medido en 1.4 (`f1_resumen*.md`).
    - SA3 no está disponible (repositorio con acceso restringido), así que la comparación de sonido es AudioLDM frente a procedural (columna `sonido`).
- Verificación: **307 tests en verde**, ruff limpio. Tests nuevos:
  - 2 de prompts de audio;
  - 7 de 6.1: CSV, resumen, hoja de contactos, CLI, sin fuentes del sistema y batería completa con backends simulados, incluida una variante inexistente.

### 2026-11-11 11:38 · Windows (`-Paso experimentos`) · 6.2 hecha
- **Corrida:** 11:15 a 11:33 (18 min), 16 pruebas y ninguna fallida. Commits 046a765 (código) y 89eb929 (evidencias), subidos a GitHub.

| Configuración | CLIP img-img (media / mín.) | CLIP img-texto | Imágenes (mediana) | VRAM pico |
|---|---|---|---|---|
| C3 (Bible + seed fija + IP-Adapter 0,4, LCM 6 pasos) | **0,765** / 0,618 | 0,319 | 27,1 s | 4076 MB |
| C2 (Bible + seed fija, sin IP-Adapter) | 0,616 / 0,382 | 0,335 | 17,2 s | 4078 MB |
| C1 (sin Bible, seeds aleatorias) | 0,501 / 0,326 | 0,343 | 17,2 s | 4086 MB |
| `calidad` (C3 con DPM++ 25 pasos) | **0,778** / 0,614 | 0,347 | 54,9 s | 4070 MB |

- **Consistencia visual:** C3 > C2 > C1 en las 4 historias. La Bible sola sube la similitud entre ilustraciones de 0,50 a 0,62; con IP-Adapter llega a 0,77. Es la hipótesis del proyecto, ahora con datos.
- **Costo de la consistencia:**
  - El CLIP img-texto baja un poco con IP-Adapter (0,343 en C1 frente a 0,319 en C3): la referencia del personaje compite con el prompt.
  - En las hojas de contactos de C3 casi todas las escenas son retratos del personaje mirando a la cámara, con poca acción.
  - En "El Camino de los Amigos" aparecen clones del protagonista cuando el prompt pide un grupo (escena 2, también en `calidad`).
  - C1 muestra escenas más variadas, pero el personaje cambia por completo; en la escena 3 de la historia de terror aparece un robot.
- **LCM 6 pasos frente a DPM++ 25 pasos:** casi la misma consistencia (0,765 frente a 0,778) y CLIP img-texto algo mayor (0,347), por el doble de tiempo de imagen (55 s frente a 27 s). Se confirma LCM para el perfil rápido.
- **Texto y voz:**
  - LLM de 74 a 90 s por historia.
  - WER medio de 0,035 a 0,048 (la narración se entiende bien).
  - Historia completa en 124–129 s. La primera tardó 182 s porque las imágenes tomaron 65 s con los modelos aún sin cachear.
- **VRAM:** el pico de NVML (toda la GPU) llega a unos 4070–4086 MB de 4096 MB en todas las configuraciones. Funciona, pero sin margen; en 6.3 conviene reportar también el pico de torch, que también está en los manifests.
- **Sonido:**
  - AudioLDM quedó en 12 de 20 escenas: ciencia ficción 5/5, fantasía 4/5, terror 2/5 e infantil 1/5. Las otras 8 pasaron a procedural.
  - Quitar "soft", "gently" y "faint" no bastó: con el prompt ya limpio, "wind (rustling/blowing) through trees…" sigue dando clips de −47 a −75 dBFS o con huecos del 59–89 %. En cambio, "wind howls…", "machinery hums…" o "wind blows through narrow streets" salen bien.
  - Se prepara `scripts/f6_audioldm_prompts.py` (`-Paso audioldm`): con los 20 prompts de esta batería y 2 seeds, compara 4 variantes (base, sufijo ", high quality, clear", guidance 4,0, ambas). Tiene 3 tests con un backend falso.
- **Para el informe (6.3), observaciones de la historia:**
  - El LLM repite "wind" + "heartbeat" en casi todos los `prompt_sonido`, sin importar el género.
  - En "Un perro y un gato…" el protagonista es un niño con un gato: el perro desaparece.
  - Las columnas `*_1a5` de `results.csv` quedan por llenar a mano al revisar las hojas y los audios.

### 2026-11-11 11:53 · Windows (`-Paso audioldm`) + sesión interactiva · sufijo de calidad adoptado
- **Prueba** (`docs/evidencias/f6_audioldm_prompts.md` y `.json`, commit 61d15a5):
  - Prompts: los 20 `prompt_sonido` de la batería 20261111_111458.
  - Seeds: 101 y 1101. Una escena pasa si alguna de las 2 sirve, como los 2 intentos de producción.

| Variante | Escenas que pasan | Clips aptos | Nivel mediano |
|---|---|---|---|
| base (producción, guidance 2,5) | 13/20 | 24/40 | −18,2 dBFS |
| sufijo ", high quality, clear" | **20/20** | 39/40 | −14,6 dBFS |
| guidance 4,0 | 12/20 | 20/40 | −21,4 dBFS |
| sufijo + guidance 4,0 | **20/20** | 40/40 | −9,2 dBFS |

- **Lectura de los resultados:**
  - El sufijo resuelve justo los prompts que fallaban, que en base daban de −32 a −63 dBFS: "wind rustling through trees", "wind through trees…" y "birds sing". Con sufijo dan de −7 a −29 dBFS.
  - Subir el guidance, por sí solo, empeora el resultado.
  - Al llevar "high quality", "low quality" sale del negative prompt (`negativo_compatible`). La mejora medida es la suma de las dos cosas, y así se reproduce en producción.
- **Decisión:** se adopta solo el sufijo y el guidance queda en 2,5. Es el cambio mínimo, y el guidance alto no mostró beneficio propio: la diferencia entre 39/40 y 40/40 es ruido.
- **Cambios:**
  - `SoundConfig.audioldm_sufijo` (por defecto ", high quality, clear") y `configs/default.yaml`.
  - `sound/generator.prompts_para_backend` arma el prompt y el negativo para cada modelo; el sufijo se aplica solo a AudioLDM.
  - `scripts/f6_audioldm_prompts.py` apaga el sufijo de producción para que la variante base siga siendo reproducible.
  - `scripts/exportar_muestras.py` tiene `--las-de-samples` (rehace las historias que ya están en `samples/`) y `--rehacer-procedurales` (reintenta AudioLDM en las escenas procedurales). `-Paso muestras` usa los dos.
- Verificación: **311 tests en verde**, ruff limpio. Tests nuevos:
  - sufijo solo para AudioLDM y negativo sin "low quality";
  - la prueba apaga el sufijo de producción;
  - reintento de escenas procedurales y selección de las historias de `samples/`.
- **Validar en Windows** (`-Paso muestras`): las 6 escenas procedurales de los ejemplos deberían pasar a AudioLDM.

### 2026-11-11 11:59 · Windows (`-Paso muestras`) · sufijo de AudioLDM validado en la aplicación
- `-Paso muestras` (11:57–11:58), con `--las-de-samples --rehacer-procedurales`. Las 6 escenas de los ejemplos que tenían sonido procedural pasaron a AudioLDM al primer intento, sin ningún clip rechazado:
  - "El Faro de Lucian", escena 3;
  - "La Biblia del Dragón", escena 2;
  - "El Camino de los Amigos", escenas 1, 2, 4 y 5.
- Con esto, las 3 historias de `samples/` usan AudioLDM en sus 15 escenas. Ambiente de −26 a −34 dB RMS y mezcla de −17,7 a −17,9 dB, verificados al leer los OGG.
- Commits 0049286 (código) y 3629671 (ejemplos), subidos a GitHub.

### 2026-11-11 12:08 · sesión interactiva (Claude) · 6.3 hecha → **F6 completa**
- **`docs/informe/analisis_experimentos.md`:** preguntas P1–P5, diseño, resultados con tablas y gráficas, revisión cualitativa de las hojas de contactos, VRAM por etapa, sonido, LLM, conclusiones, limitaciones y trabajo futuro. Es la base de las secciones de resultados y discusión del informe (7.2).
- **Gráficas** (`docs/informe/graficas/`):
  - `consistencia.png`
  - `pertinencia.png`
  - `costo_consistencia.png`
  - `tiempos_etapas.png`
  - `audioldm.png`

  Se dibujan con Pillow, sin dependencias nuevas, en fondo blanco para imprimir y con la paleta Okabe-Ito. Las genera `scripts/graficas_informe.py` a partir de `results.csv` y `f6_audioldm_prompts.json`. Código en `src/storybook/evaluation/graficas.py`.
- **VRAM por etapa** (de los manifests de la batería, para el informe):
  - Imágenes C3: 3156 MB asignados por torch, 4034 MB reservados y 4076 MB en NVML. El tope de NVML es sobre todo caché del asignador; quedan unos 900 MB de margen real.
  - AudioLDM: 943 MB asignados.
  - Voz: CPU.
  - Ollama se libera antes de las imágenes (la GPU parte de 196–226 MB).
- **Matiz de la métrica:** parte del CLIP img-img alto de C3 viene de la composición repetida (retratos), no solo de la identidad del personaje. Queda explicado en el análisis (sección 3).
- Verificación: **315 tests en verde**, ruff limpio. 4 tests nuevos de las gráficas: los 3 tipos, valores faltantes, un punto en x = 0, la selección de batería y la CLI.
- **Pendiente:** las columnas `*_1a5` de `results.csv` (revisión humana, tarea 7.3).

### 2026-11-11 12:19 · sesión interactiva (Claude) · 7.1 hecha
- **`docs/arquitectura.md`** (nuevo), con 4 diagramas Mermaid verificados con `mmdc`:
  - componentes;
  - flujo de datos;
  - secuencia de una generación y paso de la GPU entre modelos;
  - cadenas de *fallback*.

  Incluye además tablas de módulos, memoria medida por etapa, capas de consistencia, estructura de una historia, perfiles, decisiones de diseño con la alternativa descartada y su motivo, y calidad del software.
- **`README.md`:**
  - estado actual y tabla de documentos;
  - historias de ejemplo;
  - 3 capturas reales de la app (`docs/informe/capturas/`), tomadas con Playwright sobre "La Biblia del Dragón" de `samples/`;
  - resultados medidos;
  - comandos de experimentos;
  - tabla de solución de problemas (9 síntomas).
- **`MODELS.md`:**
  - revisión (commit) de cada repositorio, tomada de `docs/models_registry.json`, y estado real: SA3 y SAO no disponibles (acceso restringido) y AudioLDM en uso con el sufijo;
  - nueva tabla de mediciones por modelo;
  - Qwen3-0.6B marcado como no evaluado y corrección de "Python 3.11" a 3.12.
- **Correcciones en la app**, encontradas al tomar las capturas:
  - **Avisos viejos en *Detalles técnicos*:** después de rehacer el sonido de los ejemplos, seguía diciendo "Sonido de la escena 2: falló AudioLDM", aunque la escena 2 ya usaba AudioLDM.
    - Nuevo `ui_logica.fallbacks_vigentes`: al regenerar una escena o rehacer su sonido, descarta los avisos anteriores de esa escena.
    - "<backend> no estaba disponible" solo se muestra si alguna escena usa un backend posterior en la cadena.
    - Arregla también los manifests ya exportados, sin volver a generar nada.
  - **Perfiles con tiempos medidos:** "Rápido · unos 2 minutos" y "Calidad · imágenes con 25 pasos, unos 3 minutos". Antes decía "3 a 5" y "5 a 12 minutos", estimaciones previas a las mediciones.
- **Observación para el informe:** en "La Biblia del Dragón" el LLM nombró a los personajes "Kai Kai" y "Morin Morin" (nombre duplicado en el plan; no es un error del código).
- Verificación: **316 tests en verde**, ruff limpio.

### 2026-11-11 12:27 · Windows (`-Paso git`) + sesión interactiva (Claude) · 7.2 hecha
- `-Paso git` (12:21): commit 24f465e con 19 archivos (6.3 y 7.1), subido a GitHub.
- **`docs/informe/informe.md`:** las 12 secciones de CLAUDE.md §16, más portada, resumen, referencias (18) y anexos.
  - Datos: los de las evidencias y de `analisis_experimentos.md`.
  - Figuras:
    - los 4 diagramas de `docs/arquitectura.md`, convertidos a PNG con `mmdc` (`docs/informe/diagramas/`);
    - las 5 gráficas;
    - la captura del visor;
    - las hojas de contactos de C1 y C3 (terror).
  - Ética: transparencia, reglas de contenido por género, sesgos observados, voz sin clonación, licencias (AudioLDM es CC BY-NC-SA, así que el uso es académico), privacidad y costo computacional (estimado en 3–5 Wh por historia con el límite de 75 W; es una estimación, no una medición).
- **`docs/informe/informe.pdf`:** 21 páginas A4, con portada, encabezado y numeración. Se genera en el entorno de Claude (Markdown → HTML → Chromium); se regenera cuando cambie `informe.md`.
- **`[DATO PENDIENTE]`** (tarea 7.3):
  - nombre del docente;
  - lista de verificación 1–5 por historia;
  - enlace del video.
- `README.md`: nota sobre equipos sin GPU NVIDIA (solo el modo simulado y los ejemplos) y aviso de *symlinks* de Hugging Face en la tabla de problemas.

### 2026-11-11 12:30 · sesión interactiva (Claude) · 8.1 hecha → **todas las tareas [AUTO] completas**
- **`docs/sustentacion.md`:**
  - lista de verificación previa, que incluye una generación de calentamiento porque la primera del día tarda 182 s;
  - guion de demo de 10 minutos con tiempos, qué mostrar y qué decir;
  - plan B para 6 fallas;
  - las 5 respuestas centrales de la defensa (CLAUDE.md §17);
  - 30 preguntas probables con respuestas cortas basadas en los datos medidos;
  - tabla de datos para tener a mano.
- **Respaldo en vivo:** `StoryBook.cmd respaldo` pone `STORYBOOK_SIN_AUDIO_GENERATIVO=1`.
  - `GeneradorSonido` trata los modelos generativos como no disponibles, sin cargarlos, y la cadena pasa a biblioteca y procedural, quedando registrado en el manifest.
  - La barra lateral muestra un aviso amarillo.
  - Sirve para la sustentación (CLAUDE.md §17) y para el video (CLAUDE.md §16.3: "demostración de un fallback").
  - Test nuevo, y verificado con Playwright que el aviso aparece y la app no da errores.
- Verificación: **317 tests en verde**, ruff limpio.
