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
| `KT_SANDBOX_NAME` | the sandbox's name, used in the server's instructions | none |
| `KT_SANDBOX_MCP_TOKEN` | bearer token for `--transport http` | none (refuses to start) |

The server's instructions tell the model that the tools run inside the sandbox,
in the work folder, and that files and packages stay between calls. With
`KT_SANDBOX_NAME` set, they add that a file can be passed to a tool that takes a
file or media argument as `sandbox:<name>/<path>`.

## Command line

```
kt-sandbox-mcp [--transport stdio|http] [--host 0.0.0.0] [--port 8765]
               [--token-env KT_SANDBOX_MCP_TOKEN] [--insecure-no-auth]
```

Over HTTP the endpoint is `/mcp`. Bound to a loopback address, the server
accepts only loopback `Host` and `Origin` headers.

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
