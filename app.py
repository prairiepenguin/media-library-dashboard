import json
from pathlib import Path

import streamlit as st

DATA = Path(__file__).parent / "data"

st.set_page_config(page_title="Music Library", page_icon="🎵", layout="wide")
st.title("Music Library")

inventory_path = DATA / "inventory.json"
if not inventory_path.exists():
    st.info("No inventory has been generated yet. Run the scan command locally, then commit data/inventory.json.")
    st.stop()

inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
summary = inventory["summary"]
cols = st.columns(3)
cols[0].metric("Artists", summary["artists"])
cols[1].metric("Albums", summary["albums"])
cols[2].metric("Tracks", summary["tracks"])
st.caption(f"Catalog updated {inventory['generated_at']}")

owned_tab, missing_tab = st.tabs(["Owned albums", "Missing albums"])
with owned_tab:
    artist = st.selectbox("Artist", ["All"] + sorted({a["artist"] for a in inventory["albums"]}))
    rows = inventory["albums"] if artist == "All" else [a for a in inventory["albums"] if a["artist"] == artist]
    st.dataframe(rows, width="stretch", hide_index=True)

with missing_tab:
    missing_path = DATA / "missing_albums.json"
    if not missing_path.exists():
        st.info("Run the catalog command locally to populate missing albums.")
    else:
        catalog = json.loads(missing_path.read_text(encoding="utf-8"))
        rows = [{"artist": a["artist"], **album} for a in catalog["artists"] for album in a["missing"]]
        st.dataframe(rows, width="stretch", hide_index=True)
