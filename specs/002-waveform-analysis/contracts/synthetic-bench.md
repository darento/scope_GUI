# Contract: Synthetic Bench (test-only)

**Feature**: 002-waveform-analysis

Lives only under `tests/`; nothing in `src/scope_gui` imports it (Constitution I, IV; checked by
a test that greps `src/` for `synthetic`).

## Launch

```powershell
uv run python tests/bench.py [--rate 20] [--points 10000] [--seed N] [--mean-pe 3]
```

- Opens the normal `MainWindow` titled "Scope GUI — SYNTHETIC test bench"; press Connect (any
  address).
- Uses its own settings file (`%LOCALAPPDATA%\scope_gui\bench.ini`): the real last address and
  measurement list are never changed. First start adds a demo measurement set:
  - Δt C2 lead 20 % → C3 lead 20 % (coincidence timing)
  - Δt C2 ↑ 30 mV → C4 ↓ −400 mV (discriminator delay)
  - Δt C1 ↑ 1.25 V → C2 ↑ 30 mV (leading edge, shows walk)
  - Amplitude C2 (photoelectron spectrum)
  - Area C2
  - Frequency C1
  - Rise time C2

## `SyntheticScope` (VISA-resource stand-in)

| Method | Behaviour |
|--------|-----------|
| `write(cmd)` / `read_raw()` / `read()` / `query(cmd)` | Answers the allowlisted queries of `driver.ALLOWED_COMMANDS` with SHORT headers; unknown commands → no reply → timeout, like the scope |
| `Cn:WF? DESC` | Starts a new acquisition (no faster than `rate_hz`; waits in the calling thread) and returns its descriptor |
| `Cn:WF? ALL` | The current acquisition's block for `Cn`: LECROY_2_3 descriptor, BYTE codes at 25 codes/div, offset as the channel's OFST, clipped to −128…127; same TRIGGER_TIME for all channels of one acquisition |
| `clear()` / `close()` | As a VISA resource |
| `scene`, `current`, `acquisitions` | Parameters, the latest `SyntheticAcquisition` (true values) and a counter, for tests |

Identity: `*IDN LECROY,WR610ZI,SYNTHETIC,9.1.0` (supported model, so no warning dialog).
Settings replies follow `Scene.channels`, `time_per_div`, `trigger_delay`; trigger mode `NORM`;
`GRID SINGLE`. Changing `scene` between acquisitions changes what the next status read reports
(used to test FR-022).

`synthetic_factory(scope)` returns a `resource_factory` for `ScopeDriver`, like
`fakes.fake_factory`.
