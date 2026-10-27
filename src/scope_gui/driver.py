"""The only module that talks to the instrument (Constitution Principle I).

Every query sent must match ALLOWED_COMMANDS: read-only queries verified on the WR610Zi
(contracts/scope-driver.md). The one exception is the acquisition control of synchronized capture
(Constitution v2.1.0, Principle III): writes matching CONTROL_COMMANDS (ARM, FRTR and TRMD <mode>
to restore a remembered trigger mode), sent only through _write. The two lists never overlap.
Anything else raises CommandNotAllowed before reaching the wire.
"""

import logging
import re
import socket
import time

import pyvisa
from pyvisa import constants
from pyvisa.errors import VisaIOError

from .errors import (
    CommandNotAllowed,
    ScopeBusy,
    ScopeError,
    ScopeLost,
    ScopeProtocolError,
    ScopeReplyMismatch,
    ScopeTimeout,
    ScopeUnreachable,
)
from .models import (
    CHANNELS,
    AcqState,
    AcquisitionSettings,
    ChannelSettings,
    InstrumentIdentity,
    ScopeStatus,
    TriggerMode,
    Waveform,
    WaveformDescriptor,
)
from .settings import host_of
from .wavedesc import decode_waveform, parse_descriptor, split_block

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

# Acquisition control of synchronized capture: the only commands that may be written, and
# only to arm/force one acquisition or to restore the trigger mode the user had.
CONTROL_COMMANDS = tuple(
    re.compile(pattern) for pattern in (r"ARM", r"FRTR", r"TRMD (?:AUTO|NORM|SINGLE|STOP)")
)

QUERY_TIMEOUT_MS = 3000
RECOVER_TIMEOUT_MS = 1500
WAVEFORM_TIMEOUT_BASE_MS = 2000
WAVEFORM_TIMEOUT_MAX_MS = 10000
VXI11_PORT = 111
DEFAULT_WFSU = "SP,0,NP,0,FP,0,SN,0"

_BUSY_CODES = {
    constants.StatusCode.error_resource_busy,
    constants.StatusCode.error_resource_locked,
}

_UNITS = {"V", "S", "SAMPLE", "SAMPLES", "HZ"}

# Long header names used when CHDR is LONG (contracts/scope-driver.md "Reply validation").
_LONG_NAMES = {
    "TRA": "TRACE",
    "VDIV": "VOLT_DIV",
    "OFST": "OFFSET",
    "CPL": "COUPLING",
    "TDIV": "TIME_DIV",
    "TRDL": "TRIG_DELAY",
    "TRMD": "TRIG_MODE",
    "CHDR": "COMM_HEADER",
    "CFMT": "COMM_FORMAT",
    "CORD": "COMM_ORDER",
    "WFSU": "WAVEFORM_SETUP",
    "WF": "WAVEFORM",
}


def is_allowed(command: str) -> bool:
    return any(pattern.fullmatch(command) for pattern in ALLOWED_COMMANDS)


def is_control_allowed(command: str) -> bool:
    return any(pattern.fullmatch(command) for pattern in CONTROL_COMMANDS)


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


def expected_headers(command: str) -> set[str]:
    """Reply headers accepted for a query: ``C1:VDIV?`` -> {``C1:VDIV``, ``C1:VOLT_DIV``}."""
    head = command.split()[0].rstrip("?").upper()
    prefix, _, name = head.rpartition(":")
    prefix = prefix + ":" if prefix else ""
    return {prefix + name, prefix + _LONG_NAMES.get(name, name)}


def reply_matches(command: str, reply: bytes | str, header_mode: str) -> bool:
    """True if ``reply`` answers ``command`` (FR-021, research R13).

    Text replies are checked by their header (impossible with ``CHDR OFF``); binary replies
    (``WF?``) must start with ``Cn:WF DESC,`` / ``Cn:WF ALL,`` or, with ``CHDR OFF``, ``DESC,`` /
    ``ALL,`` (as the WR610Zi sends) or ``#``.
    """
    binary = isinstance(reply, bytes)
    text = reply[:40].decode("ascii", "replace") if binary else reply
    if header_mode == "OFF":
        if not binary:
            return True
        kind, comma, _ = text.partition(",")
        return text.startswith("#") or bool(comma) and kind.upper() == command.split()[1].upper()
    tokens = text.replace(",", " ", 1).split() if binary else text.split()
    if not tokens or tokens[0].upper() not in expected_headers(command):
        return False
    if binary:  # "C1:WF DESC,#9..." -> second token must be the requested block
        return len(tokens) > 1 and tokens[1].upper() == command.split()[1].upper()
    return True


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


def waveform_timeout_ms(expected_bytes: int) -> int:
    """2 s plus 1 ms per KB, capped at 10 s (research R8)."""
    return min(WAVEFORM_TIMEOUT_BASE_MS + expected_bytes // 1000, WAVEFORM_TIMEOUT_MAX_MS)


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
        self._expected_bytes: dict[str, int] = {}
        self._header_mode = "SHORT"  # CHDR as read at connect; decides reply validation

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
            # The header mode is not known yet: CHDR? decides how replies are validated.
            self._header_mode = "UNKNOWN"
            idn = self._query("*IDN?")
            # "*IDN LECROY,..." or, with CHDR OFF, "LECROY,..." (no header before the first comma)
            if not idn.upper().startswith("*IDN") and " " in idn.split(",")[0]:
                self._mismatch("*IDN?", idn)
            identity = parse_identity(idn)
            log.info("connected to %s", identity)
            # Read (never write) the remote-interface setup shared with other clients (R3).
            chdr = self._query("CHDR?")
            mode = parse_value(chdr).upper()
            headed = len(chdr.split()) > 1
            if mode not in ("SHORT", "LONG", "OFF") or (
                headed and not reply_matches("CHDR?", chdr, "SHORT")
            ):
                self._mismatch("CHDR?", chdr)
            self._header_mode = "OFF" if mode == "OFF" else "SHORT"
            if self._header_mode == "OFF":
                log.warning("CHDR is OFF: text replies cannot be checked against their query")
            setup = {"CHDR?": chdr}
            setup.update({cmd: self._query(cmd) for cmd in ("CFMT?", "CORD?", "WFSU?")})
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

    # --- live data ---------------------------------------------------------------------------
    def read_status(self) -> ScopeStatus:
        """Channel and acquisition settings; acq_state is STOPPED or ACQUIRING (worker refines)."""
        try:
            channels = tuple(
                ChannelSettings(
                    name=ch,
                    enabled=parse_value(self._query(f"{ch}:TRA?")).upper() == "ON",
                    volts_per_div=parse_float(self._query(f"{ch}:VDIV?")),
                    offset=parse_float(self._query(f"{ch}:OFST?")),
                    coupling=parse_value(self._query(f"{ch}:CPL?")),
                )
                for ch in CHANNELS
            )
            mode = self._trigger_mode()
            acquisition = AcquisitionSettings(
                time_per_div=parse_float(self._query("TDIV?")),
                trigger_delay=parse_float(self._query("TRDL?")),
                trigger_mode=mode,
                grid_mode=parse_value(self._query("GRID?")),
            )
        except (ValueError, KeyError) as exc:
            raise ScopeProtocolError(f"unexpected setting reply: {exc}") from exc
        state = AcqState.STOPPED if mode is TriggerMode.STOP else AcqState.ACQUIRING
        return ScopeStatus(channels, acquisition, state, time.monotonic())

    def read_trigger_mode(self) -> TriggerMode:
        """Current trigger mode (read-only ``TRMD?``)."""
        try:
            return self._trigger_mode()
        except (ValueError, KeyError) as exc:
            raise ScopeProtocolError(f"unexpected trigger mode reply: {exc}") from exc

    # --- acquisition control (synchronized capture only) -------------------------------------
    def arm(self) -> None:
        """Arm one acquisition (``ARM``); the scope stops after the next trigger."""
        self._write("ARM")

    def force_trigger(self) -> None:
        """Force the armed acquisition to trigger now (``FRTR``)."""
        self._write("FRTR")

    def restore_trigger_mode(self, mode: TriggerMode) -> None:
        """Put the trigger mode back to ``mode`` and confirm it with ``TRMD?``."""
        self._write(f"TRMD {mode.name}")
        actual = self.read_trigger_mode()
        # A restored Single re-arms; it may trigger and stop before the check.
        done_single = mode is TriggerMode.SINGLE and actual is TriggerMode.STOP
        if actual is not mode and not done_single:
            raise ScopeProtocolError(f"trigger mode is {actual.value}, expected {mode.value}")
        log.info("trigger mode restored to %s", mode.value)

    def read_descriptor(self, channel: str) -> WaveformDescriptor:
        command = f"{channel}:WF? DESC"
        desc = parse_descriptor(split_block(self._query_raw(command)))
        self._check_source(command, desc)
        self._expected_bytes[channel] = desc.data_offset + desc.point_count * desc.bytes_per_sample
        return desc

    def read_waveform(self, channel: str) -> Waveform:
        timeout = waveform_timeout_ms(self._expected_bytes.get(channel, 0))
        command = f"{channel}:WF? ALL"
        desc, volts = decode_waveform(self._query_raw(command, timeout))
        self._check_source(command, desc)
        self._expected_bytes[channel] = desc.data_offset + desc.point_count * desc.bytes_per_sample
        return Waveform(
            channel=channel,
            volts=volts,
            t0=desc.horiz_offset,
            dt=desc.horiz_interval,
            trigger_time=desc.trigger_time,
            received_at=time.monotonic(),
            step=desc.vertical_gain,
        )

    # --- low level ---------------------------------------------------------------------------
    def _check(self, command: str) -> None:
        if not is_allowed(command):
            raise CommandNotAllowed(f"refusing to send non-allowlisted command {command!r}")
        if self._resource is None:
            raise ScopeError("not connected")

    def _trigger_mode(self) -> TriggerMode:
        return TriggerMode[parse_value(self._query("TRMD?")).upper()]

    def _check_source(self, command: str, desc: WaveformDescriptor) -> None:
        if desc.source != command.split(":")[0]:
            self._mismatch(command, f"waveform of {desc.source}")

    def _mismatch(self, command: str, reply: bytes | str) -> None:
        """Flush the shared reply queue and refuse the reply (FR-021)."""
        shown = reply[:40] if isinstance(reply, bytes) else reply[:60]
        log.warning("reply to %s does not match the query: %r", command, shown)
        try:
            self._resource.clear()
        except Exception as exc:
            log.debug("clear after mismatch: %s", exc)
        raise ScopeReplyMismatch(f"reply to {command!r} belongs to another query")

    def _validate(self, command: str, reply: bytes | str) -> None:
        if self._header_mode == "UNKNOWN":  # during connect, checked in connect()
            return
        if not reply_matches(command, reply, self._header_mode):
            self._mismatch(command, reply)

    def _query(self, command: str) -> str:
        self._check(command)
        log.debug("query %s", command)
        try:
            self._resource.timeout = QUERY_TIMEOUT_MS
            reply = self._resource.query(command).strip()
        except VisaIOError as exc:
            raise map_visa_error(exc, command) from exc
        except OSError as exc:  # socket reset/aborted (e.g. cable unplugged), raised by pyvisa-py
            log.warning("%s: network error %s", command, exc)
            raise ScopeLost("network link to the scope was interrupted") from exc
        log.debug("reply %s", reply)
        self._validate(command, reply)
        return reply

    def _write(self, command: str) -> None:
        """Send an allowlisted control command and read nothing (the scope does not reply)."""
        if not is_control_allowed(command):
            raise CommandNotAllowed(f"refusing to send non-allowlisted command {command!r}")
        if self._resource is None:
            raise ScopeError("not connected")
        log.debug("write %s", command)
        try:
            self._resource.timeout = QUERY_TIMEOUT_MS
            self._resource.write(command)
        except VisaIOError as exc:
            raise map_visa_error(exc, command) from exc
        except OSError as exc:  # socket reset/aborted (e.g. cable unplugged), raised by pyvisa-py
            log.warning("%s: network error %s", command, exc)
            raise ScopeLost("network link to the scope was interrupted") from exc

    def _query_raw(self, command: str, timeout_ms: int = QUERY_TIMEOUT_MS) -> bytes:
        self._check(command)
        log.debug("query %s (binary, timeout %d ms)", command, timeout_ms)
        try:
            self._resource.timeout = timeout_ms
            self._resource.write(command)
            reply = self._resource.read_raw()
        except VisaIOError as exc:
            raise map_visa_error(exc, command) from exc
        except OSError as exc:  # socket reset/aborted (e.g. cable unplugged), raised by pyvisa-py
            log.warning("%s: network error %s", command, exc)
            raise ScopeLost("network link to the scope was interrupted") from exc
        self._validate(command, reply)
        return reply
