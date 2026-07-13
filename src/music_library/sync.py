from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from .catalog import missing_albums
from .cover_art import enrich_music_csv
from .plex_export import connect, export
from .scanner import scan
from .storage import write_inventory


def run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh local media data and optionally publish changes")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--music-root", type=Path, default=Path(os.environ.get("MUSIC_LIBRARY_PATH", "M:\\")))
    parser.add_argument("--skip-musicbrainz", action="store_true")
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()
    data = args.project / "data"
    inventory = data / "inventory.json"
    tracks = scan(args.music_root)
    write_inventory(inventory, args.music_root, tracks)
    print(f"Cataloged {len(tracks):,} WAV tracks")
    if not args.skip_musicbrainz:
        user_agent = os.environ.get("MUSICBRAINZ_USER_AGENT", "JacobMediaLibrary/1.0 jacobingalls@outlook.com")
        import json
        payload = missing_albums(inventory, user_agent)
        (data / "missing_albums.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    movie_count, album_count = export(connect(), data / "movies.csv", data / "plex_music.csv")
    print(f"Exported {movie_count:,} movies and {album_count:,} Plex albums")
    matched_covers, queried_covers = enrich_music_csv(
        data / "plex_music.csv", data / "musicbrainz_artwork.json",
        os.environ.get("MUSICBRAINZ_USER_AGENT", "JacobMediaLibrary/1.0 jacobingalls@outlook.com"),
    )
    print(f"Matched {matched_covers:,} album covers ({queried_covers:,} new MusicBrainz lookups)")
    if args.push:
        run(["git", "add", "data"], args.project)
        changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=args.project).returncode != 0
        if changed:
            run(["git", "commit", "-m", "Refresh media catalog"], args.project)
            run(["git", "push"], args.project)
            print("Published refreshed catalog to GitHub")
        else:
            print("No catalog changes to publish")


if __name__ == "__main__":
    main()
