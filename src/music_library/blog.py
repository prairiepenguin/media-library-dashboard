from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class BlogPost:
    slug: str
    title: str
    published: date
    summary: str
    tags: tuple[str, ...]
    cover_image: str
    body: str


def _parse_tags(value: str) -> tuple[str, ...]:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return tuple(
        item.strip().strip("'\"")
        for item in value.split(",")
        if item.strip().strip("'\"")
    )


def parse_post(path: Path) -> BlogPost:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing opening YAML front matter delimiter")

    try:
        closing = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError("missing closing YAML front matter delimiter") from exc

    metadata: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"invalid front matter line: {line}")
        key, value = line.split(":", 1)
        metadata[key.strip().casefold()] = value.strip().strip("'\"")

    missing = [key for key in ("title", "date", "summary") if not metadata.get(key)]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")

    try:
        published = date.fromisoformat(metadata["date"])
    except ValueError as exc:
        raise ValueError("date must use YYYY-MM-DD format") from exc

    return BlogPost(
        slug=path.stem,
        title=metadata["title"],
        published=published,
        summary=metadata["summary"],
        tags=_parse_tags(metadata.get("tags", "")),
        cover_image=metadata.get("cover_image", ""),
        body="\n".join(lines[closing + 1 :]).strip(),
    )


def load_posts(directory: Path) -> tuple[list[BlogPost], list[str]]:
    posts: list[BlogPost] = []
    errors: list[str] = []
    if not directory.is_dir():
        return posts, errors

    for path in sorted(directory.glob("*.md")):
        try:
            posts.append(parse_post(path))
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"{path.name}: {exc}")
    posts.sort(key=lambda post: (post.published, post.title.casefold()), reverse=True)
    return posts, errors
