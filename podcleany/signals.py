"""Señales acústicas auxiliares: silencio, cambios de volumen y música (heurísticas ligeras)."""
from __future__ import annotations

import numpy as np

SR = 16000
FRAME = 800            # 50 ms
SILENCE_DB = -45.0
MIN_SILENCE_S = 0.30


def frame_features(x: np.ndarray) -> dict:
    """x float32 mono 16 kHz -> rms_db por frame de 50 ms, y 'tonalidad' por segundo."""
    n = len(x) // FRAME
    if n == 0:
        return {"rms_db": np.zeros(0, np.float32), "flat": np.zeros(0, np.float32), "cv": np.zeros(0, np.float32)}
    fr = x[: n * FRAME].reshape(n, FRAME)
    rms = np.sqrt((fr ** 2).mean(axis=1) + 1e-12)
    rms_db = (20 * np.log10(rms + 1e-9)).astype(np.float32)
    per_s = 20  # frames de 50 ms por segundo
    m = n // per_s
    flat = np.zeros(m, np.float32)
    cv = np.zeros(m, np.float32)
    if m:
        win = np.hanning(FRAME)
        for i in range(m):
            seg = fr[i * per_s: (i + 1) * per_s]
            spec = np.abs(np.fft.rfft(seg * win, axis=1)) + 1e-9
            g = np.exp(np.log(spec).mean(axis=1)) / spec.mean(axis=1)   # planitud espectral por frame
            flat[i] = g.mean()
            r = rms[i * per_s: (i + 1) * per_s]
            cv[i] = r.std() / (r.mean() + 1e-9)                           # modulación de energía
    return {"rms_db": rms_db, "flat": flat, "cv": cv}


def silences(rms_db: np.ndarray, offset_s: float = 0.0) -> list[tuple[float, float]]:
    """Intervalos de silencio (inicio, fin) en segundos absolutos."""
    quiet = rms_db < SILENCE_DB
    out, i, n = [], 0, len(quiet)
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if (j - i) * FRAME / SR >= MIN_SILENCE_S:
                out.append((offset_s + i * FRAME / SR, offset_s + j * FRAME / SR))
            i = j
        else:
            i += 1
    return out


def music_score(flat: np.ndarray, cv: np.ndarray, a: float, b: float) -> float:
    """Fracción de segundos [a,b) con perfil tipo música/cama sonora: tonal y poca modulación."""
    i0, i1 = int(a), int(np.ceil(b))
    f, c = flat[i0:i1], cv[i0:i1]
    if len(f) == 0:
        return 0.0
    return float(np.mean((f < 0.12) & (c < 0.5)))


def loudness_jump(rms_db: np.ndarray, t: float, span_s: float = 2.0) -> float:
    """Salto de volumen (dB, 0..1 normalizado a 10 dB) alrededor de t."""
    k = int(span_s * SR / FRAME)
    i = int(t * SR / FRAME)
    if i - k < 0 or i + k > len(rms_db):
        return 0.0
    before = rms_db[i - k:i]
    after = rms_db[i:i + k]
    # promedio de la energía activa (ignora silencios)
    b = before[before > SILENCE_DB]
    a = after[after > SILENCE_DB]
    if len(a) < 5 or len(b) < 5:
        return 0.0
    return float(min(1.0, abs(a.mean() - b.mean()) / 10.0))
