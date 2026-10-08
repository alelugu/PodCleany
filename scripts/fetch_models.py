"""Provisión INICIAL de modelos (única operación que requiere red además de descargar episodios).

Ejecutar una vez, con conexión, antes de la primera ejecución. Después PodCleany opera sin descargar modelos.
Los modelos por defecto están sujetos a sus licencias (ver docs/LICENCIAS.md); confirme su elección en Fase 1.
"""
import argparse
import shutil
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from podcleany.config import Config  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--data-dir")
ap.add_argument("--whisper", default="Systran/faster-whisper-small", help="repo de faster-whisper (CTranslate2)")
ap.add_argument("--llm-repo", default="Qwen/Qwen2.5-1.5B-Instruct-GGUF")
ap.add_argument("--llm-file", default="qwen2.5-1.5b-instruct-q4_k_m.gguf")
a = ap.parse_args()
cfg = Config.load(a.data_dir)
wdir = cfg.models_dir / "whisper"
print("Descargando Whisper en", wdir)
# faster-whisper con local_files_only espera el layout de caché de huggingface dentro de download_root
snapshot_download(a.whisper, cache_dir=str(wdir))
ldir = cfg.models_dir / "llm"
ldir.mkdir(parents=True, exist_ok=True)
print("Descargando LLM en", ldir)
p = hf_hub_download(a.llm_repo, a.llm_file, cache_dir=str(ldir / ".cache"))
shutil.copy(p, ldir / a.llm_file)
print("Listo. Modelos en", cfg.models_dir)
