# Sustentación de StoryBook IA

Guía para la presentación, la demo en vivo y las preguntas del 23 de noviembre de 2026. Va de la mano con `StoryBook_IA_Sustentacion.pptx` (12 diapositivas). Diego presenta y defiende solo todo el proyecto.

## 1. La estrategia: que el portátil trabaje mientras hablas

Con el perfil Avanzada, una historia tarda ~11 min y la escena 1 sale a los ~3 min. La presentación dura ~10 min. Por eso:

1. Muestras la portada y pides al jurado una idea y un género.
2. Lanzas la generación en Avanzada y vuelves a las diapositivas.
3. Al terminar la diapositiva 12, la historia del jurado ya está lista o casi lista: la demo es abrirla.

Frase para pedirlo: *"Antes de empezar, ¿me dan una idea en una frase y un género? Mientras les presento, el portátil va a escribir, ilustrar y narrar ese cuento sin Internet."*

Si prefieren dar la idea al final, usa **Modelo grande (SDXL)**: ~6 min, con la escena 1 a los ~1,6 min. Mientras se genera, muestra "Las Puertas Olvidadas" en los tres perfiles desde **Historias guardadas**.

## 2. Antes de entrar (lista de verificación)

| Cuándo | Qué hacer | Por qué |
|---|---|---|
| 40 min antes | Portátil **conectado a la corriente**, modo de energía **Mejor rendimiento** y sin actualizaciones de Windows pendientes | Con batería, la GPU baja su potencia |
| 40 min antes | Cerrar todo lo que no se use: Chrome, editores y juegos. Dejar abiertos solo Ollama, la app y la presentación | FLUX ocupa hasta ~18 GB de los 24 GB de RAM; si falta RAM, Windows usa el disco y todo se pone lento |
| 35 min antes | **Apagar el Wi-Fi**, abrir `StoryBook.cmd` y generar una historia de calentamiento en Avanzada (~11 min) | Confirma que Avanzada funciona sin Internet y deja los modelos en la caché del disco |
| 15 min antes | Revisar que en **Historias guardadas** estén "Las Puertas Olvidadas" (los tres perfiles) y la del avión | Son el plan B y la evidencia de la comparación |
| 10 min antes | Dejar la app abierta con el perfil **Avanzada** marcado y la presentación en la diapositiva 1 | Para lanzar la generación con dos clics |
| A mano | `docs/presentacion/`, `docs/evidencias/f10_avanzada.md`, `docs/PROGRESO.md` y `docs/informe/informe.pdf` | Por si piden la evidencia |

## 3. Guion por diapositiva (~10 min)

| # | Tiempo | Qué decir |
|---|---|---|
| 1 · Portada | 0:00–0:40 | "StoryBook IA escribe, ilustra, narra y ambienta un cuento de cinco escenas a partir de una idea, todo en este portátil y sin Internet: el Wi-Fi está apagado." → pedir la idea y el género, lanzar la generación y volver. |
| 2 · Qué hace | 0:40–1:30 | "La entrada es una idea y un género; la salida, cinco escenas con texto, ilustración, narración y ambiente mezclados. Lo importante para el usuario: la escena 1 se lee mientras se generan las demás." |
| 3 · La restricción | 1:30–2:15 | "Todo el proyecto se explica por un número: 4 GB de VRAM. Ningún modelo grande cabe entero, así que se turnan: uno carga, trabaja y se libera antes del siguiente." |
| 4 · El flujo | 2:15–3:30 | "Primero el LLM hace el plan: título, estilo, personajes con un descriptor visual fijo y el canon. Luego, por cada escena: texto, ilustrador (el LLM dice quién se ve, cuántos, qué hace y dónde), imagen, voz, ambiente y mezcla. Todo sale de la Story Bible, un JSON validado; si el LLM devuelve algo inválido, se rechaza y se corrige. El manifest guarda modelos, seeds, tiempos y VRAM." |
| 5 · Tres perfiles | 3:30–4:20 | "El docente pidió un modelo de imagen más grande, y en clase vimos la combinación Avanzada. Por eso hay tres perfiles: el texto es el mismo y cambian la imagen y la voz. Avanzada usa FLUX.1-schnell y XTTS-v2, y es el perfil por defecto." |
| 6 · Misma historia | 4:20–5:30 | "Generé la misma idea con los tres perfiles y el LLM escribió la misma historia, así que solo cambia el modelo de imagen. Fíjense en Sara, la mujer de gris: debe aparecer en las escenas 2, 3 y 4. SD 1.5 y SDXL no la dibujan; FLUX, en las tres. La caja de madera solo está en las cinco con FLUX." |
| 7 · Lo que cuesta | 5:30–6:20 | "La mejora tiene precio. SD 1.5: 4 min 19 s; SDXL: 6 min; FLUX: 11 min 14 s. Con CLIP, los modelos grandes siguen mejor el texto, pero en FLUX la consistencia baja algo porque no tiene IP-Adapter. Por eso no hay un solo perfil." |
| 8 · FLUX en 4 GB | 6:20–7:20 | "FLUX tiene 12 mil millones de parámetros y no cabía ni en 16 bits. Convertí los pesos oficiales a fp8 y viven en la RAM; cada bloque sube a la GPU solo mientras calcula. El codificador T5 se carga solo para leer el prompt. Y antes de narrar libero la GPU: la voz bajó de ~70 a ~30 s por escena." |
| 9 · Consistencia | 7:20–8:00 | "Para que el personaje sea el mismo en las cinco escenas hay varias capas: descriptor fijo, seed fija, IP-Adapter en SD y SDXL, el ilustrador y un reparto fiel a la idea. Medido con CLIP: 0,50 sin Story Bible, 0,62 con ella y 0,77 con IP-Adapter, y se cumple en los cuatro géneros." |
| 10 · Problemas reales | 8:00–8:50 | "Las correcciones salieron de mirar historias reales: personajes que sobraban, un niño que salía como niña, una escena que salió como foto y una historia de casi 15 minutos que bajó a 11. Cada una tiene su prueba automática." |
| 11 · Ética y límites | 8:50–9:30 | "Nada sale del equipo y todo se marca como generado por IA. Las licencias de XTTS y AudioLDM son no comerciales: el proyecto es académico. La voz es una incluida en el modelo; no se clonó a nadie. Límites: Avanzada tarda 11 minutos, CLIP es una medida indirecta y FLUX a veces inventa letreros o firmas." |
| 12 · Cierre | 9:30–10:00 | "Tres perfiles, 431 pruebas automáticas y cero conexiones externas. Ahora veamos el cuento que pidieron." → cambiar a la app. |

## 4. Demo (3–4 min)

1. Abrir la historia del jurado (o la que esté en curso: la escena en curso tiene un reloj de arena).
2. **Escena 1:** reproducir 15–20 s de la narración (XTTS, voz "Ana Florence") con el ambiente debajo.
3. **Detalles técnicos** de esa escena: "Lo que debe verse" (lo que dijo el ilustrador), seed, tiempo de la imagen y "Lista a los…".
4. **Prompts usados:** el estilo va al principio y el descriptor del personaje, al final.
5. Pasar a otra escena con → y mostrar que el personaje se mantiene.
6. Si sobra tiempo: **Historias guardadas** → "Las Puertas Olvidadas" con SD 1.5 y con SDXL, para comparar en vivo.

Mientras esperas una escena, explica lo que está pasando: *"Ahora mismo FLUX sube a la GPU bloque por bloque; por eso tarda alrededor de un minuto por imagen."*

## 5. Plan B

| Falla | Señal | Qué hacer |
|---|---|---|
| Ollama no responde | "Ollama no responde en http://localhost:11434" | Abrir Ollama desde Inicio y volver a generar. Si no arranca, abrir una historia guardada. |
| La PC se pone lenta | La presentación o la página tardan en responder | Es la RAM llena (FLUX + XTTS + PowerPoint). La generación sigue: no cierres nada y abre la historia desde **Historias guardadas** cuando termine. |
| La página deja de actualizarse | El progreso no avanza durante minutos | La generación sigue en segundo plano y guarda escena por escena. Recarga con F5 y, cuando termine, ábrela desde **Historias guardadas**. |
| No alcanza el tiempo | La presentación termina y faltan escenas | Mostrar las escenas listas (se pueden leer) y decir cuánto falta. Mientras tanto, mostrar "Las Puertas Olvidadas". |
| Falta de memoria (CUDA OOM) | Ilustración de respaldo o aviso amarillo | "El pipeline registró el error y usó el respaldo: ninguna escena queda sin imagen ni sonido." Usar **Regenerar ilustración y ambiente**. |
| XTTS no arranca | La voz suena distinta (Piper) | Es el respaldo automático; queda registrado en el manifest. |
| La app no abre el navegador | La ventana negra está abierta pero no aparece la página | Abrir <http://localhost:8501> a mano. |
| El portátil falla por completo | — | Mostrar la presentación y las historias de `docs/presentacion/`. En cualquier PC, `uv run streamlit run app/streamlit_app.py -- --mock` abre la app en modo simulado. |

**Aviso amarillo en Rápido y Modelo grande** ("Stable Audio 3 Small-SFX no estaba disponible"): no es un error. Stable Audio 3 no está descargado y la cadena pasó sola a AudioLDM, que es la idea del diseño con respaldos.

## 6. Preguntas probables

### Arquitectura

1. **¿Por qué los modelos van uno tras otro y no en paralelo?** Con 4 GB no caben juntos: Qwen3 4B ocupa ~2,5 GB y FLUX usa los 4 GB enteros al calcular. Cada etapa carga su modelo, trabaja y lo libera. El LLM se descarga después de cada llamada y la imagen suelta la GPU antes de la voz.
2. **¿Qué es la Story Bible?** Un JSON validado con Pydantic: título, estilo visual, personajes con descriptor fijo, canon y las 5 escenas. El texto, la imagen y el sonido de cada escena salen de ella, así que cuentan lo mismo.
3. **¿Qué pasa si el LLM devuelve un JSON inválido?** El esquema lo rechaza y el error vuelve al modelo para que corrija (en el manifest se ve, por ejemplo, "prompt_imagen debe estar en inglés"). Si se agotan los intentos, la UI lo dice claro; nunca pasa una historia rota.
4. **¿Qué es el ilustrador?** Una segunda llamada al LLM por escena que devuelve un "plano visual": personaje principal, acompañantes con cantidad, acción, lugar y tipo de plano. El prompt de imagen se arma con eso, no con texto libre. Así se resolvió que sobraran o faltaran personajes.
5. **¿Cómo eligen entre 2 versiones?** En SD 1.5 y SDXL se generan 2 imágenes por escena. OpenCLIP compara cada una con la lista de "lo que debe verse" y penaliza lo que debe evitarse (por ejemplo, "dos niños" si solo hay uno). En FLUX se genera 1, porque sigue mejor el prompt y 2 duplicarían el tiempo.
6. **¿Cómo se muestra la escena 1 antes de terminar?** La generación es progresiva: se hace el plan y luego cada escena completa (texto → imagen → voz → ambiente → mezcla). Cada escena se guarda y se muestra apenas está lista. Corre en un hilo aparte y la UI consulta cada segundo.
7. **¿Por qué salió la misma historia con los tres perfiles?** Los tres usan el mismo LLM con la misma configuración y la misma seed, así que el plan es reproducible. Eso permitió aislar la variable: solo cambió el modelo de imagen.
8. **¿Cómo se prueba sin GPU?** Los modelos se inyectan como dependencias y `storybook.mock` los simula. Son 431 pruebas automáticas: esquemas, prompts, reparto, pipeline, sonido, mezcla, UI y verificación sin conexión.

### Modelos de imagen

9. **¿En qué se diferencian SD 1.5, SDXL y FLUX?**
   - **SD 1.5:** una UNet de ~0,9B con el codificador CLIP (77 tokens), a 768 × 512.
   - **SDXL:** una UNet de ~2,6B con dos codificadores CLIP, a ~1 megapíxel.
   - **FLUX.1:** un transformer de difusión de 12B entrenado con *rectified flow*, que lee el prompt con CLIP y con T5-XXL (hasta 256 tokens aquí). T5 entiende frases largas, por eso FLUX dibuja mejor "una niña con una caja junto a una mujer de gris".
10. **¿Qué es un modelo de difusión?** Aprende a quitar ruido paso a paso. Para generar, parte de ruido en el espacio latente y, guiado por el texto codificado, lo va limpiando. El VAE convierte el latente final en la imagen.
11. **¿Por qué FLUX.1-schnell y no FLUX.1-dev?** Schnell tiene licencia Apache 2.0 y está destilado para 1–4 pasos sin CFG. Dev es de uso no comercial y necesita ~30–50 pasos: en este equipo tardaría varios minutos por imagen.
12. **¿Qué es fp8 y no pierde calidad?** Son números de 8 bits (e4m3) en vez de 16, la mitad de memoria. Los pesos se guardan en fp8 y cada capa se calcula en bf16. En la prueba automática con un FLUX y un T5 pequeños, la diferencia frente a bf16 fue de ~5 % (el límite de la prueba es 10 %). Y la pertinencia de FLUX en fp8 superó a SDXL (0,315 frente a 0,298).
13. **¿Qué es group offloading?** El modelo vive en la RAM y cada bloque del transformer sube a la GPU justo antes de usarse y baja después. Con *streams* de CUDA, la copia del siguiente bloque se solapa con el cálculo del actual. Así un modelo de 12B corre en una GPU de 4 GB, a cambio de tiempo (~1 min por imagen).
14. **¿Qué es LCM?** Un adaptador (LoRA) que destila SD 1.5 para muestrear en 4–8 pasos en vez de 25–50. Con 6 pasos, la consistencia fue casi igual a 25 pasos (0,765 frente a 0,778) en la mitad del tiempo.
15. **¿Qué hace el IP-Adapter y por qué FLUX no lo usa?** Inyecta las características de una imagen de referencia (la *character sheet* del protagonista) en la atención cruzada, sin reentrenar. Con escala 0,4 mantiene la identidad sin volver todo retratos. Para FLUX no hay un IP-Adapter oficial y no uso pesos de terceros; ahí la consistencia viene del descriptor, que T5 sigue muy bien. Por eso la consistencia CLIP baja un poco (0,845 → 0,763) mientras la pertinencia sube (0,298 → 0,315).
16. **¿Por qué FLUX no usa negative prompt?** Schnell está destilado sin *classifier-free guidance* (guidance 0): el negative prompt no tiene efecto. Lo que no debe aparecer se controla con el plano visual.
17. **¿Por qué aparecen firmas o letreros en algunas imágenes de FLUX?** Aprendió de ilustraciones firmadas y dibuja texto con facilidad. Es una limitación conocida; está en la diapositiva de límites.

### Texto, voz y sonido

18. **¿Por qué Qwen3 4B y no uno más grande?** Lo medí: el 8B tuvo la misma validez (9/10), pero tardó 982 s frente a 75 s, porque el 61 % del modelo corría en CPU. El 4B cabe entero en la GPU (~43 tokens/s).
19. **¿Cómo funciona XTTS-v2 y por qué en otro entorno?** Es un modelo autorregresivo (tipo GPT) que genera tokens de audio, más un decodificador que los vuelve onda, condicionado por la voz de un hablante. Necesita `torchaudio`, que no existe para la versión de PyTorch de la app (2.15). Por eso corre en su propio entorno (torch 2.11) y la app le habla por stdin/stdout con JSON. Narra ~45 s de audio en ~30 s (RTF ~0,7). Si falla, la escena se narra con Piper.
20. **¿Clonaste alguna voz?** No: "Ana Florence" es una voz incluida en el modelo. XTTS puede clonar voces, pero no se usó.
21. **¿Por qué quitaste Stable Audio Open?** Tardaba ~38 s por escena para 8 s de ambiente bajo la voz, casi una cuarta parte de la historia. AudioLDM lo hace en ~2 s y, debajo de la narración, la diferencia casi no se oye. Sigue descargado y se puede reactivar en la configuración.
22. **¿Cómo funciona AudioLDM y su control de calidad?** Es difusión latente para audio, condicionada con CLAP. El sufijo ", high quality, clear" subió las escenas aptas de 13/20 a 20/20. Si un clip sale casi mudo (menos de −45 dBFS o más del 40 % en silencio), se reintenta con otra seed. Si sigue mal, pasa a la biblioteca CC0 y después a la síntesis procedural, que nunca falla.
23. **¿Cómo mezclas?** Normalización por sonoridad (LUFS, ITU-R BS.1770): voz a −18 LUFS, ambiente 12 dB por debajo y *ducking* de 6 dB mientras se habla. El ambiente se ajusta a la duración de la voz con bucle y fundido cruzado.

### Métricas y evaluación

24. **¿Cómo mediste la consistencia y la pertinencia?** Con CLIP. La consistencia (img-img) es la similitud coseno media entre los 10 pares de ilustraciones de una historia. La pertinencia (img-texto) compara cada imagen con su prompt.
25. **¿CLIP mide si es el mismo personaje?** No del todo: mide similitud global y premia composiciones repetidas. Por eso lo complemento con conteos concretos, como "Sara en 0, 0 y 3 de 3 escenas", y con las hojas de contactos.
26. **¿Cómo aislaste la variable?** Misma idea, mismo género y mismo texto, generado una vez o reproducido con la misma seed. Solo cambia el modelo o la estrategia de imagen.
27. **¿Qué limitaciones tiene la evaluación?** Pocas historias por configuración, un solo equipo, y CLIP como medida indirecta. Para el audio no medí correspondencia con el texto (haría falta CLAP).

### Ética y cierre

28. **¿Cómo demuestras que no usa Internet?** `verify_offline.py` bloquea y registra cualquier conexión que no sea a localhost: 0 intentos en 3 historias con el Wi-Fi apagado. Hoy la demo también corre con el Wi-Fi apagado. Hugging Face está en modo offline y la telemetría de Streamlit, desactivada.
29. **¿Qué controles de contenido hay?** Cada escena recibe la regla de su género (infantil sin violencia ni miedo intenso; terror sin gore), hay un negative prompt común en SD y SDXL, y todo se marca como generado por IA.
30. **¿Qué sesgos viste?** Los modelos tienden a rostros jóvenes e idealizados y a estereotipos de vestuario. Un caso real: con "un niño", el LLM describió "child" y FLUX lo dibujó con rasgos de niña. Por eso el reparto ahora exige "boy" o "girl" según la idea.
31. **¿Qué mejorarías con más tiempo o más GPU?**
    - Con 8 GB o más, FLUX cabría sin offloading y bajaría a segundos por imagen.
    - Una referencia de identidad para FLUX (un LoRA por personaje).
    - Stable Audio con una GPU que lo haga rápido.
    - CLAP para evaluar el audio y una evaluación con personas.

## 7. Datos para tener a mano

| Dato | Valor |
|---|---|
| Hardware | RTX 3050 Laptop de 4 GB, 24 GB de RAM, Windows 11, sin Internet |
| Texto | Qwen3 4B (Q4_K_M) en Ollama, ~43 tok/s; el 8B fue 13 veces más lento |
| Rápido (SD 1.5) | Escena 1 a los 92 s, historia en 4 min 19 s; ~10 s por imagen con 2 versiones |
| Modelo grande (SDXL) | Escena 1 a los 98 s, historia en 6 min 1 s; ~30 s por imagen con 2 versiones |
| Avanzada (FLUX + XTTS) | Escena 1 a los 191 s, historia en 11 min 14 s; FLUX 54–79 s por imagen, XTTS 27–34 s por escena |
| Sara en las escenas 2–4 | SD 1.5 0/3 · SDXL 0/3 · FLUX 3/3 |
| Pertinencia CLIP | SD 1.5 0,282 → SDXL 0,348; SDXL 0,298 → FLUX 0,315 |
| Consistencia CLIP | SD 1.5 0,734 → SDXL 0,658; SDXL 0,845 → FLUX 0,763 |
| Story Bible (CLIP img-img) | 0,50 sin Bible → 0,62 con Bible → 0,77 con IP-Adapter |
| FLUX en memoria | Pesos en fp8 en la RAM (copia de ~17 GB); pico del proceso ~18 GB; T5 solo al leer el prompt |
| Sonido | AudioLDM ~2 s por clip; sufijo de calidad: 13/20 → 20/20 |
| Mezcla | Voz −18 LUFS, ambiente −12 dB, *ducking* 6 dB |
| Pruebas | 431 automáticas, sin GPU ni red |
| Sin conexión | 0 conexiones externas |
