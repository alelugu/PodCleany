"""Configuración y rutas locales (Windows, macOS; Linux funciona pero está diferido)."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path


def default_data_dir() -> Path:
    env = os.environ.get("PODCLEANY_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "PodCleany"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PodCleany"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "podcleany"


@dataclass
class Config:
    data_dir: Path = field(default_factory=default_data_dir)
    host: str = "127.0.0.1"
    port: int = 8765
    # Audio
    sample_rate: int = 16000
    block_seconds: int = 600          # bloques de normalización (~10 min)
    crossfade_ms: int = 60
    min_keep_seconds: float = 0.25
    snap_window_s: float = 1.5        # alineación de cortes al silencio
    # Decisión: dos umbrales. VALORES PROVISIONALES hasta acordarlos en Fase 1 (ver docs/PENDIENTES.md)
    threshold_low: float = 0.45
    threshold_high: float = 0.75
    min_ad_seconds: float = 6.0
    # Fingerprints
    fp_min_votes: int = 25
    fp_min_fraction: float = 0.15
    # Modelos (provisión inicial separada de la operación: scripts/fetch_models.py)
    whisper_model: str = "small"
    whisper_model_dir: str = ""       # vacío => <data_dir>/models/whisper
    llm_model_path: str = ""          # vacío => <data_dir>/models/llm/*.gguf
    stt_backend: str = "auto"         # auto | faster-whisper | none
    llm_backend: str = "auto"         # auto | llama | heuristic
    backend_factory: str = ""         # "modulo:funcion" (solo pruebas)
    # Worker
    poll_interval_s: float = 1.0
    stale_job_s: float = 900.0
    download_timeout_s: float = 60.0

    # --- rutas derivadas
    @property
    def db_path(self) -> Path:
        return self.data_dir / "podcleany.db"

    @property
    def episodes_dir(self) -> Path:
        return self.data_dir / "episodes"

    @property
    def library_dir(self) -> Path:
        return self.data_dir / "library"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    def episode_dir(self, episode_id: int) -> Path:
        return self.episodes_dir / f"{episode_id:06d}"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.episodes_dir, self.library_dir, self.logs_dir, self.models_dir):
            p.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls, data_dir: str | os.PathLike | None = None) -> "Config":
        cfg = cls()
        if data_dir:
            cfg.data_dir = Path(data_dir)
        path = cfg.data_dir / "config.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            names = {f.name for f in fields(cls)}
            for k, v in data.items():
                if k in names and k != "data_dir":
                    setattr(cfg, k, v)
        if cfg.threshold_low >= cfg.threshold_high:
            raise ValueError("threshold_low debe ser menor que threshold_high")
        cfg.ensure_dirs()
        return cfg
