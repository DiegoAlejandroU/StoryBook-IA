# F2/F3 · Imágenes y voz reales (2026-11-10 12:22)

- Perfil `rapido` · historia `C:/Users/diego/Documents/StoryBook-IA/outputs/f1/20261110_085328/story_01.json`: "El Faro de las Noches" (misterio), 2 personajes.

## Imágenes (tarea 2.3)

- `Lykon/dreamshaper-8` · lcm · 6 pasos · CFG 1.5 · 768×512 · IP-Adapter sí (escala 0.6).
- Tiempos: carga 30.125 s · character sheet 2.818 s · IP-Adapter 4.68 s · **por imagen (mediana) 3.424 s** · total 55.27 s.
- **VRAM pico:** GPU 4066.5 MB de 4096.0 MB · torch 3155.6 MB.
- Respaldos (OOM u otro error): ninguno · fallbacks: ninguno.
- CLIP imagen-texto (media): 0.3502 · CLIP imagen-imagen: media 0.8145, mínimo 0.7381 (10 pares).

| Escena | s | Seed | Tokens | Truncado | Nombres sustituidos | CLIP texto |
|---:|---:|---:|---:|---|---|---:|
| 1 | 3.957 | 3740413757 | 60 | no | - | 0.3989 |
| 2 | 3.42 | 3740413757 | 71 | sí | - | 0.2615 |
| 3 | 3.418 | 3740413757 | 73 | sí | - | 0.4005 |
| 4 | 3.424 | 3740413757 | 74 | sí | - | 0.3648 |
| 5 | 3.427 | 3740413757 | 61 | no | Luna→25 years old | 0.3255 |

## Voz (tarea 3.3)

| Voz | Duración total | RTF (mediana) | WER (mediana) | WER (máximo) | Carpeta |
|---|---:|---:|---:|---:|---|
| es_MX-claude-high | 216.372 s | 0.03 | 0.083 | 0.0965 | `voz\es_MX-claude-high` |
| es_MX-ald-medium | 220.285 s | 0.027 | 0.047 | 0.1058 | `voz\es_MX-ald-medium` |
| es_ES-davefx-medium | 195.055 s | 0.027 | 0.068 | 0.1154 | `voz\es_ES-davefx-medium` |

Escucha los `voice_N.wav` de cada carpeta y elige la voz (tarea 3.3).

Escena con más WER en la primera voz (escena 3, WER 0.0965):

- Texto: Luna escucha silenciosamente mientras Elias habla de su juventud. El viento sisea entre los árboles, como si recordara algo olvidado. Dice que su padre encendió el faro cada noche en 1983 para guiar a barcos perdidos durante tormentas. "No había electricidad", añade, mirando al mar con tristeza. El agua se mueve lentamente bajo las rocas, como un latido antiguo. Luna entiende que el faro no es solo una luz: es un testigo de sacrificios olvidados. Elias niega haber visto a su padre encenderlo en persona, pero sus ojos brillan con recuerdos oscuros. La brisa fría acaricia su rostro mientras habla. Luna siente que el faro no solo ilumina el mar… también ilumina historias olvidadas.
- Whisper: Luna escucha silenciosamente, mientras Helias habla de su juventud, el viento si sea entre los árboles, como si recordara algo olvidado. Dice que su padre encendió el faro cada noche en 1983 para allada barcos perdidos durante tormentas, no a vida electricidad. Añade, mirando al mar con tristeza, el agua se mueve lentamente bajo las rocas, como un latido antiguo. Luna entiende que del faro no es solo una luz, es un testigo de sacrificios olvidados. Helias niega haber visto a su padre encenderlo en persona, pero sus ojos brillan con recuerdos oscuros. La brisa fría acaricia su rostro mientras habla. Luna siente que del faro no solo dilumina, el mar también ilumina historias olvidadas.
