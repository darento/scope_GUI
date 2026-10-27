# Contract: User interface

## Switch

- Side panel, Acquisition group: checkbox **Synchronized capture**, enabled only while
  connected; unchecked at start and whenever the connection ends.
- Tooltip: "The app arms one acquisition at a time, so all channels come from the same
  trigger. The scope's trigger mode is restored when this is switched off."
- Toggling emits a queued request to the worker; the checkbox follows `sync_changed` (so it
  unchecks when the worker ends the mode by itself).

## Indicators

- While on: a permanent status-bar label, amber, **"Driving the scope: synchronized capture"**;
  the side panel trigger line reads `Trigger: <remembered mode> (synchronized)`.
- `sync_changed(False, message)` with a message: the message is shown in the status bar.
- Normal mode, mixed update (channels with different trigger times): a permanent status-bar
  label, amber, **"Channels from different triggers - switch Synchronized capture on"**; hidden
  as soon as an update is coherent, while the mode is on, and when not connected.

## Measurements and correlation

- `MeasurementsPanel.process(waveforms, gate, coherent=True)`: for `coherent=False`, specs with
  more than one channel record a miss; others are measured.
- Correlation view: pairs from mixed acquisitions are dropped when the two measurements use more
  than one channel in total; the N shown counts kept pairs.

## Close

- `closeEvent`: while the mode is on, waits up to 3 s for the worker (which restores the
  trigger mode) before aborting I/O; otherwise 1 s as before.
