# F1 · Generaciones reales de la Story Bible (2026-11-10 11:57)

- Perfil `calidad` · modelo `qwen3:8b` · estrategia `por_etapas` · auditor sí · num_ctx 8192 · num_gpu auto
- **Story Bibles válidas: 9/10**
- Tiempo por historia (mediana): 982.31 s · tokens/s (mediana): 3.02
- Intentos por llamada (mediana): 1.57 · fracción del modelo en GPU (mediana): 0.39

| # | Género | Válida | Llamadas | Intentos | s total | tok/s | GPU | Contrad. | Título |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | misterio | NO | 1 | 4 | 852.66 | 0.0 | 0.387 |  | LLMValidationError: PlanHistoria: salida inválida tras 4 int |
| 2 | fantasia | sí | 7 | 11 | 1122.3 | 2.87 | 0.387 | 0 | La sombra de Lila |
| 3 | ciencia_ficcion | sí | 7 | 10 | 1034.29 | 3.02 | 0.387 | 0 | El Jardín del Silencio |
| 4 | terror | sí | 7 | 13 | 1316.88 | 2.51 | 0.387 | 3 | Las Habitaciones que Suenan |
| 5 | infantil | sí | 7 | 9 | 922.72 | 3.41 | 0.387 | 0 | La aventura del perro y el gato |
| 6 | aventura | sí | 7 | 9 | 930.32 | 3.42 | 0.387 | 0 | El Tesoro del Abuelo |
| 7 | misterio | sí | 7 | 11 | 893.06 | 3.28 | 0.387 | 0 | El Minuto Perdido |
| 8 | fantasia | sí | 7 | 12 | 1120.5 | 2.89 | 0.387 | 0 | El Último Dragón de la Biblioteca |
| 9 | ciencia_ficcion | sí | 7 | 12 | 1200.91 | 2.6 | 0.387 | 0 | La señal del norte |
| 10 | terror | sí | 7 | 9 | 861.63 | 3.66 | 0.387 | 0 | La Muñeca del Amanecer |

Causas de reintento (errores de validación devueltos al modelo):

| Campo · causa | Veces |
|---|---:|
| personajes.descripcion_visual_fija · idioma | 31 |
| prompt_imagen · idioma | 21 |
| prompt_sonido · idioma | 17 |
| estilo_visual.iluminacion · otro | 11 |
| estilo_visual.tecnica · idioma | 10 |
| estilo_visual.paleta · idioma | 10 |
| estilo_visual.iluminacion · idioma | 4 |
