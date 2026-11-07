from theme import THEME_CSS


def test_theme_is_non_empty():
    assert len(THEME_CSS) > 1000


def test_theme_makes_no_external_requests():
    assert "@import" not in THEME_CSS
    assert "url(http" not in THEME_CSS
    assert "fonts.googleapis" not in THEME_CSS
