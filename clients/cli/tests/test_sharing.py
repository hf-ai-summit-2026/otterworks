import io
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from otter_cli import cli as cli_module
from otter_cli.client import OtterClient

OWNER_ID = "00000000-0000-0000-0000-000000000001"
RECIPIENT_ID = "00000000-0000-0000-0000-000000000002"
FINANCE_ID = "00000000-0000-0000-0000-000000000003"
FILE_ID = "00000000-0000-0000-0000-000000000004"
SECOND_FILE_ID = "00000000-0000-0000-0000-000000000005"
SHARE_ID = "00000000-0000-0000-0000-000000000006"
OWNER_EMAIL = "owner@example.test"
RECIPIENT_EMAIL = "recipient@example.test"
DOWNLOAD_BYTES = b"\x00OtterWorks fixture bytes\xff"


def fixture_file(file_id=FILE_ID, name="report.txt"):
    return {
        "id": file_id,
        "name": name,
        "folderId": FINANCE_ID,
        "ownerId": OWNER_ID,
        "mimeType": "text/plain",
        "sizeBytes": 24,
        "version": 3,
        "isTrashed": False,
        "createdAt": "2025-01-01T00:00:00Z",
        "updatedAt": "2025-01-02T00:00:00Z",
    }


def fixture_share(file_id=FILE_ID, user_id=RECIPIENT_ID, permission="viewer"):
    return {
        "id": SHARE_ID,
        "fileId": file_id,
        "sharedWith": user_id,
        "permission": permission,
        "sharedBy": OWNER_ID,
        "createdAt": "2025-01-02T00:00:00Z",
    }


def install_share_client(
    monkeypatch,
    tmp_path,
    *,
    folders=None,
    files=None,
    shares=None,
    users=None,
    shared_files=None,
):
    folders = deepcopy(
        folders
        if folders is not None
        else [{"id": FINANCE_ID, "name": "Finance", "parentId": None}]
    )
    files = deepcopy(files if files is not None else [fixture_file()])
    shares = deepcopy(shares or {})
    users = deepcopy(
        users
        if users is not None
        else {
            OWNER_ID: {"id": OWNER_ID, "email": OWNER_EMAIL, "displayName": "Owner"},
            RECIPIENT_ID: {
                "id": RECIPIENT_ID,
                "email": RECIPIENT_EMAIL,
                "displayName": "Recipient",
            },
        }
    )
    calls = []

    def handler(request):
        path = request.url.path
        payload = json.loads(request.content) if request.content else None
        calls.append((request.method, path, dict(request.url.params), payload))

        if request.method == "GET" and path == "/api/v1/folders":
            parent = request.url.params.get("parent_id")
            return httpx.Response(
                200,
                json={
                    "folders": [
                        folder
                        for folder in folders
                        if str(folder.get("parentId") or "") == str(parent or "")
                    ]
                },
            )
        if request.method == "GET" and path in {
            "/api/v1/files",
            "/api/v1/files/shared",
        }:
            page = int(request.url.params.get("page", "1"))
            if path.endswith("/shared"):
                source = shared_files if shared_files is not None else files
                page_size = 100
            else:
                source = files
                page_size = 1000
            start = (page - 1) * page_size
            return httpx.Response(
                200,
                json={
                    "files": source[start : start + page_size],
                    "total": len(source),
                    "page": page,
                    "page_size": page_size,
                },
            )
        if request.method == "GET" and path == "/api/v1/auth/profile":
            return httpx.Response(
                200,
                json={"id": OWNER_ID, "email": OWNER_EMAIL, "display_name": "Owner"},
            )
        if request.method == "GET" and path == "/api/v1/auth/users/lookup":
            user = next(
                (entry for entry in users.values() if entry["email"] == request.url.params.get("email")),
                None,
            )
            if user is None:
                return httpx.Response(
                    400, json={"message": "User not found with email"}
                )
            return httpx.Response(200, json=user)
        if request.method == "GET" and path.startswith(
            "/api/v1/auth/users/by-id/"
        ):
            user_id = path.rsplit("/", 1)[-1]
            if user_id not in users:
                return httpx.Response(404, json={"message": "User not found"})
            return httpx.Response(200, json=users[user_id])
        if request.method == "GET" and path.startswith("/api/v1/files/"):
            suffix = path.removeprefix("/api/v1/files/")
            if suffix.endswith("/download"):
                return httpx.Response(
                    200,
                    json={"url": "http://localstack:4566/bucket/report.txt?sig=test"},
                )
            file_id = suffix
            file = next(file for file in files if file["id"] == file_id)
            return httpx.Response(
                200,
                json={**file, "shared_with": shares.get(file_id, [])},
            )
        if (
            request.method == "GET"
            and request.url.host == "localhost"
            and request.url.port == 4566
        ):
            return httpx.Response(200, content=DOWNLOAD_BYTES)
        if request.method == "POST" and path.endswith("/share"):
            file_id = path.split("/")[-2]
            share = fixture_share(
                file_id, payload["shared_with"], payload["permission"]
            )
            current = shares.setdefault(file_id, [])
            previous = next(
                (item for item in current if item["sharedWith"] == payload["shared_with"]),
                None,
            )
            if previous:
                previous["permission"] = payload["permission"]
                previous["sharedBy"] = payload["shared_by"]
                share = previous
            else:
                current.append(share)
            return httpx.Response(201, json={"share": share})
        if request.method == "DELETE" and "/share/" in path:
            file_id, user_id = path.split("/share/", 1)
            file_id = file_id.rsplit("/", 1)[-1]
            current = shares.get(file_id, [])
            match = next(
                (item for item in current if item["sharedWith"] == user_id), None
            )
            if match is None:
                return httpx.Response(404, json={"message": "Share not found"})
            current.remove(match)
            return httpx.Response(204)
        if (
            request.method == "GET"
            and request.url.host == "localstack"
            and request.url.port == 4566
        ):
            return httpx.Response(200, content=DOWNLOAD_BYTES)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("OTTER_TOKEN", "mock-token")
    monkeypatch.delenv("OTTER_DOWNLOAD_HOST", raising=False)
    monkeypatch.setattr(
        cli_module,
        "OtterClient",
        lambda api_url=None: OtterClient(api_url=api_url, transport=transport),
    )
    return calls, shares


def mutations(calls):
    return [call for call in calls if call[0] in {"POST", "DELETE"}]


@pytest.mark.parametrize(
    ("arguments", "permission"),
    [
        (["share", "/Finance/report.txt", "--with", RECIPIENT_EMAIL], "viewer"),
        (
            ["share", "/Finance/report.txt", "--with", RECIPIENT_EMAIL, "--edit"],
            "editor",
        ),
    ],
)
def test_share_posts_permission_and_user_ids(
    monkeypatch, tmp_path, capsys, arguments, permission
):
    calls, _shares = install_share_client(monkeypatch, tmp_path)

    assert cli_module.main(arguments) == 0

    post = next(call for call in calls if call[0] == "POST")
    assert post[:2] == ("POST", f"/api/v1/files/{FILE_ID}/share")
    assert post[3] == {
        "shared_with": RECIPIENT_ID,
        "permission": permission,
        "shared_by": OWNER_ID,
    }
    assert f"Shared /Finance/report.txt with {RECIPIENT_EMAIL} ({permission})" in (
        capsys.readouterr().out
    )


def test_share_unknown_email_has_clear_error_without_mutation(
    monkeypatch, tmp_path, capsys
):
    calls, _shares = install_share_client(monkeypatch, tmp_path)
    unknown = "missing@example.test"

    assert cli_module.main(["share", "/Finance/report.txt", "--with", unknown]) == 1

    assert f"No OtterWorks user with email {unknown}" in capsys.readouterr().err
    assert mutations(calls) == []


def test_share_refuses_folders(monkeypatch, tmp_path, capsys):
    calls, _shares = install_share_client(monkeypatch, tmp_path)

    assert cli_module.main(["share", "/Finance", "--with", RECIPIENT_EMAIL]) == 1

    assert "only accepts files" in capsys.readouterr().err
    assert not any(path == "/api/v1/auth/users/lookup" for _, path, _, _ in calls)
    assert mutations(calls) == []


def test_unshare_deletes_share_and_reports_path(monkeypatch, tmp_path, capsys):
    calls, _shares = install_share_client(
        monkeypatch,
        tmp_path,
        shares={FILE_ID: [fixture_share()]},
    )

    assert (
        cli_module.main(
            ["unshare", "/Finance/report.txt", "--with", RECIPIENT_EMAIL]
        )
        == 0
    )

    assert mutations(calls) == [
        ("DELETE", f"/api/v1/files/{FILE_ID}/share/{RECIPIENT_ID}", {}, None)
    ]
    assert f"Stopped sharing /Finance/report.txt with {RECIPIENT_EMAIL}" in (
        capsys.readouterr().out
    )


def test_unshare_missing_share_has_clear_error(monkeypatch, tmp_path, capsys):
    calls, _shares = install_share_client(monkeypatch, tmp_path)

    assert (
        cli_module.main(
            ["unshare", "/Finance/report.txt", "--with", RECIPIENT_EMAIL]
        )
        == 1
    )

    assert "No share exists" in capsys.readouterr().err
    assert mutations(calls) == [
        ("DELETE", f"/api/v1/files/{FILE_ID}/share/{RECIPIENT_ID}", {}, None)
    ]


def test_shared_resolves_owner_once_for_multiple_files(
    monkeypatch, tmp_path, capsys
):
    files = [
        fixture_file(FILE_ID, "one.txt"),
        fixture_file(SECOND_FILE_ID, "two.txt"),
    ]
    calls, _shares = install_share_client(
        monkeypatch, tmp_path, shared_files=files
    )

    assert cli_module.main(["shared"]) == 0

    by_id_calls = [
        call
        for call in calls
        if call[0] == "GET" and call[1] == f"/api/v1/auth/users/by-id/{OWNER_ID}"
    ]
    assert len(by_id_calls) == 1
    output = capsys.readouterr().out
    assert "one.txt" in output and "two.txt" in output and OWNER_EMAIL in output


def test_info_file_resolves_shared_email(monkeypatch, tmp_path, capsys):
    calls, _shares = install_share_client(
        monkeypatch, tmp_path, shares={FILE_ID: [fixture_share()]}
    )

    assert cli_module.main(["info", "/Finance/report.txt", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["path"] == "/Finance/report.txt"
    assert output["sizeBytes"] == 24
    assert output["sharedWith"][0]["email"] == RECIPIENT_EMAIL
    assert any(
        call[0] == "GET" and call[1] == f"/api/v1/auth/users/by-id/{RECIPIENT_ID}"
        for call in calls
    )


def test_info_folder_shows_recursive_counts(monkeypatch, tmp_path, capsys):
    files = [
        fixture_file(),
        {
            **fixture_file(SECOND_FILE_ID, "nested.txt"),
            "folderId": None,
            "sizeBytes": 5,
        },
    ]
    folders = [
        {"id": FINANCE_ID, "name": "Finance", "parentId": None},
        {"id": "00000000-0000-0000-0000-000000000007", "name": "Reports", "parentId": FINANCE_ID},
    ]
    install_share_client(monkeypatch, tmp_path, folders=folders, files=files)

    assert cli_module.main(["info", "/Finance"]) == 0

    output = capsys.readouterr().out
    assert "/Finance" in output
    assert "File count" in output and "1" in output
    assert "24 bytes" in output


def test_cat_streams_exact_bytes_and_rewrites_download_host(
    monkeypatch, tmp_path
):
    calls, _shares = install_share_client(monkeypatch, tmp_path, files=[])
    monkeypatch.setenv("OTTER_DOWNLOAD_HOST", "localhost:4566")
    output = io.BytesIO()
    monkeypatch.setattr(cli_module.sys, "stdout", SimpleNamespace(buffer=output))

    assert cli_module.main(["cat", FILE_ID]) == 0

    assert output.getvalue() == DOWNLOAD_BYTES
    assert any(
        call[0] == "GET"
        and call[1] == f"/api/v1/files/{FILE_ID}/download"
        for call in calls
    )
