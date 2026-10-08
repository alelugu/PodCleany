# Instalación y arranque

Requisito: Python 3.11–3.13 (python.org). **No** hace falta compilador: todo se instala con wheels (`--only-binary=:all:`); ffmpeg viene empaquetado (`imageio-ffmpeg`).

## Windows 10/11 x64
1. Instale Python marcando «Add to PATH». 2. Doble clic a `install_windows.bat`. 3. (Una vez, con conexión) modelos: ver abajo. 4. `start_windows.bat`.

## macOS (Intel o Apple Silicon)
1. `./install_macos.sh` 2. (Una vez, con conexión) modelos. 3. `./start_macos.sh`.

## Modelos locales (provisión inicial, separada de la operación)
```
.venv/bin/python -m pip install --only-binary=:all: -r requirements-ml.txt     # Windows: .venv\Scripts\python
.venv/bin/python scripts/fetch_models.py
```
Descarga `Systran/faster-whisper-small` y `Qwen/Qwen2.5-1.5B-Instruct-GGUF` (q4_k_m) a `<datos>/models`. Los modelos por defecto son una **propuesta** a confirmar (docs/LICENCIAS.md). Tras esto la operación no descarga nada de modelos.

## Configuración
`<datos>/config.json` (opcional): `port`, `block_seconds`, `crossfade_ms`, `threshold_low/high`, rutas de modelos… (ver `podcleany/config.py`). Variables: `PODCLEANY_HOME`, `PODCLEANY_FFMPEG`.

## Solución de problemas
- «No se pudo conectar…»: revise Internet; solo el episodio se descarga de la red.
- Aviso «faster-whisper no disponible»: aún no se han provisionado modelos; las regiones sin huella no se transcriben.
- Puerto ocupado: cambie `port` en `config.json`.
- Logs por episodio: `<datos>/logs/episode_<id>.log`.
