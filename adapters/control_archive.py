"""Adapter for a control-system archive: fetch a reading's full series on demand.

The Record does not store time series. It stores an entry when a reading's status changes,
with a pointer into the archive; anyone who needs the series itself (a person looking at a
timeline, later the agent) fetches it from the source through this adapter, at full
resolution, as of a moment.

In this demo the "source" is a set of files written by the synthetic device, standing in for
the real control-system archive. Format, one directory:

    index.json                 {"channels": [{"element", "quantity", "unit", "start",
                                              "cadence_s", "n", "file"}], ...}
    <element>.<quantity>.f32   n little-endian float32 samples; sample i is at start + i*cadence_s

A sample is known as soon as it is taken, so a read "as of t" returns samples up to t.
"""
from __future__ import annotations

import json
import math
import sys
from array import array
from pathlib import Path
from typing import Any, Optional

INDEX = "index.json"


def series_file(element: str, quantity: str) -> str:
    return f"{element}.{quantity}.f32"


class ControlArchive:
    """Read-only access to one archive directory."""

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        index = json.loads((self.dir / INDEX).read_text())
        self.meta = {k: v for k, v in index.items() if k != "channels"}
        self._channels = {(c["element"], c["quantity"]): c for c in index["channels"]}

    @classmethod
    def find(cls, record_path: str | Path) -> Optional["ControlArchive"]:
        """The archive written next to a Record (``<record dir>/source/control_archive``), if any."""
        directory = Path(record_path).parent / "source" / "control_archive"
        return cls(directory) if (directory / INDEX).is_file() else None

    def channels(self) -> list[dict[str, Any]]:
        return list(self._channels.values())

    def has(self, element: str, quantity: str) -> bool:
        return (element, quantity) in self._channels

    def unit(self, element: str, quantity: str) -> str:
        return self._channels[(element, quantity)]["unit"]

    def samples(self, element: str, quantity: str, t0: int, t1: int, as_of: int) -> tuple[list[int], list[float]]:
        """Raw samples with t0 <= t <= min(t1, as_of)."""
        c = self._channels.get((element, quantity))
        if c is None:
            return [], []
        start, cad, n = c["start"], c["cadence_s"], c["n"]
        hi_t = min(t1, as_of)
        i0 = max(0, math.ceil((t0 - start) / cad))
        i1 = min(n - 1, math.floor((hi_t - start) / cad))
        if i1 < i0:
            return [], []
        values = array("f")
        with open(self.dir / c["file"], "rb") as fh:
            fh.seek(i0 * values.itemsize)
            values.fromfile(fh, i1 - i0 + 1)
        if sys.byteorder != "little":
            values.byteswap()
        return [start + i * cad for i in range(i0, i1 + 1)], [round(v, 5) for v in values]

    def fetch(self, element: str, quantity: str, t0: int, t1: int, as_of: int,
              max_points: int = 600) -> list[dict[str, Any]]:
        """The series between t0 and t1 for drawing: at most ``max_points`` points.

        Each point covers [t0, t1] and gives the mean (v), minimum (lo) and maximum (hi) of the
        raw samples in it. When the range holds fewer samples than ``max_points`` every sample
        is its own point, so zooming in reaches full resolution.
        """
        times, values = self.samples(element, quantity, t0, t1, as_of)
        if not times:
            return []
        cad = self._channels[(element, quantity)]["cadence_s"]
        step = max(1, math.ceil(len(times) / max_points))
        out = []
        for k in range(0, len(times), step):
            vs = values[k:k + step]
            out.append({"t0": times[k], "t1": times[min(k + step, len(times)) - 1] + cad,
                        "v": round(sum(vs) / len(vs), 5), "lo": min(vs), "hi": max(vs), "n": len(vs)})
        return out

    def pointer(self, element: str, quantity: str, t0: int, t1: Optional[int] = None) -> str:
        return f"source://control_archive/{element}/{quantity}?from={t0}" + (f"&to={t1}" if t1 else "")
