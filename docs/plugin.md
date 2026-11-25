# Sandbox files in any tool: the `sandbox.files` plugin

An agent that works in a sandbox through MCP makes its files there: a plot in
`/work/out/plot.png`, a report in `/work/report.pdf`. Its other tools, such as
KohakuTerrarium's `read`, an image tool, or a chat bot's "send this file" tool,
run on the agent's own machine and cannot open a path inside the container.

The `sandbox.files` plugin closes that gap. Any tool argument that takes a file
to read accepts a sandbox file written as

```
sandbox:<server>/<path>
```

Before the tool runs, the plugin fetches the file from the sandbox into a local
copy and passes the copy's path to the tool. The tool itself does not change.
This works whether the sandbox runs on the same machine or on another one.

## Install

The repository is a KohakuTerrarium package (`kohaku.yaml` at its root). It
needs KohakuTerrarium 2.2.4 or newer.

```bash
kt install https://github.com/Kohaku-Lab/kt-sandbox
# or a local checkout, editable:
kt install ./kt-sandbox -e
```

The plugin needs no extra Python packages: `httpx` and `PyYAML` come with
KohakuTerrarium. You do not need `kt-sandbox[manager]` on the agent's machine.

## Turn it on

Package plugins are installed turned off. Turn the plugin on for one creature
in its config, and name the MCP servers that are kt-sandbox servers:

```yaml
plugins:
  - name: sandbox.files
    options:
      servers: [sandbox-lab]    # names from KohakuTerrarium's MCP settings
      max_bytes: 20971520       # optional; the largest file fetched (20 MiB)
```

Or at runtime: `/plugin enable sandbox.files`, then set the `servers` option.

| Option | Default | Meaning |
|---|---|---|
| `servers` | `[]` | MCP server names (from KohakuTerrarium's MCP settings, `mcp_servers.yaml`) that are kt-sandbox servers. Empty: the plugin does nothing and adds nothing to the prompt. |
| `max_bytes` | `20971520` | The largest file the plugin fetches. A larger file blocks the tool call with a message. |

When `servers` is not empty, the plugin adds three lines to the system prompt
(`## Sandbox files`) that tell the model the handle form and the sandbox names.

## How a handle works

| Handle | File in the sandbox | Local copy |
|---|---|---|
| `sandbox:sandbox-lab/out/plot.png` | `/work/out/plot.png` | `<working dir>/.kt-sandbox/sandbox-lab/work/out/plot.png` |
| `sandbox:sandbox-lab//etc/os-release` | `/etc/os-release` | `<working dir>/.kt-sandbox/sandbox-lab/etc/os-release` |

- A relative path is under `/work`. Two slashes after the server name start an
  absolute path.
- The plugin rewrites only the arguments that a tool declares as files it
  reads (`path_arguments` with `"read"`, for example `read`'s `path` or
  `qq_send`'s `media`). A list of files works too; each item that starts with
  `sandbox:` is fetched, the others stay as they are. Arguments that write
  files, and every other argument, stay as they are.
- A path with a `..` segment is refused. Copies stay inside `.kt-sandbox/`.
- The copy is fetched again on every call, so it is never stale.
- When the plugin unloads, it removes the copies it made.

The plugin runs before the built-in `sandbox` plugin (priority 0 against 1),
so a soft sandbox on the agent checks the local copy, which is inside the
working directory.

## Remote and local sandboxes

The plugin reads each server's entry from KohakuTerrarium's MCP settings and
fetches the file the same way the agent reaches the sandbox:

- **HTTP** (`streamable_http`, `http` or `sse`): `GET <url>/files?path=...`
  with the entry's headers, so the bearer token you set for the MCP server
  also opens the file route. For `http://vps:18765/mcp` the plugin asks
  `http://vps:18765/mcp/files`. This is the form for a sandbox on another
  machine.
- **stdio through `docker exec`** (what `kt-sandbox mcp NAME --register`
  writes): the plugin runs `docker exec <container> kt-sandbox-file <path>`.
  It passes your environment and the entry's `env`, so `DOCKER_HOST` reaches
  a remote Docker engine too. Other stdio commands cannot serve files.

`${VAR}` and `${VAR:default}` in the url, headers, args and env are expanded
as KohakuTerrarium does. If a variable is not set, the tool call is blocked
with a message that names the variable. Header values never appear in a
message or a log.

## When a fetch fails

The tool call is blocked and the model gets the reason as the tool result:

| Message | What to do |
|---|---|
| `sandbox:<server>/... names no sandbox server this agent knows` | Use a server from `servers`, or add it there. |
| `the sandbox rejected the token` | Check the headers of that MCP server. |
| `no file <path> in <server>` | The file does not exist in the sandbox. |
| `... is over N bytes` / `... is not a regular file` | The server's own message. |
| `cannot reach <url>` | The server is down or the url is wrong. |
| `this sandbox's server has no file route` | See below. |

### Upgrading an older sandbox

Sandboxes made before the file route have no `/files` route and no
`kt-sandbox-file` command. Run `kt-sandbox upgrade <sandbox>` on the
sandbox's host, then restart its MCP server.
