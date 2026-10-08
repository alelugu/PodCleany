"""Backends simulados para pruebas (la voz sintética no es transcribible por Whisper)."""
import json
import os
from pathlib import Path

from podcleany.models import HeuristicClassifier, Utterance

STRONG = "Este episodio está patrocinado por ejemplo.com, use el código descuento PODCAST para un descuento especial."
WEAK = "Gracias a nuestro patrocinador, visiten ejemplo.com para más información."
PLAIN = "Hoy hablamos de historia, de ciencia y de cómo funcionan las cosas en el mundo."


class ScriptedTranscriber:
    name = "scripted"

    def transcribe(self, audio, offset_s):
        truth = json.loads(Path(os.environ["PODCLEANY_FAKE_TRUTH"]).read_text())
        log = Path(os.environ["PODCLEANY_FAKE_TRUTH"]).with_suffix(".calls")
        with open(log, "a") as f:
            f.write(json.dumps([offset_s, offset_s + len(audio) / 16000]) + "\n")
        out, t, end = [], offset_s, offset_s + len(audio) / 16000
        while t < end - 1:
            e = min(end, t + 5)
            kind = "none"
            for a, b, k in truth:
                if a <= t + 2.5 < b:
                    kind = k
            out.append(Utterance(t, e, {"strong": STRONG, "weak": WEAK}.get(kind, PLAIN)))
            t = e
        return out


def make_backends(cfg):
    return ScriptedTranscriber(), HeuristicClassifier(), []
