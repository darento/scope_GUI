# Data Model: Waveform Analysis

**Feature**: 002-waveform-analysis | **Date**: 2026-10-26

Builds on feature 001's entities (`Waveform`, `ScopeStatus`, `ChannelSettings`, …), which are
unchanged. Everything here lives on the PC and is never sent to the scope. Pure entities live in
`src/scope_gui/analysis.py`; view state lives in the widgets; the synthetic scene is test-only.

## Edge (enum)

`RISING` · `FALLING`. For relative levels, `RISING` means the leading edge (base → top),
whatever the polarity.

## Kind (enum) — measurement types

| Kind | Unit | Levels | Definition (research R2–R4) |
|------|------|--------|-----------------------------|
| `DELTA_T` "Δt @ level" | s | 2 | first crossing of level 2 on source 2 − first crossing of level 1 on source 1 |
| `TIME_AT_LEVEL` | s | 1 | first crossing, relative to the trigger (t = 0) |
| `EDGE_COUNT` | — | 1 | number of crossings of the level with its edge |
| `AMPLITUDE` | V | 0 | top − base (signed) |
| `BASE` / `TOP` | V | 0 | reference levels |
| `MAXIMUM` / `MINIMUM` / `PK_PK` / `MEAN` | V | 0 | over the gated samples |
| `AREA` | V·s | 0 | Σ (v − base) · dt over the gated samples |
| `RISE_TIME` | s | 0 | first complete leading edge, 10 % → 90 % |
| `FALL_TIME` | s | 0 | first trailing 90 % crossing → next trailing 10 % crossing |
| `WIDTH` | s | 0 | first leading 50 % → next trailing 50 % |
| `PERIOD` | s | 0 | mean spacing of leading 50 % crossings (≥ 2 needed) |
| `FREQUENCY` | Hz | 0 | 1 / period |
| `DUTY_CYCLE` | % | 0 | mean (leading → next trailing 50 %) of complete cycles / period |

Missed (NaN) when: the source (or source 2) has no waveform in this acquisition, fewer than 2
samples are in the gate, the needed crossing does not exist, or the quantity is
amplitude-relative and |top − base| < 5 × noise rms (FR-007a).

## Level

| Field | Type | Rule |
|-------|------|------|
| value | float | volts, or a fraction 0–1 when `relative` (UI shows 0–100 %) |
| relative | bool | `True` = constant fraction of base → top |
| edge | Edge | |

Label: `↑ 30 mV`, `↓ -400 mV`, `lead 20%`, `trail 50%`.

## MeasurementSpec (frozen)

| Field | Type | Rule |
|-------|------|------|
| kind | Kind | |
| source | `"C1"`…`"C4"` | |
| level | Level | used if `kind.levels ≥ 1` |
| source2 | `"C1"`…`"C4"` | used if `kind is DELTA_T`; may equal `source` (two levels on one channel) |
| level2 | Level | used if `kind is DELTA_T` |

Derived: `name` (e.g. `Δt C2 ↑ 30 mV → C4 ↓ -400 mV`, `Amplitude C2`) and `kind.unit`.
Serialised with `to_dict` / `from_dict` (enum names, not labels) for `QSettings` (R12).

## Trace (per acquisition, per channel; transient)

The gated samples of one `Waveform`, plus cached reference levels.

- Reference (whole record): base, noise rms, polarity (+1 pulses, −1 negative pulses, 0
  square-like).
- Levels (gated): top = gated peak for pulses, record top for square-like.
- Built once per channel per acquisition by `measure_all(specs, waveforms, gate)`, so the
  reference levels are shared by every measurement of that acquisition.

## Statistics (per measurement)

| Field | Type | Rule |
|-------|------|------|
| buffer | float64[100,000] ring | one entry per processed acquisition, NaN = missed |
| size | int | entries recorded (≤ capacity) |

Operations:
- `add(value)` — exactly once per processed acquisition (FR-008).
- `clear()`.
- `history()` — all entries, oldest first, with NaN.
- `values()` — finite entries only.
- `summary() → Summary`.

## Summary (frozen)

`last`, `mean`, `std` (sample σ, ddof = 1), `minimum`, `maximum`, `count` (finite values),
`missed` (NaN entries). Undefined values (no data) are NaN and shown as "—".

## AcquisitionLog (in the measurements panel)

A ring of trigger times (`Waveform.trigger_time` of the first channel), filled in step with
every `Statistics`. Used as the first CSV column (R10).

## GaussFit (frozen)

`mean`, `sigma`, `amplitude` (counts at peak); derived `fwhm = 2.3548 σ`. Produced by
`gauss_fit(centers, counts)`, or `None` when no sensible fit exists (R5).

## HistogramRange

`AUTO_ROBUST` (median ± 8 robust σ; default) · `FULL` (min–max) · `MANUAL` (from, to).
`histogram_range(values, mode, manual)` → (low, high), and the count outside is shown (R6).

## Analysis view state (GUI only)

| Item | Owner | Default | Persisted |
|------|-------|---------|-----------|
| measurement list (specs) | measurements panel | empty (bench: demo set) | yes (`analysis/measurements`) |
| selected measurement | measurements panel | first row | no |
| gate mode | measurements panel | whole record | no |
| settings-changed note | measurements panel | hidden | no |
| view: histogram / trend / correlation | histogram panel | histogram | no |
| bins | histogram panel | 100 (10–1000) | no |
| range mode / manual range | histogram panel | auto robust | no |
| log counts, Gaussian fit | histogram panel | off, on | no |
| correlation X measurement | histogram panel | first other measurement | no |
| zoomed flag | scope plot | not zoomed | no |
| cursors on, positions | scope plot | off; 1/3 and 2/3 of view | no |
| persistence | scope plot | Off (choices: fade over 10 / 100 / 1000 acquisitions, Infinite) | no |

## State transitions

```text
Statistics:  empty ──add──► accumulating ──clear / spec edited / level dragged──► empty
             (paused: no add; connection lost / disconnected: kept, exportable)

Plot view:   following scope ──box/wheel/pan──► zoomed ──Reset view / double-click──► following
             (any change of view or channel scale also restarts persistence)

Gate:        whole record ◄──► between cursors   (selecting "between cursors" shows the cursors)
```

## Synthetic scene (test-only, `tests/synthetic_scope.py`)

`Scene` (dataclass) holds the parameters of the four signals. The defaults are the spec's scene:
- 10 MHz clock, 0–2.5 V;
- SiPM A positive and SiPM B negative: Poisson mean 3 photoelectrons, 20 mV per photoelectron,
  10 % gain spread, rise 1 ns, decay 30 ns, arrivals 35 / 37 ns with 70 / 90 ps jitter, dark
  rate 1 MHz, noise 1.2 mV rms band-limited to 1 GHz;
- NIM output −0.8 V × 20 ns, 8 ns after SiPM A crosses 30 mV.

It also holds the per-channel V/div and offset, the timebase (50 ns/div), the trigger delay and
the points per record.

`SyntheticAcquisition` holds `volts` per channel and the true values: `npe_a`, `npe_b`,
`arrival_a`, `arrival_b`, `fired`.
