from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .scanner import Track


def write_inventory(path: Path, root: Path, tracks: list[Track]) -> None:
    albums: dict[tuple[str, str], dict] = {}
    for track in tracks:
        key = (track.artist, track.album)
        album = albums.setdefault(key, {
            "artist": track.artist, "album": track.album, "year": track.year,
            "track_count": 0, "path": str(Path(track.relative_path).parent),
        })
        album["track_count"] += 1
        album["year"] = album["year"] or track.year
    public_tracks = []
    for track in tracks:
        item = track.to_dict()
        item.pop("path", None)
        public_tracks.append(item)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {"artists": len({t.artist for t in tracks}), "albums": len(albums), "tracks": len(tracks)},
        "albums": sorted(albums.values(), key=lambda a: (a["artist"].casefold(), a["album"].casefold())),
        "tracks": public_tracks,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists():
        return default or {}
    return json.loads(path.read_text(encoding="utf-8"))
