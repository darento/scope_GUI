"""Synthetic test bench: the normal window on a synthetic WR610Zi. Developer tool, not a mode.

    uv run python tests/bench.py [--rate 20] [--points 10000] [--seed N] [--mean-pe 3]

Press Connect (any address). The synthetic scope sits behind the real ScopeDriver, so the
allowlist, reply validation, decoding and worker loop run exactly as with the real scope. It
lives only under tests/ (Constitution I, IV); nothing in src/scope_gui knows about it.

The bench never touches the real settings: it uses its own file,
``%LOCALAPPDATA%\\scope_gui\\bench.ini``, and disables the TCP pre-check in this process only.
"""

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from synthetic_scope import Scene, SyntheticScope, synthetic_factory

from scope_gui import driver as driver_module
from scope_gui import settings
from scope_gui.__main__ import setup_logging
from scope_gui.analysis import Edge, Kind, Level, MeasurementSpec
from scope_gui.driver import ScopeDriver
from scope_gui.ui.main_window import MainWindow

TITLE = "Scope GUI — SYNTHETIC test bench"
ADDRESS = "synthetic"

# Added on first start (contracts/synthetic-bench.md).
DEMO_MEASUREMENTS = [
    MeasurementSpec(Kind.DELTA_T, "C2", Level(0.2, True), "C3", Level(0.2, True)),  # timing
    MeasurementSpec(Kind.DELTA_T, "C2", Level(0.030), "C4", Level(-0.4, edge=Edge.FALLING)),
    MeasurementSpec(Kind.DELTA_T, "C1", Level(1.25), "C2", Level(0.030)),  # shows time walk
    MeasurementSpec(Kind.AMPLITUDE, "C2"),  # photoelectron spectrum
    MeasurementSpec(Kind.AREA, "C2"),
    MeasurementSpec(Kind.FREQUENCY, "C1"),
    MeasurementSpec(Kind.RISE_TIME, "C2"),
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tests/bench.py",
        description="Scope GUI on a synthetic WR610Zi: clock (C1), SiPM A/B (C2/C3), NIM (C4).",
    )
    parser.add_argument("--rate", type=float, default=20.0, help="acquisitions per second (20)")
    parser.add_argument("--points", type=int, default=10_000, help="samples per record (10000)")
    parser.add_argument("--seed", type=int, default=None, help="random seed (default: random)")
    parser.add_argument("--mean-pe", type=float, default=3.0, help="mean photoelectrons (3)")
    args = parser.parse_args(argv)
    if args.rate <= 0:
        parser.error("--rate must be positive")
    if args.points < 100:
        parser.error("--points must be at least 100")
    if args.mean_pe < 0:
        parser.error("--mean-pe must not be negative")
    return args


def bench_settings_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    directory = Path(base) / "scope_gui"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "bench.ini"


def use_bench_settings(path: Path) -> None:
    """Replace the settings store in this process only: the real ones are never read or written."""
    settings._settings = lambda: QSettings(str(path), QSettings.Format.IniFormat)


def build_window(args: argparse.Namespace) -> tuple[MainWindow, SyntheticScope]:
    """The bench window (not shown) and its synthetic scope. Needs a QApplication."""
    use_bench_settings(bench_settings_path())
    if not settings.load_measurements():
        settings.save_measurements(DEMO_MEASUREMENTS)
    driver_module.tcp_precheck = lambda host, timeout=3.0: None  # nothing to reach
    scene = Scene(points=args.points, mean_pe=args.mean_pe)
    scope = SyntheticScope(scene, rate_hz=args.rate, seed=args.seed)
    factory = synthetic_factory(scope)
    window = MainWindow(ADDRESS, driver_factory=lambda: ScopeDriver(factory))
    window.setWindowTitle(TITLE)
    return window, scope


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Scope GUI bench")
    window, _scope = build_window(args)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
