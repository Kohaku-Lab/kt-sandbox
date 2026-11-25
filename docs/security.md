# Security

## Threat model

- **Code in a sandbox is hostile.** A model that people in a chat can steer, or a
  script you pasted, runs there.
- **You are trusted.** The manager runs with your Docker access, and you decide
  which image to open and at which level.
- **A saved image is as trusted as whoever set it up.** A package or file added
  while a sandbox was open is in every sandbox opened from the image; the level
  still confines it.

## What each level enforces

Everything in this table is exercised against a real engine by
`tests/live/test_journeys.py`.

| Setting | `strict` | `standard` | `open` |
|---|---|---|---|
| Network | none: no route, DNS fails, a raw socket gets "network unreachable" | only the allowlist, through the egress proxy; everything else fails | normal outbound |
| User | `sandbox`, no capabilities, no-new-privileges (sudo refuses) | same | `sandbox` with sudo and Docker's default capabilities |
| CPU / memory / processes | 0.5 / 256m / 64 | 1 / 1g / 256 | 2 / 2g / 512 |
| One command | 15 s, then its process group is killed | 60 s | 300 s |
| Output | first 8 KB and last 4 KB of each result's text | same | same |

A request can shorten the time limit but never lengthen it. Memory limits kill
the offender (the shell reports it as `Killed`, exit code 137) and leave the
sandbox running; swap is off.

## The egress proxy (`standard`)

- Each sandbox has its own internal network with no gateway; the proxy is the
  only other member, so sandboxes cannot reach each other or the internet
  directly.
- The sandbox's `HTTP(S)_PROXY` carries a per-sandbox credential. The proxy
  rejects a missing or wrong credential (407) and serves only the hosts of that
  sandbox's allowlist (a host matches itself and its subdomains).
- It carries only ports 80 and 443, resolves DNS itself, refuses any host that
  resolves to a non-public address (private, loopback, link-local), and connects
  by address, so a name cannot change meaning between the check and the
  connection.
- It caps bytes per connection and logs every allow and deny
  (`docker logs kt-sandbox-egress`).
- The credential is a bearer secret: whoever holds it acts as that sandbox. It is
  not shared between sandboxes.

## Caveats

- **Containers share the host kernel.** A kernel escape defeats every level.
- **`open` is not a security level.** It exists to set things up. Its sandboxes
  share Docker's default network with each other and can reach services on the
  host's side of that network.
- **`--mount` gives a sandbox your files** with the access you grant (`:ro` for
  read-only).
- **The HTTP route is a code-execution port.** It needs a token
  (`KT_SANDBOX_MCP_TOKEN`); `--insecure-no-auth` removes the check, so use it
  only on a port nobody else can reach. Publish to `127.0.0.1` where possible.
- **The Docker socket stays with the manager.** Never mount it into a sandbox.
- **`sandbox:<name>/<path>` references read any file a sandbox holds,** for
  whoever runs `kt_sandbox.files` on the host. Only containers kt-sandbox opened
  are reachable (never the egress proxy or other containers), only regular
  files are read, and the caller sets the size limit. Which sandboxes a caller
  may read from is the caller's decision.
- **Saved images keep what was in the sandbox**, including secrets you typed or
  stored. Check before sharing an image.
- **A sandbox can exhaust its own process limit**, which blocks new tool calls
  until the processes exit; `down` and `up` clear it.
