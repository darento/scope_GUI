# Validation: Synchronized Capture

**Feature**: [spec.md](../spec.md) · **Date**: 2026-10-27 · **PC**: the lab development PC
(Windows 11, Python 3.13)

## T024 Suite and lint

- `uv run pytest`: 591 passed, 4 deselected (the hardware tests), 55 s.
- `uv run ruff check`: all checks passed. `uv run ruff format --check`: 56 files formatted.
- `uv run pytest -m hardware --collect-only`: 4 tests, including the new
  `test_synchronized_capture` (not run: scope disconnected).

## T024 Bench update rate, mode off vs on

Launcher bench (`tests/bench.py`, Auto, 200 triggers/s, demo measurement set), 200k points,
window shown, 8 s per mode after 2 s settling. Updates measured per second.

| Channels × 200k | Mode off | Mode on | Written while on |
|---|---|---|---|
| 2 | 2.9/s | 5.4/s | `ARM`, `TRMD AUTO` (on switch-off) |
| 4 | 1.2/s | 5.1/s | `ARM`, `TRMD AUTO` (on switch-off) |

- No `FRTR` was needed: at 200 triggers/s every armed acquisition triggered within 0.5 s.
- Mode off is slower on the bench only. In the running model every channel read finds a newer
  trigger, so the bench builds a new 4 × 200k acquisition (111 ms median) for each channel
  read. With the mode on it builds one per update. The real scope has no such cost, so the
  bench says nothing about the real off-mode rate.
- SC-002 (at least 5 updates/s with the mode on at 2 µs/div, 200k points, 2 channels) needs
  the real scope (T025). The 2026-10-27 experiment (`ARM` then reading all channels) gave about
  7 reads/s.

## T025 Real scope

Pending: the scope was disconnected. Run quickstart.md R1–R9 and `uv run pytest -m hardware`,
then record SC-001 to SC-004 here.
