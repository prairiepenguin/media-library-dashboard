from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path

TRACK_RE = re.compile(r"^(?P<number>\d{1,3})[ ._-]+(?P<title>.+)$")
BARE_TRACK_RE = re.compile(r"^track\s*(?P<number>\d{1,3})$", re.IGNORECASE)
YEAR_RE = re.compile(r"^(?P<year>(?:19|20)\d{2})\s*[-–—]\s*(?P<album>.+)$")
DISC_RE = re.compile(r"\b(?:disc|disk|cd)\s*(?P<number>\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Track:
    path: str
    relative_path: str
    artist: str
    album: str
    title: str
    track_number: int | None
    track_total: int | None
    disc_number: int | None
    year: int | None
    size: int
    mtime_ns: int
    fingerprint: str

    def to_dict(self) -> dict:
        return asdict(self)


def _clean_album(name: str) -> tuple[str, int | None]:
    match = YEAR_RE.match(name)
    return (match.group("album"), int(match.group("year"))) if match else (name, None)


def _track_parts(stem: str) -> tuple[str, int | None]:
    match = TRACK_RE.match(stem)
    if match:
        return match.group("title"), int(match.group("number"))
    bare = BARE_TRACK_RE.match(stem)
    return (stem, int(bare.group("number"))) if bare else (stem, None)


def _disc_number(parts: tuple[str, ...]) -> int | None:
    for part in reversed(parts):
        match = DISC_RE.search(part)
        if match:
            return int(match.group("number"))
    return None


def scan(root: Path) -> list[Track]:
    root = root.expanduser().resolve()
    candidates = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".wav")
    grouped: dict[Path, list[Path]] = {}
    for path in candidates:
        grouped.setdefault(path.parent, []).append(path)

    tracks: list[Track] = []
    for path in candidates:
        relative = path.relative_to(root)
        artist = relative.parts[0]
        album, year = _clean_album(relative.parts[1]) if len(relative.parts) >= 3 else ("Unknown Album", None)
        title, number = _track_parts(path.stem)
        stat = path.stat()
        identity = f"{relative}|{stat.st_size}|{stat.st_mtime_ns}".encode()
        tracks.append(Track(
            path=str(path), relative_path=str(relative), artist=artist, album=album,
            title=title, track_number=number, track_total=len(grouped[path.parent]),
            disc_number=_disc_number(relative.parts[1:-1]), year=year,
            size=stat.st_size, mtime_ns=stat.st_mtime_ns,
            fingerprint=hashlib.sha256(identity).hexdigest()[:20],
        ))
    return tracks
