# f9_ilustrador: la historia ilustrada otra vez con el código actual (2026-11-17 19:51)

Historia: "El Perro del Silencio" (`20261113_150217_un_perro_rodeado_de_gatos_en_u`). Mismo texto, mismas seeds; solo cambia el modelo de imagen. `original` son las imágenes de la historia tal como se generaron (antes de la corrección del personaje foco).

Con el **ilustrador** (17 nov): el LLM describió qué se ve en cada escena y el prompt se armó con eso; de 2 versiones por imagen, OpenCLIP eligió la que mejor muestra a todos (puntaje en negrita).

Grupos de la idea: surrounded by many cats. Avisos: ninguno.

| Escena | Principal | Acompañantes | Acción | Lugar | Plano |
|---|---|---|---|---|---|
| 1 | dog_1 | cat (many) | walks slowly on cold stone with trembling paws | narrow dark streets of an old city at dusk | medium shot |
| 2 | dog_1 | cat_1 (one), cat (many) | pauses, ears gently brushed by cold wind | narrow street beneath old building rooftops at dusk | medium shot |
| 3 | dog_1 | cat_1 (many), cat_2 (one) | stares at the column as a whisper flows through the cats | a rooftop at twilight with stone walls and wind-blown shadows | wide shot |
| 4 | dog_1 | cat_1 (many), cat_2 (one) | stares at glowing cat eyes in the street | cobbled alleyway surrounded by ancient buildings at twilight | wide shot |
| 5 | dog_1 | cat_1 (one), cat_2 (one) | looks at Mira and Zorin with glowing eyes | shadowed rooftop at twilight in a ancient city | medium shot |

| Perfil | Total | Carga | Por imagen | VRAM torch (pico / reservada) | VRAM GPU | CLIP img-img (media / mín.) | CLIP img-texto | Respaldos |
|---|---|---|---|---|---|---|---|---|
| `original` | — | — | — | — / — | — | 0.7438 / 0.6124 | 0.3485 | — |
| `sdxl` | 159.67 s | 20.771 s | 10.99 s | 3475.8 MB / 3780.0 MB | 4004.5 MB | 0.7681 / 0.6754 | 0.378 | 0 |

## `sdxl`: personaje foco e IP-Adapter por escena

| Escena | Foco | IP-Adapter | s | Debe verse | Versiones (CLIP) | Prompt |
|---|---|---|---|---|---|---|
| 1 | dog_1 | 0.0 | 23.668 | a dog, many cats | 0.2068 / **0.2485** | medium shot, a dog surrounded by many cats, walks slowly on cold stone with trembling paws, narrow dark street |
| 2 | dog_1 | 0.0 | 21.973 | a dog, a cat, many cats | 0.2059 / **0.2261** | medium shot, a dog surrounded by many cats, with a cat, pauses, ears gently brushed by cold wind, narrow stree |
| 3 | dog_1 | 0.0 | 22.276 | a dog, a cat, many cats | **0.1928** / 0.192 | wide shot, a dog surrounded by many cats, with a cat, stares at the column as a whisper flows through the cats |
| 4 | dog_1 | 0.0 | 22.125 | a dog, a cat, many cats | 0.2137 / **0.2353** | wide shot, a dog surrounded by many cats, with a cat, stares at glowing cat eyes in the street, cobbled alleyw |
| 5 | dog_1 | 0.0 | 22.102 | a dog, two cats, many cats | **0.2118** / 0.1945 | medium shot, a dog surrounded by many cats, with two cats, looks at a cat and a cat with glowing eyes, shadowe |

Hojas de contactos: `docs/evidencias/f9_ilustrador_hojas/`.
