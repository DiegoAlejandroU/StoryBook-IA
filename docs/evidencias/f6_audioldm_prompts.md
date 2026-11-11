# AudioLDM: variantes de prompt y guidance (complemento de 6.2)

Prompts: los `prompt_sonido` de la batería `20261111_111458`. Seeds: 101, 1101.
Una escena pasa si alguna de sus 2 seeds da un clip apto (como en producción).

| Variante | Escenas que pasan | Clips aptos | Nivel mediano | s/clip |
|---|---|---|---|---|
| `base` | 13/20 | 24/40 | -18.2 dBFS | 1.29 |
| `sufijo` | 20/20 | 39/40 | -14.6 dBFS | 1.29 |
| `guia_alta` | 12/20 | 20/40 | -21.4 dBFS | 1.3 |
| `sufijo_guia` | 20/20 | 40/40 | -9.2 dBFS | 1.26 |

## Por escena (mejor nivel de las 2 seeds; ✗ = ninguna apta)

| Historia | Esc. | Prompt (base) | `base` | `sufijo` | `guia_alta` | `sufijo_guia` |
|---|---|---|---|---|---|---|
| una_casa_antigua_donde_t | 1 | Wind rustling through trees, heartbeat in the background. | -51.7 ✗ | -14.5 | -67.1 ✗ | -11.4 |
| una_casa_antigua_donde_t | 2 | Wind howls through trees. A heartbeat pulses beneath it. | -7.0 | -12.2 | -1.7 | -8.1 |
| una_casa_antigua_donde_t | 3 | Wind through trees, mechanical hum growing louder. | -62.8 ✗ | -6.9 | -65.8 ✗ | -2.4 |
| una_casa_antigua_donde_t | 4 | Wind howls. A slow heartbeat pulses. | -10.5 | -10.0 | -18.9 | -9.0 |
| una_casa_antigua_donde_t | 5 | Wind through trees, distant water stream, heartbeat pulse. | -32.1 ✗ | -15.8 | -52.7 ✗ | -13.8 |
| el_ultimo_dragon_vive_es | 1 | Wind howls through trees. A slow heartbeat pulses beneath it. | -7.9 | -13.3 | -1.8 | -9.0 |
| el_ultimo_dragon_vive_es | 2 | Wind rustling through trees, heartbeat in the background. | -51.7 ✗ | -14.5 | -67.1 ✗ | -11.4 |
| el_ultimo_dragon_vive_es | 3 | Wind howls through trees. A slow heartbeat pulses. | -7.3 | -13.4 | -1.7 | -8.4 |
| el_ultimo_dragon_vive_es | 4 | Wind whispers through old stones. A slow heartbeat pulses. Distant for | -18.7 | -16.4 | -18.0 | -14.0 |
| el_ultimo_dragon_vive_es | 5 | Wind whispers through ancient stones. A slow heartbeat pulses. | -16.6 | -16.2 | -14.4 | -14.9 |
| una_astronauta_despierta | 1 | Wind through metal vents. Heartbeat rhythm. Distant forest sounds. | -25.1 | -15.3 | -39.0 | -15.4 |
| una_astronauta_despierta | 2 | Low hum of machinery. Heartbeat pulses. | -3.7 | -10.6 | -0.5 | -4.2 |
| una_astronauta_despierta | 3 | Low wind hums through the hull; a steady heartbeat pulses from inside  | -7.8 | -19.6 | -7.7 | -35.2 |
| una_astronauta_despierta | 4 | Wind howls through vents. Machinery hums with growing urgency. | -7.2 | -2.9 | -1.2 | -0.8 |
| una_astronauta_despierta | 5 | Wind hums through the hull. A steady heartbeat pulses. Machinery whirs | -9.8 | -5.0 | -11.5 | -1.5 |
| un_perro_y_un_gato_deben | 1 | Wind blows through trees, birds sing. | -13.1 ✗ | -13.4 | -20.0 ✗ | -5.5 |
| un_perro_y_un_gato_deben | 2 | Wind blowing through trees and birds singing in the distance. | -35.6 ✗ | -14.7 | -39.4 ✗ | -6.5 |
| un_perro_y_un_gato_deben | 3 | Wind blows through narrow streets. Footsteps echo as animals move. | -7.4 | -16.6 | -1.1 | -7.9 |
| un_perro_y_un_gato_deben | 4 | Wind blows through trees; birds sing in the distance. | -17.8 | -9.1 | -22.8 ✗ | -2.4 |
| un_perro_y_un_gato_deben | 5 | Wind blowing through old houses, light footsteps on cobblestones, dist | -48.0 ✗ | -28.8 | -66.9 ✗ | -27.4 |
