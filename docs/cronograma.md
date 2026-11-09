# Cronograma StoryBook IA (desarrollador único)

Ventana: lunes 9 a lunes 23 de noviembre de 2026 (entrega y sustentación el mismo día).
Supuesto de dedicación: ~4 h en días hábiles y ~8 h en fin de semana (≈ 36 h/semana).
Congelamiento de código: viernes 20 de noviembre.

## Semana 1 (9–15 nov): construir el vertical slice y endurecerlo

| Día | Fase | Entregable verificable | Criterio de rúbrica |
|---|---|---|---|
| Lun 9 | F0 | `uv sync`, `check_env` sin FALLO, `download_models`, `f0_hello all` con `resumen.md` | Arquitectura (restricciones medidas) |
| Mar 10 | F1 | `planner.py` (estrategia a) con reparación por reintentos + auditor; 10 generaciones seguidas válidas | Integración, Coherencia |
| Mié 11 | F2 | `prompt_builder.py` (77 tokens exactos), `generator.py`, character sheet + IP-Adapter; 5 imágenes sin OOM | Coherencia |
| Jue 12 | F3 + F4 | `tts.py` + WER; `sound/` con A → B → C y `mixer.py` (loop, LUFS, ducking) | Integración |
| Vie 13 | F5 | `pipeline.py`, `storage.py` (manifest) y UI Streamlit mínima: **historia completa de punta a punta** | Integración (30 %) |
| Sáb 14 | F5 | Fallbacks automáticos visibles en UI, cargar historias, `verify_offline.py` + prueba con Wi-Fi apagado, 2–3 historias en `samples/`, video borrador de respaldo | Integración, Entregables |
| Dom 15 | Buffer + F6 | Absorber retrasos; `run_experiment.py`, `make_contact_sheet.py`, `results.csv` | Arquitectura |

## Semana 2 (16–22 nov): evidenciar, documentar y ensayar

| Día | Fase | Entregable verificable | Criterio de rúbrica |
|---|---|---|---|
| Lun 16 | F6 | C1/C2/C3 × 4 géneros (terror, fantasía, ciencia ficción, infantil) con hojas de contacto | Coherencia (25 %) |
| Mar 17 | F6 | 4B vs 8B y LCM vs 25 pasos; gráficas; checklist humano 1–5; conclusión con datos | Arquitectura (25 %) |
| Mié 18 | F7 | Informe secciones 1–6 (arquitectura con Mermaid, justificación por VRAM) | Entregables |
| Jue 19 | F7 | Informe secciones 7–12; `MODELS.md` y `AUDIO_LICENSES.md` finales | Entregables |
| Vie 20 | F7 | README completo probado desde una carpeta limpia; tag `v1.0`; **congelar código** | Entregables (20 %) |
| Sáb 21 | F7 | Video 5–7 min; PDF final | Entregables |
| Dom 22 | F8 | Simulacro con preguntas del jurado; demo con 3 ideas al azar; checklist del día | Sustentación |
| Lun 23 | — | Entrega y sustentación (portátil a la corriente, modo Turbo, Ollama abierto, `samples/` listo) | Todos |

## Control de alcance

Nunca se recorta: 5 escenas completas siempre, fallbacks automáticos, ejecución offline
verificada, comparación C1/C2/C3 con métricas, README reproducible, informe, video.

Se recorta en este orden si hay retraso: Kokoro (Piper vs Kokoro) → CLAP → estrategia de
texto (b) → regenerar escena individual en la UI → perfil "calidad" en la demo.
