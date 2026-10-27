# Feature Specification: Synchronized Capture

**Feature Branch**: `003-synchronized-capture`

**Created**: 2026-10-27

**Status**: Draft

**Input**: User description: "we are validating the tool and we just realized that we are not
retrieving the waveforms of the same event!? The 2 signals now in the scope are always in phase
but moving, and in the GUI we are not visualizing them always in phase, but if we do a stop or a
single measurement in the scope, the GUI follows it nicely" — followed by the choice of an
opt-in mode in which the app drives the scope's acquisition (constitution v2.1.0, Principle III
"Acquisition control").

## Background

Measured on the WR610Zi (firmware 9.1.0), 2026-10-27, with the diagnostic
`tests/check_coherence.py` and a short experiment:

- While the scope runs, the app reads the channels one after the other and the scope answers
  each with its newest acquisition. At 2 µs/div, 200k points, Auto: **20 of 20** reads had the
  two channels (and the reference read) from different triggers, about 70 ms apart; reading two
  channels took about 260 ms.
- With the scope stopped, or after arming a single acquisition and waiting for it, every
  channel comes from the same trigger: **10 of 10** reads coherent, about 7 updates per second,
  the scope reporting Stopped after each acquisition.

Consequences today: signals that are in phase on the scope look out of phase in the app, and
measurements that combine two channels (Δt between channels, correlation of two channels) mix
events.

## Clarifications

### Session 2026-10-27

- Q: How should the app get all channels from the same trigger? → A: An opt-in mode in which
  the app arms one acquisition at a time, waits for it, reads all channels, and re-arms; the
  previous trigger mode is restored afterwards. Requires constitution v2.1.0 (done).
- Q: With the mode on and the scope originally in Auto, what if no trigger arrives? → A: Force
  a trigger after a short wait, as the scope's Auto does, so untriggered signals keep updating.
- Q: In normal (read-only) mode, what happens when a displayed read mixes triggers? → A: Flag
  it with a hint to switch the mode on, and count measurements that combine two different
  channels as missed for that read; single-channel measurements are unaffected.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See all channels of one trigger (Priority: P1)

A physicist looks at two signals that are locked in phase on the scope. In the app they jump
relative to each other. They switch on **Synchronized capture**; from then on every update
shows all enabled channels from the same trigger, so the signals stay in phase exactly as on
the scope, and Δt between channels measures one event at a time. When they switch it off, the
scope goes back to the trigger mode it had before.

**Why this priority**: without it the app shows wrong relative timing whenever the scope runs,
which defeats timing measurements across channels, the main purpose of the analysis tools.

**Independent Test**: on the bench with a running synthetic scope (acquisitions change between
transfers), switch the mode on: every displayed update has one trigger time for all channels;
switch it off: the scope's trigger mode is the one before switching on.

**Acceptance Scenarios**:

1. **Given** a connected scope running in Auto or Normal, **When** the user switches
   Synchronized capture on, **Then** every following update shows all enabled channels from
   one trigger, and a clearly visible indicator says the app is driving the scope's acquisition.
2. **Given** the mode is on, **When** the user switches it off, **Then** the scope is put back in
   the trigger mode it had when the mode was switched on, and the app continues in normal
   (read-only) mode.
3. **Given** the mode is on, **When** the user disconnects or closes the app, **Then** the
   previous trigger mode is restored before the connection closes.
4. **Given** the mode is on and the scope was in Auto, **When** no trigger arrives for a short
   time, **Then** the app forces one, so the display keeps updating as in Auto.
5. **Given** the mode is on and the scope was in Normal, **When** no trigger arrives, **Then**
   the app keeps waiting and shows "Waiting for trigger", and switching off still restores
   Normal promptly.
6. **Given** the mode is on, **When** the app arms the scope (which the scope reports as a
   trigger mode change), **Then** no "Scope settings changed during this run" note appears.

---

### User Story 2 - Know when the display mixes triggers (Priority: P2)

In normal (read-only) mode, the user sees in the status bar when the last displayed update
combines channels from different triggers, with a hint to switch Synchronized capture on.
Measurements that combine two different channels skip such updates (counted as missed), so
their statistics are not polluted by values from different events.

**Why this priority**: users must not trust cross-channel timing without knowing it may mix
events; it also tells them when the mode is needed.

**Independent Test**: on the bench with a running synthetic scope and the mode off: the warning
appears, a Δt C1 → C2 measurement counts those updates as missed while Amplitude C1 keeps
counting; with the scope stopped the warning disappears.

**Acceptance Scenarios**:

1. **Given** normal mode and a running scope, **When** a displayed update has channels with
   different trigger times, **Then** the status bar shows "Channels from different triggers"
   with a hint to switch Synchronized capture on.
2. **Given** that warning, **When** the next updates have one trigger time for all channels
   (e.g. scope stopped), **Then** the warning disappears.
3. **Given** a mixed update, **When** measurements are computed, **Then** measurements that
   involve two different channels count it as missed and single-channel measurements are
   computed as usual; correlation of two measurements from different channels skips it.

---

### User Story 3 - Reproduce it without the scope (Priority: P3)

A developer runs the synthetic bench with a running scope model in which acquisitions change
between two transfers, sees the mixed-trigger behaviour and its warning, switches Synchronized
capture on and sees it disappear — all without hardware.

**Why this priority**: the bench is how features are developed and tested (constitution IV);
the bug went unnoticed because the bench froze an acquisition until the next one was asked for.

**Independent Test**: the automated tests reproduce mixed reads with the bench and pass without
a scope.

**Acceptance Scenarios**:

1. **Given** the bench in running mode at a trigger rate faster than one transfer, **When** the
   app reads channels in normal mode, **Then** channels come from different triggers.
2. **Given** the same bench, **When** Synchronized capture is on, **Then** all channels of each
   update share one trigger time, and the bench records which acquisition-control commands were
   received.

### Edge Cases

- **Scope stopped or in Single when the mode is switched on**: the app arms acquisitions like in
  Normal (it waits for real triggers, it does not force) and restores Stopped (or Single) when
  switched off.
- **Trigger mode changed elsewhere while the mode is on** (front panel or another program sets
  Auto or Normal): the app switches the mode off without restoring (the newer choice wins) and
  tells the user. A front-panel *Stop* cannot be told apart from the end of an armed
  acquisition; while the mode is on, the acquisition is controlled from the app (the indicator
  says so).
- **Connection lost while the mode is on**: the app cannot restore; it tells the user the scope
  may be left stopped, with the mode it should be set back to.
- **Pause in the app while the mode is on**: no new acquisition is armed; the scope stays
  stopped on the acquisition shown, so the app and the scope screen agree. Resume re-arms.
- **Slow triggers in Normal**: waiting must not freeze the window; switching off, disconnecting
  or closing must restore within 2 seconds even while waiting for a trigger.
- **One channel enabled**: the mode works (nothing to mix); the mixed-trigger warning never
  appears.
- **Equal time stamps from different triggers**: the mixed-trigger detection relies on the
  scope's trigger time stamps; triggers closer together than the stamp resolution are not
  detected (documented limitation; the mode itself does not depend on stamps).
- **Other remote client**: an existing conflict detection still applies; on conflict the mode is
  ended as on link loss.
- **App start**: the mode is always off at start (not remembered between sessions).

## Requirements *(mandatory)*

### Functional Requirements

**Synchronized capture**

- **FR-001**: The app MUST offer a Synchronized capture switch, available while connected,
  off at every start.
- **FR-002**: While the mode is on, each update MUST consist of one armed acquisition: the app
  arms a single acquisition, waits until it completes, then reads all enabled channels, and only
  then arms the next one.
- **FR-003**: While the mode is on, a visible indicator MUST state that the app is driving the
  scope's acquisition, for as long as the mode is on.
- **FR-004**: The trigger mode read just before the mode is switched on MUST be restored when
  the mode is switched off, on disconnect and on app close; restoring MUST complete within
  2 seconds even if the app is waiting for a trigger.
- **FR-005**: If the scope was in Auto, the app MUST force a trigger when none arrives within
  0.5 seconds of arming; from Normal, Single or Stopped it MUST only wait for real triggers.
- **FR-006**: The commands the app may send in this mode are limited to: arm a single
  acquisition, wait for it, synchronise, force a trigger (Auto only), and set the trigger mode
  only to restore the remembered one. They MUST be checked against a write allowlist separate
  from the read-only allowlist; no other setting may ever be written.
- **FR-007**: The app MUST log switching the mode on and off, every restore (with the mode
  restored), and the number of acquisitions armed and triggers forced during the session.
- **FR-008**: If the trigger mode becomes Auto or Normal from outside while the mode is on, the
  app MUST switch the mode off without restoring and tell the user.
- **FR-009**: If the connection is lost (or ends by a conflict) while the mode is on, the app
  MUST tell the user the scope may be left stopped and name the mode to set back.
- **FR-010**: The app's own trigger mode changes MUST NOT raise the "Scope settings changed
  during this run" note (002 FR-022); other setting changes still do.
- **FR-011**: While the display is paused, the app MUST NOT arm new acquisitions.
- **FR-012**: The update rate shown MUST count completed synchronized updates.

**Normal mode**

- **FR-013**: With the mode off, the app MUST behave as before and send only read-only queries
  (001 FR-018, 002 FR-020 still apply to normal mode).
- **FR-014**: When a displayed update has channels with different trigger times, the app MUST
  show "Channels from different triggers" with a hint to switch Synchronized capture on, and
  clear it when an update has one trigger time for all channels.
- **FR-015**: For such an update, measurements involving two different channels (and
  correlation of two measurements from different channels) MUST count it as missed;
  single-channel measurements MUST be computed as usual.

**Bench (test-only)**

- **FR-016**: The synthetic scope MUST offer a running mode whose acquisitions change between
  two transfers at a configurable trigger rate, and MUST respond to the acquisition-control
  commands of FR-006 like the WR610Zi (arming one acquisition, reporting Stopped when done,
  restoring the trigger mode).

### Key Entities

- **Synchronized capture session**: on/off, the remembered trigger mode, counts of armed
  acquisitions and forced triggers, and how it ended (switched off, disconnect, close, external
  change, link lost).
- **Update coherence**: for each displayed update, whether all channels share one trigger time.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With the mode on, 100 % of displayed updates have all channels from one trigger
  (checked over 10 minutes on the real scope with two in-phase signals: the phase between them
  never jumps).
- **SC-002**: With the mode on, at the reference setup (2 µs/div, 200k points, 2 channels,
  triggers faster than the read time), the app shows at least 5 updates per second.
- **SC-003**: In 100 % of switch-off, disconnect and close actions the scope ends in the trigger
  mode it had before, within 2 seconds.
- **SC-004**: With the mode off, a 10-minute session sends only read-only commands (same check
  as 002 SC-007).
- **SC-005**: With the mode off and a running scope faster than the read time, the
  mixed-trigger warning appears within one update and cross-channel Δt statistics hold no
  values from mixed updates.
- **SC-006**: Every requirement above is covered by tests that run without the scope.

## Assumptions

- The scope accepts arming a single acquisition, waiting for its completion and forcing a
  trigger while other clients only read (verified for arm and wait on 2026-10-27).
- The scope's trigger time stamp is the same for all channels of one acquisition (verified)
  and changes from one trigger to the next at the update rates involved.
- Nobody else controls the scope's acquisition remotely while the mode is on; the front panel
  is not used to stop it (the indicator says the app controls it).
- The mode controls only arming; time base, channels, trigger source and level stay as set on
  the scope, and their changes are followed as today.
- Feature 002 (analysis) is the base; this feature changes how acquisitions are obtained and
  adds the coherence flag, not the analysis itself.
