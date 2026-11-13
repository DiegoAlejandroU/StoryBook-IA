# F7 · Modelo de imagen más grande: SDXL frente a SD 1.5 (2026-11-13)

Historia: "El Río Olvidado" (`20261113_105217_un_grupo_de_amigos_animales_en`). Mismo texto, mismas seeds; solo cambia el modelo de imagen. `original` son las imágenes de la historia tal como se generaron (antes de la corrección del personaje foco).

| Perfil | Total | Carga | Por imagen | VRAM torch (pico / reservada) | VRAM GPU | CLIP img-img (media / mín.) | CLIP img-texto | Respaldos |
|---|---|---|---|---|---|---|---|---|
| `original` | — | — | — | — / — | — | 0.7339 / 0.4508 | 0.2817 | — |
| `rapido` | 40.1 s | 12.177 s | 3.55 s | 3155.6 MB / 4034.0 MB | 4066.5 MB | 0.7339 / 0.4508 | 0.2817 | 0 |
| `sdxl` | 88.99 s | 10.643 s | 10.93 s | 3477.2 MB / 3780.0 MB | 4006.5 MB | 0.6582 / 0.3752 | 0.3476 | 0 |

## `rapido`: personaje foco e IP-Adapter por escena

| Escena | Foco | IP-Adapter | s | Prompt |
|---|---|---|---|---|
| 1 | boy_kai | 0.4 | 4.126 | boy age 10, a boy with curly hair, boy age 10, curly brown hair, wears a leaf-patterned shirt, carries a small |
| 2 | old_man_toro | 0.0 | 3.571 | old man age 60 stands in a clearing, old man age 60, white beard, wears a woven hat and tunic, carries a staff |
| 3 | boy_kai | 0.24 | 3.54 | robot age 200, a robot, walks through dense jungle with boy age 10 and old man age 60, monkey age 8 hangs from |
| 4 | boy_kai | 0.24 | 3.553 | boy age 10 and robot age 200 stand at a lake of moving stones, old man age 60 watches calmly, monkey age 8 han |
| 5 | boy_kai | 0.24 | 3.548 | boy age 10, old man age 60, monkey age 8 and robot age 200 stand by a glowing river in the jungle. Wide shot.  |

## `sdxl`: personaje foco e IP-Adapter por escena

| Escena | Foco | IP-Adapter | s | Prompt |
|---|---|---|---|---|
| 1 | boy_kai | 0.4 | 12.106 | boy age 10, a boy with curly hair, boy age 10, curly brown hair, wears a leaf-patterned shirt, carries a small |
| 2 | old_man_toro | 0.0 | 10.769 | old man age 60 stands in a clearing, old man age 60, white beard, wears a woven hat and tunic, carries a staff |
| 3 | boy_kai | 0.24 | 10.895 | robot age 200, a robot, walks through dense jungle with boy age 10 and old man age 60, monkey age 8 hangs from |
| 4 | boy_kai | 0.24 | 10.933 | boy age 10 and robot age 200 stand at a lake of moving stones, old man age 60 watches calmly, monkey age 8 han |
| 5 | boy_kai | 0.24 | 10.96 | boy age 10, old man age 60, monkey age 8 and robot age 200 stand by a glowing river in the jungle. Wide shot.  |

Hojas de contactos: `docs/evidencias/f7_hojas/`.
