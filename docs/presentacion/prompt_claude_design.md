Crea una presentación de 12 diapositivas (16:9, en español) para la sustentación final de mi proyecto integrador de la materia Inteligencia Artificial Generativa. La presento yo solo ante el docente y el jurado, en unos 10 minutos, y después hago una demo en vivo de la aplicación. Te adjunto 9 imágenes; más abajo digo cuál va en cada diapositiva.

## El proyecto en una frase

StoryBook IA convierte una idea y un género en un cuento de 5 escenas, cada una con texto, ilustración, narración en voz y ambiente sonoro mezclado. Todo se genera en mi portátil, sin Internet, con una GPU de 4 GB.

## Dirección visual

- La presentación debe sentirse hermana de la aplicación, que tiene forma de libro abierto (ver `01_app_libro_avanzada.jpg`). Usa su misma identidad:
  - Fondo "tela" verde azulado oscuro `#1F3D3E` (variante más clara `#2A5254`).
  - Paneles de "papel" marfil `#FAF6EC` con borde `#E4DAC2`, como páginas de un libro.
  - Tinta `#2B2520` y tinta suave `#6E6458` sobre el papel.
  - Dorado `#D2AE5B` para títulos sobre la tela y `#8A6A22` para acentos sobre el papel.
  - Texto claro `#ECE7DA` y `#A9BAB4` sobre la tela.
- Tipografías (Google Fonts, las mismas de la app): **Literata** para títulos y cifras grandes, **Atkinson Hyperlegible** para el texto.
- Las ilustraciones generadas son las protagonistas: dales espacio y no las recortes de forma que se pierdan caras o personajes. No agregues imágenes de stock, íconos decorativos, degradados ni sombras genéricas.
- Poco texto por diapositiva: frases cortas, sin párrafos. Los títulos en tipo oración, sin MAYÚSCULAS sostenidas ni etiquetas pequeñas sobre cada título.
- Usa numeración solo donde el contenido es una secuencia (el flujo de la diapositiva 4).
- En cada diapositiva con ilustraciones, un pie pequeño: "Ilustraciones generadas por StoryBook IA en el portátil".
- No inventes cifras: usa solo los números de este texto, con coma decimal.
- Agrega notas del orador en cada diapositiva con lo que digo (2 o 3 frases); las incluyo abajo.

## Diapositivas

### 1. Portada
- Título: **StoryBook IA**
- Subtítulo: "Cuentos ilustrados, narrados y ambientados, generados en un portátil sin Internet"
- Diego Alejandro Urbano Pira · Inteligencia Artificial Generativa (ISS9B) · Universidad Santo Tomás, Tunja · 23 de noviembre de 2026
- Imagen: `00_portada_puertas_olvidadas.jpg` grande, como una página ilustrada del libro.
- Notas: "StoryBook escribe, ilustra, narra y ambienta un cuento de cinco escenas a partir de una idea. Todo corre en este portátil, sin servicios en la nube."

### 2. Qué hace
- Entrada: una idea en una frase y un género (fantasía, terror, ciencia ficción, infantil…).
- Salida: 5 escenas (inicio, desarrollo, conflicto, clímax y cierre), cada una con texto, ilustración, narración, ambiente y la mezcla de voz y ambiente.
- La escena 1 se puede leer mientras se generan las siguientes.
- Imagen: `01_app_libro_avanzada.jpg` (la aplicación con "Las Puertas Olvidadas" abierta en la escena 3).
- Notas: "Así se ve la aplicación: a la izquierda la ilustración, a la derecha el texto, abajo el reproductor con la narración y el ambiente, y a la derecha los detalles técnicos de cada escena."

### 3. La restricción que define todo
- Una cifra grande: **4 GB de VRAM** (NVIDIA RTX 3050 Laptop), con 24 GB de RAM y Windows 11.
- Sin Internet: la verificación registró 0 conexiones fuera del equipo.
- Ningún modelo grande cabe entero en la GPU: los modelos se turnan. Se carga uno, trabaja y se libera antes del siguiente.
- Notas: "Esta restricción explica cada decisión del proyecto: qué modelos usé, en qué orden corren y cómo comparten la memoria."

### 4. Cómo se genera una historia
Diagrama de flujo, de izquierda a derecha, con estos pasos numerados:
1. **Plan** (Qwen3 4B): título, estilo visual, personajes con un descriptor visual fijo y el canon de la historia.
2. Por cada escena:
   - **Texto** (Qwen3 4B), que ve el canon y las escenas anteriores.
   - **Ilustrador** (Qwen3 4B): describe qué se ve (quién, cuántos, qué hace, dónde).
   - **Imagen**.
   - **Voz**.
   - **Ambiente**.
   - **Mezcla**: voz a −18 LUFS, ambiente 12 dB por debajo.
3. **Escena lista**: se muestra y se pasa a la siguiente.

- Destaca dos piezas:
  - La **Story Bible**, un JSON validado que es la única fuente de verdad: el texto, la imagen y el sonido de cada escena salen de ella.
  - El **manifest.json**, que guarda modelos, seeds, tiempos, VRAM y cualquier alternativa usada.
- Notas: "El modelo de lenguaje no solo escribe: también decide qué debe verse en cada imagen. Si una salida no cumple el esquema, se rechaza y se corrige; nunca pasa una historia rota."

### 5. Tres perfiles de modelos
Tabla con 3 columnas (Rápido, Modelo grande, Avanzada) y estas filas:

| | Rápido | Modelo grande | Avanzada |
|---|---|---|---|
| Texto | Qwen3 4B | Qwen3 4B | Qwen3 4B |
| Imagen | SD 1.5 (DreamShaper 8 + LCM, 6 pasos) | SDXL (DreamShaper XL Lightning, 6 pasos) | FLUX.1-schnell (12B, 4 pasos) |
| Versiones por imagen | 2, elige CLIP | 2, elige CLIP | 1 |
| Voz | Piper (CPU) | Piper (CPU) | XTTS-v2, voz "Ana Florence" (GPU) |
| Ambiente | AudioLDM | AudioLDM | AudioLDM |
| Historia completa | 4 min 19 s | 6 min 1 s | 11 min 14 s |

- Nota al pie: "El docente pidió un modelo de imagen más grande (12 nov) y la combinación «Avanzada» del resumen de modelos de la clase (18 nov)."
- Notas: "Los tres perfiles usan el mismo modelo de texto; cambian la imagen y la voz. Avanzada es el perfil por defecto de la aplicación."

### 6. La misma historia con cada modelo
- Imagen principal: `02_misma_historia_tres_modelos.jpg` (tres filas: SD 1.5, SDXL y FLUX.1, con las mismas 5 escenas de "Las Puertas Olvidadas").
- Una línea: "Misma idea, mismo género y mismo texto: solo cambia el modelo de imagen."
- Idea usada: "Una chica en un edificio está en un pasillo con demasiadas puertas" (fantasía). Personajes: Luna (niña de vestido azul, con una caja de madera) y Sara (mujer de abrigo gris), que debe aparecer en las escenas 2, 3 y 4.
- Tres observaciones cortas junto a la imagen:
  - Sara aparece en las escenas 2 a 4: SD 1.5 0 de 3, SDXL 0 de 3, FLUX 3 de 3.
  - La caja de madera aparece en las 5 escenas solo con FLUX.
  - SD 1.5 se acerca a una foto; SDXL y FLUX respetan la acuarela.
- Notas: "Generé la misma idea con los tres perfiles y el modelo de texto escribió la misma historia, así que la diferencia es solo del modelo de imagen. Fíjense en Sara: solo FLUX la dibuja en las tres escenas donde aparece."

### 7. Lo que cuesta cada modelo
Gráfica de barras horizontales: tiempo hasta la historia completa, con una marca para el momento en que la escena 1 ya se puede leer.

| Perfil | Escena 1 lista | Historia completa | Imagen por escena | Voz por escena |
|---|---|---|---|---|
| Rápido (SD 1.5) | 92 s | 259 s (4 min 19 s) | ~10 s (2 versiones) | 1–3 s |
| Modelo grande (SDXL) | 98 s | 361 s (6 min 1 s) | ~30 s (2 versiones) | 1–2 s |
| Avanzada (FLUX) | 191 s | 674 s (11 min 14 s) | 54–79 s (1 versión) | 27–34 s |

- Debajo, calidad medida con CLIP en dos comparaciones previas (en cada una, la misma historia con dos modelos):
  - Pertinencia (imagen frente a su texto): SD 1.5 0,282 → SDXL 0,348; SDXL 0,298 → FLUX 0,315.
  - Consistencia entre las 5 imágenes: SD 1.5 0,734 → SDXL 0,658; SDXL 0,845 → FLUX 0,763.
- Mensaje: "Los modelos más grandes siguen mejor el texto, pero cuestan más tiempo, y en FLUX baja algo la consistencia entre escenas porque no hay IP-Adapter."
- Notas: "No vendo solo la mejora: el modelo grande dibuja lo que dice el texto, pero cuesta más tiempo. Por eso hay tres perfiles."

### 8. Cómo entra FLUX (12B) en 4 GB
Cuatro ideas, cada una con una frase:
- **Copia local en fp8**: convertí los pesos oficiales a 8 bits; el modelo vive en la RAM.
- **Bloque a bloque**: cada bloque del transformer sube a la GPU solo mientras calcula (group offloading).
- **T5 solo para leer el prompt**: el codificador de texto se carga por imagen y se suelta antes de dibujar (unos 5 GB menos de RAM).
- **Memoria libre antes de la voz**: XTTS corre en otro proceso y necesita la GPU libre; liberarla bajó la voz de 66–76 s a ~30 s por escena.
- Imagen: `07_flux_ciencia_ficcion_avion.jpg` (tira de 5 escenas de otra historia, ciencia ficción).
- Notas: "FLUX no cabía ni en fp16. Con pesos en fp8 en la RAM y bloques que suben uno a uno, genera una imagen de 1056 × 704 en menos de un minuto y medio."

### 9. Personajes consistentes
- Las capas que mantienen al mismo personaje en las 5 escenas:
  - Story Bible con descriptor visual fijo.
  - Seed fija.
  - IP-Adapter en SD 1.5 y SDXL.
  - El ilustrador que dice quién se ve.
  - Un reparto fiel a la idea.
- Imagen: `08_grafica_consistencia_story_bible.png`.
- Cifra destacada: consistencia CLIP 0,50 sin Story Bible → 0,62 con Story Bible → 0,77 con Story Bible e IP-Adapter (promedio de 4 historias).
- Notas: "Medí la consistencia con CLIP en cuatro géneros. La mejora se cumple en las cuatro historias, no solo en el promedio."

### 10. Problemas reales y cómo los resolví
Cuatro filas problema → solución:
- **Sobraban o faltaban personajes** → el ilustrador describe quién aparece y, en SD 1.5 y SDXL, CLIP elige la mejor de 2 versiones.
- **Pedí "un niño" y parecía una niña** → si la idea dice niño, el personaje debe ser "boy"; si dice niña, "girl".
- **Una escena salió como foto y no como acuarela** → en FLUX, el estilo va al principio del prompt.
- **Avanzada tardaba 14 min 54 s** → sin Stable Audio y con la GPU libre antes de la voz: **11 min 14 s**.
- Imagen: `06_correccion_nino_antes_despues.jpg` (antes y después de la misma historia).
- Notas: "Cada corrección salió de mirar las historias generadas, no de suponer. Todas tienen una prueba automática."

### 11. Ética, licencias y límites
- Todo es local: ninguna idea ni historia sale del equipo, y todo se marca como contenido generado por IA.
- Licencias:
  - Qwen3 4B y FLUX.1-schnell: Apache 2.0.
  - XTTS-v2: CPML, solo uso no comercial; uso una voz incluida, sin clonar a nadie.
  - AudioLDM: CC BY-NC-SA.
  - SD 1.5 y SDXL: OpenRAIL.
- Reglas de contenido por género (infantil sin violencia; terror sin gore) y un negative prompt común.
- Límites:
  - Avanzada tarda unos 11 minutos.
  - CLIP es una medida indirecta.
  - FLUX a veces inventa letreros o firmas en la imagen.
- Notas: "El proyecto es académico y no comercial, como exigen las licencias de XTTS y AudioLDM."

### 12. Cierre y demo
- Tres cifras grandes:
  - **3 perfiles**: de 4 a 11 minutos por historia.
  - **431 pruebas automáticas**: corren sin GPU ni red.
  - **0 conexiones externas**.
- Frase final: "Un cuento completo, escrito, ilustrado y narrado por IA, en un portátil de 4 GB y sin Internet."
- Pie: "Demo en vivo · Preguntas".
- Imagen pequeña: `03_sd15_las_puertas_olvidadas.jpg`, `04_sdxl_las_puertas_olvidadas.jpg` o `05_flux_las_puertas_olvidadas.jpg` (una tira).
- Notas: "Ahora lo muestro en vivo: el jurado elige la idea y el género."
