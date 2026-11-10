# F1 · Generaciones reales de la Story Bible (2026-11-10 08:37)

- Perfil `rapido` · modelo `qwen3:4b-instruct-2507-q4_K_M` · estrategia `por_etapas` · auditor sí · num_ctx 4096 · num_gpu 99
- **Story Bibles válidas: 10/10**
- Tiempo por historia (mediana): 85.22 s · tokens/s (mediana): 35.22
- Intentos por llamada (mediana): 1.14 · fracción del modelo en GPU (mediana): 1.00

| # | Género | Válida | Llamadas | Intentos | s total | tok/s | GPU | Contrad. | Título |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | misterio | sí | 7 | 8 | 85.14 | 34.84 | 1.0 | 0 | La luz del olvido |
| 2 | fantasia | sí | 7 | 7 | 68.9 | 43.83 | 1.0 | 0 | La Sombra que Habla |
| 3 | ciencia_ficcion | sí | 7 | 7 | 68.42 | 43.85 | 1.0 | 0 | La Huerta del Cielo |
| 4 | terror | sí | 7 | 9 | 103.68 | 29.05 | 1.0 | 0 | La Casa que Cambia |
| 5 | infantil | sí | 7 | 7 | 65.83 | 43.5 | 1.0 | 0 | El Puente de Max y Luna |
| 6 | aventura | sí | 7 | 8 | 85.31 | 35.59 | 1.0 | 0 | El Tesoro del Abuelo en la Selva |
| 7 | misterio | sí | 7 | 8 | 98.79 | 31.27 | 1.0 | 0 | El Minuto Que Se Detuvo |
| 8 | fantasia | sí | 7 | 7 | 67.23 | 43.46 | 1.0 | 0 | El último dragón de la biblioteca |
| 9 | ciencia_ficcion | sí | 7 | 8 | 87.08 | 34.75 | 1.0 | 0 | La Ciudad de las Noches |
| 10 | terror | sí | 7 | 8 | 87.01 | 33.7 | 1.0 | 0 | La Muñeca de Nieve |

Causas de reintento (errores de validación devueltos al modelo):

| Campo · causa | Veces |
|---|---:|
| personajes.descripcion_visual_fija · idioma | 13 |
| prompt_imagen · presupuesto CLIP | 1 |
