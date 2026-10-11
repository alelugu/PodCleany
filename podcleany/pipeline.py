"""Pipeline completo (E.6 pasos 4-9) ejecutado por el worker."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path

import numpy as np
import psutil

from . import audio, decision, feeds, fingerprint as fp, signals as sg
from .db import jdump, touch_episode, update_job


class Sampler(threading.Thread):
    """Mide RAM pico y CPU medio del proceso durante el procesamiento (informe B)."""

    def __init__(self):
        super().__init__(daemon=True)
        self.p = psutil.Process()
        self.peak_rss = 0
        self.cpu = []
        self._stop = threading.Event()

    def run(self):
        self.p.cpu_percent(None)
        while not self._stop.wait(0.5):
            self.peak_rss = max(self.peak_rss, self.p.memory_info().rss)
            self.cpu.append(self.p.cpu_percent(None))

    def stop(self):
        self._stop.set()
        self.peak_rss = max(self.peak_rss, self.p.memory_info().rss)
        self.join(timeout=2)
        return {"peak_rss_mb": round(self.peak_rss / 2**20, 1),
                "cpu_percent_avg": round(float(np.mean(self.cpu)), 1) if self.cpu else None, "gpu": "no utilizada"}


def episode_logger(cfg, episode_id: int) -> logging.Logger:
    lg = logging.getLogger(f"podcleany.episode.{episode_id}")
    if not lg.handlers:
        cfg.logs_dir.mkdir(parents=True, exist_ok=True)
        h = logging.FileHandler(cfg.logs_dir / f"episode_{episode_id:06d}.log", encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        lg.addHandler(h)
        lg.setLevel(logging.INFO)
    return lg


def safe_name(s: str, maxlen: int = 80) -> str:
    return re.sub(r"[^\w\s().,-]", "", s, flags=re.UNICODE).strip()[:maxlen] or "episodio"


def load_fp_index(conn):
    rows = conn.execute("SELECT id, kind, duration_s, hashes FROM ad_fingerprints WHERE enabled=1").fetchall()
    return fp.build_index([(r["id"], r["kind"], r["duration_s"], r["hashes"]) for r in rows])


def _subtract(total: tuple[float, float], holes: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out, pos = [], total[0]
    for a, b in sorted(holes):
        if a > pos:
            out.append((pos, min(a, total[1])))
        pos = max(pos, b)
    if pos < total[1]:
        out.append((pos, total[1]))
    return [(a, b) for a, b in out if b - a > 0.5]


def _overlap(a, b) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def process(cfg, conn, job, backends) -> None:
    transcriber, classifier, backend_warnings = backends
    sampler = Sampler()
    sampler.start()
    t_all = time.time()
    timings: dict[str, float] = {}
    log = logging.getLogger("podcleany.pipeline")
    ep_id = job["episode_id"]
    lg = None

    def step(stage: str, progress: float, message: str):
        update_job(conn, job["id"], stage=stage, progress=round(progress, 3), message=message)
        if ep_id:
            touch_episode(conn, ep_id, status=stage)
        if lg:
            lg.info("[%s] %s", stage, message)

    try:
        # ---------------------------------------------------------- descargar (paso 4)
        step_t = time.time()
        update_job(conn, job["id"], stage="downloading", progress=0.01, message="Obteniendo el episodio")
        if ep_id is None:
            info = feeds.resolve(job["url"], cfg.download_timeout_s)
            ch = conn.execute("SELECT id FROM channels WHERE rss_url=?", (info.rss_url,)).fetchone()
            if ch:
                ch_id = ch["id"]
            else:
                ch_id = conn.execute("INSERT INTO channels(name, rss_url) VALUES (?,?)", (info.channel_name, info.rss_url)).lastrowid
            row = conn.execute("SELECT id FROM episodes WHERE channel_id=? AND guid=?", (ch_id, info.guid)).fetchone()
            if row:
                ep_id = row["id"]
                touch_episode(conn, ep_id, status="downloading", error=None)
            else:
                ep_id = conn.execute(
                    "INSERT INTO episodes(channel_id,title,source_url,guid,audio_url,description,status) VALUES (?,?,?,?,?,?,?)",
                    (ch_id, info.title, job["url"], info.guid, info.audio_url, info.description, "downloading")).lastrowid
            conn.execute("UPDATE jobs SET episode_id=? WHERE id=?", (ep_id, job["id"]))
            if info.cover_url:
                cover = cfg.episode_dir(ep_id) / "cover.img"
                cover.parent.mkdir(parents=True, exist_ok=True)
                if feeds.download_small(info.cover_url, cover):
                    touch_episode(conn, ep_id, cover_path=str(cover))
        lg = episode_logger(cfg, ep_id)
        ep = conn.execute("SELECT * FROM episodes WHERE id=?", (ep_id,)).fetchone()
        if hasattr(transcriber, "set_context"):  # solo la demo (transcripción simulada) lo usa
            transcriber.set_context(ep)
        for w in backend_warnings:
            lg.warning(w)
        lg.info("Procesando '%s' (%s) con STT=%s LLM=%s", ep["title"], ep["audio_url"],
                getattr(transcriber, "name", "?"), getattr(classifier, "name", "?"))
        edir = cfg.episode_dir(ep_id)
        edir.mkdir(parents=True, exist_ok=True)
        orig = edir / "original.mp3"
        if not (orig.exists() and orig.stat().st_size > 0):
            step("downloading", 0.02, "Descargando audio")
            feeds.download(ep["audio_url"], orig, cfg.download_timeout_s,
                           lambda f: update_job(conn, job["id"], progress=round(0.02 + 0.18 * f, 3)))
        else:
            lg.info("Checkpoint: original ya descargado")
        touch_episode(conn, ep_id, original_path=str(orig))
        timings["download_s"] = round(time.time() - step_t, 2)

        # ---------------------------------------------------------- normalizar (paso 5)
        t0 = time.time()
        step("normalizing", 0.2, "Preparando el audio")
        blocks_dir = edir / "blocks"
        info_f = edir / "normalize.json"
        if info_f.exists() and audio.count_blocks(blocks_dir) == json.loads(info_f.read_text())["blocks"]:
            norm = json.loads(info_f.read_text())
            lg.info("Checkpoint: %d bloques normalizados", norm["blocks"])
        else:
            norm = audio.normalize_to_blocks(orig, blocks_dir, cfg.sample_rate, cfg.block_seconds,
                                             lambda i: update_job(conn, job["id"], progress=round(0.2 + 0.1 * min(i / 8, 1), 3)))
            info_f.write_text(json.dumps(norm))
        duration = norm["duration_s"]
        touch_episode(conn, ep_id, duration_s=duration)
        timings["normalize_s"] = round(time.time() - t0, 2)

        # ---------------------------------------------------------- analizar bloques (paso 6)
        t0 = time.time()
        step("analyzing", 0.3, "Analizando el audio")
        all_h, rms, flat, cv, sils = [], [], [], [], []
        nblocks = norm["blocks"]
        bl_s = cfg.block_seconds
        for i in range(nblocks):
            cache = edir / "analysis" / f"a_{i:04d}.npz"
            if cache.exists():
                z = np.load(cache, allow_pickle=False)
                h, r, f, c = z["h"], z["rms"], z["flat"], z["cv"]
            else:
                x = audio.read_block(blocks_dir, i).astype(np.float32) / 32768.0
                h = fp.hashes_from_audio(x, frame_offset=int(round(i * bl_s / fp.FRAME_S)))
                feats = sg.frame_features(x)
                r, f, c = feats["rms_db"], feats["flat"], feats["cv"]
                cache.parent.mkdir(exist_ok=True)
                np.savez(cache, h=h, rms=r, flat=f, cv=c)
            all_h.append(h)
            rms.append(r)
            flat.append(f)
            cv.append(c)
            sils += sg.silences(r, offset_s=i * bl_s)
            update_job(conn, job["id"], progress=round(0.3 + 0.2 * (i + 1) / nblocks, 3))
        H = np.concatenate(all_h) if all_h else np.zeros((0, 2), np.uint32)
        feats = {"rms_db": np.concatenate(rms), "flat": np.concatenate(flat), "cv": np.concatenate(cv)}
        timings["analyze_s"] = round(time.time() - t0, 2)

        # ---------------------------------------------------------- comparar huellas (paso 6)
        t0 = time.time()
        step("matching", 0.5, "Buscando anuncios conocidos")
        matches = fp.match(H, load_fp_index(conn), cfg.fp_min_votes, cfg.fp_min_fraction)
        protected = [m for m in matches if m["kind"] == "protected"]
        known = []
        for m in matches:
            if m["kind"] != "ad":
                continue
            span = (m["start_s"], min(duration, m["end_s"]))
            if any(_overlap(span, (p["start_s"], p["end_s"])) > 0.3 * (span[1] - span[0]) for p in protected):
                lg.info("Veto: huella de anuncio %s coincide con contenido protegido en %.1fs", m["fp_id"], m["start_s"])
                continue
            known.append(m)
        lg.info("Huellas: %d anuncios conocidos, %d regiones protegidas", len(known), len(protected))
        timings["match_s"] = round(time.time() - t0, 2)

        segments: list[dict] = []
        for m in known:
            s, e = decision.snap(m["start_s"], sils, 0.5)[0], decision.snap(min(duration, m["end_s"]), sils, 0.5)[0]
            segments.append({"start_s": s, "end_s": e, "score": round(0.8 + 0.2 * m["confidence"], 3), "source": "fingerprint",
                             "decision": "remove", "fingerprint_id": m["fp_id"],
                             "evidence": {"fingerprint_id": m["fp_id"], "votes": m["votes"], "confidence": m["confidence"],
                                          "note": "anuncio conocido: no se transcribió"}})

        # ---------------------------------------------------------- resolver regiones (paso 7)
        t0 = time.time()
        holes = [(m["start_s"], min(duration, m["end_s"])) for m in known + protected]
        unresolved = _subtract((0.0, duration), holes)
        lg.info("Regiones sin resolver: %s", [(round(a, 1), round(b, 1)) for a, b in unresolved])
        step("transcribing", 0.55, "Escuchando las partes sin anuncios conocidos")
        total_unres = sum(b - a for a, b in unresolved) or 1.0
        utts, done_s = [], 0.0
        tdir = edir / "transcripts"
        tdir.mkdir(exist_ok=True)
        for a, b in unresolved:
            pos = a
            while pos < b:
                end = min(b, pos + cfg.block_seconds)
                cp = tdir / f"t_{int(pos * 1000)}_{int(end * 1000)}.json"
                if cp.exists():
                    chunk = [decision_utt(u) for u in json.loads(cp.read_text())]
                else:
                    x = audio.read_range(blocks_dir, pos, end, cfg.sample_rate, bl_s)
                    chunk = transcriber.transcribe(x, pos)
                    cp.write_text(jdump([{"start": u.start, "end": u.end, "text": u.text} for u in chunk]))
                utts += chunk
                done_s += end - pos
                update_job(conn, job["id"], progress=round(0.55 + 0.25 * done_s / total_unres, 3))
                pos = end
        timings["transcribe_s"] = round(time.time() - t0, 2)

        # ---------------------------------------------------------- decidir y cortar (paso 8)
        t0 = time.time()
        step("deciding", 0.82, "Decidiendo qué quitar")
        cands = decision.llm_candidates(decision.group_utterances(utts), classifier)
        for c in cands:
            seg = decision.combine(c, feats, sils, cfg)
            if not seg:
                continue
            if any(_overlap((seg["start_s"], seg["end_s"]), (p["start_s"], p["end_s"])) > 0.3 * (seg["end_s"] - seg["start_s"]) for p in protected):
                lg.info("Veto: candidato %.1f-%.1f s dentro de contenido protegido", seg["start_s"], seg["end_s"])
                continue
            d = decision.decide(seg["score"], cfg)
            if d:
                seg["decision"] = d
                segments.append(seg)
            else:
                lg.info("Descartado (score %.2f): %.1f-%.1f s", seg["score"], seg["start_s"], seg["end_s"])
        timings["decide_s"] = round(time.time() - t0, 2)

        # ---------------------------------------------------------- persistir (paso 9)
        step("saving", 0.92, "Guardando resultados")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM ad_segments WHERE episode_id=? AND source!='user'", (ep_id,))
        for s in sorted(segments, key=lambda s: s["start_s"]):
            conn.execute(
                "INSERT INTO ad_segments(episode_id,start_s,end_s,score,source,evidence,auto_decision,fingerprint_id) VALUES (?,?,?,?,?,?,?,?)",
                (ep_id, round(s["start_s"], 3), round(s["end_s"], 3), s["score"], s["source"], jdump(s["evidence"]),
                 s["decision"], s.get("fingerprint_id")))
            if s.get("fingerprint_id"):
                conn.execute("UPDATE ad_fingerprints SET hits=hits+1 WHERE id=?", (s["fingerprint_id"],))
        conn.execute("COMMIT")
        timings["total_s"] = round(time.time() - t_all, 2)
        metrics = {"timings": timings, "resources": sampler.stop(), "audio_duration_s": round(duration, 1),
                   "segments_removed": sum(s["decision"] == "remove" for s in segments),
                   "segments_review": sum(s["decision"] == "review" for s in segments),
                   "stt": getattr(transcriber, "name", "?"), "llm": getattr(classifier, "name", "?"),
                   "warnings": backend_warnings}
        touch_episode(conn, ep_id, status="ready", clean_stale=1, metrics=jdump(metrics), error=None)
        update_job(conn, job["id"], status="done", stage="ready", progress=1.0, message="Listo para revisar",
                   finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        lg.info("Terminado: %s", metrics)
    except Exception as e:
        sampler.stop()
        msg = friendly_error(e)
        log.exception("Job %s falló", job["id"])
        if lg:
            lg.exception("Error: %s", e)
        if ep_id:
            touch_episode(conn, ep_id, status="failed", error=msg)
        update_job(conn, job["id"], status="failed", error=msg, message=msg,
                   finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def decision_utt(d):
    from .models import Utterance
    return Utterance(d["start"], d["end"], d["text"])


def friendly_error(e: Exception) -> str:
    import requests
    if isinstance(e, requests.exceptions.ConnectionError):
        return "No se pudo conectar con el servidor del podcast. Revise su conexión."
    if isinstance(e, requests.exceptions.Timeout):
        return "El servidor del podcast tardó demasiado en responder."
    if isinstance(e, requests.exceptions.HTTPError):
        return f"El servidor del podcast respondió con un error ({e.response.status_code})."
    return str(e)[:300] or e.__class__.__name__


def render(cfg, conn, job) -> None:
    """Job 'render': genera el audio final con las decisiones finales (original intacto)."""
    ep_id = job["episode_id"]
    lg = episode_logger(cfg, ep_id)
    try:
        ep = conn.execute("SELECT e.*, c.name AS channel FROM episodes e JOIN channels c ON c.id=e.channel_id WHERE e.id=?", (ep_id,)).fetchone()
        update_job(conn, job["id"], stage="rendering", progress=0.1, message="Generando audio sin anuncios")
        touch_episode(conn, ep_id, status="rendering")
        segs = conn.execute("SELECT * FROM ad_segments WHERE episode_id=? ORDER BY start_s", (ep_id,)).fetchall()
        removals = [(s["start_s"], s["end_s"]) for s in segs if (s["user_decision"] or ("remove" if s["auto_decision"] == "remove" else "keep")) == "remove"]
        out_dir = cfg.library_dir / safe_name(ep["channel"])
        dst = out_dir / f"{safe_name(ep['title'])} (sin anuncios).mp3"
        lg.info("Render: %d cortes %s", len(removals), [(round(a, 1), round(b, 1)) for a, b in removals])
        final = audio.render_clean(Path(ep["original_path"]), dst, ep["duration_s"], removals, cfg.crossfade_ms, cfg.min_keep_seconds)
        removed = max(0.0, ep["duration_s"] - final)
        touch_episode(conn, ep_id, status="done", clean_path=str(dst), clean_duration_s=final, removed_s=removed, clean_stale=0, error=None)
        update_job(conn, job["id"], status="done", stage="done", progress=1.0, message="Audio listo",
                   finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        lg.info("Audio final: %s (%.1fs, quitados %.1fs)", dst, final, removed)
    except Exception as e:
        msg = friendly_error(e)
        lg.exception("Error de render: %s", e)
        touch_episode(conn, ep_id, status="ready", error=msg)
        update_job(conn, job["id"], status="failed", error=msg, message=msg,
                   finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
