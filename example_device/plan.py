"""The pretend calendar: beam fills, a technical stop, where each fault goes, and runs.

Nothing is written to the Record here. The plan is decided first so the routine
background records can be generated already knowing about the faults (a drifting
voltage must show up in the hourly voltage summaries, not be pasted on afterwards).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from utils import DAY, HOUR, MINUTE, from_iso

from .config import CALENDAR_START, FIRST_FILL_NUMBER, FIRST_RUN_NUMBER, LUMISECTION_S, DeviceConfig
from .model import DeviceModel

# Fault modes. "planned_change" is the trap: it looks like a fault and is not one.
FED_COMM_LOSS = "fed_comm_loss"
CONFIGURE_FAILURE = "configure_failure"
LV_DRIFT_TRIP = "lv_drift_trip"
HOT_CHANNELS = "hot_channels"
PLANNED_CHANGE = "planned_change"
BOX_SYNC_LOSS = "box_sync_loss"

LV_DRIFT_HOURS = 6
LV_DRIFT_DEPTH_V = 0.35


@dataclass
class Fill:
    number: int
    start: int
    end: int


@dataclass
class Run:
    number: int
    fill: int
    start: int
    end: int
    stop_reason: str

    @property
    def n_ls(self) -> int:
        return max(1, (self.end - self.start) // LUMISECTION_S)

    def ls_at(self, t: int) -> int:
        return min(self.n_ls, max(1, (t - self.start) // LUMISECTION_S + 1))


@dataclass
class Fault:
    mode: str
    element: str               # where the fault really is
    t: int                     # when it starts
    fill_idx: int
    t_resume: Optional[int] = None   # when data taking resumed, if it was interrupted
    chain: str = ""            # faults in one chain are recurrences of the same problem
    seq: int = 0               # position in the chain, 0 = first occurrence
    extra: dict = field(default_factory=dict)


@dataclass
class Plan:
    start: int
    end: int
    stop_start: int
    stop_end: int
    fills: list[Fill]
    runs: list[Run]
    faults: list[Fault]
    supply_off: dict[str, list[tuple[int, int, str]]]   # supply -> (t_off, t_on, reason)

    def fill_of(self, t: int) -> Optional[Fill]:
        for f in self.fills:
            if f.start <= t <= f.end:
                return f
        return None

    def run_at(self, t: int) -> Optional[Run]:
        for r in self.runs:
            if r.start <= t <= r.end:
                return r
        return None

    def runs_overlapping(self, t0: int, t1: int) -> list[Run]:
        return [r for r in self.runs if r.start <= t1 and r.end >= t0]

    def supply_is_off(self, supply: str, t: int) -> bool:
        return any(a <= t < b for a, b, _ in self.supply_off.get(supply, ()))


def _build_fills(cfg: DeviceConfig, rng: random.Random, start: int, end: int,
                 stop_start: int, stop_end: int) -> list[Fill]:
    fills: list[Fill] = []
    number = FIRST_FILL_NUMBER

    def segment(t: int, seg_end: int) -> None:
        nonlocal number
        while t + 4 * HOUR <= seg_end:
            dur = int(rng.uniform(8, 11) * HOUR)
            f_end = min(t + dur, seg_end)
            fills.append(Fill(number, t, f_end))
            number += 1
            t = f_end + int(rng.uniform(2.5, 4) * HOUR)

    segment(start + HOUR, stop_start - 30 * MINUTE)
    segment(stop_end + 2 * HOUR, end - 30 * MINUTE)
    return fills


def build_plan(cfg: DeviceConfig, model: DeviceModel) -> Plan:
    rng = random.Random(f"{cfg.seed}:plan")
    start = from_iso(CALENDAR_START)
    end = start + cfg.days * DAY
    stop_start = start + int(cfg.stop_after_h * HOUR)
    stop_end = stop_start + int(cfg.stop_hours * HOUR)
    fills = _build_fills(cfg, rng, start, end, stop_start, stop_end)

    post = next(i for i, f in enumerate(fills) if f.start >= stop_end)
    if post + 1 >= len(fills) or post == 0:
        raise ValueError("calendar too short: need a fill before the technical stop and two after it")

    faults: list[Fault] = []
    supply_off: dict[str, list[tuple[int, int, str]]] = {}

    # --- the Fig. 2 pair: configure fails on the first two nights after the stop ---------
    cfg_box = rng.choice(model.boxes)
    cfg_supply = model.supply_of[cfg_box]
    night1, night2 = fills[post], fills[post + 1]
    access = (night1.end + 30 * MINUTE, night1.end + 70 * MINUTE)
    supply_off.setdefault(cfg_supply, []).extend([
        (stop_start + HOUR, stop_end - HOUR, "technical stop"),
        (access[0], access[1], "access"),
    ])
    faults.append(Fault(CONFIGURE_FAILURE, cfg_box, night1.start, post,
                        t_resume=night1.start + int(rng.uniform(65, 90) * MINUTE),
                        chain="configure", seq=0, extra={"lv_on": stop_end - HOUR}))
    faults.append(Fault(CONFIGURE_FAILURE, cfg_box, night2.start, post + 1,
                        t_resume=night2.start + int(rng.uniform(30, 45) * MINUTE),
                        chain="configure", seq=1, extra={"lv_on": access[1]}))

    # --- everything else goes at random into the other fills ------------------------------
    free = [i for i in range(len(fills)) if i not in (post, post + 1)]
    taken: list[tuple[int, int]] = []     # (t0, t1) already used, with a margin

    def place(lead_h: float = 2.0, tail_h: float = 1.5, among: Optional[list[int]] = None) -> tuple[int, int]:
        """Pick (fill index, time) clear of other faults."""
        for _ in range(500):
            i = rng.choice(among or free)
            f = fills[i]
            lo, hi = f.start + int(lead_h * HOUR), f.end - int(tail_h * HOUR)
            if hi <= lo:
                continue
            t = rng.randrange(lo, hi)
            if all(t < a - 2 * HOUR or t > b + 2 * HOUR for a, b in taken):
                return i, t
        raise ValueError("could not place all faults; use more days or fewer faults")

    def interrupt(mode: str, element: str, minutes: tuple[float, float], chain: str, seq: int,
                  among: Optional[list[int]] = None) -> Fault:
        i, t = place(among=among)
        t_resume = t + int(rng.uniform(*minutes) * MINUTE)
        taken.append((t, t_resume))
        fault = Fault(mode, element, t, i, t_resume=t_resume, chain=chain, seq=seq)
        faults.append(fault)
        return fault

    # FED communication loss: several times on one FED, then on a different one.
    feds = model.feds[:]
    rng.shuffle(feds)
    chain = [interrupt(FED_COMM_LOSS, feds[0], (8, 15), "fed_comm", 0)
             for _ in range(cfg.n_fed_comm_same)]
    chain += [interrupt(FED_COMM_LOSS, feds[1 % len(feds)], (8, 15), "fed_comm", 0)
              for _ in range(cfg.n_fed_comm_other)]
    for seq, fault in enumerate(sorted(chain, key=lambda x: x.t)):
        fault.seq = seq

    # Low-voltage drift ending in a trip: on a supply that is not the configure-failure one.
    lv_supplies = [s for s in model.supplies if s != cfg_supply]
    rng.shuffle(lv_supplies)
    for n in range(cfg.n_lv_trip):
        supply = lv_supplies[n % len(lv_supplies)]
        fault = interrupt(LV_DRIFT_TRIP, supply, (30, 50), f"lv:{supply}", 0)
        supply_off.setdefault(supply, []).append((fault.t, fault.t_resume, "trip"))
    for supply in set(f.element for f in faults if f.mode == LV_DRIFT_TRIP):
        for seq, fault in enumerate(sorted((f for f in faults if f.mode == LV_DRIFT_TRIP
                                            and f.element == supply), key=lambda x: x.t)):
            fault.seq = seq

    # Loss of synchronisation on a readout box: recovered by a reset, never explained.
    for n in range(cfg.n_sync_loss):
        interrupt(BOX_SYNC_LOSS, rng.choice(model.boxes), (6, 10), f"sync:{n}", 0)

    # Hot channels: no downtime; lasts until the end of the fill, then the channels are masked.
    for n in range(cfg.n_hot_channels):
        i, t = place()
        box = rng.choice(model.boxes)
        channels = sorted(rng.sample(model.channels[box], k=rng.choice((2, 3))))
        taken.append((t, t))
        faults.append(Fault(HOT_CHANNELS, box, t, i, chain=f"hot:{n}", extra={"channels": channels}))

    # Planned change: a deliberate threshold change before a fill. Not a fault.
    change_fills = [i for i in free if i > 0]
    rng.shuffle(change_fills)
    for n in range(min(cfg.n_planned_change, len(change_fills))):
        i = change_fills[n]
        faults.append(Fault(PLANNED_CHANGE, rng.choice(model.subdetectors),
                            fills[i].start - 30 * MINUTE, i, chain=f"change:{n}",
                            extra={"factor": round(rng.uniform(1.12, 1.2), 3)}))

    faults.sort(key=lambda f: f.t)
    runs = _build_runs(fills, faults, rng)
    return Plan(start, end, stop_start, stop_end, fills, runs, faults, supply_off)


def _build_runs(fills: list[Fill], faults: list[Fault], rng: random.Random) -> list[Run]:
    runs: list[Run] = []
    number = FIRST_RUN_NUMBER
    for i, fill in enumerate(fills):
        t = fill.start
        cuts: list[tuple[int, int, str]] = []
        for f in faults:
            if f.fill_idx != i or f.t_resume is None:
                continue
            if f.mode == CONFIGURE_FAILURE:
                t = f.t_resume            # the first run of the fill starts late
            else:
                cuts.append((f.t + MINUTE, f.t_resume, f.mode))
        cuts.sort()
        while t < fill.end - 5 * MINUTE:
            natural = t + int(rng.uniform(2, 4) * HOUR)
            cut = next((c for c in cuts if c[0] > t), None)
            end, reason, nxt = fill.end, "beam dump", fill.end
            if natural < end:
                end, reason, nxt = natural, "new run", natural + 2 * MINUTE
            if cut and cut[0] <= end:
                end, reason, nxt = cut[0], cut[2], cut[1]
            runs.append(Run(number, fill.number, t, end, reason))
            number += 1
            t = nxt
    return runs
