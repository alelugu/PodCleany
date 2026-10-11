@echo off
rem Instalación en Windows 10/11 (x64). Requiere Python 3.11-3.13 de python.org. No requiere compiladores: solo wheels.
setlocal
where py >nul 2>nul || (echo Instale Python 3.11+ desde https://www.python.org/downloads/ y marque "Add to PATH". & exit /b 1)
py -3 -m venv .venv || exit /b 1
call .venv\Scripts\python -m pip install --upgrade pip || exit /b 1
call .venv\Scripts\python -m pip install --only-binary=:all: -r requirements.txt || exit /b 1
echo.
set /p R=Descargar ahora los modelos de IA (aprox. 1.5 GB, requiere Internet)? [S/N]: 
if /i "%R%"=="S" (
  call .venv\Scripts\python -m pip install --only-binary=:all: -r requirements-ml.txt || echo No se pudieron instalar las librerias de IA.
  call .venv\Scripts\python scripts\fetch_models.py || echo No se pudieron descargar los modelos; reintente luego con scripts\fetch_models.py
)
echo.
echo Listo. Para ver una demostracion sin modelos: demo_windows.bat
echo Para usar la aplicacion: start_windows.bat
