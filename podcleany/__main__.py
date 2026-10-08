"""Arranque: `python -m podcleany` lanza la API y el worker como procesos independientes."""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
import webbrowser

from .config import Config


def main():
    ap = argparse.ArgumentParser(prog="podcleany")
    ap.add_argument("command", nargs="?", default="start", choices=["start", "api", "worker"])
    ap.add_argument("--data-dir")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    cfg = Config.load(a.data_dir)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    extra = ["--data-dir", str(cfg.data_dir)]
    if a.command == "worker":
        from . import worker
        return worker.run(cfg)
    if a.command == "api":
        import uvicorn
        from .api import create_app
        return uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="info")
    # start: dos procesos independientes (un fallo del worker no derriba la API)
    api = subprocess.Popen([sys.executable, "-m", "podcleany", "api", *extra])
    worker = subprocess.Popen([sys.executable, "-m", "podcleany", "worker", *extra])
    url = f"http://{cfg.host}:{cfg.port}/"
    print(f"PodCleany en {url}  (Ctrl+C para salir)")
    if not a.no_browser:
        time.sleep(1.5)
        webbrowser.open(url)
    try:
        while True:
            time.sleep(2)
            if api.poll() is not None:
                break
            if worker.poll() is not None:  # reinicia solo el worker; la API sigue disponible
                print("El worker se detuvo; reiniciando…")
                worker = subprocess.Popen([sys.executable, "-m", "podcleany", "worker", *extra])
    except KeyboardInterrupt:
        pass
    finally:
        for p in (api, worker):
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    main()
