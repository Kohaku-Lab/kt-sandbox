"""Typed errors; every failure kt-sandbox reports derives from :class:`SandboxError`."""


class SandboxError(Exception):
    """Base class of every kt-sandbox failure."""


class LevelError(SandboxError, ValueError):
    """A security level name or setting is unknown or inconsistent."""


class ManagerError(SandboxError):
    """The manager could not do what was asked of Docker."""


class NotFound(SandboxError, LookupError):
    """A sandbox, image or file does not exist."""


class BadReference(SandboxError, ValueError):
    """A ``sandbox:<name>/<path>`` file reference is malformed."""


class NotAFile(SandboxError):
    """A sandbox path names a folder, a symbolic link or a special file."""


class TooLarge(SandboxError):
    """A sandbox file is larger than the caller accepts."""
