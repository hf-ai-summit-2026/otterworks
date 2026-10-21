from __future__ import annotations

import re

SIZE_UNITS = {
    "": 1,
    "B": 1,
    "K": 1024,
    "KB": 1024,
    "M": 1024**2,
    "MB": 1024**2,
    "G": 1024**3,
    "GB": 1024**3,
    "T": 1024**4,
    "TB": 1024**4,
}
DURATION_UNITS = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 24 * 60 * 60,
    "w": 7 * 24 * 60 * 60,
    "y": 365 * 24 * 60 * 60,
}


def parse_size(value: str) -> int:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([A-Za-z]*)\s*", value)
    if not match:
        raise ValueError(f"Invalid size: {value!r}")
    number, suffix = match.groups()
    multiplier = SIZE_UNITS.get(suffix.upper())
    if multiplier is None:
        raise ValueError(f"Invalid size unit in {value!r}")
    return int(float(number) * multiplier)


def parse_duration(value: str) -> int:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([A-Za-z])\s*", value)
    if not match:
        raise ValueError(f"Invalid duration: {value!r}")
    number, suffix = match.groups()
    multiplier = DURATION_UNITS.get(suffix.lower())
    if multiplier is None:
        raise ValueError(f"Invalid duration unit in {value!r}")
    return int(float(number) * multiplier)


def format_size(size: float) -> str:
    amount = float(size)
    if abs(amount) < 1024:
        return f"{int(amount)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        amount /= 1024
        if abs(amount) < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}"
    return f"{amount:.1f} TB"
