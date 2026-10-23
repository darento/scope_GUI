# Scope GUI

Desktop app that mirrors the live waveforms of the lab's **LeCroy WaveRunner 610Zi** on a PC over
the network: same channels, colours, 10 × 8 division grid, scales, offsets, timebase and trigger
position as the scope's own screen.

The app is **strictly read-only**: it sends only queries from a fixed allowlist
(`src/scope_gui/driver.py`, `ALLOWED_COMMANDS`) and never changes any scope setting.
There is no simulated or demo mode; it always shows what the real scope is acquiring.

## Requirements

- Windows 11, [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv`)
- Network access to the scope (currently `192.168.0.9`, VXI-11/LXI). No NI-VISA needed.

## Run

```powershell
uv sync --python cpython-3.13-windows-x86_64   # first time: 64-bit Python 3.13 + dependencies
uv run scope-gui
```

Enter the scope's address (remembered for next time), press **Connect**.

- Untick a channel to hide it on the PC only; **Pause** freezes the PC display only.
- The status bar shows the achieved update rate. It is limited by the scope's readout
  (~2.2 MB/s): about 5 updates/s at 100k points × 4 channels, ~1.5 updates/s at 500k × 3.
- **Help → Open log folder** opens `%LOCALAPPDATA%\scope_gui\logs` (connections and errors). Set
  `SCOPE_GUI_DEBUG=1` before launching to also log every command sent.

## Tests

```powershell
uv run pytest                 # no scope needed (fake instrument in tests/ only)
uv run pytest -m hardware     # against the real scope, read-only (--scope-address to override)
uv run ruff check; uv run ruff format --check
```

To refresh the recorded scope replies used by the tests:
`uv run python tests/fixtures/capture_fixtures.py [address]`.

## Project

Developed with GitHub Spec Kit (spec-driven development). Constitution:
`.specify/memory/constitution.md`. Feature docs and manual validation steps:
`specs/001-live-waveform-view/` (see `quickstart.md`).
