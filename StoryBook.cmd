@echo off
rem StoryBook IA - lanzador de doble clic (tarea 5.2).
rem   StoryBook.cmd        abre la app con los modelos reales (necesita Ollama).
rem   StoryBook.cmd mock   abre la app en modo simulado (sin GPU ni Ollama).
setlocal
cd /d "%~dp0"
title StoryBook IA

where uv >nul 2>nul
if errorlevel 1 (
    echo No se encontro uv. Instalalo con:
    echo   powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
    pause
    exit /b 1
)
if not exist ".venv" (
    echo Falta el entorno. Ejecuta primero:
    echo   powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
    pause
    exit /b 1
)

set "MODO=%~1"
if /i "%MODO%"=="mock" goto abrir

rem Ollama: si no responde, se abre y se espera hasta 60 s.
powershell -NoProfile -Command "try { Invoke-RestMethod -Uri http://localhost:11434/api/version -TimeoutSec 3 | Out-Null; exit 0 } catch { exit 1 }"
if not errorlevel 1 goto abrir
echo Abriendo Ollama...
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" (
    start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
) else (
    start "" /min ollama serve
)
powershell -NoProfile -Command "for ($i = 0; $i -lt 20; $i++) { try { Invoke-RestMethod -Uri http://localhost:11434/api/version -TimeoutSec 3 | Out-Null; exit 0 } catch { Start-Sleep -Seconds 3 } }; exit 1"
if errorlevel 1 (
    echo Ollama no respondio en http://localhost:11434. Abrelo manualmente y vuelve a intentar.
    pause
    exit /b 1
)

:abrir
rem Abre el navegador cuando la app responda (Streamlit corre en modo headless).
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "for ($i = 0; $i -lt 60; $i++) { try { Invoke-WebRequest -Uri http://localhost:8501/_stcore/health -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process 'http://localhost:8501'; exit } catch { Start-Sleep -Seconds 1 } }"
echo.
echo StoryBook IA se esta abriendo en el navegador: http://localhost:8501
echo Para cerrar la app, cierra esta ventana.
echo.
if /i "%MODO%"=="mock" (
    uv run streamlit run app/streamlit_app.py -- --mock
) else (
    uv run streamlit run app/streamlit_app.py
)
pause
