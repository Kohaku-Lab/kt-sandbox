"""The one error the ``sandbox.files`` plugin raises; its message is shown to the model as the tool result."""


class SandboxFileError(Exception):
    """A sandbox file cannot be named, found or fetched; the message says what to do."""


def upgrade_message(sandbox: str | None) -> str:
    """The message for a sandbox whose server predates the file route."""
    name = sandbox or "<sandbox>"
    return (
        "this sandbox's server has no file route: run "
        f"`kt-sandbox upgrade {name}` on its host and restart the server"
    )
