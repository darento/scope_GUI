# Research: Synchronized Capture

All decisions below come from measurements on the WR610Zi (firmware 9.1.0, LAN, `CHDR OFF` at
the time) on 2026-10-27, with the diagnostic `tests/check_coherence.py` and two short
experiments that wrote only the commands named here and restored the trigger mode (Auto)
afterwards.

## R1 Why the app mixes triggers

- **Decision**: treat it as the scope's normal behaviour, not a bug to work around in the
  driver: while running, each `Cn:WF?` returns that channel's newest acquisition.
- **Evidence**: Auto, 2 µs/div, 200k points, C3 + C4: 20 of 20 reads had different trigger
  time stamps for the reference descriptor, C3 and C4 (about 70 ms apart; reading both channels
  took about 260 ms). At 100 µs/div, 2.5M points, the first read had C3 and C4 0.72 s apart.
  With the scope stopped every read was coherent.
- **Alternatives considered**: read-only filtering of coherent reads (rejected by the user: at
  these rates almost no read is coherent, 0 of 20); combined multi-channel transfer (no such
  query on the WR610Zi's allowlistable set; it would still race the acquisition).

## R2 How to arm one acquisition

- **Decision**: `ARM` (arms a single acquisition whatever the current trigger mode).
- **Evidence**: `ARM` and `TRMD SINGLE` behaved the same: 5 of 5 coherent reads each, armed →
  done in 71–124 ms, the scope reports `STOP` when done.
- **Rationale**: keeps `TRMD <mode>` writes for restoring only, so the log and allowlist show
  at a glance that the app never chooses a trigger mode of its own.
- **Alternatives considered**: `TRMD SINGLE` (equivalent, but mixes arming with mode setting).

## R3 How to know the acquisition is done

- **Decision**: poll `TRMD?` (already allowlisted, read-only) about every 10 ms after arming:
  `SINGLE` = still armed, `STOP` = done; then read all channels.
- **Evidence**: right after `ARM`, `TRMD?` answered `SINGLE` (1.7 ms) and turned `STOP` when
  the acquisition finished (≈ 80–150 ms after arming); each `TRMD?` takes 2–8 ms.
- **Rationale**: every poll is a short worker cycle, so a switch-off, disconnect or close is
  handled within one poll, never blocked by a long wait (FR-004).
- **Rate**: the full status read (≈ 20 short queries, its `TRMD?` included) is done right after
  `ARM`, while the scope acquires, and counts as the first poll. The next `ARM` is sent right
  after the channels are read, so the scope acquires while the window draws (≈ 23 ms at 100k,
  ≈ 230 ms at 2.5M); the worker waits for the window only before reading the next set. An
  update then costs about max(arm→done ≈ 80 ms, window draw) + channel reads (≈ 30–70 ms each
  at 200k when stopped): ≈ 6–7 per second at the reference setup (SC-002 ≥ 5).
- **External changes between updates**: a `TRMD?` before every `ARM` (expected `STOP`) catches
  a front-panel Auto/Normal set while the app was not polling (R6); ≈ 5 ms per update.
- **Alternatives considered**: `WAIT <s>` + `*OPC?` (worked: 10 of 10 coherent; but it blocks
  the link for up to the wait time and adds two commands to the allowlist; not needed).

## R4 Auto without triggers

- **Decision**: when the remembered mode is Auto and the scope is still armed 0.5 s after
  `ARM`, send `FRTR` once for that arm.
- **Evidence**: `ARM` + `FRTR` completed in 67–82 ms with a new trigger stamp; `FRTR` with the
  scope stopped started nothing (mode stayed `STOP`, no new stamp), so a force that races a
  real trigger is harmless.
- **Alternatives considered**: never forcing (user chose forcing, spec Clarifications).

## R5 Restoring the trigger mode

- **Decision**: read `TRMD?` when the mode is switched on and remember it; restore with
  `TRMD <remembered>` (`AUTO`, `NORM`, `SINGLE` or `STOP`), then confirm with `TRMD?`.
- **Evidence**: `TRMD AUTO` after the experiments: `TRMD?` → `AUTO` at once.
- **Notes**: restoring `SINGLE` re-arms a single acquisition, which is what Single means on the
  scope (a Single that had already completed reads as `STOP` and is restored as `STOP`).

## R6 Trigger mode changed elsewhere

- **Decision**: while on, a `TRMD?` answer of `AUTO` or `NORM` (the app only ever produces
  `SINGLE`/`STOP`) means someone else changed it: end the mode without restoring, tell the
  user (FR-008).
- **Limitation**: a front-panel Stop (or Single) is indistinguishable from the app's own
  states; documented in the spec, and the indicator says the app is driving the acquisition.

## R7 No settings-changed note for the app's own mode changes

- **Decision**: while the mode is on, the worker reports the remembered trigger mode in the
  status it emits, so the window's settings comparison (002 FR-022) does not see the app's
  `SINGLE`/`STOP`. Every other setting is reported as read.

## R8 Responsiveness and restore time

- **Decision**: slots (switch on/off, disconnect, shutdown) run between worker cycles. While
  the mode is on, the channels are read one per cycle (the scope is stopped until the next
  `ARM`, so they stay coherent), so the longest cycle is one channel transfer. Restore therefore
  completes within one transfer plus two short queries: well under 2 s up to 200k points (≈ 30–130 ms per channel), about 1 s at
  2.5M points per channel. The window waits up to 3 s on close while the mode is on (instead of
  1 s) before aborting I/O, so the restore is not cut off.
- **Alternatives considered**: interrupting a transfer to restore sooner (would lose the reply
  framing and risk a conflict; not worth it for ≤ 1 s).

## R9 Detecting mixed reads in normal mode

- **Decision**: a displayed update is *mixed* when its channels' trigger time stamps differ.
- **Limitation**: the stamp's resolution as decoded varied between 1 µs and 1 ms in the
  readings; triggers closer than that are not detected. The mode itself does not rely on stamps.

## R10 What "involves two different channels" means

- **Decision**: a measurement involves two channels when it is a Δt whose two sources differ.
  A correlation pairs two measurements; it involves two channels when the union of their
  channels has more than one. For a mixed update these values/pairs are dropped (missed),
  single-channel ones are kept (spec Clarifications).
- **Implementation note**: the measurements panel keeps a per-acquisition coherence flag
  aligned with its trigger-time log; the correlation view uses it to drop pairs.

## R11 A bench that behaves like a running scope

- **Decision**: `SyntheticScope` follows its trigger mode like the WR610Zi:
  - `AUTO`/`NORM`: acquisitions advance with time at `rate_hz`; every `WF?` returns the newest
    one, generated lazily, so two transfers far enough apart return different triggers;
  - `ARM`: mode `SINGLE` until the next acquisition is due (or `FRTR` arrives), then `STOP`
    holding that acquisition; with `triggers=False` only `FRTR` completes it;
  - `STOP`: frozen; `TRMD <mode>` sets the mode.
- **Consequence**: the old behaviour ("a new acquisition on every descriptor read", which hid
  this bug) stays only as an explicit `on_demand=True` option for existing analysis tests that
  need one deterministic acquisition per update; it is documented as a test convenience, not a
  model of the scope. The bench launcher and all new tests use the running model.

## R12 Logging and the log checker

- **Decision**: control writes are logged by the driver like queries (`write ARM`, debug level,
  visible with `SCOPE_GUI_DEBUG=1`); switching on/off and every restore are logged at INFO with
  the counts of armed acquisitions and forced triggers. `tests/check_log.py` lists control
  commands separately and passes when they all match the control allowlist (so SC-004 can still
  be checked on a session with the mode off: no control commands at all).

## R13 `CHDR OFF`

- Found while measuring: the scope's `CHDR` was `OFF`; the WR610Zi then answers `WF?` with
  `DESC,#9…`/`ALL,#9…`, which the driver rejected. Fixed on this branch's base (`4d3b11c`).
  `TRMD?` replies are bare (`AUTO`) in that mode; the existing value parsing handles both.
