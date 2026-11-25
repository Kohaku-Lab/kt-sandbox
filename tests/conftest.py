"""Test-wide setup: KohakuTerrarium, imported by the server tests, writes its logs under a temporary folder."""

import os
import tempfile

os.environ.setdefault("KT_CONFIG_DIR", tempfile.mkdtemp(prefix="kt-sandbox-tests-"))
