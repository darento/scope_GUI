"""Capture real replies from the scope as test fixtures (dev tool, read-only).

Run manually with the scope on the network:

    uv run python tests/fixtures/capture_fixtures.py [address]

Only queries from the driver allowlist (contracts/scope-driver.md) are sent.
"""

import gzip
import json
import sys
from pathlib import Path

import pyvisa

HERE = Path(__file__).parent
CHANNELS = ("C1", "C2", "C3", "C4")
GLOBAL_QUERIES = ["*IDN?", "CHDR?", "CFMT?", "CORD?", "WFSU?", "TDIV?", "TRDL?", "TRMD?", "GRID?"]
CHANNEL_QUERIES = ["TRA?", "VDIV?", "OFST?", "CPL?"]


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.9"
    rm = pyvisa.ResourceManager("@py")
    scope = rm.open_resource(f"TCPIP0::{host}::inst0::INSTR", timeout=10000)
    try:
        replies = {q: scope.query(q).strip() for q in GLOBAL_QUERIES}
        for ch in CHANNELS:
            for q in CHANNEL_QUERIES:
                cmd = f"{ch}:{q}"
                replies[cmd] = scope.query(cmd).strip()
        (HERE / "wr610zi_replies.json").write_text(json.dumps(replies, indent=2) + "\n")
        for ch in CHANNELS:
            scope.write(f"{ch}:WF? DESC")
            (HERE / f"{ch.lower()}_desc.bin").write_bytes(scope.read_raw())
        scope.write("C1:WF? ALL")
        with gzip.open(HERE / "c1_wf_all.bin.gz", "wb") as f:
            f.write(scope.read_raw())
    finally:
        scope.close()
    print(json.dumps(replies, indent=2))


if __name__ == "__main__":
    main()
