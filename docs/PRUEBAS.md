# Pruebas: qué se ejecutó y qué NO

Entorno de desarrollo de esta entrega: **Linux x86-64, Python 3.13, ffmpeg del sistema**, sin acceso a Hugging Face. **No se ejecutó nada en Windows ni macOS** (ni Intel ni Apple Silicon); no hay evidencia propia de esas plataformas. El checklist D de esas plataformas está **sin completar**. Ubuntu: diferido por indicación de la solicitante (se usó Linux solo para desarrollar).

## Automatizadas (`python -m pytest`: 9 pruebas, todas pasan en Linux)
| Caso | Resultado |
|---|---|
| Huella reconocida tras ida y vuelta a MP3; sin falsos positivos con habla distinta | OK |
| Normalización por bloques por pipes; lectura de rango entre bloques | OK |
| Crossfade: duración esperada, original intacto, sin clipping ni clic en el empalme | OK |
| `keep_intervals` (fusión y tramos mínimos) | OK |
| SQLite WAL, 5 tablas, migraciones idempotentes, deduplicación de jobs | OK |
| Reclamo atómico: 4 procesos, 60 jobs, cada uno reclamado exactamente una vez | OK |
| Job `running` sin latido se re-encola (fallo del worker) | OK |
| Flujo E.6 completo: 202+dedupe, SSE, worker, rama «anuncio fuerte → quitar», rama «entre umbrales → revisión», protección de intro, confirmación/ajuste/deshacer, aprendizaje de huellas, render, Range 206/416, descarga con Content-Disposition, duración del archivo descargado = resultado, resultado obsoleto tras editar | OK |
| Episodio 2: el anuncio se reconoce por huella **sin transcribirse** y la intro protegida no se transcribe ni se elimina | OK |
| Render y feedback sin servidor de origen (sin red) | OK |
| Fallo de descarga (404): job `failed` con mensaje claro; API sigue viva; se puede reintentar | OK |
| Prueba manual con Chromium (Playwright) sobre `python -m podcleany start` real: flujo UI completo y descarga reproducible por ffmpeg; el worker fue matado y reiniciado por el supervisor con la API disponible | OK (una vez, Linux) |
| Notebooks 00–06 ejecutados desde kernel limpio con nbclient | OK (Linux) |

## Limitaciones de estas pruebas (importante)
- El audio es **sintético** (armónicos y jingles), no voz real; la transcripción en las pruebas es **simulada** (`tests/fakes.py`) porque no se pudieron descargar modelos. **faster-whisper y llama.cpp no se ejecutaron**: el código de esos backends (`podcleany/models.py`) no está probado.
- Por tanto **no hay métricas reales de detección ni de eliminación incorrecta**; `python -m podcleany.report` está listo, pero falta un corpus etiquetado y acordar regla/denominador.
- Única medición de rendimiento: episodio sintético de 46 min, sin modelos: 7.4 s, RAM pico 251 MB, CPU medio ~78 %, sin GPU (Linux, no representativo). Con Whisper/LLM los tiempos y la RAM serán muy distintos.
- No se midieron conexiones salientes con herramienta de red; por diseño el único código con red es `feeds.py` y `scripts/fetch_models.py` (verificado por lectura y porque render/feedback funcionan con el servidor apagado).
- No se verificó la audibilidad de los cortes con oído humano; solo ausencia de clipping/saltos numéricos.
- CI de GitHub Actions (Windows, macOS 13 Intel, macOS 14 Apple Silicon) está definido pero **no se ha ejecutado**; es el primer paso hacia el checklist D.

## Checklist D (estado)
| Función A.3 / plataforma | Windows | macOS Intel | macOS Apple Silicon |
|---|---|---|---|
| Instalación → reproducción (6 funciones) | pendiente | pendiente | pendiente |
| Instalación como usuario nuevo | pendiente | pendiente | pendiente |
| Operación sin conexión tras provisión de modelos | pendiente | pendiente | pendiente |
