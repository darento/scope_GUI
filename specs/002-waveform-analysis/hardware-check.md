# Hardware check: waveform analysis on the WR610Zi

Closes tasks T041–T043: the hardware tests, quickstart R1–R4 and SC-001. About 45 minutes,
including one 10-minute session. Write the results in the table at the end, then copy them to
[checklists/validation.md](checklists/validation.md) (or hand them to Claude to do it).

Everything below is read-only for the scope; the only scope changes are the ones **you** make
on its front panel in steps 3, 4 and 5.

## 0. Before you start (5 min)

1. Scope on, on the network at `192.168.0.9`; close any other program talking to it over LAN
   (a second client steals replies and the app drops the connection, as designed).
2. In PowerShell, in the repository:

   ```powershell
   git switch 002-waveform-analysis
   uv sync
   Test-NetConnection 192.168.0.9 -Port 111    # TcpTestSucceeded : True
   ```

3. Scope: channels C1–C4 on, with signals on at least C1 and C2 (step 3 needs two channels with
   related edges, e.g. a pulse generator split to C1 and C2, or the lab's usual signals).

## 1. Automated hardware tests (2 min) — T041

```powershell
uv run pytest -m hardware
```

Expected: `3 passed`. They connect, read live for 30 s twice (once with 10 measurements,
histogram, cursors, gate and persistence on) and fail if any command outside the allowlist is
sent or any scope setting changed. Anything else: note the failing test and its message.

## 2. Update rate with analysis (5 min) — R1, SC-005

1. On the scope: record length **100k points**, C1–C4 on, trigger running (Auto or Normal with
   a steady trigger).
2. `uv run scope-gui`, **Connect**. If measurements are listed, select each and **Remove**.
3. Wait 30 s; note the rate in the status bar (`N updates/s`) → **rate A**.
4. **Add…** ten measurements, for example: Δt @ level C1 → C2, Time @ level C1, Edge count
   C1, Amplitude C1, Frequency C1, Rise time C1, Maximum C2, Pk-Pk C3, Mean C4, Area C2.
   Keep the Histogram dock visible with one of them selected.
5. Wait 30 s; note the rate → **rate B**.
6. While it runs: wheel-zoom the plot, drag a cursor (Display → Cursors), open the View menu.
   Each should react at once (no visible lag).

Pass: B ≥ 0.9 × A, and the window stays responsive.

## 3. Time to a Δt histogram (2 min) — SC-001

1. Remove all measurements (connected, live view running).
2. Start a stopwatch. **Add…** → type *Δt @ level*; Source C1, its level and edge; Source 2
   C2, its level and edge → **OK**. The new measurement is selected and the Histogram dock
   shows it (Fit is on by default).
3. Stop when the orange fit curve and `fit μ … σ … FWHM …` appear under the histogram.

Pass: under 1 minute. Note the time.

## 4. Settings change warning (2 min) — R2, FR-022

1. With measurements collecting (N growing), change **V/div** of any channel on the scope.
2. The orange note *Scope settings changed during this run* appears above the table; the
   statistics are kept.
3. Click **Clear**: the note disappears and the statistics restart.

## 5. Calibrator comparison (10 min) — R4, FR-004

1. Connect the scope's calibration output to **C1**; timebase showing several periods; set the
   scope's measurements P1 = Frequency, P2 = Rise time (10–90 %), P3 = Duty cycle on C1, with
   statistics on.
2. In the app: Clear, add Frequency C1, Rise time C1, Duty cycle C1; wait for N ≥ 100.
3. Compare each app **Mean** with the scope's mean.

Pass: frequency and duty cycle agree to their last displayed digits (≲ 0.1 % and ≲ 1 %);
rise time within the scope's own spread (its σ). Note both values for each.

## 6. Ten-minute read-only session (15 min) — R3, SC-007

1. Note the clock time (e.g. `2026-10-27 10:15`), then start the app with command logging:

   ```powershell
   $env:SCOPE_GUI_DEBUG = "1"; uv run scope-gui
   ```

2. For 10 minutes, use every tool at least once: add / edit / remove measurements; Clear;
   histogram (bins, Range Auto / Full / Manual, Log, Fit), Trend and Correlation views; box
   zoom, wheel zoom, middle-drag pan, double-click and Reset view; Cursors; Gate *Between
   cursors*; drag a level line; Persistence 10 / 100 / 1000 / Infinite / Off; Pause and Resume;
   **Export…** a CSV; Disconnect and Connect again.
3. Close the app, then:

   ```powershell
   Remove-Item Env:SCOPE_GUI_DEBUG
   uv run python tests/check_log.py --since "2026-10-27 10:15"
   ```

   It lists every command sent with its count.

Pass: the last line reads `PASS: all … commands … are allowlisted`.

4. Open the exported CSV in Excel: one row per acquisition, trigger time first, one column
   per measurement, empty cells where a value was missed; Δ and µ display correctly.

## If something fails

**Help → Open log folder** (`%LOCALAPPDATA%\scope_gui\logs`) and a screenshot of the window
are enough to investigate; note the step and what you saw.

## Results

| Step | Check | Result | Notes |
|---|---|---|---|
| 1 | `pytest -m hardware` (3 tests) | | |
| 2 | Rate A (no measurements) | ___ updates/s | |
| 2 | Rate B (10 measurements + histogram) | ___ updates/s | B / A = ___ (≥ 0.9) |
| 2 | Responsive while running | | |
| 3 | Δt to fitted histogram | ___ s | (< 60 s) |
| 4 | Settings-changed note, Clear hides it | | |
| 5 | Frequency: app / scope | ___ / ___ | |
| 5 | Rise time: app / scope (σ) | ___ / ___ (___) | |
| 5 | Duty cycle: app / scope | ___ / ___ | |
| 6 | `check_log.py` result | | ___ commands |
| 6 | CSV opens correctly in Excel | | |

When everything passes, T041–T043 can be marked done and the spec set to Implemented.
