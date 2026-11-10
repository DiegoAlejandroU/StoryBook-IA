# Resultados F0 - 2026-11-10T06:39:41

- Perfil: `rapido` - GPU: NVIDIA GeForce RTX 3050 Laptop GPU (4096.0 MB), driver 617.42
- Tiempo total del script: 285.4 s

| Etapa | Segundos | Dispositivo | VRAM torch pico (MB) | VRAM GPU pico (MB) | Datos |
|---|---:|---|---:|---:|---|
| llm_bible | 227.34 | cuda | 0.0 | 2535.0 | estrategia=por_etapas, num_ctx=4096, llamadas=6, intentos=14, tokens_salida=2590, tokens_por_s=11.39 |
| imagen_carga | 5.66 | cuda | 2197.9 | 2396.5 |  |
| imagen_gen_1 | 4.284 | cuda | 3112.6 | 4076.5 | pasos=6, seed=1936057689, scheduler=lcm |
| imagen_gen_2 | 2.825 | cuda | 3112.6 | 4076.5 | pasos=6, seed=1936057690, scheduler=lcm |
| ip_adapter_embeds_cpu | 4.327 | cuda | 2197.9 | 4076.5 |  |
| ip_adapter_carga | 0.474 | cuda | 2240.9 | 4076.5 |  |
| imagen_gen_ip_adapter | 3.871 | cuda | 3155.6 | 4066.5 | ip_scale=0.6, seed=1936057689 |
| voz_carga | 2.075 | cuda | 0.0 | 224.5 |  |
| voz_sintesis | 2.783 | cuda | 0.0 | 224.5 | duracion_audio_s=41.64, rtf=0.067, sample_rate=22050 |
| sonido_audioldm_carga | 3.089 | cuda | 821.0 | 932.5 |  |
| sonido_audioldm_gen_1 | 1.622 | cuda | 943.2 | 1274.5 | duracion_audio_s=8.0, rtf=0.203, sample_rate=16000 |
| sonido_audioldm_gen_2 | 1.38 | cuda | 943.2 | 1274.5 | duracion_audio_s=8.0, rtf=0.172, sample_rate=16000 |
| eval_whisper_carga | 3.067 | cuda | 0.0 | 226.5 |  |
| eval_wer | 7.524 | cuda | 0.0 | 226.5 | wer=0.0084 |
| eval_clip_carga | 2.321 | cuda | 0.0 | 226.5 |  |
| eval_clip | 0.258 | cuda | 0.0 | 226.5 | clip_imagen_texto=0.4127 |

- Story Bible válida al primer intento: False (errores: 8); fracción del LLM en GPU: 0.724
- WER narración: 0.0084 - CLIP imagen-texto: 0.4127 - CLIP imagen-imagen: {'media': 0.8132, 'minimo': 0.7884, 'pares': 3}
