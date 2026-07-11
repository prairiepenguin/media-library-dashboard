from pathlib import Path

from music_library.scanner import scan


def test_scan_infers_metadata(tmp_path: Path):
    album = tmp_path / "Linkin Park" / "2003 - Meteora"
    album.mkdir(parents=True)
    (album / "01 Foreword.wav").write_bytes(b"not real audio")
    (album / "02 Don't Stay.wav").write_bytes(b"not real audio")
    tracks = scan(tmp_path)
    assert [(t.artist, t.album, t.year, t.track_number, t.track_total) for t in tracks] == [
        ("Linkin Park", "Meteora", 2003, 1, 2),
        ("Linkin Park", "Meteora", 2003, 2, 2),
    ]


def test_scan_keeps_artist_level_tracks(tmp_path: Path):
    artist = tmp_path / "The Wallflowers"
    artist.mkdir()
    (artist / "01 One Headlight.wav").write_bytes(b"not real audio")
    track = scan(tmp_path)[0]
    assert (track.artist, track.album, track.title) == ("The Wallflowers", "Unknown Album", "One Headlight")
