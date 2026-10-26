# Scope GUI

Desktop app that mirrors the live waveforms of the lab's **LeCroy WaveRunner 610Zi** on a PC over
the network: same channels, colours, 10 × 8 division grid, scales, offsets, timebase and trigger
position as the scope's own screen.

The app is **strictly read-only**: it sends only queries from a fixed allowlist
(`src/scope_gui/driver.py`, `ALLOWED_COMMANDS`) and never changes any scope setting.
There is no simulated or demo mode; it always shows what the real scope is acquiring.

On top of the mirror, the app measures the waveforms it has already received (no extra scope
commands): time between threshold crossings of any channels, pulse and clock parameters, running
statistics, histograms with a Gaussian fit, and export to CSV.

## Requirements

- Windows 11, [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv`)
- Network access to the scope (currently `192.168.0.9`, VXI-11/LXI). No NI-VISA needed.

## Run

```powershell
uv sync --python cpython-3.13-windows-x86_64   # first time: 64-bit Python 3.13 + dependencies
uv run scope-gui
```

Enter the scope's address (remembered for next time), press **Connect**.

- Untick a channel to hide it on the PC only; **Pause** freezes the PC display only (and stops
  the statistics, so what is shown is exactly what was measured).
- The status bar shows the achieved update rate. It is limited by the scope's readout
  (~2.2 MB/s): about 5 updates/s at 100k points × 4 channels, ~1.5 updates/s at 500k × 3.
- **Help → Open log folder** opens `%LOCALAPPDATA%\scope_gui\logs` (connections and errors). Set
  `SCOPE_GUI_DEBUG=1` before launching to also log every command sent.

## Analysis

Docks below the plot (re-open them from **View**):

- **Measurements**: **Add…** a measurement; the table shows Last, Mean, σ, Min, Max, N and Missed,
  updated once per acquisition. **Clear** restarts the statistics; editing a measurement restarts
  only its own. The list is remembered; the statistics are not. At most the last 100,000 values per
  measurement are kept. **Export…** writes one CSV row per acquisition (trigger time, then one
  column per measurement, empty where it could not be measured).
- **Histogram**: of the selected measurement, with bins, automatic (robust) / full / manual range,
  log counts and a Gaussian fit (mean, σ, FWHM); also **Trend** over acquisitions and
  **Correlation** against a second measurement (e.g. Δt versus amplitude to see time walk).

Measurement definitions (hover a type in the dialog for the same text):

| Type | Definition |
|------|------------|
| Δt @ level | First crossing of level 2 on source 2 − first crossing of level 1 on source 1 |
| Time @ level | First crossing, relative to the trigger (t = 0) |
| Edge count @ level | Number of crossings of the level with its edge |
| Amplitude, Base, Top | Square-like signals: low/high levels; pulses: baseline/peak (top below base for negative pulses) |
| Maximum, Minimum, Pk-Pk, Mean | Over the samples in the gate |
| Area | ∫ (signal − base) dt over the gate, in V·s |
| Rise / Fall time | 10 → 90 % of the first complete leading edge / 90 → 10 % of the first trailing edge |
| Width, Period, Frequency, Duty cycle | From the 50 % crossings |

- Levels are in volts, or in % of the amplitude (**constant fraction**) with a leading or trailing
  edge, for positive and negative pulses alike. Crossing times are interpolated between samples.
- Base and noise always come from the whole record. Values relative to the amplitude count as
  **missed** when the signal is below 5 × its noise (e.g. an acquisition without a pulse).
- **Gate**: *Between cursors* restricts every measurement to the shaded window between the
  cursors.

On the plot: left-drag to box-zoom, wheel to zoom, middle-drag to pan; **Reset view** or a
double-click returns to the scope's screen. **Cursors** shows two time cursors with Δt, 1/Δt and
each channel's voltage at both. The levels of the selected measurement are drawn as dashed lines;
drag one to change the level (its statistics restart). **Persistence** shows where recent
acquisitions went, fading over 10/100/1000 acquisitions or never.

## Synthetic test bench (developers)

```powershell
uv run python tests/bench.py [--rate 20] [--points 10000] [--seed N] [--mean-pe 3]
```

Opens the normal window connected to a **synthetic WR610Zi** that lives in `tests/` (it is not a
mode of the application and `scope-gui` cannot reach it). C1: 10 MHz clock; C2/C3: positive and
negative SiPM-like pulses (Poisson photoelectrons, dark counts, noise, known jitter); C4: NIM
discriminator output. It goes through the real driver and allowlist, uses its own settings file
(`%LOCALAPPDATA%\scope_gui\bench.ini`) and starts with a demo set of measurements. Validation
steps: `specs/002-waveform-analysis/quickstart.md`.

## Tests

```powershell
uv run pytest                 # no scope needed (fake and synthetic instruments in tests/ only)
uv run pytest -m hardware     # against the real scope, read-only (--scope-address to override)
uv run ruff check; uv run ruff format --check
```

To refresh the recorded scope replies used by the tests:
`uv run python tests/fixtures/capture_fixtures.py [address]`.

## Project

Developed with GitHub Spec Kit (spec-driven development). Constitution:
`.specify/memory/constitution.md`. Feature docs and manual validation steps:
`specs/001-live-waveform-view/` (live view) and `specs/002-waveform-analysis/` (analysis and
bench), each with a `quickstart.md`.
