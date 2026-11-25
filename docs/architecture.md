# Architecture

kt-sandbox ships two things: a **sandbox image** with an MCP server in it, and a
**manager** that opens containers from that image.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="images/architecture-dark.svg">
  <img src="images/architecture-light.svg" width="830" alt="kt-sandbox in one figure. Left, who talks to a sandbox: a KohakuTerrarium agent or any MCP client, which reaches the sandbox's MCP server through MCP (stdio through docker exec -i, or HTTP with a bearer token), and you, who log in with kt-sandbox connect and get a real terminal in the same container. Centre, the persistent sandbox container: kt-sandbox-mcp with KohakuTerrarium's tools bash, read, write, multi_edit, glob, grep and tree, and a shell with the /work folder and your tools, whose files and packages stay between calls, under the limits of its level (command time, output, CPU, memory, processes). Right, only for the standard level: the sandbox sits on its own network and its only way out is the egress proxy, which holds a credential per sandbox and does DNS and byte caps, and reaches only the allowed hosts such as pypi.org and github.com. Below, the kt-sandbox manager, a CLI that talks to Docker: up, down, rm and ls open a sandbox at a level; save and images use docker commit so the state can be opened at any level later; build makes the slim, data, render and dev images; mcp, doctor and levels print config and checks. The manager creates the container through the Docker API with the level's settings.">
</picture>

## Parts

| Part | Job |
|---|---|
| `server/` | The MCP server that runs inside a sandbox. Knows nothing of Docker. Limits and the level's policy come from environment variables. |
| `server/about/` | The about document (`kt-sandbox-about`): policy, live usage from the cgroup, tiers, programs and Python packages of the running sandbox. |
| `levels/` | The `Level` model and the presets `open`, `standard`, `strict`. |
| `manager/options.py` | Turns a level into container settings: limits, network, sudo, runtime, labels, environment. Pure, tested without Docker. |
| `manager/docker/` | The Docker calls: containers, images, and the allowlist network plumbing. |
| `manager/sandboxes.py` | The operations a person runs: up, down, rm, ls, save, export, import, connect. |
| `manager/builder.py` + `manager/image/` | Assembles a build context from the packaged Dockerfile, the tier files and the installed `kt_sandbox` package, and runs Docker. |
| `manager/kt_config.py` | Adds a sandbox's entry to KohakuTerrarium's global MCP server list (`kt-sandbox mcp NAME --register`), without importing KohakuTerrarium. |
| `files.py` | Reads one file out of a sandbox from a `sandbox:<name>/<path>` reference, through Docker's archive API. |
| `proxy/` | The egress proxy for the `standard` level. |
| `cli/` | `kt-sandbox` commands. |

## State

- **Docker is the registry.** A sandbox is a container with labels
  (`kt-sandbox.name`, `.level`, `.sudo`, `.network`, `.allow`); there is no
  database.
- **Files and packages live in the container's writable layer** and in `/work`
  inside it, so `save` (a `docker commit`) captures them. `rm` deletes them.
- **A saved image** is an ordinary image with the label `kt-sandbox.saved=1`.
  `export` writes it to a tarball (`docker save`) and `import` loads one
  (`docker load`); the label survives, so an imported image is listed by
  `kt-sandbox images`.

## The two network levels that need machinery

- `strict` is `--network none`.
- `standard` puts each sandbox on its **own internal network** (no gateway) with
  the egress proxy as the only other member, so sandboxes cannot reach each
  other. The proxy is attached to every such network and to the default one. It
  keeps a table of sandbox name, secret and hosts, which the manager writes into
  the proxy container whenever a sandbox starts or is removed. The proxy is
  removed with the last `standard` sandbox.

## The image

`kt-sandbox build` copies the installed `kt_sandbox` package into the build
context. The image keeps it in `/opt/kt-sandbox` (on `PYTHONPATH`) and has three
commands: `kt-sandbox-mcp` (`python -m kt_sandbox.server`), `kt-sandbox-about`
(`python -m kt_sandbox.server.about`) and `kt-sandbox` (`python -m kt_sandbox`,
which the egress proxy runs). The tiers it was built with and their usage notes
are in `/usr/local/share/kt-sandbox`.

The server's runtime packages are listed in `manager/image/`:
`runtime-requirements.txt` (installed normally: `mcp` and the packages
KohakuTerrarium's seven tools import) and `runtime-requirements-no-deps.txt`
(the pinned `kohakuterrarium`, installed with `--no-deps`, without its LLM
client stack). KohakuTerrarium's web frontend is removed from the image. To run
the server outside the image, install the `server` extra
(`pip install "kt-sandbox[server]"`).

## The server

- **KohakuTerrarium's tools, run in the sandbox.** The server imports
  KohakuTerrarium's own classes for `bash`, `read`, `write`, `multi_edit`,
  `glob`, `grep` and `tree` and runs them with the work folder as their working
  directory. Names, descriptions and argument schemas come from
  KohakuTerrarium's schema builder, so an MCP client sees what a model sees for
  the local tools.
- **One read history per client session**, for the read-before-write rule.
- **`bash` runs through the server's own runner,** which caps the time (the
  whole process group is killed at the limit) and keeps only the head and tail
  of the output in memory. The other tools' text is capped when it is returned.
- **mcp 1.x, low-level API.** The server uses `mcp.server.lowlevel.Server`, so
  the listed schemas are exactly KohakuTerrarium's. Over HTTP it serves the
  streamable-HTTP transport at `/mcp`, behind a bearer-token check.

## Access and users

- **KT knows only MCP.** kt-sandbox has no accounts, tokens or roles: whoever can
  run `docker exec` into the container can use it. The HTTP route has one bearer
  token set when you start the server.
- **One user for every level.** All levels run as `sandbox`. `open` allows `sudo`
  for setup; the others set no-new-privileges and drop every capability, so the
  same files and installs work after reopening at a stricter level.
