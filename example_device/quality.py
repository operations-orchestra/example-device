"""The synthetic data-quality archive, and the quality-status rule applied to it.

Same scheme as readings (see readings.py): the generator plays the source system and writes
every run's quality numbers per readout box to an archive (format in
adapters/dqm_archive.py); then it plays the sparsifier and records only quality status
changes per box. Occupancy is compared with a reference per subdetector, which experts update
after a deliberate change.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

FIELDS = ["run", "t_start", "t_end", "known_at", "n_channels", "dead_fraction",
          "worst_ls_dead_fraction", "hot_fraction", "hot_channels", "mean_occupancy"]

RULE = {
    "lost_if_worst_ls_dead_at_least": 0.5,
    "occupancy_band": 0.08,
}


def describe() -> str:
    return (f"channels lost if at least {RULE['lost_if_worst_ls_dead_at_least']:.0%} of a box's channels are dead "
            "in its worst lumisection; hot channels if any channel is flagged hot; occupancy high or low if more "
            f"than {RULE['occupancy_band']:.0%} away from the subdetector's reference; evaluated once per run")


def status_of(row: dict[str, Any], reference: float) -> str:
    if row["worst_ls_dead_fraction"] >= RULE["lost_if_worst_ls_dead_at_least"]:
        return "channels lost"
    if row["hot_fraction"] > 0:
        return "hot channels"
    ratio = row["mean_occupancy"] / reference
    if ratio > 1 + RULE["occupancy_band"]:
        return "occupancy high"
    if ratio < 1 - RULE["occupancy_band"]:
        return "occupancy low"
    return "normal"


def write_archive(directory: Path, rows_by_box: dict[str, list[dict[str, Any]]], meta: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for box, rows in rows_by_box.items():
        with open(directory / f"{box}.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            for r in rows:
                w.writerow({**r, "hot_channels": "|".join(r["hot_channels"])})
    (directory / "index.json").write_text(json.dumps({**meta, "fields": FIELDS, "boxes": sorted(rows_by_box)}, indent=1) + "\n")
