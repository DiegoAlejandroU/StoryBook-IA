# Resultados F0 - 2026-11-09T17:35:09

- Perfil: `rapido` - GPU: NVIDIA GeForce RTX 3050 Laptop GPU (4096.0 MB), driver 617.42
- Tiempo total del script: 363.4 s

| Etapa | Segundos | Dispositivo | VRAM torch pico (MB) | VRAM GPU pico (MB) | Datos |
|---|---:|---|---:|---:|---|
| llm | - | - | - | - | ERROR: LLMResponseError: Respuesta truncada por longitud (num_ctx=8192, num_predict=512 |
| image | - | - | - | - | ERROR: TypeError: SlicedAttnProcessor.__init__() missing 1 required positional argument |
| voz_carga | 2.103 | cuda | 0.0 | 2444.5 |  |
| voz_sintesis | 1.272 | cuda | 0.0 | 2444.5 | duracion_audio_s=41.18, rtf=0.031, sample_rate=22050 |
| sound | - | - | - | - | ERROR: GPUError: Ningún backend generativo de sonido funcionó: {'sa3': {'estado': 'no_d |
| eval_whisper_carga | 1.493 | cuda | 0.0 | 224.5 |  |
| eval_wer | 6.981 | cuda | 0.0 | 224.5 | wer=0.0748 |

- Story Bible válida al primer intento: - (errores: 0); fracción del LLM en GPU: -
- WER narración: 0.0748 - CLIP imagen-texto: - - CLIP imagen-imagen: -
