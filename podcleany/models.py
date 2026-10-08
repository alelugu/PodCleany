"""Backends de transcripción (faster-whisper + VAD) y clasificación (llama.cpp). Todo local."""
from __future__ import annotations

import importlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger("podcleany.models")


@dataclass
class Utterance:
    start: float
    end: float
    text: str


class FasterWhisperTranscriber:
    name = "faster-whisper"

    def __init__(self, model: str, model_dir: str, language: str | None = None):
        from faster_whisper import WhisperModel  # import perezoso: dependencia opcional pesada
        # local_files_only: en operación no se descarga nada (restricción de red de E.4)
        self.model = WhisperModel(model, device="auto", compute_type="int8", download_root=model_dir or None,
                                  local_files_only=True)
        self.language = language

    def transcribe(self, audio: np.ndarray, offset_s: float) -> list[Utterance]:
        segs, _ = self.model.transcribe(audio, language=self.language, vad_filter=True,
                                        vad_parameters={"min_silence_duration_ms": 500}, beam_size=1)
        return [Utterance(offset_s + s.start, offset_s + s.end, s.text.strip()) for s in segs if s.text.strip()]


class NullTranscriber:
    name = "none"

    def transcribe(self, audio, offset_s):
        return []


AD_PATTERNS = [
    r"\bpatrocin", r"\bsponsor", r"c[oó]digo (de )?descuento", r"promo(cional)? code", r"\buse (the )?code\b",
    r"\bbrought to you by\b", r"\bestá? episodio (es|está) (presentado|patrocinado)", r"\boferta\b",
    r"\bsuscr[ií]be?te\b.*\bgratis\b", r"\bprueba gratis\b", r"\bfree trial\b", r"\bdescuento\b", r"\bdiscount\b",
    r"\b\w+\.(com|es|mx|io)(/\w+)?\b", r"\bcompra(r)? ahora\b", r"\blimited time\b", r"\bpor tiempo limitado\b",
]


class HeuristicClassifier:
    """Respaldo sin modelo: coincidencia de frases publicitarias. Se registra como tal en los logs."""
    name = "heuristic"

    def classify(self, text: str) -> tuple[float, str]:
        t = text.lower()
        hits = [p for p in AD_PATTERNS if re.search(p, t)]
        p = min(1.0, 0.35 * len(hits))
        return p, f"{len(hits)} frases publicitarias" if hits else "sin indicios"


class LlamaCppClassifier:
    name = "llama.cpp"
    PROMPT = ("Eres un clasificador de anuncios en transcripciones de podcasts. Indica si el fragmento es publicidad "
              "(patrocinio, oferta, código de descuento, llamada a comprar) y no contenido editorial. "
              'Responde solo JSON: {"ad": true|false, "confidence": 0..1, "reason": "..."}.\n\nFragmento:\n')

    def __init__(self, model_path: str, n_threads: int | None = None):
        from llama_cpp import Llama  # import perezoso
        self.llm = Llama(model_path=model_path, n_ctx=2048, n_threads=n_threads, verbose=False)

    def classify(self, text: str) -> tuple[float, str]:
        out = self.llm.create_chat_completion(
            messages=[{"role": "user", "content": self.PROMPT + text[:3000]}],
            temperature=0.0, max_tokens=120, response_format={"type": "json_object"})
        raw = out["choices"][0]["message"]["content"]
        try:
            d = json.loads(raw)
            conf = float(d.get("confidence", 0.5))
            p = conf if d.get("ad") else 1.0 - conf
            return (p if d.get("ad") else min(p, 0.3)), str(d.get("reason", ""))[:200]
        except (ValueError, TypeError):
            log.warning("Respuesta no JSON del LLM: %r", raw[:100])
            return 0.0, "respuesta no interpretable"


def make_backends(cfg):
    """Devuelve (transcriber, classifier, warnings)."""
    warnings: list[str] = []
    if cfg.backend_factory:
        mod, fn = cfg.backend_factory.split(":")
        return getattr(importlib.import_module(mod), fn)(cfg)
    # --- STT
    stt = NullTranscriber()
    if cfg.stt_backend in ("auto", "faster-whisper"):
        try:
            stt = FasterWhisperTranscriber(cfg.whisper_model, cfg.whisper_model_dir or str(cfg.models_dir / "whisper"))
        except Exception as e:  # modelo no provisionado o dependencia ausente
            msg = f"faster-whisper no disponible ({type(e).__name__}); las regiones sin huella no se transcribirán"
            if cfg.stt_backend == "faster-whisper":
                raise
            warnings.append(msg)
    # --- LLM
    clf = None
    if cfg.llm_backend in ("auto", "llama"):
        path = cfg.llm_model_path or next(iter(sorted((cfg.models_dir / "llm").glob("*.gguf"))), "")
        try:
            if not path:
                raise FileNotFoundError("sin modelo GGUF")
            clf = LlamaCppClassifier(str(path))
        except Exception as e:
            if cfg.llm_backend == "llama":
                raise
            warnings.append(f"llama.cpp no disponible ({type(e).__name__}); se usa clasificador heurístico de respaldo")
    return stt, clf or HeuristicClassifier(), warnings
