from __future__ import annotations

import csv
import json
import re
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import requests

MUSICBRAINZ_API = "https://musicbrainz.org/ws/2/release-group/"
COVER_ART_ROOT = "https://coverartarchive.org/release-group"


def normalize(value: str) -> str:
    value = "".join(character for character in unicodedata.normalize("NFKD", value or "") if not unicodedata.combining(character))
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"\b(deluxe|expanded|remaster(?:ed)?|anniversary|edition)\b", " ", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def match_score(artist: str, album: str, candidate: dict) -> float:
    title_score = SequenceMatcher(None, normalize(album), normalize(candidate.get("title", ""))).ratio()
    credits = " ".join(credit.get("name", "") for credit in candidate.get("artist-credit", []))
    artist_score = SequenceMatcher(None, normalize(artist), normalize(credits)).ratio()
    return round(100 * (0.75 * title_score + 0.25 * artist_score), 1)


def _read_cache(path: Path) -> dict[str, dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_cache(path: Path, cache: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _find_cover(session: requests.Session, artist: str, album: str) -> dict:
    response = session.get(MUSICBRAINZ_API, params={
        "query": f'artist:"{artist}" AND releasegroup:"{album}"', "fmt": "json", "limit": 5,
    }, timeout=30)
    response.raise_for_status()
    candidates = response.json().get("release-groups", [])
    if not candidates:
        return {"status": "not_found"}
    best = max(candidates, key=lambda item: match_score(artist, album, item))
    score = match_score(artist, album, best)
    if score < 85:
        return {"status": "low_confidence", "score": score, "candidate": best.get("title", "")}
    mbid = best["id"]
    cover = f"{COVER_ART_ROOT}/{mbid}/front-500"
    art_response = session.head(cover, allow_redirects=False, timeout=30)
    if art_response.status_code not in {200, 307}:
        return {"status": "no_cover", "mbid": mbid, "score": score}
    return {"status": "matched", "mbid": mbid, "score": score, "url": cover}


def enrich_music_csv(csv_path: Path, cache_path: Path, user_agent: str) -> tuple[int, int]:
    with csv_path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if "Artwork" not in fields:
        fields.append("Artwork")
    cache = _read_cache(cache_path)
    session = requests.Session()
    session.headers["User-Agent"] = user_agent
    matched = queried = 0
    for row in rows:
        key = f"{normalize(row.get('Artist', ''))}\0{normalize(row.get('Album', ''))}"
        result = cache.get(key)
        if result is None:
            result = _find_cover(session, row.get("Artist", ""), row.get("Album", ""))
            cache[key] = result
            queried += 1
            time.sleep(1.05)
        if result.get("status") == "matched":
            row["Artwork"] = result["url"]
            matched += 1
    temporary = csv_path.with_suffix(".tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    temporary.replace(csv_path)
    _write_cache(cache_path, cache)
    return matched, queried
