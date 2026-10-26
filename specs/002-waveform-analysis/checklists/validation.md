# Validation: Waveform Analysis

**Feature**: [spec.md](../spec.md) · **Date**: 2026-10-26 · **PC**: the lab development PC
(Windows 11, Python 3.13)

## T039 Performance (GUI thread, per acquisition)

Ten measurements (the bench demo set plus Area C2, Period C1, Edge count C1), synthetic bench
signals on 4 channels, window 1400 × 900 (plot area 1127 × 450 px), Infinite persistence with
the image repainted on every acquisition (worst case; in the app it is repainted at most every
100 ms). Medians.

| Points × 4 | measure_all (10) | persistence add / image | live view alone | draw turn | analysis turn |
|---|---|---|---|---|---|
| 10,000 | 1.3 ms | 4.4 / 7.3 ms | 8 ms | 21 ms | 20 ms |
| 100,000 | 5.3 ms | 5.0 / 8.8 ms | 30 ms | 23 ms | 24 ms |
| 2,500,000 | 69.8 ms | 9.0 / 7.5 ms | 202 ms | 131 ms | 100 ms |

- Draw turn: traces, persistence and the window repaint. Analysis turn: measurements, table and
  histogram. They run in separate event-loop turns, so input is handled in between.
- Plan goals: analysis ≤ 10 ms at 100k (5.3 ms) ✓; persistence ≤ 40 ms at 100k (13.8 ms) ✓;
  no GUI stall above 0.2 s at 2.5M × 4 (FR-021): 131 ms and 100 ms ✓.

What it took (the first measurement gave 206 ms of analysis and 830 ms per acquisition at 2.5M):

1. Crossing search on the thresholds' transitions instead of every sample, and crossings shared
   by several measurements computed once per acquisition (analysis 206 → 70 ms at 2.5M).
2. Measurements table: cells set only when their text changes and columns fitted once per
   update; `ResizeToContents` re-measured every row after every cell (≈ 0.3 ms a cell).
3. Curves: peak downsampling and clip-to-view set on the PlotItem. Since feature 001 they were
   set per curve and silently overwritten by `PlotItem.addItem`, so every point was drawn
   (live view alone at 2.5M × 4: 736 → ~200 ms). The trace time ramp is cached per timebase.
4. Analysis runs in the event-loop turn after drawing.

## Responsiveness on the bench (user report: Infinite persistence "gets stuck")

Cause: the worker sent acquisitions as fast as the bench produced them; with persistence on, a
maximised window needed more GUI time per acquisition than the bench period, so queued
acquisitions grew without end and input was never handled. Fix: the worker sends the next
waveforms only after the window has drawn and measured the previous ones (a slow GUI lowers the
rate instead), and the persistence image is repainted at most every 100 ms.

Bench, 10k points, window maximised, Infinite persistence, 6 s (20 ms GUI timer):

| Bench rate | Timer gap median / max | Shown rate |
|---|---|---|
| 20 /s | 22 / 69 ms | 19.3 /s |
| 200 /s | 24 / 79 ms | 13.5 /s |
