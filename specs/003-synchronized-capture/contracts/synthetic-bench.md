# Contract: Synthetic scope as a running WR610Zi (test-only)

Extends [002 synthetic-bench contract](../../002-waveform-analysis/contracts/synthetic-bench.md).
Lives in `tests/synthetic_scope.py`; never reachable from `src/` (existing test).

```python
SyntheticScope(scene=None, rate_hz=20.0, seed=None, trigger_mode="NORM", triggers=True,
               on_demand=False)
```

Behaviour (R11):

1. `AUTO`/`NORM`: the newest acquisition advances with time at `rate_hz`; each `Cn:WF?` returns
   the newest one (generated lazily; skipped ones only advance the trigger time). Two transfers
   further apart than `1/rate_hz` return different trigger times.
2. `ARM`: `trigger_mode = "SINGLE"` until the next trigger is due (immediately on `FRTR`), then a
   new acquisition is held and `trigger_mode = "STOP"`. With `triggers=False`, only `FRTR`
   completes it. `FRTR` while not armed does nothing.
3. `STOP`: no new acquisitions; every transfer returns the held one.
4. `TRMD <AUTO|NORM|SINGLE|STOP>` sets the mode (`SINGLE` arms like `ARM`); `TRMD?` answers it.
5. Every command is recorded in `sent`; control commands also in `controls`.
6. `on_demand=True` keeps the 002 behaviour (a new acquisition on every `WF? DESC`, paced to
   `rate_hz`, ignoring the trigger mode) for existing tests that need one deterministic
   acquisition per update; it is not a model of the scope.
7. The bench launcher (`tests/bench.py`) starts in `AUTO`, so the mixed-trigger warning and the
   switch can be demonstrated.
