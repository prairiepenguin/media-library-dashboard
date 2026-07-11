import json
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

DATA = Path(__file__).parent / "data"


@st.cache_data
def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def artist_summary(inventory: dict, catalog: dict) -> pd.DataFrame:
    owned = Counter(album["artist"] for album in inventory["albums"])
    tracks = Counter(track["artist"] for track in inventory["tracks"])
    missing = {item["artist"]: len(item.get("missing", [])) for item in catalog.get("artists", [])}
    statuses = {item["artist"]: item.get("status", "unknown") for item in catalog.get("artists", [])}
    rows = []
    for artist in sorted(owned, key=str.casefold):
        owned_count = owned[artist]
        missing_count = missing.get(artist, 0)
        total = owned_count + missing_count
        included = statuses.get(artist) != "excluded_collection"
        rows.append({
            "Artist": artist,
            "Owned": owned_count,
            "Missing": missing_count if included else None,
            "Collection %": round(100 * owned_count / total, 1) if total and included else None,
            "Tracks": tracks[artist],
        })
    return pd.DataFrame(rows)


st.set_page_config(page_title="Music Library", page_icon="🎵", layout="wide")
st.title("🎵 Music Library")

inventory_path = DATA / "inventory.json"
if not inventory_path.exists():
    st.info("No inventory has been generated yet. Run the scan command locally, then commit data/inventory.json.")
    st.stop()

inventory = load_json(inventory_path)
missing_path = DATA / "missing_albums.json"
catalog = load_json(missing_path) if missing_path.exists() else {"artists": []}
artists = artist_summary(inventory, catalog)
catalog_by_artist = {item["artist"]: item for item in catalog.get("artists", [])}

query = st.sidebar.text_input("Search artists", placeholder="Try: Queen")
matches = artists[artists["Artist"].str.contains(query, case=False, regex=False)] if query else artists
artist_options = matches["Artist"].tolist()
selected_artist = st.sidebar.selectbox("Selected artist", artist_options, index=None, placeholder="Choose an artist")
st.sidebar.caption("You can also select an artist from the directory table.")

overview_tab, artists_tab, albums_tab = st.tabs(["Overview", "Artists", "All albums"])

with overview_tab:
    valid = artists.dropna(subset=["Missing", "Collection %"])
    total_owned = int(valid["Owned"].sum())
    total_missing = int(valid["Missing"].sum())
    total_known = total_owned + total_missing
    completion = 100 * total_owned / total_known if total_known else 0
    library_bytes = sum(track["size"] for track in inventory["tracks"])

    cols = st.columns(5)
    cols[0].metric("Artists", inventory["summary"]["artists"])
    cols[1].metric("Owned albums", inventory["summary"]["albums"])
    cols[2].metric("Missing albums", total_missing)
    cols[3].metric("Overall coverage", f"{completion:.1f}%")
    cols[4].metric("Lossless audio", f"{library_bytes / 1024**3:.1f} GB")
    st.caption("Coverage compares local album folders with MusicBrainz studio-album release groups. Collections such as Soundtracks are excluded.")

    chart_col, insight_col = st.columns([2, 1])
    with chart_col:
        st.subheader("Collection progress by artist")
        chart_data = valid.sort_values("Collection %", ascending=False).set_index("Artist")[["Collection %"]]
        st.bar_chart(chart_data, horizontal=True, height=max(400, len(chart_data) * 24))
    with insight_col:
        st.subheader("Collection insights")
        closest = valid[valid["Missing"] > 0].sort_values(["Missing", "Collection %"], ascending=[True, False]).head(5)
        biggest = valid.sort_values("Missing", ascending=False).head(5)
        fullest = valid.sort_values(["Collection %", "Owned"], ascending=False).iloc[0]
        st.success(f"Strongest collection: **{fullest['Artist']}** at **{fullest['Collection %']:.1f}%**")
        st.markdown("**Closest to completing**")
        for row in closest.itertuples():
            st.write(f"{row.Artist}: {int(row.Missing)} album{'s' if row.Missing != 1 else ''} away")
        st.markdown("**Biggest discovery opportunities**")
        for row in biggest.itertuples():
            st.write(f"{row.Artist}: {int(row.Missing)} missing")

    years = [album.get("year") for album in inventory["albums"] if album.get("year")]
    if years:
        st.subheader("Owned albums by decade")
        decades = Counter(f"{year // 10 * 10}s" for year in years)
        st.bar_chart(pd.DataFrame({"Albums": decades}).sort_index())

with artists_tab:
    st.subheader("Artist directory")
    st.write("Search with the sidebar, then click a row to open that artist’s collection.")
    event = st.dataframe(
        matches,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={"Collection %": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100)},
    )
    if event.selection.rows:
        selected_artist = matches.iloc[event.selection.rows[0]]["Artist"]

    if selected_artist:
        owned_albums = [album for album in inventory["albums"] if album["artist"] == selected_artist]
        catalog_artist = catalog_by_artist.get(selected_artist, {"missing": [], "status": "not_cataloged"})
        missing_albums = catalog_artist.get("missing", [])
        row = artists[artists["Artist"] == selected_artist].iloc[0]

        st.divider()
        st.header(selected_artist)
        metrics = st.columns(4)
        metrics[0].metric("Owned", int(row["Owned"]))
        metrics[1].metric("Missing", int(row["Missing"]) if pd.notna(row["Missing"]) else "N/A")
        metrics[2].metric("Collection", f"{row['Collection %']:.1f}%" if pd.notna(row["Collection %"]) else "Collection")
        metrics[3].metric("Tracks", int(row["Tracks"]))
        if pd.notna(row["Collection %"]):
            st.progress(float(row["Collection %"]) / 100, text=f"{row['Collection %']:.1f}% of known albums owned")

        owned_col, missing_col = st.columns(2)
        with owned_col:
            st.subheader("✅ Owned")
            st.dataframe(
                pd.DataFrame(owned_albums).rename(columns={"album": "Album", "year": "Year", "track_count": "Tracks", "path": "Folder"})[["Album", "Year", "Tracks"]],
                width="stretch", hide_index=True,
            )
        with missing_col:
            st.subheader("○ Not owned")
            if catalog_artist.get("status") == "excluded_collection":
                st.info("This folder is a collection rather than an artist, so missing albums are not calculated.")
            elif missing_albums:
                missing_frame = pd.DataFrame(missing_albums).rename(columns={"title": "Album", "first_release_date": "First released", "type": "Type"})
                st.dataframe(missing_frame[["Album", "First released"]], width="stretch", hide_index=True)
            else:
                st.success("No missing studio albums found.")

with albums_tab:
    owned_filter, missing_filter = st.columns(2)
    artist_names = sorted(artists["Artist"].tolist(), key=str.casefold)
    chosen = owned_filter.multiselect("Filter artists", artist_names)
    only_missing = missing_filter.checkbox("Show missing albums only")
    owned_rows = [{"Status": "Owned", "Artist": album["artist"], "Album": album["album"], "Year": album.get("year")} for album in inventory["albums"]]
    missing_rows = [
        {"Status": "Missing", "Artist": item["artist"], "Album": album["title"], "Year": album.get("first_release_date")}
        for item in catalog.get("artists", []) for album in item.get("missing", [])
    ]
    rows = missing_rows if only_missing else owned_rows + missing_rows
    if chosen:
        rows = [row for row in rows if row["Artist"] in chosen]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

st.caption(f"Local catalog updated {inventory['generated_at']}")
