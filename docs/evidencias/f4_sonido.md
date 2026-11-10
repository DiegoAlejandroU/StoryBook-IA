# F4 · Sonido y mezcla reales (2026-11-10 13:09)

- Perfil `rapido` · historia `C:/Users/diego/Documents/StoryBook-IA/outputs/f1/20261110_085328/story_01.json`: "El Faro de las Noches" (misterio).
- Voz `es_MX-claude-high`: 216.779 s de narración.

| Variante | Backend por escena (1-5) | s/clip | VRAM pico GPU | LUFS voz / ambiente | Ambiente bajo la voz (pausas / habla) | Fallbacks |
|---|---|---:|---:|---|---|---|
| `cadena` | audioldm · audioldm · audioldm · audioldm · audioldm | 1.338 | 1274.5 MB | -18.0 / -30.0 | 12.0 / 18.0 dB | sonido:sa3:no_disponible |
| `procedural` | procedural · procedural · procedural · procedural · procedural | 0.092 | 226.5 MB | -18.0 / -30.0 | 12.0 / 18.0 dB | ninguno |

Prompts y etiquetas de sonido de cada escena:

1. `Ongoing ocean waves, wind howling through dense vegetation, faint heartbeat pulse.` (wind, ocean_waves, heartbeat)
2. `Wind howls through the forest. A slow heartbeat pulses in the background.` (wind, forest, heartbeat)
3. `Wind howls through the forest. Water streams gently over rocks. Distant waves crash against the shore.` (wind, water_stream, forest)
4. `Wind howls through the rocks. A slow heartbeat pulses in the background.` (wind, water_stream, heartbeat)
5. `Constant ocean waves, soft wind, slow heartbeat pulses` (wind, ocean_waves, heartbeat)

Escucha `mix_N.wav` de cada carpeta de variante: ¿se distingue el ambiente de la voz? ¿encaja con la escena?
