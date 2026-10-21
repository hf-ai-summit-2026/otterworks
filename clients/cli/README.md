# OtterWorks CLI

`otter` is a command-line client for the OtterWorks file drive and search API.

## Install

From the repository root:

```sh
pip install -e clients/cli
# or
uv tool install ./clients/cli
```

## Commands

```sh
otter login
otter login --email you@example.com --api-url http://localhost:8080
otter whoami
otter logout

otter ls /
otter ls /Finance/Reports -l
otter ls / --json
otter tree /
otter tree /Finance --depth 2 --files
otter du /
otter du /Finance --json
otter find / --name '*.pptx'
otter find / --larger-than 80K --older-than 30d -l
otter find / --smaller-than 1.5MB --newer-than 12h --json

otter mkdir /Finance/Reports
otter mkdir -p /Finance/Reports/2025/Q1
otter mv /Finance/Reports/q1.xlsx /Finance/Archive
otter mv /Finance/Reports/q1.xlsx /Finance/Archive/quarterly.xlsx
otter rename /Finance/Archive/quarterly.xlsx q1-final.xlsx
otter share /Finance/Reports/q1.xlsx --with teammate@example.com
otter share /Finance/Reports/q1.xlsx --with teammate@example.com --edit
otter unshare /Finance/Reports/q1.xlsx --with teammate@example.com
otter shared
otter shared --json
otter info /Finance/Reports/q1.xlsx
otter info /Finance --json
otter cat /Finance/Reports/q1.xlsx
otter versions /Finance/Reports/q1.xlsx
otter versions /Finance/Reports/q1.xlsx --json

otter upload ./report.pdf --to /Finance/Reports
otter upload ./quarterly-folder -r --to /Finance
otter download /Finance/Reports/report.pdf
otter download /Finance/Reports/report.pdf -o ./report-copy.pdf
otter rm /Finance/Reports/report.pdf
otter trash
otter trash --json
otter restore report.pdf
otter search Q2
otter search budget --type document --json
```

Paths use `/` for the drive root, exact folder and file names, or a raw UUID. Ambiguous
names are rejected with the matching IDs. `rm` moves files to Trash; it does not accept
folders. `mkdir` creates folders and `-p` creates missing parents. `mv` can move files and
folders into an existing folder, or move and rename a single item to a new path. `rename`
changes a file or folder name within its current parent.
`share` and `unshare` manage file access by user email; folders are not shareable.
`shared` lists files shared with the signed-in user. `info` shows file metadata and shares,
or recursive totals for a folder. `cat` streams file contents to standard output.
Use a file UUID from `otter shared` to address shared files with `download`, `info`, and
`cat`. `versions` lists a file's version history; `--json` emits normalized version data.
Re-uploading the same name into the same folder creates a separate file, not a new version;
versions are associated with an individual file ID.

## Environment

- `OTTER_API_URL` sets the API origin; default is `http://localhost:8080`.
- `OTTER_TOKEN` supplies a bearer token directly and bypasses saved credentials.
- `OTTER_EMAIL` and `OTTER_PASSWORD` provide non-interactive credentials to `otter login`.
- `OTTER_DOWNLOAD_HOST` replaces the host in a presigned download URL, for example
  `localhost:4566` when using a local stack.
- `XDG_CONFIG_HOME` changes the base directory used for saved credentials.

Without `OTTER_TOKEN`, credentials are saved in
`$XDG_CONFIG_HOME/otter/credentials.json`, or `~/.config/otter/credentials.json` when
`XDG_CONFIG_HOME` is unset. The file is restricted to mode `0600`.
