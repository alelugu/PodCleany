"""Lanza API y worker como procesos independientes y supervisa el worker."""
from __future__ import annotations

import signal
import subprocess
import sys
import time
import webbrowser

from .config import Config


def run_services(cfg: Config, open_url: str | None = None, no_browser: bool = False, extra_msg: str = "") -> None:
    extra = ["--data-dir", str(cfg.data_dir)]
    api = subprocess.Popen([sys.executable, "-m", "podcleany", "api", *extra])
    worker = subprocess.Popen([sys.executable, "-m", "podcleany", "worker", *extra])
    url = open_url or f"http://{cfg.host}:{cfg.port}/"
    print(f"\nPodCleany en {url}  (Ctrl+C para salir)\n{extra_msg}")
    if not no_browser:
        time.sleep(1.5)
        webbrowser.open(url)
    signal.signal(signal.SIGTERM, lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
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
