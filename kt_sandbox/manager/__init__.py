"""The manager: opens, stops, saves and reopens sandboxes through the Docker API.

``options`` turns a level into container settings (pure, no Docker needed);
``sandboxes`` is the user-facing operations; ``docker/`` holds the Docker
calls; ``builder`` builds the sandbox image from tiers.
"""
