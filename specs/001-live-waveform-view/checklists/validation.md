# Validation: Live Waveform View

**Date**: 2026-10-23 · **Scope**: LeCroy WR610Zi, fw 9.1.0, `192.168.0.9` · **Build**: branch
`001-live-waveform-view`

Scenarios from [quickstart.md](../quickstart.md). "Verified" items were checked against the real
scope (or by automated tests where noted). "Pending" items need a person at the scope (front-panel
actions, cable, visual comparison).

| # | Scenario | Result | Evidence |
|---|----------|--------|----------|
| 1 | Connect, identity shown | Verified | App connected; identity `LECROY WR610ZI · SN LCRY3201N55990 · FW 9.1.0`; `test_identity` (hardware) |
| 2 | Wrong address → error ≤ 10 s | Verified | `192.168.0.99`: "Instrument not reachable at 192.168.0.99" after 3.0 s |
| 3 | Address remembered | Verified (automated) | `test_connect_shows_identity_and_saves_address`, `test_last_address_round_trip` |
| 4 | Side by side with scope screen (channels, colours, positions, trigger) | Verified (visual) | User compared the app with the scope screen: same colours and positions on the grid. Default palette (research R10) kept |
| 5 | Front-panel changes followed ≤ 2 s | Verified | User changed horizontal/vertical scale and turned channels on/off on the scope: PC followed (e.g. C3 1 mV/div, ofs −1 mV → 0 V trace at −1 div; 50 ns/div) |
| 6 | Scope Stop → "Stopped", no restart | Verified | User pressed Stop on the scope: app showed Stopped, kept the last trace, did not restart acquisition |
| 7 | Pause / Resume | Verified (automated) | `test_pause_freezes_display_but_worker_keeps_running` |
| 8 | Hide channel locally | Verified (hardware) | User unticked C1 and C4 in the app: hidden on the PC only, scope settings still listed (still on at scope); `test_hiding_a_channel_is_local_only` |
| 9 | Cable unplugged → Lost ≤ 5 s, reconnect | Verified | User unplugged the cable: Lost 0.9 s into the failing cycle, traces kept and marked STALE (log 15:52:58); after replugging, Connect worked without restarting the app. New loss message ("Network link to the scope was interrupted") to be seen after restarting with build `7dff75c`+ |
| 10 | ≥ 5 updates/s at 100k pts × 4 ch | **Not met while acquiring** (scope-limited) | User: ~2.2 updates/s at 100k pts × 4 ch, TDIV 1 µs, AUTO. Measured: scope makes 12.3 acquisitions/s; while it runs, each `WF? ALL` waits for the current acquisition (~80 ms, sometimes 14 ms), so a cycle of descriptor + 4 channels ≈ 5 acquisition periods. With the scope stopped the same transfers take 12–23 ms and full cycles run at 8.75/s: link and app are fast enough, the limit is the scope serving data between acquisitions (research R2) |
| 11 | Window responsive during transfers/loss | Verified | User moved/resized the window, toggled channels and Pause/Resume while live: no freeze, no "Not responding"; `test_window_responsive_while_connecting`; all I/O in the worker thread |
| 12 | Scope settings unchanged after session | Verified (10 min) | `test_live_read_only --live-seconds 600` (hardware): 24 settings identical before/after 601 s live (9.9 updates/s, 3 ch × 5002 pts); every command sent matched the allowlist |
| 13 | Log folder shows events and commands | Verified | User opened Help → Open log folder. New build (started 16:27): a 2-minute session wrote 11 lines (start, connect, identity, CHDR/CFMT/CORD/WFSU replies, state changes, close); no per-query lines unless `SCOPE_GUI_DEBUG=1` |
| 14 | Another program polls the scope (FR-021) | Verified | Second pyvisa client polling `TDIV?`/`C1:VDIV?`: foreign replies refused (never shown), app stopped after 6.4 s with "Another program is using the scope - reconnect when it has finished"; alone: 109 clean cycles in 15 s. `test_worker_conflict`, `test_reply_validation` |

## Issues found and fixed during validation

- Trigger marker drew a plain `QPen` (non-cosmetic) whose 1-unit width is 1 *second* on the time
  axis, flooding the plot orange. Fixed by using `pg.mkPen`; regression test
  `test_all_pens_are_cosmetic`.
- Cable unplug showed the raw Windows socket error (Spanish, `WinError 10054`) in the status and
  the side panel still said "Acquiring". Socket errors now map to `ScopeLost` → "Network link to
  the scope was interrupted"; the side panel shows "State: Not live (last known settings)".
  Regression tests: `test_cable_unplugged_socket_reset`, `test_cable_unplugged_shows_not_live`,
  `test_socket_reset_maps_to_scope_lost`.
- Log grew ~624 KB in 28 s because every query was logged; per-command logging is now opt-in
  (`SCOPE_GUI_DEBUG=1`), rotation raised to 5 MB × 5.
- Two remote clients share the scope's reply queue (the VXI-11 lock is not enforced), so a
  second program made the app receive its replies, and vice versa (found when the hardware test
  ran while the app was connected). Every reply is now checked against its query; after 3 cycles
  with foreign replies the app stops and says another program is using the scope (FR-021,
  research R13).
