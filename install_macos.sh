#!/usr/bin/env bash
# Instalación en macOS (Intel y Apple Silicon). Requiere Python 3.11-3.13 (python.org o Homebrew). Solo wheels.
set -euo pipefail
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Instale Python 3.11+ (https://www.python.org/downloads/macos/)"; exit 1; }
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --only-binary=:all: -r requirements.txt
echo
echo "Núcleo instalado ($(uname -m)). Para modelos locales, con conexión, ejecute UNA vez:"
echo "  .venv/bin/python -m pip install --only-binary=:all: -r requirements-ml.txt"
echo "  .venv/bin/python scripts/fetch_models.py"
echo "Para iniciar: ./start_macos.sh"
