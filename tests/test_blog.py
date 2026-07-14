from datetime import date

from music_library.blog import load_posts, parse_post


def test_parse_post_reads_front_matter_and_body(tmp_path):
    path = tmp_path / "first-post.md"
    path.write_text(
        """---
title: First Post
date: 2026-07-14
summary: A quick introduction.
tags: [movies, collecting]
cover_image: images/first.jpg
---
# Hello

This is the body.
""",
        encoding="utf-8",
    )

    post = parse_post(path)

    assert post.slug == "first-post"
    assert post.title == "First Post"
    assert post.published == date(2026, 7, 14)
    assert post.tags == ("movies", "collecting")
    assert post.body == "# Hello\n\nThis is the body."


def test_load_posts_sorts_newest_first_and_reports_invalid_files(tmp_path):
    (tmp_path / "older.md").write_text(
        "---\ntitle: Older\ndate: 2025-01-01\nsummary: Old.\n---\nBody",
        encoding="utf-8",
    )
    (tmp_path / "newer.md").write_text(
        "---\ntitle: Newer\ndate: 2026-01-01\nsummary: New.\n---\nBody",
        encoding="utf-8",
    )
    (tmp_path / "broken.md").write_text("No front matter", encoding="utf-8")

    posts, errors = load_posts(tmp_path)

    assert [post.title for post in posts] == ["Newer", "Older"]
    assert errors == ["broken.md: missing opening YAML front matter delimiter"]
