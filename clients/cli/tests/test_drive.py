from datetime import datetime, timezone

import pytest

from otter_cli.drive import (
    AmbiguousPathError,
    PathResolutionError,
    du_rows,
    file_path,
    find_files,
    resolve_file,
    resolve_folder,
)

FINANCE = "10000000-0000-0000-0000-000000000001"
REPORTS = "10000000-0000-0000-0000-000000000002"
DUPLICATE_A = "10000000-0000-0000-0000-000000000003"
DUPLICATE_B = "10000000-0000-0000-0000-000000000004"
NESTED_FILE = "20000000-0000-0000-0000-000000000001"


@pytest.fixture
def folders():
    return [
        {"id": FINANCE, "name": "Finance", "parentId": None},
        {"id": REPORTS, "name": "Reports", "parentId": FINANCE},
        {"id": DUPLICATE_A, "name": "Dup", "parentId": None},
        {"id": DUPLICATE_B, "name": "Dup", "parentId": None},
    ]


@pytest.fixture
def files():
    return [
        {
            "id": "root-file",
            "name": "readme.txt",
            "folderId": None,
            "sizeBytes": 10,
            "updatedAt": "2024-12-31T00:00:00Z",
        },
        {
            "id": NESTED_FILE,
            "name": "q1.xlsx",
            "folderId": REPORTS,
            "sizeBytes": 100,
            "updatedAt": "2024-11-01T00:00:00Z",
        },
        {
            "id": "duplicate-file-a",
            "name": "same.txt",
            "folderId": REPORTS,
            "sizeBytes": 2,
        },
        {
            "id": "duplicate-file-b",
            "name": "same.txt",
            "folderId": REPORTS,
            "sizeBytes": 3,
        },
    ]


def test_resolve_nested_folder_and_root_file(folders, files):
    assert resolve_folder("/Finance/Reports", folders) == REPORTS
    assert resolve_folder(FINANCE, folders) == FINANCE
    root_file = resolve_file("/readme.txt", folders, files)
    assert root_file["id"] == "root-file"
    assert file_path(files[1], folders) == "/Finance/Reports/q1.xlsx"


def test_resolve_file_uuid_passthrough(folders, files):
    assert resolve_file(NESTED_FILE, folders, files) is files[1]


def test_ambiguous_folder_and_file_names_report_ids(folders, files):
    with pytest.raises(AmbiguousPathError, match=DUPLICATE_A):
        resolve_folder("/Dup", folders)
    with pytest.raises(AmbiguousPathError, match="duplicate-file-a"):
        resolve_file("/Finance/Reports/same.txt", folders, files)


def test_not_found_path_is_clear(folders, files):
    with pytest.raises(PathResolutionError, match="Folder not found"):
        resolve_folder("/Unknown", folders)
    with pytest.raises(PathResolutionError, match="File not found"):
        resolve_file("/Finance/missing.txt", folders, files)


def test_du_rolls_up_nested_and_direct_files():
    folders = [
        {"id": "a", "name": "A", "parentId": None},
        {"id": "nested", "name": "Nested", "parentId": "a"},
        {"id": "b", "name": "B", "parentId": None},
    ]
    files = [
        {"id": "root", "name": "root.bin", "folderId": None, "sizeBytes": 5},
        {"id": "a1", "name": "a.bin", "folderId": "a", "sizeBytes": 4},
        {"id": "a2", "name": "a2.bin", "folderId": "nested", "sizeBytes": 7},
        {"id": "b1", "name": "b.bin", "folderId": "b", "sizeBytes": 3},
    ]
    rows = du_rows(None, folders, files)
    assert rows[0]["name"] == "A/"
    assert rows[0]["bytes"] == 11
    assert rows[0]["fileCount"] == 2
    direct = next(row for row in rows if row["name"].startswith("Files directly"))
    total = rows[-1]
    assert direct["bytes"] == 5
    assert direct["fileCount"] == 1
    assert total["bytes"] == 19
    assert total["fileCount"] == 4


def test_find_each_filter_and_combination():
    folders = [{"id": "f", "name": "Finance", "parentId": None}]
    files = [
        {
            "id": "old-pdf",
            "name": "old.pdf",
            "folderId": "f",
            "sizeBytes": 2048,
            "updatedAt": "2024-11-01T00:00:00Z",
        },
        {
            "id": "new-txt",
            "name": "new.txt",
            "folderId": "f",
            "sizeBytes": 512,
            "updatedAt": "2024-12-30T00:00:00Z",
        },
        {
            "id": "mid-pptx",
            "name": "mid.pptx",
            "folderId": "f",
            "sizeBytes": 1024,
            "updatedAt": "2024-12-01T00:00:00Z",
        },
        {
            "id": "trashed-pdf",
            "name": "gone.pdf",
            "folderId": "f",
            "sizeBytes": 99999,
            "updatedAt": "2024-01-01T00:00:00Z",
            "isTrashed": True,
        },
    ]
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)

    def ids(**filters):
        return {
            file["id"]
            for file in find_files("f", folders, files, now=now, **filters)
        }

    assert ids(name="*.pdf") == {"old-pdf"}
    assert ids(larger_than=1000) == {"old-pdf", "mid-pptx"}
    assert ids(smaller_than=600) == {"new-txt"}
    assert ids(older_than_seconds=30 * 86400) == {"old-pdf", "mid-pptx"}
    assert ids(newer_than_seconds=7 * 86400) == {"new-txt"}
    assert ids(
        name="*.pptx",
        larger_than=1000,
        older_than_seconds=30 * 86400,
        smaller_than=2000,
    ) == {"mid-pptx"}
    assert "trashed-pdf" not in ids()
