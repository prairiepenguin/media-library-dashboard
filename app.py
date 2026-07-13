from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st


APP_TITLE = "Media Library Dashboard"
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_PATH = PROJECT_ROOT / "data"
sys.path.insert(0, str(PROJECT_ROOT / "src"))
DEFAULT_CSV_PATH = DATA_PATH / "movies.csv"
DEFAULT_MUSIC_CSV_PATH = DATA_PATH / "plex_music.csv"
DEFAULT_CACHE_PATH = DATA_PATH / "tmdb_cache.json"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
PLACEHOLDER_POSTER = "https://placehold.co/500x750?text=No+Poster"

CSV_COLUMNS = ["Movie", "Digital", "Type", "File Size", "Bluray", "DVD"]
MUSIC_COLUMNS = ["Artist", "Album", "Year", "Genres", "Tracks", "Duration", "Type", "File Size", "Artwork"]


st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)


CUSTOM_CSS = """
<style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 3rem;
    }

    [data-testid="stMetric"] {
        background: rgba(127, 127, 127, 0.08);
        border: 1px solid rgba(127, 127, 127, 0.18);
        padding: 1rem;
        border-radius: 0.8rem;
    }

    .movie-card {
        border: 1px solid rgba(127, 127, 127, 0.20);
        border-radius: 0.9rem;
        padding: 0.8rem;
        height: 100%;
        background: rgba(127, 127, 127, 0.04);
    }

    .movie-title {
        font-size: 1.05rem;
        font-weight: 700;
        line-height: 1.25;
        margin-top: 0.45rem;
        margin-bottom: 0.35rem;
    }

    .format-line {
        font-size: 0.90rem;
        opacity: 0.82;
        margin-bottom: 0.15rem;
    }

    .small-muted {
        font-size: 0.82rem;
        opacity: 0.68;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def is_owned(value: Any) -> bool:
    text = str(value or "").strip().casefold()
    return text in {"1", "1.0", "true", "yes", "y", "owned", "x"}


def parse_size_to_bytes(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return 0

    parts = text.replace(",", "").split()
    if not parts:
        return 0

    try:
        number = float(parts[0])
    except ValueError:
        return 0

    unit = parts[1].upper() if len(parts) > 1 else "B"
    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
    }
    return int(number * multipliers.get(unit, 1))


def human_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


@st.cache_data(show_spinner=False)
def load_movies(csv_path: str) -> pd.DataFrame:
    path = Path(csv_path)

    if not path.exists():
        raise FileNotFoundError(f"Movie CSV not found: {path}")

    df = pd.read_csv(path, dtype="string").fillna("")
    df.columns = [str(column).strip() for column in df.columns]

    for column in CSV_COLUMNS:
        if column not in df.columns:
            df[column] = ""

    df = df[CSV_COLUMNS].copy()
    df["Movie"] = df["Movie"].str.strip()
    df = df[df["Movie"] != ""].drop_duplicates(subset=["Movie"], keep="first")

    df["Digital Owned"] = df["Digital"].map(is_owned)
    df["Bluray Owned"] = df["Bluray"].map(is_owned)
    df["DVD Owned"] = df["DVD"].map(is_owned)

    df["Any Owned"] = (
        df["Digital Owned"] | df["Bluray Owned"] | df["DVD Owned"]
    )

    df["Format Count"] = (
        df[["Digital Owned", "Bluray Owned", "DVD Owned"]]
        .astype(int)
        .sum(axis=1)
    )

    df["File Size Bytes"] = df["File Size"].map(parse_size_to_bytes)

    return df.sort_values("Movie", key=lambda s: s.str.casefold()).reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_music(csv_path: str) -> pd.DataFrame:
    path = Path(csv_path)
    if not path.exists():
        return pd.DataFrame(columns=MUSIC_COLUMNS + ["File Size Bytes"])
    df = pd.read_csv(path, dtype="string").fillna("")
    df.columns = [str(column).strip() for column in df.columns]
    for column in MUSIC_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    df = df[MUSIC_COLUMNS].copy()
    df["Artist"] = df["Artist"].str.strip()
    df["Album"] = df["Album"].str.strip()
    df = df[df["Album"] != ""].drop_duplicates(subset=["Artist", "Album"], keep="first")
    df["File Size Bytes"] = df["File Size"].map(parse_size_to_bytes)
    return df.sort_values(["Artist", "Album"], key=lambda s: s.str.casefold()).reset_index(drop=True)


def get_plex_access() -> tuple[str, str]:
    try:
        from music_library.plex_export import connect
        plex = connect()
        return str(plex._baseurl), str(plex._token)
    except Exception:
        return "", ""


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_plex_artwork(base_url: str, artwork: str, token: str) -> bytes | None:
    if not (base_url and artwork and token):
        return None
    try:
        response = requests.get(
            f"{base_url.rstrip('/')}{artwork}",
            params={"X-Plex-Token": token},
            timeout=15,
        )
        response.raise_for_status()
        return response.content
    except requests.RequestException:
        return None


def get_tmdb_credentials() -> tuple[str, str]:
    token = ""
    api_key = ""

    try:
        token = str(st.secrets.get("TMDB_BEARER_TOKEN", "")).strip()
        api_key = str(st.secrets.get("TMDB_API_KEY", "")).strip()
    except Exception:
        token = ""
        api_key = ""

    if not token:
        token = os.getenv("TMDB_BEARER_TOKEN", "").strip()
    if not api_key:
        api_key = os.getenv("TMDB_API_KEY", "").strip()

    return token, api_key


def load_cache(cache_path: Path) -> dict[str, dict[str, Any]]:
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_cache(cache_path: Path, cache: dict[str, dict[str, Any]]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def tmdb_headers(token: str) -> dict[str, str]:
    headers = {"accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def tmdb_params(api_key: str, **params: Any) -> dict[str, Any]:
    if api_key:
        params["api_key"] = api_key
    return params


def fetch_tmdb_metadata(title: str, token: str, api_key: str) -> dict[str, Any]:
    candidates = [title]
    without_prefix = re.sub(r"^\d+\s+(?=[A-Za-z])", "", title).strip()
    without_suffix = re.sub(r"\s+the movie$", "", without_prefix, flags=re.I).strip()
    for candidate in (without_prefix, without_suffix):
        if candidate and candidate.casefold() not in {item.casefold() for item in candidates}:
            candidates.append(candidate)

    results: list[dict[str, Any]] = []
    for candidate in candidates:
        search_response = requests.get(
            "https://api.themoviedb.org/3/search/movie",
            headers=tmdb_headers(token),
            params=tmdb_params(
                api_key,
                query=candidate,
                include_adult="false",
                language="en-US",
                page=1,
            ),
            timeout=20,
        )
        search_response.raise_for_status()
        results = search_response.json().get("results", [])
        if results:
            break

    if not results:
        return {
            "title": title,
            "poster_url": PLACEHOLDER_POSTER,
            "overview": "",
            "release_date": "",
            "year": "",
            "rating": None,
            "vote_count": 0,
            "genres": [],
            "runtime": None,
            "tmdb_id": None,
        }

    best = results[0]
    tmdb_id = best.get("id")

    details_response = requests.get(
        f"https://api.themoviedb.org/3/movie/{tmdb_id}",
        headers=tmdb_headers(token),
        params=tmdb_params(api_key, language="en-US"),
        timeout=20,
    )
    details_response.raise_for_status()
    details = details_response.json()

    poster_path = details.get("poster_path")
    release_date = details.get("release_date") or ""
    year = release_date[:4] if release_date else ""

    return {
        "title": details.get("title") or title,
        "poster_url": (
            f"{TMDB_IMAGE_BASE}{poster_path}"
            if poster_path
            else PLACEHOLDER_POSTER
        ),
        "overview": details.get("overview") or "",
        "release_date": release_date,
        "year": year,
        "rating": details.get("vote_average"),
        "vote_count": details.get("vote_count") or 0,
        "genres": [
            genre.get("name")
            for genre in details.get("genres", [])
            if genre.get("name")
        ],
        "runtime": details.get("runtime"),
        "tmdb_id": tmdb_id,
    }


def get_metadata(
    title: str,
    token: str,
    api_key: str,
    cache_path: Path,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cache_key = title.strip().casefold()

    if cache_key in cache:
        cached = cache[cache_key]
        is_placeholder_miss = (
            not cached.get("tmdb_id")
            and cached.get("poster_url") == PLACEHOLDER_POSTER
        )
        if not is_placeholder_miss:
            return cached

    if not (token or api_key):
        return {
            "title": title,
            "poster_url": PLACEHOLDER_POSTER,
            "overview": "",
            "release_date": "",
            "year": "",
            "rating": None,
            "vote_count": 0,
            "genres": [],
            "runtime": None,
            "tmdb_id": None,
        }

    try:
        metadata = fetch_tmdb_metadata(title, token, api_key)
    except requests.RequestException:
        return {
            "title": title,
            "poster_url": PLACEHOLDER_POSTER,
            "overview": "",
            "release_date": "",
            "year": "",
            "rating": None,
            "vote_count": 0,
            "genres": [],
            "runtime": None,
            "tmdb_id": None,
        }
    cache[cache_key] = metadata
    save_cache(cache_path, cache)
    return metadata


def render_landing_search(
    df: pd.DataFrame,
    token: str,
    api_key: str,
    cache_path: Path,
    cache: dict[str, dict[str, Any]],
) -> None:
    st.subheader("Find a movie in your database")
    st.caption("Search only the titles tracked in your local MovieDB.CSV file.")

    query = st.text_input(
        "Search by title",
        placeholder="Try The Godfather, Alien, or Dune...",
        label_visibility="collapsed",
        key="landing_search",
    ).strip()

    if not query:
        return

    local_matches = df[df["Movie"].str.contains(query, case=False, na=False, regex=False)]

    if local_matches.empty:
        st.info("No matching titles were found in your local database.")
        return

    st.caption(f"{len(local_matches):,} local match{'es' if len(local_matches) != 1 else ''}")
    for _, movie in local_matches.head(25).iterrows():
        metadata = get_metadata(
            movie["Movie"], token, api_key, cache_path, cache
        )
        poster_col, title_col, status_col = st.columns([1, 3, 2])
        with poster_col:
            st.image(
                metadata.get("poster_url") or PLACEHOLDER_POSTER,
                width="stretch",
            )
        with title_col:
            st.markdown(f"#### {movie['Movie']}")
            year = metadata.get("year") or ""
            if year:
                st.caption(year)
            if movie["Digital Owned"] and movie["File Size"]:
                st.caption(f"{movie['Type'] or 'Digital'} · {movie['File Size']}")
            overview = metadata.get("overview") or ""
            if overview:
                st.write(overview)
        with status_col:
            if movie["Any Owned"]:
                st.success(f"Owned — {owned_format_text(movie)}")
            else:
                st.warning("Tracked, but not owned")

    if len(local_matches) > 25:
        st.caption("Showing the first 25 matches. Refine your search to narrow the list.")


def owned_format_text(row: pd.Series) -> str:
    formats: list[str] = []

    if row["Digital Owned"]:
        digital_type = str(row["Type"]).strip()
        formats.append(f"Digital ({digital_type})" if digital_type else "Digital")

    if row["Bluray Owned"]:
        formats.append("Blu-ray")

    if row["DVD Owned"]:
        formats.append("DVD")

    return " • ".join(formats) if formats else "Not owned"


def filter_movies(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df.copy()

    search = st.text_input(
        "Search movies",
        placeholder="Type a movie title...",
        key="collection_search",
    ).strip()

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    ownership_filter = filter_col1.selectbox(
        "Ownership",
        [
            "All movies",
            "Owned in any format",
            "Not owned",
            "Digital",
            "Blu-ray",
            "DVD",
            "Multiple formats",
        ],
    )

    file_types = sorted(
        {
            item.strip()
            for value in df["Type"]
            for item in str(value).split(",")
            if item.strip()
        }
    )

    selected_types = filter_col2.multiselect(
        "Digital file type",
        options=file_types,
    )

    sort_option = filter_col3.selectbox(
        "Sort by",
        [
            "Movie title A–Z",
            "Movie title Z–A",
            "Largest digital file",
            "Smallest digital file",
            "Most formats owned",
        ],
    )

    if search:
        filtered = filtered[
            filtered["Movie"].str.contains(search, case=False, na=False)
        ]

    if ownership_filter == "Owned in any format":
        filtered = filtered[filtered["Any Owned"]]
    elif ownership_filter == "Not owned":
        filtered = filtered[~filtered["Any Owned"]]
    elif ownership_filter == "Digital":
        filtered = filtered[filtered["Digital Owned"]]
    elif ownership_filter == "Blu-ray":
        filtered = filtered[filtered["Bluray Owned"]]
    elif ownership_filter == "DVD":
        filtered = filtered[filtered["DVD Owned"]]
    elif ownership_filter == "Multiple formats":
        filtered = filtered[filtered["Format Count"] > 1]

    if selected_types:
        pattern = "|".join(selected_types)
        filtered = filtered[
            filtered["Type"].str.contains(pattern, case=False, regex=True, na=False)
        ]

    if sort_option == "Movie title A–Z":
        filtered = filtered.sort_values(
            "Movie",
            key=lambda s: s.str.casefold(),
            ascending=True,
        )
    elif sort_option == "Movie title Z–A":
        filtered = filtered.sort_values(
            "Movie",
            key=lambda s: s.str.casefold(),
            ascending=False,
        )
    elif sort_option == "Largest digital file":
        filtered = filtered.sort_values("File Size Bytes", ascending=False)
    elif sort_option == "Smallest digital file":
        filtered = filtered.sort_values("File Size Bytes", ascending=True)
    elif sort_option == "Most formats owned":
        filtered = filtered.sort_values(
            ["Format Count", "Movie"],
            ascending=[False, True],
        )

    return filtered.reset_index(drop=True)


def collection_metadata(df: pd.DataFrame, cache: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """Join cached TMDB facts to the local collection without network calls."""
    rows: list[dict[str, Any]] = []
    for _, movie in df.iterrows():
        metadata = cache.get(str(movie["Movie"]).strip().casefold(), {})
        year_text = str(metadata.get("year") or "").strip()
        year = int(year_text) if year_text.isdigit() else None
        rows.append({
            "Movie": movie["Movie"],
            "Year": year,
            "Decade": f"{year // 10 * 10}s" if year else "Unknown",
            "Genres": metadata.get("genres") or [],
            "Rating": metadata.get("rating"),
            "Runtime": metadata.get("runtime"),
        })
    return pd.DataFrame(rows)


def render_metadata_sync(
    df: pd.DataFrame,
    token: str,
    api_key: str,
    cache_path: Path,
    cache: dict[str, dict[str, Any]],
) -> None:
    missing = [
        str(title)
        for title in df["Movie"]
        if str(title).strip().casefold() not in cache
    ]
    if not missing:
        return

    st.warning(
        f"Movie details are available for {len(df) - len(missing):,} of "
        f"{len(df):,} CSV movies. Scan the remaining {len(missing):,} to "
        "complete the year, decade, and genre breakdowns."
    )
    if not (token or api_key):
        st.info("Configure a TMDB API key to scan the missing movie details.")
        return
    if not st.button("Scan missing movie details", type="primary"):
        return

    progress = st.progress(0, text="Looking up movie details...")
    completed = 0
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(fetch_tmdb_metadata, title, token, api_key): title
            for title in missing
        }
        for future in as_completed(futures):
            title = futures[future]
            try:
                cache[title.strip().casefold()] = future.result()
            except requests.RequestException:
                pass
            completed += 1
            progress.progress(
                completed / len(missing),
                text=f"Scanned {completed:,} of {len(missing):,} movies",
            )
    save_cache(cache_path, cache)
    st.rerun()


def render_trends(df: pd.DataFrame, cache: dict[str, dict[str, Any]]) -> None:
    facts = collection_metadata(df[df["Any Owned"]], cache)
    st.subheader("Collection trends")
    st.caption("Patterns across the movies you own, based on cached TMDB details.")
    if facts.empty:
        st.info("No owned movies are available yet.")
        return

    owned = df[df["Any Owned"]].copy()
    physical = owned["Bluray Owned"] | owned["DVD Owned"]
    digital = owned["Digital Owned"]
    digital_only = int((digital & ~physical).sum())
    physical_only = int((physical & ~digital).sum())
    both = int((digital & physical).sum())
    physical_total = int(physical.sum())

    st.markdown("#### Digital vs. physical")
    format_cols = st.columns(4)
    format_cols[0].metric("Digital", f"{int(digital.sum()):,}")
    format_cols[1].metric("Physical", f"{physical_total:,}", help="Owned on Blu-ray, DVD, or both")
    format_cols[2].metric("Digital only", f"{digital_only:,}")
    format_cols[3].metric("Digital + physical", f"{both:,}")

    format_mix = pd.DataFrame(
        {
            "Ownership": ["Digital only", "Physical only", "Digital + physical"],
            "Movies": [digital_only, physical_only, both],
        }
    ).set_index("Ownership")
    mix_chart, mix_text = st.columns([3, 2])
    with mix_chart:
        st.bar_chart(format_mix)
    with mix_text:
        owned_count = len(owned)
        both_share = both / owned_count if owned_count else 0
        st.write(
            f"Your collection contains **{int(digital.sum()):,} digital movies** "
            f"and **{physical_total:,} physical movies**. Physical includes anything "
            f"owned on Blu-ray or DVD. **{both:,} movies ({both_share:.1%})** are owned "
            "in both digital and physical formats."
        )
        st.caption(
            f"Physical only: {physical_only:,} · Digital only: {digital_only:,}"
        )

    st.divider()
    st.markdown("#### Release and rating trends")
    dated = facts.dropna(subset=["Year"]).copy()
    rated = facts.dropna(subset=["Rating"]).copy()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Years represented", int(dated["Year"].nunique()) if not dated.empty else 0)
    c2.metric("Average rating", f"{rated['Rating'].astype(float).mean():.1f}" if not rated.empty else "—")
    runtimes = facts["Runtime"].dropna().astype(float)
    c3.metric("Average runtime", f"{runtimes.mean():.0f} min" if not runtimes.empty else "—")
    c4.metric("Metadata coverage", f"{len(dated) / len(facts):.0%}")
    left, right = st.columns(2)
    with left:
        st.caption("Movies by release year")
        if dated.empty:
            st.info("Open Movies to build the metadata cache.")
        else:
            st.line_chart(dated.groupby("Year").size().rename("Movies"))
    with right:
        st.caption("Top-rated movies in your collection")
        if rated.empty:
            st.info("No ratings are cached yet.")
        else:
            top = rated.sort_values("Rating", ascending=False).head(10)
            st.dataframe(top[["Movie", "Year", "Rating"]], hide_index=True, use_container_width=True)


def render_decades(df: pd.DataFrame, cache: dict[str, dict[str, Any]]) -> None:
    facts = collection_metadata(df[df["Any Owned"]], cache)
    st.subheader("Movies by decade")
    known = facts[facts["Decade"] != "Unknown"].copy()
    if known.empty:
        st.info("No release years are cached yet. Open Movies to fetch details.")
        return
    counts = known.groupby("Decade").size().rename("Movies").sort_index()
    st.bar_chart(counts)
    decades = list(counts.index)
    selected = st.selectbox("Explore a decade", decades, index=len(decades) - 1)
    selected_movies = known[known["Decade"] == selected].sort_values(["Year", "Movie"])
    st.dataframe(selected_movies[["Movie", "Year", "Rating"]], hide_index=True, use_container_width=True)


def render_genres(df: pd.DataFrame, cache: dict[str, dict[str, Any]]) -> None:
    facts = collection_metadata(df[df["Any Owned"]], cache)
    exploded = facts.explode("Genres").rename(columns={"Genres": "Genre"})
    exploded = exploded[exploded["Genre"].notna() & (exploded["Genre"] != "")]
    st.subheader("Movies by genre")
    if exploded.empty:
        st.info("No genres are cached yet. Open Movies to fetch details.")
        return
    counts = exploded.groupby("Genre").size().rename("Movies").sort_values(ascending=False)
    st.bar_chart(counts)
    selected = st.selectbox("Explore a genre", list(counts.index))
    selected_movies = exploded[exploded["Genre"] == selected].sort_values("Movie")
    st.dataframe(selected_movies[["Movie", "Year", "Rating"]], hide_index=True, use_container_width=True)


def render_dashboard(df: pd.DataFrame) -> None:
    total_movies = len(df)
    owned_movies = int(df["Any Owned"].sum())
    digital_count = int(df["Digital Owned"].sum())
    bluray_count = int(df["Bluray Owned"].sum())
    dvd_count = int(df["DVD Owned"].sum())
    physical_only = int(
        ((df["Bluray Owned"] | df["DVD Owned"]) & ~df["Digital Owned"]).sum()
    )
    multiple_formats = int((df["Format Count"] > 1).sum())
    total_storage = int(df["File Size Bytes"].sum())

    st.subheader("Collection overview")

    row1 = st.columns(4)
    row1[0].metric("Movies tracked", f"{total_movies:,}")
    row1[1].metric("Owned", f"{owned_movies:,}")
    row1[2].metric("Digital", f"{digital_count:,}")
    row1[3].metric("Digital storage", human_size(total_storage))

    row2 = st.columns(4)
    row2[0].metric("Blu-ray", f"{bluray_count:,}")
    row2[1].metric("DVD", f"{dvd_count:,}")
    row2[2].metric("Physical only", f"{physical_only:,}")
    row2[3].metric("Multiple formats", f"{multiple_formats:,}")

    chart_col1, chart_col2 = st.columns(2)

    format_counts = pd.DataFrame(
        {
            "Format": ["Digital", "Blu-ray", "DVD"],
            "Movies": [digital_count, bluray_count, dvd_count],
        }
    )

    with chart_col1:
        st.caption("Movies by format")
        st.bar_chart(format_counts.set_index("Format"))

    type_counts: dict[str, int] = {}
    for value in df.loc[df["Digital Owned"], "Type"]:
        for file_type in str(value).split(","):
            file_type = file_type.strip().upper()
            if file_type:
                type_counts[file_type] = type_counts.get(file_type, 0) + 1

    with chart_col2:
        st.caption("Digital file types")
        if type_counts:
            type_df = pd.DataFrame(
                {
                    "Type": list(type_counts.keys()),
                    "Movies": list(type_counts.values()),
                }
            ).sort_values("Movies", ascending=False)
            st.bar_chart(type_df.set_index("Type"))
        else:
            st.info("No digital file types are currently recorded.")


def render_movie_grid(
    df: pd.DataFrame,
    token: str,
    api_key: str,
    cache_path: Path,
    cache: dict[str, dict[str, Any]],
) -> None:
    st.subheader("Movie collection")

    if df.empty:
        st.info("No movies match the selected filters.")
        return

    page_size = st.select_slider(
        "Movies per page",
        options=[12, 24, 36, 48, 60],
        value=24,
    )

    total_pages = max(1, (len(df) + page_size - 1) // page_size)
    page = st.number_input(
        "Page",
        min_value=1,
        max_value=total_pages,
        value=1,
        step=1,
    )

    start = (int(page) - 1) * page_size
    end = min(start + page_size, len(df))
    page_df = df.iloc[start:end]

    st.caption(
        f"Showing {start + 1:,}–{end:,} of {len(df):,} matching movies"
    )

    columns_per_row = 6

    for row_start in range(0, len(page_df), columns_per_row):
        columns = st.columns(columns_per_row)

        for column, (_, movie) in zip(
            columns,
            page_df.iloc[row_start : row_start + columns_per_row].iterrows(),
        ):
            with column:
                metadata = get_metadata(
                    movie["Movie"],
                    token,
                    api_key,
                    cache_path,
                    cache,
                )

                st.image(
                    metadata.get("poster_url") or PLACEHOLDER_POSTER,
                    use_container_width=True,
                )

                year = metadata.get("year") or ""
                title_line = movie["Movie"]
                if year:
                    title_line = f"{title_line} ({year})"

                st.markdown(
                    f'<div class="movie-title">{title_line}</div>',
                    unsafe_allow_html=True,
                )

                st.markdown(
                    f'<div class="format-line">{owned_format_text(movie)}</div>',
                    unsafe_allow_html=True,
                )

                if movie["Digital Owned"] and movie["File Size"]:
                    st.markdown(
                        f'<div class="small-muted">{movie["File Size"]}</div>',
                        unsafe_allow_html=True,
                    )

                rating = metadata.get("rating")
                runtime = metadata.get("runtime")
                details: list[str] = []

                if rating is not None:
                    details.append(f"★ {float(rating):.1f}")
                if runtime:
                    details.append(f"{runtime} min")

                if details:
                    st.markdown(
                        f'<div class="small-muted">{" • ".join(details)}</div>',
                        unsafe_allow_html=True,
                    )

                overview = metadata.get("overview") or ""
                if overview:
                    with st.expander("Details"):
                        st.write(overview)
                        genres = metadata.get("genres") or []
                        if genres:
                            st.caption("Genres: " + ", ".join(genres))


def render_table(df: pd.DataFrame) -> None:
    table = df[
        [
            "Movie",
            "Digital",
            "Type",
            "File Size",
            "Bluray",
            "DVD",
        ]
    ].copy()

    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Movie": st.column_config.TextColumn("Movie", width="large"),
            "Digital": st.column_config.TextColumn("Digital"),
            "Type": st.column_config.TextColumn("File type"),
            "File Size": st.column_config.TextColumn("File size"),
            "Bluray": st.column_config.TextColumn("Blu-ray"),
            "DVD": st.column_config.TextColumn("DVD"),
        },
    )


def render_everything_search(movies: pd.DataFrame, music: pd.DataFrame) -> None:
    st.subheader("Search everything")
    query = st.text_input(
        "Search movies, artists, albums, and genres",
        placeholder="Try Alien, Prince, jazz, or Rumours...",
        label_visibility="collapsed",
        key="everything_search",
    ).strip()
    if not query:
        return

    movie_matches = movies[movies["Movie"].str.contains(query, case=False, na=False, regex=False)]
    if music.empty:
        music_matches = music
    else:
        music_matches = music[
            music[["Artist", "Album", "Genres"]]
            .astype(str)
            .agg(" ".join, axis=1)
            .str.contains(query, case=False, na=False, regex=False)
        ]

    movie_col, music_col = st.columns(2)
    with movie_col:
        st.markdown(f"#### Movies ({len(movie_matches):,})")
        for title in movie_matches["Movie"].head(12):
            st.write(f"🎬 {title}")
    with music_col:
        st.markdown(f"#### Music ({len(music_matches):,})")
        for _, album in music_matches.head(12).iterrows():
            year = f" ({album['Year']})" if album["Year"] else ""
            st.write(f"💿 {album['Artist']} — {album['Album']}{year}")
    if movie_matches.empty and music_matches.empty:
        st.info("Nothing in Millenial Antiquing matches that search yet.")


def filter_music(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    search_col, genre_col, sort_col = st.columns([2, 1, 1])
    search = search_col.text_input("Search music", placeholder="Artist, album, or genre...").strip()
    genres = sorted({genre.strip() for value in df["Genres"] for genre in str(value).split(",") if genre.strip()})
    selected_genres = genre_col.multiselect("Genre", genres)
    sort = sort_col.selectbox("Sort by", ["Artist A-Z", "Album A-Z", "Newest", "Oldest", "Largest"])
    filtered = df.copy()
    if search:
        haystack = filtered[["Artist", "Album", "Genres"]].astype(str).agg(" ".join, axis=1)
        filtered = filtered[haystack.str.contains(search, case=False, na=False, regex=False)]
    if selected_genres:
        pattern = "|".join(re.escape(genre) for genre in selected_genres)
        filtered = filtered[filtered["Genres"].str.contains(pattern, case=False, na=False, regex=True)]
    if sort == "Artist A-Z":
        filtered = filtered.sort_values(["Artist", "Album"], key=lambda s: s.str.casefold())
    elif sort == "Album A-Z":
        filtered = filtered.sort_values("Album", key=lambda s: s.str.casefold())
    elif sort in {"Newest", "Oldest"}:
        filtered = filtered.assign(_year=pd.to_numeric(filtered["Year"], errors="coerce")).sort_values("_year", ascending=sort == "Oldest").drop(columns="_year")
    else:
        filtered = filtered.sort_values("File Size Bytes", ascending=False)
    return filtered.reset_index(drop=True)


def render_music(music: pd.DataFrame) -> None:
    st.subheader("Music collection")
    if music.empty:
        st.info("No music has been synced yet. Use Sync with Plex to build MusicDB.CSV.")
        return
    total_tracks = int(pd.to_numeric(music["Tracks"], errors="coerce").fillna(0).sum())
    metric_cols = st.columns(4)
    metric_cols[0].metric("Albums", f"{len(music):,}")
    metric_cols[1].metric("Artists", f"{music['Artist'].nunique():,}")
    metric_cols[2].metric("Tracks", f"{total_tracks:,}")
    metric_cols[3].metric("Storage", human_size(int(music["File Size Bytes"].sum())))

    with st.expander("Search, filter, and sort", expanded=True):
        filtered = filter_music(music)
    if filtered.empty:
        st.info("No albums match those filters.")
        return
    base_url, token = get_plex_access()
    st.caption(f"Showing {len(filtered):,} matching albums")
    for start in range(0, len(filtered), 6):
        columns = st.columns(6)
        for column, (_, album) in zip(columns, filtered.iloc[start:start + 6].iterrows()):
            with column:
                artwork = fetch_plex_artwork(base_url, str(album["Artwork"]), token)
                st.image(artwork or "https://placehold.co/500x500?text=Album+Art", use_container_width=True)
                st.markdown(f'<div class="movie-title">{album["Album"]}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="format-line">{album["Artist"]}</div>', unsafe_allow_html=True)
                facts = [str(value) for value in (album["Year"], f'{album["Tracks"]} tracks' if album["Tracks"] else "", album["Duration"]) if value]
                if facts:
                    st.markdown(f'<div class="small-muted">{" · ".join(facts)}</div>', unsafe_allow_html=True)
                if album["Genres"]:
                    st.caption(album["Genres"])


def render_home_dashboard(movies: pd.DataFrame, music: pd.DataFrame) -> None:
    owned_movies = movies[movies["Any Owned"]]
    artists = int(music["Artist"].nunique()) if not music.empty else 0
    tracks = int(pd.to_numeric(music["Tracks"], errors="coerce").fillna(0).sum()) if not music.empty else 0
    movie_storage = int(movies["File Size Bytes"].sum())
    music_storage = int(music["File Size Bytes"].sum()) if not music.empty else 0

    st.markdown("### The cabinet at a glance")
    overview = st.columns(4)
    overview[0].metric("Movies", f"{len(owned_movies):,}")
    overview[1].metric("Albums", f"{len(music):,}")
    overview[2].metric("Artists", f"{artists:,}")
    overview[3].metric("Total storage", human_size(movie_storage + music_storage))

    movie_col, music_col = st.columns(2, gap="large")
    with movie_col:
        st.markdown("### 🎬 On the screen")
        digital = int(owned_movies["Digital Owned"].sum())
        physical = int((owned_movies["Bluray Owned"] | owned_movies["DVD Owned"]).sum())
        movie_metrics = st.columns(3)
        movie_metrics[0].metric("Owned", f"{len(owned_movies):,}")
        movie_metrics[1].metric("Digital", f"{digital:,}")
        movie_metrics[2].metric("Physical", f"{physical:,}")
        movie_mix = pd.DataFrame(
            {"Movies": [digital, physical]},
            index=["Digital", "Physical"],
        )
        st.caption("Movie formats")
        st.bar_chart(movie_mix)

    with music_col:
        st.markdown("### 🎵 On the speakers")
        music_metrics = st.columns(3)
        music_metrics[0].metric("Albums", f"{len(music):,}")
        music_metrics[1].metric("Artists", f"{artists:,}")
        music_metrics[2].metric("Tracks", f"{tracks:,}")
        genre_counts: dict[str, int] = {}
        for value in music["Genres"] if not music.empty else []:
            for genre in str(value).split(","):
                genre = genre.strip()
                if genre:
                    genre_counts[genre] = genre_counts.get(genre, 0) + 1
        st.caption("Top music genres")
        if genre_counts:
            top_genres = pd.Series(genre_counts, name="Albums").sort_values(ascending=False).head(8)
            st.bar_chart(top_genres)
        else:
            st.info("Sync music from Plex to see your genre mix.")

    st.divider()
    st.markdown("### A few things from the shelves")
    movie_shelf, music_shelf = st.columns(2, gap="large")
    with movie_shelf:
        st.caption("MOVIES")
        for title in owned_movies["Movie"].head(5):
            st.write(f"🎬 {title}")
        if owned_movies.empty:
            st.info("No owned movies are listed yet.")
    with music_shelf:
        st.caption("MUSIC")
        for _, album in music.head(5).iterrows():
            st.write(f"💿 **{album['Album']}** — {album['Artist']}")
        if music.empty:
            st.info("No albums are listed yet. Sync with Plex to add them.")


@st.cache_data(show_spinner=False)
def load_local_catalog() -> tuple[dict[str, Any], dict[str, Any]]:
    def load(name: str, fallback: dict[str, Any]) -> dict[str, Any]:
        try:
            return json.loads((DATA_PATH / name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return fallback
    return load("inventory.json", {"summary": {}, "albums": [], "tracks": []}), load("missing_albums.json", {"artists": []})


def render_lossless_collection() -> None:
    inventory, _ = load_local_catalog()
    albums = pd.DataFrame(inventory.get("albums", []))
    tracks = inventory.get("tracks", [])
    if albums.empty:
        st.info("No lossless inventory has been generated yet.")
        return
    summary = inventory.get("summary", {})
    metrics = st.columns(4)
    metrics[0].metric("Artists", f"{summary.get('artists', 0):,}")
    metrics[1].metric("Albums", f"{summary.get('albums', 0):,}")
    metrics[2].metric("Tracks", f"{summary.get('tracks', 0):,}")
    metrics[3].metric("Storage", human_size(sum(int(track.get("size", 0)) for track in tracks)))
    query = st.text_input("Search lossless collection", placeholder="Artist or album...").strip()
    display = albums.rename(columns={"artist": "Artist", "album": "Album", "year": "Year", "track_count": "Tracks", "path": "Folder"})
    if query:
        match = display[["Artist", "Album"]].astype(str).agg(" ".join, axis=1).str.contains(query, case=False, regex=False)
        display = display[match]
    st.dataframe(display, width="stretch", hide_index=True)


def render_missing_albums() -> None:
    inventory, catalog = load_local_catalog()
    rows = [
        {"Artist": artist["artist"], "Album": album["title"], "First released": album.get("first_release_date", "")}
        for artist in catalog.get("artists", []) for album in artist.get("missing", [])
    ]
    missing = pd.DataFrame(rows, columns=["Artist", "Album", "First released"])
    metrics = st.columns(3)
    metrics[0].metric("Owned albums", f"{inventory.get('summary', {}).get('albums', 0):,}")
    metrics[1].metric("Missing albums", f"{len(missing):,}")
    metrics[2].metric("Artists with gaps", f"{missing['Artist'].nunique() if not missing.empty else 0:,}")
    if missing.empty:
        st.success("No missing studio albums are currently listed.")
        return
    artists = sorted(missing["Artist"].unique(), key=str.casefold)
    chosen = st.multiselect("Filter artists", artists)
    if chosen:
        missing = missing[missing["Artist"].isin(chosen)]
    st.dataframe(missing, width="stretch", hide_index=True)


def render_music_stats(music: pd.DataFrame) -> None:
    inventory, catalog = load_local_catalog()
    albums = inventory.get("albums", [])
    tracks = inventory.get("tracks", [])
    owned = Counter(album["artist"] for album in albums)
    track_counts = Counter(track["artist"] for track in tracks)
    catalog_by_artist = {item["artist"]: item for item in catalog.get("artists", [])}
    rows: list[dict[str, Any]] = []
    for artist in sorted(owned, key=str.casefold):
        item = catalog_by_artist.get(artist, {})
        excluded = item.get("status") == "excluded_collection"
        missing = len(item.get("missing", []))
        total = owned[artist] + missing
        rows.append({
            "Artist": artist,
            "Owned": owned[artist],
            "Missing": None if excluded else missing,
            "Collection %": None if excluded or not total else round(100 * owned[artist] / total, 1),
            "Tracks": track_counts[artist],
        })
    stats = pd.DataFrame(rows)
    valid = stats.dropna(subset=["Missing", "Collection %"]) if not stats.empty else stats
    total_owned = int(valid["Owned"].sum()) if not valid.empty else len(albums)
    total_missing = int(valid["Missing"].sum()) if not valid.empty else 0
    total_known = total_owned + total_missing
    coverage = 100 * total_owned / total_known if total_known else 0
    plex_tracks = int(pd.to_numeric(music["Tracks"], errors="coerce").fillna(0).sum()) if not music.empty else len(tracks)
    metrics = st.columns(6)
    metrics[0].metric("Artists", f"{len(owned):,}")
    metrics[1].metric("Owned albums", f"{len(albums):,}")
    metrics[2].metric("Missing albums", f"{total_missing:,}")
    metrics[3].metric("Overall coverage", f"{coverage:.1f}%")
    metrics[4].metric("Tracks", f"{plex_tracks:,}")
    metrics[5].metric("Music storage", human_size(int(music["File Size Bytes"].sum())) if not music.empty else human_size(sum(int(t.get("size", 0)) for t in tracks)))
    if valid.empty:
        st.info("Run the local scan and MusicBrainz catalog refresh to calculate collection coverage.")
        return

    chart, insights = st.columns([2, 1])
    with chart:
        st.subheader("Collection completion by artist")
        st.bar_chart(valid.sort_values("Collection %").set_index("Artist")[["Collection %"]], horizontal=True,
                     height=max(420, len(valid) * 30))
    with insights:
        st.subheader("Collection insights")
        fullest = valid.sort_values(["Collection %", "Owned"], ascending=False).iloc[0]
        st.success(f"Strongest: **{fullest['Artist']}** at **{fullest['Collection %']:.1f}%**")
        st.markdown("**Closest to completing**")
        closest = valid[valid["Missing"] > 0].sort_values(["Missing", "Collection %"], ascending=[True, False]).head(5)
        for row in closest.itertuples():
            st.write(f"{row.Artist}: {int(row.Missing)} album{'s' if row.Missing != 1 else ''} away")
        st.markdown("**Biggest discovery opportunities**")
        for row in valid.sort_values("Missing", ascending=False).head(5).itertuples():
            st.write(f"{row.Artist}: {int(row.Missing)} missing")

    years = [album.get("year") for album in albums if album.get("year")]
    genre_col, decade_col = st.columns(2)
    with genre_col:
        st.subheader("Top Plex genres")
        genres = Counter(genre.strip() for value in music.get("Genres", []) for genre in str(value).split(",") if genre.strip())
        if genres:
            st.bar_chart(pd.Series(genres, name="Albums").sort_values(ascending=False).head(12))
    with decade_col:
        st.subheader("Owned albums by decade")
        if years:
            decades = Counter(f"{int(year) // 10 * 10}s" for year in years)
            st.bar_chart(pd.Series(decades, name="Albums").sort_index())

    st.subheader("Artist statistics")
    st.dataframe(stats, width="stretch", hide_index=True,
                 column_config={"Collection %": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100)})


def sync_with_plex() -> str:
    from music_library.plex_export import connect, export
    movie_count, album_count = export(connect(), DEFAULT_CSV_PATH, DEFAULT_MUSIC_CSV_PATH)
    load_movies.clear()
    load_music.clear()
    return f"Synced {movie_count:,} movies and {album_count:,} Plex albums."


def main() -> None:
    st.title("📼 Media Library Dashboard")
    st.caption(
        "Your movies and music, collected in one searchable cabinet."
    )

    csv_path = str(DEFAULT_CSV_PATH)
    cache_path = DEFAULT_CACHE_PATH

    status_col, update_col = st.columns([5, 1])
    if update_col.button(
        "Sync with Plex",
        use_container_width=True,
        help="Refresh both movies and music using your saved Plex connection",
    ):
        try:
            with st.spinner("Opening the cabinet and checking Plex..."):
                message = sync_with_plex()
            status_col.success(message)
        except Exception as exc:
            status_col.error(f"Plex sync failed: {exc}")

    token, api_key = get_tmdb_credentials()

    try:
        movies = load_movies(csv_path)
    except Exception as exc:
        st.error(str(exc))
        st.stop()
    music = load_music(str(DEFAULT_MUSIC_CSV_PATH))

    cache = load_cache(cache_path)

    view = st.segmented_control(
        "Navigate Millenial Antiquing",
        ["Home", "Movies", "Music", "Music Stats", "Lossless", "Missing Albums", "Trends", "Decades", "Genres", "Table"],
        default="Home",
        label_visibility="collapsed",
        key="main_navigation",
    )

    if view == "Home":
        render_everything_search(movies, music)
        st.divider()
        render_home_dashboard(movies, music)
    elif view == "Movies":
        with st.expander("Search, filter, and sort", expanded=True):
            filtered = filter_movies(movies)
        render_movie_grid(
            filtered,
            token,
            api_key,
            cache_path,
            cache,
        )
    elif view == "Music":
        render_music(music)
    elif view == "Music Stats":
        render_music_stats(music)
    elif view == "Lossless":
        render_lossless_collection()
    elif view == "Missing Albums":
        render_missing_albums()
    elif view == "Trends":
        render_metadata_sync(movies, token, api_key, cache_path, cache)
        render_trends(movies, cache)
    elif view == "Decades":
        render_metadata_sync(movies, token, api_key, cache_path, cache)
        render_decades(movies, cache)
    elif view == "Genres":
        render_metadata_sync(movies, token, api_key, cache_path, cache)
        render_genres(movies, cache)
    else:
        with st.expander("Search, filter, and sort", expanded=True):
            filtered = filter_movies(movies)
        render_table(filtered)


if __name__ == "__main__":
    main()
