# F2 · Variantes de imagen (2026-11-10 12:44)

- Perfil base `rapido` · historia `C:/Users/diego/Documents/StoryBook-IA/outputs/f1/20261110_085328/story_01.json`: "El Faro de las Noches" (misterio), 2 personajes. Misma Bible y seeds.
- CLIP imagen-texto: cuánto se parece cada imagen a su prompt (acción de la escena).
- CLIP imagen-imagen: cuánto se parecen las 5 entre sí (consistencia).

| # | Variante | s/imagen | VRAM pico GPU | Truncados | CLIP texto | CLIP img-img (media / mín.) | Carpeta |
|---:|---|---:|---:|---:|---:|---|---|
| 1 | `ip=0.6` | 3.503 | 4066.5 MB | 3/5 | 0.3502 | 0.8145 / 0.7381 | `v1` |
| 2 | `ip=0.4` | 3.525 | 4066.5 MB | 3/5 | 0.3648 | 0.7493 / 0.6224 | `v2` |
| 3 | `ip=0.25` | 3.514 | 4066.5 MB | 3/5 | 0.3458 | 0.7262 / 0.577 | `v3` |
| 4 | `ip=0.4+orden=accion_primero` | 3.551 | 4066.5 MB | 3/5 | 0.355 | 0.7512 / 0.6221 | `v4` |
| 5 | `ip=0.25+orden=accion_primero` | 3.552 | 4066.5 MB | 3/5 | 0.3456 | 0.6241 / 0.3856 | `v5` |
