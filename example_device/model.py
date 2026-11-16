"""The pretend detector: a hierarchy of elements plus service-side relations."""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import DeviceConfig

EXPERIMENT = "CMS"
DETECTOR = "HCAL"


@dataclass
class DeviceModel:
    subdetectors: list[str] = field(default_factory=list)
    boxes: list[str] = field(default_factory=list)
    sub_of: dict[str, str] = field(default_factory=dict)            # box -> subdetector
    channels: dict[str, list[str]] = field(default_factory=dict)    # box -> channels
    supply_of: dict[str, str] = field(default_factory=dict)         # box -> LV supply
    fed_of: dict[str, str] = field(default_factory=dict)            # box -> FED
    supplies: list[str] = field(default_factory=list)
    feds: list[str] = field(default_factory=list)

    def boxes_of_sub(self, sub: str) -> list[str]:
        return [b for b in self.boxes if self.sub_of[b] == sub]

    def boxes_of_supply(self, supply: str) -> list[str]:
        return [b for b in self.boxes if self.supply_of[b] == supply]

    def boxes_of_fed(self, fed: str) -> list[str]:
        return [b for b in self.boxes if self.fed_of[b] == fed]


def build_model(cfg: DeviceConfig) -> DeviceModel:
    m = DeviceModel()
    for sub in cfg.subdetectors:
        m.subdetectors.append(sub)
        for i in range(cfg.boxes_per_sub):
            box = f"{sub}P{i + 1:02d}"
            m.boxes.append(box)
            m.sub_of[box] = sub
            m.channels[box] = [f"{box}-ch{j + 1:02d}" for j in range(cfg.channels_per_box)]
            supply = f"LV-{sub}-{i // cfg.boxes_per_supply + 1:02d}"
            fed = f"FED-{sub}-{i // cfg.boxes_per_fed + 1:02d}"
            m.supply_of[box] = supply
            m.fed_of[box] = fed
            if supply not in m.supplies:
                m.supplies.append(supply)
            if fed not in m.feds:
                m.feds.append(fed)
    return m


def write_model(store, m: DeviceModel) -> None:
    """Write the elements and their relations into the Record."""
    store.add_element(EXPERIMENT, "experiment")
    store.add_element(DETECTOR, "detector", parent=EXPERIMENT)
    for sub in m.subdetectors:
        store.add_element(sub, "subdetector", parent=DETECTOR)
    for s in m.supplies:
        store.add_element(s, "lv_supply", parent=DETECTOR)
    for f in m.feds:
        store.add_element(f, "fed", parent=DETECTOR)
    for box in m.boxes:
        store.add_element(box, "readout_box", parent=m.sub_of[box])
        store.relate(box, m.supply_of[box], "powered_by")
        store.relate(box, m.fed_of[box], "read_out_by")
        for ch in m.channels[box]:
            store.add_element(ch, "channel", parent=box)
