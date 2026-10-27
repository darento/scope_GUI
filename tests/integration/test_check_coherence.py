"""The channel coherence check used to debug phase jumps on the real scope."""

from dataclasses import replace

import check_coherence
import pytest
from synthetic_scope import Scene, SyntheticScope, synthetic_factory

from scope_gui import driver as driver_module
from scope_gui.driver import ScopeDriver, is_allowed


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(driver_module, "tcp_precheck", lambda host, timeout=3.0: None)


def bench_driver() -> tuple[ScopeDriver, SyntheticScope]:
    scope = SyntheticScope(Scene(points=2000), rate_hz=1000, seed=3)
    driver = ScopeDriver(synthetic_factory(scope))
    driver.connect("TCPIP0::synthetic::inst0::INSTR")
    return driver, scope


def test_bench_reads_are_coherent(capsys):
    driver, scope = bench_driver()
    assert check_coherence.main(["--reads", "3"], driver) == 0
    out = capsys.readouterr().out
    assert "3 of 3 reads had every channel from the same trigger" in out
    assert "different triggers" not in out
    assert [c for c in scope.sent if not is_allowed(c)] == []


def test_reads_spanning_triggers_are_flagged(capsys, monkeypatch):
    driver, _ = bench_driver()
    read = driver.read_waveform

    def later_trigger_after_c1(channel):  # what a running scope does between two transfers
        waveform = read(channel)
        late = channel != "C1"
        return replace(waveform, trigger_time=waveform.trigger_time + late * 1e-3)

    monkeypatch.setattr(driver, "read_waveform", later_trigger_after_c1)
    assert check_coherence.main(["--reads", "2"], driver) == 1
    out = capsys.readouterr().out
    assert out.count("<-- different triggers") == 2
    assert "0 of 2 reads" in out
