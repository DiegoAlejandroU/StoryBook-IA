# f10: voz y ambiente del perfil Avanzada (2026-11-19 12:35)

Historia: `20261118_151141_un_elefante_en_la_sabana_afric`. Audios en `docs/evidencias/f10_audio/`.

## Voz

Backend: **piper** es_MX-claude-high en cpu (respaldo: XTTS falló: XttsError: XTTS no cargó: ImportError: 
From Pytorch 2.9, the torchcodec library is required for audio IO, but it was not
found in your environment. You can install it with Coqui's `codec` extra:
```
pip install coqui-tts[codec]
```
 (registro: C:\Users\diego\AppData\Local\Temp\storybook_xtts__1fqy5k9.log)). Carga: 8.557 s.

| Escena | Audio (s) | Síntesis (s) | RTF |
|---|---|---|---|
| 1 | 40.997 | 2.864 | 0.0699 |
| 2 | 42.947 | 1.48 | 0.0345 |
| 3 | 33.543 | 1.005 | 0.03 |
| 4 | 46.918 | 1.385 | 0.0295 |
| 5 | 48.996 | 1.354 | 0.0276 |

## Ambiente

Cadena: sao → sa3 → audioldm → library → procedural. Total: 24.87 s. Respaldos: sonido:sao:no_disponible, sonido:sa3:no_disponible, sonido:escena_1:audioldm_fallo, sonido:escena_3:audioldm_fallo, sonido:library:no_disponible.

| Escena | Backend | Prompt |
|---|---|---|
| 1 | procedural | Forest silence, then a single gust of wind fades abruptly. |
| 2 | audioldm | Silent air, distant heartbeat pulse. |
| 3 | procedural | Silent forest; low buffalo growl fades into silence. |
| 4 | audioldm | Distant wind hums beneath deep breathing sound. Forest silence grows heavy and still. |
| 5 | audioldm | Soft wind rustling grass, distant forest breaths. |
