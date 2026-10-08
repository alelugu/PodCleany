"""Resolución de URL/RSS y descarga HTTPS (única conexión saliente durante la operación)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests

AUDIO_EXT = (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav")
UA = {"User-Agent": "PodCleany/0.1 (+local)"}


class InvalidUrl(ValueError):
    pass


def validate_url(url: str) -> str:
    url = (url or "").strip()
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise InvalidUrl("La dirección debe empezar por http:// o https:// e incluir el dominio.")
    if len(url) > 2000:
        raise InvalidUrl("La dirección es demasiado larga.")
    return url


def normalize_key(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc.lower()}{p.path}" + (f"?{p.query}" if p.query else "")


@dataclass
class EpisodeInfo:
    title: str
    channel_name: str
    rss_url: str
    audio_url: str
    guid: str
    description: str = ""
    cover_url: str | None = None


def _get(url: str, timeout: float, **kw):
    r = requests.get(url, headers=UA, timeout=timeout, **kw)
    r.raise_for_status()
    return r


def resolve(url: str, timeout: float = 60.0) -> EpisodeInfo:
    """URL de audio directo o de RSS (se toma el episodio más reciente)."""
    if urlparse(url).path.lower().endswith(AUDIO_EXT):
        host = urlparse(url).netloc
        name = os.path.basename(urlparse(url).path) or "episodio"
        return EpisodeInfo(title=re.sub(r"\.\w+$", "", name), channel_name=host, rss_url=f"direct:{host}",
                           audio_url=url, guid=url)
    r = _get(url, timeout)
    ctype = r.headers.get("content-type", "")
    if ctype.startswith("audio/"):
        return resolve_direct(url)
    feed = feedparser.parse(r.content)
    if not feed.entries:
        raise ValueError("No se encontró un episodio en esa dirección. Pegue el enlace del RSS o del archivo de audio.")
    for ent in feed.entries:
        enc = [l for l in ent.get("links", []) if l.get("rel") == "enclosure"] or ent.get("enclosures", [])
        if enc:
            href = enc[0].get("href") or enc[0].get("url")
            cover = (ent.get("image") or {}).get("href") or (feed.feed.get("image") or {}).get("href")
            return EpisodeInfo(
                title=ent.get("title", "Episodio"), channel_name=feed.feed.get("title", urlparse(url).netloc),
                rss_url=url, audio_url=href, guid=ent.get("id") or href,
                description=re.sub(r"<[^>]+>", "", ent.get("summary", ""))[:2000], cover_url=cover)
    raise ValueError("El RSS no contiene episodios con audio.")


def resolve_direct(url: str) -> EpisodeInfo:
    host = urlparse(url).netloc
    return EpisodeInfo(title=os.path.basename(urlparse(url).path) or "episodio", channel_name=host,
                       rss_url=f"direct:{host}", audio_url=url, guid=url)


def download(url: str, dst: Path, timeout: float = 60.0, progress=None) -> int:
    """Descarga por streaming a .part y renombra de forma atómica."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    with _get(url, timeout, stream=True) as r:
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done / total)
    os.replace(tmp, dst)
    return dst.stat().st_size


def download_small(url: str, dst: Path, timeout: float = 30.0, max_bytes: int = 5_000_000) -> bool:
    try:
        r = _get(url, timeout)
        if len(r.content) > max_bytes:
            return False
        dst.write_bytes(r.content)
        return True
    except Exception:
        return False
