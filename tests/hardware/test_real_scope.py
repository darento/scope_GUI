"""Tests against the real scope (read-only). Run with: uv run pytest -m hardware"""

import logging

import pytest

from scope_gui import driver as driver_module
from scope_gui.driver import ScopeDriver, is_allowed
from scope_gui.models import ConnectionState, InstrumentSupport
from scope_gui.settings import to_visa_resource
from scope_gui.worker import AcquisitionWorker

pytestmark = pytest.mark.hardware

log = logging.getLogger(__name__)

SETTING_QUERIES = [
    "CHDR?", "CFMT?", "CORD?", "WFSU?", "TDIV?", "TRDL?", "TRMD?", "GRID?",
    *[f"{ch}:{q}" for ch in ("C1", "C2", "C3", "C4") for q in ("TRA?", "VDIV?", "OFST?", "CPL?")],
]  # fmt: skip


class RecordingResource:
    """Wraps the real VISA resource and records every command written."""

    def __init__(self, resource, sent):
        self._resource, self._sent = resource, sent

    def write(self, command):
        self._sent.append(command)
        return self._resource.write(command)

    def query(self, command):
        self._sent.append(command)
        return self._resource.query(command)

    def __getattr__(self, name):
        return getattr(self._resource, name)

    def __setattr__(self, name, value):
        if name in ("_resource", "_sent"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._resource, name, value)


def snapshot(address):
    driver = ScopeDriver()
    try:
        driver.connect(address)
        return {q: driver._query(q) for q in SETTING_QUERIES}
    finally:
        driver.close()


def test_identity(scope_address):
    driver = ScopeDriver()
    try:
        identity = driver.connect(to_visa_resource(scope_address))
        assert identity.manufacturer == "LECROY"
        assert identity.model == "WR610ZI"
        assert identity.support is InstrumentSupport.SUPPORTED
    finally:
        driver.close()


def test_live_read_only(scope_address, live_seconds, qtbot):
    """SC-005 / FR-018: a live session leaves every scope setting unchanged."""
    address = to_visa_resource(scope_address)
    before = snapshot(address)
    sent: list[str] = []

    def factory():
        return ScopeDriver(
            resource_factory=lambda a, t: RecordingResource(
                driver_module._default_factory(a, t), sent
            )
        )

    worker = AcquisitionWorker(factory)
    received: list[dict] = []
    rates: list[float] = []
    statuses = []
    worker.waveforms_updated.connect(received.append)
    worker.waveforms_updated.connect(lambda _w: worker.waveforms_consumed())
    worker.rate_updated.connect(rates.append)
    worker.status_updated.connect(statuses.append)
    worker.connect_to(scope_address)
    assert worker.state is ConnectionState.CONNECTED
    try:
        qtbot.wait(live_seconds * 1000)
        assert worker.state is ConnectionState.CONNECTED
    finally:
        worker.close_connection()
    after = snapshot(address)

    assert after == before
    assert sent and all(is_allowed(cmd) for cmd in sent), sorted(set(sent))
    enabled = statuses[-1].enabled_channels
    assert received, "no waveform received"
    assert set(received[-1]) == set(enabled)
    rate = max(rates) if rates else 0.0
    points = received[-1][enabled[0]].volts.size
    log.warning("live rate %.2f updates/s, %d channels x %d points", rate, len(enabled), points)
    print(f"\nlive rate {rate:.2f} updates/s with {len(enabled)} channels x {points} points")


def test_analysis_session_read_only(scope_address, live_seconds, qtbot):
    """SC-007 / FR-020: a session using every analysis tool sends only allowlisted queries."""
    from scope_gui.analysis import Kind, Level, MeasurementSpec
    from scope_gui.ui.main_window import MainWindow

    address = to_visa_resource(scope_address)
    before = snapshot(address)
    sent: list[str] = []

    def factory():
        return ScopeDriver(
            resource_factory=lambda a, t: RecordingResource(
                driver_module._default_factory(a, t), sent
            )
        )

    window = MainWindow(scope_address, driver_factory=factory)
    qtbot.addWidget(window)
    window.show()
    panel = window.measurements_panel
    kinds = [
        Kind.AMPLITUDE, Kind.BASE, Kind.TOP, Kind.MAXIMUM, Kind.MINIMUM,
        Kind.MEAN, Kind.AREA, Kind.RISE_TIME, Kind.FREQUENCY,
    ]  # fmt: skip
    for kind in kinds:
        panel.add(MeasurementSpec(kind, "C1"))
    panel.add(MeasurementSpec(Kind.DELTA_T, "C1", Level(0.5, True), "C1", Level(0.5, True)))
    window.side_panel.cursors_checkbox.setChecked(True)
    panel.set_gate_between_cursors(True)
    window.side_panel.persistence_combo.setCurrentText("100")
    try:
        window.connection_bar.button.click()
        qtbot.waitUntil(lambda: window._state is ConnectionState.CONNECTED, timeout=10000)
        qtbot.wait(live_seconds * 1000)
        assert window._state is ConnectionState.CONNECTED
        assert panel.trigger_log.size > 0
    finally:
        window.close()
    after = snapshot(address)

    assert after == before
    assert sent and all(is_allowed(cmd) for cmd in sent), sorted(set(sent))
    rate = window.view.update_rate_hz
    print(f"\nanalysis session: {panel.trigger_log.size} acquisitions measured, {rate:.2f}/s")
