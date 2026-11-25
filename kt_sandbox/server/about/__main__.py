"""``python -m kt_sandbox.server.about``: the same entry point as ``kt-sandbox-about``."""

from kt_sandbox.server.about.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
