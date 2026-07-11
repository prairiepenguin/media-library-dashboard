from __future__ import annotations

import argparse
import json
from pathlib import Path

from .catalog import missing_albums
from .scanner import scan
from .storage import write_inventory
from .tagger import tag_track


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="music-library")
    sub = result.add_subparsers(dest="command", required=True)
    scan_cmd = sub.add_parser("scan", help="Refresh the local JSON inventory")
    scan_cmd.add_argument("root", type=Path)
    scan_cmd.add_argument("--output", type=Path, default=Path("data/inventory.json"))
    tag_cmd = sub.add_parser("tag", help="Preview or write inferred WAV tags")
    tag_cmd.add_argument("root", type=Path)
    tag_cmd.add_argument("--apply", action="store_true")
    tag_cmd.add_argument("--overwrite", action="store_true")
    catalog_cmd = sub.add_parser("catalog", help="Refresh missing studio albums using MusicBrainz")
    catalog_cmd.add_argument("--inventory", type=Path, default=Path("data/inventory.json"))
    catalog_cmd.add_argument("--output", type=Path, default=Path("data/missing_albums.json"))
    catalog_cmd.add_argument(
        "--user-agent",
        default="JacobMusicLibrary/0.1 jacobingalls@outlook.com",
        help="MusicBrainz contact identity (the project default is used when omitted)",
    )
    return result


def main() -> None:
    args = parser().parse_args()
    if args.command == "scan":
        tracks = scan(args.root)
        write_inventory(args.output, args.root, tracks)
        print(f"Cataloged {len(tracks)} WAV tracks in {args.output}")
    elif args.command == "tag":
        results = [tag_track(track, args.apply, args.overwrite) for track in scan(args.root)]
        counts = {status: sum(r.status == status for r in results) for status in ("updated", "preview", "unchanged", "error")}
        print(json.dumps(counts, indent=2))
        errors = [result for result in results if result.status == "error"]
        for result in errors[:10]:
            print(f"ERROR {result.path}: {result.error}")
        if len(errors) > 10:
            print(f"... {len(errors) - 10} additional errors omitted")
    else:
        payload = missing_albums(args.inventory, args.user_agent)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
