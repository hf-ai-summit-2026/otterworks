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
folders.

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
