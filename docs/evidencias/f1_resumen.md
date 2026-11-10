# F1 · Generaciones reales de la Story Bible (2026-11-10 08:15)

- Perfil `rapido` · modelo `qwen3:4b-instruct-2507-q4_K_M` · estrategia `por_etapas` · auditor sí · num_ctx 4096 · num_gpu 99
- **Story Bibles válidas: 6/10**
- Tiempo por historia (mediana): 84.50 s · tokens/s (mediana): 33.22
- Intentos por llamada (mediana): 1.21 · fracción del modelo en GPU (mediana): 1.00

| # | Género | Válida | Llamadas | Intentos | s total | tok/s | GPU | Contrad. | Título |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | misterio | sí | 7 | 8 | 82.81 | 34.54 | 1.0 | 0 | El Faro que Llama a los Perdidos |
| 2 | fantasia | sí | 7 | 8 | 83.1 | 34.23 | 1.0 | 0 | La Sombra que Habla |
| 3 | ciencia_ficcion | NO | 0 | 0 | 65.72 | 0.0 | 1.0 |  | LLMValidationError: PlanHistoria: salida inválida tras 4 int |
| 4 | terror | NO | 0 | 0 | 63.8 | 0.0 | 1.0 |  | LLMValidationError: PlanHistoria: salida inválida tras 4 int |
| 5 | infantil | sí | 7 | 9 | 105.86 | 29.5 | 1.0 | 0 | El Camino del Sol |
| 6 | aventura | sí | 7 | 8 | 87.08 | 34.84 | 1.0 | 0 | El Tesoro del Abuelo Leo |
| 7 | misterio | sí | 7 | 12 | 154.63 | 20.98 | 1.0 | 0 | El Minuto que Se Detiene |
| 8 | fantasia | NO | 0 | 0 | 85.9 | 0.0 | 1.0 |  | LLMValidationError: Escena: salida inválida tras 4 intentos |
| 9 | ciencia_ficcion | sí | 7 | 9 | 93.11 | 32.22 | 1.0 | 0 | La Ciudad Sin Mapa |
| 10 | terror | NO | 0 | 0 | 67.77 | 0.0 | 1.0 |  | LLMValidationError: PlanHistoria: salida inválida tras 4 int |

Causas de reintento (errores de validación devueltos al modelo):

| Campo · causa | Veces |
|---|---:|
| plan_escenas.resumen · idioma | 10 |
| personajes.descripcion_visual_fija · presupuesto CLIP | 7 |
| estilo_visual · presupuesto CLIP | 5 |
| personajes.descripcion_visual_fija · idioma | 5 |
| prompt_imagen · presupuesto CLIP | 2 |
| titulo · idioma | 1 |
| prompt_imagen · idioma | 1 |
