"""Persistent user settings and well-known paths."""

import json
import logging
import os
import re
from pathlib import Path

from PySide6.QtCore import QSettings

from .analysis import MeasurementSpec

log = logging.getLogger(__name__)

DEFAULT_ADDRESS = "192.168.0.9"
_ADDRESS_KEY = "connection/last_address"
_MEASUREMENTS_KEY = "analysis/measurements"
_VISA_RE = re.compile(r"^TCPIP\d*::([^:]+)::", re.IGNORECASE)


def _settings() -> QSettings:
    return QSettings("scope_gui", "scope_gui")


def load_last_address() -> str:
    value = _settings().value(_ADDRESS_KEY, DEFAULT_ADDRESS)
    return str(value) if value else DEFAULT_ADDRESS


def save_last_address(address: str) -> None:
    _settings().setValue(_ADDRESS_KEY, address.strip())


def load_measurements() -> list[MeasurementSpec]:
    """Measurement definitions of the last session; invalid entries are skipped (research R12)."""
    text = _settings().value(_MEASUREMENTS_KEY, "")
    if not text:
        return []
    try:
        entries = json.loads(str(text))
    except json.JSONDecodeError:
        log.warning("ignoring unreadable measurement list in settings")
        return []
    specs = []
    for entry in entries if isinstance(entries, list) else []:
        try:
            specs.append(MeasurementSpec.from_dict(entry))
        except (KeyError, ValueError, TypeError) as exc:
            log.warning("skipping invalid measurement %r: %s", entry, exc)
    return specs


def save_measurements(specs: list[MeasurementSpec]) -> None:
    _settings().setValue(
        _MEASUREMENTS_KEY, json.dumps([spec.to_dict() for spec in specs], ensure_ascii=False)
    )


def to_visa_resource(address: str) -> str:
    """IP or hostname -> VXI-11 VISA resource string; full VISA strings pass through."""
    address = address.strip()
    if not address:
        raise ValueError("Enter the scope's IP address or hostname")
    if address.upper().startswith("TCPIP"):
        return address
    return f"TCPIP0::{address}::inst0::INSTR"


def host_of(resource: str) -> str:
    match = _VISA_RE.match(resource)
    return match.group(1) if match else resource


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    path = Path(base) / "scope_gui" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
