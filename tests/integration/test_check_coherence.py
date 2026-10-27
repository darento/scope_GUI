"""The channel coherence check used to debug phase jumps on the real scope."""

import check_coherence
import pytest
from synthetic_scope import Scene, SyntheticScope, synthetic_factory

from scope_gui import driver as driver_module
from scope_gui.driver import ScopeDriver, is_allowed


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(driver_module, "tcp_precheck", lambda host, timeout=3.0: None)


def bench_driver(**kwargs) -> tuple[ScopeDriver, SyntheticScope]:
    kwargs = {"on_demand": True, **kwargs}
    scope = SyntheticScope(Scene(points=2000), rate_hz=1000, seed=3, **kwargs)
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


def test_reads_spanning_triggers_are_flagged(capsys):
    driver, scope = bench_driver(on_demand=False, trigger_mode="AUTO")
    now = [0.0]

    def clock():  # every transfer takes 2 ms: a new trigger (1 ms apart) between two reads
        now[0] += 2e-3
        return now[0]

    scope.clock = clock
    scope._origin = 0.0
    assert check_coherence.main(["--reads", "2"], driver) == 1
    out = capsys.readouterr().out
    assert out.count("<-- different triggers") == 2
    assert "0 of 2 reads" in out
