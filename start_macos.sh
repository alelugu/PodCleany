#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Aún no está instalado: ejecutando ./install_macos.sh"; ./install_macos.sh; }
exec .venv/bin/python -m podcleany start
