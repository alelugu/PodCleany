"""Fingerprinting acústico propio (pares de picos espectrales, estilo Shazam) con numpy/scipy.

Sin dependencias nativas: instalable por wheel en Windows y macOS (Intel y Apple Silicon).
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import maximum_filter
from scipy.signal import stft

SR = 16000
N_FFT = 1024
HOP = 256                      # 16 ms por frame
FRAME_S = HOP / SR
FAN_OUT = 5
DT_MIN, DT_MAX = 1, 63         # ~1 s de ventana de emparejado
PEAK_NEIGHBORHOOD = (15, 15)   # (frecuencia, tiempo)
OFFSET_BIN = 4                 # tolerancia de alineación (frames)


CHUNK_FRAMES = 3750            # ~60 s: acota la RAM del espectrograma (un bloque de 10 min ocuparía cientos de MB)


def hashes_from_audio(x: np.ndarray, frame_offset: int = 0) -> np.ndarray:
    """Devuelve array (n,2) uint32 [hash, frame_absoluto] para audio float32 mono 16 kHz."""
    step = CHUNK_FRAMES * HOP
    if len(x) <= step + N_FFT:
        return _hashes_chunk(x.astype(np.float32, copy=False), frame_offset)
    parts = [_hashes_chunk(x[i:i + step + N_FFT].astype(np.float32, copy=False), frame_offset + i // HOP)
             for i in range(0, len(x), step)]
    return np.concatenate(parts)


def _hashes_chunk(x: np.ndarray, frame_offset: int) -> np.ndarray:
    if len(x) < N_FFT * 2:
        return np.zeros((0, 2), dtype=np.uint32)
    _, _, Z = stft(x, fs=SR, nperseg=N_FFT, noverlap=N_FFT - HOP, boundary=None, padded=False)
    mag = np.log1p(np.abs(Z) * 100.0)[8:400]            # ~125 Hz - 6.2 kHz
    local_max = maximum_filter(mag, size=PEAK_NEIGHBORHOOD) == mag
    thresh = np.percentile(mag, 90)
    fi, ti = np.nonzero(local_max & (mag > thresh))
    if len(fi) == 0:
        return np.zeros((0, 2), dtype=np.uint32)
    order = np.argsort(ti, kind="stable")
    fi, ti = fi[order].astype(np.int64), ti[order].astype(np.int64)
    out = []
    n = len(ti)
    for k in range(1, FAN_OUT + 1):
        # emparejar cada ancla con los k-ésimos picos siguientes dentro de la ventana temporal
        j = np.arange(n - k)
        dt = ti[j + k] - ti[j]
        ok = (dt >= DT_MIN) & (dt <= DT_MAX)
        j = j[ok]
        h = ((fi[j] & 0x1FF) << 15) | ((fi[j + k] & 0x1FF) << 6) | (dt[ok] & 0x3F)
        out.append(np.stack([h, ti[j] + frame_offset], axis=1))
    res = np.concatenate(out) if out else np.zeros((0, 2), dtype=np.int64)
    return res.astype(np.uint32)


def pack(h: np.ndarray) -> bytes:
    return np.ascontiguousarray(h, dtype="<u4").tobytes()


def unpack(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype="<u4").reshape(-1, 2)


def build_index(rows) -> dict | None:
    """rows: iterable de (fp_id, kind, duration_s, hashes_bytes) -> índice ordenado por hash."""
    hs, fs, ids = [], [], []
    meta = {}
    for fp_id, kind, dur, blob in rows:
        h = unpack(blob)
        if len(h) == 0:
            continue
        hs.append(h[:, 0])
        fs.append(h[:, 1])
        ids.append(np.full(len(h), fp_id, dtype=np.int64))
        meta[fp_id] = {"kind": kind, "duration_s": dur, "n": len(h)}
    if not hs:
        return None
    H, F, I = np.concatenate(hs), np.concatenate(fs).astype(np.int64), np.concatenate(ids)
    o = np.argsort(H, kind="stable")
    return {"H": H[o], "F": F[o], "I": I[o], "meta": meta}


def match(query: np.ndarray, index: dict | None, min_votes: int = 25, min_fraction: float = 0.15) -> list[dict]:
    """Busca coincidencias de la biblioteca en `query` (hashes del episodio).

    Devuelve [{fp_id, kind, start_s, end_s, votes, confidence}] ordenado por inicio.
    """
    if index is None or len(query) == 0:
        return []
    Q = query[:, 0]
    lo = np.searchsorted(index["H"], Q, "left")
    hi = np.searchsorted(index["H"], Q, "right")
    cnt = hi - lo
    sel = cnt > 0
    if not sel.any():
        return []
    cnt_s, lo_s = cnt[sel], lo[sel]
    qf = np.repeat(query[sel, 1].astype(np.int64), cnt_s)
    starts = np.repeat(lo_s, cnt_s)
    within = np.arange(cnt_s.sum()) - np.repeat(np.cumsum(cnt_s) - cnt_s, cnt_s)
    idx = starts + within
    offs = qf - index["F"][idx]
    ids = index["I"][idx]
    bins = np.floor_divide(offs, OFFSET_BIN)
    keys = np.stack([ids, bins], axis=1)
    uniq, votes = np.unique(keys, axis=0, return_counts=True)
    results = []
    by_fp: dict[int, list] = {}
    for (fid, b), v in zip(uniq, votes):
        by_fp.setdefault(int(fid), []).append((int(b), int(v)))
    for fid, items in by_fp.items():
        items.sort()
        bd = dict(items)
        # fusionar picos contiguos y buscar máximos locales (puede haber varias apariciones)
        cand = sorted(items, key=lambda t: -t[1])
        taken: list[int] = []
        for b, v in cand:
            tot = bd.get(b - 1, 0) + v + bd.get(b + 1, 0)
            meta = index["meta"][fid]
            need = max(min_votes, min_fraction * meta["n"])
            if tot < need:
                break
            if any(abs(b - t) <= 8 for t in taken):
                continue
            taken.append(b)
            start_frame = b * OFFSET_BIN
            start = max(0.0, start_frame * FRAME_S)
            results.append({
                "fp_id": fid, "kind": meta["kind"], "start_s": start,
                "end_s": start + meta["duration_s"], "votes": int(tot),
                "confidence": float(min(1.0, tot / (0.5 * meta["n"]))),
            })
    results.sort(key=lambda r: r["start_s"])
    return results
