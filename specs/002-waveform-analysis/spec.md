# Feature Specification: Waveform Analysis

**Feature Branch**: `002-waveform-analysis`

**Created**: 2026-10-26

**Status**: Draft

**Input**: User description: "use the synthetic approach to simulate waveforms (usually we
visualize square signals, and SiPM kind of analog signals) and implement several
functionalities you find useful: plotting delta time between different thresholds of different
channels, histograms, zoom... anything that can help extracting information from the signals,
as we are processing the waveform when doing the visualization."

## Clarifications

### Session 2026-10-26

- Q: When Pause freezes the display, do statistics and histograms also stop accumulating?
  → A: Yes; paused means everything is frozen, so what is shown is what was measured.
- Q: Scope settings change during a run (V/div, offset, timebase)? → A: Keep accumulating and
  show a warning note until the user clears the statistics.

### Amendments from planning research (2026-10-26)

Measured on the synthetic bench (see [research.md](research.md)); no change in intent:

- Base and noise come from the whole record even when gated (a tight gate around a pulse gave a
  wrong base) — FR-007.
- Amplitude-relative quantities are missed on noise-only acquisitions (they produced Δt
  outliers of ±100 ns) — FR-007a.
- Histogram range defaults to a robust automatic range (dark-count outliers squeezed the
  timing peak into one bin) — FR-012.
- Persistence is a fading density display, not N overlaid traces (overlaying 20 × 4 traces of
  100k points took 2.3 s per update) — FR-018, US4-5.
- SC-002 is stated for signals where noise jitter is negligible, so it checks the analysis and
  not the bench's noise.

From `/speckit-analyze` (2026-10-26):

- US2 and US3 independent tests quantified; the US2 jitter check uses 20 photoelectrons
  (dark-count outliers at 3 photoelectrons).
- FR-002 noise is band-limited (as on a real scope), not white.
- Hysteresis edge case matches R4 (5 % of amplitude or 3 × noise rms); noise is at least one
  digitiser step (flat signals) — FR-007a.
- FR-018 fade lengths are the offered choices 10 / 100 / 1000.
- FR-021 made measurable (0.2 s, 10 %); at 2.5M points the reference levels use ≤ 100k samples
  and persistence is rasterised per pixel column to stay within it (research R1, R7).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Synthetic signal bench for development and demos (Priority: P1)

A developer (or an engineer preparing a demo) wants to work on the analysis tools without
occupying the shared scope. They start a separate test-bench command that opens the normal
application connected to a *synthetic* scope. That scope produces the kinds of signals the lab
usually looks at: a square clock, two SiPM-like detector signals (random number of
photoelectrons, fast rise, exponential decay, dark counts, noise, one positive and one negative
polarity, arriving close together in time with known jitter) and a NIM discriminator output
that fires from one of the SiPM signals after a fixed delay. Because the true values (delays,
jitters, photoelectron gain, clock frequency) are known, the analysis results can be checked
against them.

**Why this priority**: The scope is shared and not always free (Constitution IV). Every other
story is developed, tested and demonstrated on this bench first, then confirmed on the real
scope.

**Independent Test**: Run the bench command, press Connect, and verify the window shows four
live, changing traces (clock, positive pulses, negative pulses, NIM pulse) with the scope's
grid, colours and update-rate readout, and that the window title and identity clearly say the
signals are synthetic.

**Acceptance Scenarios**:

1. **Given** the bench command is started, **When** the user presses Connect, **Then** the
   identity shows a synthetic instrument and the four traces update continuously.
2. **Given** the normal application (`scope-gui`), **When** it is started, **Then** there is
   no way to reach the synthetic scope from it; it still only talks to a real instrument.
3. **Given** the bench is running, **When** the user looks at consecutive acquisitions,
   **Then** pulse heights vary in discrete photoelectron steps, some acquisitions have no
   pulse (and no NIM pulse), and occasional extra small pulses (dark counts) appear at random
   times.

---

### User Story 2 - Measurements with running statistics (Priority: P1)

An engineer wants numbers, not just pictures. They add measurements to a list, for example:
"time between C2 crossing 30 mV rising and C4 crossing −400 mV falling", "time between C2 and
C3 at 20 % of their amplitude (constant fraction)", "amplitude of C2", "area of C2",
"frequency and duty cycle of C1", "rise time of C2". For every new acquisition each
measurement is computed from the received waveform, and a table shows its last value and
running statistics: mean, standard deviation, minimum, maximum, number of values and number
of acquisitions where it could not be measured. The engineer can edit or remove a measurement
and clear the statistics at any time.

**Why this priority**: Timing between thresholds of different channels and pulse properties
are the information the lab extracts from these signals; this is the core of the feature.

**Independent Test**: On the bench, add "Δt C2 lead 20 % → C3 lead 20 %" and "Frequency C1";
with about 20 photoelectrons per pulse (`--mean-pe 20`), after a few hundred acquisitions the
Δt mean is within 20 ps of the known 2 ns delay, its standard deviation within 10 % of the
known combined jitter, and the frequency reads 10 MHz. (With the default 3 photoelectrons,
dark counts make a quarter of the Δt values outliers, so only the histogram fit of User Story 3
gives the jitter there.)

**Acceptance Scenarios**:

1. **Given** live acquisitions, **When** the user adds a Δt measurement between two channels
   with a level and an edge for each, **Then** a new row appears and updates once per new
   acquisition.
2. **Given** a level given as a percentage, **When** the pulse amplitude changes from one
   acquisition to the next, **Then** the crossing is taken at that percentage of each
   acquisition's own amplitude (constant fraction), for positive and negative pulses alike.
3. **Given** an acquisition where a measurement cannot be made (no crossing, channel off,
   signal flat), **Then** no value is added for it and its "missed" count increases.
4. **Given** accumulated statistics, **When** the user presses Clear, **Then** all counts
   restart from zero.
5. **Given** the user edits a measurement's definition, **Then** that measurement's statistics
   restart; the others are unaffected.
6. **Given** measurements were defined, **When** the application is restarted, **Then** the
   same measurements are listed again (with empty statistics).

---

### User Story 3 - Distributions: histogram, trend and correlation (Priority: P2)

The engineer selects a measurement and sees its histogram growing live, for example the Δt
distribution of a SiPM coincidence (timing resolution) or the amplitude spectrum of a SiPM
(photoelectron peaks). They can fit a Gaussian to the main peak and read its mean, sigma and
FWHM, switch to a logarithmic count axis, change the number of bins, view the measurement's
trend over acquisitions, or plot it against another measurement (e.g. Δt versus amplitude to
see time walk).

**Why this priority**: Distributions are how timing resolution and detector spectra are
judged; this turns the statistics into physics results. Depends on User Story 2.

**Independent Test**: On the bench, select the C2 amplitude measurement and verify the
histogram shows separate peaks spaced by the known photoelectron amplitude; select the
constant-fraction Δt and verify the fitted mean is within 20 ps of 2 ns and the fitted sigma
within 15 % of the known combined jitter (default scene; within 10 % with 20 photoelectrons,
SC-002).

**Acceptance Scenarios**:

1. **Given** a selected measurement, **When** new acquisitions arrive, **Then** its
   histogram updates, labelled with the measurement's name and unit.
2. **Given** "Fit Gaussian" is on, **Then** the fitted curve is drawn over the histogram and
   its mean, sigma and FWHM are shown; if no sensible fit exists, the app says so instead of
   showing numbers.
3. **Given** the trend view, **Then** values are shown in acquisition order, with gaps where
   the measurement was missed.
4. **Given** the correlation view and a second measurement chosen, **Then** each acquisition
   where both were measured is a point (second measurement on the horizontal axis, selected
   on the vertical axis).

---

### User Story 4 - Inspecting the waveform: zoom, cursors, thresholds, persistence (Priority: P2)

The engineer zooms into a rising edge to look at it closely, pans around, and returns to the
scope's own screen with one action. They switch on two time cursors and read the time between
them and each channel's voltage at each cursor. They can restrict all measurements to the time
window between the cursors (a gate), e.g. to measure only the pulse and not a later dark count.
The level of a selected threshold measurement is drawn on the plot as a line in the channel's
colour, and dragging the line changes the level. A persistence mode shows where recent
acquisitions went, fading out over about N acquisitions (or never, until cleared), so the
photoelectron "bands" of a SiPM or the jitter of an edge become visible.

**Why this priority**: These make the measurements understandable and easy to set up, but the
measurements and distributions are useful without them.

**Independent Test**: On the bench, box-zoom on the C1 edge at t = 0, verify the axes show the
zoomed region and stay there while acquisitions continue, then reset and verify the view
matches the scope screen again. Enable cursors, place them 100 ns apart and verify the readout
shows 100 ns and 10 MHz.

**Acceptance Scenarios**:

1. **Given** a zoomed view, **When** new acquisitions or setting changes arrive, **Then** the
   zoom is kept until the user resets it; after reset the view follows the scope screen again.
2. **Given** cursors on, **When** the user drags a cursor, **Then** Δt, 1/Δt and each visible
   channel's voltage at both cursors update immediately and with each new acquisition.
3. **Given** "gate between cursors" is selected, **Then** the gated window is shaded on the
   plot and measurements use only samples inside it.
4. **Given** a selected measurement with a level in volts, **When** the user drags its line,
   **Then** the measurement's level becomes the dropped value and its statistics restart.
5. **Given** persistence set to N, **Then** behind the current traces each channel shows, in
   its colour, how often recent acquisitions passed through each point of the screen, older
   ones fading out over about N acquisitions; "infinite" never fades; Off removes it. Zooming,
   resetting the view or a scale change restarts the persistence.

---

### User Story 5 - Export measurements (Priority: P3)

After a run, the engineer exports all accumulated measurement values to a CSV file (one row per
acquisition, one column per measurement, plus the acquisition's trigger time) for offline
analysis.

**Why this priority**: Valuable for reports and deeper analysis, but the in-app statistics
cover day-to-day use.

**Independent Test**: Accumulate 500 acquisitions with three measurements, export, and verify
the file has 500 rows, a header with the three measurement names and empty cells where a value
was missed.

**Acceptance Scenarios**:

1. **Given** accumulated values, **When** the user exports, **Then** a CSV file is written
   without freezing the window and the status bar confirms where it was saved.
2. **Given** a measurement added after others, **Then** its column is empty for the
   acquisitions before it existed.

---

### Edge Cases

- Channel used by a measurement is switched off at the scope: the measurement counts as
  missed; it resumes when the channel is back on.
- Scope settings (V/div, offset, timebase, channel on/off) change during a run: statistics keep
  accumulating and a note "Scope settings changed during this run" is shown until the
  statistics are cleared (FR-022).
- Signal clipped at the top or bottom of the screen (saturated SiPM pulses): values are
  measured on the clipped samples, as the scope would; the amplitude histogram shows the
  pile-up at the clipping level.
- Noise riding on a threshold: a crossing only counts again after the signal has moved back
  past the level by a small hysteresis (5 % of the signal's amplitude or 3 × its noise rms,
  whichever is larger), so noise does not create extra edges.
- Flat signal, or noise smaller than one digitiser step: the noise level is taken as at least
  one digitiser step, so amplitude-relative quantities are missed instead of measured on a
  one-step wiggle (FR-007a).
- Gate narrower than two samples, or entirely outside the record: every measurement is missed.
- Pause pressed: statistics, histograms and the export history stop accumulating too, so what
  is shown is exactly what was measured; they continue on Resume (FR-023).
- Connection lost or scope stopped: no new acquisitions, so statistics stop growing; they are
  kept (and can be exported) until cleared, also after Disconnect.
- Very long runs: at most the last 100,000 values per measurement are kept; older ones drop
  out of statistics, histogram and export.
- Persistence or many measurements at large record lengths must not freeze the window; if
  the PC cannot keep up, the update rate drops (it is shown), but nothing blocks.

## Requirements *(mandatory)*

### Functional Requirements

**Synthetic bench (test-only)**

- **FR-001**: The project MUST provide a developer command that opens the application connected
  to a synthetic scope; the synthetic scope MUST live with the tests, go through the same
  driver path as the real scope, and MUST NOT be reachable from the shipped application
  (Constitution I and IV).
- **FR-002**: The synthetic scope MUST produce: a square clock, a positive and a negative
  SiPM-like signal (Poisson-distributed photoelectron count with per-photoelectron gain
  spread, fast rise, exponential decay, random dark counts, band-limited noise, Gaussian arrival
  jitter) and a NIM logic pulse fired by one SiPM signal crossing a discriminator level; the
  scope's 8-bit resolution and screen clipping MUST be reproduced.
- **FR-003**: The synthetic scope's signal parameters (rates, delays, jitters, amplitudes,
  record length, acquisition rate) MUST be known to tests so results can be checked against
  true values; the window MUST make clear that the signals are synthetic.

**Measurements and statistics**

- **FR-004**: Users MUST be able to add, edit and remove measurements. Available types:
  Δt @ level (between two channels or two levels of one channel), Time @ level (relative to
  the trigger), Edge count @ level, Amplitude, Base, Top, Maximum, Minimum, Pk-Pk, Mean,
  Area, Rise time 10–90 %, Fall time 90–10 %, Width @ 50 %, Period, Frequency, Duty cycle.
- **FR-005**: Levels MUST be settable in volts or as a percentage of the signal's amplitude
  (constant fraction), each with an edge (rising/falling; for percentages, leading/trailing).
  Δt is "second crossing time minus first crossing time", each the first crossing in the
  record (or gate).
- **FR-006**: Crossing times MUST be interpolated between samples, so timing results are finer
  than the sample interval.
- **FR-007**: Base and top MUST be estimated per acquisition and channel: for square-like
  signals the typical low and high levels; for narrow pulses the baseline and the peak; for
  negative pulses top is below base. Base (and the noise level) always come from the whole
  record; for pulses, top is the peak inside the gate. Amplitude = top − base; percentage
  levels, rise/fall time, width, period and duty cycle are relative to base and top; Area is
  the integral of (signal − base) over the record or gate (volt-seconds).
- **FR-007a**: Quantities relative to the amplitude (percentage levels, rise/fall time, width,
  period, duty cycle) MUST count as missed when the signal does not stand out of its noise
  (amplitude below 5 × the noise rms, the noise being at least one digitiser step), instead of
  returning values computed on noise.
- **FR-008**: Each new acquisition MUST be measured exactly once; measurements MUST use every
  received acquisition of the channel even if it is hidden on the PC.
- **FR-009**: For each measurement the app MUST show last value, mean, standard deviation,
  minimum, maximum, count and missed count, with units, updated per acquisition.
- **FR-010**: Users MUST be able to clear all statistics; editing a measurement MUST clear
  only its own statistics.
- **FR-011**: The list of measurement definitions MUST be remembered between sessions.

**Distributions**

- **FR-012**: Users MUST be able to show, for the selected measurement, a histogram with
  adjustable bin count and linear/log count axis, a trend over acquisitions, or a
  correlation plot against a second measurement. The histogram range MUST default to a robust
  automatic range around the bulk of the values (so a few outliers do not squeeze the peak
  into one bin) with the number of values outside shown; full range and a manual range MUST
  also be available.
- **FR-013**: Users MUST be able to fit a Gaussian to the histogram's main peak and read mean,
  sigma and FWHM; the fit MUST follow the highest peak and not be pulled by tails or other
  peaks.

**Waveform inspection**

- **FR-014**: Users MUST be able to zoom (box and wheel) and pan the waveform plot, and return
  to the scope's screen with one action (button or double-click). While zoomed, scope updates
  MUST NOT move the view.
- **FR-015**: Users MUST be able to show two draggable time cursors with a readout of Δt,
  1/Δt and each visible channel's voltage at both cursors (taken from the waveform, not the
  mouse position).
- **FR-016**: Users MUST be able to choose the measurement gate: whole record (default) or
  between the cursors; the gate MUST be shown on the plot.
- **FR-017**: The volt levels of the selected measurement MUST be drawn as lines in the
  channel colour; dragging a line MUST set that level.
- **FR-018**: Users MUST be able to switch on a persistence display: per channel, the density of
  recent acquisitions on the screen, fading over about N acquisitions (N = 10, 100 or 1000) or
  infinite until cleared; it restarts when the view or a channel's scale changes.

**Export and safety**

- **FR-019**: Users MUST be able to export accumulated values to CSV (one row per acquisition,
  first column the trigger time, one column per measurement, empty cell when missed), without
  blocking the window.
- **FR-020**: None of the analysis features may send any command to the scope; the
  application stays strictly read-only (feature 001, FR-018, Constitution III).
- **FR-021**: Analysis MUST NOT block the window (no GUI stall above 0.2 s, up to 2.5M points
  × 4 channels); with up to ten measurements the achieved update rate on the real scope MUST
  stay within 10 % of the rate without measurements (SC-005).
- **FR-022**: When the scope's channel or acquisition settings change while statistics hold
  values, the app MUST keep the statistics and show a "Scope settings changed during this run"
  note until they are cleared.
- **FR-023**: While the display is paused, no acquisition MUST be added to the statistics.

### Key Entities

- **Measurement definition**: type, source channel, level (value, volts or percent, edge), and
  for Δt a second channel and level. Has a readable name such as
  "Δt C2 ↑ 30 mV → C4 ↓ -400 mV" and a unit.
- **Measurement history**: one value per processed acquisition (or "missed"), latest 100,000
  kept; summary statistics derive from it.
- **Acquisition record**: the trigger time of each processed acquisition, aligned with the
  histories, used for export.
- **Analysis view state**: selected measurement, view (histogram / trend / correlation), bins,
  log axis, fit on/off, gate mode, cursor positions, zoom, persistence depth (fade length or infinite). GUI-only, never
  sent to the scope.
- **Synthetic scene** (test-only): the signal parameters the synthetic scope generates from,
  and per acquisition the true values (photoelectrons, arrival times).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Starting from a connected live view, a user can define a Δt measurement between
  two channels and see its histogram with a Gaussian fit in under 1 minute.
- **SC-002**: On the synthetic bench, with signals large enough that electronic noise adds
  little timing jitter (≥ 20 photoelectrons on average), after 2,000 acquisitions the fitted
  sigma of the constant-fraction Δt between the two SiPM signals is within 10 % of the true
  combined arrival jitter and its mean within 20 ps of the true delay; with the default scene
  the clock frequency is within 0.1 % of 10 MHz.
- **SC-003**: On noiseless test edges, interpolated crossing times are within 1 % of the
  sample interval of the true crossing.
- **SC-004**: On the bench, the C2 amplitude histogram shows at least four separate
  photoelectron peaks, spaced by the true single-photoelectron amplitude within 5 %.
- **SC-005**: On the real scope at 100k points × 4 channels with ten measurements and the
  histogram shown, the achieved update rate stays within 10 % of the rate with no
  measurements, and the window stays responsive (zoom, drag, menus react within 0.2 s).
- **SC-006**: Exporting 100,000 acquisitions × 10 measurements finishes without freezing the
  window and produces a file that opens in a spreadsheet with the expected rows and columns.
- **SC-007**: During a 10-minute analysis session on the real scope, the app sends only the
  read-only queries of feature 001 (verified from the debug log).

## Assumptions

- Users are the lab's engineers and physicists; they know scope terminology (Δt @ level,
  constant fraction, rise time, FWHM). The UI stays in English.
- Measurements follow common oscilloscope definitions; where scopes differ, the definitions
  in FR-005–FR-007 apply and are documented in the app (tooltips) and README.
- "First crossing" semantics are enough for this version; per-pulse measurements (every
  pulse in a record) and timing walk correction are later features.
- Only C1–C4 are analysed (feature 001 scope); math/memory traces are out of scope.
- Measurements are recomputed on the PC from the transferred samples; the scope's own
  measurement engine (P1–P8 parameters) is not read, which keeps the app read-only and works
  for any measurement the PC defines.
- The synthetic bench is a development and demonstration tool, not a simulation mode of the
  application; spec 001's "no simulated mode" (FR-009) still holds for the shipped app.
- Histograms, trends and correlation use the kept history (latest 100,000 values); the
  correlation plot shows at most the latest 5,000 points to stay responsive.
