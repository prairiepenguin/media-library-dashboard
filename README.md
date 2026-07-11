# Music Library Manager

A conservative, repeatable workflow for a WAV library:

- infer standard ID3 tags from the existing `Artist/Album/Track.wav` layout;
- generate a JSON inventory that changes only when the library changes;
- compare owned albums with MusicBrainz release groups;
- publish the generated catalog as a read-only Streamlit app.

## Setup

```bash
cd /home/jacob/music-library-manager
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Safe first run

Generate the inventory (this never edits music):

```bash
.venv/bin/music-library scan /mnt/TheBackup/Music
```

Preview WAV tag changes (also read-only):

```bash
.venv/bin/music-library tag /mnt/TheBackup/Music
```

Review the preview count. To write only missing tags, make sure the backup is current and run:

```bash
.venv/bin/music-library tag /mnt/TheBackup/Music --apply
```

Existing tag values are preserved. `--overwrite` is deliberately separate and should only be used after reviewing the inferred data.

The tagger supports both standard RIFF/WAVE files and this library's ID3-prefixed WAV files. It does not convert audio or rename files.

## Missing-album catalog

MusicBrainz requires a descriptive User-Agent containing contact information. The project is configured with `jacobingalls@outlook.com`, so the refresh command is:

```bash
.venv/bin/music-library catalog
```

The first refresh is intentionally slow because MusicBrainz permits roughly one request per second. The catalog compares studio release groups of type `Album`; compilations, live releases, soundtracks, EPs, and other secondary types are excluded to reduce noise. A top-level `Soundtracks` collection is not treated as an artist.

## Streamlit

```bash
.venv/bin/streamlit run app.py
```

Commit `data/inventory.json` and `data/missing_albums.json` to GitHub. Streamlit Community Cloud can then run `app.py` from that repository. The hosted app is read-only: it cannot see `/mnt/TheBackup/Music`, so scans and tag writes must run on the machine where the backup is mounted.

The committed inventory contains relative library paths only; it does not publish `/mnt` paths or audio files. GitHub Actions runs the test suite on every push and pull request.

After adding music, rerun `scan`; rerun `catalog` when you want to refresh missing albums. A later phase can automate the local scan/commit/push after we choose the desired schedule and GitHub repository.

## Metadata policy

The first version writes only metadata it can infer reliably: artist, album artist, album, title, track number/total, disc number, and year when encoded in the album folder. Genre, exact release date, MusicBrainz IDs, and cover art require matching an exact release and are intentionally not guessed.
