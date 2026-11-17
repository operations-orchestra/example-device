"""Adapter for a data-quality archive: fetch per-run quality numbers on demand.

Like readings, the per-run numbers per readout box stay in the source; the Record stores only
quality status changes, with a pointer. In this demo the source is a set of files written by
the synthetic device. Format, one directory:

    index.json        {"fields": [...], "boxes": [...]}
    <box>.csv         one row per run: run, t_start, t_end, known_at, and the fields

A run's numbers are known once the run has been processed (``known_at``).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Optional

STATUS = "built"
ROLE = "Fetches a box's per-run data-quality numbers from the data-quality archive, as of a moment."
EXAMPLE = {
    "input": "fetch('HBP02', t0=2040-03-01 00:00, t1=2040-03-01 12:00, as_of=2040-03-01 05:00)",
    "output": "[{run, t_start, t_end, dead_fraction, worst_ls_dead_fraction, hot_fraction, hot_channels, mean_occupancy}, ...] "
              "for runs processed by 05:00",
    "produces": None,
}
NUMERIC = ("n_channels", "dead_fraction", "worst_ls_dead_fraction", "hot_fraction", "mean_occupancy")


class DqmArchive:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.meta = json.loads((self.dir / "index.json").read_text())
        self._cache: dict[str, list[dict[str, Any]]] = {}

    @classmethod
    def find(cls, record_path: str | Path) -> Optional["DqmArchive"]:
        directory = Path(record_path).parent / "source" / "dqm_archive"
        return cls(directory) if (directory / "index.json").is_file() else None

    def boxes(self) -> list[str]:
        return list(self.meta["boxes"])

    def _rows(self, box: str) -> list[dict[str, Any]]:
        if box not in self._cache:
            path = self.dir / f"{box}.csv"
            rows = []
            if path.is_file():
                with open(path, newline="") as fh:
                    for r in csv.DictReader(fh):
                        row: dict[str, Any] = {k: int(r[k]) for k in ("run", "t_start", "t_end", "known_at")}
                        row.update({k: float(r[k]) for k in NUMERIC})
                        row["hot_channels"] = [c for c in r["hot_channels"].split("|") if c]
                        rows.append(row)
            self._cache[box] = rows
        return self._cache[box]

    def fetch(self, box: str, t0: int, t1: int, as_of: int) -> list[dict[str, Any]]:
        """Runs overlapping [t0, t1] whose numbers were known by ``as_of``."""
        return [r for r in self._rows(box) if r["t_start"] <= t1 and r["t_end"] >= t0 and r["known_at"] <= as_of]

    def pointer(self, box: str, run: int) -> str:
        return f"source://dqm_archive/{box}?run={run}"
