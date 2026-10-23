"""Persistent user settings and well-known paths."""

import os
import re
from pathlib import Path

from PySide6.QtCore import QSettings

DEFAULT_ADDRESS = "192.168.0.9"
_ADDRESS_KEY = "connection/last_address"
_VISA_RE = re.compile(r"^TCPIP\d*::([^:]+)::", re.IGNORECASE)


def _settings() -> QSettings:
    return QSettings("scope_gui", "scope_gui")


def load_last_address() -> str:
    value = _settings().value(_ADDRESS_KEY, DEFAULT_ADDRESS)
    return str(value) if value else DEFAULT_ADDRESS


def save_last_address(address: str) -> None:
    _settings().setValue(_ADDRESS_KEY, address.strip())


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
