# Feature Specification: Live Waveform View

**Feature Branch**: `001-live-waveform-view`

**Created**: 2026-10-23

**Status**: Draft

**Input**: User description: "connect to the scope and show live waveforms"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Connect to the scope (Priority: P1)

A lab engineer opens the application, confirms or types the oscilloscope's network address, and
connects. The application shows that it is connected and displays the instrument's identity
(manufacturer, model, serial number, firmware) so the engineer knows they are talking to the
right scope. The engineer can disconnect at any time.

**Why this priority**: Nothing else works without a reliable connection, and showing the
identity immediately confirms the setup (cabling, network, address) is correct.

**Independent Test**: Launch the app, enter the scope's address, press Connect, and verify the
status shows "Connected" with the correct model and serial number; press Disconnect and verify
the status returns to "Disconnected".

**Acceptance Scenarios**:

1. **Given** the app is open and the scope is on the network, **When** the user enters the
   scope's address and presses Connect, **Then** the status shows "Connected" and the identity
   (manufacturer, model, serial number, firmware) is displayed.
2. **Given** the address points to no reachable instrument, **When** the user presses Connect,
   **Then** within 10 seconds the app shows a clear error explaining the instrument could not be
   reached and remains usable.
3. **Given** the app is connected, **When** the user presses Disconnect, **Then** the session
   ends cleanly and the status shows "Disconnected".
4. **Given** the user connected successfully before, **When** they open the app again, **Then**
   the last-used address is pre-filled.

---

### User Story 2 - See live waveforms (Priority: P2)

Once connected, the engineer sees the waveforms of every channel that is turned on at the scope,
updating continuously as the scope acquires, in real units (volts versus time) and with the same
channel colours as the scope's screen. The scope's current vertical scale per channel, timebase
and trigger state are shown next to the plot. If someone changes settings on the scope's front
panel, the view follows.

**Why this priority**: This is the core value of the feature: viewing the signals on the PC
instead of only on the scope's screen.

**Independent Test**: With the scope acquiring a known signal (e.g. its calibration output),
connect and verify the waveform appears, updates continuously, and its amplitude and period
match what the scope itself displays.

**Acceptance Scenarios**:

1. **Given** the app is connected and channels 1, 3 and 4 are on at the scope, **When** the live
   view is shown, **Then** exactly those three channels are plotted, each in its scope colour,
   and they update continuously.
2. **Given** a live view is running, **When** someone turns a channel on or off or changes its
   vertical scale or the timebase at the scope, **Then** the view reflects the change within
   2 seconds.
3. **Given** a live view is running, **When** the scope's acquisition is stopped at the scope,
   **Then** the app keeps showing the last acquired waveform and indicates that the scope is
   stopped, without restarting acquisition.
4. **Given** a live view is running, **When** the user pauses the live view in the app, **Then**
   the display freezes on the current waveforms while the scope keeps running, and resuming
   continues live updates.
5. **Given** several channels are plotted, **When** the user hides one channel in the app,
   **Then** it disappears from the plot only, and the scope's own channel setting is unchanged.

---

### User Story 3 - Work without a scope (simulated mode) (Priority: P3)

An engineer who does not have the scope at hand (or the scope is in use by someone else) starts
the application in simulated mode. The whole connect-and-view flow works with generated signals,
and the app clearly labels that the data is simulated.

**Why this priority**: Lets the tool be demonstrated, developed and checked without occupying
shared lab equipment. Required by the project's principles but not the primary user value.

**Independent Test**: On a PC with no scope connected, start in simulated mode, connect, and
verify identity, channel settings and moving waveforms appear, all labelled as simulated.

**Acceptance Scenarios**:

1. **Given** no scope is available, **When** the user chooses simulated mode and connects,
   **Then** a simulated identity and continuously updating waveforms for several channels are
   shown.
2. **Given** simulated mode is active, **When** the user looks at any part of the window,
   **Then** a visible "SIMULATED" indicator makes it impossible to confuse the data with real
   measurements.

---

### Edge Cases

- **Wrong or unreachable address**: connect fails within 10 seconds with a clear message; no hang.
- **Connection lost during live view** (cable pulled, scope powered off): detected and reported
  within 5 seconds; the last waveforms stay visible but are marked as stale; the user can
  reconnect without restarting the app.
- **Scope busy or held by another remote client**: the app reports that the instrument is busy
  instead of freezing, and lets the user retry.
- **Instrument at the address is not a supported LeCroy scope**: the app shows the identity it
  received, warns that the model is unsupported, and lets the user cancel or continue at their
  own risk.
- **No channels turned on at the scope**: the plot area shows a message such as "No channels
  enabled on the scope" instead of an empty plot.
- **Very long record lengths** (millions of points): the view stays responsive; the update rate
  may drop, and the actual update rate is shown so the user knows.
- **Trigger never fires** (e.g. normal trigger mode with no signal): the app shows that it is
  waiting for a trigger and keeps the last waveform, rather than reporting an error.
- **Closing the app during a transfer**: the app closes promptly and ends the session cleanly.

## Requirements *(mandatory)*

### Functional Requirements

**Connection**

- **FR-001**: Users MUST be able to enter or edit the instrument address before connecting; the
  last successfully used address MUST be remembered between sessions (initial default:
  the lab scope's address `192.168.0.9`).
- **FR-002**: Connecting and disconnecting MUST only happen through explicit user actions.
- **FR-003**: On connection, the system MUST display the instrument's manufacturer, model,
  serial number and firmware version.
- **FR-004**: If the connected instrument is not a supported LeCroy oscilloscope, the system
  MUST warn the user and let them cancel or continue.
- **FR-005**: The connection state (Disconnected, Connecting, Connected, Error/Lost) MUST be
  visible at all times.
- **FR-006**: A connection attempt MUST either succeed or fail with an understandable message
  within 10 seconds.
- **FR-007**: Loss of connection MUST be detected and shown within 5 seconds; the system MUST
  return to a state from which the user can reconnect without restarting.

**Live view**

- **FR-008**: While connected, the system MUST continuously display the waveforms of each analog
  channel (C1–C4) that is turned on at the scope, and MUST NOT plot channels that are off.
- **FR-009**: Waveforms MUST be shown in physical units (volts on the vertical axis, seconds on
  the horizontal axis) derived from the scope's current settings.
- **FR-010**: Each channel MUST be drawn in the same colour the scope uses for that channel.
- **FR-011**: The system MUST show, for each displayed channel, its vertical scale (V/div) and
  offset, plus the scope's timebase (time/div) and trigger/acquisition state
  (e.g. Auto, Normal, Single, Stopped, Waiting for trigger).
- **FR-012**: Changes made at the scope (channel on/off, vertical scale, offset, timebase) MUST
  be reflected in the view within 2 seconds.
- **FR-013**: The system MUST indicate how fresh the data is (live update rate and/or time of
  the last update), and mark waveforms as stale when no new data arrives because of an error.
- **FR-014**: Users MUST be able to pause and resume the live view; pausing affects only the
  application's display, never the scope.
- **FR-015**: Users MUST be able to hide and show individual channels in the application's plot
  without changing the scope.

**Safety & robustness**

- **FR-016**: This feature MUST NOT change any setting or state of the scope (including channel
  settings, timebase, trigger mode, and acquisition run/stop); it only reads.
- **FR-017**: The window MUST remain responsive (moving, resizing, pausing, disconnecting) during
  connection attempts, data transfers and connection failures.
- **FR-018**: Connection events and errors MUST be recorded in a log the user can consult when
  troubleshooting.

**Simulated mode**

- **FR-019**: Users MUST be able to run the application in a simulated mode that provides a
  simulated instrument identity, channel settings and continuously changing waveforms on at
  least two channels, with no scope present.
- **FR-020**: While in simulated mode, a "SIMULATED" indicator MUST be permanently visible.

### Key Entities

- **Instrument Connection**: the session with one oscilloscope; has an address, a state
  (Disconnected, Connecting, Connected, Error/Lost) and whether it is real or simulated.
- **Instrument Identity**: manufacturer, model, serial number, firmware version of the connected
  scope.
- **Channel**: one analog input (C1–C4); has an on/off state at the scope, vertical scale,
  offset, display colour, and a local shown/hidden state in the app.
- **Acquisition Settings**: timebase (time/div), trigger mode and acquisition state at the scope.
- **Waveform**: the latest acquired trace for one channel; sample values in volts with their
  time axis, and the time it was received.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user who knows the scope's address goes from launching the app to seeing live
  waveforms in under 30 seconds.
- **SC-002**: With four channels on and up to 100,000 points per channel, the live view
  refreshes at least 5 times per second on the lab network.
- **SC-003**: The window responds to user input within 0.2 seconds at all times, including
  during connection, data transfer and connection loss.
- **SC-004**: In 100% of tested connection-loss scenarios (cable unplugged, scope powered off),
  the loss is reported within 5 seconds and the app neither freezes nor crashes.
- **SC-005**: After a 10-minute live-view session, the scope's settings are identical to those
  before the session (zero changes caused by the app).
- **SC-006**: Voltage and time values displayed for the scope's calibration signal match the
  scope's own readings within 2% of full scale.
- **SC-007**: Every acceptance scenario of User Stories 1–3 that does not involve the physical
  scope can be demonstrated on a PC with no scope connected, using simulated mode.

## Assumptions

- One user, one scope at a time: the LeCroy WaveRunner 610Zi in the lab, reachable over the
  local network (currently at `192.168.0.9`).
- Only the four analog channels (C1–C4) are in scope; math, memory, zoom and digital traces are
  out of scope for this feature.
- Changing scope settings from the app (scale, timebase, trigger, run/stop) is out of scope and
  will be a later feature; this feature is read-only.
- Saving, exporting or measuring waveforms is out of scope and will be a later feature.
- For very long records, the display may show a reduced-resolution version of the waveform as
  long as its visible shape is faithful; full-resolution data is a concern of a later
  capture/export feature.
- People may keep using the scope's front panel while the app is connected; the app adapts to
  their changes rather than preventing them.
- The application runs on the lab's Windows 11 PCs.
