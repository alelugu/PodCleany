"""Worker: proceso local separado que consume la cola de SQLite."""
from __future__ import annotations

import argparse
import logging
import os
import time

from . import pipeline
from .config import Config
from .db import claim_job, open_db, requeue_stale
from .models import make_backends

log = logging.getLogger("podcleany.worker")


def run(cfg: Config, once: bool = False, stop_when_idle: bool = False) -> None:
    conn = open_db(cfg)
    worker_id = f"worker-{os.getpid()}"
    backends = None  # carga perezosa: los modelos pesados solo se cargan si hay trabajo de 'process'
    log.info("Worker %s iniciado (datos en %s)", worker_id, cfg.data_dir)
    while True:
        requeue_stale(conn, cfg.stale_job_s)
        job = claim_job(conn, worker_id)
        if job is None:
            if once or stop_when_idle:
                return
            time.sleep(cfg.poll_interval_s)
            continue
        log.info("Job %s (%s) reclamado", job["id"], job["kind"])
        if job["kind"] == "process":
            if backends is None:
                backends = make_backends(cfg)
            pipeline.process(cfg, conn, job, backends)
        else:
            pipeline.render(cfg, conn, job)
        if once:
            return


def main():
    ap = argparse.ArgumentParser(description="Worker de PodCleany")
    ap.add_argument("--data-dir")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run(Config.load(a.data_dir), once=a.once)


if __name__ == "__main__":
    main()
