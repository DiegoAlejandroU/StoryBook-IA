<#
Quita a Claude como coautor de TODO el historial de git y lo sube a GitHub.

Los commits hechos por setup_windows.ps1 hasta el 10 nov llevaban la linea
"Co-Authored-By: Claude ..."; por eso GitHub mostraba a Claude como colaborador. Este script:
  1. Guarda los cambios pendientes (commit sin coautor, via setup_windows.ps1 -Paso git).
  2. Crea la rama local "respaldo-antes-de-quitar-coautor" (copia de seguridad).
  3. Reescribe los mensajes de main con git filter-branch, quitando esas lineas
     (scripts/filtro_mensaje_commit.py). El autor de cada commit sigue siendo Diego.
  4. Verifica que no quede ninguna y sube main con --force-with-lease.

Reescribe el historial: los hashes de los commits cambian. Si algo sale mal antes del push:
    git reset --hard respaldo-antes-de-quitar-coautor

Uso (PowerShell, desde la carpeta del proyecto):
    powershell -ExecutionPolicy Bypass -File .\scripts\quitar_coautor.ps1
#>
param([switch]$SinPausa)

$Raiz = Split-Path -Parent $PSScriptRoot
Set-Location $Raiz

function Terminar([int]$Codigo, [string]$Mensaje, [string]$Color = "Green") {
    Write-Host ""
    Write-Host $Mensaje -ForegroundColor $Color
    if (-not $SinPausa) { Read-Host "Presiona Enter para cerrar" | Out-Null }
    exit $Codigo
}

function Contar-Coautor([string]$Rama) {
    $mensajes = & git log $Rama --format=%B 2>$null
    return @($mensajes | Select-String -Pattern "^\s*(Co-Authored-By:\s*Claude|Claude-Session:)").Count
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Terminar 1 "No se encontro git." "Red" }
$python = Join-Path $Raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { Terminar 1 "Falta el entorno .venv (setup_windows.ps1 -Paso entorno)." "Red" }

Write-Host "1. Guardando los cambios pendientes (commit sin coautor)..." -ForegroundColor Cyan
& powershell -ExecutionPolicy Bypass -File (Join-Path $Raiz "scripts\setup_windows.ps1") -Paso git -SinPausa
if ($LASTEXITCODE -ne 0) { Terminar 1 "El paso git fallo; revisa docs\evidencias\setup_windows.log." "Red" }
if (& git status --porcelain) { Terminar 1 "Quedan cambios sin commit; no se reescribe el historial." "Red" }

$antes = Contar-Coautor "main"
Write-Host ("Mensajes de commit con Claude como coautor: {0}" -f $antes)
if ($antes -eq 0) { Terminar 0 "No hay nada que quitar: el historial ya esta limpio." }

Write-Host "2. Copia de seguridad: rama local respaldo-antes-de-quitar-coautor" -ForegroundColor Cyan
& git branch -f respaldo-antes-de-quitar-coautor main
if ($LASTEXITCODE -ne 0) { Terminar 1 "No se pudo crear la rama de respaldo." "Red" }

Write-Host "3. Reescribiendo los mensajes de commit (puede tardar un minuto)..." -ForegroundColor Cyan
$filtro = "'{0}' '{1}'" -f ($python -replace "\\", "/"), ((Join-Path $Raiz "scripts\filtro_mensaje_commit.py") -replace "\\", "/")
$env:FILTER_BRANCH_SQUELCH_WARNING = "1"
& git filter-branch -f --msg-filter $filtro -- main
if ($LASTEXITCODE -ne 0) {
    Terminar 1 "filter-branch fallo. Para volver atras: git reset --hard respaldo-antes-de-quitar-coautor" "Red"
}

$despues = Contar-Coautor "main"
if ($despues -ne 0) {
    Terminar 1 ("Aun quedan {0} mensajes con coautor. Para volver atras: git reset --hard respaldo-antes-de-quitar-coautor" -f $despues) "Red"
}
Write-Host ("Listo en local: {0} mensajes limpiados, 0 restantes." -f $antes) -ForegroundColor Green

Write-Host "4. Subiendo el historial limpio a GitHub (--force-with-lease)..." -ForegroundColor Cyan
& git push --force-with-lease origin main
if ($LASTEXITCODE -ne 0) {
    Terminar 1 "El push fallo. El historial local ya esta limpio; reintenta con: git push --force-with-lease origin main" "Yellow"
}
Terminar 0 "LISTO. Claude ya no aparece como coautor. GitHub puede tardar unos minutos en actualizar la lista de colaboradores."
