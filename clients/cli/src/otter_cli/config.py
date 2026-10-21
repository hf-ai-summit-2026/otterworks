from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_API_URL = "http://localhost:8080"


@dataclass
class Credentials:
    api_url: str
    email: str
    access_token: str
    refresh_token: str


def credentials_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return base / "otter" / "credentials.json"


def load_credentials() -> Credentials | None:
    path = credentials_path()
    if not path.exists():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return Credentials(
        api_url=str(data.get("api_url", DEFAULT_API_URL)),
        email=str(data.get("email", "")),
        access_token=str(data.get("access_token", "")),
        refresh_token=str(data.get("refresh_token", "")),
    )


def save_credentials(credentials: Credentials) -> Path:
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(asdict(credentials), stream, indent=2)
        stream.write("\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return path


def delete_credentials() -> None:
    try:
        credentials_path().unlink()
    except FileNotFoundError:
        pass


def resolve_api_url(
    api_url: str | None = None, credentials: Credentials | None = None
) -> str:
    return (
        api_url
        or os.environ.get("OTTER_API_URL")
        or (credentials.api_url if credentials else None)
        or DEFAULT_API_URL
    ).rstrip("/")
