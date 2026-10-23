"""The only module that talks to the instrument (Constitution Principle I).

Every command sent must match ALLOWED_COMMANDS: read-only queries verified on the WR610Zi
(contracts/scope-driver.md). Anything else raises CommandNotAllowed before reaching the wire.
"""

import logging
import re
import socket

import pyvisa
from pyvisa import constants
from pyvisa.errors import VisaIOError

from .errors import CommandNotAllowed, ScopeBusy, ScopeError, ScopeTimeout, ScopeUnreachable
from .models import InstrumentIdentity
from .settings import host_of

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
RECOVER_TIMEOUT_MS = 1500
VXI11_PORT = 111
DEFAULT_WFSU = "SP,0,NP,0,FP,0,SN,0"

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


def tcp_precheck(host: str, timeout: float = 3.0) -> None:
    """Fail fast when nothing answers on the VXI-11 portmapper (research R8)."""
    try:
        with socket.create_connection((host, VXI11_PORT), timeout=timeout):
            pass
    except OSError as exc:
        raise ScopeUnreachable(f"Instrument not reachable at {host}") from exc


def parse_identity(reply: str) -> InstrumentIdentity:
    # "*IDN LECROY,WR610ZI,LCRY3201N55990,9.1.0" (header optional)
    body = reply.strip()
    if body.upper().startswith("*IDN"):
        body = body[4:].strip()
    fields = [f.strip() for f in body.split(",")]
    if len(fields) < 4:
        raise ScopeError(f"unexpected identity reply {reply!r}")
    return InstrumentIdentity(*fields[:4])


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

    # --- connection --------------------------------------------------------------------------
    def connect(self, address: str) -> InstrumentIdentity:
        """Open the VXI-11 link and identify the instrument. Sends queries only."""
        tcp_precheck(host_of(address))
        log.info("opening %s", address)
        try:
            self._resource = self._factory(address, QUERY_TIMEOUT_MS)
        except VisaIOError as exc:
            raise map_visa_error(exc, "open") from exc
        try:
            identity = parse_identity(self._query("*IDN?"))
            log.info("connected to %s", identity)
            # Read (never write) the remote-interface setup shared with other clients (R3).
            setup = {cmd: self._query(cmd) for cmd in ("CHDR?", "CFMT?", "CORD?", "WFSU?")}
            for command, reply in setup.items():
                log.info("%s -> %s", command, reply)
            wfsu = parse_value(setup["WFSU?"])
            if wfsu.upper() != DEFAULT_WFSU:
                log.warning("WFSU is %s (not %s): transfers may be sparse", wfsu, DEFAULT_WFSU)
        except Exception:
            self.close()
            raise
        return identity

    def close(self) -> None:
        resource, self._resource = self._resource, None
        if resource is None:
            return
        try:
            resource.close()
            log.info("connection closed")
        except Exception as exc:  # closing an already broken link must never fail
            log.debug("close: %s", exc)

    def recover(self) -> bool:
        """Device clear + identity check; True if the link answers again (research R4)."""
        resource = self._resource
        if resource is None:
            return False
        try:
            resource.clear()
            self._check("*IDN?")
            log.debug("query *IDN? (recover)")
            resource.timeout = RECOVER_TIMEOUT_MS
            resource.query("*IDN?")
            log.info("link recovered")
            return True
        except Exception as exc:
            log.warning("recover failed: %s", exc)
            return False

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
