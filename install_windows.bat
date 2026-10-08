@echo off
rem Instalación en Windows 10/11 (x64). Requiere Python 3.11-3.13 de python.org. No requiere compiladores: solo wheels.
setlocal
where py >nul 2>nul || (echo Instale Python 3.11+ desde https://www.python.org/downloads/ y marque "Add to PATH". & exit /b 1)
py -3 -m venv .venv || exit /b 1
call .venv\Scripts\python -m pip install --upgrade pip || exit /b 1
call .venv\Scripts\python -m pip install --only-binary=:all: -r requirements.txt || exit /b 1
echo.
echo Nucleo instalado. Para modelos locales (Whisper + LLM), con conexion, ejecute UNA vez:
echo   .venv\Scripts\python -m pip install --only-binary=:all: -r requirements-ml.txt
echo   .venv\Scripts\python scripts\fetch_models.py
echo Para iniciar: start_windows.bat
