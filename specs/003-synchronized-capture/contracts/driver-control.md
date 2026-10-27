# Contract: Acquisition control in the driver and worker

Constitution v2.1.0, Principle III "Acquisition control". Extends
[001 scope-driver contract](../../001-live-waveform-view/contracts/scope-driver.md); the
read-only allowlist `ALLOWED_COMMANDS` and its tests are unchanged.

## Driver (`src/scope_gui/driver.py`)

```python
CONTROL_COMMANDS: tuple[re.Pattern, ...]   # fullmatch: "ARM", "FRTR", "TRMD (AUTO|NORM|SINGLE|STOP)"

def is_control_allowed(command: str) -> bool

class ScopeDriver:
    def read_trigger_mode(self) -> TriggerMode         # TRMD? (read-only, existing allowlist)
    def arm(self) -> None                              # ARM
    def force_trigger(self) -> None                    # FRTR
    def restore_trigger_mode(self, mode: TriggerMode) -> None  # TRMD <mode>, then TRMD? check
```

Guarantees:

1. A control command is sent only through `_write`, which raises `CommandNotAllowed` before
   the wire unless `is_control_allowed(command)`; queries still go only through `_query` /
   `_query_raw` with `is_allowed`. No command is in both lists.
2. `_write` sends without reading a reply, maps VISA/socket errors like queries, and logs
   `write <command>` at debug level.
3. `restore_trigger_mode` logs `trigger mode restored to <mode>` at INFO; raises
   `ScopeProtocolError` if `TRMD?` then reports another mode.
4. `read_trigger_mode` accepts `CHDR` SHORT, LONG and OFF replies (`TRMD AUTO`,
   `TRIG_MODE AUTO`, `AUTO`).

## Worker (`src/scope_gui/worker.py`)

```python
class AcquisitionWorker(QObject):
    sync_changed = Signal(bool, str)   # on, user message ("" when switched as asked)

    @Slot(bool)
    def set_synchronized(self, on: bool) -> None   # queued from the GUI
    def set_capture_paused(self, paused: bool) -> None  # thread-safe (threading.Event)
```

Guarantees:

1. Off after every connect; `set_synchronized(True)` while not connected is ignored.
2. Switching on reads and remembers the trigger mode, logs `synchronized capture on (was
   <mode>)`, emits `sync_changed(True, "")`.
3. While on, one update = `TRMD?` (expect `STOP`) → `ARM` → status read (its `TRMD?` is the
   first poll) → `TRMD?` polled every 10 ms until `STOP` → after `waveforms_consumed()`, one
   enabled channel read per cycle → `waveforms_updated` (counted for the rate) → next `ARM` at
   once unless paused. At most one set waits for the GUI.
4. Remembered mode Auto: `FRTR` once when still armed 0.5 s after `ARM`.
5. `TRMD?` = `AUTO`/`NORM` while on: off without restore, log, `sync_changed(False,
   "Trigger mode changed on the scope - synchronized capture switched off")`.
6. Switching off, `close_connection` and `shutdown`: restore first, then continue as before;
   `sync_changed(False, "")`. A failed restore: `sync_changed(False, "Could not restore the
   trigger mode - set the scope back to <mode>")`.
7. Link lost or conflict while on: the LOST message ends with `The scope may be left stopped -
   set its trigger mode back to <mode>.`
8. Ending logs `synchronized capture off (<reason>): <n> acquisitions armed, <m> triggers
   forced`.
9. While on, emitted status reports `trigger_mode = remembered mode` (no settings-changed
   note); `acq_state` is `WAITING_FOR_TRIGGER` after 1 s armed.
10. With the mode off, the worker sends exactly what it sent before this feature.
