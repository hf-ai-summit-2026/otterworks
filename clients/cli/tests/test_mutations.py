import json
from copy import deepcopy

import httpx
import pytest

from otter_cli import cli as cli_module
from otter_cli.client import OtterClient

OWNER_ID = "00000000-0000-0000-0000-000000000001"
FINANCE_ID = "00000000-0000-0000-0000-000000000002"
ARCHIVE_ID = "00000000-0000-0000-0000-000000000003"
REPORTS_ID = "00000000-0000-0000-0000-000000000004"
FILE_ID = "00000000-0000-0000-0000-000000000005"
OTHER_FILE_ID = "00000000-0000-0000-0000-000000000006"
NEW_FOLDER_ID = "00000000-0000-0000-0000-000000000007"


def seeded_folders():
    return [
        {"id": FINANCE_ID, "name": "Finance", "parentId": None},
        {"id": ARCHIVE_ID, "name": "Archive", "parentId": FINANCE_ID},
        {"id": REPORTS_ID, "name": "Reports", "parentId": FINANCE_ID},
    ]


def seeded_files():
    return [
        {
            "id": FILE_ID,
            "name": "report.txt",
            "folderId": FINANCE_ID,
            "sizeBytes": 12,
            "isTrashed": False,
        }
    ]


def install_mutation_client(monkeypatch, tmp_path, folders=None, files=None):
    folders = deepcopy(folders if folders is not None else seeded_folders())
    files = deepcopy(files if files is not None else seeded_files())
    calls = []
    next_folder_id = 0

    def handler(request):
        nonlocal next_folder_id
        path = request.url.path
        payload = json.loads(request.content) if request.content else None
        calls.append((request.method, path, payload))

        if request.method == "GET" and path == "/api/v1/folders":
            parent = request.url.params.get("parent_id")
            rows = [
                folder
                for folder in folders
                if str(folder.get("parentId") or "") == str(parent or "")
            ]
            return httpx.Response(200, json={"folders": rows})
        if request.method == "GET" and path == "/api/v1/files":
            return httpx.Response(
                200,
                json={
                    "files": files,
                    "total": len(files),
                    "page": 1,
                    "page_size": 1000,
                },
            )
        if request.method == "GET" and path == "/api/v1/auth/profile":
            return httpx.Response(
                200,
                json={
                    "id": OWNER_ID,
                    "email": "seeded@example.test",
                    "display_name": "OtterWorks Drive",
                },
            )
        if request.method == "POST" and path == "/api/v1/auth/login":
            return httpx.Response(
                200,
                json={
                    "accessToken": "mock-access",
                    "refreshToken": "mock-refresh",
                    "user": {"email": payload["email"]},
                },
            )
        if request.method == "POST" and path == "/api/v1/folders":
            next_folder_id += 1
            folder = {
                "id": f"00000000-0000-0000-0000-{next_folder_id + 100:012d}",
                "name": payload["name"],
                "parentId": payload.get("parent_id"),
            }
            folders.append(folder)
            return httpx.Response(201, json=folder)
        if request.method == "PUT" and path.startswith("/api/v1/folders/"):
            folder_id = path.rsplit("/", 1)[-1]
            folder = next(folder for folder in folders if folder["id"] == folder_id)
            if payload.get("name") is not None:
                folder["name"] = payload["name"]
            if payload.get("parent_id") is not None:
                folder["parentId"] = payload["parent_id"]
            return httpx.Response(200, json=folder)
        if request.method == "PUT" and path.endswith("/move"):
            file_id = path.split("/")[-2]
            file = next(file for file in files if file["id"] == file_id)
            file["folderId"] = payload["folder_id"]
            return httpx.Response(200, json=file)
        if request.method == "PATCH" and path.endswith("/rename"):
            file_id = path.split("/")[-2]
            file = next(file for file in files if file["id"] == file_id)
            file["name"] = payload["name"]
            return httpx.Response(200, json=file)
        raise AssertionError(f"Unexpected request: {request.method} {path}")

    transport = httpx.MockTransport(handler)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("OTTER_TOKEN", "mock-token")
    monkeypatch.setattr(
        cli_module,
        "OtterClient",
        lambda api_url=None: OtterClient(api_url=api_url, transport=transport),
    )
    return calls, folders, files


def mutations(calls):
    return [call for call in calls if call[0] in {"POST", "PUT", "PATCH"}]


def test_mkdir_creates_folder_with_owner_and_parent(monkeypatch, tmp_path, capsys):
    calls, _folders, _files = install_mutation_client(
        monkeypatch, tmp_path, folders=[seeded_folders()[0]], files=[]
    )

    assert cli_module.main(["mkdir", "/Finance/Archive"]) == 0

    post = next(call for call in calls if call[0] == "POST")
    assert post[:2] == ("POST", "/api/v1/folders")
    assert post[2] == {
        "name": "Archive",
        "parent_id": FINANCE_ID,
        "owner_id": OWNER_ID,
    }
    assert capsys.readouterr().out.strip().endswith("/Finance/Archive")


def test_mkdir_existing_folder_errors(monkeypatch, tmp_path, capsys):
    calls, _folders, _files = install_mutation_client(monkeypatch, tmp_path)

    assert cli_module.main(["mkdir", "/Finance"]) == 1

    assert "Already exists: /Finance" in capsys.readouterr().err
    assert mutations(calls) == []


def test_mkdir_parents_creates_only_missing_levels(monkeypatch, tmp_path, capsys):
    calls, _folders, _files = install_mutation_client(
        monkeypatch,
        tmp_path,
        folders=seeded_folders()[:2],
        files=[],
    )

    assert cli_module.main(["mkdir", "-p", "/Finance/Archive/2025/Q1"]) == 0

    posts = [call for call in calls if call[0] == "POST"]
    assert [call[2]["name"] for call in posts] == ["2025", "Q1"]
    assert [call[2]["parent_id"] for call in posts] == [
        ARCHIVE_ID,
        "00000000-0000-0000-0000-000000000101",
    ]
    assert all(call[2]["owner_id"] == OWNER_ID for call in posts)
    assert capsys.readouterr().out.strip().endswith("/Finance/Archive/2025/Q1")


def test_mkdir_without_parents_rejects_missing_parent(monkeypatch, tmp_path, capsys):
    calls, _folders, _files = install_mutation_client(monkeypatch, tmp_path)

    assert cli_module.main(["mkdir", "/Missing/Child"]) == 1

    assert "Parent folder not found" in capsys.readouterr().err
    assert mutations(calls) == []


def test_mv_moves_file_into_folder(monkeypatch, tmp_path, capsys):
    calls, _folders, _files = install_mutation_client(monkeypatch, tmp_path)

    assert cli_module.main(["mv", "/Finance/report.txt", "/Finance/Archive"]) == 0

    assert mutations(calls) == [
        (
            "PUT",
            f"/api/v1/files/{FILE_ID}/move",
            {"folder_id": ARCHIVE_ID},
        )
    ]
    assert capsys.readouterr().out.strip() == (
        "/Finance/report.txt -> /Finance/Archive/report.txt"
    )


def test_mv_file_to_root_sends_null_folder_id(monkeypatch, tmp_path, capsys):
    calls, _folders, _files = install_mutation_client(monkeypatch, tmp_path)

    assert cli_module.main(["mv", "/Finance/report.txt", "/"]) == 0

    assert mutations(calls) == [
        ("PUT", f"/api/v1/files/{FILE_ID}/move", {"folder_id": None})
    ]
    assert capsys.readouterr().out.strip() == "/Finance/report.txt -> /report.txt"


def test_mv_file_move_and_rename(monkeypatch, tmp_path, capsys):
    calls, _folders, _files = install_mutation_client(monkeypatch, tmp_path)

    assert (
        cli_module.main(
            ["mv", "/Finance/report.txt", "/Finance/Archive/final.txt"]
        )
        == 0
    )

    assert mutations(calls) == [
        (
            "PUT",
            f"/api/v1/files/{FILE_ID}/move",
            {"folder_id": ARCHIVE_ID},
        ),
        (
            "PATCH",
            f"/api/v1/files/{FILE_ID}/rename",
            {"name": "final.txt"},
        ),
    ]
    assert capsys.readouterr().out.strip() == (
        "/Finance/report.txt -> /Finance/Archive/final.txt"
    )


def test_mv_rename_only_skips_move_request(monkeypatch, tmp_path, capsys):
    calls, _folders, _files = install_mutation_client(monkeypatch, tmp_path)

    assert cli_module.main(["mv", "/Finance/report.txt", "/Finance/new.txt"]) == 0

    assert mutations(calls) == [
        (
            "PATCH",
            f"/api/v1/files/{FILE_ID}/rename",
            {"name": "new.txt"},
        )
    ]
    assert capsys.readouterr().out.strip() == (
        "/Finance/report.txt -> /Finance/new.txt"
    )


def test_mv_moves_folder_into_folder(monkeypatch, tmp_path, capsys):
    calls, _folders, _files = install_mutation_client(monkeypatch, tmp_path)

    assert cli_module.main(["mv", "/Finance/Reports", "/Finance/Archive"]) == 0

    assert mutations(calls) == [
        (
            "PUT",
            f"/api/v1/folders/{REPORTS_ID}",
            {"parent_id": ARCHIVE_ID},
        )
    ]
    assert capsys.readouterr().out.strip() == (
        "/Finance/Reports -> /Finance/Archive/Reports"
    )


def test_mv_folder_to_own_descendant_is_refused_before_mutation(
    monkeypatch, tmp_path, capsys
):
    calls, _folders, _files = install_mutation_client(monkeypatch, tmp_path)

    assert (
        cli_module.main(["mv", "/Finance", "/Finance/Reports"]) == 1
    )

    assert "itself or its descendants" in capsys.readouterr().err
    assert mutations(calls) == []


def test_mv_name_collision_is_refused_before_mutation(monkeypatch, tmp_path, capsys):
    files = seeded_files() + [
        {
            "id": OTHER_FILE_ID,
            "name": "report.txt",
            "folderId": ARCHIVE_ID,
            "sizeBytes": 8,
            "isTrashed": False,
        }
    ]
    calls, _folders, _files = install_mutation_client(
        monkeypatch, tmp_path, files=files
    )

    assert cli_module.main(["mv", "/Finance/report.txt", "/Finance/Archive"]) == 1

    assert "already contains" in capsys.readouterr().err
    assert mutations(calls) == []


def test_mv_multiple_sources_require_existing_folder(
    monkeypatch, tmp_path, capsys
):
    files = seeded_files() + [
        {
            "id": OTHER_FILE_ID,
            "name": "other.txt",
            "folderId": FINANCE_ID,
            "sizeBytes": 4,
            "isTrashed": False,
        }
    ]
    calls, _folders, _files = install_mutation_client(
        monkeypatch, tmp_path, files=files
    )

    assert (
        cli_module.main(
            [
                "mv",
                "/Finance/report.txt",
                "/Finance/other.txt",
                "/Finance/new-name.txt",
            ]
        )
        == 1
    )

    assert "Multiple sources require an existing destination folder" in capsys.readouterr().err
    assert mutations(calls) == []


def test_rename_file_uses_patch(monkeypatch, tmp_path, capsys):
    calls, _folders, _files = install_mutation_client(monkeypatch, tmp_path)

    assert cli_module.main(["rename", "/Finance/report.txt", "final.txt"]) == 0

    assert mutations(calls) == [
        (
            "PATCH",
            f"/api/v1/files/{FILE_ID}/rename",
            {"name": "final.txt"},
        )
    ]
    assert capsys.readouterr().out.strip() == (
        "/Finance/report.txt -> /Finance/final.txt"
    )


def test_rename_folder_uses_put(monkeypatch, tmp_path, capsys):
    calls, _folders, _files = install_mutation_client(monkeypatch, tmp_path)

    assert cli_module.main(["rename", "/Finance/Reports", "Monthly"]) == 0

    assert mutations(calls) == [
        ("PUT", f"/api/v1/folders/{REPORTS_ID}", {"name": "Monthly"})
    ]
    assert capsys.readouterr().out.strip() == (
        "/Finance/Reports -> /Finance/Monthly"
    )


def test_rename_refuses_sibling_name_collision(monkeypatch, tmp_path, capsys):
    folders = seeded_folders() + [
        {
            "id": NEW_FOLDER_ID,
            "name": "Monthly",
            "parentId": FINANCE_ID,
        }
    ]
    calls, _folders, _files = install_mutation_client(
        monkeypatch, tmp_path, folders=folders
    )

    assert (
        cli_module.main(["rename", "/Finance/Reports", "Monthly"]) == 1
    )

    assert "already exists" in capsys.readouterr().err
    assert mutations(calls) == []


def test_rename_rejects_slashes_with_usage_error(capsys):
    with pytest.raises(SystemExit) as error:
        cli_module.main(["rename", "/Finance/report.txt", "bad/name"])

    assert error.value.code == 2
    assert "NEW_NAME" in capsys.readouterr().err


def test_login_prints_email(monkeypatch, tmp_path, capsys):
    install_mutation_client(monkeypatch, tmp_path)
    monkeypatch.setenv("OTTER_PASSWORD", "mock-password")

    assert (
        cli_module.main(["login", "--email", "seeded@example.test"]) == 0
    )

    assert capsys.readouterr().out.strip() == "Logged in as seeded@example.test"


def test_whoami_shows_email_name_and_id(monkeypatch, tmp_path, capsys):
    install_mutation_client(monkeypatch, tmp_path)

    assert cli_module.main(["whoami"]) == 0

    output = capsys.readouterr().out
    assert "Email" in output and "seeded@example.test" in output
    assert "Name" in output and "OtterWorks Drive" in output
    assert "ID" in output and OWNER_ID in output
