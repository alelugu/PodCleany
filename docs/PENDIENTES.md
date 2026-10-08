# Decisiones pendientes, supuestos y brechas

**Supuesto de partida:** solo se recibió la *síntesis* del service request; **no** se tuvo acceso a `Local_Podcast_AdRemoval_Services_Agreement_v2.docx` ni a sus apéndices A–E. No hay verificación contra A.3 (seis funciones), B, C, D ni E.7/§13. Hay que contrastar esta entrega con los apéndices antes de la aceptación.

## Por acordar (según §7–§8; no se inventaron valores)
- Umbrales de calidad y rendimiento (D). Los umbrales de decisión `threshold_low=0.45` / `threshold_high=0.75` y `min_ad_seconds=6` son **valores de arranque sin calibrar**.
- Regla de coincidencia y denominador de las métricas (`report.py` propone: ≥50 % de cobertura; denominador = segundos no publicitarios).
- Versiones de SO/hardware, modelos y licencias (propuesta: Whisper small + Qwen2.5-1.5B q4), duración de bloque (10 min) y crossfade (60 ms), librería de fingerprints (se implementó una propia, sin dependencias nativas), empaquetado (hoy: venv + scripts; no hay instalador/ejecutable).
- Adaptación Voilà (docs/ADAPTACION_VOILA.md) y aplazamiento de Ubuntu: registrar en control de cambios.

## Brechas conocidas
1. Sin validación en Windows/macOS ni con modelos reales (ver PRUEBAS.md). Los pines de `requirements-ml.txt` no se verificaron.
2. Formatos de entrada: MP3 está probado; otros (m4a/ogg) usan fallback a archivo si el pipe falla, sin pruebas. Solo se descarga el episodio más reciente de un RSS (no hay selector de episodio).
3. Detección de música/volumen son heurísticas simples; el texto (LLM) domina el score. Anuncios integrados en el discurso dependen por completo de la calidad del LLM.
4. El LLM clasifica fragmentos sin contexto de episodio; el clasificador heurístico de respaldo (frases) existe solo para operar sin modelo y no sustituye al LLM.
5. Huellas: un anuncio distinto cada vez (inserción dinámica con voz distinta) no se reconoce; solo audio idéntico/similar.
6. API sin autenticación (solo 127.0.0.1); no se aplica protección CSRF/CORS adicional ni límite de tamaño de descarga.
7. Sesión de transferencia de conocimiento y informe B con corpus real: pendientes.
8. «Mi biblioteca» es mínima (listar, abrir, descargar); no hay borrado de episodios.
