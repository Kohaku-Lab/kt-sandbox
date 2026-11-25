# kt-sandbox

Persistent Docker sandboxes with an MCP server inside, and a manager to open,
log into, save and lock them down.

An agent (a KohakuTerrarium creature, or anything that speaks MCP) works in a
sandbox through its MCP server, which offers KohakuTerrarium's standard tools
(`bash`, `read`, `write`, `multi_edit`, `glob`, `grep`, `tree`) running inside
the sandbox. You can log into the same sandbox with a real
terminal, set it up by hand with everything open, save it as an image, and open
that image again at a stricter security level.

## How it fits together

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/architecture-dark.svg">
  <img src="docs/images/architecture-light.svg" width="830" alt="kt-sandbox in one figure. Left, who talks to a sandbox: a KohakuTerrarium agent or any MCP client, which reaches the sandbox's MCP server through MCP (stdio through docker exec -i, or HTTP with a bearer token), and you, who log in with kt-sandbox connect and get a real terminal in the same container. Centre, the persistent sandbox container: kt-sandbox-mcp with KohakuTerrarium's tools bash, read, write, multi_edit, glob, grep and tree, and a shell with the /work folder and your tools, whose files and packages stay between calls, under the limits of its level (command time, output, CPU, memory, processes). Right, only for the standard level: the sandbox sits on its own network and its only way out is the egress proxy, which holds a credential per sandbox and does DNS and byte caps, and reaches only the allowed hosts such as pypi.org and github.com. Below, the kt-sandbox manager, a CLI that talks to Docker: up, down, rm and ls open a sandbox at a level; save and images use docker commit so the state can be opened at any level later; build makes the slim, data, render and dev images; mcp, doctor and levels print config and checks. The manager creates the container through the Docker API with the level's settings.">
</picture>

- **KT only speaks MCP** to a sandbox. How you run the server (stdio through
  `docker exec -i`, or HTTP on a published port) is up to you; `kt-sandbox mcp`
  prints a ready config for either, and `--register` adds the stdio one to KT's
  MCP server list.
- **Sandboxes are persistent.** Files and installed packages survive stop and
  start. `kt-sandbox save` turns a sandbox into an image you can open again.
- **A level is policy, never part of the image.** Network, CPU, memory, process
  count, command time and sudo are set when a sandbox is opened.
- **The agent knows its sandbox.** The server's instructions state the level's
  network, sudo and time limit, and `kt-sandbox-about` (also written to
  `~/.kt-sandbox/about.md`) lists the programs, Python packages, tiers and live
  usage.

| Level | Network | sudo | CPUs / memory / processes | One command |
|---|---|---|---|---|
| `open` | open | yes | 2 / 2g / 512 | 300 s |
| `standard` (default) | only an allowlist of hosts, through an egress proxy | no | 1 / 1g / 256 | 60 s |
| `strict` | none | no | 0.5 / 256m / 64 | 15 s |

## The template workflow

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/workflow-dark.svg">
  <img src="docs/images/workflow-light.svg" width="830" alt="Set a sandbox up with everything open, then lock it down. A top lane shows the state held in the image: the base image with python, curl and sudo (kt-sandbox build), then your setup of packages, files and dotfiles made by kt-sandbox up lab --level open and kt-sandbox connect lab, then at the save line the saved image lab-image (kt-sandbox save lab lab-image), then the same state in a new sandbox (kt-sandbox up bot --level strict --from lab-image). A bottom lane shows the policy, the level: before the save line it is open, with network, sudo, 2 CPUs and 300 seconds a command, to install and try things; after it, strict, with no network, no sudo, 0.5 CPU and 15 seconds a command, for an agent anyone can steer. The level is set when a sandbox is created; to change it, save and open the image as a new sandbox.">
</picture>

## Quick start

```bash
pip install "kt-sandbox[manager] @ git+https://github.com/Kohaku-Lab/kt-sandbox"
kt-sandbox build                       # builds ghcr.io/kohaku-lab/kt-sandbox:slim locally
kt-sandbox up lab --level open         # open a sandbox with everything allowed
kt-sandbox connect lab                 # log in: install what you need, then exit
kt-sandbox save lab lab-image          # save its state as an image
kt-sandbox up bot --from lab-image --level strict   # same state, locked down
kt-sandbox mcp bot --register          # add it to KT's MCP servers as sandbox-bot
```

`kt-sandbox ls`, `down`, `rm`, `images`, `export`, `import`, `levels` and
`doctor` do what they say; see [docs/usage.md](docs/usage.md).
`kt-sandbox upgrade NAME` puts the installed kt-sandbox into an existing sandbox.
A sandbox file can be fetched with `GET /mcp/files?path=...` on the HTTP server,
or `kt-sandbox-file PATH` inside the sandbox; see [docs/mcp.md](docs/mcp.md).

## Sandbox files in any KohakuTerrarium tool

The repository is also a KohakuTerrarium package with one plugin,
`sandbox.files`. With it, any tool argument that takes a file to read accepts
a file inside a sandbox, local or on another machine, as
`sandbox:<server>/<path>`:

```bash
kt install https://github.com/Kohaku-Lab/kt-sandbox
```

```yaml
plugins:
  - name: sandbox.files
    options:
      servers: [sandbox-lab]
```

See [docs/plugin.md](docs/plugin.md).

## Layout and tests

The repository follows the conventions of the KohakuTerrarium packages:

- One responsibility per module. A family of files that share a prefix is a
  sub-package with the prefix dropped (`kt_sandbox/cli/connect.py`, not
  `kt_sandbox/cli_connect.py`).
- Files stay under 500 statements (imports and docstrings excluded); 1000 is the
  hard limit (`tests/unit/test_layout.py`).
- Imports sit at the top of the module, grouped as standard library, third
  party, then this package. No `from __future__ import annotations`.
- Tests mirror the package: `tests/unit/<area>/test_<module>.py` tests
  `kt_sandbox/<area>/<module>.py` and asserts behaviour. `tests/live/` runs whole
  workflows against a real Docker engine (`KT_SANDBOX_LIVE=1`).

```bash
pip install -e ".[dev]"
ruff check . && black --check . && pytest
KT_SANDBOX_LIVE=1 pytest tests/live    # needs Docker; builds the image first
```

## Documentation

- [Usage](docs/usage.md): commands, the template workflow, images, connecting, troubleshooting
- [Architecture](docs/architecture.md): components, state and access
- [Security](docs/security.md): what each level enforces and what it does not
- [MCP tools](docs/mcp.md): the tools a sandbox offers and how to connect
- [Plugin](docs/plugin.md): `sandbox:<server>/<path>` files for any KohakuTerrarium tool

## License

Apache-2.0
