#!/usr/bin/env bash
# Instalación en macOS (Intel y Apple Silicon). Requiere Python 3.11-3.13 (python.org o Homebrew). Solo wheels.
set -euo pipefail
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Instale Python 3.11+ (https://www.python.org/downloads/macos/)"; exit 1; }
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --only-binary=:all: -r requirements.txt
echo
read -r -p "¿Descargar ahora los modelos de IA (≈1.5 GB, requiere Internet)? [s/N] " R
if [[ "$R" =~ ^[sSyY]$ ]]; then
  .venv/bin/python -m pip install --only-binary=:all: -r requirements-ml.txt || echo "No se pudieron instalar las librerías de IA."
  .venv/bin/python scripts/fetch_models.py || echo "No se pudieron descargar los modelos; reintente con scripts/fetch_models.py"
fi
echo
echo "Listo ($(uname -m)). Demostración sin modelos: ./demo_macos.sh   ·   Aplicación: ./start_macos.sh"
