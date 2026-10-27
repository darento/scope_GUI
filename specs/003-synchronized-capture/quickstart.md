# Quickstart: Synchronized Capture

## Without the scope (bench)

```powershell
git switch 003-synchronized-capture
uv sync
uv run pytest                      # everything, no scope needed (SC-006)
uv run python tests/bench.py       # bench window, synthetic scope running in Auto
```

| # | Do | Expect |
|---|---|---|
| B1 | Connect; watch the status bar | "Channels from different triggers - switch Synchronized capture on" appears (bench acquisitions change between transfers) |
| B2 | Add Δt C1 → C2 and Amplitude C1 | Δt counts the mixed updates as missed; Amplitude counts all |
| B3 | Tick **Synchronized capture** | Amber "Driving the scope: synchronized capture"; the mixed warning disappears; Δt N grows; trigger line `Trigger: Auto (synchronized)` |
| B4 | Untick it | Indicator gone; bench trigger mode back to Auto (tests check `TRMD AUTO` was sent) |
| B5 | Tick, then Disconnect / close the window | Trigger mode restored before the link closes (automated) |

## With the scope (WR610Zi)

Two in-phase signals on two channels; the reference setup is 2 µs/div, 200k points, Auto.

| # | Do | Expect / record |
|---|---|---|
| R1 | Connect, mode off, scope running | Mixed-trigger warning; traces jump relative to each other (the original report) |
| R2 | Tick **Synchronized capture**, watch 10 min (SC-001) | The phase between the two signals never jumps; Δt σ small and stable |
| R3 | Read the rate in the status bar (SC-002) | ≥ 5 updates/s |
| R4 | Untick; scope front panel (SC-003) | Trigger mode back to what it was (repeat from Normal and Stopped) within 2 s |
| R5 | Tick, then Disconnect; tick, then close the app | Scope back in its mode each time |
| R6 | Tick, then press Auto (or Normal) on the scope | App switches the mode off and says the trigger mode was changed on the scope |
| R7 | Tick with the scope in Normal and no trigger | "Waiting for trigger"; untick restores Normal within 2 s |
| R8 | `$env:SCOPE_GUI_DEBUG = "1"`, 10 min with the mode **off**, then `uv run python tests/check_log.py --since "<start>"` (SC-004) | PASS, no control commands |
| R9 | Same with the mode **on** for part of the session | PASS; control commands listed separately: only `ARM`, `FRTR`, `TRMD <mode>` |

Hardware tests (opt-in; they arm the scope and restore its mode):

```powershell
uv run pytest -m hardware
```
