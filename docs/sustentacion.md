# Sustentación de StoryBook IA

Guía para la demo en vivo y la defensa técnica del 23 de noviembre de 2026. El docente define la idea y el género; Diego defiende solo todo el pipeline.

## 1. Antes de entrar (lista de verificación)

| Cuándo | Qué hacer | Por qué |
|---|---|---|
| El día anterior | Ejecutar `uv run pytest` y generar una historia completa con `StoryBook.cmd` | Confirma que nada cambió en el entorno |
| El día anterior | Revisar que `samples/` tenga las 3 historias y que se abran desde **Historias guardadas** | Es el plan B |
| 30 min antes | Portátil **conectado a la corriente**, modo de energía **Mejor rendimiento**, sin actualizaciones de Windows pendientes | La GPU baja su potencia con batería |
| 30 min antes | Cerrar juegos, editores de video y navegadores con aceleración por GPU que no se usen | Con 4 GB, otra app en la GPU puede provocar falta de memoria |
| 15 min antes | Abrir `StoryBook.cmd` y **generar una historia de calentamiento** | La primera generación del día tarda más (182 s frente a ~128 s), porque los pesos se cargan en frío desde el disco |
| 15 min antes | Apagar el **Wi-Fi** | Demuestra en vivo que todo es local |
| A mano | `docs/informe/informe.pdf`, `docs/arquitectura.md` (diagramas), `docs/informe/graficas/` y `docs/evidencias/f6_hojas/` | Para mostrar la evidencia cuando pregunten |

## 2. Guion de la demo (~10 minutos)

| Tiempo | Qué se muestra | Qué se dice (idea central) |
|---|---|---|
| 0:00–0:45 | Pantalla de inicio de la app | "StoryBook genera un cuento de 5 escenas con texto, ilustración, narración y ambiente sonoro, todo en este portátil con una GPU de 4 GB y sin Internet. El Wi-Fi está apagado." |
| 0:45–2:00 | Diagrama de flujo de datos (`docs/informe/diagramas/flujo_datos.png`) | "La pieza central es la Story Bible: un JSON validado que produce el LLM. De ella salen el texto, los prompts de imagen y los de sonido. Como no caben todos los modelos en 4 GB, cargo uno por etapa y lo libero antes del siguiente." |
| 2:00–4:30 | Escribir la idea y el género del docente, perfil **Rápido**, **Generar historia**. Mientras corre, señalar las etapas del progreso. | Texto (Qwen3 4B, ~75 s): plan, 5 escenas y auditor, con validación y reparación. Imágenes (SD 1.5 + LCM + IP-Adapter, ~27 s): primero la *character sheet* del protagonista. Voz (Piper, CPU). Sonido (AudioLDM, ~1,3 s por clip) y mezcla. |
| 4:30–6:30 | Recorrer las 5 escenas con **Siguiente**. Reproducir la narración, el ambiente y la mezcla de 1–2 escenas. | "El indicador n/5 muestra la fase narrativa. El ambiente va 12 dB bajo la voz y baja 6 dB más mientras se habla (*ducking*)." |
| 6:30–7:30 | **Detalles técnicos** de una escena | "Cada historia guarda un `manifest.json` con modelos, seeds, tiempos, VRAM y las alternativas usadas. Aquí se ve que Stable Audio no está disponible, así que el sistema pasó solo a AudioLDM." |
| 7:30–8:45 | Hojas de contactos C1 frente a C3 (`f6_hojas/…una_casa_c1_baseline.jpg` y `…c3_ipadapter.jpg`) y gráfica `consistencia.png` | "Medí la consistencia con CLIP: sin Bible 0,50, con Bible 0,62 y con Bible + IP-Adapter 0,77, en las 4 historias. El costo: unos 10 s más y escenas más tipo retrato." |
| 8:45–9:30 | **Respaldo en vivo:** cerrar la app y abrir `StoryBook.cmd respaldo`. Regenerar una escena o generar una historia corta. Mostrar el aviso amarillo y *Detalles técnicos*. | "Desactivo el sonido generativo: la cadena pasa sola a la síntesis procedural y la escena igual tiene ambiente. Ninguna escena queda sin sonido ni imagen." |
| 9:30–10:00 | Cierre | Unos 2 minutos por historia, 316 pruebas automatizadas y 0 conexiones fuera del equipo. Limitaciones: retratos con IP-Adapter y un solo personaje con referencia visual. |

**Atajo si el tiempo aprieta:** omitir el respaldo en vivo y mostrar *Detalles técnicos* de un ejemplo con `sonido:sa3:no_disponible`. También es una alternativa real.

## 3. Plan B (qué hacer si algo falla)

| Falla | Señal | Respuesta inmediata |
|---|---|---|
| Ollama no responde | Mensaje "Ollama no responde en http://localhost:11434" | Abrir Ollama desde el menú Inicio y volver a generar. Si no arranca, pasar a las historias de ejemplo. |
| La generación tarda demasiado | Más de 4 minutos | Explicar la etapa en curso con el diagrama de secuencia. Si no termina, abrir una historia de `samples/`. |
| Falta de memoria (CUDA OOM) | Error en la etapa de imágenes o ilustraciones de respaldo | Explicar que el pipeline registró el error y usó el respaldo. Cerrar otras apps de la GPU y usar **Regenerar ilustración y ambiente**. |
| La app no abre el navegador | La ventana negra está abierta pero no aparece la página | Abrir <http://localhost:8501> a mano. |
| El LLM no logra una Story Bible válida (≈1 de 10 en la tarea 1.4) | Mensaje "No se pudo completar" | "El validador rechazó la salida tras los reintentos y no dejó pasar una historia rota." Volver a generar: cada intento usa otra seed. |
| El portátil falla por completo | — | Mostrar el video demo y el informe. En cualquier PC, `uv run streamlit run app/streamlit_app.py -- --mock` abre las historias de ejemplo sin GPU. |

## 4. Respuestas centrales de la defensa

**Cómo viaja la información:**
- Idea y género → validación (`StoryRequest`).
- El LLM produce el plan (personajes con descriptor visual fijo, estilo, escenario, canon).
- Luego produce las 5 escenas, cada una viendo el canon y los resúmenes previos, y el auditor corrige contradicciones. El resultado es la Story Bible (`story.json`).
- De cada escena de la Bible salen:
  - el texto, que va a Piper;
  - estilo + descriptores + `prompt_imagen`, que van a SD 1.5;
  - `prompt_sonido`, que va a AudioLDM.
- La voz y el ambiente se mezclan, y todo queda en `outputs/<run_id>/` con su manifest.

**Por qué cada modelo, dada la restricción de 4 GB:**
- **Qwen3 4B** cabe completo en la GPU (43 tok/s). El 8B tenía la misma validez pero tardaba 13 veces más, con el 61 % del modelo en CPU.
- **SD 1.5** cabe en ~3,2 GB; SDXL y FLUX no caben. **LCM** baja a 6 pasos.
- **Piper** corre en CPU, así que no compite por la VRAM.
- **AudioLDM** cabe en ~0,9 GB y no exige aceptar licencias.

**Qué mide cada métrica:**
- **CLIP img-img:** similitud media entre las 5 ilustraciones (consistencia).
- **CLIP img-texto:** cuánto se parece cada imagen a su prompt (pertinencia).
- **WER:** palabras que Whisper transcribe mal sobre la narración (inteligibilidad).
- **LUFS:** sonoridad percibida, para fijar la voz en −18 y el ambiente 12 dB por debajo.

**Qué mostraron los experimentos:**
- Consistencia: C3 > C2 > C1 en las 4 historias (0,77, 0,62 y 0,50). Con 25 pasos, la mejora es mínima por el doble de tiempo.
- El 8B no compensa.
- El sufijo de calidad llevó AudioLDM de 13/20 a 20/20 escenas aptas.

**Cómo se preservan los personajes:**
1. El descriptor visual fijo se repite en cada prompt.
2. La seed es fija y compartida.
3. IP-Adapter usa la *character sheet* como referencia de identidad.
4. La acción va antes del estilo en el prompt.
5. El límite de 77 tokens evita que se corte el descriptor.

En el texto, el canon y el auditor.

## 5. Preguntas probables del jurado (30)

### Arquitectura y diseño

1. **¿Por qué un pipeline secuencial y no paralelo?** Con 4 GB no caben a la vez el LLM (~2,5 GB), SD 1.5 con IP-Adapter (~3,2 GB) y AudioLDM (~0,9 GB). Cargo uno por etapa y lo libero; la memoria al cargar las imágenes vuelve a ~200 MB, medido.
2. **¿Qué es la Story Bible y por qué es la "fuente de verdad"?** Es un JSON validado con Pydantic con título, estilo visual, personajes con descriptor fijo, canon y las 5 escenas. Todas las modalidades leen de ella, así que el texto, la imagen y el sonido de una escena cuentan lo mismo.
3. **¿Qué pasa si el LLM devuelve un JSON inválido?** El esquema lo rechaza y el error de validación vuelve al modelo para que repare. Si la reparación falla, se intenta de cero con otra seed. Si se agotan los intentos, la UI muestra un mensaje claro. Nunca pasa una historia rota.
4. **¿Por qué generar por etapas y no en una sola llamada?** Ollama ordena alfabéticamente las claves del JSON: en una sola llamada, las escenas salían antes que los personajes. Por etapas, el plan fija los personajes primero y cada escena ve el canon acumulado.
5. **¿Cómo sabe la app qué alternativa usó?** Cada etapa registra sus *fallbacks* en `manifest.json` (por ejemplo, `sonido:sa3:no_disponible`), y la UI los muestra en *Detalles técnicos*.
6. **¿Por qué Streamlit y no Gradio?** Streamlit da estado de sesión y progreso por etapa (`st.status`) con poco código. Además, toda la lógica está fuera de la UI (`ui_logica.py`) y tiene pruebas.
7. **¿Cómo se prueba sin GPU?** Las dependencias pesadas se inyectan y `storybook.mock` las simula. Son 316 pruebas, que cubren esquemas, prompts, pipeline completo, sonido, mezcla, UI y verificación sin conexión.

### Modelos

8. **¿Por qué Qwen3 4B y no un modelo más grande?** Lo medí: el 8B tuvo la misma validez (9/10) pero tardó 982 s frente a 75 s, porque el 61 % del modelo corría en CPU.
9. **¿Por qué SD 1.5 y no SDXL o FLUX?** SDXL y FLUX no caben en 4 GB; con offload tardan minutos por imagen. SD 1.5 en fp16 con LCM genera una imagen de 768 × 512 en 3,4 s.
10. **¿Qué es LCM-LoRA?** Un adaptador que destila el modelo para muestrear en 4–8 pasos en vez de 25–50. Comparé 6 pasos (LCM) contra 25 (DPM++): consistencia casi igual (0,765 frente a 0,778) en la mitad del tiempo.
11. **¿Qué hace el IP-Adapter?** Inyecta las características de una imagen de referencia (la *character sheet*) en la atención cruzada del modelo, sin reentrenarlo. Con escala 0,4 mantiene la identidad sin convertir todo en retratos; con 0,6 sí pasaba.
12. **¿Por qué Piper y no XTTS?** Piper corre en CPU en tiempo real y no compite por la VRAM. XTTS compite por la GPU, su licencia restringe el uso y su clonación de voz no se necesita.
13. **¿Por qué AudioLDM si Stable Audio es mejor?** Stable Audio exige aceptar su licencia con una cuenta, y en este equipo no está. Queda primero en la cadena: si se descarga, se usa. AudioLDM no exige token y cabe en ~0,9 GB.
14. **¿Qué pasa si AudioLDM falla?** Un control rechaza los clips casi mudos (menos de −45 dBFS o más del 40 % en silencio). Se reintenta con otra seed y después pasa a la biblioteca CC0 y a la síntesis procedural, que nunca falla.

### Consistencia y métricas

15. **¿Cómo mediste la consistencia visual?** Con CLIP img-img: la similitud coseno media entre los 10 pares de ilustraciones de cada historia, más el par menos parecido.
16. **¿CLIP mide realmente si es el mismo personaje?** No del todo: mide similitud global y premia composiciones repetidas. Por eso lo complemento con las hojas de contactos y con CLIP img-texto. En C3, parte de la similitud viene de que las escenas son retratos parecidos, y lo reporto como limitación.
17. **¿Qué diferencia hay entre C1, C2 y C3?** C1: sin Bible y con seeds aleatorias. C2: Bible y seed fija. C3: C2 más IP-Adapter. Resultados: 0,50, 0,62 y 0,77; el orden se cumple en las 4 historias.
18. **¿Cómo aislaste la variable en los experimentos?** Para cada idea generé el texto una sola vez (con C3) y regeneré solo las imágenes con cada configuración. Así el texto es idéntico y solo cambia la estrategia de imagen.
19. **¿Qué es el WER y qué valores obtuviste?** La proporción de palabras que Whisper transcribe mal respecto al texto original: de 3,5 a 4,8 % en la batería. Los errores están sobre todo en nombres inventados.
20. **¿Qué limitaciones tiene tu evaluación?** Son 4 historias por configuración, con una seed y un equipo. CLIP es una medida indirecta, y el control de sonido mide nivel, no correspondencia con el prompt (para eso haría falta CLAP). La revisión humana 1–5 complementa los números.

### Sonido y voz

21. **¿Cómo mezclas la voz y el ambiente?** Normalizo con LUFS (ITU-R BS.1770): voz a −18 LUFS y ambiente 12 dB por debajo, con *ducking* de 6 dB mientras se habla. El ambiente se ajusta a la duración de la voz con bucle y fundido cruzado.
22. **¿Cómo descubriste el sufijo ", high quality, clear"?** AudioLDM dejaba 8 de 20 escenas casi mudas, sobre todo con fuentes tenues ("wind rustling through trees"). Probé 4 variantes con los 20 prompts y 2 seeds: el sufijo dio 20/20 y subir el guidance empeoró (12/20).
23. **¿La síntesis procedural es "IA"?** No es un modelo entrenado; es generación de señal propia (numpy/scipy) para 21 etiquetas. Es el respaldo que garantiza que siempre haya sonido, y no tiene problemas de licencia.

### Ejecución local, reproducibilidad y ética

24. **¿Cómo demuestras que no usa Internet?** `verify_offline.py` bloquea y registra cualquier conexión que no sea a localhost mientras corre el pipeline. Con el Wi-Fi apagado generé 3 historias y registró 0 intentos. Además, HF está en modo offline y la telemetría de Streamlit está desactivada.
25. **¿Cómo se reproduce una historia?** Las seeds quedan en `story.json` y el manifest guarda la configuración completa y las versiones. Los commits de los modelos están en `docs/models_registry.json`.
26. **¿Cuánto tarda y cuánta memoria usa?** Unos 2 minutos por historia (124–129 s): el texto el 60 % y las imágenes ~21 %. Pico de memoria: 3,16 GB asignados en la etapa de imágenes.
27. **¿Qué controles de contenido tienes?** Cada escena recibe la regla de su género (infantil sin violencia ni miedo intenso; terror sin gore), y todas las imágenes llevan un negative prompt común (nsfw, gore). Todo se etiqueta como generado por IA.
28. **¿Qué sesgos observaste?** Los modelos de imagen tienden a representar protagonistas jóvenes de rostro idealizado y estereotipos de vestuario según el rol. El descriptor fijo del personaje permite controlarlo en parte.
29. **¿Hay problemas de licencias?** AudioLDM es CC BY-NC-SA, así que el proyecto es académico y no comercial. Las demás licencias (Apache 2.0, OpenRAIL, GPL para el código de Piper) están en `MODELS.md`. No hay clonación de voz.

### Cierre

30. **¿Qué mejorarías con más tiempo?** Escala de IP-Adapter por escena para tener más acción, una referencia visual por personaje, CLAP para medir la correspondencia audio-texto, y evaluar Stable Audio 3 con licencia aceptada.

## 6. Datos para tener a mano

| Dato | Valor |
|---|---|
| Hardware | RTX 3050 Laptop de 4 GB (75 W), 24 GB de RAM, Windows 11 |
| Tiempo por historia (rápido) | 124–129 s (mediana 128 s); la primera en frío, 182 s |
| Texto | Qwen3 4B, 75 s, 43 tok/s, 9/10 válidas |
| Imagen | SD 1.5 + LCM 6 pasos, 3,4 s por imagen, ~27 s por historia, 3,16 GB |
| Consistencia (CLIP img-img) | C1 0,50 · C2 0,62 · C3 0,77 · 25 pasos 0,78 |
| Pertinencia (CLIP img-texto) | C1 0,343 · C2 0,335 · C3 0,319 · 25 pasos 0,347 |
| Voz | Piper `es_MX-claude-high`, CPU, RTF 0,03, WER 3,5–4,8 % |
| Sonido | AudioLDM, ~1,3 s por clip, 0,94 GB; sufijo de calidad 13/20 → 20/20 |
| Mezcla | Voz −18 LUFS, ambiente −12 dB, *ducking* 6 dB |
| Sin conexión | 0 conexiones externas (3 historias con el Wi-Fi apagado) |
| Pruebas | 316+ automatizadas, sin GPU ni red |
