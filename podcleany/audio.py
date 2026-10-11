"""ffmpeg: localización, decodificación por pipes, normalización por bloques, edición con crossfade."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import wave
from pathlib import Path

import numpy as np

_NOWIN = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW


def ffmpeg_path() -> str:
    env = os.environ.get("PODCLEANY_FFMPEG")
    if env:
        return env
    try:  # binario empaquetado en wheel: no requiere toolchain en Windows/macOS
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("No se encontró ffmpeg. Instale las dependencias (pip install -r requirements.txt).")
    return found


def probe_duration(path: Path) -> float | None:
    """Duración declarada por el contenedor (ffmpeg -i; no requiere ffprobe)."""
    p = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", str(path)], capture_output=True, text=True, **_NOWIN)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", p.stderr)
    if not m:
        return None
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def _write_wav(path: Path, samples: np.ndarray, sr: int) -> None:
    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(samples.astype("<i2").tobytes())
    os.replace(tmp, path)


def block_path(blocks_dir: Path, idx: int) -> Path:
    return blocks_dir / f"block_{idx:04d}.wav"


def normalize_to_blocks(src: Path, blocks_dir: Path, sr: int, block_seconds: int, progress=None) -> dict:
    """Decodifica con ffmpeg (stdin->stdout, pipes) a 16 kHz mono y escribe bloques WAV de ~10 min.

    Nunca mantiene el episodio completo en RAM. Los bloques ya existentes se omiten (checkpoint).
    """
    blocks_dir.mkdir(parents=True, exist_ok=True)
    total = _normalize_pipe(src, blocks_dir, sr, block_seconds, progress, use_pipe=True)
    if total == 0:  # p. ej. m4a con moov al final no es decodificable desde pipe
        total = _normalize_pipe(src, blocks_dir, sr, block_seconds, progress, use_pipe=False)
    if total == 0:
        raise RuntimeError("ffmpeg no produjo audio; ¿archivo corrupto o formato no soportado?")
    return {"samples": total, "duration_s": total / sr, "blocks": (total + sr * block_seconds - 1) // (sr * block_seconds)}


def _normalize_pipe(src, blocks_dir, sr, block_seconds, progress, use_pipe: bool) -> int:
    cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-i", "pipe:0" if use_pipe else str(src),
           "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "pipe:1"]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if use_pipe else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_NOWIN)
    errbuf: list[bytes] = []

    def feed():
        try:
            with open(src, "rb") as f:
                while chunk := f.read(1 << 20):
                    proc.stdin.write(chunk)
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    threads = [threading.Thread(target=lambda: errbuf.append(proc.stderr.read()), daemon=True)]
    if use_pipe:
        threads.append(threading.Thread(target=feed, daemon=True))
    for t in threads:
        t.start()
    block_bytes = sr * block_seconds * 2
    idx = total = 0
    while True:
        data = proc.stdout.read(block_bytes)
        while data and len(data) < block_bytes:
            more = proc.stdout.read(block_bytes - len(data))
            if not more:
                break
            data += more
        if not data:
            break
        total += len(data) // 2
        bp = block_path(blocks_dir, idx)
        if not bp.exists():
            _write_wav(bp, np.frombuffer(data[: len(data) // 2 * 2], dtype="<i2"), sr)
        idx += 1
        if progress:
            progress(idx)
    proc.wait()
    for t in threads:
        t.join(timeout=5)
    if proc.returncode != 0 and total == 0 and not use_pipe:
        raise RuntimeError("ffmpeg falló: " + b"".join(errbuf).decode(errors="replace")[-500:])
    return total


def read_block(blocks_dir: Path, idx: int) -> np.ndarray:
    with wave.open(str(block_path(blocks_dir, idx)), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


def count_blocks(blocks_dir: Path) -> int:
    return len(list(blocks_dir.glob("block_*.wav")))


def read_range(blocks_dir: Path, start_s: float, end_s: float, sr: int, block_seconds: int) -> np.ndarray:
    """Lee [start_s, end_s) como float32 (-1..1) sin cargar todo el episodio."""
    s0, s1 = int(max(0, start_s) * sr), int(max(0, end_s) * sr)
    bl = sr * block_seconds
    out = []
    for idx in range(s0 // bl, (max(s1 - 1, s0)) // bl + 1):
        if not block_path(blocks_dir, idx).exists():
            break
        blk = read_block(blocks_dir, idx)
        a, b = max(s0 - idx * bl, 0), min(s1 - idx * bl, len(blk))
        if b > a:
            out.append(blk[a:b])
    if not out:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(out).astype(np.float32) / 32768.0


# ------------------------------------------------------------------- edición
def keep_intervals(duration: float, removals: list[tuple[float, float]], min_keep: float) -> list[tuple[float, float]]:
    """Complemento de las regiones eliminadas. Tramos conservados < min_keep se descartan."""
    merged: list[list[float]] = []
    for s, e in sorted((max(0.0, s), min(duration, e)) for s, e in removals if e > s):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    keeps, pos = [], 0.0
    for s, e in merged:
        if s - pos >= min_keep:
            keeps.append((pos, s))
        pos = e
    if duration - pos >= min_keep:
        keeps.append((pos, duration))
    return keeps


def _publish(tmp: Path, dst: Path) -> Path:
    """Mueve tmp -> dst. En Windows no se puede reemplazar un archivo abierto (p. ej. el reproductor del
    navegador lo está leyendo): se reintenta y, si sigue bloqueado, se guarda con otro nombre ("… (2).mp3")."""
    import time
    for _ in range(5):
        try:
            os.replace(tmp, dst)
            return dst
        except PermissionError:
            time.sleep(0.4)
    n = 2
    while True:
        alt = dst.with_name(f"{dst.stem} ({n}){dst.suffix}")
        try:
            if not alt.exists():
                os.replace(tmp, alt)
                return alt
        except PermissionError:
            pass
        n += 1
        if n > 99:
            raise PermissionError(f"No se pudo guardar {dst.name}: cierre el reproductor que lo usa e intente de nuevo.")


def render_clean(src: Path, dst: Path, duration: float, removals: list[tuple[float, float]],
                 crossfade_ms: int, min_keep: float) -> float:
    """Como render_clean_path pero devuelve solo la duración final."""
    return render_clean_path(src, dst, duration, removals, crossfade_ms, min_keep)[1]


def render_clean_path(src: Path, dst: Path, duration: float, removals: list[tuple[float, float]],
                      crossfade_ms: int, min_keep: float) -> tuple[Path, float]:
    """Genera el MP3 final a partir del ORIGINAL (nunca se sobrescribe) con crossfade breve.

    Devuelve (ruta real, duración): la ruta puede diferir de `dst` si éste estaba bloqueado."""
    keeps = keep_intervals(duration, removals, min_keep)
    if not keeps:
        raise RuntimeError("El resultado quedaría vacío: todo el episodio está marcado como anuncio.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.stem + ".part" + dst.suffix)
    cf = crossfade_ms / 1000.0
    # el crossfade necesita tramos más largos que su duración
    keeps = [k for k in keeps if k[1] - k[0] > cf * 2] or keeps
    parts, labels = [], []
    for i, (s, e) in enumerate(keeps):
        parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[a{i}]")
    if len(keeps) == 1:
        graph = parts[0].replace("[a0]", "[out]")
    else:
        chain, prev = [], "[a0]"
        for i in range(1, len(keeps)):
            out = "[out]" if i == len(keeps) - 1 else f"[x{i}]"
            chain.append(f"{prev}[a{i}]acrossfade=d={cf:.3f}:c1=tri:c2=tri{out}")
            prev = out
        graph = ";".join(parts + chain)
    graph_file = dst.parent / (dst.stem + ".filter.txt")
    graph_file.write_text(graph, encoding="utf-8")
    cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
           "-filter_complex_script", str(graph_file), "-map", "[out]",
           "-c:a", "libmp3lame", "-q:a", "2", "-f", "mp3", str(tmp)]
    p = subprocess.run(cmd, capture_output=True, text=True, **_NOWIN)
    graph_file.unlink(missing_ok=True)
    if p.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg falló al generar el audio: " + p.stderr[-500:])
    final = _publish(tmp, dst)
    return final, (probe_duration(final) or sum(e - s for s, e in keeps))
