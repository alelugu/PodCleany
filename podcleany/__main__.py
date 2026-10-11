"""Arranque: `python -m podcleany` lanza la API y el worker como procesos independientes."""
from __future__ import annotations

import argparse
import logging

from .config import Config


def main():
    ap = argparse.ArgumentParser(prog="podcleany")
    ap.add_argument("command", nargs="?", default="start", choices=["start", "api", "worker", "demo"])
    ap.add_argument("--data-dir")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.command == "demo":
        from . import demo
        return demo.main(a.data_dir, a.no_browser)
    cfg = Config.load(a.data_dir)
    if a.command == "worker":
        from . import worker
        return worker.run(cfg)
    if a.command == "api":
        import uvicorn
        from .api import create_app
        return uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="info")
    from .launcher import run_services
    run_services(cfg, no_browser=a.no_browser)


if __name__ == "__main__":
    main()
