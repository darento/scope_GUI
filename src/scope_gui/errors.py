"""Errors raised by the scope driver."""


class ScopeError(Exception):
    """Base class for all instrument communication errors."""


class ScopeUnreachable(ScopeError):
    """No instrument answered at the given address."""


class ScopeBusy(ScopeError):
    """The instrument is locked or busy serving another client."""


class ScopeTimeout(ScopeError):
    """The instrument did not answer in time."""


class ScopeProtocolError(ScopeError):
    """A reply or waveform block could not be parsed."""


class ScopeLost(ScopeError):
    """The connection was lost and could not be recovered."""


class CommandNotAllowed(ScopeError):
    """A command outside the read-only allowlist was about to be sent."""


class ScopeReplyMismatch(ScopeProtocolError):
    """A reply belongs to another query (another remote client shares the scope, R13)."""
