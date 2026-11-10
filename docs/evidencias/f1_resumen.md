# F1 · Generaciones reales de la Story Bible (2026-11-10 09:06)

- Perfil `rapido` · modelo `qwen3:4b-instruct-2507-q4_K_M` · estrategia `por_etapas` · auditor sí · num_ctx 4096 · num_gpu 99
- **Story Bibles válidas: 9/10**
- Tiempo por historia (mediana): 75.34 s · tokens/s (mediana): 42.92
- Intentos por llamada (mediana): 1.07 · fracción del modelo en GPU (mediana): 1.00

| # | Género | Válida | Llamadas | Intentos | s total | tok/s | GPU | Contrad. | Título |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | misterio | sí | 7 | 8 | 76.13 | 39.13 | 1.0 | 0 | El Faro de las Noches |
| 2 | fantasia | sí | 7 | 7 | 67.36 | 43.81 | 1.0 | 0 | La Sombra Que Habla |
| 3 | ciencia_ficcion | sí | 7 | 9 | 92.2 | 35.01 | 1.0 | 0 | Huerta de Códigos |
| 4 | terror | sí | 7 | 8 | 83.65 | 38.23 | 1.0 | 0 | El Sueño Que Cambia |
| 5 | infantil | sí | 7 | 7 | 69.54 | 42.92 | 1.0 | 0 | El Camino de Luna y Milo |
| 6 | aventura | sí | 7 | 7 | 71.87 | 43.68 | 1.0 | 0 | El Tesoro del Árbol Silencioso |
| 7 | misterio | sí | 7 | 7 | 73.73 | 43.67 | 1.0 | 0 | El Minuto Olvidado |
| 8 | fantasia | sí | 7 | 7 | 74.55 | 43.61 | 1.0 | 0 | El Último Dragón de los Libros |
| 9 | ciencia_ficcion | NO | 1 | 4 | 85.97 | 0.0 | 1.0 |  | LLMValidationError: PlanHistoria: salida inválida tras 4 int |
| 10 | terror | sí | 7 | 8 | 82.1 | 35.54 | 1.0 | 0 | La Muñeca del Amanecer |

Causas de reintento (errores de validación devueltos al modelo):

| Campo · causa | Veces |
|---|---:|
| plan_escenas.resumen · idioma | 15 |
| personajes.descripcion_visual_fija · idioma | 5 |
| prompt_imagen · idioma | 4 |
| prompt_sonido · idioma | 2 |
