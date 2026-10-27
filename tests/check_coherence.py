"""Do the channels of one live read come from the same trigger?

Reads the enabled channels the way the app does (``WF? DESC`` of the first, then ``WF? ALL`` of
each, one after the other) and prints, per read, two independent checks against the first
channel:

- the trigger time stamp in each channel's descriptor (equal: same trigger);
- the time of each channel's first leading edge at 50 % (steady from read to read: same trigger,
  when the signals are locked in phase on the scope).

Run it with the scope running, then with it stopped (or in Single) for comparison::

    uv run python tests/check_coherence.py --reads 30

Read-only: it uses the app's driver, so only allowlisted queries are sent.
"""

import argparse
import math
import sys

from scope_gui.analysis import Trace
from scope_gui.driver import ScopeDriver
from scope_gui.models import Waveform
from scope_gui.settings import load_last_address


def read_set(driver: ScopeDriver) -> dict[str, Waveform]:
    channels = driver.read_status().enabled_channels
    if not channels:
        return {}
    driver.read_descriptor(channels[0])
    return {ch: driver.read_waveform(ch) for ch in channels}


def leading_edge(waveform: Waveform) -> float:
    times = Trace(waveform).leading(0.5)
    return float(times[0]) if times.size else math.nan


def compare(waves: dict[str, Waveform]) -> tuple[bool, dict[str, float], dict[str, float]]:
    """Same trigger for all?, trigger stamp and edge time of each channel minus the first's."""
    first, *others = waves.values()
    edge = leading_edge(first)
    stamps = {w.channel: w.trigger_time - first.trigger_time for w in others}
    edges = {w.channel: leading_edge(w) - edge for w in others}
    return all(d == 0 for d in stamps.values()), stamps, edges


def _ns(value: float) -> str:
    return "      -" if math.isnan(value) else f"{value * 1e9:+7.2f}"


def _us(value: float) -> str:
    return f"{value * 1e6:+12.3f}"


def run(driver: ScopeDriver, reads: int) -> int:
    """Print one line per read; returns how many reads had every channel on one trigger."""
    same = 0
    for n in range(1, reads + 1):
        waves = read_set(driver)
        if len(waves) < 2:
            print("Need at least two channels on.")
            return 0
        coherent, stamps, edges = compare(waves)
        same += coherent
        if n == 1:
            ref = next(iter(waves))
            print(f"Against {ref}: trigger stamp difference (µs) | first 50 % edge difference (ns)")
            print(
                "read  "
                + "".join(f"{ch:>13}" for ch in stamps)
                + "  |"
                + "".join(f"{ch:>8}" for ch in edges)
            )
        print(
            f"{n:>4}  "
            + "".join(_us(d) for d in stamps.values())
            + "  |"
            + "".join(f" {_ns(d)}" for d in edges.values())
            + ("" if coherent else "   <-- different triggers")
        )
    print(f"{same} of {reads} reads had every channel from the same trigger")
    return same


def main(argv: list[str] | None = None, driver: ScopeDriver | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--address", default=None, help="default: the app's last address")
    parser.add_argument("--reads", type=int, default=20)
    args = parser.parse_args(argv)
    driver = driver or ScopeDriver()
    if not driver.is_open:
        address = args.address or load_last_address()
        print(f"Connecting to {address} ...")
        print(f"Connected: {driver.connect(address)}")
    try:
        same = run(driver, args.reads)
    finally:
        driver.close()
    return 0 if same == args.reads else 1


if __name__ == "__main__":
    sys.exit(main())
