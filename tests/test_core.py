import multiprocessing as mp
import numpy as np
from pathlib import Path

from podcleany import audio, fingerprint as fp, synth
from podcleany.config import Config
from podcleany.db import claim_job, enqueue, open_db, connect, migrate


def test_fingerprint_roundtrip_and_no_false_positive(tmp_path):
    ad = synth.jingle(15, 7)
    idx = fp.build_index([(1, "ad", 15.0, fp.pack(fp.hashes_from_audio(ad)))])
    ep, marks = synth.make_episode([("speech", 25, 1), ("ad", 15, 7), ("speech", 20, 2)])
    mp3 = tmp_path / "e.mp3"
    synth.to_mp3(ep, mp3)
    audio.normalize_to_blocks(mp3, tmp_path / "b", 16000, 30)
    x = np.concatenate([audio.read_block(tmp_path / "b", i) for i in range(audio.count_blocks(tmp_path / "b"))]).astype(np.float32) / 32768
    m = fp.match(fp.hashes_from_audio(x), idx)
    assert len(m) == 1 and abs(m[0]["start_s"] - 25) < 0.3          # tras MP3 sigue reconociéndose
    assert fp.match(fp.hashes_from_audio(synth.speech_like(60, 9)), idx) == []


def test_normalize_blocks_and_range_read(tmp_path):
    x, _ = synth.make_episode([("speech", 70, 3)])
    mp3 = tmp_path / "e.mp3"
    synth.to_mp3(x, mp3)
    info = audio.normalize_to_blocks(mp3, tmp_path / "b", 16000, 30)
    assert info["blocks"] == 3 and abs(info["duration_s"] - 70) < 0.2
    seg = audio.read_range(tmp_path / "b", 25, 35, 16000, 30)   # cruza el límite de bloque
    assert len(seg) == 160000


def test_render_removes_and_crossfades(tmp_path):
    x, _ = synth.make_episode([("speech", 20, 1), ("ad", 10, 5), ("speech", 20, 2)])
    src = tmp_path / "o.mp3"
    synth.to_mp3(x, src)
    before = src.read_bytes()
    dur = audio.probe_duration(src)
    out = audio.render_clean(src, tmp_path / "c.mp3", dur, [(20, 30)], 60, 0.25)
    assert abs(out - (dur - 10 - 0.06)) < 0.15
    assert src.read_bytes() == before                      # original intacto
    audio.normalize_to_blocks(tmp_path / "c.mp3", tmp_path / "cb", 16000, 60)
    y = audio.read_range(tmp_path / "cb", 0, out, 16000, 60)
    j = int(20 * 16000)
    assert np.abs(y[j - 800:j + 800]).max() < 0.9          # sin clipping en el empalme
    assert np.abs(np.diff(y[j - 400:j + 400])).max() < 0.5  # sin salto brusco (clic)


def test_keep_intervals():
    assert audio.keep_intervals(100, [(10, 20), (15, 30), (99.9, 100)], 0.25) == [(0, 10), (30, 99.9)]


def test_migrations_wal_dedupe(tmp_path):
    cfg = Config.load(tmp_path)
    conn = open_db(cfg)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"jobs", "channels", "episodes", "ad_segments", "ad_fingerprints"} <= names
    a, d1 = enqueue(conn, "process", "k", url="http://x/a.mp3")
    b, d2 = enqueue(conn, "process", "k", url="http://x/a.mp3")
    assert a == b and not d1 and d2
    assert migrate(conn) == 1                                # idempotente


def _claimer(path, n, q):
    conn = connect(path)
    got = []
    while (j := claim_job(conn, f"w{mp.current_process().pid}")) is not None:
        got.append(j["id"])
    q.put(got)


def test_atomic_claim_no_duplicates(tmp_path):
    cfg = Config.load(tmp_path)
    conn = open_db(cfg)
    for i in range(60):
        enqueue(conn, "process", f"k{i}", url=f"http://x/{i}.mp3")
    q = mp.Queue()
    ps = [mp.Process(target=_claimer, args=(str(cfg.db_path), 60, q)) for _ in range(4)]
    [p.start() for p in ps]
    results = [q.get(timeout=60) for _ in ps]
    [p.join() for p in ps]
    flat = [i for r in results for i in r]
    assert sorted(flat) == list(range(1, 61))                # todos reclamados exactamente una vez


def test_stale_running_job_is_requeued(tmp_path):
    import time
    from podcleany.db import requeue_stale
    conn = open_db(Config.load(tmp_path))
    jid, _ = enqueue(conn, "process", "k", url="http://x/a.mp3")
    claim_job(conn, "w-muerto")
    assert requeue_stale(conn, 60) == 0                      # latido reciente: sigue en ejecución
    conn.execute("UPDATE jobs SET heartbeat_at=? WHERE id=?", (time.time() - 1000, jid))
    assert requeue_stale(conn, 60) == 1
    assert claim_job(conn, "w2")["id"] == jid                # otro worker lo retoma
