"""Motor de decisión: combina evidencias y aplica dos umbrales."""
from __future__ import annotations

import numpy as np

from . import signals as sg


def group_utterances(utts, max_s: float = 25.0, max_words: int = 110):
    """Agrupa enunciados contiguos en fragmentos para el LLM."""
    groups, cur = [], []
    for u in utts:
        words = sum(len(x.text.split()) for x in cur) + len(u.text.split())
        if cur and (u.end - cur[0].start > max_s or words > max_words or u.start - cur[-1].end > 3.0):
            groups.append(cur)
            cur = []
        cur.append(u)
    if cur:
        groups.append(cur)
    return groups


def llm_candidates(groups, classifier, edge_threshold: float = 0.3, bridge_s: float = 8.0) -> list[dict]:
    """Dos pasadas: (1) clasifica grupos; (2) en los grupos sospechosos clasifica cada enunciado para fijar bordes.

    Los enunciados publicitarios consecutivos forman un candidato; se puentean huecos cortos (<= bridge_s)
    porque dentro de un anuncio hay frases neutras.
    """
    ads = []   # enunciados publicitarios: (start, end, p, reason, text)
    for g in groups:
        p, _ = classifier.classify(" ".join(u.text for u in g))
        if p < edge_threshold:
            continue
        for u in g:
            pu, reason = classifier.classify(u.text)
            if pu >= edge_threshold:
                ads.append((u.start, u.end, float(pu), reason, u.text))
    out, cur = [], None
    for start, end, p, reason, text in ads:
        if cur and start - cur["end"] <= bridge_s:
            cur["end"] = end
            cur["ps"].append(p)
            cur["reasons"].append(reason)
        else:
            cur = {"start": start, "end": end, "ps": [p], "reasons": [reason], "text": text[:300]}
            out.append(cur)
    return out


def snap(t: float, sils: list[tuple[float, float]], window: float) -> tuple[float, bool]:
    """Mueve t al centro del silencio más cercano dentro de ±window."""
    best, bd = None, window + 1
    for a, b in sils:
        c = (a + b) / 2
        d = abs(c - t) if not (a <= t <= b) else 0.0
        if d <= window and d < bd:
            best, bd = c, d
    return (best, True) if best is not None else (t, False)


def combine(cand: dict, feats: dict, sils, cfg) -> dict | None:
    """Convierte un candidato (LLM) en segmento con score y evidencia."""
    s0, e0 = cand["start"], cand["end"]
    s, ss = snap(s0, sils, cfg.snap_window_s)
    e, se = snap(e0, sils, cfg.snap_window_s)
    if e - s < cfg.min_ad_seconds:
        return None
    jump = max(sg.loudness_jump(feats["rms_db"], s), sg.loudness_jump(feats["rms_db"], e))
    music = sg.music_score(feats["flat"], feats["cv"], s, e)
    llm_p = float(np.max(cand["ps"]))
    # pesos: el texto domina; las señales acústicas refuerzan o debilitan
    score = 0.70 * llm_p + 0.10 * (1.0 if ss and se else 0.5 if ss or se else 0.0) + 0.10 * jump + 0.10 * music
    return {"start_s": s, "end_s": e, "score": float(min(1.0, score)), "source": "llm",
            "evidence": {"llm_probability": llm_p, "llm_reason": cand["reasons"][0], "text": cand["text"],
                         "silence_start": ss, "silence_end": se, "loudness_jump": jump, "music": music,
                         "raw_start": s0, "raw_end": e0}}


def decide(score: float, cfg) -> str | None:
    """Dos umbrales: >= alto => remove; entre bajo y alto => review; < bajo => descartar."""
    if score >= cfg.threshold_high:
        return "remove"
    if score >= cfg.threshold_low:
        return "review"
    return None
