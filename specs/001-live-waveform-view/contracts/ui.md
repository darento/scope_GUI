# Contract: User Interface

**Feature**: 001-live-waveform-view

## Launch

`uv run scope-gui` opens the main window in `DISCONNECTED` state. No command-line flags are
required; there is no simulated mode.

## Main window layout

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Address [192.168.0.9      ] [Connect] ● Connected  LECROY WR610ZI        │ ← connection bar
│                                   SN LCRY3201N55990  FW 9.1.0            │
├───────────────────────────────────────────────────────┬──────────────────┤
│                                                       │ ☑ C1  1 V/div    │
│        plot: black background, 10 × 8 divisions,      │       ofs -3.01 V│
│        traces in scope colours, trigger marker at t=0 │ ☐ C2  (off)      │
│                                                       │ ☑ C3 500 mV/div  │
│                                                       │ ☑ C4 500 mV/div  │
│                                                       ├──────────────────┤
│                                                       │ 5 µs/div         │
│                                                       │ Trig AUTO        │
│                                                       │ Acquiring        │
│                                                       │ [❚❚ Pause]       │
├───────────────────────────────────────────────────────┴──────────────────┤
│ status bar: 1.5 updates/s · last update 15:54:27 · messages              │
└──────────────────────────────────────────────────────────────────────────┘
```

## Controls and behaviour

| Element | Behaviour | Req |
|---------|-----------|-----|
| Address field | Editable when not connected; pre-filled with last successful address (default `192.168.0.9`); accepts IP/hostname or full VISA string | FR-001 |
| Connect / Disconnect button | Toggles; disabled while `CONNECTING` except as Cancel | FR-002 |
| Status indicator | Grey Disconnected · amber Connecting · green Connected · red Lost/Error, with text | FR-005 |
| Identity label | Manufacturer, model, serial, firmware after connect | FR-003 |
| Unsupported dialog | Modal Continue/Cancel when identity is not `SUPPORTED` | FR-004 |
| Error message | Non-modal banner/status message for unreachable, busy, timeout | FR-006, edge cases |
| Plot | Shows enabled channels only, in divisions grid; hover readout shows time and per-channel volts | FR-008–FR-012 |
| "No channels enabled on the scope" | Centered text when no channel is on | edge case |
| Channel panel checkbox | Hides/shows a trace locally only; disabled for channels off at the scope | FR-017 |
| Channel panel text | V/div, offset, coupling per channel | FR-013 |
| Acquisition panel | Time/div, trigger mode, `Acquiring` / `Waiting for trigger` / `Stopped` | FR-013 |
| Pause / Resume | Freezes display only | FR-016 |
| Stale overlay | When `LOST`/`ERROR`: traces dimmed + "STALE — not live" label | FR-015 |
| Status bar | Update rate (Hz) and time of last update | FR-015 |
| Help → Open log folder | Opens `%LOCALAPPDATA%\scope_gui\logs` | FR-020 |

## Guarantees

- No control in this feature sends a state-changing command to the scope (FR-018).
- The window stays interactive (move, resize, pause, disconnect) at all times (FR-019).
- Closing the window during a transfer exits within ~1 s plus the current read's abort (R8).
