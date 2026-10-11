@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Aun no esta instalado. Se ejecutara primero la instalacion...
  call install_windows.bat
)
if not exist .venv\Scripts\python.exe (
  echo No se pudo instalar; no se puede iniciar la demostracion.
  pause
  exit /b 1
)
.venv\Scripts\python -m podcleany demo
echo.
echo PodCleany se cerro. Si vio un error arriba, copielo y envielo.
pause
