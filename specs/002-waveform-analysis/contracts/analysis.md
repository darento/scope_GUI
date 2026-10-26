# Contract: Analysis Module (`scope_gui.analysis`)

**Feature**: 002-waveform-analysis

Pure numpy; imports nothing from Qt, `pyvisa` or the driver (Constitution I). Entities and
definitions: [data-model.md](../data-model.md).

```python
class Edge(Enum): RISING, FALLING
class Kind(Enum): ...            # .unit -> str, .levels -> 0 | 1 | 2

@dataclass(frozen=True)
class Level: value: float; relative: bool = False; edge: Edge = Edge.RISING
    def label(self) -> str

@dataclass(frozen=True)
class MeasurementSpec: kind; source; level; source2; level2
    name: str (property); to_dict() -> dict; from_dict(dict) -> MeasurementSpec  # ValueError/KeyError if invalid

def measure_all(specs, waveforms: dict[str, Waveform],
                gate: tuple[float, float] | None = None) -> list[float]   # NaN = missed

class Statistics:
    add(value) ; clear() ; size ; history() ; values() ; last ; summary() -> Summary

def histogram_range(values, mode: RangeMode, manual=None) -> tuple[float, float]
def gauss_fit(centers, counts) -> GaussFit | None
```

## Behavioural guarantees (tested in `tests/unit/test_analysis.py`)

1. Linear ramp crossing a volt level between samples → crossing time exact to 1 % of `dt`
   (SC-003); falling edges likewise.
2. Δt between two identical edges shifted by τ (not a multiple of `dt`) → τ ± 1 % `dt`.
3. Constant-fraction Δt of two pulses of the same shape but different amplitude and polarity →
   their shift, independent of amplitude.
4. Square wave of known frequency/duty (several periods, including a cut first edge) →
   frequency within 0.1 %, duty within 0.5 %, rise time of the edge model within 2 %.
5. Pulse on noise: base ≈ baseline, top = peak; negative pulse → negative amplitude; Area of a
   rectangle = height × width.
6. Noise only → percentage-level, rise/fall, width, period, duty cycle missed; amplitude
   measured.
7. Noise riding on a level → one crossing per real edge (hysteresis).
8. Gate: values computed only from samples inside it; base from the whole record; gate with
   < 2 samples → missed.
9. Missing source channel → missed, others unaffected.
10. `Statistics`: ring wraps at capacity, `history()` oldest first, NaN counted as missed,
    `summary()` matches numpy on finite values.
11. `gauss_fit` on a sampled Gaussian (with a second smaller peak and tails) → mean and σ
    within 5 %; `None` for < 10 entries or a flat histogram.
12. `histogram_range` AUTO with 25 % outliers → range contains ≥ 95 % of the main peak and
    excludes the far outliers; constant values → a non-empty range.
13. `MeasurementSpec` round-trips through `to_dict` / `from_dict`.
