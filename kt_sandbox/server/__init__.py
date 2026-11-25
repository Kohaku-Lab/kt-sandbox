"""The MCP server that runs inside a sandbox: KohakuTerrarium's file and shell tools.

It knows nothing about Docker or the host. How a client reaches it (stdio
through ``docker exec -i``, HTTP on a published port, anything else) is up to
whoever opens the sandbox. Limits come from environment variables the manager
sets when it opens the sandbox.
"""

import os
import tempfile
from pathlib import Path

# KohakuTerrarium opens a log file under its config folder when its tools are
# imported; the server keeps that out of the sandbox user's home.
KT_LOG_HOME = str(Path(tempfile.gettempdir()) / "kt-sandbox-mcp")
os.environ.setdefault("KT_CONFIG_DIR", KT_LOG_HOME)
