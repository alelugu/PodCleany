"""Demostración sin modelos ni internet: episodios sintéticos con anuncios + transcripción SIMULADA.

`python -m podcleany demo` crea un sitio local con 2 episodios, arranca el sistema real (API + worker)
en una carpeta de datos separada (<datos>/demo) y abre la interfaz. La voz es sintética, así que aquí la
"transcripción" es un guion; con modelos reales (faster-whisper + llama.cpp) se usan en su lugar.
"""
from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from . import synth
from .config import Config
from .models import HeuristicClassifier, Utterance

DEMO_PORT, SITE_PORT = 8766, 8767
STRONG = "Este episodio está patrocinado por ejemplo.com, use el código descuento PODCAST para un descuento especial."
WEAK = "Gracias a nuestro patrocinador, visiten ejemplo.com para más información."
PLAIN = "Hoy hablamos de historia, de ciencia y de cómo funcionan las cosas en el mundo."

# Qué "dice" cada tramo en cada episodio (inicio, fin, tipo). La intro suena a anuncio a propósito (falso positivo).
TRUTH = {
    "demo_ep1.mp3": [(0, 8, "strong"), (39.5, 59.5, "strong"), (92.5, 107.5, "weak")],
    "demo_ep2.mp3": [(0, 8, "strong")],
}


class DemoTranscriber:
    name = "demo (simulado)"

    def __init__(self):
        self.truth = []

    def set_context(self, episode) -> None:
        self.truth = TRUTH.get(Path(episode["audio_url"]).name, [])

    def transcribe(self, audio, offset_s):
        out, t, end = [], offset_s, offset_s + len(audio) / 16000
        while t < end - 1:
            e = min(end, t + 5)
            kind = next((k for a, b, k in self.truth if a <= t + 2.5 < b), "none")
            out.append(Utterance(t, e, {"strong": STRONG, "weak": WEAK}.get(kind, PLAIN)))
            t = e
        return out


def make_backends(cfg):
    return DemoTranscriber(), HeuristicClassifier(), []


def build_site(site: Path, base: str) -> None:
    site.mkdir(parents=True, exist_ok=True)
    ep1, _ = synth.make_episode([("intro", 8, 99), ("speech", 30, 1), ("silence", 1.5, 0), ("ad", 20, 7), ("silence", 1.5, 0),
                                 ("speech", 30, 2), ("silence", 1.5, 0), ("ad", 15, 11), ("silence", 1.5, 0), ("speech", 25, 3)])
    ep2, _ = synth.make_episode([("intro", 8, 99), ("speech", 40, 4), ("silence", 1.5, 0), ("ad", 20, 7), ("silence", 1.5, 0), ("speech", 30, 5)])
    for n, ep in ((1, ep1), (2, ep2)):
        synth.to_mp3(ep, site / f"demo_ep{n}.mp3")
        (site / f"feed{n}.xml").write_text(
            f'<?xml version="1.0"?><rss version="2.0"><channel><title>Podcast de Demostración</title>'
            f'<item><title>Episodio {n} (demo)</title><guid>demo-{n}</guid><description>Episodio sintético {n}: voz simulada con anuncios de prueba.</description>'
            f'<enclosure url="{base}/demo_ep{n}.mp3" type="audio/mpeg"/></item></channel></rss>', encoding="utf-8")


def main(data_dir: str | None = None, no_browser: bool = False) -> None:
    root = Config.load(data_dir).data_dir / "demo"
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text(json.dumps({"backend_factory": "podcleany.demo:make_backends", "port": DEMO_PORT,
                                                  "block_seconds": 60}), encoding="utf-8")
    cfg = Config.load(root)
    base = f"http://127.0.0.1:{SITE_PORT}"
    print("Preparando episodios de demostración…")
    build_site(root / "site", base)

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", SITE_PORT), partial(Quiet, directory=str(root / "site")))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    u1, u2 = f"{base}/feed1.xml", f"{base}/feed2.xml"
    steps = f"""
=== DEMO: qué hacer ===
1) Ya se abrió el episodio 1. Pulse «Analizar episodio».
2) Verá 3 tramos. El primero (0:00-0:09) es la intro del programa: un FALSO anuncio.
   Pulse «Conservar y proteger» ahí. El 2.º es un anuncio detectado (ya se quitará). El 3.º es «Posible»: pulse «Quitar» para confirmarlo.
3) Pulse «Generar audio sin anuncios» (así el sistema aprende esos anuncios) y luego «Descargar audio».
4) Para ver que aprendió: pegue este enlace y analice:  {u2}
   El anuncio se reconoce solo («Anuncio ya conocido») y la intro ya no aparece.
Aviso: voz y transcripción son SIMULADAS en la demo (no hay modelos de IA).
"""
    from .launcher import run_services
    run_services(cfg, open_url=f"http://127.0.0.1:{DEMO_PORT}/?url={quote(u1)}", no_browser=no_browser, extra_msg=steps)
    srv.shutdown()
