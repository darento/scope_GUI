# Quickstart & Validation: Live Waveform View

**Feature**: 001-live-waveform-view

## Prerequisites

- Windows 11 PC with `uv` installed (`winget install astral-sh.uv`).
- LeCroy WR610Zi on the lab LAN, reachable from the PC (currently `192.168.0.9` via the USB-GbE
  adapter configured as `192.168.0.10/24`). Check: `ping 192.168.0.9`.
- No NI-VISA needed.

## Setup and run

```powershell
uv sync                 # creates .venv from pyproject.toml / uv.lock (Python 3.13)
uv run scope-gui        # launches the application
```

## Automated tests

```powershell
uv run pytest                 # all tests that need no scope (default; must pass anywhere)
uv run pytest -m hardware     # tests against the real scope at 192.168.0.9 (read-only)
uv run ruff check; uv run ruff format --check
```

The hardware tests also verify the command allowlist end-to-end and record the scope's settings
before and after (SC-005).

## Manual validation scenarios (real scope)

Prepare the scope: calibration output (or any known signal) on C1, channels 1, 3, 4 on,
Auto trigger. Note its settings (or save a setup on the scope) to compare at the end.

| # | Steps | Expected | Spec |
|---|-------|----------|------|
| 1 | Launch, check address, press Connect | Green "Connected"; identity `LECROY WR610ZI`, serial, fw 9.1.0 in < 10 s | US1-1, FR-003 |
| 2 | Disconnect; set address `192.168.0.99`; Connect | Error "instrument not reachable" within 10 s; window stays responsive | US1-2, FR-006 |
| 3 | Close and relaunch | Address pre-filled with `192.168.0.9` | US1-4, FR-001 |
| 4 | Connect; place PC window next to scope screen | Same channels (C1, C3, C4), colours, positions on 10 × 8 grid; trigger marker matches | US2-1, US2-2, SC-006 |
| 5 | On the scope: turn C3 off, change C1 V/div and timebase | PC follows within 2 s | US2-3, FR-014 |
| 6 | On the scope: press Stop | PC shows "Stopped", keeps last trace, no restart of acquisition | US2-4 |
| 7 | In app: Pause, wait, Resume | PC freezes then resumes; scope keeps running | US2-5, FR-016 |
| 8 | In app: uncheck C4 | C4 hidden on PC only; still on at scope | US2-6, FR-017 |
| 9 | Unplug the Ethernet cable during live view | "Lost" within 5 s; traces marked STALE; replug → Connect works without restart | FR-007, SC-004 |
| 10 | Set scope to 100k points (e.g. adjust timebase/memory), 4 channels on | Status bar shows ≥ 5 updates/s | SC-002 |
| 11 | Drag/resize the window during transfers and during step 9 | Always responsive | FR-019, SC-003 |
| 12 | After ~10 min of live view, compare scope settings with the start | Identical | SC-005, FR-018 |
| 13 | Help → Open log folder | Log shows connect/disconnect/errors and the queries sent | FR-020 |

Expected performance at the current 500k points/channel: ~1.5 updates/s with 3 channels
(scope readout limit ~2.2 MB/s, see [research.md](research.md) R2); the status bar must show it.

See [contracts/ui.md](contracts/ui.md) and [contracts/scope-driver.md](contracts/scope-driver.md)
for the exact UI elements and allowed commands, and [data-model.md](data-model.md) for states.
