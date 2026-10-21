import json

import httpx

from otter_cli import cli as cli_module
from otter_cli.client import OtterClient


def mock_drive_transport():
    def handler(request):
        if request.url.path == "/api/v1/folders":
            parent = request.url.params.get("parent_id")
            folders = (
                []
                if parent
                else [
                    {
                        "id": "finance",
                        "name": "Finance",
                        "parent_id": None,
                        "owner_id": "owner",
                        "updated_at": "2024-12-01T00:00:00Z",
                    }
                ]
            )
            return httpx.Response(200, json={"folders": folders})
        if request.url.path == "/api/v1/files":
            files = [
                {
                    "id": "root",
                    "name": "readme.txt",
                    "folder_id": None,
                    "size_bytes": 512,
                    "is_trashed": False,
                    "updated_at": "2024-12-30T00:00:00Z",
                },
                {
                    "id": "finance-file",
                    "name": "budget.xlsx",
                    "folder_id": "finance",
                    "size_bytes": 1024,
                    "is_trashed": False,
                    "updated_at": "2024-12-31T00:00:00Z",
                },
            ]
            folder_id = request.url.params.get("folder_id")
            if folder_id:
                files = [file for file in files if file["folder_id"] == folder_id]
            return httpx.Response(
                200,
                json={"files": files, "total": len(files), "page": 1, "page_size": 1000},
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def install_mock_client(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("OTTER_TOKEN", "mock-token")
    transport = mock_drive_transport()
    monkeypatch.setattr(
        cli_module,
        "OtterClient",
        lambda api_url=None: OtterClient(api_url=api_url, transport=transport),
    )


def test_main_ls_json_smoke(monkeypatch, tmp_path, capsys):
    install_mock_client(monkeypatch, tmp_path)

    assert cli_module.main(["ls", "/", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert [folder["name"] for folder in output["folders"]] == ["Finance"]
    assert [file["name"] for file in output["files"]] == ["readme.txt"]


def test_main_du_smoke(monkeypatch, tmp_path, capsys):
    install_mock_client(monkeypatch, tmp_path)

    assert cli_module.main(["du", "/"]) == 0

    output = capsys.readouterr().out
    assert "Finance/" in output
    assert "Files directly in /" in output
    assert "1,536" not in output
    assert "1536" in output
    assert "Total" in output


def test_rm_refuses_folders_with_status_one(monkeypatch, tmp_path, capsys):
    install_mock_client(monkeypatch, tmp_path)

    assert cli_module.main(["rm", "/Finance"]) == 1
    assert "only accepts files" in capsys.readouterr().err


def test_find_invalid_size_exits_with_usage_error(capsys):
    try:
        cli_module.main(["find", "/", "--larger-than", "not-a-size"])
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("invalid size should exit with status 2")
    assert "Invalid size" in capsys.readouterr().err
