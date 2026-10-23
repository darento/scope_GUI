# Data Model: Live Waveform View

**Feature**: 001-live-waveform-view | **Date**: 2026-10-23

All entities are in-memory, immutable value objects (frozen dataclasses) passed from the worker
thread to the GUI via Qt signals. Nothing is persisted except the last address (see R9).

## ConnectionState (enum)

`DISCONNECTED` · `CONNECTING` · `CONNECTED` · `LOST` · `ERROR`

```text
                 connect()                    identity ok (+ user accepts warning, FR-004)
DISCONNECTED ───────────────► CONNECTING ─────────────────────────────► CONNECTED
     ▲  ▲                         │  unreachable / busy / timeout ≤10 s      │
     │  │                         ▼  / user cancels warning                  │ I/O fails and
     │  └──── dismiss ────────  ERROR                                        │ recovery fails (≤5 s)
     │                                                                       ▼
     └──────────── disconnect() (from CONNECTED, LOST or ERROR) ─────────  LOST
                   connect() is also allowed directly from LOST / ERROR (reconnect)
```

Rules: only explicit user actions trigger `connect()` / `disconnect()` (FR-002). In `LOST`, the
last waveforms stay visible and are flagged stale (FR-015).

## InstrumentIdentity

| Field | Type | Source | Rule |
|-------|------|--------|------|
| manufacturer | str | `*IDN?` field 1 | e.g. `LECROY` |
| model | str | `*IDN?` field 2 | e.g. `WR610ZI` |
| serial | str | `*IDN?` field 3 | |
| firmware | str | `*IDN?` field 4 | |
| support | enum `SUPPORTED` / `UNTESTED_LECROY` / `NOT_LECROY` | derived (R11) | non-`SUPPORTED` requires user confirmation |

## ChannelSettings

| Field | Type | Source | Rule |
|-------|------|--------|------|
| name | `"C1"`…`"C4"` | fixed | analog channels only |
| enabled | bool | `Cn:TRA?` | only enabled channels are plotted (FR-008) |
| volts_per_div | float (V) | `Cn:VDIV?` | > 0 |
| offset | float (V) | `Cn:OFST?` | screen centre = −offset |
| coupling | str | `Cn:CPL?` | informational (e.g. `D1M`, `D50`) |
| color | str (hex) | fixed palette (R10) | |

## AcquisitionSettings

| Field | Type | Source | Rule |
|-------|------|--------|------|
| time_per_div | float (s) | `TDIV?` | > 0 |
| trigger_delay | float (s) | `TRDL?` | screen centre time = −trigger_delay |
| trigger_mode | `AUTO` / `NORM` / `SINGLE` / `STOP` | `TRMD?` | |
| grid_mode | str | `GRID?` | only `SINGLE` mirrored (R6) |
| h_divisions / v_divisions | int | constant | 10 / 8 |

## ScopeStatus (snapshot emitted every cycle)

| Field | Type | Notes |
|-------|------|-------|
| channels | tuple[ChannelSettings, ×4] | |
| acquisition | AcquisitionSettings | |
| acq_state | `ACQUIRING` / `WAITING_FOR_TRIGGER` / `STOPPED` | derived (R5) |
| read_at | float (monotonic s) | |

Changes at the scope appear in the next snapshot; cycle period ≤ 1 s, so FR-014's 2 s bound holds.

## WaveformDescriptor (parsed from binary WAVEDESC)

| Field | Type | WAVEDESC field |
|-------|------|----------------|
| comm_type | `BYTE` / `WORD` | COMM_TYPE |
| little_endian | bool | COMM_ORDER |
| vertical_gain | float | VERTICAL_GAIN |
| vertical_offset | float | VERTICAL_OFFSET |
| horiz_interval | float (s) | HORIZ_INTERVAL |
| horiz_offset | float (s) | HORIZ_OFFSET |
| point_count | int | WAVE_ARRAY_COUNT |
| first_valid / last_valid | int | FIRST_VALID_PNT / LAST_VALID_PNT |
| trigger_time | float (s, absolute) | TRIGGER_TIME (binary timestamp) |
| source | str | WAVE_SOURCE |

Validation: descriptor block must start with `WAVEDESC`; template name `LECROY_2_3`; data array
length must equal `point_count × bytes_per_sample`; otherwise the record is rejected and logged.

## Waveform

| Field | Type | Notes |
|-------|------|-------|
| channel | `"C1"`…`"C4"` | |
| volts | float32 array | `vertical_gain × code − vertical_offset` (R6) |
| t0 | float (s) | `horiz_offset` (time of first point relative to trigger) |
| dt | float (s) | `horiz_interval` |
| trigger_time | float | for novelty detection (R5) |
| received_at | float (monotonic s) | for freshness/staleness (FR-015) |

Relationship: one `Waveform` per enabled `ChannelSettings` per acquisition. Display converts to
divisions using the *current* `ChannelSettings` (`div = (volts + offset) / volts_per_div`).

## LiveViewState (GUI only, not sent to the scope)

| Field | Type | Notes |
|-------|------|-------|
| paused | bool | FR-016; while paused, incoming waveforms are dropped by the view |
| hidden_channels | set[str] | FR-017 |
| update_rate_hz | float | moving average of received acquisitions (FR-015) |
| stale | bool | true when `LOST`/`ERROR` or no data while expected (FR-015) |
