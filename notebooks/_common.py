"""Ayudantes compartidos por los notebooks (evita duplicar código)."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from podcleany import synth  # noqa: E402


def workdir(name="podcleany_nb") -> Path:
    d = Path(tempfile.gettempdir()) / name
    d.mkdir(exist_ok=True)
    return d


def make_demo_site(web: Path):
    """Crea un feed RSS local con 2 episodios sintéticos (el mismo anuncio A en ambos)."""
    web.mkdir(exist_ok=True)
    ep1, m1 = synth.make_episode([("intro", 8, 99), ("speech", 30, 1), ("silence", 1.5, 0), ("ad", 20, 7), ("silence", 1.5, 0),
                                  ("speech", 30, 2), ("silence", 1.5, 0), ("ad", 15, 11), ("silence", 1.5, 0), ("speech", 25, 3)])
    ep2, m2 = synth.make_episode([("intro", 8, 99), ("speech", 40, 4), ("silence", 1.5, 0), ("ad", 20, 7), ("silence", 1.5, 0), ("speech", 30, 5)])
    synth.to_mp3(ep1, web / "ep1.mp3")
    synth.to_mp3(ep2, web / "ep2.mp3")
    return ep1, m1, ep2, m2


def serve(directory: Path, port: int):
    class Q(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", port), partial(Q, directory=str(directory)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def write_feed(web: Path, base: str, n: int):
    (web / f"feed{n}.xml").write_text(f"""<?xml version="1.0"?><rss version="2.0"><channel><title>Canal Demo</title>
<item><title>Episodio {n}</title><guid>demo-{n}</guid><description>Episodio sintético {n}</description>
<enclosure url="{base}/ep{n}.mp3" type="audio/mpeg"/></item></channel></rss>""")
