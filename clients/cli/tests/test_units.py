import pytest

from otter_cli.units import format_size, parse_duration, parse_size


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", 0),
        ("512", 512),
        ("1K", 1024),
        ("1.5MB", 1536 * 1024),
        ("2G", 2 * 1024**3),
        ("1B", 1),
    ],
)
def test_parse_size(value, expected):
    assert parse_size(value) == expected


@pytest.mark.parametrize("value", ["", "-1", "1XB", "1.2.3K", "one"])
def test_parse_size_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="Invalid size"):
        parse_size(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0s", 0),
        ("12h", 12 * 60 * 60),
        ("30d", 30 * 24 * 60 * 60),
        ("6w", 6 * 7 * 24 * 60 * 60),
        ("1y", 365 * 24 * 60 * 60),
    ],
)
def test_parse_duration(value, expected):
    assert parse_duration(value) == expected


@pytest.mark.parametrize("value", ["", "-1d", "1", "3q", "1dd"])
def test_parse_duration_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="Invalid duration"):
        parse_duration(value)


def test_format_size_uses_binary_units():
    assert format_size(512) == "512 B"
    assert format_size(1024) == "1.0 KB"
    assert format_size(37_300_000) == "35.6 MB"
