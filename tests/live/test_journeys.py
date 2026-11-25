"""Whole workflows against a real Docker engine: set up open, save, reopen locked down."""

import asyncio
import gzip
import os
import socket
import time

import httpx
import pytest
import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from kt_sandbox import files
from kt_sandbox.cli import main
from kt_sandbox.errors import ManagerError, NotAFile, NotFound, TooLarge
from kt_sandbox.manager.options import container_name

TOOLS = {"bash", "read", "write", "multi_edit", "glob", "grep", "tree"}
# An image built before the current package, with the server's dependencies;
# without it the upgrade steps run on a sandbox from the image under test.
PRE_IMAGE = os.environ.get("KT_SANDBOX_LIVE_PRE_IMAGE", "")
# An image whose server predates KohakuTerrarium's tools.
OLD_IMAGE = os.environ.get(
    "KT_SANDBOX_LIVE_OLD_IMAGE", "ghcr.io/kohaku-lab/kt-sandbox:slim"
)
TOKEN = "live-token"


def stdio_params(name: str) -> StdioServerParameters:
    """The server of sandbox ``name`` over ``docker exec -i``, as a KT stdio entry runs it."""
    return StdioServerParameters(
        command="docker", args=["exec", "-i", container_name(name), "kt-sandbox-mcp"]
    )


async def mcp_session(params: StdioServerParameters, steps) -> object:
    """Open one MCP session and return what ``steps(session, init)`` returns."""
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            return await steps(session, init)


async def mcp_call(name: str, tool: str, **arguments) -> str:
    """Call one tool in a fresh session; return its text (an error message comes first)."""

    async def call(session, _):
        return await session.call_tool(tool, arguments)

    result = await mcp_session(stdio_params(name), call)
    return "\n".join(part.text for part in result.content if part.type == "text")


async def sh(name: str, command: str, **arguments) -> str:
    return await mcp_call(name, "bash", command=command, **arguments)


async def instructions_of(session, init) -> str:
    return init.instructions


def exec_about(manager, name: str) -> str:
    """Run ``kt-sandbox-about`` in sandbox ``name`` through ``docker exec``; return its output."""
    container = manager.client.containers.get(container_name(name))
    code, output = container.exec_run(["kt-sandbox-about"])
    assert code == 0, output
    return output.decode()


def assert_lines(text: str, *lines: str) -> None:
    present = text.splitlines()
    for line in lines:
        assert line in present, f"{line!r} not in:\n{text}"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def serve_http(container) -> None:
    """Start the sandbox's MCP server over HTTP in the background, with :data:`TOKEN`."""
    container.exec_run(
        ["kt-sandbox-mcp", "--transport", "http", "--port", "8765"],
        environment={"KT_SANDBOX_MCP_TOKEN": TOKEN},
        detach=True,
    )


def fetch(port: int, path: str, token: str | None = TOKEN) -> httpx.Response:
    """GET ``/mcp/files`` on ``port``, retrying until the server answers."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    deadline = time.monotonic() + 30
    while True:
        try:
            return httpx.get(
                f"http://127.0.0.1:{port}/mcp/files",
                params={"path": path},
                headers=headers,
                timeout=10,
            )
        except httpx.TransportError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.3)


def wait_closed(port: int) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{port}/mcp", timeout=1)
        except httpx.TransportError:
            return
        time.sleep(0.3)
    raise AssertionError(f"the server on port {port} did not stop")


async def py(name: str, code: str, **arguments) -> str:
    """Run a Python snippet through ``bash`` with a here-document."""
    return await sh(name, f"python3 - <<'PY'\n{code}\nPY", **arguments)


async def test_set_up_open_save_and_reopen_strict(
    manager, names, image, tmp_path, monkeypatch, capsys
):
    lab, bot, moved = names("lab"), names("bot"), names("moved")
    image_ref = f"{lab}:v1"

    up = manager.up(lab, level_name="open", image=image)
    assert up.action == "created" and up.info.sudo is True
    assert manager.up(lab, level_name="open", image=image).action == "running"

    # `mcp --register` writes the entry KT reads; that entry reaches the sandbox.
    monkeypatch.setenv("KT_CONFIG_DIR", str(tmp_path / "kt"))
    assert main(["mcp", lab, "--register"]) == 0
    printed = capsys.readouterr().out
    assert f"registered sandbox-{lab}" in printed and "mcp_servers.yaml" in printed
    servers = yaml.safe_load((tmp_path / "kt" / "mcp_servers.yaml").read_text())
    assert servers == [manager.mcp_config(lab)]

    async def first_look(session, init):
        listed = {tool.name for tool in (await session.list_tools()).tools}
        ran = await session.call_tool("bash", {"command": "echo $KT_SANDBOX_NAME"})
        return init.instructions, listed, ran.content[0].text

    registered = StdioServerParameters(
        command=servers[0]["command"], args=servers[0]["args"]
    )
    instructions, listed, own_name = await mcp_session(registered, first_look)
    assert listed == TOOLS and own_name == f"{lab}\n"
    assert f"inside the sandbox {lab}:" in instructions
    assert "sandbox:" not in instructions.replace(f"the sandbox {lab}:", "")
    assert instructions.splitlines()[1:] == [
        "Level open: the network is open. `sudo` works without a password. "
        "Each command runs up to 300 s.",
        "Programs, Python packages and live usage: "
        "/home/sandbox/.kt-sandbox/about.md (written when this server started), "
        "or run `kt-sandbox-about` for a fresh view.",
    ]
    assert main(["mcp", lab, "--register"]) == 0
    assert f"updated sandbox-{lab}" in capsys.readouterr().out

    # An open sandbox: network, sudo, its own files owned by the sandbox user.
    out = await sh(
        lab,
        "id -un; sudo -n touch /usr/local/marker && echo sudo-ok; echo mine > /work/notes.txt; curl -sS -m 15 -o /dev/null -w 'net:%{http_code}' https://pypi.org",
    )
    assert "sandbox" in out and "sudo-ok" in out and "net:200" in out

    # The sandbox describes itself: its level, live usage and image tiers.
    lab_about = exec_about(manager, lab)
    assert_lines(
        lab_about,
        "- Level: open",
        "- Network: open",
        "- sudo: works without a password",
        "- User: sandbox",
        "- One command: up to 300 s",
        "- CPUs: 2",
        "- Tiers: slim",
        "## Notes: slim",
    )
    assert " used of 2 GiB" in lab_about and " of 512)" in lab_about
    assert "- Found: python3, pip, curl, sudo" in lab_about

    # The file is written when a server starts; the command reads the sandbox now.
    async def install_and_compare(session, _):
        result = await session.call_tool(
            "bash",
            {
                "command": "pip install -q cowsay >/dev/null 2>&1; "
                "echo fresh:$(kt-sandbox-about | grep -c cowsay); "
                "echo file:$(grep -c cowsay ~/.kt-sandbox/about.md)"
            },
        )
        return result.content[0].text

    compared = await mcp_session(stdio_params(lab), install_and_compare)
    assert compared.split() == ["fresh:1", "file:0"]
    assert "cowsay" in await sh(lab, "cat ~/.kt-sandbox/about.md")

    # Stop and start keep the state.
    manager.down(lab)
    assert manager.up(lab, level_name="open", image=image).action == "started"
    assert "mine" in await sh(lab, "cat /work/notes.txt")

    # Naming no level restarts a stopped sandbox at the level it already has.
    manager.down(lab)
    assert manager.up(lab, image=image).action == "started"
    assert {i.name: i.level for i in manager.ls()}[lab] == "open"

    saved = manager.save(lab, image_ref)
    assert saved.reference == image_ref and saved.source == lab
    assert image_ref in [i.reference for i in manager.saved_images()]

    # The same state, locked down.
    manager.up(bot, level_name="strict", image=image_ref)
    state = await sh(
        bot,
        "cat /work/notes.txt; ls /usr/local/marker; ls -l /work/notes.txt | cut -d' ' -f3",
    )
    assert "mine" in state and "/usr/local/marker" in state and "sandbox" in state

    # The image carries the open level's values; the strict level replaces them.
    policy = await sh(
        bot, "env | grep -E '^KT_SANDBOX_(LEVEL|NETWORK|ALLOW|SUDO)=' | sort"
    )
    assert policy.split() == [
        "KT_SANDBOX_ALLOW=",
        "KT_SANDBOX_LEVEL=strict",
        "KT_SANDBOX_NETWORK=none",
        "KT_SANDBOX_SUDO=0",
    ]
    bot_instructions = await mcp_session(stdio_params(bot), instructions_of)
    assert bot_instructions.splitlines()[1] == (
        "Level strict: the sandbox is offline; work with the files and packages "
        "already here. Commands run as the user `sandbox`, without sudo. Each "
        "command runs up to 15 s."
    )
    written = await sh(bot, "cat ~/.kt-sandbox/about.md")
    assert_lines(written, "- Level: strict", "- Network: none; the sandbox is offline")
    assert "cowsay" in written and "- Level: open" not in written
    bot_about = exec_about(manager, bot)
    assert_lines(
        bot_about,
        "- Level: strict",
        "- sudo: off",
        "- One command: up to 15 s",
        "- CPUs: 0.5",
        "- Tiers: slim",
    )
    assert " used of 256 MiB" in bot_about and " of 64)" in bot_about

    locked = await sh(
        bot,
        "sudo -n true 2>&1 | head -1; grep -E '^(CapEff|NoNewPrivs)' /proc/self/status",
    )
    assert "no new privileges" in locked.lower()
    assert "CapEff:\t0000000000000000" in locked and "NoNewPrivs:\t1" in locked

    offline = await sh(
        bot,
        "curl -sS -m 5 https://pypi.org 2>&1 | tail -1; env | grep -ci '^https\\?_proxy=.\\+' || true",
    )
    assert "Could not resolve host" in offline and offline.rstrip().endswith("0")

    # Limits of the strict level hold.
    started = time.monotonic()
    assert await sh(bot, "exec sleep 60", timeout=100) == (
        "Command timed out after 15s"
    )
    assert time.monotonic() - started < 30
    forks = await py(
        bot,
        "import os\nn=0\nfor _ in range(200):\n    try:\n        if os.fork()==0:\n            import time; time.sleep(3); os._exit(0)\n        n+=1\n    except OSError:\n        break\nprint('forked', n)",
        timeout=10,
    )
    assert "forked" in forks and int(forks.split("forked")[1].split()[0]) < 64
    await asyncio.sleep(
        4
    )  # the forked children exit; until then no new process can start
    oom = await py(bot, "b = bytearray(600*1024*1024); print('allocated')", timeout=10)
    assert oom.startswith("Command exited with code 137\n"), oom
    assert "Killed" in oom and "allocated" not in oom.splitlines()
    loud = await sh(bot, "yes abcdefghij | head -c 2000000")
    assert "bytes omitted" in loud and len(loud) < 20000

    # Files written through MCP land in /work and survive; the file tools agree.
    wrote = await mcp_call(
        bot, "write", path="out/result.txt", content="written by the agent\n"
    )
    assert wrote.startswith("Created /work/out/result.txt")
    assert "written by the agent" in await sh(bot, "cat /work/out/result.txt")
    assert await mcp_call(bot, "read", path="out/result.txt") == (
        "     1→written by the agent"
    )
    assert await mcp_call(bot, "glob", pattern="out/*") == "out/result.txt"
    assert "out/result.txt" in await mcp_call(bot, "grep", pattern="agent")
    assert "result.txt" in await mcp_call(bot, "tree", path="out")

    # sandbox:<name>/<path> references read files out of the sandbox.
    await sh(
        bot,
        "ln -s /etc/passwd /work/out/passwd; head -c 300000 /dev/zero > /work/out/big.bin",
    )
    got = files.read(f"sandbox:{bot}/out/result.txt", max_bytes=1000)
    assert (got.sandbox, got.path, got.name, got.data) == (
        bot,
        "/work/out/result.txt",
        "result.txt",
        b"written by the agent\n",
    )
    container_id = manager.client.containers.get(container_name(bot)).id
    by_id = files.read(
        f"sandbox:{container_id[:10]}//work/out/result.txt", max_bytes=1000
    )
    assert by_id.sandbox == bot and by_id.data == got.data
    for ref, error, message in [
        (f"sandbox:{bot}/out/passwd", NotAFile, "symbolic link to /etc/passwd"),
        (f"sandbox:{bot}/out", NotAFile, "is a folder"),
        (f"sandbox:{bot}/out/nope.txt", NotFound, "/work/out/nope.txt does not exist"),
        (f"sandbox:{bot}-gone/out/result.txt", NotFound, "kt-sandbox ls"),
        (f"sandbox:{bot}/out/big.bin", TooLarge, "is 300000 bytes, over the 1000-byte"),
    ]:
        with pytest.raises(error, match=message):
            files.read(ref, max_bytes=1000)

    # The level cannot be changed on an existing sandbox; the error says how.
    try:
        manager.up(bot, level_name="open", image=image_ref)
    except Exception as exc:
        assert "save it" in str(exc) and "--level open" in str(exc)
    else:
        raise AssertionError("an existing sandbox must keep its level")

    listing = {info.name: info for info in manager.ls()}
    assert listing[lab].level == "open" and listing[bot].level == "strict"
    manager.down(bot)
    stopped = files.read(f"sandbox:{bot}/out/result.txt", max_bytes=1000)
    assert stopped.data == b"written by the agent\n"
    manager.rm(bot, force=True)
    assert bot not in {info.name for info in manager.ls()}

    # Move the saved image through tarballs: export, remove, import, open again.
    plain, packed = tmp_path / "lab.tar", tmp_path / "lab.tar.gz"
    assert manager.export_image(image_ref, plain) == plain.stat().st_size > 0
    assert manager.export_image(image_ref, packed) == packed.stat().st_size
    assert packed.read_bytes()[:2] == b"\x1f\x8b"
    with gzip.open(packed) as unpacked:
        assert unpacked.read(262)[257:262] == b"ustar"
    try:
        manager.export_image(image_ref, packed)
    except ManagerError as exc:
        assert "--force" in str(exc)
    else:
        raise AssertionError("export must not overwrite a file without force")
    assert manager.export_image(image_ref, packed, force=True) > 0

    for tarball in (plain, packed):
        manager.remove_image(image_ref)
        assert image_ref not in [i.reference for i in manager.saved_images()]
        loaded = manager.import_images(tarball)
        assert [(i.reference, i.saved) for i in loaded] == [(image_ref, True)]
        assert image_ref in [i.reference for i in manager.saved_images()]

    manager.up(moved, level_name="strict", image=image_ref)
    carried = await sh(moved, "cat /work/notes.txt; ls /usr/local/marker")
    assert "mine" in carried and "/usr/local/marker" in carried

    # `upgrade` puts this kt-sandbox into a sandbox from an earlier image.
    pre, port = names("pre"), free_port()
    manager.up(pre, level_name="open", image=PRE_IMAGE or image, publish=port)
    box = manager.client.containers.get(container_name(pre))
    box.exec_run(
        [
            "python3",
            "-c",
            "import os; os.makedirs('/work/out', exist_ok=True); "
            "open('/work/out/x.png', 'wb').write(b'\\x89PNG\\r\\n\\x1a\\n' + "
            "os.urandom(300000)); os.symlink('/etc/passwd', '/work/out/passwd')",
        ]
    )
    if PRE_IMAGE:
        assert box.exec_run(["test", "-e", "/usr/local/bin/kt-sandbox-file"])[0] != 0
        serve_http(box)
        assert fetch(port, "out/x.png").status_code == 404
        box.exec_run(["pkill", "-f", "kt_sandbox.server|kt-sandbox-mcp"])
        wait_closed(port)
    stale = "/opt/kt-sandbox/kt_sandbox/stale_module.py"
    box.exec_run(["touch", stale], user="root")
    manager.down(pre)
    assert main(["upgrade", pre]) == 0
    printed = capsys.readouterr().out
    assert f"upgraded {pre}" in printed and "were not checked" in printed
    assert (
        f"docker exec {container_name(pre)} pkill -f 'kt-sandbox-mcp|kt_sandbox.server', then start "
        "it again (stdio servers restart on the next connection)."
    ) in printed
    box.reload()
    assert box.status == "exited"
    manager.up(pre)
    assert box.exec_run(["test", "-e", stale])[0] != 0
    assert main(["upgrade", pre]) == 0
    assert "were not checked" not in capsys.readouterr().out
    serve_http(box)
    png = box.exec_run(["cat", "/work/out/x.png"])[1]
    got = fetch(port, "out/x.png")
    assert got.status_code == 200 and got.content == png and len(png) == 300008
    assert got.headers["x-kt-sandbox-size"] == "300008"
    assert fetch(port, "/work/out/x.png").content == png
    assert fetch(port, "out/x.png", token=None).status_code == 401
    linked = fetch(port, "out/passwd")
    assert linked.status_code == 422 and "symbolic link" in linked.json()["error"]
    assert fetch(port, "out/nope.png").status_code == 404
    code, output = box.exec_run(["kt-sandbox-file", "out/x.png"])
    assert code == 0 and output == png
    assert box.exec_run(["kt-sandbox-file", "out/passwd"])[0] == 4
    assert await mcp_call(pre, "glob", pattern="out/*.png") == "out/x.png"
    assert box.exec_run(["pkill", "-f", "kt-sandbox-mcp"])[0] == 0
    wait_closed(port)

    # A sandbox whose server predates KohakuTerrarium's tools is left alone.
    old = names("old")
    manager.up(old, level_name="open", image=OLD_IMAGE)
    with pytest.raises(ManagerError, match="too old to upgrade in place"):
        manager.upgrade(old)
    old_box = manager.client.containers.get(container_name(old))
    assert old_box.exec_run(["test", "-e", "/usr/local/bin/kt-sandbox-file"])[0] != 0


async def test_allowlist_level_reaches_only_its_hosts_and_isolates_sandboxes(
    manager, names, image
):
    std, other = names("std"), names("oth")
    manager.up(std, level_name="standard", image=image)
    manager.up(
        other, level_name="standard", image=image, overrides={"allow": ["example.org"]}
    )

    # Each sandbox is told its own hosts; its proxy credential is never shown.
    told = await mcp_session(stdio_params(std), instructions_of)
    assert told.splitlines()[1].startswith(
        "Level standard: the network reaches only pypi.org, files.pythonhosted.org, "
        "github.com, raw.githubusercontent.com, through a proxy already set up."
    )
    told_other = await mcp_session(stdio_params(other), instructions_of)
    assert "reaches only example.org, through" in told_other
    env = manager.client.containers.get(container_name(std)).attrs["Config"]["Env"]
    secret = next(
        e.split("=", 1)[1] for e in env if e.startswith("KT_SANDBOX_EGRESS_SECRET=")
    )
    std_about = exec_about(manager, std)
    assert_lines(
        std_about,
        "- Network: only pypi.org, files.pythonhosted.org, github.com, "
        "raw.githubusercontent.com, through the proxy set in HTTP_PROXY and HTTPS_PROXY",
    )
    assert len(secret) >= 20 and secret not in std_about
    assert "kt-sandbox-egress" not in std_about
    assert secret not in await sh(std, "cat ~/.kt-sandbox/about.md")

    reach = await sh(
        std,
        "curl -sS -m 15 -o /dev/null -w 'pypi:%{http_code}\\n' https://pypi.org/simple/ 2>&1 | tail -1",
    )
    assert "pypi:200" in reach
    denied = await sh(
        std,
        "curl -sS -m 10 https://example.com 2>&1 | tail -1; curl -sS -m 10 https://github.com:22 2>&1 | tail -1",
    )
    assert denied.count("response 403") == 2
    assert "response 407" in await sh(
        std,
        "curl -sS -m 10 -x http://kt-sandbox-egress:3128 https://pypi.org 2>&1 | tail -1",
    )
    bypass = await sh(
        std, "curl -sS -m 6 --noproxy '*' https://pypi.org 2>&1 | tail -1"
    )
    assert "Could not resolve host" in bypass
    raw = await py(
        std,
        "import socket\ntry:\n    socket.create_connection(('1.1.1.1', 443), timeout=3); print('CONNECTED')\nexcept OSError as e: print('blocked', e.errno)",
        timeout=10,
    )
    assert "blocked 101" in raw

    pip = await sh(
        std,
        "pip install -q cowsay 2>&1 | tail -1; python -c 'import cowsay; print(\"installed\")'",
        timeout=60,
    )
    assert "installed" in pip

    # Each sandbox has its own hosts, and they cannot see each other.
    own = await sh(
        other,
        "curl -sS -m 10 -o /dev/null -w 'example:%{http_code}\\n' https://example.org 2>&1 | tail -1; curl -sS -m 10 -o /dev/null -w 'pypi:%{http_code}\\n' https://pypi.org 2>&1 | tail -1",
    )
    assert "example:200" in own and "pypi:000" in own
    other_ip = manager.client.containers.get(container_name(other)).attrs[
        "NetworkSettings"
    ]["Networks"][f"kt-sandbox-net-{other}"]["IPAddress"]
    lateral = await py(
        std,
        f"import socket\ntry:\n    socket.create_connection(('{other_ip}', 8765), timeout=3); print('REACHED')\nexcept OSError as e: print('blocked', e.errno)",
        timeout=10,
    )
    assert "blocked" in lateral and "REACHED" not in lateral

    # A restarted sandbox registers with the proxy again and keeps its state.
    manager.down(std)
    manager.up(std, level_name="standard", image=image)
    again = await sh(
        std,
        "curl -sS -m 15 -o /dev/null -w 'pypi:%{http_code}\\n' https://pypi.org 2>&1 | tail -1; python -c 'import cowsay; print(\"state kept\")'",
    )
    assert "pypi:200" in again and "state kept" in again

    # Removing the last allowlist sandbox removes the proxy and the networks.
    manager.rm(std, force=True)
    assert manager.client.containers.get("kt-sandbox-egress") is not None
    manager.rm(other, force=True)
    assert not manager.client.containers.list(
        all=True, filters={"name": "kt-sandbox-egress"}
    )
    assert not manager.client.networks.list(
        names=[f"kt-sandbox-net-{std}", f"kt-sandbox-net-{other}"]
    )
