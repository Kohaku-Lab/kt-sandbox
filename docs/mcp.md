# MCP tools

The server (`kt-sandbox-mcp`, or `python -m kt_sandbox.server`) runs inside the
sandbox and speaks MCP over stdio (default) or streamable HTTP.

## The tools

The server offers seven tools with the same names, descriptions and arguments as
KohakuTerrarium's built-in tools of the same name. It runs KohakuTerrarium's own
tool code inside the sandbox, so behaviour and output formats are the same as
for a local agent. Relative paths are relative to the work folder (`/work`).

| Tool | Arguments | Does |
|---|---|---|
| `bash` | `command`, `type?`, `timeout?` | runs a shell command in `/work` and returns its output (stdout and stderr together) |
| `read` | `path`, `offset?`, `limit?` | shows a text file with line numbers, an image (PNG, JPEG, GIF, WEBP) as an image, or PDF pages (in images that have `pymupdf`, such as the `render` tier) |
| `write` | `path`, `content` | creates a file, or replaces one that this session has read |
| `multi_edit` | `path`, `edits`, `strict?`, `best_effort?` | applies ordered search-and-replace edits to one file that this session has read |
| `glob` | `pattern`, `path?`, `limit?`, `gitignore?` | lists the files that match a pattern |
| `grep` | `pattern`, `path?`, `glob?`, `limit?`, `ignore_case?`, `gitignore?` | searches files for a regular expression |
| `tree` | `path?`, `depth?`, `limit?`, `hidden?`, `gitignore?` | shows a folder as a tree |

The `bash` schema also carries KohakuTerrarium's call controls
`run_in_background` and `allow_concurrent`. The server runs every call to the
end and returns its result.

**Reading before writing.** `write` and `multi_edit` change an existing file
only after `read` has shown it in the same MCP session, and only if the file did
not change since. A file the session wrote itself counts as read. Each client
session keeps its own read history.

## Results

- Text comes back as text, an image as MCP image content.
- A failure is an MCP error result: the first text is the message (for example
  `Command exited with code 4` or `File not found: notes.txt`), followed by any
  output the tool produced.
- `bash` stops a command at the sandbox's time limit and kills its whole
  process group; the result says `Command timed out after 15s`. A `timeout`
  argument can shorten the limit, never lengthen it; `0` or no value means the
  limit.
- A command gets no input (stdin is empty). Background processes it starts keep
  running and do not hold up the result; their output is read and dropped.
- The text of any result is cut to the output limit: the first two thirds and
  the last third are kept, with `[... N bytes omitted ...]` between them.

## Settings

The manager sets these when it opens a sandbox; a hand-started server reads the
same variables.

| Variable | Meaning | Default |
|---|---|---|
| `KT_SANDBOX_WORKDIR` | where the tools work | `/work` if it exists, else the current folder |
| `KT_SANDBOX_WALL_S` | longest one command may run | 30 |
| `KT_SANDBOX_OUTPUT_BYTES` | most text one result returns | 12288 |
| `KT_SANDBOX_NAME` | the sandbox's name, used in the server's instructions (`--name` overrides it) | none |
| `KT_SANDBOX_LEVEL` | the level the sandbox was opened at | none |
| `KT_SANDBOX_NETWORK` | `none`, `allowlist` or `open` | none |
| `KT_SANDBOX_ALLOW` | the allowed hosts, separated by commas | none |
| `KT_SANDBOX_SUDO` | `1` if `sudo` works, `0` if not | none |
| `KT_SANDBOX_MCP_TOKEN` | bearer token for `--transport http` | none (refuses to start) |

A blank value means the default. A value that is not a whole number, a network
mode or `0`/`1` stops the server with a message that names the variable.

The manager sets `LEVEL`, `NETWORK`, `ALLOW` and `SUDO` for every sandbox at
every level, so a sandbox opened from a saved image gets its own level's values,
not those of the level the image was saved at. They never hold the egress
proxy's credential.

## The server's instructions

The server sends instructions that a client shows its model. They say that the
tools run inside the sandbox, in the work folder, and that files and packages
stay between calls. With a name set (`KT_SANDBOX_NAME`, or `--name` on a server
started by hand), they name the sandbox.

When the manager opened the sandbox, two more lines follow: the facts of its
level, and where to read about the rest. For a sandbox `bot` at `strict`:

```
You work inside the sandbox bot: these tools run there, in /work, and files and packages stay between calls.
Level strict: the sandbox is offline; work with the files and packages already here. Commands run as the user `sandbox`, without sudo. Each command runs up to 15 s.
Programs, Python packages and live usage: /home/sandbox/.kt-sandbox/about.md (written when this server started), or run `kt-sandbox-about` for a fresh view.
```

The level line of the other presets:

```
Level standard: the network reaches only pypi.org, files.pythonhosted.org, github.com, raw.githubusercontent.com, through a proxy already set up. Commands run as the user `sandbox`, without sudo; `pip install` installs into its home. Each command runs up to 60 s.
Level open: the network is open. `sudo` works without a password. Each command runs up to 300 s.
```

Overrides such as `--allow` or `--wall` change the facts to match. A server
started by hand without these variables sends only the first line. If the about
file cannot be written, the last line names only `kt-sandbox-about`.

## The about document

`kt-sandbox-about` prints a short Markdown document about the sandbox it runs
in, read from the running container:

| Section | Shows |
|---|---|
| Policy | level, network and allowed hosts, sudo, user, time limit of one command, text limit of one result, work folder |
| Usage now | memory used and its limit, CPU limit, processes and tasks against the process limit (from the cgroup), free disk in the work folder |
| Image and programs | the tiers the image was built with, and which of a fixed list of programs are on `PATH` (looked up, not run) |
| Python | the installed distributions with versions, apart from the server's own packages and what they need; the server's direct packages on a line of their own |
| Notes | the usage notes of each tier in the image |

A value that cannot be read says `unknown`; the command still exits 0. The
document is built only from those facts: it never shows environment variables,
proxy settings or tokens.

The server writes the same document to `~/.kt-sandbox/about.md`
(`/home/sandbox/.kt-sandbox/about.md`) each time it starts, which for stdio is
each time a client connects. The file therefore shows the sandbox as it was when
the session began: a package installed during the session appears in
`kt-sandbox-about` at once and in the file from the next session. The server
writes the file only when the manager set the level's values; a failed write is
logged and the server starts anyway.

## Command line

```
kt-sandbox-mcp [--transport stdio|http] [--host 0.0.0.0] [--port 8765]
               [--token-env KT_SANDBOX_MCP_TOKEN] [--insecure-no-auth] [--name NAME]
```

Over HTTP the endpoint is `/mcp`. Bound to a loopback address, the server
accepts only loopback `Host` and `Origin` headers. With `--transport http` the
server logs each file request (path and status, never headers) to standard
error.

## Reading a file out of the sandbox

Both ways follow one rule: a relative path is under the work folder
(`KT_SANDBOX_WORKDIR`, `/work` by default), an absolute path is used as given;
the last component must be a regular file, so a symbolic link, a folder or a
special file is refused (a link earlier in the path is followed); a file over
the byte limit is refused before any byte is sent. The limit is 64 MiB, and a
larger requested limit is lowered to it.

Over HTTP, on the same port and behind the same bearer token as `/mcp`:

```
GET /mcp/files?path=out/chart.png&max_bytes=10000000
Authorization: Bearer <token>
```

| Status | Means |
|---|---|
| 200 | the file's bytes, `Content-Type: application/octet-stream`, with `Content-Length`, `X-KT-Sandbox-Size` and `X-KT-Sandbox-Mtime` (seconds since the epoch, a float) |
| 400 | `path` missing or empty, or `max_bytes` not a whole number of at least 1 |
| 401 | no token or the wrong one |
| 403 | the server's user cannot read the file |
| 404 | the file does not exist |
| 413 | the file is over the limit; the message gives its size and the limit |
| 422 | a folder, a symbolic link or a special file |

Every error is JSON, `{"error": "<message>"}`.

Inside the sandbox, for clients that reach it over stdio (`docker exec`):

```
kt-sandbox-file PATH [--max-bytes N]   # or python -m kt_sandbox.server.files
```

writes the file's bytes to standard output and exits 0. On a refusal it prints
the reason on standard error and exits 3 (not found), 4 (not a regular file),
5 (too large), 6 (cannot be read) or 2 (usage).

```
kt-sandbox-about        # or python -m kt_sandbox.server.about
```

prints the about document to standard output.

## For KohakuTerrarium

`kt-sandbox mcp NAME` prints the `mcp_servers` entry for a sandbox, and
`kt-sandbox mcp NAME --register` adds it, as `sandbox-NAME`, to
KohakuTerrarium's global MCP server list (see
[usage](usage.md#connecting-an-agent)).

Through KohakuTerrarium's MCP meta-tools, the agent calls a sandbox tool with
`mcp_call(server, tool, args)`, for example
`mcp_call("sandbox-lab", "bash", {"command": "ls"})`. Those results come back as
text only: an image becomes `[binary data: N bytes]`, so an image that `read`
returns is not shown to the model on that route.
