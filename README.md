# Millennial Antiquing

One private data pipeline and public read-only Streamlit dashboard for:

- Plex movies, including preserved Blu-ray and DVD ownership fields;
- Plex albums, genres, formats, sizes, durations, and artwork references;
- the local lossless WAV inventory;
- missing studio albums from MusicBrainz.

No Plex token, absolute media path, or audio/video file is committed. Generated inventory paths are relative to the music root.

## Windows setup on the backup drive

Open PowerShell in the project folder:

```powershell
py -m venv .venv
.venv\Scripts\pip.exe install -e .
$env:PLEX_TOKEN = "your-token"
.venv\Scripts\media-library-sync.exe --music-root "M:\"
.venv\Scripts\streamlit.exe run app.py
```

The sync also understands the token saved by the older MovieDB updater in `%USERPROFILE%\.plex_movie_exporter.json`.

## GitHub and nightly publishing

Create an empty private GitHub repository, set it as this repository's `origin`, and make one initial push. Ensure Git credentials work non-interactively on the Windows computer. Then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_nightly_task.ps1
```

The task runs daily at 2:00 AM, refreshes all four generated catalog files, and pushes only when their contents change. The computer and backup drive must be available. Plex must be reachable.

Deploy `app.py` on Streamlit Community Cloud from the same private repository for an always-available read-only dashboard.

## Metadata writes

Nightly sync is read-only toward media files. WAV metadata editing remains an explicit manual operation:

```powershell
.venv\Scripts\music-library.exe tag "M:\"       # preview
.venv\Scripts\music-library.exe tag "M:\" --apply
```
