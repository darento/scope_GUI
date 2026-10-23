# Contract: Scope Driver

**Feature**: 001-live-waveform-view

The driver is the only module allowed to import `pyvisa` or format remote commands
(Constitution Principle I). The GUI and worker depend only on this interface.

## Interface (Python, synchronous; called only from the worker thread)

```python
class ScopeDriver:
    def __init__(self, resource_factory=None) -> None: ...
        # resource_factory(address, timeout_ms) -> VISA-like resource; default opens pyvisa "@py".
        # Tests inject a fake from tests/ (never shipped in the app).

    def connect(self, address: str) -> InstrumentIdentity: ...
        # TCP pre-check (port 111, 3 s), open VXI-11 link, *IDN?. Raises ScopeUnreachable,
        # ScopeBusy, ScopeTimeout.

    def read_status(self) -> ScopeStatus: ...
        # Channel and acquisition settings via the allowlisted setting queries.

    def read_descriptor(self, channel: str) -> WaveformDescriptor: ...
        # Cn:WF? DESC — cheap novelty check (R5).

    def read_waveform(self, channel: str) -> Waveform: ...
        # Cn:WF? ALL — full record, decoded per the descriptor (R3, R6).

    def recover(self) -> bool: ...
        # Device clear + *IDN?; True if the link is healthy again (R4).

    def close(self) -> None: ...
        # Idempotent; safe to call from another thread to abort a pending read (R8).
```

Errors (all subclass `ScopeError`): `ScopeUnreachable`, `ScopeBusy`, `ScopeTimeout`,
`ScopeProtocolError` (malformed reply/descriptor), `ScopeLost`.

## Command allowlist (read-only)

The driver MUST send only these strings (`n` ∈ 1–4). Every one is a query (ends in `?` or is a
`?`-form) and was verified on the WR610Zi fw 9.1.0. A unit test asserts that every command the
driver writes matches this list; any other string raises before reaching the wire (FR-018).

| Command | Purpose | Example reply (CHDR SHORT) |
|---------|---------|---------------------------|
| `*IDN?` | identity, health check | `*IDN LECROY,WR610ZI,LCRY3201N55990,9.1.0` |
| `CHDR?` | header mode for parsing | `CHDR SHORT` |
| `CFMT?` | data format (info/log) | `CFMT DEF9,BYTE,BIN` |
| `CORD?` | byte order (info/log) | `CORD LO` |
| `WFSU?` | transfer setup (info/log) | `WFSU SP,0,NP,0,FP,0,SN,0` |
| `Cn:TRA?` | channel on/off | `C1:TRA ON` |
| `Cn:VDIV?` | V/div | `C1:VDIV 1 V` |
| `Cn:OFST?` | offset | `C1:OFST -3.01 V` |
| `Cn:CPL?` | coupling | `C1:CPL D1M` |
| `TDIV?` | time/div | `TDIV 5E-6 S` |
| `TRDL?` | trigger delay | `TRDL -9.2E-6 S` |
| `TRMD?` | trigger mode | `TRMD AUTO` |
| `GRID?` | grid mode | `GRID SINGLE` |
| `Cn:WF? DESC` | descriptor only | `C1:WF DESC,#9000000346WAVEDESC…` |
| `Cn:WF? ALL` | descriptor + data | `C1:WF ALL,#9000500348WAVEDESC…` |

Device clear (`viClear`) is a VISA operation, not a command; it resets the I/O buffers only and
does not change instrument settings.

## Parsing rules

- Replies may come with `SHORT`, `LONG` or `OFF` headers; parsers take the last
  whitespace-separated value group and ignore header and unit suffix (`V`, `S`).
- Binary blocks are IEEE 488.2 definite-length (`#9` + 9 digits); the payload starts with the
  `WAVEDESC` block, whose layout follows the `LECROY_2_3` template.
- Never send a query not in the allowlist: the scope does not answer unknown queries and the
  read times out (R4).

## Reply validation (FR-021, research R13)

- Text queries: when `CHDR` is `SHORT` or `LONG`, the reply's first token MUST equal the query
  without `?` in short form (`C1:VDIV`) or long form (`C1:VOLT_DIV`). Long forms: `TRA`→`TRACE`,
  `VDIV`→`VOLT_DIV`, `OFST`→`OFFSET`, `CPL`→`COUPLING`, `TDIV`→`TIME_DIV`, `TRDL`→`TRIG_DELAY`,
  `TRMD`→`TRIG_MODE`, `CHDR`→`COMM_HEADER`, `CFMT`→`COMM_FORMAT`, `CORD`→`COMM_ORDER`,
  `WFSU`→`WAVEFORM_SETUP`, `WF`→`WAVEFORM`; `GRID` and `*IDN` are the same in both.
- Binary queries: the reply MUST start with `Cn:WF DESC,` / `Cn:WF ALL,` (or the `WAVEFORM`
  long form; with `CHDR OFF`, directly with `#`), and the descriptor's `WAVE_SOURCE` MUST be `Cn`.
- On mismatch: raise `ScopeReplyMismatch` (subclass of `ScopeProtocolError`) after a device clear
  to flush stale replies.
