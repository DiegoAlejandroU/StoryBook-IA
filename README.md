# StoryBook IA

Aplicación local de IA generativa que, a partir de una **idea** y un **género**, genera un cuento
de **exactamente 5 escenas**. Cada escena incluye texto narrativo, ilustración original, narración
con voz sintética en español y ambientación sonora. Todos los modelos se ejecutan en el equipo
local; no se usan APIs de pago ni servicios de inferencia remotos.

Proyecto integrador · Electiva Ingeniería Aplicada – Inteligencia Artificial Generativa ·
Ingeniería de Sistemas · Universidad Santo Tomás, Seccional Tunja · 2026.

> **Estado:** Fase 0 (entorno, descarga de modelos y pruebas por modalidad). Este README se
> completa en la Fase 7 con capturas, tiempos medidos y solución de problemas.

## Requisitos

| | Mínimo | Equipo de referencia (pruebas y sustentación) |
|---|---|---|
| SO | Windows 10/11 x64 | Windows 11 Home x64 (build 26200) |
| GPU | NVIDIA con 4 GB de VRAM (Ampere o superior), driver con CUDA 13.2 | RTX 3050 Laptop 4 GB |
| RAM | 16 GB | 24 GB |
| Disco | 25 GB libres | — |
| Software | [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com), Git | — |

Python 3.12 instalado desde python.org (o `winget install Python.Python.3.12`). No se usa el Python que descarga `uv` porque el Control inteligente de aplicaciones de Windows puede bloquearlo. No se requiere ffmpeg.

## Instalación (PowerShell)

```powershell
# 1. Clonar y entrar al proyecto
git clone https://github.com/DiegoAlejandroU/StoryBook-IA.git
cd StoryBook-IA

# 2. Verificar la versión de CUDA que soporta el driver (línea "CUDA Version")
nvidia-smi
#    >= 13.2 -> continuar. 12.x -> actualizar el driver o usar el índice alternativo
#    comentado en pyproject.toml (torch 2.14 + cu126).

# 3. Crear el entorno con el Python 3.12 del sistema e instalar dependencias
#    (incluye PyTorch con CUDA)
uv venv --python-preference only-system --python 3.12
uv sync
uv run python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
#    Debe mostrar una versión de CUDA (no None) y True.

# 4. Configuración local
Copy-Item .env.example .env
#    Editar .env y pegar HF_TOKEN (solo necesario para Stable Audio, licencia gated).

# 5. Optimización de VRAM para Ollama (una sola vez; luego reiniciar Ollama)
[Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION", "1", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_KV_CACHE_TYPE", "q8_0", "User")

# 6. Descargar modelos (único paso con Internet). Ollama debe estar abierto.
uv run python scripts/download_models.py

# 7. Diagnóstico del entorno
uv run python scripts/check_env.py
```

Los pesos quedan en `models/` (excluida de git): `models/hf` (caché de Hugging Face) y
`models/piper` (voces). Los modelos de Ollama se guardan en la carpeta de Ollama del usuario.
El registro de repositorios, revisiones y licencias descargadas queda en
`docs/models_registry.json`.

### Licencias "gated"

Los modelos de Stable Audio exigen aceptar la *Stability AI Community License* en la página de
cada modelo, con la misma cuenta del token: `stabilityai/stable-audio-3-small-sfx` y
`stabilityai/stable-audio-open-1.0`. Sin ese paso, la aplicación funciona igual: el sonido se genera con
AudioLDM (`cvssp/audioldm`, no requiere token) y, si tampoco está, con la biblioteca CC0 y la
síntesis procedural.

## Prueba por modalidad (Fase 0)

```powershell
uv run python scripts/f0_hello.py all --ip-adapter
```

Genera en `outputs/f0/<fecha_hora>/` una Story Bible, imágenes, narración, ambiente sonoro y
métricas (WER, CLIP), además de `resumen.md` con tiempos y VRAM pico por etapa.

## Desarrollo

```powershell
uv run pytest           # pruebas (sin GPU)
uv run ruff check .     # lint
uv run ruff format .    # formato
```

## Licencia

Código bajo licencia MIT. Los modelos y recursos de terceros conservan sus licencias
(ver `MODELS.md` y `AUDIO_LICENSES.md`). Todo el contenido generado por la aplicación se
identifica como generado por IA.
