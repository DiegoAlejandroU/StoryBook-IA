# Arquitectura de StoryBook IA

StoryBook IA convierte una **idea** y un **género** en un cuento de **5 escenas**. Cada escena trae texto narrativo, ilustración, narración y ambiente sonoro. Todo se genera en el equipo local y sin conexión, con una GPU de 4 GB.

La arquitectura responde a tres restricciones:

1. **4 GB de VRAM:** los modelos pesados no caben a la vez. El pipeline es secuencial por etapas: cada modelo se carga una vez, procesa las 5 escenas y se libera antes del siguiente.
2. **Coherencia entre modalidades:** hay una sola fuente de verdad, la **Story Bible**. Es un JSON validado con Pydantic v2 del que salen el texto, los prompts de imagen y los de sonido.
3. **Robustez en la demo:** cada etapa tiene una alternativa automática (*fallback*), y todo queda registrado en un `manifest.json`.

> **Versión final (23 nov):** la generación es escena por escena (`progresivo.py`), con un ilustrador que describe cada plano y tres perfiles de modelos (Rápido · SD 1.5, Modelo grande · SDXL, Avanzada · FLUX.1-schnell + XTTS-v2). Los diagramas reflejan esa versión; las tablas de memoria de las secciones 3 y 5 son de la batería del perfil rápido (11 nov). Las mediciones de los tres perfiles están en `docs/informe/informe.pdf`, secciones 8.7 a 8.9.

## 1. Componentes

```mermaid
flowchart TB
    subgraph UI["Interfaz"]
        APP["app/streamlit_app.py<br/>(libro, solo dibuja)"]
        UIL["ui_logica.py<br/>(lógica testeable)"]
        CMD["StoryBook.cmd<br/>(lanzador)"]
    end
    subgraph ORQ["Orquestación"]
        PROG["progresivo.py<br/>generación escena por escena"]
        GEC["generacion_en_curso.py<br/>un trabajo de GPU a la vez"]
        PIPE["pipeline.py<br/>Dependencias · regenerar"]
        CFG["config.py<br/>rapido · sdxl · avanzada"]
        GPU["gpu.py<br/>NVML · liberar VRAM"]
        STO["storage.py<br/>outputs/ · samples/"]
        MOCK["mock.py<br/>dependencias simuladas"]
    end
    subgraph TXT["Texto · GPU (Ollama)"]
        PLAN["story/planner.py<br/>plan · escenas · ilustrador"]
        REPA["story/reparto.py<br/>reparto fiel a la idea"]
        LLM["story/llm_client.py<br/>JSON Schema · reparación"]
        SCH["schemas.py<br/>Story Bible · PlanoVisual"]
    end
    subgraph IMG["Imagen · GPU"]
        PB["image/prompt_builder.py<br/>presupuesto de tokens"]
        IGEN["image/generator.py<br/>SD 1.5 · SDXL + IP-Adapter"]
        FLX["image/flux.py<br/>FLUX fp8 · group offloading"]
        SEL["image/seleccion.py<br/>mejor de 2 con OpenCLIP"]
    end
    subgraph AUD2["Voz y sonido"]
        TTS["voice/tts.py<br/>Piper · CPU"]
        XT["voice/xtts.py<br/>proceso .venv-xtts · GPU"]
        SGEN["sound/generator.py<br/>AudioLDM → respaldos"]
        MIX["sound/mixer.py<br/>LUFS · ducking"]
    end
    OLL[("Ollama<br/>localhost:11434")]
    CMD --> APP --> UIL
    APP --> GEC --> PROG
    PROG --> PIPE
    PROG --> CFG
    PROG --> GPU
    PROG --> STO
    MOCK -.-> PIPE
    PROG --> PLAN --> LLM --> OLL
    PLAN --> REPA
    PLAN --> SCH
    PROG --> IGEN
    IGEN --> PB
    IGEN --> FLX
    IGEN --> SEL
    PROG --> TTS
    TTS --> XT
    PROG --> SGEN
    PROG --> MIX
```

| Módulo | Responsabilidad | Dónde corre |
|---|---|---|
| `schemas.py` | Story Bible y validaciones: idioma por campo, presupuesto de tokens CLIP, ids, un solo protagonista, exactamente 5 escenas | — |
| `story/` | Planificador por etapas (plan y luego escena por escena con el canon acumulado), cliente de Ollama con JSON Schema y reparación, y auditor de coherencia | GPU (Ollama) |
| `image/` | Prompt = estilo + descriptores de los personajes + acción, dentro de 77 tokens; seeds; SD 1.5 (DreamShaper 8) + LCM-LoRA + IP-Adapter con *character sheet* | GPU |
| `voice/tts.py` | Piper `es_MX-claude-high`, una voz fija con parámetros constantes | CPU |
| `sound/` | Cadena de sonido con control de calidad, biblioteca CC0, síntesis procedural y mezcla | GPU → CPU |
| `pipeline.py` | Orden de etapas, liberación de VRAM, *fallbacks*, manifest, regenerar escena y rehacer sonido | — |
| `storage.py` | `outputs/<run_id>/`, listado de historias y exportación a `samples/` (OGG) | — |
| `evaluation/` | CLIP (img-img, img-texto), WER con Whisper, `results.csv`, gráficas y hojas de contactos | CPU |
| `app/` + `ui_logica.py` | Interfaz Streamlit: formulario, progreso, visor de escenas, regenerar e historias guardadas | — |

**La lógica no depende de la interfaz:** la app solo dibuja. Todo lo testeable vive en `ui_logica.py`, `pipeline.py` y `storage.py`.

**Las dependencias pesadas se inyectan** (`Dependencias`): Ollama, diffusers y Piper se reemplazan por dobles simulados (`mock.py`). Así se prueban la UI y el pipeline completo sin GPU: 431 pruebas en Linux sin torch.

## 2. Flujo de datos

```mermaid
flowchart TB
    subgraph A["1 · Plan de la historia (una vez)"]
        direction LR
        IN["Idea + género<br/>+ perfil"] --> VAL{"Validación<br/>StoryRequest"}
        VAL -- inválida --> ERR["Mensaje claro<br/>en la UI"]
        VAL --> PLAN["LLM · plan (Qwen3 4B)<br/>estilo, personajes con<br/>descriptor fijo, canon"]
        PLAN --> REP{"¿Reparto fiel<br/>a la idea?"}
        REP -- no --> FIX["LLM corrige el reparto<br/>niño → boy · niña → girl"]
        FIX --> BIB
        REP -- sí --> BIB[("Story Bible<br/>story.json")]
    end
    subgraph B["2 · Por cada escena n = 1…5"]
        direction LR
        TX["LLM · escena n<br/>(canon + escenas previas)"] --> PV["LLM · ilustrador<br/>quién, cuántos, acción,<br/>lugar, encuadre"]
        PV --> PR["prompt_builder<br/>estilo + acción<br/>+ descriptores"]
        PR --> IM["Imagen<br/>SD 1.5 · SDXL<br/>FLUX.1-schnell"]
        IM --> SEL["OpenCLIP elige<br/>1 de 2 versiones<br/>(SD 1.5 y SDXL)"]
        TX --> VO["Voz<br/>Piper · XTTS-v2"]
        TX --> SO["Ambiente<br/>AudioLDM → CC0<br/>→ procedural"]
        VO --> MX["Mezcla<br/>voz −18 LUFS<br/>ambiente −12 dB"]
        SO --> MX
        SEL --> OUT["scene_n.png<br/>voice_n.wav · mix_n.wav"]
        MX --> OUT
    end
    subgraph C["3 · Resultado"]
        direction LR
        MAN[("manifest.json<br/>modelos · seeds · tiempos<br/>VRAM · fallbacks")]
        UI["Libro en la UI: la escena n<br/>se lee mientras se genera la n+1"]
    end
    A --> B --> C
```

**Idioma por campo:** el texto narrativo, el título y los resúmenes van en español. Los prompts para el ilustrador y el sonidista van en inglés, porque SD 1.5 y AudioLDM se entrenaron con descripciones en inglés. El esquema rechaza cada campo escrito en el idioma equivocado y devuelve el error al modelo para que lo repare.

## 3. Secuencia de una generación y uso de la GPU

```mermaid
sequenceDiagram
    autonumber
    participant U as Usuario (Streamlit)
    participant P as progresivo.py (hilo)
    participant O as Ollama (GPU)
    participant I as Imagen (GPU)
    participant X as Proceso XTTS (GPU)
    participant A as AudioLDM (GPU)
    participant S as Disco
    U->>P: generar(idea, género, perfil)
    Note over P,I: el modelo de imagen se precarga en la RAM mientras el LLM escribe el plan
    P->>O: plan + reparto (JSON Schema)
    O-->>P: plan validado
    loop escena n = 1…5
        P->>O: escena n + plano visual
        O-->>P: texto y plano validados
        P->>O: descargar el modelo (keep_alive 0)
        P->>I: ilustrar (FLUX: bloque a bloque desde la RAM)
        I-->>P: scene_n.png
        P->>I: estacionar (empty_cache): GPU libre
        P->>X: narrar (una línea JSON por stdin)
        X-->>P: voice_n.wav (el modelo vuelve a la RAM)
        P->>A: ambiente de la escena n
        A-->>P: sfx_n.wav (control de nivel y silencio)
        P->>S: mezcla + manifest
        P-->>U: escena n lista (se puede leer)
    end
```

**Memoria medida** (batería de experimentos, `docs/informe/analisis_experimentos.md`):

| Etapa | Pico en la GPU | Comentario |
|---|---|---|
| Texto (Qwen3 4B Q4_K_M) | ~2,5 GB, 100 % en GPU | `num_ctx` 4096 y `num_gpu` 99. Se descarga antes de las imágenes: la GPU vuelve a 196–226 MB. |
| Imágenes (C3) | 3,16 GB asignados por torch, 4,03 GB reservados | El tope de NVML (4,08 GB) es sobre todo caché del asignador. VAE slicing y SDPA; sin attention slicing. |
| Sonido (AudioLDM) | 0,94 GB asignados | ~1,3 s por clip de 8 s. |
| Voz y mezcla | CPU | No compiten por la VRAM. |

Una historia completa con el perfil rápido tarda unos 2 minutos (124–129 s): texto ~60 %, imágenes ~21 %, sonido ~10 %, voz ~7 % y mezcla ~2 %.

## 4. Alternativas automáticas (*fallbacks*)

```mermaid
flowchart TB
    subgraph T["Texto"]
        direction LR
        T1["Llamada con<br/>JSON Schema"] -->|inválida| T2["Reparación con el<br/>error de validación"]
        T2 -->|vuelve a fallar| T3["Intento limpio<br/>con otra seed"]
        T3 -->|agota intentos| T4["Mensaje claro<br/>en la UI"]
    end
    subgraph I["Imagen"]
        direction LR
        I1["SD 1.5 · SDXL · FLUX"] -->|"falta de memoria o<br/>el modelo no carga"| I2["Ilustración de respaldo<br/>imagen:respaldo"]
    end
    subgraph V["Voz"]
        direction LR
        V1["XTTS-v2<br/>(Avanzada)"] -->|el proceso falla| V2["Piper"]
        V2 -->|falla| V3["Escena sin narración<br/>voz:sin_narracion"]
    end
    subgraph SND["Ambiente (por escena)"]
        direction LR
        S1["Stable Audio 3<br/>(Rápido y SDXL)"] -->|no descargado| S3["AudioLDM<br/>+ sufijo de calidad"]
        S3 -->|"clip mudo o con<br/>huecos (2 intentos)"| S4["Biblioteca CC0"]
        S4 -->|sin clip para<br/>la etiqueta| S5["Síntesis procedural<br/>(nunca falla)"]
    end
    T ~~~ I ~~~ V ~~~ SND
```

- **Texto:** es la única etapa sin la que no hay historia. Por eso tiene reparación y reintentos, y si aun así falla, un mensaje claro (por ejemplo, "Ollama no responde…").
- **Sonido:** es la etapa con más alternativas. Una escena nunca queda sin ambiente.
  - **Control de calidad:** cada clip generativo debe tener un nivel de al menos −45 dBFS y menos del 40 % del tiempo en silencio. Si no lo cumple, se reintenta con otra seed y luego se pasa al siguiente backend.
  - **Sufijo de calidad:** el sufijo ", high quality, clear" para AudioLDM se adoptó en la tarea 6.2. Llevó la tasa de clips aptos de 13/20 a 20/20 escenas.
- **Registro:** cada alternativa usada queda en `manifest.json["fallbacks"]`, por ejemplo `sonido:sa3:no_disponible`. La UI la muestra en *Detalles técnicos*.

## 5. Consistencia visual

La consistencia se demuestra con evidencia; la batería de la tarea 6.2 compara las estrategias C1, C2 y C3:

| Capa | Mecanismo | Efecto medido (CLIP img-img) |
|---|---|---|
| Story Bible | Estilo visual y descriptor fijo del personaje en cada prompt | 0,501 → 0,616 |
| Seed fija y compartida | `consistency.py` deriva las seeds de una base (1234) | (incluida en C2) |
| IP-Adapter 0,4 | *Character sheet* del protagonista como referencia visual | 0,616 → 0,765 |
| Orden del prompt `accion_primero` | La acción va antes del estilo, para no repetir retratos de frente | Elegido en las variantes de la tarea 2.3 |
| Límite de 77 tokens | `prompt_builder` recorta por prioridad (personajes > acción > estilo) y registra los truncamientos | Evita que CLIP corte el descriptor |

**Limitación conocida:** IP-Adapter aplica la identidad de la *character sheet* a cualquier persona del cuadro. Eso favorece composiciones de retrato y produce clones cuando el prompt pide un grupo. Las mitigaciones están en la sección 10 del análisis de experimentos.

## 6. Estructura de una historia guardada

```text
outputs/<AAAAMMDD_HHMMSS>_<idea>/
├── story.json           Story Bible final (con las seeds usadas)
├── manifest.json        tipo, perfil, configuración completa, modelos y versiones, hardware,
│                        tiempos y VRAM por etapa, fallbacks, errores y regeneraciones
├── character_sheet.png  referencia del protagonista (IP-Adapter)
├── scene_1..5.png       ilustraciones 768 × 512
├── voice_1..5.wav       narración (Piper)
├── sfx_1..5.wav         clip de sonido tal como salió del backend
├── ambience_1..5.wav    ambiente ajustado a la duración de la voz (sin ducking)
└── mix_1..5.wav         voz + ambiente con ducking
```

- Una historia se reabre sin regenerarla (`storage.cargar_historia`).
- Las historias de ejemplo se versionan en `samples/` con los audios en OGG Vorbis, de unos 8 MB por historia.
- `experiments/results.csv` guarda una fila por prueba, y los resúmenes van a `docs/evidencias/`.

## 7. Configuración y perfiles

| Perfil | LLM | Imagen | Sonido | Uso |
|---|---|---|---|---|
| `rapido` (por defecto) | Qwen3 4B, por etapas + auditor | LCM 6 pasos, IP-Adapter 0,4 | SA3 → AudioLDM → biblioteca → procedural | Demo; ~2 min por historia |
| `calidad` | Qwen3 4B | DPM++ 2M Karras 25 pasos | SA3 → SAO 1.0 → AudioLDM → … | Cuando el tiempo no importa |
| `experiments/c1_baseline`, `c2_bible`, `c3_ipadapter` | — | Estrategias C1, C2 y C3 | — | Batería de la tarea 6.2 |
| `experiments/llm_8b` | Qwen3 8B | — | — | Comparación de LLM (tarea 1.4) |

`config.py` valida cada YAML con Pydantic. `configs/default.yaml` tiene todos los valores, y cada perfil solo declara lo que cambia. El manifest guarda la configuración completa de cada ejecución, para que sea reproducible.

## 8. Decisiones de diseño

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| Pipeline secuencial con liberación de VRAM | Modelos residentes | Con 4 GB no caben a la vez el LLM, SD 1.5 con IP-Adapter y AudioLDM. |
| Story Bible como fuente de verdad | Prompts sueltos por modalidad | La coherencia entre texto, imagen y sonido sale de un mismo documento validado. |
| Generación por etapas (plan y luego escena por escena) | Una sola llamada | Ollama ordena las claves del JSON alfabéticamente: en una sola llamada, las escenas se generaban antes que los personajes. |
| Qwen3 4B en los dos perfiles | Qwen3 8B | Validez igual (9/10), pero el 8B es 13 veces más lento en 4 GB. |
| SD 1.5 (DreamShaper 8) + LCM | SDXL, FLUX | Exceden 4 GB; requerirían minutos por imagen. |
| Piper en CPU | XTTS-v2 | No compite por la VRAM; la licencia de XTTS restringe el uso y la clonación de voz no se necesita. |
| AudioLDM con respaldo procedural | Solo biblioteca | El enunciado valora el sonido generativo; el respaldo procedural garantiza que siempre haya ambiente. |
| Streamlit | Gradio | Estado de sesión y `st.status` para el progreso; la lógica queda separada en `ui_logica.py`. |
| Sin *safety checker* | Safety checker de SD | Ahorra ~600 MB de VRAM; se sustituye por prompts negativos, reglas por género y revisión humana. |

## 9. Calidad del software

- **Pruebas:** 431 pruebas con pytest. Corren sin GPU y sin red gracias a las dependencias inyectadas; cubren esquemas, prompts, pipeline completo simulado, sonido, mezcla, almacenamiento, UI, experimentos y verificación sin conexión.
- **Estilo:** ruff (lint y formato) con tipado estricto en las firmas.
- **Sin conexión:** `scripts/verify_offline.py` bloquea y registra cualquier conexión que no sea a `localhost` mientras corre el pipeline. La prueba real con el Wi-Fi apagado registró 0 intentos (tarea 5.4).
- **Trazabilidad:** cada ejecución deja su `manifest.json`. Cada prueba en Windows deja su evidencia en `docs/evidencias/` y una entrada en `docs/PROGRESO.md`.
