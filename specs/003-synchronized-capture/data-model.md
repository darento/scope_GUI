# Data Model: Synchronized Capture

## Synchronized capture session (worker, `worker.py`)

| Field | Type | Notes |
|---|---|---|
| `on` | bool | Off at start and after every connect (FR-001) |
| `restore_mode` | `TriggerMode` | Read with `TRMD?` when switched on (R5) |
| `phase` | `IDLE` / `ARMED` | `IDLE`: next cycle arms (when the GUI consumed the last update and the view is not paused); `ARMED`: polling `TRMD?` |
| `armed_at` | monotonic s | For forcing (Auto, 0.5 s, R4) and "Waiting for trigger" (1 s) |
| `forced` | bool | `FRTR` already sent for this arm |
| `armed_count`, `forced_count` | int | Logged when the session ends (FR-007) |

State transitions:

```text
OFF --switch on (TRMD? read -> restore_mode)--> ON/IDLE
ON/IDLE --GUI consumed, not paused: ARM, read status (its TRMD? is the first poll)--> ON/ARMED
ON/ARMED --TRMD? = SINGLE, Auto, >0.5 s, not forced: FRTR--> ON/ARMED
ON/ARMED --TRMD? = STOP: read all channels, emit--> ON/IDLE
ON/ARMED or ON/IDLE --TRMD? = AUTO/NORM (external)--> OFF (no restore, user told)
ON/* --switch off | disconnect | shutdown: TRMD <restore_mode>, TRMD? check--> OFF
ON/* --link lost | conflict--> OFF (cannot restore; user told the mode to set back)
```

Validation rules:

- Only `ARM`, `FRTR` and `TRMD <restore_mode>` are ever written (contract
  [driver-control.md](contracts/driver-control.md)).
- `FRTR` only when `restore_mode` is `AUTO`, at most once per arm.
- While on, the emitted `ScopeStatus.acquisition.trigger_mode` is `restore_mode` (R7);
  `acq_state` is `ACQUIRING`, or `WAITING_FOR_TRIGGER` after 1 s armed.

## Update coherence (GUI)

| Field | Where | Notes |
|---|---|---|
| `coherent` | computed per displayed update | all channels' `trigger_time` equal (R9); always true for one channel |
| coherence log | `MeasurementsPanel` | one flag per accumulated acquisition, aligned with the trigger-time log; cleared with the statistics |

Rules:

- `MeasurementSpec.channels`: `{source}` or, for Δt, `{source, source2}`.
- Mixed update: every spec with more than one channel records NaN (missed); others measure as
  usual (FR-015).
- Correlation of specs A and B: pairs from mixed acquisitions are dropped when
  `A.channels ∪ B.channels` has more than one channel (R10).

## Synthetic scope additions (`tests/synthetic_scope.py`)

| Field | Notes |
|---|---|
| `trigger_mode` | `AUTO`/`NORM`/`SINGLE`/`STOP`, set by `TRMD <mode>`, answered by `TRMD?` |
| `triggers` | bool, default true; false = no trigger events (only `FRTR` completes an arm) |
| `armed_due` | time the armed acquisition completes (next trigger at `rate_hz`) |
| `controls` | list of control commands received (also in `sent`) |
