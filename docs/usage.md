# Usage

## Commands

| Command | Does |
|---|---|
| `kt-sandbox up NAME [--level L] [--from IMAGE] [...]` | create a sandbox and start it, or start a stopped one |
| `kt-sandbox connect NAME` | a real terminal in the sandbox (`docker exec -it`), starting it if stopped |
| `kt-sandbox down NAME` | stop it; files and packages are kept |
| `kt-sandbox rm NAME [--force]` | remove it and its state |
| `kt-sandbox ls` | list sandboxes with level, state, sudo and image |
| `kt-sandbox save NAME IMAGE` | save the sandbox's state as an image |
| `kt-sandbox images [--rm IMAGE]` | list or remove saved images |
| `kt-sandbox export IMAGE FILE [--force]` | write an image to a tarball (`.tar`, or gzip for `.tar.gz`) |
| `kt-sandbox import FILE` | load images from a `.tar` or `.tar.gz` tarball |
| `kt-sandbox mcp NAME [--http \| --register]` | print the config that connects an agent, or add it to KohakuTerrarium's MCP server list |
| `kt-sandbox levels` | show what each level sets |
| `kt-sandbox build [-t TAG] [--extras ...]` | build the sandbox image |
| `kt-sandbox doctor` | check Docker, its runtimes and the default image |

`up` options override a level: `--network`, `--allow HOST` (repeatable),
`--cpus`, `--memory`, `--pids`, `--wall SECONDS`, `--runtime NAME`,
`--read-only`, `--mount SRC:DST[:ro]`, `--env KEY=VALUE`, `--publish PORT`.
`--runtime NAME` passes a container runtime to Docker: any runtime installed in
your Docker engine (`kt-sandbox doctor` lists them).

A sandbox keeps the level it was created with: `up NAME` without `--level` starts
a stopped sandbox at that level, and naming another level is refused. To use a
different one, save it and open the image as a new sandbox.

## The template workflow

Setting a sandbox up by hand is faster than writing a comprehensive Dockerfile:

```bash
kt-sandbox up lab --level open            # network and sudo available
kt-sandbox connect lab                    # sudo apt-get install ...; pip install ...; tidy up
kt-sandbox save lab lab-image
kt-sandbox up bot --from lab-image --level strict
```

The saved image carries the state: installed packages, files under `/work`,
dotfiles. The new sandbox gets the level's policy: no network, no sudo, small
limits. Nothing about the old level is in the image; proxy variables and
credentials from a `standard` sandbox are blanked when a sandbox opens at
another level.

## Images

`kt-sandbox build` assembles the image from tiers. `slim` is always installed.

| Tier | Adds |
|---|---|
| `slim` | python3, curl, sudo, CJK fonts, the MCP server |
| `data` | numpy, pandas, scipy, sympy, matplotlib, pillow |
| `render` | rsvg, poppler, cairosvg, pymupdf, weasyprint |
| `dev` | compiler, git, node, jq, ripgrep, sqlite, pytest, ipython |
| `media` | ffmpeg, imagemagick |
| `browser` | Chromium and playwright (large) |

```bash
kt-sandbox build --extras data,render -t my-sandbox
kt-sandbox build --apt tmux --pip duckdb -t my-sandbox
kt-sandbox up lab --from my-sandbox
```

`build` copies the installed `kt_sandbox` package (from a checkout or from a
git install) into the image, so the image runs the same version as your
manager.

Published images are `ghcr.io/kohaku-lab/kt-sandbox:slim|data|render|dev`.
Any image works if it has `kt-sandbox-mcp` on its `PATH` and a `sandbox` user
(uid 1000) with `/work`; the easiest way is `FROM` one of the published images.

## Moving images between hosts

`export` streams an image into a tarball and `import` loads it on another host:

```bash
kt-sandbox export lab-image lab-image.tar.gz     # gzip because of .gz; .tar stays plain
scp lab-image.tar.gz other-host:
kt-sandbox import lab-image.tar.gz               # on the other host
kt-sandbox up bot --from lab-image --level strict
```

`export` refuses to overwrite an existing file unless you pass `--force`.
An imported image keeps its labels, so a saved image is listed by
`kt-sandbox images` again; `import` says when a loaded image was not saved by
kt-sandbox.

## Connecting an agent

KohakuTerrarium reaches a sandbox only through MCP. `kt-sandbox mcp NAME`
prints an `mcp_servers` entry:

```yaml
mcp_servers:
  - name: sandbox-lab
    transport: stdio
    command: docker
    args: [exec, -i, kt-sandbox-lab, kt-sandbox-mcp]
```

This works at every level, including `strict` (no network, so no published
port). It needs the Docker CLI where KT runs; for a remote Docker host set
`DOCKER_HOST`.

`kt-sandbox mcp NAME --register` writes the same entry, named `sandbox-NAME`,
into KohakuTerrarium's global MCP server list: `mcp_servers.yaml` in
`$KT_CONFIG_DIR`, or in `~/.kohakuterrarium`. It replaces an entry of the same
name and keeps every other entry as it is. A file that is not a valid list is
reported and left unchanged.

The tools a sandbox offers are listed in [MCP tools](mcp.md).

For HTTP, open the sandbox with `--publish PORT`, start the server in it with a
token, and connect with a bearer header (KohakuTerrarium accepts `headers` in an
`mcp_servers` entry):

```bash
kt-sandbox up lab --level open --publish 18765
docker exec -d -e KT_SANDBOX_MCP_TOKEN=secret kt-sandbox-lab kt-sandbox-mcp --transport http --port 8765
```

```yaml
mcp_servers:
  - name: sandbox-lab
    transport: streamable_http
    url: http://localhost:18765/mcp
    headers:
      Authorization: "Bearer ${SANDBOX_TOKEN}"
```

The HTTP server refuses to start without a token unless you pass
`--insecure-no-auth`.

## Reading a sandbox file from Python

Code on the host that holds a reference like `sandbox:lab/out/chart.png` (for
example a chat bot sending an agent's chart) reads the file with
`kt_sandbox.files`, which needs the `manager` extra:

```python
from kt_sandbox import files
from kt_sandbox.errors import SandboxError

try:
    chart = files.read("sandbox:lab/out/chart.png", max_bytes=10_000_000)
except SandboxError as exc:
    print(exc)          # says what to do next
else:
    print(chart.sandbox, chart.path, chart.name, len(chart.data))
```

- The part before the first `/` is the sandbox's name, or its container's id,
  id prefix or name. Only sandboxes count; any other container is "no sandbox".
- A relative path is under `/work`; `sandbox:lab//etc/hosts` is an absolute path.
- The sandbox may be stopped. The file comes through Docker's archive API, so
  links in the middle of the path resolve inside the container.
- Only a regular file is read: a folder, a symbolic link or a special file is
  refused. A file over `max_bytes` is refused before its content is read.

## Troubleshooting

- **A sandbox that uses up its process limit blocks new calls.** Docker cannot
  start the next `exec` while the limit is reached, and the call fails with
  "OCI runtime exec failed". The processes usually exit by themselves; if not,
  `kt-sandbox down NAME && kt-sandbox up NAME` clears them.
- **`up` fails with "image ... could not be pulled".** Build it:
  `kt-sandbox build -t <that name>`.
- **A command is cut or killed.** Each command has the level's time limit, and
  every result keeps the first two thirds and last third of 12 KB of text.
- **Background processes** keep running after a command returns, and their
  output is read and dropped so they never block. They stop with the sandbox.
