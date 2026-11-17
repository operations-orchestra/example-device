"""The synthetic control-system archive, and the status-change rule applied to it.

Two jobs, both standing in for things that do not exist here:

1. Play the **source system**: write each readout box's full voltage and temperature series
   into an archive on disk (format in adapters/control_archive.py). This is not the Record.
2. Play the **sparsifier**: scan each series with a fixed rule and report only the moments
   when the reading's status changes (normal, drifting, low, high, off). Those changes are
   what the Record stores, each with a pointer back into the archive.

The rule is a demo choice, not a design result; it is exposed on the GUI's build page.
"""
from __future__ import annotations

import json
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from utils import HOUR, MINUTE


@dataclass(frozen=True)
class StatusRule:
    """When a reading counts as normal, drifting, low, high or off."""

    unit: str
    setpoint: float           # the reference the reading is compared with
    band: float               # low/high when the smoothed reading is this far from the reference
    drift_slope_per_h: float  # drifting when the 1-hour change exceeds this ...
    drift_min_offset: float   # ... and the reading is at least this far from the reference
    off_below: Optional[float] = None   # off when a raw sample is below this
    smooth_s: int = 15 * MINUTE
    slope_over_s: int = HOUR
    hold_s: int = 10 * MINUTE           # a new status must hold this long to be recorded

    def describe(self) -> str:
        parts = [f"compared with the setpoint {self.setpoint} {self.unit}",
                 f"low/high beyond ±{self.band} {self.unit}",
                 f"drifting if the 1-h change exceeds {self.drift_slope_per_h} {self.unit}/h"]
        if self.off_below is not None:
            parts.append(f"off below {self.off_below} {self.unit}")
        parts.append(f"a status must hold {self.hold_s // MINUTE} min to be recorded")
        return "; ".join(parts)


RULES = {
    "lv_voltage": StatusRule(unit="V", setpoint=8.0, band=0.20, drift_slope_per_h=0.03, drift_min_offset=0.03, off_below=1.0),
    "temperature": StatusRule(unit="degC", setpoint=22.0, band=1.0, drift_slope_per_h=0.5, drift_min_offset=0.3),
}


def status_changes(start: int, cadence: int, values: list[float], rule: StatusRule) -> tuple[float, list[tuple[int, int, str, float]]]:
    """Scan one series. Returns (reference, [(t_start, t_known, status, reading)]).

    t_start is the first sample in the new status; t_known is when the rule could tell
    (t_start + the hold time). The first element of the list is the status at the start.
    """
    n = len(values)
    off = [rule.off_below is not None and v < rule.off_below for v in values]
    reference = rule.setpoint
    w = max(1, rule.smooth_s // cadence)
    lag = max(1, rule.slope_over_s // cadence)
    smooth: list[Optional[float]] = [None] * n
    seg_start, acc = 0, 0.0
    for i in range(n):                       # rolling mean, restarted after every "off" stretch
        if off[i]:
            seg_start, acc = i + 1, 0.0
            continue
        acc += values[i]
        if i - seg_start >= w:
            acc -= values[i - w]
        smooth[i] = acc / min(w, i - seg_start + 1)
    seg_first, seg = [0] * n, 0
    for i in range(n):
        if off[i]:
            seg = i + 1
        seg_first[i] = seg
    seg_of = seg_first.__getitem__
    status = []
    for i in range(n):
        if off[i]:
            status.append("off")
            continue
        s = smooth[i]
        d = s - reference
        prev = smooth[i - lag] if i - lag >= seg_of(i) else None
        slope = (s - prev) * HOUR / (lag * cadence) if prev is not None else 0.0
        if d <= -rule.band:
            status.append("low")
        elif d >= rule.band:
            status.append("high")
        elif slope <= -rule.drift_slope_per_h and d <= -rule.drift_min_offset:
            status.append("drifting down")
        elif slope >= rule.drift_slope_per_h and d >= rule.drift_min_offset:
            status.append("drifting up")
        else:
            status.append("normal")
    hold = max(1, rule.hold_s // cadence)
    changes = [(start, start, status[0], round(values[0], 4))]
    current, i = status[0], 1
    while i < n:
        if status[i] != current:
            j = i
            while j < n and status[j] == status[i] and j - i < hold:
                j += 1
            if j - i >= hold or j == n:      # held long enough (or the series ended)
                current = status[i]
                reading = smooth[i] if smooth[i] is not None else values[i]
                changes.append((start + i * cadence, start + min(i + hold, n - 1) * cadence, current, round(reading, 4)))
                i = j
                continue
        i += 1
    return round(reference, 4), changes


def write_archive(directory: Path, start: int, cadence: int, n: int,
                  series: dict[tuple[str, str], tuple[str, Callable[[int], float]]],
                  meta: dict) -> dict[tuple[str, str], list[float]]:
    """Write every series to the archive. ``series`` maps (element, quantity) to (unit, value_at(i))."""
    directory.mkdir(parents=True, exist_ok=True)
    out, index = {}, []
    for (element, quantity), (unit, value_at) in series.items():
        values = [value_at(i) for i in range(n)]
        packed = array("f", values)
        if packed.itemsize != 4:
            raise RuntimeError("float32 arrays are needed for the archive format")
        import sys
        if sys.byteorder != "little":
            packed.byteswap()
        name = f"{element}.{quantity}.f32"
        with open(directory / name, "wb") as fh:
            packed.tofile(fh)
        index.append({"element": element, "quantity": quantity, "unit": unit, "start": start,
                      "cadence_s": cadence, "n": n, "file": name})
        out[(element, quantity)] = [float(v) for v in array("f", values)]   # as stored (float32)
    (directory / "index.json").write_text(json.dumps({**meta, "channels": index}, indent=1) + "\n")
    return out
