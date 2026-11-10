<#
  StoryBook IA - Instalacion en Windows (tareas 0.1, 0.5 y 0.6 de docs/PROGRESO.md)

  Uso (PowerShell, desde la carpeta del proyecto):
      powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
  Solo un paso:
      powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1 -Paso git
      powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1 -Paso entorno
      powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1 -Paso modelos
  Tarea 1.4 (generaciones reales del LLM; el 4B ya va 100 % en GPU por configs/default.yaml):
      powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1 -Paso f1 -Generaciones 10
  Comparacion con Qwen3 8B (perfil calidad; evidencias con sufijo _calidad):
      powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1 -Paso f1 -Generaciones 3 -Perfil calidad

  Todo queda registrado en docs\evidencias\setup_windows.log (UTF-8).
  El script NO pide ni muestra el token de Hugging Face: se lee de .env si existe.
  Texto sin tildes a proposito (compatibilidad con Windows PowerShell 5.1).
#>
param(
    [ValidateSet("todo", "git", "entorno", "modelos", "f1")]
    [string]$Paso = "todo",
    [int]$Generaciones = 10,
    [int]$NumGpu = -1,
    [ValidateSet("rapido", "calidad")]
    [string]$Perfil = "rapido",
    [switch]$SinPausa
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:UV_NO_PROGRESS = "1"

$Raiz = Split-Path -Parent $PSScriptRoot
Set-Location $Raiz
$Evid = Join-Path $Raiz "docs\evidencias"
New-Item -ItemType Directory -Force -Path $Evid | Out-Null
$Log = Join-Path $Evid "setup_windows.log"

function Escribir([string]$Texto, [string]$Color = "Gray") {
    Write-Host $Texto -ForegroundColor $Color
    Add-Content -Path $Log -Value $Texto -Encoding UTF8
}

function Titulo([string]$Texto) {
    $linea = "=" * 78
    Escribir "" ; Escribir $linea "Cyan"
    Escribir ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Texto) "Cyan"
    Escribir $linea "Cyan"
}

# Ejecuta un comando nativo, muestra y registra su salida, y devuelve el codigo de salida.
function Ejecutar([string]$Exe, [string[]]$Argumentos, [string]$Copia = "") {
    Escribir ("> {0} {1}" -f $Exe, ($Argumentos -join " ")) "Yellow"
    & $Exe @Argumentos 2>&1 | ForEach-Object {
        $l = "$_"
        Write-Host $l
        Add-Content -Path $Log -Value $l -Encoding UTF8
        if ($Copia) { Add-Content -Path $Copia -Value $l -Encoding UTF8 }
    }
    $codigo = $LASTEXITCODE
    if ($null -eq $codigo) { $codigo = 0 }
    Escribir ("  (codigo de salida: {0})" -f $codigo) "DarkGray"
    return $codigo
}

function Requiere([string]$Comando, [string]$Ayuda) {
    if (-not (Get-Command $Comando -ErrorAction SilentlyContinue)) {
        Escribir ("FALTA '{0}'. {1}" -f $Comando, $Ayuda) "Red"
        return $false
    }
    return $true
}

function Fin([int]$Codigo) {
    Escribir ""
    if ($Codigo -eq 0) {
        Escribir "LISTO. Avisale a Claude para que revise docs\evidencias y actualice docs\PROGRESO.md." "Green"
    } else {
        Escribir "Se detuvo con errores. Avisale a Claude: el detalle esta en docs\evidencias\setup_windows.log." "Red"
    }
    if (-not $SinPausa) { Read-Host "Presiona Enter para cerrar" | Out-Null }
    exit $Codigo
}

# ---------------------------------------------------------------------------------------
# Tarea 0.1 - git
# ---------------------------------------------------------------------------------------
function Paso-Git {
    Titulo "Tarea 0.1 - Git: repositorio local, primer commit y push"
    if (-not (Requiere "git" "Instalalo con: winget install Git.Git  (y abre una PowerShell nueva)")) { return 1 }

    if (-not (Test-Path ".git")) {
        if ((Ejecutar "git" @("init", "-b", "main")) -ne 0) { return 1 }
    } else {
        Escribir "El repositorio git ya existe; se reutiliza." "DarkGray"
    }
    Ejecutar "git" @("config", "core.autocrlf", "false") | Out-Null

    $remoto = (& git remote 2>$null)
    if ($remoto -notcontains "origin") {
        Ejecutar "git" @("remote", "add", "origin", "https://github.com/DiegoAlejandroU/StoryBook-IA.git") | Out-Null
    }

    $correo = (& git config user.email 2>$null)
    if (-not $correo) {
        Escribir "Git no tiene configurado tu nombre y correo (se usan como autor de los commits)." "Yellow"
        $nombre = Read-Host "Tu nombre para los commits (Enter = Diego Alejandro Urbano Pira)"
        if (-not $nombre) { $nombre = "Diego Alejandro Urbano Pira" }
        $correo = Read-Host "Tu correo de GitHub"
        Ejecutar "git" @("config", "user.name", $nombre) | Out-Null
        Ejecutar "git" @("config", "user.email", $correo) | Out-Null
    }

    if ((Ejecutar "git" @("add", "-A")) -ne 0) { return 1 }

    # Seguridad: nada de pesos, entornos, secretos ni el enunciado en el repositorio.
    $prohibidos = @("^\.cache/", "^models/", "^\.venv/", "^\.env$", "^docs/enunciado/", "^outputs/", "\.safetensors$", "\.gguf$", "\.onnx$")
    $preparados = (& git diff --cached --name-only 2>$null)
    $malos = @()
    foreach ($f in $preparados) { foreach ($p in $prohibidos) { if ($f -match $p) { $malos += $f } } }
    if ($malos.Count -gt 0) {
        Escribir "ALTO: estos archivos no deben subirse y estan preparados para commit:" "Red"
        $malos | ForEach-Object { Escribir "  $_" "Red" }
        Ejecutar "git" @("reset") | Out-Null
        return 1
    }
    Escribir ("Archivos para el commit: {0}" -f @($preparados).Count) "DarkGray"

    $pendiente = (& git status --porcelain 2>$null)
    if ($pendiente) {
        & git rev-parse --verify HEAD 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $titulo = "chore: actualizar archivos del proyecto" } else { $titulo = "chore: estructura inicial del proyecto (Fase 0)" }
        if ($Paso -eq "f1") { $titulo = "chore: codigo usado en las generaciones reales de F1 (tarea 1.4)" }
        $coautor = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
        if ((Ejecutar "git" @("commit", "-m", $titulo, "-m", $coautor)) -ne 0) { return 1 }
    } else {
        Escribir "No hay cambios nuevos para commit." "DarkGray"
    }

    Escribir "Subiendo a GitHub. Si se abre el navegador, inicia sesion con tu cuenta de GitHub." "Yellow"
    if ((Ejecutar "git" @("push", "-u", "origin", "main")) -ne 0) {
        Escribir "AVISO: el push fallo. El commit quedo local; se puede reintentar con: git push -u origin main" "Yellow"
    }
    return 0
}

# ---------------------------------------------------------------------------------------
# Tarea 0.5 - entorno
# ---------------------------------------------------------------------------------------
function Paso-Entorno {
    Titulo "Tarea 0.5 - Entorno: driver, Python 3.12, uv sync, PyTorch con CUDA y tests"
    if (-not (Requiere "uv" "Instalalo con: irm https://astral.sh/uv/install.ps1 | iex")) { return 1 }
    if (-not (Requiere "nvidia-smi" "Instala o actualiza el driver NVIDIA desde la NVIDIA App.")) { return 1 }

    $smi = Join-Path $Evid "nvidia-smi.txt"
    if (Test-Path $smi) { Remove-Item $smi }
    if ((Ejecutar "nvidia-smi" @() $smi) -ne 0) { return 1 }
    $texto = Get-Content $smi -Raw
    # Drivers antiguos: "CUDA Version: 13.2"; drivers recientes (6xx): "CUDA UMD Version: 13.4".
    $m = [regex]::Match($texto, "CUDA(?:\s+UMD)?\s+Version:\s*([0-9]+)\.([0-9]+)")
    if (-not $m.Success) { Escribir "No se pudo leer la version de CUDA de nvidia-smi." "Red"; return 1 }
    $cuda = [double]("{0}.{1}" -f $m.Groups[1].Value, $m.Groups[2].Value)
    Escribir ("Version maxima de CUDA del driver: {0}" -f $cuda) "Green"
    if ($cuda -lt 13.2) {
        Escribir "El driver soporta CUDA $cuda, menor a 13.2 (requerido por torch 2.15 + cu132)." "Red"
        Escribir "Solucion recomendada: actualiza el driver con la NVIDIA App, reinicia y vuelve a ejecutar este script." "Red"
        Escribir "Alternativa: usar el bloque comentado cu126 (torch 2.14) de pyproject.toml; pidele a Claude que lo active." "Red"
        return 1
    }

    $libre = [math]::Round((Get-PSDrive -Name ((Get-Location).Drive.Name)).Free / 1GB, 1)
    Escribir ("Espacio libre en disco: {0} GB (se necesitan ~25 GB para entorno + modelos)" -f $libre)
    if ($libre -lt 25) { Escribir "AVISO: poco espacio libre; la descarga de modelos puede fallar." "Yellow" }

    if (-not (Test-Path ".venv")) {
        if ((Ejecutar "uv" @("venv", "--python-preference", "only-system", "--python", "3.12")) -ne 0) {
            Escribir "No se encontro Python 3.12 del sistema. Instalalo con: winget install Python.Python.3.12" "Red"
            return 1
        }
    } else {
        Escribir "El entorno .venv ya existe; se reutiliza." "DarkGray"
    }
    if ((Ejecutar "uv" @("sync", "--python-preference", "only-system")) -ne 0) { return 1 }

    $torch = Join-Path $Evid "torch_cuda.txt"
    if (Test-Path $torch) { Remove-Item $torch }
    $py = "import torch; print('torch', torch.__version__); print('cuda', torch.version.cuda); print('gpu', torch.cuda.is_available()); print('nombre', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')"
    Ejecutar "uv" @("run", "python", "-c", $py) $torch | Out-Null
    $t = Get-Content $torch -Raw
    if ($t -match "4551" -or $t -match "Control de aplicaciones" -or $t -match "Application Control") {
        Escribir "Windows bloqueo las DLL de PyTorch: el Control inteligente de aplicaciones esta activado." "Red"
        Escribir "Desactivalo en: Seguridad de Windows > Control de aplicaciones y navegador >" "Red"
        Escribir "  Configuracion de Control inteligente de aplicaciones > Desactivado. Luego ejecuta:" "Red"
        Escribir "  powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1 -Paso entorno" "Red"
        return 1
    }
    if ($t -notmatch "gpu True") {
        if ($t -match "cuda None") {
            Escribir "Se instalo una version de PyTorch solo CPU (cuda None). Revisa el indice de PyTorch en pyproject.toml." "Red"
        } else {
            Escribir "PyTorch no pudo usar la GPU. Revisa docs\evidencias\torch_cuda.txt." "Red"
        }
        return 1
    }
    Escribir "PyTorch ve la GPU con CUDA." "Green"

    $tests = Join-Path $Evid "pytest.txt"
    if (Test-Path $tests) { Remove-Item $tests }
    if ((Ejecutar "uv" @("run", "pytest", "-q") $tests) -ne 0) { Escribir "Hay tests en rojo (ver docs\evidencias\pytest.txt)." "Yellow" }

    $env1 = Join-Path $Evid "check_env_antes_de_modelos.txt"
    if (Test-Path $env1) { Remove-Item $env1 }
    Ejecutar "uv" @("run", "python", "scripts/check_env.py", "--profile", "rapido") $env1 | Out-Null
    Escribir "check_env antes de descargar modelos: es normal que marque FALLO en modelos y Ollama." "DarkGray"
    return 0
}

# ---------------------------------------------------------------------------------------
# Tarea 0.6 - modelos y prueba por modalidad
# ---------------------------------------------------------------------------------------
function Esperar-Ollama([int]$Segundos = 90) {
    for ($i = 0; $i -lt $Segundos; $i += 3) {
        try {
            $v = Invoke-RestMethod -Uri "http://localhost:11434/api/version" -TimeoutSec 3
            Escribir ("Ollama responde (version {0})." -f $v.version) "Green"
            return $true
        } catch { Start-Sleep -Seconds 3 }
    }
    return $false
}

function Paso-Modelos {
    Titulo "Tarea 0.6 - Ollama, descarga de modelos y prueba por modalidad (f0_hello)"
    if (-not (Test-Path ".venv")) { Escribir "Primero ejecuta el paso 'entorno'." "Red"; return 1 }

    # Variables de Ollama para ahorrar VRAM del KV cache (persisten para el usuario).
    [Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION", "1", "User")
    [Environment]::SetEnvironmentVariable("OLLAMA_KV_CACHE_TYPE", "q8_0", "User")
    $env:OLLAMA_FLASH_ATTENTION = "1"
    $env:OLLAMA_KV_CACHE_TYPE = "q8_0"
    Escribir "Variables OLLAMA_FLASH_ATTENTION=1 y OLLAMA_KV_CACHE_TYPE=q8_0 configuradas." "Green"

    # Reiniciar Ollama para que tome las variables.
    Get-Process -Name "ollama*" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    $app = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
    if (Test-Path $app) {
        Start-Process -FilePath $app
    } elseif (Get-Command "ollama" -ErrorAction SilentlyContinue) {
        Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    } else {
        Escribir "No se encontro Ollama. Instalalo desde https://ollama.com y vuelve a ejecutar." "Red"
        return 1
    }
    if (-not (Esperar-Ollama)) { Escribir "Ollama no respondio en http://localhost:11434." "Red"; return 1 }

    # Token de Hugging Face (solo para Stable Audio, licencia gated). No se muestra.
    if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Escribir "Se creo .env a partir de .env.example." "DarkGray" }
    $tieneToken = (Select-String -Path ".env" -Pattern "^\s*HF_TOKEN\s*=\s*\S+" -Quiet)
    $args1 = @("run", "python", "scripts/download_models.py")
    if (-not $tieneToken) {
        Escribir "No hay HF_TOKEN en .env: se omite Stable Audio; el sonido generado sera con AudioLDM (no requiere token)." "Yellow"
        Escribir "Para incluirlo: acepta la licencia en huggingface.co/stabilityai/stable-audio-3-small-sfx y" "Yellow"
        Escribir "huggingface.co/stabilityai/stable-audio-open-1.0, pon HF_TOKEN=... en .env y ejecuta: -Paso modelos" "Yellow"
        $args1 += "--skip-gated"
    }
    $desc = Join-Path $Evid "download_models.txt"
    if (Test-Path $desc) { Remove-Item $desc }
    if ((Ejecutar "uv" $args1 $desc) -ne 0) { Escribir "La descarga reporto errores (ver docs\evidencias\download_models.txt). Se continua con lo disponible." "Yellow" }

    $env2 = Join-Path $Evid "check_env.txt"
    if (Test-Path $env2) { Remove-Item $env2 }
    Ejecutar "uv" @("run", "python", "scripts/check_env.py", "--profile", "rapido") $env2 | Out-Null

    $hola = Join-Path $Evid "f0_hello.txt"
    if (Test-Path $hola) { Remove-Item $hola }
    Ejecutar "uv" @("run", "python", "scripts/f0_hello.py", "all", "--ip-adapter") $hola | Out-Null

    $ultimo = Get-ChildItem -Path "outputs\f0" -Directory -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($ultimo -and (Test-Path (Join-Path $ultimo.FullName "resumen.md"))) {
        Copy-Item (Join-Path $ultimo.FullName "resumen.md") (Join-Path $Evid "f0_resumen.md") -Force
        Escribir ("Resumen de la prueba copiado a docs\evidencias\f0_resumen.md (sesion {0})." -f $ultimo.Name) "Green"
    } else {
        Escribir "No se encontro resumen.md de f0_hello (ver docs\evidencias\f0_hello.txt)." "Yellow"
    }
    return 0
}

# ---------------------------------------------------------------------------------------
# Commit de evidencias (uv.lock, docs/evidencias, registro de modelos) al final de cada paso
# ---------------------------------------------------------------------------------------
function Guardar-Evidencias([string]$Mensaje) {
    if (-not (Test-Path ".git")) { return 0 }
    if (-not (Get-Command "git" -ErrorAction SilentlyContinue)) { return 0 }
    $rutas = @("docs/evidencias", "uv.lock", "docs/models_registry.json") | Where-Object { Test-Path $_ }
    if (-not $rutas) { return 0 }
    & git add -- @rutas 2>$null | Out-Null
    & git diff --cached --quiet 2>$null
    if ($LASTEXITCODE -eq 0) { return 0 }
    Titulo "Guardando evidencias en git"
    $coautor = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
    if ((Ejecutar "git" @("commit", "-m", $Mensaje, "-m", $coautor)) -ne 0) { return 1 }
    if ((Ejecutar "git" @("push")) -ne 0) {
        Escribir "AVISO: el push de evidencias fallo; quedaron en un commit local." "Yellow"
    }
    return 0
}

# ---------------------------------------------------------------------------------------
Titulo ("StoryBook IA - setup_windows.ps1 (paso: {0}) en {1}" -f $Paso, $Raiz)

$codigo = 0
# f1 tambien hace commit del codigo antes de generar: la evidencia debe corresponder a un commit.
if ($Paso -in @("todo", "git", "f1")) { $codigo = Paso-Git; if ($codigo -ne 0) { Fin $codigo } }
if ($Paso -in @("todo", "entorno")) {
    $codigo = Paso-Entorno
    Guardar-Evidencias "chore: evidencias de instalacion del entorno (tarea 0.5)" | Out-Null
    if ($codigo -ne 0) { Fin $codigo }
}
if ($Paso -in @("todo", "modelos")) {
    $codigo = Paso-Modelos
    Guardar-Evidencias "chore: evidencias de modelos y prueba por modalidad (tarea 0.6)" | Out-Null
    if ($codigo -ne 0) { Fin $codigo }
}
if ($Paso -eq "f1") {
    Titulo ("Tarea 1.4 - {0} generaciones reales de la Story Bible (perfil {1})" -f $Generaciones, $Perfil)
    $argsF1 = @("run", "python", "scripts/f1_generaciones.py", "--n", "$Generaciones", "--perfil", $Perfil)
    if ($NumGpu -ge 0) { $argsF1 += @("--num-gpu", "$NumGpu") }
    $sufijo = if ($Perfil -eq "rapido") { "" } else { "_$Perfil" }
    $salidaF1 = Join-Path $Evid ("f1_generaciones{0}.txt" -f $sufijo)
    if (Test-Path $salidaF1) { Remove-Item $salidaF1 }
    $codigo = Ejecutar "uv" $argsF1 $salidaF1
    Guardar-Evidencias "chore: evidencias de generaciones reales del LLM (tarea 1.4)" | Out-Null
    if ($codigo -ne 0) { Fin $codigo }
}
Fin 0
