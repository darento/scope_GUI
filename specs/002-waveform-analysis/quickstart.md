# Quickstart & Validation: Waveform Analysis

**Feature**: 002-waveform-analysis

## Prerequisites

As in [001's quickstart](../001-live-waveform-view/quickstart.md). The synthetic bench needs no
scope; the real-scope checks need the WR610Zi at `192.168.0.9`.

## Run

```powershell
uv run scope-gui                      # the application (real scope only)
uv run python tests/bench.py          # synthetic test bench (developers/demos)
uv run python tests/bench.py --rate 50 --points 100000 --mean-pe 20
```

## Automated tests

```powershell
uv run pytest            # includes analysis unit tests, synthetic-bench accuracy tests (SC-002,
                         # SC-003, SC-004) and pytest-qt tests of the new panels and plot tools
uv run pytest -m hardware
uv run ruff check; uv run ruff format --check
```

## Manual validation — synthetic bench

Start the bench and press Connect. The demo measurements are listed. Contracts:
[ui.md](contracts/ui.md), [synthetic-bench.md](contracts/synthetic-bench.md).

| # | Steps | Expected | Spec |
|---|-------|----------|------|
| B1 | Watch the plot for 10 s | Clock (yellow), positive pulses (pink), negative pulses (cyan), NIM pulses (green); pulse heights in steps; some acquisitions without pulses; title says SYNTHETIC | US1 |
| B2 | Select "Δt C2 lead 20% → C3 lead 20%", wait ~1 min, Fit on | Peak near 2.0 ns, fitted σ ≈ 0.13 ns; "outside" count from dark counts | US2, US3 |
| B3 | Gate: Between cursors; drag cursors to ~25 ns and ~60 ns; Clear | Shaded gate; after refilling, "outside" much lower; same peak | FR-016, R6 |
| B4 | Select "Amplitude C2", Log on, Bins 200 | Separate photoelectron peaks ~20 mV apart, pedestal near 0 | SC-004 |
| B5 | Correlation view, X = Amplitude C2, Y = "Δt C1 ↑ 1.25 V → C2 ↑ 30 mV" | Δt decreases as amplitude grows (time walk) | FR-012 |
| B6 | Select the C2 → C4 Δt; drag the C2 line from 30 mV to 50 mV | Line follows; on release the name shows 50 mV and its statistics restart; more misses | FR-017 |
| B7 | Box-zoom on the C1 edge at t = 0; wait | View stays zoomed while traces update; double-click → full screen again | FR-014 |
| B8 | Cursors on; place on two C1 rising edges | Δt ≈ 100 ns, 1/Δt ≈ 10 MHz; channel voltages at both cursors | FR-015 |
| B9 | Persistence 100 | Coloured density behind traces; SiPM photoelectron bands visible; zoom restarts it | FR-018 |
| B10 | Pause 10 s, Resume | Table, histogram and N frozen while paused | FR-023 |
| B11 | Export… to a file; open in Excel | One row per acquisition, trigger time + one column per measurement, empty cells for misses; status bar shows the path | FR-019 |
| B12 | Close and restart the bench | Same measurements listed, statistics empty | FR-011 |

## Manual validation — real scope

Step by step, with the hardware tests and SC-001 timing: [hardware-check.md](hardware-check.md).

| # | Steps | Expected | Spec |
|---|-------|----------|------|
| R1 | 100k points × 4 channels, note the update rate; add 10 measurements, histogram shown | Rate within 10 % of before; window responsive | SC-005 |
| R2 | During a run, change V/div on the scope | "Scope settings changed during this run" appears; Clear hides it | FR-022 |
| R3 | `SCOPE_GUI_DEBUG=1`, 10-minute session using every analysis tool; inspect the log | Only 001's allowlisted queries | SC-007, FR-020 |
| R4 | Calibration output on C1: Frequency, Rise time, Duty cycle | Match the scope's own P1–P3 measurements within their stated accuracy | FR-004 |
