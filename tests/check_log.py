"""Which commands did the app send to the scope? (SC-007, FR-020, SC-004)

Reads the debug log written with ``SCOPE_GUI_DEBUG=1`` (every read-only command is logged as
``query <command>``, every acquisition-control command of Synchronized capture as
``write <command>``), counts each command and checks it against the driver's allowlists: queries
against ``ALLOWED_COMMANDS``, writes against ``CONTROL_COMMANDS``. The control writes are listed
in their own block, so a read-only session shows 0 of them::

    uv run python tests/check_log.py --since "2026-10-27 09:30"

Exit code 0: commands were found and all are allowlisted; 1 otherwise (a command in neither
list, a query that is a control command, or a write that is a read-only query).
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from scope_gui.driver import is_allowed, is_control_allowed
from scope_gui.settings import log_dir

# "2026-10-27 09:30:01,123 DEBUG   [scope-io] scope_gui.driver: query C1:WF? ALL (binary, ...)"
# "2026-10-27 09:30:01,124 DEBUG   [scope-io] scope_gui.driver: write ARM"
LINE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ .*? scope_gui\.driver: "
    r"(?:query (?P<query>.+?)(?: \((?:binary, timeout \d+ ms|recover)\))?|write (?P<write>.+))$"
)


def sent_commands(files: list[Path], since: str = "") -> tuple[Counter, Counter]:
    """Count of each query and of each control write sent, from the given time on."""
    queries: Counter = Counter()
    writes: Counter = Counter()
    for path in files:
        with path.open(encoding="utf-8", errors="replace") as log:
            for line in log:
                match = LINE.match(line.rstrip("\n"))
                if match and match[1] >= since:
                    if match["query"] is not None:
                        queries[match["query"]] += 1
                    else:
                        writes[match["write"]] += 1
    return queries, writes


def report(counts: Counter, allowed) -> int:
    """Print the counts, most frequent first; return how many different commands are refused."""
    refused = 0
    for command, n in sorted(counts.items(), key=lambda item: -item[1]):
        flag = ""
        if not allowed(command):
            flag = "   <-- NOT ALLOWLISTED"
            refused += 1
        print(f"{n:>9}  {command}{flag}")
    return refused


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", default="", help='only lines from this time, "YYYY-MM-DD HH:MM"')
    parser.add_argument("--log-dir", type=Path, default=None, help="default: the app's log folder")
    args = parser.parse_args(argv)
    folder = args.log_dir or log_dir()
    files = sorted(folder.glob("scope_gui.log*"), key=lambda f: f.stat().st_mtime)
    queries, writes = sent_commands(files, args.since)
    if not queries and not writes:
        print(f"No commands found in {folder} (was SCOPE_GUI_DEBUG=1 set? is --since right?)")
        return 1
    refused = report(queries, is_allowed)
    if writes:
        print("Acquisition-control writes (Synchronized capture):")
        refused += report(writes, is_control_allowed)
    total = sum(queries.values()) + sum(writes.values())
    n_writes = sum(writes.values())
    if refused:
        print(f"FAIL: {refused} command(s) outside the allowlist ({total} commands in all)")
        return 1
    print(
        f"PASS: all {total} commands ({len(queries) + len(writes)} different) are allowlisted; "
        f"{n_writes} acquisition-control writes"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
