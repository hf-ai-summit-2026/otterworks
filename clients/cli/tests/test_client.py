import json
import stat

import httpx
import pytest

from otter_cli.client import OtterClient, SessionExpiredError, normalize_keys
from otter_cli.config import (
    Credentials,
    credentials_path,
    load_credentials,
    save_credentials,
)


def configure_isolated_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OTTER_TOKEN", raising=False)
    monkeypatch.delenv("OTTER_API_URL", raising=False)


def test_normalize_keys_handles_nested_objects():
    assert normalize_keys({"page_size": 2, "file": {"folder_id": None}}) == {
        "pageSize": 2,
        "file": {"folderId": None},
    }


def test_list_all_files_fetches_all_pages():
    pages = {1: ["a", "b"], 2: ["c", "d"], 3: ["e"]}

    def handler(request):
        page = int(request.url.params["page"])
        return httpx.Response(
            200,
            json={
                "files": [{"id": file_id} for file_id in pages[page]],
                "total": 5,
                "page": page,
                "page_size": 2,
            },
        )

    client = OtterClient(transport=httpx.MockTransport(handler))
    files = client.list_all_files()
    client.close()

    assert [file["id"] for file in files] == ["a", "b", "c", "d", "e"]


def test_refresh_retries_and_saves_new_tokens(monkeypatch, tmp_path):
    configure_isolated_credentials(monkeypatch, tmp_path)
    save_credentials(
        Credentials("http://localhost:8080", "user@example.test", "expired", "old-refresh")
    )
    calls = []

    def handler(request):
        calls.append((request.url.path, request.headers.get("Authorization")))
        if request.url.path == "/api/v1/files":
            if request.headers.get("Authorization") == "Bearer expired":
                return httpx.Response(401, json={"message": "Expired"})
            assert request.headers.get("Authorization") == "Bearer new-access"
            return httpx.Response(200, json={"files": [], "total": 0, "page_size": 1000})
        if request.url.path == "/api/v1/auth/refresh":
            assert request.headers.get("Authorization") == "Bearer old-refresh"
            return httpx.Response(
                200, json={"accessToken": "new-access", "refreshToken": "new-refresh"}
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    client = OtterClient(transport=httpx.MockTransport(handler))
    response = client.get("/files", params={"page": 1})
    client.close()

    assert response["pageSize"] == 1000
    assert [path for path, _ in calls] == [
        "/api/v1/files",
        "/api/v1/auth/refresh",
        "/api/v1/files",
    ]
    saved = load_credentials()
    assert saved.access_token == "new-access"
    assert saved.refresh_token == "new-refresh"


def test_failed_refresh_has_exact_session_expired_message(monkeypatch, tmp_path):
    configure_isolated_credentials(monkeypatch, tmp_path)
    save_credentials(
        Credentials("http://localhost:8080", "user@example.test", "expired", "old-refresh")
    )

    def handler(_request):
        return httpx.Response(401, json={"message": "Rejected"})

    client = OtterClient(transport=httpx.MockTransport(handler))
    with pytest.raises(
        SessionExpiredError, match=r"^Session expired, run `otter login`\.$"
    ):
        client.get("/files")
    client.close()


def test_credentials_file_is_private_and_round_trips(monkeypatch, tmp_path):
    configure_isolated_credentials(monkeypatch, tmp_path)
    credentials = Credentials(
        "http://localhost:8080", "user@example.test", "access", "refresh"
    )

    path = save_credentials(credentials)

    assert path == credentials_path()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_credentials() == credentials
    assert json.loads(path.read_text())["refresh_token"] == "refresh"


def test_stream_download_rewrites_host_and_yields_bytes(monkeypatch):
    monkeypatch.setenv("OTTER_DOWNLOAD_HOST", "localhost:4566")
    requests = []
    payload = b"\x00OtterWorks\xff"

    def handler(request):
        requests.append(request.url)
        return httpx.Response(200, content=payload)

    client = OtterClient(transport=httpx.MockTransport(handler))
    chunks = b"".join(
        client.stream_download(
            "http://localstack:4566/bucket/file?X-Amz-Signature=test"
        )
    )
    client.close()

    assert chunks == payload
    assert requests[0].host == "localhost"
    assert requests[0].port == 4566
    assert requests[0].path == "/bucket/file"
    assert requests[0].query == b"X-Amz-Signature=test"
