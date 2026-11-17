"""Generator settings and the three size presets."""
from __future__ import annotations

from dataclasses import dataclass, replace

# The synthetic calendar starts here, and run and fill numbers start at these values,
# so nothing can be mistaken for, or collide with, a real CMS run.
CALENDAR_START = "2040-03-01T00:00:00Z"
FIRST_RUN_NUMBER = 900001
FIRST_FILL_NUMBER = 50001
LUMISECTION_S = 23
HARD_CAP_MB = 100.0


@dataclass(frozen=True)
class DeviceConfig:
    preset: str
    seed: int
    days: int
    subdetectors: tuple[str, ...]
    boxes_per_sub: int
    channels_per_box: int
    boxes_per_supply: int
    boxes_per_fed: int
    raw_cadence_s: int         # seconds between samples in the control-system archive (not the Record)
    stop_after_h: float        # the technical stop begins after this many hours
    stop_hours: float
    max_size_mb: float
    # how many of each fault to plant (the configure-failure pair is always planted)
    n_fed_comm_same: int       # occurrences on one FED (a recurring problem)
    n_fed_comm_other: int      # occurrences on a different FED
    n_lv_trip: int
    n_hot_channels: int
    n_planned_change: int      # deliberate changes that look like faults but are not
    n_sync_loss: int           # recoveries that are never explained

    @property
    def n_boxes(self) -> int:
        return len(self.subdetectors) * self.boxes_per_sub


PRESETS: dict[str, DeviceConfig] = {
    "tiny": DeviceConfig(
        preset="tiny", seed=1, days=3, subdetectors=("HB", "HF"), boxes_per_sub=2,
        channels_per_box=12, boxes_per_supply=1, boxes_per_fed=2, raw_cadence_s=60,
        stop_after_h=12, stop_hours=10, max_size_mb=2.0,
        n_fed_comm_same=1, n_fed_comm_other=0, n_lv_trip=1, n_hot_channels=1,
        n_planned_change=1, n_sync_loss=0,
    ),
    "small": DeviceConfig(
        preset="small", seed=1, days=30, subdetectors=("HB", "HE", "HF", "HO"), boxes_per_sub=4,
        channels_per_box=18, boxes_per_supply=2, boxes_per_fed=2, raw_cadence_s=60,
        stop_after_h=228, stop_hours=36, max_size_mb=15.0,
        n_fed_comm_same=3, n_fed_comm_other=1, n_lv_trip=5, n_hot_channels=9,
        n_planned_change=4, n_sync_loss=3,
    ),
    "full": DeviceConfig(
        preset="full", seed=1, days=90, subdetectors=("HB", "HE", "HF", "HO"), boxes_per_sub=9,
        channels_per_box=24, boxes_per_supply=3, boxes_per_fed=3, raw_cadence_s=120,
        stop_after_h=480, stop_hours=48, max_size_mb=HARD_CAP_MB,
        n_fed_comm_same=6, n_fed_comm_other=4, n_lv_trip=14, n_hot_channels=25,
        n_planned_change=10, n_sync_loss=8,
    ),
}


def preset(name: str, **overrides) -> DeviceConfig:
    if name not in PRESETS:
        raise KeyError(f"unknown preset {name!r}; choose from {sorted(PRESETS)}")
    return replace(PRESETS[name], **overrides)
