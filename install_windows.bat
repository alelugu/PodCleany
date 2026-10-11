@echo off
cd /d "%~dp0"
echo === Instalacion de PodCleany (Windows) ===
rem Busca Python: primero "py", luego "python"
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" where python >nul 2>nul && set PY=python
if "%PY%"=="" (
  echo.
  echo No se encontro Python. Instale Python 3.12 o 3.13 desde https://www.python.org/downloads/
  echo IMPORTANTE: en el instalador marque "Add python.exe to PATH". Luego vuelva a ejecutar este archivo.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  %PY% -m venv .venv || goto :fallo
)
call .venv\Scripts\python -m pip install --upgrade pip || goto :fallo
call .venv\Scripts\python -m pip install --only-binary=:all: -r requirements.txt || goto :fallo
echo.
set /p R=Descargar ahora los modelos de IA (aprox. 1.5 GB, requiere Internet)? Escriba S o N: 
if /i "%R%"=="S" (
  call .venv\Scripts\python -m pip install --only-binary=:all: -r requirements-ml.txt || echo No se pudieron instalar las librerias de IA.
  call .venv\Scripts\python scripts\fetch_models.py || echo No se pudieron descargar los modelos; reintente luego con scripts\fetch_models.py
)
echo.
echo LISTO. Para ver una demostracion sin modelos: demo_windows.bat
echo Para usar la aplicacion: start_windows.bat
pause
exit /b 0
:fallo
echo.
echo *** La instalacion fallo. Copie el mensaje de error de arriba y envielo. ***
pause
exit /b 1
