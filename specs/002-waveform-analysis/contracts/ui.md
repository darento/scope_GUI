# Contract: User Interface (analysis additions)

**Feature**: 002-waveform-analysis — extends [001's UI contract](../../001-live-waveform-view/contracts/ui.md);
everything there still holds.

## Layout

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Address […] [Connect] ● Connected  LECROY WR610ZI …                    View  Help │
├───────────────────────────────────────────────────────────────┬──────────────────┤
│ plot (as in 001) + persistence image behind traces            │ Channels (001)   │
│   ┊1          ┊2   ← time cursors; shaded when gate is on     │ Acquisition (001)│
│ ─ ─ ─ ─ ─ ─ ─ ─ ─ ← level line(s) of the selected measurement │ Display          │
│ cursor readout (top-left)      hover readout (bottom-left)    │  ☐ Cursors       │
│                                                               │  Persistence [▾] │
│                                                               │  [Reset view]    │
│                                                               │ [❚❚ Pause]       │
├──────────────────────────────────────┬────────────────────────┴──────────────────┤
│ Measurements (dock)                  │ Histogram (dock)                          │
│ [Add…][Edit…][Remove][Clear][Export…]│ [Histogram|Trend|Correlation] X:[meas ▾]  │
│ Gate: [Whole record ▾]               │ Bins [100] Range [Auto ▾] ☐ Log ☑ Fit     │
│ ⚠ Scope settings changed during run  │ ┌───────────────────────────────────────┐ │
│ Measurement   Last Mean σ Min Max N M│ │  histogram / trend / scatter          │ │
│ Δt C2 lead…   …                      │ └───────────────────────────────────────┘ │
│ Amplitude C2  …                      │ N 1894 · outside 45 · fit μ 1.997 ns      │
└──────────────────────────────────────┴───────────────────────────────────────────┘
│ status bar (001): rate · last update · messages (export done/failed)              │
```

Docks can be moved, tabbed, floated or closed; **View** menu re-opens them. Window default size
grows to 1400 × 900.

## Controls and behaviour

| Element | Behaviour | Req |
|---------|-----------|-----|
| Add… / Edit… (or double-click row) | Dialog: type; source; level value + unit (V or %) + edge (Rising/Falling, shown as Leading/Trailing for %), shown only for types with levels; second source + level for Δt. OK disabled until valid | FR-004, FR-005 |
| Remove | Removes the selected measurement and its statistics | FR-004 |
| Clear | Clears all statistics and the settings-changed note | FR-010, FR-022 |
| Export… | Save-file dialog (`.csv`); written in the background; status bar reports result | FR-019 |
| Gate | Whole record / Between cursors (switches cursors on, shades the region) | FR-016 |
| Table | Columns: Measurement, Last, Mean, σ, Min, Max, N, Missed; values in SI units (4 significant digits; % with 2 decimals; counts plain); "—" when undefined. Rows update once per processed acquisition. Selecting a row selects it for the histogram and level lines | FR-009 |
| Settings note | "⚠ Scope settings changed during this run" while applicable | FR-022 |
| Histogram view | Step histogram of the selected measurement; x label = name with unit (SI-prefixed axis); stats line: N, outside, mean, σ; with fit: μ, σ, FWHM, or "no fit" | FR-012, FR-013 |
| Trend view | Value vs acquisition index, gaps for missed | FR-012 |
| Correlation view | Scatter: X = chosen measurement, Y = selected; acquisitions where both exist; latest 5,000 points | FR-012 |
| Bins / Range / Log / Fit | 10–1000 bins; Auto (robust) / Full / Manual (from, to fields); log count axis; Gaussian fit overlay | FR-012, FR-013 |
| Plot mouse | Left-drag: box zoom · wheel: zoom · middle-drag: pan · double-click: reset view | FR-014 |
| Reset view | Back to the scope's screen; view follows the scope again | FR-014 |
| Cursors | Two vertical lines "1" "2", draggable; readout: `Δt`, `1/Δt`, then per visible channel `Cn  V1  V2  ΔV` | FR-015 |
| Level lines | Dashed, channel colour, labelled with the level; only volt levels of the selected measurement; draggable; on release the level is updated and that measurement's statistics clear | FR-017 |
| Persistence | Off / 10 / 100 / 1000 / Infinite (fade length in acquisitions); density image per channel colour behind the traces; restarts on view or scale change | FR-018 |

## Guarantees

- No control in this feature sends anything to the scope; the driver allowlist is unchanged
  (FR-020).
- Paused: no table, histogram or persistence change; statistics do not grow (FR-023).
- Disconnect / connection lost: statistics, histogram and export stay available; zoom and
  cursors are kept, persistence is cleared with the traces.
- Measurement definitions persist between sessions; statistics do not (FR-011).
