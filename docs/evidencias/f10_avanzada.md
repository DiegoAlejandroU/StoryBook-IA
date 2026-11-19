# f10_avanzada: la historia ilustrada otra vez con el código actual (2026-11-19 17:51)

Historia: "El Respiro de la Sabana" (`20261118_151141_un_elefante_en_la_sabana_afric`). Mismo texto, mismas seeds; solo cambia el modelo de imagen. `original` son las imágenes de la historia tal como se generaron (antes de la corrección del personaje foco).

Con el **ilustrador** (17 nov): el LLM describió qué se ve en cada escena y el prompt se armó con eso; de 2 versiones por imagen, OpenCLIP eligió la que mejor muestra a todos (puntaje en negrita).

Grupos de la idea: ninguno. Avisos: ninguno.

| Escena | Principal | Acompañantes | Acción | Lugar | Plano |
|---|---|---|---|---|---|
| 1 | elephant_60 | — | lowers her snout, ears twitching as if listening to a silent wind | a moonlit savanna at twilight, trees still and shadows deep | medium shot |
| 2 | elephant_60 | zebra_12 (one) | an old elephant moves silently across the savanna, feet barely touching ground | a quiet savanna at dusk, golden light fading into deep blue | medium shot |
| 3 | buffalo_25 | — | stares into the darkness, eyes glowing with quiet intensity | a vast savanna at twilight under a clear dark sky | medium shot |
| 4 | elephant_60 | buffalo_25 (one), zebra_12 (one) | opens mouth slowly, releasing a deep, earthy sound | a valley at twilight with distant hills and soft shadows | medium shot |
| 5 | buffalo_25 | elephant_60 (one) | elephant and buffalo gaze at each other, wind gently stirring their fur | a vast savanna under deep blue sky with soft golden light | medium shot |

| Perfil | Total | Carga | Por imagen | VRAM torch (pico / reservada) | VRAM GPU | RAM (proceso / libre mín.) | CLIP img-img (media / mín.) | CLIP img-texto | Respaldos |
|---|---|---|---|---|---|---|---|---|---|
| `original` | — | — | — | — / — | — | — / — | 0.8053 / 0.7233 | 0.2976 | — |
| `sdxl` | 284.73 s | 35.021 s | 11.07 s | 3477.2 MB / 3780.0 MB | 4004.5 MB | 12.31 GB / 1.46 GB | 0.8451 / 0.7233 | 0.2979 | 0 |
| `avanzada` | 273.5 s | 1.247 s | 53.34 s | 2083.2 MB / 5090.0 MB | 4080.5 MB | 17.95 GB / 0.01 GB | 0.7628 / 0.6331 | 0.3147 | 0 |

## `sdxl`: personaje foco e IP-Adapter por escena

| Escena | Foco | IP-Adapter | s | Debe verse | Versiones (CLIP) | Prompt |
|---|---|---|---|---|---|---|
| 1 | elephant_60 | 0.4 | 23.737 | an African elephant | 0.325 / **0.3277** | medium shot, an African elephant, lowers her snout, ears twitching as if listening to a silent wind, a moonlit |
| 2 | elephant_60 | 0.24 | 22.321 | an African elephant, an African zebra | 0.2375 / **0.2395** | medium shot, an African elephant, with an African zebra, moves silently across the savanna, feet barely touchi |
| 3 | buffalo_25 | 0.0 | 21.792 | an African buffalo | 0.3458 / **0.3538** | medium shot, an African buffalo, stares into the darkness, eyes glowing with quiet intensity, a vast savanna a |
| 4 | elephant_60 | 0.24 | 24.654 | an African elephant, an African buffalo, an African zebra | **0.2404** / 0.2303 | medium shot, an African elephant, with an African buffalo and an African zebra, opens mouth slowly, releasing  |
| 5 | buffalo_25 | 0.0 | 22.995 | an African buffalo, an African elephant | 0.2665 / **0.2721** | medium shot, an African buffalo, with an African elephant, elephant and buffalo gaze at each other, wind gentl |

## `avanzada`: personaje foco e IP-Adapter por escena

| Escena | Foco | IP-Adapter | s | Debe verse | Versiones (CLIP) | Prompt |
|---|---|---|---|---|---|---|
| 1 | elephant_60 | 0.0 | 61.665 | an African elephant | — | medium shot, an African elephant, lowers her snout, ears twitching as if listening to a silent wind, a moonlit |
| 2 | elephant_60 | 0.0 | 53.344 | an African elephant, an African zebra | — | medium shot, an African elephant, with an African zebra (white stripes, short tail), moves silently across the |
| 3 | buffalo_25 | 0.0 | 51.821 | an African buffalo | — | medium shot, an African buffalo, stares into the darkness, eyes glowing with quiet intensity, a vast savanna a |
| 4 | elephant_60 | 0.0 | 48.056 | an African elephant, an African buffalo, an African zebra | — | medium shot, an African elephant, with an African buffalo (dark brown hide, short horns) and an African zebra  |
| 5 | buffalo_25 | 0.0 | 54.088 | an African buffalo, an African elephant | — | medium shot, an African buffalo, with an African elephant (gray skin, thick trunk), elephant and buffalo gaze  |

Hojas de contactos: `docs/evidencias/f10_avanzada_hojas/`.
