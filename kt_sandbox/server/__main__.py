"""``python -m kt_sandbox.server``: the same entry point as ``kt-sandbox-mcp``."""

from kt_sandbox.server.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
