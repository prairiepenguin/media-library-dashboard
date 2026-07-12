from __future__ import annotations

import csv
import json
import os
from pathlib import Path

from plexapi.server import PlexServer

MOVIE_FIELDS = ["Movie", "Digital", "Type", "File Size", "Bluray", "DVD"]
MUSIC_FIELDS = ["Artist", "Album", "Year", "Genres", "Tracks", "Duration", "Type", "File Size", "Artwork"]


def human_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


def _media_details(item) -> tuple[set[str], int]:
    kinds: set[str] = set()
    size = 0
    for media in getattr(item, "media", None) or []:
        if getattr(media, "container", None):
            kinds.add(str(media.container).upper())
        for part in getattr(media, "parts", None) or []:
            size += int(getattr(part, "size", 0) or 0)
            suffix = Path(str(getattr(part, "file", "") or "")).suffix
            if suffix:
                kinds.add(suffix.lstrip(".").upper())
    return kinds, size


def _read_movies(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as source:
        return [{field: str(row.get(field, "") or "").strip() for field in MOVIE_FIELDS}
                for row in csv.DictReader(source) if row.get("Movie")]


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def connect() -> PlexServer:
    url = os.environ.get("PLEX_URL", "http://192.168.68.69:32400")
    token = os.environ.get("PLEX_TOKEN", "").strip()
    if not token:
        token_file = Path(os.environ.get("PLEX_SETTINGS_PATH", Path.home() / ".plex_movie_exporter.json"))
        try:
            token = str(json.loads(token_file.read_text(encoding="utf-8")).get("token", "")).strip()
        except (OSError, json.JSONDecodeError):
            pass
    if not token:
        raise RuntimeError("Set PLEX_TOKEN or provide the existing Plex settings file")
    return PlexServer(url, token, timeout=30)


def export(plex: PlexServer, movie_path: Path, music_path: Path) -> tuple[int, int]:
    existing = {row["Movie"].casefold().strip(): row for row in _read_movies(movie_path)}
    movies: list[dict[str, str]] = []
    matched: set[str] = set()
    albums: list[dict[str, str]] = []
    for section in plex.library.sections():
        if getattr(section, "type", None) == "movie":
            for movie in section.all():
                kinds, size = _media_details(movie)
                title = str(getattr(movie, "title", "Untitled") or "Untitled")
                prior = existing.get(title.casefold().strip(), {})
                movies.append({"Movie": title, "Digital": "1", "Type": ", ".join(sorted(kinds)),
                               "File Size": human_size(size) if size else "", "Bluray": prior.get("Bluray", ""),
                               "DVD": prior.get("DVD", "")})
                matched.add(title.casefold().strip())
        elif getattr(section, "type", None) == "artist":
            for album in section.albums():
                tracks = list(album.tracks())
                kinds: set[str] = set()
                size = duration = 0
                for track in tracks:
                    duration += int(getattr(track, "duration", 0) or 0)
                    track_kinds, track_size = _media_details(track)
                    kinds.update(track_kinds); size += track_size
                genres = sorted(str(g.tag).strip() for g in (getattr(album, "genres", None) or []) if str(g.tag).strip())
                minutes = duration // 60000
                albums.append({"Artist": str(getattr(album, "parentTitle", "Unknown Artist")),
                               "Album": str(getattr(album, "title", "Untitled Album")),
                               "Year": str(getattr(album, "year", "") or ""), "Genres": ", ".join(genres),
                               "Tracks": str(len(tracks)), "Duration": f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m",
                               "Type": ", ".join(sorted(kinds)), "File Size": human_size(size) if size else "",
                               "Artwork": str(getattr(album, "thumb", "") or "")})
    movies.extend(row for key, row in existing.items() if key not in matched)
    movies.sort(key=lambda row: row["Movie"].casefold())
    albums.sort(key=lambda row: (row["Artist"].casefold(), row["Album"].casefold()))
    _write_csv(movie_path, MOVIE_FIELDS, movies)
    _write_csv(music_path, MUSIC_FIELDS, albums)
    return len(movies), len(albums)
