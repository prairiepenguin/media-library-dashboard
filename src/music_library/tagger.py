from __future__ import annotations

from dataclasses import dataclass

from .scanner import Track


@dataclass
class TagResult:
    path: str
    status: str
    fields: list[str]
    error: str | None = None


def desired_tags(track: Track) -> dict[str, str]:
    values = {
        "TPE1": track.artist,
        "TPE2": track.artist,
        "TALB": track.album,
        "TIT2": track.title,
    }
    if track.track_number is not None:
        values["TRCK"] = f"{track.track_number}/{track.track_total}" if track.track_total else str(track.track_number)
    if track.disc_number is not None:
        values["TPOS"] = str(track.disc_number)
    if track.year is not None:
        values["TDRC"] = str(track.year)
    return values


def tag_track(track: Track, apply: bool = False, overwrite: bool = False) -> TagResult:
    try:
        from mutagen.id3 import ID3, Frames
        from mutagen.wave import WAVE

        # Some rippers place an ID3v2 block before the RIFF header. That is not a
        # standard RIFF chunk, but Mutagen's ID3 parser can safely handle it.
        with open(track.path, "rb") as source:
            prefixed_id3 = source.read(3) == b"ID3"
        audio = None
        if prefixed_id3:
            tags = ID3(track.path)
        else:
            audio = WAVE(track.path)
            if audio.tags is None:
                audio.add_tags()
            assert isinstance(audio.tags, ID3)
            tags = audio.tags
        changed: list[str] = []
        for frame_id, value in desired_tags(track).items():
            if tags.get(frame_id) is not None and not overwrite:
                continue
            frame_type = Frames[frame_id]
            tags.setall(frame_id, [frame_type(encoding=3, text=[value])])
            changed.append(frame_id)
        if apply and changed:
            if prefixed_id3:
                tags.save(track.path, v2_version=4)
            else:
                assert audio is not None
                audio.save()
        return TagResult(track.path, "updated" if apply and changed else "preview" if changed else "unchanged", changed)
    except Exception as exc:
        return TagResult(track.path, "error", [], str(exc))
