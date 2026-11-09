# Resultados F0 - 2026-11-09T17:50:02

- Perfil: `rapido` - GPU: NVIDIA GeForce RTX 3050 Laptop GPU (4096.0 MB), driver 617.42
- Tiempo total del script: 269.2 s

| Etapa | Segundos | Dispositivo | VRAM torch pico (MB) | VRAM GPU pico (MB) | Datos |
|---|---:|---|---:|---:|---|
| llm | - | - | - | - | ERROR: LLMResponseError: Respuesta truncada por longitud (num_ctx=8192, num_predict=409 |
| imagen_carga | 5.473 | cuda | 2197.9 | 2332.5 |  |
| imagen_gen_1 | 4.01 | cuda | 3112.6 | 4076.5 | pasos=6, seed=1234, scheduler=lcm |
| imagen_gen_2 | 2.857 | cuda | 3112.6 | 4076.5 | pasos=6, seed=1235, scheduler=lcm |
| ip_adapter_embeds_cpu | 4.485 | cuda | 2197.9 | 4076.5 |  |
| ip_adapter_carga | 0.402 | cuda | 2240.9 | 4076.5 |  |
| imagen_gen_ip_adapter | 4.01 | cuda | 3155.6 | 4066.5 | ip_scale=0.6, seed=1234 |
| voz_carga | 1.809 | cuda | 0.0 | 224.5 |  |
| voz_sintesis | 1.313 | cuda | 0.0 | 224.5 | duracion_audio_s=40.89, rtf=0.032, sample_rate=22050 |
| sonido_audioldm_carga | 2.955 | cuda | 821.0 | 972.5 |  |
| sonido_audioldm_gen_1 | 1.614 | cuda | 943.2 | 1274.5 | duracion_audio_s=8.0, rtf=0.202, sample_rate=16000 |
| sonido_audioldm_gen_2 | 1.219 | cuda | 943.2 | 1274.5 | duracion_audio_s=8.0, rtf=0.152, sample_rate=16000 |
| eval_whisper_carga | 1.574 | cuda | 0.0 | 226.5 |  |
| eval_wer | 7.209 | cuda | 0.0 | 226.5 | wer=0.0561 |
| eval_clip_carga | 2.246 | cuda | 0.0 | 226.5 |  |
| eval_clip | 0.27 | cuda | 0.0 | 226.5 | clip_imagen_texto=0.408 |

- Story Bible válida al primer intento: - (errores: 0); fracción del LLM en GPU: -
- WER narración: 0.0561 - CLIP imagen-texto: 0.408 - CLIP imagen-imagen: {'media': 0.8206, 'minimo': 0.7449, 'pares': 3}
