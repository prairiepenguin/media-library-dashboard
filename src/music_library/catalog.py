from __future__ import annotations

import time
import unicodedata
from pathlib import Path

import requests

from .storage import read_json

API = "https://musicbrainz.org/ws/2"
ARTIST_QUERIES = {"matchbox 20": "Matchbox Twenty"}


def _normalize(value: str) -> str:
    ascii_value = "".join(
        character for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )
    return " ".join(ascii_value.casefold().replace("&", "and").split())


def _artist_matches(candidate: dict, local_name: str) -> bool:
    wanted = _normalize(local_name)
    names = [candidate.get("name", ""), candidate.get("sort-name", "")]
    names.extend(alias.get("name", "") for alias in candidate.get("aliases", []))
    normalized = {_normalize(name) for name in names}
    return wanted in normalized or f"the {wanted}" in normalized


def missing_albums(inventory_path: Path, user_agent: str, include_types: tuple[str, ...] = ("Album",)) -> dict:
    inventory = read_json(inventory_path)
    owned_by_artist: dict[str, set[str]] = {}
    for album in inventory.get("albums", []):
        owned_by_artist.setdefault(album["artist"], set()).add(_normalize(album["album"]))

    session = requests.Session()
    session.headers["User-Agent"] = user_agent
    output: list[dict] = []
    for artist, owned in sorted(owned_by_artist.items()):
        if _normalize(artist) == "soundtracks":
            output.append({"artist": artist, "status": "excluded_collection", "missing": []})
            continue
        query_name = ARTIST_QUERIES.get(_normalize(artist), artist)
        response = session.get(f"{API}/artist/", params={"query": f'artist:"{query_name}"', "fmt": "json", "limit": 5}, timeout=30)
        response.raise_for_status()
        candidates = response.json().get("artists", [])
        exact = next((a for a in candidates if _artist_matches(a, query_name)), None)
        if not exact:
            output.append({"artist": artist, "status": "artist_not_matched", "missing": []})
            time.sleep(1.05)
            continue
        time.sleep(1.05)
        response = session.get(f"{API}/release-group", params={"artist": exact["id"], "fmt": "json", "limit": 100}, timeout=30)
        response.raise_for_status()
        releases = response.json().get("release-groups", [])
        missing = [
            {"title": item["title"], "first_release_date": item.get("first-release-date"), "type": item.get("primary-type")}
            for item in releases
            if item.get("primary-type") in include_types
            and not item.get("secondary-types")
            and _normalize(item["title"]) not in owned
        ]
        output.append({"artist": artist, "musicbrainz_id": exact["id"], "status": "matched", "missing": missing})
        time.sleep(1.05)
    return {"schema_version": 1, "artists": output}
