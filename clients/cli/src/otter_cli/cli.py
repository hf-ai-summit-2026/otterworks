from __future__ import annotations

import argparse
import getpass
import json
import mimetypes
import os
import shlex
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from .client import ApiError, OtterClient, SessionExpiredError
from .drive import (
    AmbiguousPathError,
    PathResolutionError,
    descendant_folder_ids,
    du_rows,
    file_path,
    find_files,
    folder_children,
    folder_path,
    resolve_file,
    resolve_folder,
    tree_lines,
)
from .units import format_size, parse_duration, parse_size


def _json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _format_time(value: Any) -> str:
    if not value:
        return "-"
    try:
        value = str(value)
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value)


def _print_table(headers: list[str], rows: list[list[Any]]) -> None:
    if not rows:
        return
    string_rows = [[str(value) for value in row] for row in rows]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in string_rows))
        for index in range(len(headers))
    ]
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in string_rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def _size(file: dict[str, Any]) -> int:
    return int(file.get("sizeBytes", file.get("size", 0)) or 0)


def _entries_for_folder(
    client: OtterClient, path: str
) -> tuple[str | None, list[dict[str, Any]], list[dict[str, Any]]]:
    folders = client.list_folder_tree()
    folder_id = resolve_folder(path, folders)
    files = client.list_all_files(folder_id=folder_id)
    if folder_id is None:
        files = [file for file in files if not file.get("folderId")]
    return folder_id, folders, files


def _login(args: argparse.Namespace, client: OtterClient) -> int:
    email = args.email or os.environ.get("OTTER_EMAIL") or input("Email: ")
    password = os.environ.get("OTTER_PASSWORD") or getpass.getpass("Password: ")
    response = client.login(email, password)
    user = response.get("user") or {}
    print(f"Logged in as {user.get('email') or email}")
    return 0


def _logout(_args: argparse.Namespace, client: OtterClient) -> int:
    client.logout()
    print("Logged out")
    return 0


def _whoami(_args: argparse.Namespace, client: OtterClient) -> int:
    profile = client.get("/auth/profile")
    _print_table(
        ["FIELD", "VALUE"],
        [
            ["Email", profile.get("email", "")],
            ["Name", profile.get("displayName", "")],
            ["ID", profile.get("id", "")],
        ],
    )
    return 0


def _ls(args: argparse.Namespace, client: OtterClient) -> int:
    folder_id, folders, files = _entries_for_folder(client, args.path)
    child_folders = folder_children(folder_id, folders)
    if args.json:
        _json({"folders": child_folders, "files": files})
        return 0
    if args.long:
        rows = [
            ["-", _format_time(folder.get("updatedAt")), f"{folder['name']}/"]
            for folder in child_folders
        ]
        rows.extend(
            [
                format_size(_size(file)),
                _format_time(file.get("updatedAt")),
                str(file.get("name", "")),
            ]
            for file in files
        )
        _print_table(["SIZE", "MODIFIED", "NAME"], rows)
    else:
        for folder in child_folders:
            print(f"{folder.get('name', '')}/")
        for file in files:
            print(file.get("name", ""))
    return 0


def _tree(args: argparse.Namespace, client: OtterClient) -> int:
    folders = client.list_folder_tree()
    files = client.list_all_files()
    folder_id = resolve_folder(args.path, folders)
    for line in tree_lines(
        folder_id,
        folders,
        files,
        include_files=args.files,
        max_depth=args.depth,
    ):
        print(line)
    return 0


def _du(args: argparse.Namespace, client: OtterClient) -> int:
    folders = client.list_folder_tree()
    files = client.list_all_files()
    folder_id = resolve_folder(args.path, folders)
    rows = du_rows(folder_id, folders, files)
    if args.json:
        _json(rows)
        return 0
    _print_table(
        ["BYTES", "SIZE", "FILES", "NAME"],
        [
            [
                row["bytes"],
                format_size(row["bytes"]),
                row["fileCount"],
                row["name"],
            ]
            for row in rows
        ],
    )
    return 0


def _find(args: argparse.Namespace, client: OtterClient) -> int:
    folders = client.list_folder_tree()
    files = client.list_all_files()
    folder_id = resolve_folder(args.path, folders)
    matches = find_files(
        folder_id,
        folders,
        files,
        name=args.name,
        larger_than=parse_size(args.larger_than) if args.larger_than else None,
        smaller_than=parse_size(args.smaller_than) if args.smaller_than else None,
        older_than_seconds=(
            parse_duration(args.older_than) if args.older_than else None
        ),
        newer_than_seconds=(
            parse_duration(args.newer_than) if args.newer_than else None
        ),
    )
    results = [
        {
            "id": file.get("id"),
            "name": file.get("name"),
            "path": file_path(file, folders),
            "sizeBytes": _size(file),
            "updatedAt": file.get("updatedAt"),
        }
        for file in matches
    ]
    if args.json:
        _json(results)
    elif args.long:
        _print_table(
            ["SIZE", "MODIFIED", "PATH"],
            [
                [format_size(row["sizeBytes"]), _format_time(row["updatedAt"]), row["path"]]
                for row in results
            ],
        )
    else:
        for row in results:
            print(row["path"])
    return 0


def _find_or_create_folder(
    client: OtterClient,
    folders: list[dict[str, Any]],
    name: str,
    parent_id: str | None,
    owner_id: str,
) -> str:
    candidates = [
        folder
        for folder in folders
        if folder.get("name") == name
        and str(folder.get("parentId") or "") == str(parent_id or "")
    ]
    if len(candidates) > 1:
        raise AmbiguousPathError(
            f"Ambiguous folder name {name!r}; matching IDs: "
            + ", ".join(str(folder.get("id")) for folder in candidates)
        )
    if candidates:
        return str(candidates[0]["id"])
    created = client.post(
        "/folders",
        json={"name": name, "parent_id": parent_id, "owner_id": owner_id},
    )
    folders.append(created)
    return str(created["id"])


def _owner_id(client: OtterClient) -> str:
    profile = client.get("/auth/profile")
    owner_id = str(profile.get("id", ""))
    if not owner_id:
        raise ValueError("Unable to determine account ID for folder creation")
    return owner_id


def _matching_folders(
    name: str, parent_id: str | None, folders: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        folder
        for folder in folders
        if folder.get("name") == name
        and str(folder.get("parentId") or "") == str(parent_id or "")
    ]


def _matching_files(
    name: str, parent_id: str | None, files: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        file
        for file in files
        if not file.get("isTrashed", False)
        and file.get("name") == name
        and str(file.get("folderId") or "") == str(parent_id or "")
    ]


def _mkdir(args: argparse.Namespace, client: OtterClient) -> int:
    folders = client.list_folder_tree()
    files = client.list_all_files()
    owner_id: str | None = None
    for path in args.paths:
        parts = [part for part in path.strip("/").split("/") if part]
        if not parts:
            if args.parents:
                print("/")
                continue
            raise ValueError("Already exists: /")

        parent_id: str | None = None
        for index, name in enumerate(parts):
            candidates = _matching_folders(name, parent_id, folders)
            if len(candidates) > 1:
                raise AmbiguousPathError(
                    f"Ambiguous folder name {name!r}; matching IDs: "
                    + ", ".join(str(folder.get("id")) for folder in candidates)
                )
            if candidates:
                if index == len(parts) - 1 and not args.parents:
                    raise ValueError(f"Already exists: {path}")
                parent_id = str(candidates[0]["id"])
                continue
            if _matching_files(name, parent_id, files):
                if index == len(parts) - 1:
                    raise ValueError(f"Already exists: {path}")
                raise PathResolutionError(
                    f"Parent path is a file: /{'/'.join(parts[: index + 1])}"
                )
            if index != len(parts) - 1 and not args.parents:
                raise PathResolutionError(
                    f"Parent folder not found: /{'/'.join(parts[: index + 1])}"
                )
            if owner_id is None:
                owner_id = _owner_id(client)
            parent_id = _find_or_create_folder(
                client, folders, name, parent_id, owner_id
            )
        print(folder_path(parent_id, folders))
    return 0


def _resolve_item(
    path: str, folders: list[dict[str, Any]], files: list[dict[str, Any]]
) -> tuple[str, dict[str, Any]]:
    try:
        file = resolve_file(path, folders, files)
    except AmbiguousPathError:
        raise
    except PathResolutionError as error:
        file_error = error
        file = None
    try:
        folder_id = resolve_folder(path, folders)
    except AmbiguousPathError:
        raise
    except PathResolutionError:
        folder_id = None
    folder = next(
        (item for item in folders if str(item.get("id")) == folder_id), None
    )
    if file and folder:
        raise AmbiguousPathError(
            f"Ambiguous path {path!r}; matching IDs: "
            f"{_item_id('file', file)}, {_item_id('folder', folder)}"
        )
    if file:
        return "file", file
    if folder:
        return "folder", folder
    if path.strip() in ("", "/"):
        raise ValueError("The root folder cannot be moved")
    raise file_error


def _item_id(kind: str, item: dict[str, Any]) -> str:
    return str(item.get("id", ""))


def _item_name(item: dict[str, Any]) -> str:
    return str(item.get("name", ""))


def _item_parent(kind: str, item: dict[str, Any]) -> str | None:
    parent = item.get("folderId") if kind == "file" else item.get("parentId")
    return str(parent) if parent else None


def _item_path(
    kind: str, item: dict[str, Any], folders: list[dict[str, Any]]
) -> str:
    return (
        file_path(item, folders)
        if kind == "file"
        else folder_path(_item_id(kind, item), folders)
    )


def _name_collision(
    name: str,
    parent_id: str | None,
    folders: list[dict[str, Any]],
    files: list[dict[str, Any]],
    excluded: set[tuple[str, str]],
) -> bool:
    return any(
        ("folder", str(folder.get("id"))) not in excluded
        and folder.get("name") == name
        and _item_parent("folder", folder) == parent_id
        for folder in folders
    ) or any(
        ("file", str(file.get("id"))) not in excluded
        and file.get("name") == name
        and _item_parent("file", file) == parent_id
        for file in files
    )


def _destination_for_move(
    path: str,
    folders: list[dict[str, Any]],
    source_count: int,
) -> tuple[str | None, str | None]:
    try:
        return resolve_folder(path, folders), None
    except AmbiguousPathError:
        raise
    except PathResolutionError:
        if source_count != 1:
            raise ValueError("Multiple sources require an existing destination folder")
        parts = [part for part in path.strip("/").split("/") if part]
        if not parts:
            raise ValueError(f"Invalid destination: {path}")
        name = parts[-1]
        parent_path = "/" + "/".join(parts[:-1]) if len(parts) > 1 else "/"
        return resolve_folder(parent_path, folders), name


def _mv(args: argparse.Namespace, client: OtterClient) -> int:
    folders = client.list_folder_tree()
    files = client.list_all_files()
    sources = [_resolve_item(path, folders, files) for path in args.sources]
    source_keys = {(kind, _item_id(kind, item)) for kind, item in sources}
    if len(source_keys) != len(sources):
        raise ValueError("A source may only be moved once")

    destination_id, rename_to = _destination_for_move(
        args.destination, folders, len(sources)
    )
    descendant_ids = {
        _item_id(kind, item): descendant_folder_ids(_item_id(kind, item), folders)
        for kind, item in sources
        if kind == "folder"
    }
    planned_names: set[str] = set()
    plans: list[tuple[str, dict[str, Any], str, str, str, str]] = []
    for kind, item in sources:
        item_id = _item_id(kind, item)
        current_parent = _item_parent(kind, item)
        target_name = rename_to or _item_name(item)
        if kind == "folder" and destination_id in descendant_ids[item_id]:
            raise ValueError("A folder cannot be moved into itself or its descendants")
        if kind == "folder" and destination_id is None and current_parent is not None:
            raise ValueError("Moving folders to / is not supported by the API")
        if _name_collision(
            target_name, destination_id, folders, files, source_keys
        ):
            raise ValueError(f"Destination already contains an item named {target_name!r}")
        if target_name in planned_names:
            raise ValueError(f"Destination already contains an item named {target_name!r}")
        planned_names.add(target_name)
        old_path = _item_path(kind, item, folders)
        parent_path = folder_path(destination_id, folders).rstrip("/")
        new_path = f"{parent_path}/{target_name}"
        plans.append((kind, item, target_name, old_path, new_path, item_id))

    for kind, item, target_name, old_path, new_path, item_id in plans:
        current_parent = _item_parent(kind, item)
        if kind == "file":
            if current_parent != destination_id:
                client.put(
                    f"/files/{item_id}/move",
                    json={"folder_id": destination_id},
                )
            if target_name != _item_name(item):
                client.patch(f"/files/{item_id}/rename", json={"name": target_name})
            item["folderId"] = destination_id
            item["name"] = target_name
        else:
            body: dict[str, Any] = {}
            if current_parent != destination_id:
                body["parent_id"] = destination_id
            if target_name != _item_name(item):
                body["name"] = target_name
            if body:
                updated = client.put(f"/folders/{item_id}", json=body) or {}
                if destination_id is None and current_parent is not None:
                    actual_parent = updated.get("parentId", current_parent)
                    if actual_parent != destination_id:
                        raise ValueError(
                            "Moving folders to / is not supported by the API"
                        )
            item["parentId"] = destination_id
            item["name"] = target_name
        print(f"{old_path} -> {new_path}")
    return 0


def _rename(args: argparse.Namespace, client: OtterClient) -> int:
    folders = client.list_folder_tree()
    files = client.list_all_files()
    kind, item = _resolve_item(args.path, folders, files)
    name = args.new_name
    if _name_collision(
        name,
        _item_parent(kind, item),
        folders,
        files,
        {(kind, _item_id(kind, item))},
    ):
        raise ValueError(f"An item named {name!r} already exists in this folder")
    old_path = _item_path(kind, item, folders)
    if name != _item_name(item):
        if kind == "file":
            client.patch(
                f"/files/{_item_id(kind, item)}/rename", json={"name": name}
            )
        else:
            client.put(f"/folders/{_item_id(kind, item)}", json={"name": name})
    parent_path = folder_path(_item_parent(kind, item), folders).rstrip("/")
    print(f"{old_path} -> {parent_path}/{name}")
    return 0


def _upload_file(
    client: OtterClient,
    local_path: Path,
    folder_id: str | None,
    folders: list[dict[str, Any]],
) -> str:
    content_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
    data = {"folder_id": folder_id} if folder_id else {}
    with local_path.open("rb") as stream:
        response = client.post(
            "/files/upload",
            data=data,
            files={"file": (local_path.name, stream, content_type)},
        )
    uploaded = response.get("file", response)
    return file_path(uploaded, folders)


def _upload(args: argparse.Namespace, client: OtterClient) -> int:
    folders = client.list_folder_tree()
    target_id = resolve_folder(args.to, folders)
    local_paths = [Path(value).expanduser() for value in args.local]
    for path in local_paths:
        if not path.exists():
            raise ValueError(f"Local path not found: {path}")
        if path.is_dir() and not args.recursive:
            raise ValueError(f"{path} is a directory; use -r to upload directories")

    owner_id = ""
    if any(path.is_dir() for path in local_paths):
        profile = client.get("/auth/profile")
        owner_id = str(profile.get("id", ""))
        if not owner_id:
            raise ValueError("Unable to determine account ID for folder creation")

    for local_path in local_paths:
        if not local_path.is_dir():
            print(_upload_file(client, local_path, target_id, folders))
            continue
        root_id = _find_or_create_folder(
            client, folders, local_path.name, target_id, owner_id
        )
        directories = sorted(
            (item for item in local_path.rglob("*") if item.is_dir()),
            key=lambda item: (len(item.relative_to(local_path).parts), item.as_posix()),
        )
        folder_ids: dict[Path, str] = {Path("."): root_id}
        for directory in directories:
            relative = directory.relative_to(local_path)
            parent_relative = relative.parent
            parent_id = folder_ids.get(parent_relative)
            if parent_id is None:
                parent_id = root_id
                for part in parent_relative.parts:
                    parent_id = _find_or_create_folder(
                        client, folders, part, parent_id, owner_id
                    )
            folder_ids[relative] = _find_or_create_folder(
                client, folders, directory.name, parent_id, owner_id
            )
        for item in sorted(local_path.rglob("*"), key=lambda entry: entry.as_posix()):
            if not item.is_file():
                continue
            relative_parent = item.relative_to(local_path).parent
            parent_id = folder_ids.get(relative_parent, root_id)
            print(_upload_file(client, item, parent_id, folders))
    return 0


def _sync_local_tree(local_root: Path) -> tuple[list[Path], list[Path]]:
    directories: list[Path] = []
    files: list[Path] = []

    def raise_walk_error(error: OSError) -> None:
        raise error

    for current, dirnames, filenames in os.walk(
        local_root, topdown=True, onerror=raise_walk_error, followlinks=False
    ):
        current_path = Path(current)
        relative = current_path.relative_to(local_root)
        if relative != Path("."):
            directories.append(relative)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not name.startswith(".") and not (current_path / name).is_symlink()
        )
        for name in sorted(filenames):
            path = current_path / name
            if name.startswith(".") or path.is_symlink() or not path.is_file():
                continue
            files.append(path)

    directories.sort(key=lambda path: (len(path.parts), path.as_posix()))
    files.sort(key=lambda path: path.relative_to(local_root).as_posix())
    return directories, files


def _sync_remote_path(root_path: str, relative: Path) -> str:
    suffix = relative.as_posix()
    if not suffix or suffix == ".":
        return root_path
    return f"{root_path.rstrip('/')}/{suffix}" if root_path != "/" else f"/{suffix}"


def _sync(args: argparse.Namespace, client: OtterClient) -> int:
    local_root = Path(args.local_dir).expanduser()
    if local_root.is_symlink() or not local_root.is_dir():
        raise ValueError(f"Local path is not a directory: {local_root}")

    folders = client.list_folder_tree()
    try:
        root_id = resolve_folder(args.remote_path, folders)
    except AmbiguousPathError:
        raise
    except PathResolutionError as error:
        raise ValueError(
            f"Remote path not found: {args.remote_path}; "
            f"create it with `otter mkdir -p {args.remote_path}`"
        ) from error
    root_path = folder_path(root_id, folders)
    files = client.list_all_files()
    try:
        directories, local_files = _sync_local_tree(local_root)
    except OSError as error:
        raise ValueError(f"Unable to read local directory: {error}") from error

    actions: list[dict[str, Any]] = []
    summary = {
        "mkdir": 0,
        "upload": 0,
        "replace": 0,
        "skip": 0,
        "changed": 0,
        "ambiguous": 0,
        "failed": 0,
    }

    def add_action(
        action: str,
        path: str,
        status: str,
        detail: str | None = None,
    ) -> None:
        record: dict[str, Any] = {"action": action, "path": path, "status": status}
        if detail:
            record["detail"] = detail
        actions.append(record)
        summary[action] += 1
        if status == "failed":
            summary["failed"] += 1

    folder_ids: dict[Path, tuple[str | None, bool]] = {Path("."): (root_id, True)}
    owner_id: str | None = None
    for relative in directories:
        parent_relative = relative.parent
        parent_id, parent_exists = folder_ids.get(parent_relative, (None, False))
        path = _sync_remote_path(root_path, relative)
        if not parent_exists:
            if args.dry_run:
                add_action("mkdir", path, "planned")
            else:
                add_action("mkdir", path, "failed", "parent folder was not created")
            folder_ids[relative] = (None, False)
            continue

        name = relative.name
        matches = _matching_folders(name, parent_id, folders)
        if len(matches) > 1:
            add_action(
                "mkdir",
                path,
                "failed",
                "ambiguous remote folder name",
            )
            folder_ids[relative] = (None, False)
            continue
        if matches:
            folder_ids[relative] = (str(matches[0]["id"]), True)
            continue
        if args.dry_run:
            add_action("mkdir", path, "planned")
            folder_ids[relative] = (None, False)
            continue

        try:
            if owner_id is None:
                owner_id = _owner_id(client)
            created_id = _find_or_create_folder(
                client, folders, name, parent_id, owner_id
            )
        except (ApiError, httpx.HTTPError, OSError, ValueError) as error:
            add_action("mkdir", path, "failed", str(error))
            folder_ids[relative] = (None, False)
            continue
        folder_ids[relative] = (created_id, True)
        add_action("mkdir", path, "created")

    warning_emitted = False
    for local_file in local_files:
        relative = local_file.relative_to(local_root)
        relative_parent = relative.parent
        folder_id, folder_exists = folder_ids.get(relative_parent, (root_id, True))
        remote_path = _sync_remote_path(root_path, relative)
        try:
            local_size = local_file.stat().st_size
        except OSError as error:
            add_action("upload", remote_path, "failed", str(error))
            continue
        if not folder_exists:
            if args.dry_run:
                add_action("upload", remote_path, "planned")
            else:
                add_action("upload", remote_path, "failed", "parent folder was not created")
            continue
        matches = _matching_files(local_file.name, folder_id, files)
        if len(matches) > 1:
            add_action(
                "ambiguous",
                remote_path,
                "skipped",
                f"{len(matches)} remote files with this name",
            )
            continue
        if matches and _size(matches[0]) == local_size:
            add_action("skip", remote_path, "same")
            continue
        if matches and not args.replace:
            add_action("changed", remote_path, "skipped", "skipped; use --replace")
            continue

        is_replace = bool(matches)
        action = "replace" if is_replace else "upload"
        if args.dry_run:
            add_action(action, remote_path, "planned")
            continue
        try:
            _upload_file(client, local_file, folder_id, folders)
        except (ApiError, httpx.HTTPError, OSError, ValueError) as error:
            detail = f"upload failed: {error}" if is_replace else str(error)
            add_action(action, remote_path, "failed", detail)
            continue
        if is_replace:
            try:
                client.post(f"/files/{matches[0]['id']}/trash")
            except (ApiError, httpx.HTTPError, OSError, ValueError) as error:
                add_action("replace", remote_path, "failed", f"trash failed: {error}")
                continue
            matches[0]["isTrashed"] = True
            if not warning_emitted:
                warning_emitted = True
            add_action("replace", remote_path, "replaced")
        else:
            add_action("upload", remote_path, "uploaded")

    if warning_emitted:
        print(
            "Warning: replacements get new file IDs; existing shares are not carried over.",
            file=sys.stderr,
        )
    if args.json:
        _json({"actions": actions, "summary": summary})
        return int(summary["failed"] > 0)

    for action in actions:
        detail = action.get("detail")
        if not detail and action["status"] == "planned":
            detail = "planned"
        elif not detail and action["action"] == "skip":
            detail = "same"
        suffix = f" ({detail})" if detail else ""
        print(f"{action['action']} {action['path']}{suffix}")
    print(
        "Summary: "
        + ", ".join(f"{name}={count}" for name, count in summary.items())
    )
    return int(summary["failed"] > 0)


def _download(args: argparse.Namespace, client: OtterClient) -> int:
    folders = client.list_folder_tree()
    files = client.list_all_files()
    selected = [
        _resolve_file_or_id(path, client, folders, files) for path in args.paths
    ]
    destination = Path(args.output).expanduser() if args.output else None
    if destination and len(selected) > 1 and destination.exists() and not destination.is_dir():
        raise ValueError("A destination directory is required for multiple downloads")
    if destination and len(selected) > 1:
        destination.mkdir(parents=True, exist_ok=True)
    for file in selected:
        name = str(file.get("name", "download"))
        if destination is None:
            output = Path(name)
        elif destination.is_dir() or len(selected) > 1:
            output = destination / name
        else:
            output = destination
        download = client.get(f"/files/{file['id']}/download")
        url = download.get("url")
        if not url:
            raise ValueError(f"Download URL missing for {name}")
        client.download_to(str(url), output)
        print(f"{_file_path_or_shared(file, folders, files)} -> {output}")
    return 0


def _rm(args: argparse.Namespace, client: OtterClient) -> int:
    folders = client.list_folder_tree()
    files = client.list_all_files()
    for path in args.paths:
        file = resolve_file(path, folders, files)
        client.post(f"/files/{file['id']}/trash")
        print(f"Moved to trash: {file_path(file, folders)}")
    return 0


def _trash(args: argparse.Namespace, client: OtterClient) -> int:
    files = client.list_all_files(endpoint="/files/trash")
    if args.json:
        _json(files)
    else:
        _print_table(
            ["ID", "SIZE", "MODIFIED", "NAME"],
            [
                [
                    file.get("id", ""),
                    format_size(_size(file)),
                    _format_time(file.get("updatedAt")),
                    file.get("name", ""),
                ]
                for file in files
            ],
        )
    return 0


def _restore(args: argparse.Namespace, client: OtterClient) -> int:
    folders = client.list_folder_tree()
    trashed = client.list_all_files(endpoint="/files/trash")
    for value in args.names:
        if "/" in value or not _looks_like_id(value):
            if "/" not in value:
                candidates = [file for file in trashed if file.get("name") == value]
                if len(candidates) > 1:
                    ids = ", ".join(str(file.get("id")) for file in candidates)
                    raise AmbiguousPathError(
                        f"Ambiguous file name {value!r}; matching IDs: {ids}"
                    )
                if not candidates:
                    raise ValueError(f"Trashed file not found: {value}")
                file = candidates[0]
            else:
                file = resolve_file(value, folders, trashed)
        else:
            file = resolve_file(value, folders, trashed)
        client.post(f"/files/{file['id']}/restore")
        print(f"Restored: {file_path(file, folders)}")
    return 0


def _looks_like_id(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def _search(args: argparse.Namespace, client: OtterClient) -> int:
    params = {"q": args.query}
    if args.type:
        params["type"] = args.type
    response = client.get("/search", params=params)
    results = response.get("results", [])
    if args.json:
        _json(response)
    else:
        _print_table(
            ["TYPE", "NAME", "UPDATED", "ID"],
            [
                [
                    result.get("type", ""),
                    result.get("title", result.get("name", result.get("id", ""))),
                    _format_time(result.get("updatedAt")),
                    result.get("id", ""),
                ]
                for result in results
            ],
        )
        print(f"{response.get('total', len(results))} result(s)")
    return 0


def _lookup_user(client: OtterClient, email: str) -> dict[str, Any]:
    try:
        user = client.get("/auth/users/lookup", params={"email": email})
    except ApiError as error:
        if error.status_code == 404 or (
            error.status_code == 400 and "user not found" in error.message.lower()
        ):
            raise ValueError(f"No OtterWorks user with email {email}") from error
        raise
    if not isinstance(user, dict) or not user.get("id"):
        raise ValueError(f"No OtterWorks user with email {email}")
    return user


def _user_email(
    client: OtterClient, user_id: str, cache: dict[str, str | None]
) -> str:
    if user_id not in cache:
        try:
            user = client.get(f"/auth/users/by-id/{user_id}")
        except (ApiError, httpx.HTTPError):
            cache[user_id] = None
        else:
            email = user.get("email") if isinstance(user, dict) else None
            cache[user_id] = str(email) if email else None
    return cache[user_id] or user_id


def _resolve_file_or_id(
    path: str,
    client: OtterClient,
    folders: list[dict[str, Any]],
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        return resolve_file(path, folders, files)
    except PathResolutionError:
        raw = path.strip()
        if not _looks_like_id(raw):
            raise
        file_id = str(uuid.UUID(raw))
        if any(str(folder.get("id", "")).lower() == file_id for folder in folders):
            raise ValueError(f"{path} is a folder; this command only accepts files")
        try:
            file = client.get(f"/files/{file_id}")
        except ApiError as error:
            if error.status_code in {403, 404}:
                raise PathResolutionError(f"File not found: {path}") from error
            raise
        if not isinstance(file, dict) or not file.get("id"):
            raise PathResolutionError(f"File not found: {path}")
        return file


def _file_path_or_shared(
    file: dict[str, Any],
    folders: list[dict[str, Any]],
    files: list[dict[str, Any]],
) -> str:
    if any(str(item.get("id")) == str(file.get("id")) for item in files):
        return file_path(file, folders)
    return f"(shared) {file.get('name', '')}"


def _resolve_shared_file(
    path: str, client: OtterClient
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    folders = client.list_folder_tree()
    files = client.list_all_files()
    kind, item = _resolve_item(path, folders, files)
    if kind != "file":
        raise ValueError(f"{path} is a folder; this command only accepts files")
    return item, folders


def _share(args: argparse.Namespace, client: OtterClient) -> int:
    file, folders = _resolve_shared_file(args.path, client)
    user = _lookup_user(client, args.email)
    owner_id = _owner_id(client)
    permission = "editor" if args.edit else "viewer"
    client.post(
        f"/files/{file['id']}/share",
        json={
            "shared_with": user["id"],
            "permission": permission,
            "shared_by": owner_id,
        },
    )
    print(
        f"Shared {file_path(file, folders)} with {user.get('email', args.email)} "
        f"({permission})"
    )
    return 0


def _unshare(args: argparse.Namespace, client: OtterClient) -> int:
    file, folders = _resolve_shared_file(args.path, client)
    user = _lookup_user(client, args.email)
    try:
        client.delete(f"/files/{file['id']}/share/{user['id']}")
    except ApiError as error:
        if error.status_code == 404:
            raise ValueError(
                f"No share exists for {args.email} on {file_path(file, folders)}"
            ) from error
        raise
    print(f"Stopped sharing {file_path(file, folders)} with {user.get('email', args.email)}")
    return 0


def _shared(args: argparse.Namespace, client: OtterClient) -> int:
    files = client.list_all_files(endpoint="/files/shared")
    cache: dict[str, str | None] = {}
    rows = []
    for file in files:
        owner_id = str(file.get("ownerId") or "")
        owner_email = _user_email(client, owner_id, cache) if owner_id else "-"
        rows.append(
            {
                **file,
                "ownerEmail": owner_email,
            }
        )
    if args.json:
        _json(rows)
    else:
        _print_table(
            ["NAME", "SIZE", "MODIFIED", "OWNER", "ID"],
            [
                [
                    file.get("name", ""),
                    format_size(_size(file)),
                    _format_time(file.get("updatedAt")),
                    file["ownerEmail"],
                    file.get("id", ""),
                ]
                for file in rows
            ],
        )
    return 0


def _info(args: argparse.Namespace, client: OtterClient) -> int:
    folders = client.list_folder_tree()
    files = client.list_all_files()
    resolved_by_id = False
    try:
        kind, item = _resolve_item(args.path, folders, files)
    except PathResolutionError:
        kind, item = "file", _resolve_file_or_id(args.path, client, folders, files)
        resolved_by_id = True
    if kind == "folder":
        path = folder_path(_item_id(kind, item), folders)
        total = du_rows(_item_id(kind, item), folders, files)[-1]
        data = {
            "path": path,
            "id": _item_id(kind, item),
            "createdAt": item.get("createdAt"),
            "fileCount": total["fileCount"],
            "sizeBytes": total["bytes"],
        }
        if args.json:
            _json(data)
        else:
            _print_table(
                ["FIELD", "VALUE"],
                [
                    ["Path", path],
                    ["ID", data["id"]],
                    ["Created", _format_time(data["createdAt"])],
                    ["File count", data["fileCount"]],
                    [
                        "Size",
                        f"{format_size(data['sizeBytes'])} ({data['sizeBytes']:,} bytes)",
                    ],
                ],
            )
        return 0

    if not resolved_by_id:
        item = _resolve_file_or_id(args.path, client, folders, files)
    is_shared = not any(
        str(file.get("id")) == str(item.get("id")) for file in files
    )
    metadata = (
        item
        if is_shared
        else client.get(f"/files/{_item_id(kind, item)}")
    )
    shares = []
    cache: dict[str, str | None] = {}
    for share in metadata.get("sharedWith", []):
        resolved = dict(share)
        user_id = str(share.get("sharedWith") or "")
        resolved["email"] = _user_email(client, user_id, cache) if user_id else ""
        shares.append(resolved)
    data = {
        **metadata,
        "path": _file_path_or_shared(item, folders, files),
        "sharedWith": shares,
    }
    if args.json:
        _json(data)
        return 0
    size = _size(metadata)
    rows = [
        ["Path", data["path"]],
        ["ID", data.get("id", "")],
        ["Size", f"{format_size(size)} ({size:,} bytes)"],
        ["Type", metadata.get("mimeType", "-")],
        ["Created", _format_time(metadata.get("createdAt"))],
        ["Modified", _format_time(metadata.get("updatedAt"))],
    ]
    if metadata.get("version") is not None:
        rows.append(["Version", metadata["version"]])
    rows.extend(
        [
            "Shared with",
            f"{share['email']} ({share.get('permission', '')})",
        ]
        for share in shares
    )
    _print_table(["FIELD", "VALUE"], rows)
    return 0


def _cat(args: argparse.Namespace, client: OtterClient) -> int:
    folders = client.list_folder_tree()
    files = client.list_all_files()
    output = sys.stdout.buffer
    for path in args.paths:
        file = _resolve_file_or_id(path, client, folders, files)
        download = client.get(f"/files/{file['id']}/download")
        url = download.get("url") if isinstance(download, dict) else None
        if not url:
            name = file.get("name", path) if file else path
            raise ValueError(f"Download URL missing for {name}")
        for chunk in client.stream_download(str(url)):
            output.write(chunk)
    output.flush()
    return 0


def _versions(args: argparse.Namespace, client: OtterClient) -> int:
    folders = client.list_folder_tree()
    files = client.list_all_files()
    file = _resolve_file_or_id(args.path, client, folders, files)
    response = client.get(f"/files/{file['id']}/versions")
    if args.json:
        _json(response)
        return 0
    versions = sorted(
        response.get("versions", []),
        key=lambda version: int(version.get("version", 0)),
        reverse=True,
    )
    cache: dict[str, str | None] = {}
    _print_table(
        ["VERSION", "SIZE", "CREATED", "CREATED BY"],
        [
            [
                version.get("version", ""),
                format_size(_size(version)),
                _format_time(version.get("createdAt")),
                _user_email(client, str(version.get("createdBy")), cache)
                if version.get("createdBy")
                else "-",
            ]
            for version in versions
        ],
    )
    return 0


def _parser_option_strings(parser: argparse.ArgumentParser) -> list[str]:
    return sorted(
        {
            option
            for action in parser._actions
            for option in action.option_strings
        }
    )


def _subcommand_parsers(
    parser: argparse.ArgumentParser,
) -> dict[str, argparse.ArgumentParser]:
    action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return action.choices


def _bash_completion(parser: argparse.ArgumentParser) -> str:
    subcommands = _subcommand_parsers(parser)
    root_words = " ".join(
        [*subcommands, *_parser_option_strings(parser)]
    )
    lines = [
        "_otter_completion() {",
        "    local current command",
        '    current="${COMP_WORDS[COMP_CWORD]}"',
        "    if (( COMP_CWORD == 1 )); then",
        (
            "        COMPREPLY=( $(compgen -W "
            f"{shlex.quote(root_words)} -- \"$current\") )"
        ),
        "        return 0",
        "    fi",
        '    command="${COMP_WORDS[1]}"',
        '    case "$command" in',
    ]
    for name, command_parser in subcommands.items():
        options = " ".join(_parser_option_strings(command_parser))
        lines.extend(
            [
                f"        {name})",
                (
                    "            COMPREPLY=( $(compgen -W "
                    f"{shlex.quote(options)} -- \"$current\") )"
                ),
                "            ;;",
            ]
        )
    lines.extend(
        [
            "    esac",
            "}",
            "complete -F _otter_completion otter",
        ]
    )
    return "\n".join(lines) + "\n"


def _zsh_completion(parser: argparse.ArgumentParser) -> str:
    subcommands = _subcommand_parsers(parser)
    command_words = " ".join(subcommands)
    root_options = " ".join(
        shlex.quote(option) for option in _parser_option_strings(parser)
    )
    lines = [
        "#compdef otter",
        "_otter_completion() {",
        "    local -a commands",
        f"    commands=({command_words})",
        "    if (( CURRENT == 2 )); then",
        f'        compadd -- "${{commands[@]}}" {root_options}',
        "        return",
        "    fi",
        '    case "${words[2]}" in',
    ]
    for name, command_parser in subcommands.items():
        options = " ".join(
            shlex.quote(option) for option in _parser_option_strings(command_parser)
        )
        lines.extend(
            [
                f"        {name})",
                f"            compadd -- {options}",
                "            ;;",
            ]
        )
    lines.extend(
        [
            "    esac",
            "}",
            "compdef _otter_completion otter",
        ]
    )
    return "\n".join(lines) + "\n"


def _completion(args: argparse.Namespace, client: OtterClient | None = None) -> int:
    parser = build_parser()
    script = _bash_completion(parser) if args.shell == "bash" else _zsh_completion(parser)
    print(script, end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="otter")
    commands = parser.add_subparsers(dest="command", required=True)

    login = commands.add_parser("login")
    login.add_argument("--email")
    login.add_argument("--api-url")
    login.set_defaults(handler=_login)

    logout = commands.add_parser("logout")
    logout.set_defaults(handler=_logout)

    whoami = commands.add_parser("whoami")
    whoami.set_defaults(handler=_whoami)

    ls = commands.add_parser("ls")
    ls.add_argument("path", nargs="?", default="/")
    ls.add_argument("-l", "--long", action="store_true")
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(handler=_ls)

    tree = commands.add_parser("tree")
    tree.add_argument("path", nargs="?", default="/")
    tree.add_argument("--depth", type=int)
    tree.add_argument("--files", action="store_true")
    tree.set_defaults(handler=_tree)

    du = commands.add_parser("du")
    du.add_argument("path", nargs="?", default="/")
    du.add_argument("--json", action="store_true")
    du.set_defaults(handler=_du)

    find = commands.add_parser("find")
    find.add_argument("path", nargs="?", default="/")
    find.add_argument("--name")
    find.add_argument("--larger-than")
    find.add_argument("--smaller-than")
    find.add_argument("--older-than")
    find.add_argument("--newer-than")
    find.add_argument("-l", "--long", action="store_true")
    find.add_argument("--json", action="store_true")
    find.set_defaults(handler=_find)

    mkdir = commands.add_parser("mkdir")
    mkdir.add_argument("paths", nargs="+")
    mkdir.add_argument("-p", "--parents", action="store_true")
    mkdir.set_defaults(handler=_mkdir)

    mv = commands.add_parser("mv")
    mv.add_argument("sources", nargs="+")
    mv.add_argument("destination")
    mv.set_defaults(handler=_mv)

    rename = commands.add_parser("rename")
    rename.add_argument("path")
    rename.add_argument("new_name")
    rename.set_defaults(handler=_rename)

    upload = commands.add_parser("upload")
    upload.add_argument("local", nargs="+")
    upload.add_argument("--to", default="/")
    upload.add_argument("-r", "--recursive", action="store_true")
    upload.set_defaults(handler=_upload)

    download = commands.add_parser("download")
    download.add_argument("paths", nargs="+")
    download.add_argument("-o", "--output")
    download.set_defaults(handler=_download)

    rm = commands.add_parser("rm")
    rm.add_argument("paths", nargs="+")
    rm.set_defaults(handler=_rm)

    trash = commands.add_parser("trash")
    trash.add_argument("--json", action="store_true")
    trash.set_defaults(handler=_trash)

    restore = commands.add_parser("restore")
    restore.add_argument("names", nargs="+")
    restore.set_defaults(handler=_restore)

    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--type", choices=("file", "document"))
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=_search)

    share = commands.add_parser("share")
    share.add_argument("path")
    share.add_argument("--with", dest="email", required=True)
    share.add_argument("--edit", action="store_true")
    share.set_defaults(handler=_share)

    unshare = commands.add_parser("unshare")
    unshare.add_argument("path")
    unshare.add_argument("--with", dest="email", required=True)
    unshare.set_defaults(handler=_unshare)

    shared = commands.add_parser("shared")
    shared.add_argument("--json", action="store_true")
    shared.set_defaults(handler=_shared)

    info = commands.add_parser("info")
    info.add_argument("path")
    info.add_argument("--json", action="store_true")
    info.set_defaults(handler=_info)

    cat = commands.add_parser("cat")
    cat.add_argument("paths", nargs="+")
    cat.set_defaults(handler=_cat)

    versions = commands.add_parser("versions")
    versions.add_argument("path")
    versions.add_argument("--json", action="store_true")
    versions.set_defaults(handler=_versions)

    sync = commands.add_parser("sync")
    sync.add_argument("local_dir")
    sync.add_argument("remote_path")
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument("--replace", action="store_true")
    sync.add_argument("--json", action="store_true")
    sync.set_defaults(handler=_sync)

    completion = commands.add_parser("completion")
    completion.add_argument("shell", choices=("bash", "zsh"))
    completion.set_defaults(handler=_completion)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "find":
        try:
            if args.larger_than:
                parse_size(args.larger_than)
            if args.smaller_than:
                parse_size(args.smaller_than)
            if args.older_than:
                parse_duration(args.older_than)
            if args.newer_than:
                parse_duration(args.newer_than)
        except ValueError as error:
            parser.error(str(error))
    if args.command == "rename" and (not args.new_name or "/" in args.new_name):
        parser.error("NEW_NAME must be non-empty and must not contain '/'")
    if args.command == "completion":
        return args.handler(args)
    client: OtterClient | None = None
    try:
        client = OtterClient(api_url=getattr(args, "api_url", None))
        return args.handler(args, client)
    except SessionExpiredError as error:
        print(str(error), file=sys.stderr)
        return 1
    except ApiError as error:
        print(str(error), file=sys.stderr)
        return 1
    except httpx.HTTPError as error:
        print(f"Request failed: {error}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except OSError:
            pass
        return 0
    except TypeError as error:
        print(f"Invalid server response: {error}", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
