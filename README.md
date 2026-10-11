# PodCleany

Eliminación **local** de anuncios de podcasts: pegue el enlace de un episodio o RSS, revise la línea de tiempo,
genere el audio sin anuncios y descárguelo. Todo se procesa en su equipo; durante la operación la única conexión
saliente es la descarga del episodio desde el host del podcast.

- Plataformas de la primera entrega: **Windows 10/11 (x64)** y **macOS (Intel y Apple Silicon)**, una sola base de código. Ubuntu: diferido por indicación de la solicitante.
- Estado real de la entrega, qué está verificado y qué no: **[docs/PRUEBAS.md](docs/PRUEBAS.md)** y **[docs/PENDIENTES.md](docs/PENDIENTES.md)**. Léalos antes de dar por aceptado nada.

## Inicio rápido
| | Windows | macOS |
|---|---|---|
| Instalar | `install_windows.bat` | `./install_macos.sh` |
| Iniciar | `start_windows.bat` | `./start_macos.sh` |


Modelos (Whisper + LLM): se provisionan una sola vez, con conexión, con `scripts/fetch_models.py`; sin ellos el sistema arranca pero avisa y usa un clasificador heurístico de respaldo y no transcribe.

**Demostración sin modelos** (recomendada para la primera prueba): `demo_windows.bat` / `./demo_macos.sh` → [docs/DEMO.md](docs/DEMO.md).
Los instaladores ofrecen descargar los modelos de IA (Hugging Face, ~1.5 GB) al final; también puede hacerlo desde el notebook `00a_instalar_modelos`.

## Arquitectura (resumen)
`python -m podcleany start` lanza **dos procesos independientes**: la Local API (FastAPI, 127.0.0.1) y el worker. Se coordinan solo por la tabla `jobs` de SQLite (WAL). Detalle y diagrama: [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md). Datos: [docs/DATOS.md](docs/DATOS.md).

## Notebooks
`notebooks/00…07` construyen, explican y prueban cada etapa; `06` es la integración (API + worker como procesos separados). Orden y reglas: [docs/NOTEBOOKS.md](docs/NOTEBOOKS.md). Se regeneran con `python scripts/make_notebooks.py`.

## Pruebas
`pip install -r requirements-dev.txt && python -m pytest` (flujo E.6 completo con servidor HTTP local, API y worker reales; reclamo atómico multiproceso; Range 206; SSE; migraciones; crossfade). CI en `.github/workflows/ci.yml` (Windows, macOS Intel, macOS Apple Silicon).

## Aviso de derechos del contenido
Los podcasts y sus anuncios están protegidos por derechos de autor y por los términos de cada publicador. Use PodCleany solo con contenido que tenga derecho a descargar y modificar para uso personal. No redistribuya el audio resultante. Esta herramienta no exporta a AntennaPod ni envía contenido a terceros. Las condiciones legales del acuerdo de servicios prevalecen sobre este aviso.
