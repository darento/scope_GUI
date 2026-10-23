"""The only module that talks to the instrument (Constitution Principle I).

Every command sent must match ALLOWED_COMMANDS: read-only queries verified on the WR610Zi
(contracts/scope-driver.md). Anything else raises CommandNotAllowed before reaching the wire.
"""

import logging
import re

import pyvisa
from pyvisa import constants
from pyvisa.errors import VisaIOError

from .errors import CommandNotAllowed, ScopeBusy, ScopeError, ScopeTimeout

log = logging.getLogger(__name__)

_CH = r"C[1-4]"
ALLOWED_COMMANDS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\*IDN\?",
        r"CHDR\?",
        r"CFMT\?",
        r"CORD\?",
        r"WFSU\?",
        rf"{_CH}:TRA\?",
        rf"{_CH}:VDIV\?",
        rf"{_CH}:OFST\?",
        rf"{_CH}:CPL\?",
        r"TDIV\?",
        r"TRDL\?",
        r"TRMD\?",
        r"GRID\?",
        rf"{_CH}:WF\? DESC",
        rf"{_CH}:WF\? ALL",
    )
)

QUERY_TIMEOUT_MS = 3000

_BUSY_CODES = {
    constants.StatusCode.error_resource_busy,
    constants.StatusCode.error_resource_locked,
}

_UNITS = {"V", "S", "SAMPLE", "SAMPLES", "HZ"}


def is_allowed(command: str) -> bool:
    return any(pattern.fullmatch(command) for pattern in ALLOWED_COMMANDS)


def parse_value(reply: str) -> str:
    """Value part of a reply, whatever the CHDR mode (SHORT, LONG or OFF); units removed.

    ``C1:VDIV 1 V`` -> ``1``; ``1 V`` -> ``1``; ``TRMD AUTO`` -> ``AUTO``;
    ``CFMT DEF9,BYTE,BIN`` -> ``DEF9,BYTE,BIN``.
    """
    tokens = reply.strip().split()
    if tokens and tokens[-1].upper() in _UNITS:
        tokens = tokens[:-1]
    if not tokens:
        raise ValueError(f"empty reply {reply!r}")
    return tokens[-1]


def parse_float(reply: str) -> float:
    return float(parse_value(reply))


def _default_factory(address: str, timeout_ms: int):
    rm = pyvisa.ResourceManager("@py")
    return rm.open_resource(address, timeout=timeout_ms)


def map_visa_error(exc: VisaIOError, command: str) -> ScopeError:
    if exc.error_code == constants.StatusCode.error_timeout:
        return ScopeTimeout(f"no reply to {command!r} (timeout)")
    if exc.error_code in _BUSY_CODES:
        return ScopeBusy("instrument busy or locked by another client")
    return ScopeError(f"{command!r} failed: {exc.description}")


class ScopeDriver:
    def __init__(self, resource_factory=None) -> None:
        self._factory = resource_factory or _default_factory
        self._resource = None

    @property
    def is_open(self) -> bool:
        return self._resource is not None

    # --- low level ---------------------------------------------------------------------------
    def _check(self, command: str) -> None:
        if not is_allowed(command):
            raise CommandNotAllowed(f"refusing to send non-allowlisted command {command!r}")
        if self._resource is None:
            raise ScopeError("not connected")

    def _query(self, command: str) -> str:
        self._check(command)
        log.debug("query %s", command)
        try:
            self._resource.timeout = QUERY_TIMEOUT_MS
            reply = self._resource.query(command).strip()
        except VisaIOError as exc:
            raise map_visa_error(exc, command) from exc
        log.debug("reply %s", reply)
        return reply

    def _query_raw(self, command: str, timeout_ms: int = QUERY_TIMEOUT_MS) -> bytes:
        self._check(command)
        log.debug("query %s (binary, timeout %d ms)", command, timeout_ms)
        try:
            self._resource.timeout = timeout_ms
            self._resource.write(command)
            return self._resource.read_raw()
        except VisaIOError as exc:
            raise map_visa_error(exc, command) from exc
