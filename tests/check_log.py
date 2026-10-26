"""Which commands did the app send to the scope? (SC-007, FR-020)

Reads the debug log written with ``SCOPE_GUI_DEBUG=1`` (every command is logged as
``query <command>``), counts each command and checks it against the driver's allowlist::

    uv run python tests/check_log.py --since "2026-10-27 09:30"

Exit code 0: commands were found and all are allowlisted; 1 otherwise.
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from scope_gui.driver import is_allowed
from scope_gui.settings import log_dir

# "2026-10-27 09:30:01,123 DEBUG   [scope-io] scope_gui.driver: query C1:WF? ALL (binary, ...)"
LINE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ .*? scope_gui\.driver: query (.+?)"
    r"(?: \((?:binary, timeout \d+ ms|recover)\))?$"
)


def sent_commands(files: list[Path], since: str = "") -> Counter:
    counts: Counter = Counter()
    for path in files:
        with path.open(encoding="utf-8", errors="replace") as log:
            for line in log:
                match = LINE.match(line.rstrip("\n"))
                if match and match[1] >= since:
                    counts[match[2]] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", default="", help='only lines from this time, "YYYY-MM-DD HH:MM"')
    parser.add_argument("--log-dir", type=Path, default=None, help="default: the app's log folder")
    args = parser.parse_args(argv)
    folder = args.log_dir or log_dir()
    files = sorted(folder.glob("scope_gui.log*"), key=lambda f: f.stat().st_mtime)
    counts = sent_commands(files, args.since)
    if not counts:
        print(f"No commands found in {folder} (was SCOPE_GUI_DEBUG=1 set? is --since right?)")
        return 1
    refused = {command: n for command, n in counts.items() if not is_allowed(command)}
    for command, n in sorted(counts.items(), key=lambda item: -item[1]):
        print(f"{n:>9}  {command}{'   <-- NOT ALLOWLISTED' if command in refused else ''}")
    total = sum(counts.values())
    if refused:
        print(f"FAIL: {len(refused)} command(s) outside the allowlist ({total} commands in all)")
        return 1
    print(f"PASS: all {total} commands ({len(counts)} different) are allowlisted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
