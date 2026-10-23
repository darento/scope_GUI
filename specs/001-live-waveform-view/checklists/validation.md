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
| 4 | Side by side with scope screen (channels, colours, positions, trigger) | Pending (visual) | Screenshot of the app on the real scope looks consistent: C1/C3/C4 shown, C2 off; 10 × 8 grid −316…684 ns at 100 ns/div, TRDL −184 ns; trigger at t=0. Colours (research R10) not yet compared against the scope screen |
| 5 | Front-panel changes followed ≤ 2 s | Verified (scales); channel on/off at scope pending | User changed horizontal and vertical scale on the scope: PC followed (C3 1 mV/div, ofs −1 mV → 0 V trace at −1 div; timebase 50 ns/div). Automated: `test_settings_change_and_channel_toggle` |
| 6 | Scope Stop → "Stopped", no restart | Pending (front panel) | Automated: `test_stopped_scope` |
| 7 | Pause / Resume | Verified (automated) | `test_pause_freezes_display_but_worker_keeps_running` |
| 8 | Hide channel locally | Verified (hardware) | User unticked C1 and C4 in the app: hidden on the PC only, scope settings still listed (still on at scope); `test_hiding_a_channel_is_local_only` |
| 9 | Cable unplugged → Lost ≤ 5 s, reconnect | Verified (Lost); reconnect pending | User unplugged the cable: Lost 0.9 s into the failing cycle, traces kept and marked STALE (log 15:52:58). Reconnect after replug covered by `test_cable_unplugged_shows_not_live`; to confirm on hardware |
| 10 | ≥ 5 updates/s at 100k pts × 4 ch | Pending (needs record length change at scope) | Measured 8.2–8.7 updates/s at 10k pts × 3 ch on the real scope |
| 11 | Window responsive during transfers/loss | Pending (interactive) | Automated: `test_window_responsive_while_connecting`; all I/O in worker thread |
| 12 | Scope settings unchanged after session | Verified (30 s) | `test_live_read_only` (hardware): 24 settings identical before/after; every command sent matched the allowlist. 10-minute run pending |
| 13 | Log folder shows events and commands | Pending (interactive) | Rotating log configured in `__main__.setup_logging` |

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
