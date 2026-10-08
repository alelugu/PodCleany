# Diccionario de datos (SQLite, WAL) y archivos locales

Migraciones en `podcleany/db.py` (`schema_migrations`). Relaciones: `channels 1—N episodes 1—N ad_segments`; `jobs N—1 episodes`; `ad_fingerprints N—1 channels`; `ad_segments N—1 ad_fingerprints`.

**channels**: `id`, `name` (título del feed, el mismo que muestra AntennaPod), `rss_url` (UNIQUE; `direct:<host>` si se pegó un MP3), `cover_path`, `created_at` (fecha de alta).
**episodes**: `id`, `channel_id`, `title`, `source_url` (URL enviada), `guid`, `audio_url` (referencia original), `description`, `cover_path`, `duration_s`, `original_path`, `clean_path` (ruta del resultado), `clean_duration_s`, `removed_s`, `clean_stale` (hay cambios sin aplicar), `status` (queued/downloading/normalizing/analyzing/matching/transcribing/deciding/saving/ready/rendering/done/failed), `error`, `metrics` (JSON: tiempos, RAM pico, CPU, GPU), `created_at`, `updated_at`. UNIQUE(channel_id, guid).
**jobs** (cola): `id`, `kind` (process/render), `episode_id`, `url`, `dedupe_key` (índice único parcial entre queued/running/done), `status` (queued/running/done/failed), `stage`, `progress` 0–1, `message`, `error`, `attempts`, `worker_id`, `heartbeat_at`, `created_at`, `started_at`, `finished_at`.
**ad_segments**: `id`, `episode_id`, `start_s`, `end_s` (tiempos del original), `score`, `source` (fingerprint/llm/signals/user), `evidence` (JSON: votos de huella, probabilidad LLM, silencio, salto de volumen, música, texto), `auto_decision` (remove/review), `user_decision` (keep/remove/NULL), `fingerprint_id`, `history` (JSON; base de «Deshacer»), `created_at`, `updated_at`. Decisión final = `user_decision` si existe; si no, `remove` solo cuando `auto_decision='remove'`.
**ad_fingerprints**: `id`, `channel_id`, `kind` (ad/protected: contenido protegido p. ej. intros/outros), `label`, `duration_s`, `n_hashes`, `hashes` (BLOB uint32 [hash, frame]), `source_episode_id`, `enabled`, `hits`, `false_positives` (2 rechazos → se desactiva), `created_at`.

## Archivos (`<datos>`: Windows `%LOCALAPPDATA%\PodCleany`, macOS `~/Library/Application Support/PodCleany`, o `PODCLEANY_HOME`)
```
podcleany.db(-wal,-shm)   config.json (opcional)
episodes/<id>/original.mp3  normalize.json  blocks/block_NNNN.wav (16 kHz mono)  analysis/a_NNNN.npz  transcripts/*.json  cover.img
library/<canal>/<título> (sin anuncios).mp3     logs/episode_<id>.log     models/{whisper,llm}
```
El original **nunca** se sobrescribe; el resultado se genera siempre desde él.
