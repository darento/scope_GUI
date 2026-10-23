# Feature Specification: Live Waveform View

**Feature Branch**: `001-live-waveform-view`

**Created**: 2026-10-23

**Status**: Draft

**Input**: User description: "connect to the scope and show live waveforms" — the GUI must
connect to the real scope and show what is being seen on it; no simulation.

## Clarifications

### Session 2026-10-23

- Q: Besides C1–C4, which other traces shown on the scope should the PC display in this first
  version? → A: Only C1–C4; math, zoom, memory traces and measurements are later features.
- Q: Is ~1.5 refreshes/s at 500k points × 3 channels acceptable, or is a faster option needed?
  → A: Acceptable; always full resolution and read-only, with the achieved rate shown. No
  fast-preview mode.
- Q: When the scope shows traces across several grids (dual/quad), what should the PC show?
  → A: Always one grid with every channel correctly positioned, plus a note that the scope uses
  a multi-grid layout.
- Q: What language should the interface use? → A: English only.
- Q: Will other programs control the scope remotely while the app is open? → A: Rarely; the app
  must coexist with them, adapting to their changes and retrying when the scope is busy.
  *(Refined by the next answer after validation on the real scope.)*
- Q: The scope mixes up replies between simultaneous remote clients and does not enforce
  exclusive locks. What should the app do when another program is clearly talking to the scope
  at the same time? → A: Validate every reply; after repeated mismatched replies, stop polling,
  keep the last traces marked stale, and tell the user another program is using the scope
  (the user reconnects manually). Changes made by another program *between* sessions or from
  the front panel are still followed as before.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Connect to the scope (Priority: P1)

A lab engineer opens the application, confirms or types the oscilloscope's network address, and
connects. The application shows that it is connected and displays the instrument's identity
(manufacturer, model, serial number, firmware) so the engineer knows they are talking to the
right scope. The engineer can disconnect at any time.

**Why this priority**: Nothing else works without a reliable connection, and showing the
identity immediately confirms the setup (cabling, network, address) is correct.

**Independent Test**: With the scope on the network, launch the app, enter the scope's address,
press Connect, and verify the status shows "Connected" with the scope's real model and serial
number; press Disconnect and verify the status returns to "Disconnected".

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

### User Story 2 - Mirror the scope's waveforms live (Priority: P2)

Once connected, the engineer sees on the PC the same waveforms the scope is showing on its own
screen: the same channels, in the same colours, on the same grid of divisions, with the same
vertical scale, offset and timebase, updating continuously as the scope acquires. If someone
changes settings on the scope's front panel, the PC view follows, so the two screens always
match.

**Why this priority**: This is the core value of the feature: seeing on the PC exactly what the
scope is measuring.

**Independent Test**: With the scope acquiring a known signal (e.g. its calibration output),
connect and place the PC view next to the scope screen; verify the same channels appear with
the same shape, position, amplitude and period, and that both update together.

**Acceptance Scenarios**:

1. **Given** the app is connected and channels 1, 3 and 4 are on at the scope, **When** the live
   view is shown, **Then** exactly those three channels are plotted, each in its scope colour,
   and they update continuously.
2. **Given** a live view is running, **When** the user compares it with the scope's screen,
   **Then** each waveform sits at the same position on the same grid of divisions, with the
   same vertical scale, offset, timebase and trigger position.
3. **Given** a live view is running, **When** someone turns a channel on or off or changes its
   vertical scale, offset or the timebase at the scope, **Then** the PC view reflects the change
   within 2 seconds.
4. **Given** a live view is running, **When** the scope's acquisition is stopped at the scope,
   **Then** the app keeps showing the last acquired waveform, as the scope does, and indicates
   that the scope is stopped, without restarting acquisition.
5. **Given** a live view is running, **When** the user pauses the live view in the app, **Then**
   the PC display freezes on the current waveforms while the scope keeps running, and resuming
   continues live updates.
6. **Given** several channels are plotted, **When** the user hides one channel in the app,
   **Then** it disappears from the PC plot only, and the scope's own channel setting is
   unchanged.

---

### Edge Cases

- **Wrong or unreachable address**: connect fails within 10 seconds with a clear message; no hang.
- **Connection lost during live view** (cable pulled, scope powered off): detected and reported
  within 5 seconds; the last waveforms stay visible but are clearly marked as stale (not live);
  the user can reconnect without restarting the app.
- **Scope busy or held by another remote client**: when connecting, the app reports that the
  instrument is busy instead of freezing, and lets the user retry. During live view, a briefly
  busy scope is retried automatically; the connection is only declared lost if the scope stays
  unresponsive beyond the 5-second limit.
- **Another program changes scope settings remotely** while the app is open: the app adapts
  (same as front-panel changes) and keeps working.
- **Another program polls the scope at the same time** (verified: the scope hands replies to
  whichever client reads first): a reply that does not match the question is never shown as
  data. Isolated mismatches are discarded and retried; if they keep occurring, the app stops
  polling, marks the traces stale and shows "Another program is using the scope - reconnect
  when it has finished".
- **Instrument at the address is not a supported LeCroy scope**: the app shows the identity it
  received, warns that the model is unsupported, and lets the user cancel or continue at their
  own risk.
- **No channels turned on at the scope**: the plot area shows a message such as "No channels
  enabled on the scope" instead of an empty plot.
- **Very long record lengths** (millions of points): the view stays responsive; the update rate
  may drop, and the actual update rate is shown so the user knows.
- **Trigger never fires** (e.g. normal trigger mode with no signal): the app shows that the scope
  is waiting for a trigger and keeps the last waveform, rather than reporting an error.
- **Closing the app during a transfer**: the app closes promptly and ends the session cleanly.
- **Scope set to a multi-grid layout** (dual/quad grid): the PC still draws all channels on a
  single grid, each at its correct scale and position, and shows a note that the scope is using
  a multi-grid layout.

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

**Live view (mirroring the scope)**

- **FR-008**: While connected, the system MUST continuously display the waveforms of each analog
  channel (C1–C4) that is turned on at the scope, and MUST NOT plot channels that are off.
- **FR-009**: All displayed data MUST come from the connected scope; the application MUST NOT
  generate, simulate or fabricate waveform data under any circumstance.
- **FR-010**: The plot MUST reproduce the scope's display geometry: the same grid of divisions
  (horizontal and vertical), and each waveform drawn at the same vertical position (scale and
  offset) and horizontal position (timebase and trigger position) as on the scope's screen.
  Only the single-grid layout is reproduced; when the scope uses a multi-grid layout, all
  channels are drawn on one grid and the user is told the scope's layout differs.
- **FR-011**: Waveforms MUST be shown in physical units (volts and seconds) derived from the
  scope's current settings, so values can be read off the axes or cursor readout.
- **FR-012**: Each channel MUST be drawn in the same colour the scope uses for that channel.
- **FR-013**: The system MUST show, for each displayed channel, its vertical scale (V/div) and
  offset, plus the scope's timebase (time/div) and trigger/acquisition state
  (e.g. Auto, Normal, Single, Stopped, Waiting for trigger).
- **FR-014**: Changes made at the scope (channel on/off, vertical scale, offset, timebase,
  trigger position) MUST be reflected in the view within 2 seconds.
- **FR-015**: The system MUST indicate how fresh the data is (live update rate and/or time of
  the last update), and mark waveforms as stale when no new data arrives because of an error.
- **FR-016**: Users MUST be able to pause and resume the live view; pausing affects only the
  application's display, never the scope.
- **FR-017**: Users MUST be able to hide and show individual channels in the application's plot
  without changing the scope.

**Safety & robustness**

- **FR-018**: This feature MUST NOT change any setting or state of the scope (including channel
  settings, timebase, trigger mode, and acquisition run/stop); it only reads.
- **FR-019**: The window MUST remain responsive (moving, resizing, pausing, disconnecting) during
  connection attempts, data transfers and connection failures.
- **FR-020**: Connection events and errors MUST be recorded in a log the user can consult when
  troubleshooting.
- **FR-021**: Every reply from the scope MUST be checked to belong to the question that was
  asked (e.g. a timebase reply to a timebase query, a channel 3 waveform to a channel 3
  request); mismatched replies MUST never be displayed. After 3 consecutive cycles with
  mismatched replies, the system MUST stop polling, keep the last waveforms marked stale, and
  report that another program is using the scope.

### Key Entities

- **Instrument Connection**: the session with the oscilloscope; has an address and a state
  (Disconnected, Connecting, Connected, Error/Lost).
- **Instrument Identity**: manufacturer, model, serial number, firmware version of the connected
  scope.
- **Channel**: one analog input (C1–C4); has an on/off state at the scope, vertical scale,
  offset, display colour, and a local shown/hidden state in the app.
- **Acquisition Settings**: timebase (time/div), trigger position, trigger mode and acquisition
  state at the scope.
- **Waveform**: the latest acquired trace for one channel as read from the scope; sample values
  in volts with their time axis, and the time it was received.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user who knows the scope's address goes from launching the app to seeing live
  waveforms in under 30 seconds.
- **SC-002**: With four channels on and up to 100,000 points per channel, the live view
  refreshes at least 5 times per second on the lab network. For longer records the refresh rate
  is bounded by the scope's readout speed (about 1.5 refreshes/s at 500,000 points × 3
  channels); this is acceptable as long as the achieved rate is displayed. Waveforms are always
  shown at the full resolution the scope provides.
- **SC-003**: The window responds to user input within 0.2 seconds at all times, including
  during connection, data transfer and connection loss.
- **SC-004**: In 100% of tested connection-loss scenarios (cable unplugged, scope powered off),
  the loss is reported within 5 seconds and the app neither freezes nor crashes.
- **SC-005**: After a 10-minute live-view session, the scope's settings are identical to those
  before the session (zero changes caused by the app).
- **SC-006**: Placed side by side with the scope's screen, every displayed waveform matches the
  scope's trace in position and shape within 0.1 division, and voltage/time values for the
  scope's calibration signal match the scope's own readings within 2% of full scale.

## Assumptions

- One user, one scope at a time: the LeCroy WaveRunner 610Zi in the lab, reachable over the
  local network (currently at `192.168.0.9`). The application has no simulated or demo mode;
  without a reachable scope it only offers connecting.
- Only the four analog channels (C1–C4) are in scope; math, zoom, memory and digital traces and
  the measurement table are out of scope for this feature (confirmed in Clarifications).
- Changing scope settings from the app (scale, timebase, trigger, run/stop) is out of scope and
  will be a later feature; this feature is read-only.
- Saving, exporting or measuring waveforms is out of scope and will be a later feature.
- For very long records, the display may draw a reduced-resolution version of the real data as
  long as its visible shape is faithful to the scope's trace; full-resolution data is a concern
  of a later capture/export feature.
- People may keep using the scope's front panel while the app is connected; the app adapts to
  their changes rather than preventing them. Other remote programs cannot safely talk to the
  scope at the same time as the app (the scope shares one reply queue between clients and does
  not enforce locks); the app detects this and steps back (FR-021).
- Automated tests may substitute a fake instrument inside the test suite only (per the
  constitution); this never affects what the application shows.
- The application runs on the lab's Windows 11 PCs.
- The user interface is in English only, using the scope's own terminology (e.g. Trigger,
  V/div, Stopped).
