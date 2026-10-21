from __future__ import annotations

import fnmatch
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


class PathResolutionError(ValueError):
    pass


class AmbiguousPathError(PathResolutionError):
    pass


class NotAFileError(PathResolutionError):
    pass


def _id(item: dict[str, Any]) -> str:
    return str(item.get("id", ""))


def _folder_parent(folder: dict[str, Any]) -> str | None:
    parent = folder.get("parentId")
    return str(parent) if parent else None


def _file_parent(file: dict[str, Any]) -> str | None:
    parent = file.get("folderId")
    return str(parent) if parent else None


def _matches_by_name(
    entries: list[dict[str, Any]], name: str, parent_id: str | None, is_folder: bool
) -> list[dict[str, Any]]:
    result = []
    for entry in entries:
        entry_parent = _folder_parent(entry) if is_folder else _file_parent(entry)
        if entry.get("name") == name and entry_parent == parent_id:
            result.append(entry)
    return result


def _unique_match(
    candidates: list[dict[str, Any]], name: str, kind: str
) -> dict[str, Any] | None:
    if len(candidates) > 1:
        ids = ", ".join(_id(item) for item in candidates)
        raise AmbiguousPathError(f"Ambiguous {kind} name {name!r}; matching IDs: {ids}")
    return candidates[0] if candidates else None


def _is_uuid(value: str) -> bool:
    try:
        canonical = str(uuid.UUID(value))
        return bool(canonical)
    except (ValueError, AttributeError):
        return False


def resolve_folder(path: str | None, folders: list[dict[str, Any]]) -> str | None:
    raw = (path or "/").strip()
    if raw in ("", "/"):
        return None
    folder_by_id = {_id(folder): folder for folder in folders}
    normalized = raw.strip("/")
    if _is_uuid(normalized):
        normalized = str(uuid.UUID(normalized))
        if normalized in folder_by_id:
            return normalized
        raise PathResolutionError(f"Folder not found: {path}")

    parent_id: str | None = None
    for segment in normalized.split("/"):
        if not segment:
            continue
        if _is_uuid(segment):
            folder_id = str(uuid.UUID(segment))
            if folder_id in folder_by_id:
                folder = folder_by_id[folder_id]
                if _folder_parent(folder) != parent_id:
                    raise PathResolutionError(f"Folder not found: {path}")
                parent_id = folder_id
                continue
        candidates = _matches_by_name(folders, segment, parent_id, True)
        folder = _unique_match(candidates, segment, "folder")
        if not folder:
            raise PathResolutionError(f"Folder not found: {path}")
        parent_id = _id(folder)
    return parent_id


def resolve_file(
    path: str,
    folders: list[dict[str, Any]],
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    raw = path.strip()
    if _is_uuid(raw):
        raw = str(uuid.UUID(raw))
        matches = [item for item in files if _id(item) == raw]
        if matches:
            return matches[0]
        if any(_id(folder) == raw for folder in folders):
            raise NotAFileError(f"{path} is a folder; this command only accepts files")
        raise PathResolutionError(f"File not found: {path}")

    segments = [segment for segment in raw.strip("/").split("/") if segment]
    if not segments:
        raise NotAFileError("The root path is a folder, not a file")
    parent_path = "/" + "/".join(segments[:-1]) if len(segments) > 1 else "/"
    parent_id = resolve_folder(parent_path, folders)
    candidates = _matches_by_name(files, segments[-1], parent_id, False)
    match = _unique_match(candidates, segments[-1], "file")
    if match:
        return match
    folder_candidates = _matches_by_name(folders, segments[-1], parent_id, True)
    folder = _unique_match(folder_candidates, segments[-1], "folder")
    if folder:
        raise NotAFileError(f"{path} is a folder; this command only accepts files")
    raise PathResolutionError(f"File not found: {path}")


def folder_path(folder_id: str | None, folders: list[dict[str, Any]]) -> str:
    if not folder_id:
        return "/"
    by_id = {_id(folder): folder for folder in folders}
    parts: list[str] = []
    current = folder_id
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        folder = by_id.get(current)
        if not folder:
            break
        parts.append(str(folder.get("name", "")))
        current = _folder_parent(folder)
    return "/" + "/".join(reversed([part for part in parts if part]))


def file_path(file: dict[str, Any], folders: list[dict[str, Any]]) -> str:
    parent = folder_path(_file_parent(file), folders).rstrip("/")
    return f"{parent}/{file.get('name', '')}"


def descendant_folder_ids(
    folder_id: str | None, folders: list[dict[str, Any]]
) -> set[str | None]:
    descendants: set[str | None] = {folder_id}
    changed = True
    while changed:
        changed = False
        for folder in folders:
            parent_id = _folder_parent(folder)
            if parent_id in descendants and _id(folder) not in descendants:
                descendants.add(_id(folder))
                changed = True
    return descendants


def folder_children(
    folder_id: str | None, folders: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return sorted(
        (folder for folder in folders if _folder_parent(folder) == folder_id),
        key=lambda folder: str(folder.get("name", "")).casefold(),
    )


def direct_files(
    folder_id: str | None, files: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        file
        for file in files
        if _file_parent(file) == folder_id and not file.get("isTrashed", False)
    ]


def du_rows(
    folder_id: str | None,
    folders: list[dict[str, Any]],
    files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    children_by_parent: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    files_by_parent: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    for folder in folders:
        children_by_parent[_folder_parent(folder)].append(folder)
    for file in files:
        if not file.get("isTrashed", False):
            files_by_parent[_file_parent(file)].append(file)
    totals: dict[str | None, tuple[int, int]] = {}

    def roll_up(current_id: str | None) -> tuple[int, int]:
        byte_count = sum(
            int(file.get("sizeBytes", file.get("size", 0)) or 0)
            for file in files_by_parent[current_id]
        )
        file_count = len(files_by_parent[current_id])
        for child in children_by_parent[current_id]:
            child_bytes, child_count = roll_up(_id(child))
            byte_count += child_bytes
            file_count += child_count
        totals[current_id] = byte_count, file_count
        return byte_count, file_count

    roll_up(folder_id)
    rows: list[dict[str, Any]] = []
    for child in children_by_parent[folder_id]:
        byte_count, file_count = totals[_id(child)]
        rows.append(
            {
                "name": f"{child.get('name', '')}/",
                "path": folder_path(_id(child), folders),
                "bytes": byte_count,
                "fileCount": file_count,
            }
        )
    rows.sort(key=lambda row: (-row["bytes"], row["name"].casefold()))
    own_files = files_by_parent[folder_id]
    own_bytes = sum(
        int(file.get("sizeBytes", file.get("size", 0)) or 0) for file in own_files
    )
    rows.append(
        {
            "name": f"Files directly in {folder_path(folder_id, folders)}",
            "path": folder_path(folder_id, folders),
            "bytes": own_bytes,
            "fileCount": len(own_files),
        }
    )
    total_bytes, total_count = totals[folder_id]
    rows.append(
        {
            "name": "Total",
            "path": folder_path(folder_id, folders),
            "bytes": total_bytes,
            "fileCount": total_count,
        }
    )
    return rows


def _parse_updated_at(file: dict[str, Any]) -> datetime | None:
    value = file.get("updatedAt")
    if not value:
        return None
    try:
        value = str(value)
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def find_files(
    folder_id: str | None,
    folders: list[dict[str, Any]],
    files: list[dict[str, Any]],
    *,
    name: str | None = None,
    larger_than: int | None = None,
    smaller_than: int | None = None,
    older_than_seconds: int | None = None,
    newer_than_seconds: int | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    allowed_folders = descendant_folder_ids(folder_id, folders)
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    old_cutoff = (
        current_time.timestamp() - older_than_seconds
        if older_than_seconds is not None
        else None
    )
    new_cutoff = (
        current_time.timestamp() - newer_than_seconds
        if newer_than_seconds is not None
        else None
    )
    matches: list[dict[str, Any]] = []
    for file in files:
        if file.get("isTrashed", False) or _file_parent(file) not in allowed_folders:
            continue
        file_name = str(file.get("name", ""))
        size = int(file.get("sizeBytes", file.get("size", 0)) or 0)
        modified = _parse_updated_at(file)
        if name and not fnmatch.fnmatchcase(file_name, name):
            continue
        if larger_than is not None and size <= larger_than:
            continue
        if smaller_than is not None and size >= smaller_than:
            continue
        if old_cutoff is not None and (
            modified is None or modified.timestamp() >= old_cutoff
        ):
            continue
        if new_cutoff is not None and (
            modified is None or modified.timestamp() <= new_cutoff
        ):
            continue
        matches.append(file)
    return sorted(matches, key=lambda file: file_path(file, folders).casefold())


def tree_lines(
    folder_id: str | None,
    folders: list[dict[str, Any]],
    files: list[dict[str, Any]],
    *,
    include_files: bool = False,
    max_depth: int | None = None,
) -> list[str]:
    if folder_id:
        root = next((folder for folder in folders if _id(folder) == folder_id), None)
        label = f"{root.get('name', '')}/" if root else folder_path(folder_id, folders)
    else:
        label = "."
    lines = [label]

    def walk(parent_id: str | None, prefix: str, level: int) -> None:
        entries: list[tuple[str, dict[str, Any], bool]] = [
            (str(folder.get("name", "")) + "/", folder, True)
            for folder in folder_children(parent_id, folders)
        ]
        if include_files:
            entries.extend(
                (str(file.get("name", "")), file, False)
                for file in direct_files(parent_id, files)
            )
            entries.sort(key=lambda entry: (not entry[2], entry[0].casefold()))
        visible: list[tuple[str, dict[str, Any], bool]] = []
        for name, entry, is_folder in entries:
            if is_folder and max_depth is not None and level >= max_depth:
                continue
            visible.append((name, entry, is_folder))
        for index, (name, entry, is_folder) in enumerate(visible):
            last = index == len(visible) - 1
            lines.append(prefix + ("└── " if last else "├── ") + name)
            if is_folder:
                walk(_id(entry), prefix + ("    " if last else "│   "), level + 1)

    walk(folder_id, "", 0)
    return lines
