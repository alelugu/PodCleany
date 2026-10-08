"""Flujo completo E.6 (pasos 1-11) con servidor HTTP local, API y worker reales."""
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from podcleany import audio, synth, worker
from podcleany.api import create_app
from podcleany.config import Config


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture()
def env(tmp_path, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    # ep1: intro + habla + anuncio fuerte A + habla + anuncio débil B + habla
    ep1, m1 = synth.make_episode([("intro", 8, 99), ("speech", 30, 1), ("silence", 1.5, 0), ("ad", 20, 7), ("silence", 1.5, 0),
                                  ("speech", 30, 2), ("silence", 1.5, 0), ("ad", 15, 11), ("silence", 1.5, 0), ("speech", 25, 3)])
    # ep2: misma intro, mismo anuncio A en otra posición, sin B
    ep2, m2 = synth.make_episode([("intro", 8, 99), ("speech", 40, 4), ("silence", 1.5, 0), ("ad", 20, 7), ("silence", 1.5, 0), ("speech", 30, 5)])
    synth.to_mp3(ep1, web / "ep1.mp3")
    synth.to_mp3(ep2, web / "ep2.mp3")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(web)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    for n in (1, 2):
        (web / f"feed{n}.xml").write_text(f"""<?xml version="1.0"?><rss version="2.0"><channel><title>Canal de Prueba</title>
<item><title>Episodio {n}</title><guid>guid-{n}</guid><description>Descripción {n}</description>
<enclosure url="{base}/ep{n}.mp3" type="audio/mpeg"/></item></channel></rss>""")
    truth = tmp_path / "truth.json"
    monkeypatch.setenv("PODCLEANY_FAKE_TRUTH", str(truth))
    cfg = Config.load(tmp_path / "data")
    cfg.backend_factory = "tests.fakes:make_backends"
    cfg.block_seconds = 60
    client = TestClient(create_app(cfg))
    yield dict(cfg=cfg, client=client, base=base, truth=truth, m1=m1, m2=m2, srv=srv)
    srv.shutdown()


def run_worker(cfg):
    worker.run(cfg, stop_when_idle=True)


def submit(c, url):
    r = c.post("/episodes", json={"url": url})
    assert r.status_code == 202
    return r.json()


def test_full_flow(env):
    c, cfg, base = env["client"], env["cfg"], env["base"]
    assert c.post("/episodes", json={"url": "ftp://x"}).status_code == 422
    # 1-2: enviar y encolar (202) + deduplicación
    j1 = submit(c, f"{base}/feed1.xml")
    assert j1["status"] == "queued" and not j1["duplicate"]
    assert submit(c, f"{base}/feed1.xml")["duplicate"] is True
    # La API sigue disponible sin worker
    assert c.get("/health").status_code == 200 and c.get("/library").json() == []
    env["truth"].write_text(json.dumps([[0, 8, "strong"], [39.5, 59.5, "strong"], [92.5, 107.5, "weak"]]))
    # SSE y worker
    run_worker(cfg)
    job = c.get(f"/jobs/{j1['job_id']}").json()
    assert job["status"] == "done", job
    with c.stream("GET", f"/jobs/{j1['job_id']}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        assert '"status": "done"' in "".join(r.iter_text())
    ep = c.get(f"/episodes/{job['episode_id']}").json()
    assert ep["title"] == "Episodio 1" and ep["channel"] == "Canal de Prueba" and ep["description"] == "Descripción 1"
    segs = ep["segments"]
    by = lambda a: min(segs, key=lambda s: abs(s["start"] - a))
    A, B, intro = by(39.5), by(92.5), by(0)
    assert A["kind"] == "detected" and abs(A["start"] - 39.5) < 2 and abs(A["end"] - 59.5) < 2
    assert B["kind"] == "possible" and B["decision"] == "keep"        # entre umbrales: revisión
    assert intro["start"] < 1                                          # la intro se detecta como "anuncio" (trampa)
    # 11: el usuario conserva la intro y la protege; confirma A y B; añade un ajuste
    assert c.patch(f"/segments/{intro['id']}", json={"decision": "keep"}).status_code == 200
    assert c.post(f"/episodes/{ep['id']}/protect", json={"start": 0, "end": 8, "label": "intro"}).status_code == 201
    ra = c.patch(f"/segments/{A['id']}", json={"decision": "remove"}).json()
    rb = c.patch(f"/segments/{B['id']}", json={"decision": "remove", "start": 91, "end": 108.5}).json()
    assert ra["learned_fingerprint"] and rb["learned_fingerprint"]
    # deshacer
    c.patch(f"/segments/{B['id']}", json={"decision": "keep"})
    assert c.post(f"/segments/{B['id']}/undo").status_code == 200
    seg_b = [s for s in c.get(f"/episodes/{ep['id']}").json()["segments"] if s["id"] == B["id"]][0]
    assert seg_b["decision"] == "remove" and seg_b["start"] == 91
    # 10: generar y descargar
    assert c.get(f"/episodes/{ep['id']}/audio/clean").status_code in (404, 409)
    rj = c.post(f"/episodes/{ep['id']}/render")
    assert rj.status_code == 202
    run_worker(cfg)
    ep = c.get(f"/episodes/{ep['id']}").json()
    assert ep["clean"]["ready"] and ep["clean"]["format"] == "MP3" and ep["clean"]["name"].endswith("(sin anuncios).mp3")
    orig_dur = ep["duration"]
    assert 30 < ep["clean"]["removed"] < 45
    # Range 206
    r = c.get(f"/episodes/{ep['id']}/audio/clean", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206 and len(r.content) == 100 and r.headers["content-range"].startswith("bytes 100-199/")
    assert c.get(f"/episodes/{ep['id']}/audio/clean", headers={"Range": "bytes=99999999-"}).status_code == 416
    full = c.get(f"/episodes/{ep['id']}/audio/clean?download=1")
    assert full.status_code == 200 and "attachment" in full.headers["content-disposition"]
    out = Path(cfg.data_dir / "dl.mp3")
    out.write_bytes(full.content)
    assert abs(audio.probe_duration(out) - ep["clean"]["duration"]) < 0.2    # el archivo descargado == decisiones finales
    assert Path(ep["clean"]["name"]).name and (cfg.library_dir / "Canal de Prueba").exists()
    # tras editar, el resultado queda obsoleto
    c.patch(f"/segments/{A['id']}", json={"decision": "keep"})
    assert c.get(f"/episodes/{ep['id']}").json()["clean"]["stale"] is True
    c.post(f"/segments/{A['id']}/undo")

    # ---- Episodio 2: reconoce A por huella (sin transcribirlo) y respeta la intro protegida
    env["truth"].write_text(json.dumps([[0, 8, "strong"], [41.5 + 8 - 8 + 0, 41.5, "none"]]))   # solo la intro sería "anuncio"
    env["truth"].with_suffix(".calls").unlink(missing_ok=True)
    j2 = submit(c, f"{base}/feed2.xml")
    run_worker(cfg)
    ep2 = c.get(f"/episodes/{c.get(f'/jobs/{j2['job_id']}').json()['episode_id']}").json()
    assert c.get(f"/jobs/{j2['job_id']}").json()["status"] == "done"
    segs2 = ep2["segments"]
    assert len(segs2) == 1, segs2                                      # solo A; la intro protegida no es anuncio
    s = segs2[0]
    assert s["source"] == "fingerprint" and s["decision"] == "remove"
    assert abs(s["start"] - 49.5) < 1.5 and abs(s["end"] - 71.5) < 1.5   # A cae en [49.5, 69.5] + silencios
    calls = [json.loads(l) for l in env["truth"].with_suffix(".calls").read_text().splitlines()]
    assert all(b <= s["start"] + 1 or a >= s["end"] - 1 for a, b in calls), calls   # nunca se transcribió la región conocida
    assert not any(a < 8 for a, b in calls)                              # ni el contenido protegido
    # sin conexión: render y feedback no tocan la red
    env["srv"].shutdown()
    assert c.post(f"/episodes/{ep2['id']}/render").status_code == 202
    run_worker(cfg)
    assert c.get(f"/episodes/{ep2['id']}").json()["clean"]["ready"]
    # métricas
    m = json.loads(sqlite_get(cfg, "SELECT metrics FROM episodes WHERE id=?", ep2["id"]))
    assert m["timings"]["total_s"] > 0 and m["resources"]["peak_rss_mb"] > 0


def sqlite_get(cfg, q, *a):
    from podcleany.db import open_db
    return open_db(cfg).execute(q, a).fetchone()[0]


def test_failure_is_reported_and_api_survives(env):
    c, cfg, base = env["client"], env["cfg"], env["base"]
    j = submit(c, f"{base}/no-existe.mp3")
    run_worker(cfg)
    job = c.get(f"/jobs/{j['job_id']}").json()
    assert job["status"] == "failed" and "404" in job["error"]
    assert c.get("/health").status_code == 200
    # un fallo permite reintentar la misma URL
    assert submit(c, f"{base}/no-existe.mp3")["duplicate"] is False
