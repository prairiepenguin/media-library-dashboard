from music_library.cover_art import match_score, normalize


def test_normalize_ignores_common_edition_words():
    assert normalize("The Album: Deluxe Remastered Edition") == "the album"


def test_match_score_prefers_same_artist_and_album():
    candidate = {"title": "Gold: Greatest Hits", "artist-credit": [{"name": "ABBA"}]}
    assert match_score("ABBA", "Gold Greatest Hits", candidate) >= 90
