"""Informe B: detección, eliminación incorrecta, tiempos y recursos sobre episodios etiquetados.

Uso: python -m podcleany.report etiquetas.json [--data-dir DIR] [--coverage 0.5]
etiquetas.json: {"<id de episodio o título>": [[inicio_s, fin_s], ...]}  (anuncios reales, tiempos del original)

Definiciones PROPUESTAS (deben acordarse al inicio de la Fase 1, ver docs/PENDIENTES.md):
  * Detección = anuncios reales con >= `coverage` de su duración cubierta por cortes / total de anuncios reales.
  * Eliminación incorrecta = segundos no publicitarios retirados / segundos no publicitarios totales.
"""
from __future__ import annotations

import argparse
import json

from .config import Config
from .db import open_db


def _union(iv):
    out = []
    for s, e in sorted(iv):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def _inter(a, b):
    return sum(max(0.0, min(x[1], y[1]) - max(x[0], y[0])) for x in a for y in b)


def evaluate(conn, labels: dict, coverage: float = 0.5) -> list[dict]:
    rows = []
    for key, truth in labels.items():
        ep = conn.execute("SELECT * FROM episodes WHERE id=? OR title=?", (str(key), str(key))).fetchone()
        if not ep:
            continue
        segs = conn.execute("SELECT * FROM ad_segments WHERE episode_id=?", (ep["id"],)).fetchall()
        removed = _union([[s["start_s"], s["end_s"]] for s in segs
                          if (s["user_decision"] or ("remove" if s["auto_decision"] == "remove" else "keep")) == "remove"])
        truth_u = _union([list(t) for t in truth])
        hit = sum(1 for t in truth_u if _inter([t], removed) >= coverage * (t[1] - t[0]))
        ad_s = sum(e - s for s, e in truth_u)
        non_ad = max(1e-9, (ep["duration_s"] or 0) - ad_s)
        wrong = sum(e - s for s, e in removed) - _inter(removed, truth_u)
        m = json.loads(ep["metrics"] or "{}")
        rows.append({"episode": ep["title"], "ads_true": len(truth_u), "ads_found": hit,
                     "detection_pct": 100.0 * hit / max(1, len(truth_u)),
                     "wrong_removal_pct": 100.0 * wrong / non_ad,
                     "processing_s": m.get("timings", {}).get("total_s"),
                     "audio_s": ep["duration_s"], "peak_rss_mb": m.get("resources", {}).get("peak_rss_mb"),
                     "cpu_pct": m.get("resources", {}).get("cpu_percent_avg"), "gpu": m.get("resources", {}).get("gpu")})
    return rows


def to_markdown(rows) -> str:
    h = "| Episodio | Anuncios reales | Detectados | Detección % | Eliminación incorrecta % | Proc. (s) | Audio (s) | RAM pico (MB) | CPU % | GPU |\n|---|---|---|---|---|---|---|---|---|---|\n"
    return h + "\n".join(
        f"| {r['episode']} | {r['ads_true']} | {r['ads_found']} | {r['detection_pct']:.1f} | {r['wrong_removal_pct']:.2f} | "
        f"{r['processing_s']} | {r['audio_s'] and round(r['audio_s'], 1)} | {r['peak_rss_mb']} | {r['cpu_pct']} | {r['gpu']} |" for r in rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("labels")
    ap.add_argument("--data-dir")
    ap.add_argument("--coverage", type=float, default=0.5)
    a = ap.parse_args()
    cfg = Config.load(a.data_dir)
    rows = evaluate(open_db(cfg), json.load(open(a.labels, encoding="utf-8")), a.coverage)
    print(to_markdown(rows))


if __name__ == "__main__":
    main()
