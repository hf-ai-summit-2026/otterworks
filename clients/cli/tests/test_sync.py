import json
import re
from copy import deepcopy

import httpx

from otter_cli import cli as cli_module
from otter_cli.client import OtterClient

OWNER_ID = "00000000-0000-0000-0000-000000000001"
FINANCE_ID = "00000000-0000-0000-0000-000000000002"


def install_sync_client(
    monkeypatch,
    tmp_path,
    *,
    folders=None,
    files=None,
    fail_upload=False,
    fail_trash=False,
):
    folders = deepcopy(
        folders
        if folders is not None
        else [{"id": FINANCE_ID, "name": "Finance", "parentId": None}]
    )
    files = deepcopy(files if files is not None else [])
    calls = []
    uploads = []
    next_folder_id = 0
    next_file_id = 0

    def handler(request):
        nonlocal next_folder_id, next_file_id
        path = request.url.path
        content_type = request.headers.get("content-type", "")
        payload = (
            json.loads(request.content)
            if content_type.startswith("application/json") and request.content
            else None
        )
        calls.append((request.method, path, payload))

        if request.method == "GET" and path == "/api/v1/folders":
            parent_id = request.url.params.get("parent_id")
            rows = [
                folder
                for folder in folders
                if str(folder.get("parentId") or "") == str(parent_id or "")
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
            return httpx.Response(200, json={"id": OWNER_ID})
        if request.method == "POST" and path == "/api/v1/folders":
            next_folder_id += 1
            folder = {
                "id": f"folder-{next_folder_id}",
                "name": payload["name"],
                "parentId": payload.get("parent_id"),
            }
            folders.append(folder)
            return httpx.Response(201, json=folder)
        if request.method == "POST" and path == "/api/v1/files/upload":
            if fail_upload:
                return httpx.Response(500, json={"message": "upload failed"})
            file_name = re.search(rb'filename="([^"]+)"', request.content)
            folder_match = re.search(
                rb'name="folder_id"\r\n\r\n([^\r\n]*)', request.content
            )
            name = file_name.group(1).decode() if file_name else "uploaded.bin"
            folder_id = folder_match.group(1).decode() if folder_match else None
            uploads.append({"name": name, "folder_id": folder_id})
            next_file_id += 1
            uploaded = {
                "id": f"uploaded-{next_file_id}",
                "name": name,
                "folder_id": folder_id,
                "size_bytes": 0,
                "is_trashed": False,
            }
            files.append(uploaded)
            return httpx.Response(201, json={"file": uploaded})
        if request.method == "POST" and path.endswith("/trash"):
            if fail_trash:
                return httpx.Response(500, json={"message": "trash failed"})
            file_id = path.rsplit("/", 2)[-2]
            file = next(file for file in files if file["id"] == file_id)
            file["isTrashed"] = True
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
    return calls, folders, files, uploads


def write_file(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_sync_classifies_new_same_changed_and_ambiguous(
    monkeypatch, tmp_path, capsys
):
    local = tmp_path / "local"
    write_file(local, "new.txt", b"new")
    write_file(local, "same.txt", b"same")
    write_file(local, "changed.txt", b"longer")
    write_file(local, "duplicate.txt", b"x")
    write_file(local, "trashed.txt", b"fresh")
    remote = [
        {
            "id": "same-id",
            "name": "same.txt",
            "folderId": FINANCE_ID,
            "sizeBytes": 4,
            "isTrashed": False,
        },
        {
            "id": "changed-id",
            "name": "changed.txt",
            "folderId": FINANCE_ID,
            "sizeBytes": 1,
            "isTrashed": False,
        },
        {
            "id": "duplicate-1",
            "name": "duplicate.txt",
            "folderId": FINANCE_ID,
            "sizeBytes": 1,
            "isTrashed": False,
        },
        {
            "id": "duplicate-2",
            "name": "duplicate.txt",
            "folderId": FINANCE_ID,
            "sizeBytes": 2,
            "isTrashed": False,
        },
        {
            "id": "trashed-id",
            "name": "trashed.txt",
            "folderId": FINANCE_ID,
            "sizeBytes": 5,
            "isTrashed": True,
        },
    ]
    calls, _folders, _files, uploads = install_sync_client(
        monkeypatch, tmp_path, files=remote
    )

    assert cli_module.main(["sync", str(local), "/Finance"]) == 0

    output = capsys.readouterr().out
    assert "upload /Finance/new.txt" in output
    assert "skip /Finance/same.txt (same)" in output
    assert "changed /Finance/changed.txt (skipped; use --replace)" in output
    assert "ambiguous /Finance/duplicate.txt (2 remote files with this name)" in output
    assert [upload["name"] for upload in uploads] == ["new.txt", "trashed.txt"]
    assert "Summary: mkdir=0, upload=2, replace=0, skip=1, changed=1, ambiguous=1, failed=0" in output
    assert not any(call[0] == "POST" and call[1].endswith("/trash") for call in calls)


def test_sync_creates_nested_folders_and_uploads_into_them(
    monkeypatch, tmp_path, capsys
):
    local = tmp_path / "local"
    write_file(local, "sub/nested/file.txt", b"content")
    calls, folders, _files, uploads = install_sync_client(monkeypatch, tmp_path)

    assert cli_module.main(["sync", str(local), "/Finance"]) == 0

    posts = [call for call in calls if call[0] == "POST" and call[1] == "/api/v1/folders"]
    assert [call[2]["name"] for call in posts] == ["sub", "nested"]
    assert posts[0][2] == {
        "name": "sub",
        "parent_id": FINANCE_ID,
        "owner_id": OWNER_ID,
    }
    nested_folder = next(folder for folder in folders if folder["name"] == "nested")
    assert posts[1][2]["parent_id"] == "folder-1"
    assert uploads == [{"name": "file.txt", "folder_id": nested_folder["id"]}]
    assert "mkdir /Finance/sub" in capsys.readouterr().out
    assert len(folders) == 3


def test_sync_dry_run_sends_no_mutating_requests_and_json_has_expected_shape(
    monkeypatch, tmp_path, capsys
):
    local = tmp_path / "local"
    write_file(local, "sub/new.txt", b"new")
    calls, _folders, _files, _uploads = install_sync_client(monkeypatch, tmp_path)

    assert cli_module.main(["sync", str(local), "/Finance", "--dry-run", "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert set(result) == {"actions", "summary"}
    assert [(action["action"], action["status"]) for action in result["actions"]] == [
        ("mkdir", "planned"),
        ("upload", "planned"),
    ]
    assert result["summary"]["mkdir"] == 1
    assert result["summary"]["upload"] == 1
    assert result["summary"]["failed"] == 0
    assert all(
        method not in {"POST", "PUT", "PATCH", "DELETE"}
        for method, _path, _payload in calls
    )


def test_sync_replace_uploads_before_trashing_old_file(monkeypatch, tmp_path, capsys):
    local = tmp_path / "local"
    write_file(local, "replace.txt", b"new-content")
    remote = [
        {
            "id": "old-file",
            "name": "replace.txt",
            "folderId": FINANCE_ID,
            "sizeBytes": 3,
            "isTrashed": False,
        }
    ]
    calls, _folders, files, _uploads = install_sync_client(
        monkeypatch, tmp_path, files=remote
    )

    assert cli_module.main(["sync", str(local), "/Finance", "--replace"]) == 0

    mutations = [(method, path) for method, path, _payload in calls if method == "POST"]
    assert mutations == [
        ("POST", "/api/v1/files/upload"),
        ("POST", "/api/v1/files/old-file/trash"),
    ]
    assert files[0]["isTrashed"] is True
    captured = capsys.readouterr()
    assert captured.out.startswith("replace /Finance/replace.txt\n")
    assert captured.err.count("Warning:") == 1


def test_sync_replace_does_not_trash_if_upload_fails(monkeypatch, tmp_path, capsys):
    local = tmp_path / "local"
    write_file(local, "replace.txt", b"new-content")
    remote = [
        {
            "id": "old-file",
            "name": "replace.txt",
            "folderId": FINANCE_ID,
            "sizeBytes": 3,
            "isTrashed": False,
        }
    ]
    calls, _folders, files, _uploads = install_sync_client(
        monkeypatch, tmp_path, files=remote, fail_upload=True
    )

    assert cli_module.main(["sync", str(local), "/Finance", "--replace"]) == 1

    output = capsys.readouterr().out
    assert "replace /Finance/replace.txt (upload failed: HTTP 500: upload failed)" in output
    assert "failed=1" in output
    assert not any(path.endswith("/trash") for _method, path, _payload in calls)
    assert files[0]["isTrashed"] is False


def test_sync_reports_trash_failure_after_upload(monkeypatch, tmp_path, capsys):
    local = tmp_path / "local"
    write_file(local, "replace.txt", b"new-content")
    remote = [
        {
            "id": "old-file",
            "name": "replace.txt",
            "folderId": FINANCE_ID,
            "sizeBytes": 3,
            "isTrashed": False,
        }
    ]
    calls, _folders, files, uploads = install_sync_client(
        monkeypatch, tmp_path, files=remote, fail_trash=True
    )

    assert cli_module.main(["sync", str(local), "/Finance", "--replace"]) == 1

    captured = capsys.readouterr()
    assert "replace /Finance/replace.txt (trash failed: HTTP 500: trash failed)" in captured.out
    assert "failed=1" in captured.out
    assert [upload["name"] for upload in uploads] == ["replace.txt"]
    assert files[0]["isTrashed"] is False
    assert any(path.endswith("/trash") for _method, path, _payload in calls)
    assert "Warning:" not in captured.err


def test_sync_skips_dotfiles_and_symlinks(monkeypatch, tmp_path):
    local = tmp_path / "local"
    normal = write_file(local, "normal.txt", b"content")
    write_file(local, ".hidden", b"secret")
    write_file(local, ".hidden-dir/nested.txt", b"secret")
    (local / "linked.txt").symlink_to(normal)
    _calls, _folders, _files, uploads = install_sync_client(monkeypatch, tmp_path)

    assert cli_module.main(["sync", str(local), "/Finance"]) == 0

    assert uploads == [{"name": "normal.txt", "folder_id": FINANCE_ID}]


def test_sync_requires_existing_remote_path(monkeypatch, tmp_path, capsys):
    local = tmp_path / "local"
    local.mkdir()
    calls, _folders, _files, _uploads = install_sync_client(monkeypatch, tmp_path)

    assert cli_module.main(["sync", str(local), "/Missing/Remote"]) == 1

    error = capsys.readouterr().err
    assert "Remote path not found: /Missing/Remote" in error
    assert "otter mkdir -p /Missing/Remote" in error
    assert not any(method in {"POST", "PUT", "PATCH", "DELETE"} for method, *_ in calls)
