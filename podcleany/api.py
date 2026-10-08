"""Local API (FastAPI, 127.0.0.1): E.6 pasos 1-2, 10 y 11."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from . import audio, feeds, fingerprint as fp
from .config import Config
from .db import enqueue, jdump, open_db, touch_episode

STATIC = Path(__file__).parent / "static"


class NewEpisode(BaseModel):
    url: str


class Span(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    label: str | None = None


class SegmentEdit(BaseModel):
    decision: str | None = None      # keep | remove
    start: float | None = Field(default=None, ge=0)
    end: float | None = None


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or Config.load()
    app = FastAPI(title="PodCleany", docs_url=None, redoc_url=None)
    app.state.cfg = cfg

    def db() -> sqlite3.Connection:
        return open_db(cfg)  # conexión corta por petición (WAL admite lectores concurrentes)

    # ---------------------------------------------------------------- páginas
    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ---------------------------------------------------- pasos 1-2: enviar y encolar
    @app.post("/episodes", status_code=202)
    def submit(body: NewEpisode):
        try:
            url = feeds.validate_url(body.url)
        except feeds.InvalidUrl as e:
            raise HTTPException(422, str(e))
        conn = db()
        try:
            job_id, dup = enqueue(conn, "process", "process:" + feeds.normalize_key(url), url=url)
            job = conn.execute("SELECT status, episode_id FROM jobs WHERE id=?", (job_id,)).fetchone()
            return {"job_id": job_id, "status": job["status"], "episode_id": job["episode_id"], "duplicate": dup}
        finally:
            conn.close()

    # ---------------------------------------------------------------- jobs + SSE
    def job_dict(r) -> dict:
        return {k: r[k] for k in ("id", "kind", "episode_id", "status", "stage", "progress", "message", "error")}

    @app.get("/jobs/{job_id}")
    def get_job(job_id: int):
        conn = db()
        try:
            r = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not r:
                raise HTTPException(404, "Trabajo no encontrado")
            return job_dict(r)
        finally:
            conn.close()

    @app.get("/jobs/{job_id}/events")
    async def job_events(job_id: int):
        async def gen():
            last = None
            while True:
                conn = db()
                try:
                    r = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                finally:
                    conn.close()
                if r is None:
                    yield "event: error\ndata: {\"error\": \"not found\"}\n\n"
                    return
                d = job_dict(r)
                if d != last:
                    yield f"data: {json.dumps(d, ensure_ascii=False)}\n\n"
                    last = d
                if d["status"] in ("done", "failed"):
                    return
                await asyncio.sleep(0.5)
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---------------------------------------------------------------- biblioteca
    @app.get("/library")
    def library():
        conn = db()
        try:
            rows = conn.execute(
                "SELECT e.id,e.title,e.status,e.duration_s,e.clean_duration_s,e.removed_s,e.clean_stale,e.clean_path,e.created_at,c.name AS channel "
                "FROM episodes e JOIN channels c ON c.id=e.channel_id ORDER BY e.id DESC").fetchall()
            return [{**dict(r), "has_clean": bool(r["clean_path"]) and not r["clean_stale"]} for r in rows]
        finally:
            conn.close()

    def seg_dict(r) -> dict:
        eff = r["user_decision"] or ("remove" if r["auto_decision"] == "remove" else "keep")
        ev = json.loads(r["evidence"] or "{}")
        return {"id": r["id"], "start": r["start_s"], "end": r["end_s"], "source": r["source"],
                "kind": "detected" if r["auto_decision"] == "remove" and r["source"] != "user" else ("user" if r["source"] == "user" else "possible"),
                "auto_decision": r["auto_decision"], "user_decision": r["user_decision"], "decision": eff,
                "can_undo": bool(json.loads(r["history"] or "[]")),
                "reason": ev.get("llm_reason") or ev.get("note") or ""}

    @app.get("/episodes/{ep_id}")
    def episode(ep_id: int):
        conn = db()
        try:
            e = conn.execute("SELECT e.*, c.name AS channel FROM episodes e JOIN channels c ON c.id=e.channel_id WHERE e.id=?", (ep_id,)).fetchone()
            if not e:
                raise HTTPException(404, "Episodio no encontrado")
            segs = conn.execute("SELECT * FROM ad_segments WHERE episode_id=? ORDER BY start_s", (ep_id,)).fetchall()
            job = conn.execute("SELECT * FROM jobs WHERE episode_id=? ORDER BY id DESC LIMIT 1", (ep_id,)).fetchone()
            segs_d = [seg_dict(s) for s in segs]
            removed = sum(s["end"] - s["start"] for s in segs_d if s["decision"] == "remove")
            clean_name = Path(e["clean_path"]).name if e["clean_path"] else None
            return {
                "id": e["id"], "title": e["title"], "channel": e["channel"], "description": e["description"],
                "duration": e["duration_s"], "status": e["status"], "error": e["error"],
                "has_cover": bool(e["cover_path"]), "segments": segs_d, "planned_removed_s": removed,
                "planned_final_s": (e["duration_s"] - removed) if e["duration_s"] else None,
                "clean": {"ready": bool(e["clean_path"]) and not e["clean_stale"], "stale": bool(e["clean_stale"]) and bool(e["clean_path"]),
                          "name": clean_name, "format": "MP3" if clean_name else None,
                          "duration": e["clean_duration_s"], "removed": e["removed_s"]},
                "job": job_dict(job) if job else None,
            }
        finally:
            conn.close()

    @app.get("/episodes/{ep_id}/cover")
    def cover(ep_id: int):
        conn = db()
        try:
            r = conn.execute("SELECT cover_path FROM episodes WHERE id=?", (ep_id,)).fetchone()
        finally:
            conn.close()
        if not r or not r["cover_path"] or not Path(r["cover_path"]).exists():
            raise HTTPException(404)
        return FileResponse(r["cover_path"])

    # ------------------------------------------------ paso 10: streaming Range 206
    @app.api_route("/episodes/{ep_id}/audio/{which}", methods=["GET", "HEAD"])
    def stream(ep_id: int, which: str, request: Request, download: int = 0):
        if which not in ("original", "clean"):
            raise HTTPException(404)
        conn = db()
        try:
            r = conn.execute("SELECT original_path, clean_path, clean_stale FROM episodes WHERE id=?", (ep_id,)).fetchone()
        finally:
            conn.close()
        path = r and (r["original_path"] if which == "original" else r["clean_path"])
        if not path or not Path(path).exists():
            raise HTTPException(404, "El audio todavía no está disponible")
        if which == "clean" and r["clean_stale"]:
            raise HTTPException(409, "Hay cambios sin aplicar: genere de nuevo el audio sin anuncios")
        headers = {}
        if download:
            headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(Path(path).name)
        return range_response(Path(path), request, "audio/mpeg", headers)

    # -------------------------------------------------------- generar audio (job render)
    @app.post("/episodes/{ep_id}/render", status_code=202)
    def render(ep_id: int):
        conn = db()
        try:
            e = conn.execute("SELECT status FROM episodes WHERE id=?", (ep_id,)).fetchone()
            if not e:
                raise HTTPException(404, "Episodio no encontrado")
            if e["status"] not in ("ready", "done"):
                raise HTTPException(409, "El episodio aún se está analizando")
            # cada generación es un job nuevo (dedupe solo frente a uno activo)
            active = conn.execute("SELECT id FROM jobs WHERE kind='render' AND episode_id=? AND status IN ('queued','running')", (ep_id,)).fetchone()
            if active:
                return {"job_id": active["id"], "duplicate": True}
            cur = conn.execute("INSERT INTO jobs(kind, episode_id, dedupe_key) VALUES ('render', ?, ?)",
                               (ep_id, f"render:{ep_id}:{os.urandom(4).hex()}"))
            return {"job_id": cur.lastrowid, "duplicate": False}
        finally:
            conn.close()

    # --------------------------------------------- paso 11: retroalimentación y aprendizaje
    def _get_seg(conn, seg_id):
        s = conn.execute("SELECT * FROM ad_segments WHERE id=?", (seg_id,)).fetchone()
        if not s:
            raise HTTPException(404, "Segmento no encontrado")
        return s

    def _episode_ready(conn, ep_id):
        e = conn.execute("SELECT * FROM episodes WHERE id=?", (ep_id,)).fetchone()
        if not e:
            raise HTTPException(404, "Episodio no encontrado")
        if e["status"] not in ("ready", "done"):
            raise HTTPException(409, "El episodio aún se está analizando")
        return e

    def learn(conn, e, start: float, end: float, kind: str = "ad", label: str | None = None, seg_id: int | None = None):
        """Calcula la huella del tramo (desde el audio normalizado) y la guarda en ad_fingerprints."""
        if end - start < 3 or end - start > 300:
            return None
        x = audio.read_range(cfg.episode_dir(e["id"]) / "blocks", start, end, cfg.sample_rate, cfg.block_seconds)
        h = fp.hashes_from_audio(x)
        if len(h) < 50:
            return None
        # evitar duplicados: si la biblioteca ya reconoce este audio, no se vuelve a añadir
        rows = conn.execute("SELECT id, kind, duration_s, hashes FROM ad_fingerprints WHERE enabled=1 AND kind=?", (kind,)).fetchall()
        idx = fp.build_index([(r["id"], r["kind"], r["duration_s"], r["hashes"]) for r in rows])
        for m in fp.match(h, idx, cfg.fp_min_votes, cfg.fp_min_fraction):
            if m["confidence"] > 0.5 and abs((m["end_s"] - m["start_s"]) - (end - start)) < 3:
                return m["fp_id"]
        cur = conn.execute(
            "INSERT INTO ad_fingerprints(channel_id,kind,label,duration_s,n_hashes,hashes,source_episode_id) VALUES (?,?,?,?,?,?,?)",
            (e["channel_id"], kind, label or e["title"], end - start, len(h), fp.pack(h), e["id"]))
        return cur.lastrowid

    def _push_history(s) -> str:
        hist = json.loads(s["history"] or "[]")
        hist.append({"start": s["start_s"], "end": s["end_s"], "user_decision": s["user_decision"]})
        return jdump(hist[-50:])

    @app.patch("/segments/{seg_id}")
    def edit_segment(seg_id: int, body: SegmentEdit):
        conn = db()
        try:
            s = _get_seg(conn, seg_id)
            e = _episode_ready(conn, s["episode_id"])
            start = s["start_s"] if body.start is None else body.start
            end = s["end_s"] if body.end is None else body.end
            if body.decision not in (None, "keep", "remove"):
                raise HTTPException(422, "decision debe ser 'keep' o 'remove'")
            if end <= start or end > (e["duration_s"] or end) + 0.01:
                raise HTTPException(422, "El inicio y el fin del tramo no son válidos")
            decision = body.decision or s["user_decision"]
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE ad_segments SET start_s=?, end_s=?, user_decision=?, history=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                         (start, end, decision, _push_history(s), seg_id))
            fp_id = None
            effective = decision or ("remove" if s["auto_decision"] == "remove" else "keep")
            if effective == "remove" and s["source"] != "fingerprint" and (body.decision == "remove" or body.start is not None or body.end is not None):
                fp_id = learn(conn, e, start, end, seg_id=seg_id)
                if fp_id:
                    conn.execute("UPDATE ad_segments SET fingerprint_id=? WHERE id=?", (fp_id, seg_id))
            if body.decision == "keep" and s["fingerprint_id"]:
                # falso positivo de una huella: tras 2 rechazos deja de usarse
                conn.execute("UPDATE ad_fingerprints SET false_positives=false_positives+1, enabled=CASE WHEN false_positives+1>=2 THEN 0 ELSE enabled END WHERE id=?", (s["fingerprint_id"],))
            touch_episode(conn, e["id"], clean_stale=1)
            conn.execute("COMMIT")
            return {"ok": True, "learned_fingerprint": fp_id}
        except HTTPException:
            _rollback(conn)
            raise
        finally:
            conn.close()

    @app.post("/segments/{seg_id}/undo")
    def undo_segment(seg_id: int):
        conn = db()
        try:
            s = _get_seg(conn, seg_id)
            hist = json.loads(s["history"] or "[]")
            if not hist:
                raise HTTPException(409, "No hay cambios que deshacer")
            prev = hist.pop()
            conn.execute("UPDATE ad_segments SET start_s=?, end_s=?, user_decision=?, history=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                         (prev["start"], prev["end"], prev["user_decision"], jdump(hist), seg_id))
            touch_episode(conn, s["episode_id"], clean_stale=1)
            return {"ok": True}
        finally:
            conn.close()

    @app.post("/episodes/{ep_id}/segments", status_code=201)
    def add_missed_ad(ep_id: int, body: Span):
        conn = db()
        try:
            e = _episode_ready(conn, ep_id)
            if body.end <= body.start or body.end > (e["duration_s"] or body.end) + 0.01:
                raise HTTPException(422, "El inicio y el fin del tramo no son válidos")
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "INSERT INTO ad_segments(episode_id,start_s,end_s,score,source,evidence,auto_decision,user_decision) VALUES (?,?,?,?,?,?,?,?)",
                (ep_id, body.start, body.end, 1.0, "user", jdump({"note": "marcado por el usuario"}), "remove", "remove"))
            fp_id = learn(conn, e, body.start, body.end)
            if fp_id:
                conn.execute("UPDATE ad_segments SET fingerprint_id=? WHERE id=?", (fp_id, cur.lastrowid))
            touch_episode(conn, ep_id, clean_stale=1)
            conn.execute("COMMIT")
            return {"id": cur.lastrowid, "learned_fingerprint": fp_id}
        except HTTPException:
            _rollback(conn)
            raise
        finally:
            conn.close()

    @app.post("/episodes/{ep_id}/protect", status_code=201)
    def protect(ep_id: int, body: Span):
        """Marca un tramo (p. ej. intro/outro) como contenido protegido: nunca se elimina."""
        conn = db()
        try:
            e = _episode_ready(conn, ep_id)
            conn.execute("BEGIN IMMEDIATE")
            fp_id = learn(conn, e, body.start, body.end, kind="protected", label=body.label or "contenido protegido")
            if not fp_id:
                conn.execute("ROLLBACK")
                raise HTTPException(422, "El tramo debe durar entre 3 y 300 segundos y contener audio")
            conn.execute("COMMIT")
            return {"fingerprint_id": fp_id}
        except HTTPException:
            _rollback(conn)
            raise
        finally:
            conn.close()

    @app.get("/fingerprints")
    def fingerprints():
        conn = db()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT id, kind, label, duration_s, n_hashes, enabled, hits, false_positives, channel_id FROM ad_fingerprints ORDER BY id")]
        finally:
            conn.close()

    return app


def _rollback(conn):
    try:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def range_response(path: Path, request: Request, media_type: str, extra: dict | None = None) -> Response:
    """Respuesta con soporte HTTP Range (206 Partial Content / 416)."""
    size = path.stat().st_size
    headers = {"Accept-Ranges": "bytes", **(extra or {})}
    rng = request.headers.get("range")
    start, end, status = 0, size - 1, 200
    if rng:
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip())
        if not m or (m.group(1) == "" and m.group(2) == ""):
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        a, b = m.groups()
        if a == "":
            n = int(b)
            start, end = max(0, size - n), size - 1
        else:
            start = int(a)
            end = min(int(b), size - 1) if b else size - 1
        if start >= size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        status = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    length = end - start + 1
    headers["Content-Length"] = str(length)
    if request.method == "HEAD":
        return Response(status_code=status, headers=headers, media_type=media_type)

    def body():
        with open(path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(1 << 16, left))
                if not chunk:
                    break
                left -= len(chunk)
                yield chunk
    return StreamingResponse(body(), status_code=status, headers=headers, media_type=media_type)


def app_factory() -> FastAPI:  # uvicorn --factory
    return create_app()
