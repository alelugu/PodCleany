# Adaptación propuesta de E.3: Voilà + ipywidgets (registro de cambio)

**Estado: propuesta, pendiente de aprobación por el control de cambios (E.7 / §13). No se implementó como reemplazo.**
- La interfaz principal entregada es la **estática servida por la API** (lo que E.3 prescribe). Voilà no sustituye el backend FastAPI.
- Integración documentada: Voilà corre como servidor aparte (`voila notebooks/07_interfaz_voila.ipynb`); su kernel solo hace `requests` a la Local API (REST/JSON). SSE y Range 206 los consume el navegador/`<audio>` directamente contra la API (CORS no está habilitado: hoy Voilà y la API serían orígenes distintos, así que reproducir audio desde Voilà requeriría un proxy o habilitar CORS — **decisión pendiente**).
- La interfaz no escribe en SQLite ni invoca el worker. El aislamiento actual (127.0.0.1) no cambia.
- `07_interfaz_voila.ipynb` es solo un esqueleto mínimo (enviar URL); la experiencia completa de UI/UX requerida está en la interfaz estática.
