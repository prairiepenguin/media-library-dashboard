from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

DATA = Path(__file__).parent / "data"


@st.cache_data
def read_json(name: str, default: dict) -> dict:
    path = DATA / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


@st.cache_data
def read_csv(name: str, columns: list[str]) -> pd.DataFrame:
    path = DATA / name
    return pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("") if path.exists() else pd.DataFrame(columns=columns)


def searchable(frame: pd.DataFrame, query: str) -> pd.DataFrame:
    if not query or frame.empty:
        return frame
    return frame[frame.astype(str).apply(lambda col: col.str.contains(query, case=False, regex=False)).any(axis=1)]


st.set_page_config(page_title="Media Library", page_icon="📚", layout="wide")
st.title("📚 Media Library Dashboard")
st.caption("Movies, Plex albums, and the lossless music collection in one searchable catalog.")

inventory = read_json("inventory.json", {"summary": {}, "albums": [], "tracks": []})
catalog = read_json("missing_albums.json", {"artists": []})
movies = read_csv("movies.csv", ["Movie", "Digital", "Type", "File Size", "Bluray", "DVD"])
plex_music = read_csv("plex_music.csv", ["Artist", "Album", "Year", "Genres", "Tracks", "Duration", "Type", "File Size", "Artwork"])
local_albums = pd.DataFrame(inventory.get("albums", []))
missing_rows = [{"Artist": artist["artist"], "Album": album["title"], "First released": album.get("first_release_date", "")}
                for artist in catalog.get("artists", []) for album in artist.get("missing", [])]
missing = pd.DataFrame(missing_rows, columns=["Artist", "Album", "First released"])

query = st.sidebar.text_input("Search everything")
st.sidebar.caption("The hosted dashboard is read-only. Nightly updates run on the computer connected to Plex and the backup drive.")

overview, movie_tab, plex_tab, collection_tab, gaps_tab = st.tabs(
    ["Overview", "Movies", "Plex Music", "Lossless Collection", "Missing Albums"]
)

with overview:
    digital = int((movies.get("Digital", pd.Series(dtype=str)) == "1").sum())
    physical = int(((movies.get("Bluray", pd.Series(dtype=str)) != "") | (movies.get("DVD", pd.Series(dtype=str)) != "")).sum())
    cols = st.columns(5)
    cols[0].metric("Movies", f"{len(movies):,}")
    cols[1].metric("Digital movies", f"{digital:,}")
    cols[2].metric("Physical movies", f"{physical:,}")
    cols[3].metric("Plex albums", f"{len(plex_music):,}")
    cols[4].metric("Missing albums", f"{len(missing):,}")
    left, right = st.columns(2)
    with left:
        st.subheader("Movie formats")
        formats = Counter(kind.strip() for value in movies.get("Type", []) for kind in str(value).split(",") if kind.strip())
        if formats:
            st.bar_chart(pd.Series(formats, name="Movies").sort_values(ascending=False))
    with right:
        st.subheader("Top music genres")
        genres = Counter(genre.strip() for value in plex_music.get("Genres", []) for genre in str(value).split(",") if genre.strip())
        if genres:
            st.bar_chart(pd.Series(genres, name="Albums").sort_values(ascending=False).head(12))

with movie_tab:
    view = searchable(movies, query)
    media = st.multiselect("Ownership", ["Digital", "Blu-ray", "DVD"])
    if media:
        mask = pd.Series(False, index=view.index)
        if "Digital" in media: mask |= view["Digital"].eq("1")
        if "Blu-ray" in media: mask |= view["Bluray"].ne("")
        if "DVD" in media: mask |= view["DVD"].ne("")
        view = view[mask]
    st.dataframe(view, width="stretch", hide_index=True)

with plex_tab:
    view = searchable(plex_music, query)
    artists = sorted(plex_music["Artist"].unique(), key=str.casefold) if not plex_music.empty else []
    chosen = st.multiselect("Artists", artists)
    if chosen: view = view[view["Artist"].isin(chosen)]
    st.dataframe(view.drop(columns=["Artwork"], errors="ignore"), width="stretch", hide_index=True)

with collection_tab:
    if local_albums.empty:
        st.info("Run the local sync to create the lossless inventory.")
    else:
        display = local_albums.rename(columns={"artist": "Artist", "album": "Album", "year": "Year", "track_count": "Tracks", "path": "Folder"})
        st.dataframe(searchable(display, query), width="stretch", hide_index=True)

with gaps_tab:
    if missing.empty:
        st.success("No missing studio albums are currently listed.")
    else:
        artists = sorted(missing["Artist"].unique(), key=str.casefold)
        chosen = st.multiselect("Artists with gaps", artists)
        view = missing[missing["Artist"].isin(chosen)] if chosen else missing
        st.dataframe(searchable(view, query), width="stretch", hide_index=True)

generated = inventory.get("generated_at")
if generated:
    st.caption(f"Local media catalog last refreshed {generated}")
