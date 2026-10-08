"""Audio sintético reproducible para pruebas y notebooks (no es voz real)."""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 16000


def speech_like(seconds: float, seed: int) -> np.ndarray:
    """Sílabas armónicas con envolvente ~4 Hz y pausas aleatorias: proxy de habla."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(seconds * SR), np.float32)
    t = 0.0
    while t < seconds:
        dur = rng.uniform(0.12, 0.35)
        f0 = rng.uniform(90, 220)
        n = int(dur * SR)
        tt = np.arange(n) / SR
        formants = rng.uniform(300, 2800, 3)
        sig = np.zeros(n)
        for h in range(1, 25):
            f = f0 * h
            amp = sum(np.exp(-((f - fm) / 250.0) ** 2) for fm in formants)
            sig += amp * np.sin(2 * np.pi * f * tt + rng.uniform(0, 6.28))
        env = np.sin(np.pi * tt / dur) ** 2
        s = int(t * SR)
        seg = (sig * env * 0.12).astype(np.float32)
        out[s:s + n] += seg[: len(out) - s]
        t += dur + (rng.uniform(0.35, 0.9) if rng.random() < 0.12 else rng.uniform(0.01, 0.06))
    return out


def jingle(seconds: float, seed: int) -> np.ndarray:
    """Cuña publicitaria: melodía con acordes, ruido y más volumen. Idéntica para el mismo seed."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    out = np.zeros(n, np.float32)
    t = 0.0
    while t < seconds:
        dur = rng.choice([0.25, 0.5, 0.75])
        root = rng.choice([262, 294, 330, 349, 392, 440, 494, 523]) * rng.choice([1, 1, 2])
        tt = np.arange(int(dur * SR)) / SR
        chord = sum(np.sin(2 * np.pi * root * r * tt) / (i + 1) for i, r in enumerate([1, 1.26, 1.5, 2.0]))
        env = np.minimum(1, tt * 40) * np.exp(-tt * 2.5)
        s = int(t * SR)
        seg = (chord * env * 0.3).astype(np.float32)
        out[s:s + len(seg)] += seg[: n - s]
        t += dur
    out += rng.normal(0, 0.01, n).astype(np.float32)
    return out


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SR), np.float32)


def write_wav(path: Path, x: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def to_mp3(x: np.ndarray, path: Path) -> None:
    from .audio import ffmpeg_path
    p = subprocess.run([ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "s16le", "-ar", str(SR), "-ac", "1",
                        "-i", "pipe:0", "-c:a", "libmp3lame", "-b:a", "96k", str(path)],
                       input=(np.clip(x, -1, 1) * 32767).astype("<i2").tobytes(), capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.decode()[-300:])


def make_episode(parts: list[tuple[str, float, int]]) -> tuple[np.ndarray, list[tuple[float, float, str]]]:
    """parts: [('speech'|'ad'|'intro'|'silence', segundos, seed)] -> (audio, [(inicio, fin, tipo)])."""
    chunks, marks, t = [], [], 0.0
    for kind, sec, seed in parts:
        if kind == "speech":
            c = speech_like(sec, seed)
        elif kind in ("ad", "intro"):
            c = jingle(sec, seed) * (1.6 if kind == "ad" else 1.0)
        else:
            c = silence(sec)
        chunks.append(c)
        marks.append((t, t + sec, kind))
        t += sec
    return np.concatenate(chunks), marks
