"""Build a synthetic Operations Record for the example device.

Order of work:
  1. fit the settings to the size budget
  2. plan the calendar and where each fault goes        (plan.py)
  3. write the routine background records, already shaped by the planned faults
  4. write what each fault adds: events, logbook notes, downtime, the incident,
     and later the expert's follow-up, cause and links
  5. write planted.json, the hidden list of what was planted (never in the Record)

Everything goes through the aggregator's write API. Same seed, same Record.
"""
from __future__ import annotations

import json
import math
import random
import shutil
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Optional

from aggregator import RecordStore
from utils import DAY, HOUR, MINUTE, Entry, to_iso

from . import readings, texts
from .config import HARD_CAP_MB, LUMISECTION_S, DeviceConfig
from .model import DETECTOR, EXPERIMENT, DeviceModel, build_model, write_model
from .plan import (BOX_SYNC_LOSS, CONFIGURE_FAILURE, FED_COMM_LOSS, HOT_CHANNELS, LV_DRIFT_HOURS,
                   LV_DRIFT_DEPTH_V, LV_DRIFT_TRIP, PLANNED_CHANGE, Fault, Plan, Run, build_plan)

PRODUCER = "example_device.generator"
VERSION = "0.1"
BANNER = ("SYNTHETIC, NOT CMS DATA. Detector names follow public CMS naming; every event, time, "
          "run number, reading and logbook line was invented by a seeded generator.")

LUMI_PB_PER_S = 0.018
NOMINAL_V = 8.0
NOMINAL_TEMP_C = 22.0
_BYTES_PER_ROW = 400          # Record bytes per entry, measured on the tiny preset, rounded up
_BYTES_PER_SAMPLE = 4         # archive: one float32 per sample
_MAX_CADENCE_S = 15 * MINUTE
QUANTITIES = (("lv_voltage", "V"), ("temperature", "degC"))


class SizeBudgetError(Exception):
    pass


# ------------------------------------------------------------------------------- size budget
def estimate_rows(cfg: DeviceConfig) -> int:
    """Entries in the Record. Readings add only their status changes, a few per box per day."""
    status = cfg.n_boxes * len(QUANTITIES) * (2 + cfg.days)
    runs = cfg.days * 7
    per_run = cfg.n_boxes + len(cfg.subdetectors) + 3
    return status + runs * per_run + cfg.days * 10 + 400


def estimate_bytes(cfg: DeviceConfig) -> int:
    """Record plus archive."""
    samples = cfg.n_boxes * len(QUANTITIES) * cfg.days * DAY // cfg.raw_cadence_s
    return estimate_rows(cfg) * _BYTES_PER_ROW + samples * _BYTES_PER_SAMPLE


def fit_to_budget(cfg: DeviceConfig) -> tuple[DeviceConfig, list[str]]:
    """Sample the archive less often, then shorten the calendar, until Record plus archive fit."""
    if cfg.max_size_mb > HARD_CAP_MB:
        raise SizeBudgetError(f"max size {cfg.max_size_mb} MB is above the hard cap of {HARD_CAP_MB} MB")
    if cfg.max_size_mb <= 0:
        raise SizeBudgetError("max size must be positive")
    notes: list[str] = []
    target = cfg.max_size_mb * 1e6 * 0.85
    while estimate_bytes(cfg) > target:
        if cfg.raw_cadence_s < _MAX_CADENCE_S:
            cfg = replace(cfg, raw_cadence_s=min(cfg.raw_cadence_s * 2, _MAX_CADENCE_S))
            notes.append(f"archive sampled every {cfg.raw_cadence_s} s")
        elif cfg.days > 3:
            days = max(3, int(cfg.days * 0.8))
            scale = days / cfg.days
            cfg = replace(cfg, days=days, stop_after_h=max(12.0, cfg.stop_after_h * scale))
            notes.append(f"calendar shortened to {cfg.days} days")
        else:
            raise SizeBudgetError(
                f"cannot fit preset {cfg.preset!r} into {cfg.max_size_mb} MB; raise --max-size-mb")
    return cfg, notes


# ----------------------------------------------------------------------------------- writer
class _Gen:
    def __init__(self, store: RecordStore, cfg: DeviceConfig, model: DeviceModel, plan: Plan, archive_dir: Path):
        self.store, self.cfg, self.model, self.plan = store, cfg, model, plan
        self.archive_dir = archive_dir
        self.noise = random.Random(f"{cfg.seed}:noise")
        self.words = random.Random(f"{cfg.seed}:words")
        self.idx: dict[tuple, int] = {}                  # handles to background entries
        self.status_ids: dict[tuple[str, str], list[tuple[int, str, int]]] = {}  # (box, quantity) -> (t, status, entry id)
        self.planted: list[dict[str, Any]] = []
        self.attached: set[tuple[int, int]] = set()
        self.touched: list[int] = []                     # entries the current fault script wrote or used
        self.dead_box = model.boxes[-1]                  # one known dead channel, as a distractor
        self.dead_channel = model.channels[self.dead_box][6 % cfg.channels_per_box]

    # -- helpers ------------------------------------------------------------------------
    def add(self, source: str, record_class: str, kind: str, type: str, element: str, t: int,
            known: Optional[int] = None, t_end: Optional[int] = None,
            payload: Optional[dict] = None, raw_ref: Optional[str] = None) -> int:
        eid = self.store.add_entry(Entry(
            source=source, record_class=record_class, kind=kind, type=type, element=element,
            t_start=t, t_end=t_end, known_at=t if known is None else known, payload=payload or {},
            raw_ref=raw_ref or f"synthetic://{source}/{type}/{element}?t={to_iso(t)}",
            producer=PRODUCER, producer_version=VERSION,
        ))
        self.touched.append(eid)
        return eid

    def say(self, key: str, **kw: Any) -> str:
        return self.words.choice(texts.T[key]).format(**kw)

    def elog(self, role: str, element: str, t: int, text: str, known: Optional[int] = None) -> int:
        return self.add("elog", "HI", "report", "shift_note", element, t, known=known,
                        payload={"author_role": role, "text": text})

    def next_expert_slot(self, t: int) -> int:
        """Experts write follow-ups at 15:00 UTC, at least three hours after the event."""
        day_start = t - (t - self.plan.start) % DAY
        slot = day_start + 15 * HOUR
        return slot if slot >= t + 3 * HOUR else slot + DAY

    def faults(self, mode: str) -> list[Fault]:
        return [f for f in self.plan.faults if f.mode == mode]

    # -- what the faults do to routine readings --------------------------------------------
    def voltage(self, box: str, t: int) -> float:
        supply = self.model.supply_of[box]
        if self.plan.supply_is_off(supply, t):
            return 0.02
        v = NOMINAL_V + 0.01 * (self.model.boxes.index(box) % 5)
        for f in self.faults(LV_DRIFT_TRIP):
            if f.element == supply and f.t - LV_DRIFT_HOURS * HOUR <= t < f.t:
                v -= LV_DRIFT_DEPTH_V * (t - (f.t - LV_DRIFT_HOURS * HOUR)) / (LV_DRIFT_HOURS * HOUR)
        return v

    def temperature(self, box: str, t: int) -> float:
        day_phase = 2 * math.pi * ((t - self.plan.start) % DAY) / DAY
        temp = NOMINAL_TEMP_C + 0.4 * math.sin(day_phase) + 0.1 * (self.model.boxes.index(box) % 3)
        if self.plan.supply_is_off(self.model.supply_of[box], t):
            temp -= 2.0
        return temp

    def occupancy_factor(self, sub: str, t: int) -> float:
        factor = 1.0
        for f in self.faults(PLANNED_CHANGE):
            if f.element == sub and t >= f.t:
                factor *= f.extra["factor"]
        return factor

    def bad_ranges(self, run: Run, sub: str) -> list[tuple[int, int, str]]:
        """Lumisection ranges of this run that certification marks bad for this subdetector."""
        out = []
        for f in self.faults(LV_DRIFT_TRIP):
            subs = {self.model.sub_of[b] for b in self.model.boxes_of_supply(f.element)}
            if sub in subs and run.start <= f.t <= run.end:
                out.append((run.ls_at(f.t), run.n_ls, f"LV trip of {f.element}"))
        for f in self.faults(HOT_CHANNELS):
            fill_end = self.plan.fills[f.fill_idx].end
            if self.model.sub_of[f.element] == sub and run.start <= fill_end and run.end >= f.t:
                out.append((run.ls_at(max(f.t, run.start)), run.n_ls, f"hot channels in {f.element}"))
        return out

    # -- routine background ----------------------------------------------------------------
    def background(self) -> None:
        p, m = self.plan, self.model

        # beam mode, as a state on the experiment
        self.add("lhc", "MS", "state", "beam_mode", EXPERIMENT, p.start, payload={"value": "NO BEAM"})
        modes = [(p.stop_start, "TECHNICAL STOP"), (p.stop_end, "NO BEAM")]
        for f in p.fills:
            modes += [(f.start, "STABLE BEAMS"), (f.end, "NO BEAM")]
        for t, value in sorted(modes):
            self.add("lhc", "MS", "state", "beam_mode", EXPERIMENT, t, payload={"value": value, })

        # low-voltage supply state, and each box's control link
        for supply in m.supplies:
            self.idx[("supply_state", supply, p.start)] = self.add(
                "dcs", "MS", "state", "supply_state", supply, p.start, payload={"value": "on"})
            for t_off, t_on, reason in sorted(p.supply_off.get(supply, [])):
                value = "tripped" if reason == "trip" else "off"
                self.idx[("supply_state", supply, t_off)] = self.add(
                    "dcs", "MS", "state", "supply_state", supply, t_off,
                    payload={"value": value, "reason": reason})
                self.idx[("supply_state", supply, t_on)] = self.add(
                    "dcs", "MS", "state", "supply_state", supply, t_on, payload={"value": "on"})
        for box in m.boxes:
            self.add("dcs", "MS", "state", "control_link", box, p.start, payload={"value": "ok"})
        for f in self.faults(CONFIGURE_FAILURE):
            self.idx[("control_link", f.element, f.extra["lv_on"])] = self.add(
                "dcs", "MS", "state", "control_link", f.element, f.extra["lv_on"],
                payload={"value": "lost"})
            self.add("dcs", "MS", "state", "control_link", f.element, f.t_resume - 5 * MINUTE,
                     payload={"value": "ok"})

        # configure attempts before each fill
        failing = {f.fill_idx: f for f in self.faults(CONFIGURE_FAILURE)}
        for i, fill in enumerate(p.fills):
            if i in failing:
                for n, minutes in enumerate((15, 11, 7, 3)):
                    self.idx[("configure_failed", i, n)] = self.add(
                        "runcontrol", "MS", "point", "configure", DETECTOR, fill.start - minutes * MINUTE,
                        payload={"result": "failed", "fill": fill.number,
                                 "attempt": "initial" if n == 0 else f"automatic recovery {n}",
                                 "detail": "HCAL in error"})
                self.add("runcontrol", "MS", "point", "configure", DETECTOR,
                         failing[i].t_resume - 2 * MINUTE,
                         payload={"result": "ok", "fill": fill.number, "attempt": "after local configure"})
            else:
                self.add("runcontrol", "MS", "point", "configure", DETECTOR, fill.start - 15 * MINUTE,
                         payload={"result": "ok", "fill": fill.number, "attempt": "initial"})
        for f in p.faults:
            if f.mode in (FED_COMM_LOSS, LV_DRIFT_TRIP):
                self.add("runcontrol", "MS", "point", "configure", DETECTOR, f.t_resume - 2 * MINUTE,
                         payload={"result": "ok", "attempt": "reconfigure"})

        # runs
        for run in p.runs:
            self.add("runcontrol", "MS", "point", "run_start", EXPERIMENT, run.start,
                     payload={"run": run.number, "fill": run.fill})
            self.idx[("run_stop", run.number)] = self.add(
                "runcontrol", "MS", "point", "run_stop", EXPERIMENT, run.end,
                payload={"run": run.number, "fill": run.fill, "n_ls": run.n_ls,
                         "reason": run.stop_reason})
            self.elog(texts.SHIFT_LEADER, DETECTOR, run.start + 4 * MINUTE,
                      self.say("run_start", run=run.number, fill=run.fill))

        # readings: the full series go to the control-system archive (the source, not the
        # Record); the Record gets an entry only when a reading's status changes
        cad = self.cfg.raw_cadence_s
        n = (p.end - p.start) // cad
        noise_of = {"lv_voltage": 0.004, "temperature": 0.05}
        value_of = {"lv_voltage": self.voltage, "temperature": self.temperature}
        series = {}
        for box in m.boxes:
            for quantity, unit in QUANTITIES:
                f, sd = value_of[quantity], noise_of[quantity]
                series[(box, quantity)] = (unit, lambda i, f=f, box=box, sd=sd: f(box, p.start + i * cad) + self.noise.gauss(0, sd))
        written = readings.write_archive(self.archive_dir, p.start, cad, n, series,
                                         {"system": "control-system archive (synthetic)", "banner": BANNER})
        for (box, quantity), values in written.items():
            rule = readings.RULES[quantity]
            reference, changes = readings.status_changes(p.start, cad, values, rule)
            ids = self.status_ids.setdefault((box, quantity), [])
            for t_start, t_known, status, reading in changes:
                ids.append((t_start, status, self.add(
                    "dcs", "MS", "state", f"{quantity}_status", box, t_start, known=t_known,
                    payload={"value": status, "reading": reading, "reference": reference, "unit": rule.unit},
                    raw_ref=f"source://control_archive/{box}/{quantity}?from={t_start}")))

        # data-quality summary per run and box; certification per run and subdetector
        for run in p.runs:
            dur = max(1, run.end - run.start)
            for box in m.boxes:
                n_ch = len(m.channels[box])
                dead = 1 / n_ch if box == self.dead_box else 0.0
                worst = dead
                for f in p.faults:
                    hit = ((f.mode == LV_DRIFT_TRIP and box in m.boxes_of_supply(f.element))
                           or (f.mode == FED_COMM_LOSS and box in m.boxes_of_fed(f.element)))
                    if hit and run.start <= f.t <= run.end:
                        dead = max(dead, (run.end - f.t) / dur)
                        worst = 1.0
                hot: list[str] = []
                for f in self.faults(HOT_CHANNELS):
                    if f.element == box and run.start <= p.fills[f.fill_idx].end and run.end >= f.t:
                        hot = f.extra["channels"]
                occ = self.occupancy_factor(m.sub_of[box], run.start) * (1 + self.noise.gauss(0, 0.01))
                self.idx[("qa", box, run.number)] = self.add(
                    "dqm", "QA", "feature", "occupancy_summary", box, run.start,
                    known=run.end + 10 * MINUTE, t_end=run.end, payload={
                        "run": run.number, "n_channels": n_ch, "dead_fraction": round(dead, 4),
                        "worst_ls_dead_fraction": round(worst, 4),
                        "hot_fraction": round(len(hot) / n_ch, 4), "hot_channels": hot,
                        "mean_occupancy": round(occ, 4)})
            for sub in m.subdetectors:
                bad = self.bad_ranges(run, sub)
                known = run.end + int(self.noise.uniform(1, 3) * DAY)
                self.idx[("cert", sub, run.number)] = self.add(
                    "certification", "HI", "report", "cert_flag", sub, run.start, known=known,
                    t_end=run.end, payload={
                        "run": run.number, "status": "BAD" if bad else "GOOD",
                        "bad_ls": [[a, b] for a, b, _ in bad],
                        "cause": "; ".join(c for _, _, c in bad)})

        # shift notes and the daily run summary
        self.elog(texts.HCAL_DOC, self.dead_channel, p.start + 20 * MINUTE,
                  self.say("known_dead", channel=self.dead_channel))
        for t in range(p.start + 7 * HOUR, p.end, 8 * HOUR):
            self.elog(texts.SHIFT_LEADER, DETECTOR, t, self.say("shift_start"))
        for day in range(1, self.cfg.days + 1):
            t0, t1 = p.start + (day - 1) * DAY, p.start + day * DAY
            runs = [r for r in p.runs if t0 <= r.start < t1]
            lost = sum((f.t_resume - f.t) for f in p.faults if f.t_resume and t0 <= f.t < t1)
            self.add("summary", "HI", "report", "daily_run_summary", EXPERIMENT, t0, known=t1 + 9 * HOUR,
                     t_end=t1, payload={"author_role": texts.RUN_COORDINATOR, "text": (
                         f"Daily run summary: {len(runs)} runs, "
                         f"{sum(r.end - r.start for r in runs) / HOUR:.1f} h of data taking, "
                         f"{lost // MINUTE} min of HCAL downtime.")})

    # -- shared pieces of a fault script ---------------------------------------------------
    def downtime(self, element: str, f: Fault, category: str, details: str) -> int:
        dur = f.t_resume - f.t
        did = self.add("downtime", "HI", "report", "downtime", element, f.t, known=f.t_resume + 2 * MINUTE,
                       t_end=f.t_resume, payload={
                           "duration_s": dur, "lost_lumi_pb": round(dur * LUMI_PB_PER_S, 2),
                           "group": "HCAL", "category": category, "details": details,
                           "run_stopped": f.mode != CONFIGURE_FAILURE})
        run = self.plan.run_at(f.t)
        if run and f.mode != CONFIGURE_FAILURE:
            self.store.add_link(did, self.idx[("run_stop", run.number)], "direct", "stopped_run",
                                known_at=f.t_resume + 2 * MINUTE, producer=PRODUCER,
                                producer_version=VERSION, status="confirmed",
                                rationale="downtime interval contains the run stop")
        return did

    def open_incident(self, title: str, element: str, f: Fault, known: int,
                      attach: list[tuple[int, str]]) -> int:
        iid = self.store.open_incident(title, element, f.t, known)
        if f.t_resume:
            self.store.set_incident_end(iid, f.t_resume)
        for entry_id, role in attach:
            self.attach(iid, entry_id, role, known)
        return iid

    def attach(self, iid: int, entry_id: int, role: str, known: int) -> None:
        """Attach an entry to an incident once; a later role for the same entry is dropped."""
        self.touched.append(entry_id)
        if (iid, entry_id) not in self.attached:
            self.attached.add((iid, entry_id))
            self.store.attach(iid, entry_id, role, known)

    def conclude(self, iid: int, element: str, f: Fault, known: int, text: Optional[str],
                 evidence: list[tuple[int, str]], no_cause_text: str = "") -> None:
        """The expert's later analysis: a cause with its evidence, or 'unresolved'."""
        if text is None:
            note = self.add("expert", "HI", "report", "closing_note", element, f.t, known=known,
                            payload={"author_role": texts.HCAL_EXPERT, "text": no_cause_text})
            self.attach(iid, note, "closing_note", known)
            self.store.close_incident(iid, "unresolved", known)
            return
        cause = self.add("expert", "HI", "report", "root_cause", element, f.t, known=known,
                         payload={"author_role": texts.HCAL_EXPERT, "text": text})
        self.attach(iid, cause, "cause", known)
        for entry_id, rationale in evidence:
            self.attach(iid, entry_id, "evidence", known)
            self.store.add_link(entry_id, cause, "indirect", "supports", known_at=known,
                                producer=PRODUCER, producer_version=VERSION, status="confirmed",
                                rationale=rationale)
        self.store.label_incident(iid, "confirmed_cause", text, known)
        self.store.close_incident(iid, "closed", known)

    def certify(self, iid: int, f: Fault, sub: str) -> None:
        run = self.plan.run_at(f.t) or next((r for r in self.plan.runs if r.start >= f.t), None)
        if run is None:
            return
        entry = self.store.get_entry(self.idx[("cert", sub, run.number)], as_of=2**62)
        value = entry.payload["status"] + (f": {entry.payload['cause']}" if entry.payload["cause"] else "")
        self.attach(iid, entry.id, "certification", entry.known_at)
        self.store.label_incident(iid, "certification", value, entry.known_at)

    def plant(self, f: Fault, reported: str, ask_at: int, iid: Optional[int]) -> None:
        self.planted.append({
            "id": f"P{len(self.planted) + 1:02d}", "mode": f.mode, "chain": f.chain, "seq": f.seq,
            "true_element": f.element, "reported_element": reported,
            "t_event": f.t, "t_event_iso": to_iso(f.t), "ask_at": ask_at, "ask_at_iso": to_iso(ask_at),
            "question": texts.QUESTIONS[f.mode].format(element=reported), "incident_id": iid,
        })

    # -- the fault scripts -----------------------------------------------------------------
    def fed_comm_loss(self, f: Fault, t_cause: Optional[int]) -> None:
        fed = f.element
        sub = self.model.sub_of[self.model.boxes_of_fed(fed)[0]]
        point = self.add("daq", "MS", "point", "fed_out_of_sync", fed, f.t, payload={"state": "OUT_OF_SYNC"})
        e1 = self.elog(texts.DAQ_SHIFTER, fed, f.t + 2 * MINUTE, self.say("fed_symptom", fed=fed, sub=sub))
        e2 = self.elog(texts.HCAL_DOC, fed, f.t_resume + MINUTE, self.say("fed_recovery", fed=fed))
        down = self.downtime(sub, f, "FED", self.say("fed_downtime", fed=fed))
        opened = f.t_resume + 10 * MINUTE
        iid = self.open_incident(f"Communication loss on {fed}", fed, f, opened,
                                 [(point, "symptom"), (e1, "symptom"), (e2, "action"), (down, "downtime")])
        self.store.label_incident(iid, "recovery_action", "Stop the run and reconfigure HCAL", opened)
        self.certify(iid, f, sub)
        if t_cause is None:
            self.conclude(iid, fed, f, f.t + 10 * DAY, None, [],
                          f"No cause found for the communication loss on {fed}. Closing as unresolved.")
        else:
            self.conclude(iid, fed, f, max(t_cause, f.t + DAY), self.say("fed_cause", fed=fed),
                          [(point, "the out-of-sync state matches a loss of lock on the uplink")])
        self.plant(f, fed, f.t + 5 * MINUTE, iid)

    def configure_failure(self, f: Fault, t_cause: int) -> None:
        box, fill = f.element, self.plan.fills[f.fill_idx]
        supply = self.model.supply_of[box]
        attempts = [(self.idx[("configure_failed", f.fill_idx, n)], "symptom") for n in range(4)]
        e1 = self.elog(texts.SHIFT_LEADER, DETECTOR, f.t + 3 * MINUTE, self.say("cfg_symptom", fill=fill.number))
        e2 = self.elog(texts.SHIFT_LEADER, DETECTOR, f.t_resume + 2 * MINUTE, self.say("cfg_recovery_terse"))
        down = self.downtime(DETECTOR, f, "CONFIGURE", self.say("cfg_downtime"))
        opened = f.t_resume + 10 * MINUTE
        iid = self.open_incident(f"HCAL fails to configure for fill {fill.number}", DETECTOR, f, opened,
                                 attempts + [(e1, "symptom"), (e2, "action"), (down, "downtime")])
        # What the expert actually did is only written down some hours later, but always
        # before the next fill, so the second occurrence can find it.
        told = f.t_resume + 6 * HOUR
        follow = self.add("expert", "HI", "report", "followup", box, f.t, known=told, payload={
            "author_role": texts.HCAL_DOC, "text": self.say("cfg_followup", fill=fill.number, box=box)})
        self.attach(iid, follow, "action", told)
        self.store.label_incident(
            iid, "recovery_action",
            f"Power-cycle the control module of {box}, then run a local configure", told)
        self.certify(iid, f, self.model.sub_of[box])
        lost = self.idx[("control_link", box, f.extra["lv_on"])]
        lv_on = self.idx[("supply_state", supply, f.extra["lv_on"])]
        self.conclude(iid, box, f, max(t_cause, told), self.say("cfg_cause", box=box, supply=supply), [
            (lost, "the control link was lost from the moment the low voltage came back"),
            (lv_on, "the low-voltage power cycle preceded the loss of the control link"),
        ])
        self.plant(f, DETECTOR, f.t + 5 * MINUTE, iid)

    def lv_drift_trip(self, f: Fault) -> None:
        supply = f.element
        boxes = self.model.boxes_of_supply(supply)
        sub = self.model.sub_of[boxes[0]]
        names = ", ".join(boxes)
        trip = self.idx[("supply_state", supply, f.t)]
        e1 = self.elog(texts.DCS_SHIFTER, supply, f.t + 3 * MINUTE, self.say("lv_symptom", supply=supply, boxes=names))
        e2 = self.elog(texts.HCAL_DOC, supply, f.t_resume + MINUTE, self.say("lv_recovery", supply=supply, boxes=names))
        down = self.downtime(sub, f, "LV", self.say("lv_downtime", supply=supply))
        opened = f.t_resume + 10 * MINUTE
        iid = self.open_incident(f"Trip of {supply}", supply, f, opened,
                                 [(trip, "symptom"), (e1, "symptom"), (e2, "action"), (down, "downtime")])
        self.store.label_incident(iid, "recovery_action", f"Power-cycle {supply}", opened)
        self.certify(iid, f, sub)
        drift = [(eid, f"the output voltage was {status} before the trip; the series is in the control-system archive")
                 for t0, status, eid in self.status_ids[(boxes[0], "lv_voltage")]
                 if f.t - LV_DRIFT_HOURS * HOUR <= t0 < f.t and status in ("drifting down", "low")]
        self.conclude(iid, supply, f, f.t + 14 * DAY,
                      self.say("lv_cause", supply=supply, hours=LV_DRIFT_HOURS), drift)
        self.plant(f, supply, f.t + 5 * MINUTE, iid)

    def hot_channels(self, f: Fault) -> None:
        box, channels = f.element, f.extra["channels"]
        sub = self.model.sub_of[box]
        fill_end = self.plan.fills[f.fill_idx].end
        run = self.plan.run_at(f.t) or next(r for r in self.plan.runs if r.start >= f.t)
        seen = run.end + 10 * MINUTE
        short = ", ".join(c.split("-")[-1] for c in channels)
        flags = [self.add("dqm", "QA", "report", "channel_flag", ch, f.t, known=seen, t_end=fill_end,
                          payload={"flag": "hot", "run": run.number}) for ch in channels]
        note_t = max(f.t + 40 * MINUTE, seen)
        e1 = self.elog(texts.DQM_SHIFTER, sub, note_t, self.say("hot_symptom", sub=sub, box=box))
        opened = note_t + 5 * MINUTE
        iid = self.open_incident(f"Hot channels in {box}", box, f, opened,
                                 [(e1, "symptom")] + [(x, "symptom") for x in flags])
        self.store.set_incident_end(iid, fill_end)
        told = self.next_expert_slot(note_t)
        follow = self.add("expert", "HI", "report", "followup", box, f.t, known=told, payload={
            "author_role": texts.HCAL_DOC, "text": self.say("hot_followup", channels=short, box=box)})
        self.attach(iid, follow, "action", told)
        self.store.label_incident(iid, "recovery_action", f"Mask the hot channels of {box}", told)
        self.certify(iid, f, sub)
        qa = [(self.idx[("qa", box, r.number)], "the occupancy summary shows the hot fraction")
              for r in self.plan.runs_overlapping(f.t, fill_end)]
        if self.words.random() < 0.3:
            self.conclude(iid, box, f, f.t + 5 * DAY, None, [],
                          self.say("hot_no_cause", channels=short, box=box))
        else:
            self.conclude(iid, box, f, f.t + 5 * DAY, self.say("hot_cause", channels=short), qa)
        self.plant(f, box, note_t + 2 * MINUTE, iid)

    def planned_change(self, f: Fault) -> None:
        sub, fill = f.element, self.plan.fills[f.fill_idx]
        self.elog(texts.RUN_COORDINATOR, sub, f.t - 3 * HOUR, self.say("change_announce", sub=sub, fill=fill.number))
        self.add("runcontrol", "MS", "point", "config_change", sub, f.t, payload={
            "parameter": "zero_suppression_threshold", "change": "lowered", "planned": True})
        first = next(r for r in self.plan.runs if r.start >= fill.start)
        self.plant(f, sub, first.end + 15 * MINUTE, None)

    def box_sync_loss(self, f: Fault) -> None:
        box = f.element
        sub = self.model.sub_of[box]
        point = self.add("daq", "MS", "point", "data_integrity_errors", box, f.t,
                         payload={"errors": self.words.randrange(2000, 9000)})
        e1 = self.elog(texts.DAQ_SHIFTER, box, f.t + 2 * MINUTE, self.say("sync_symptom", box=box))
        e2 = self.elog(texts.HCAL_DOC, box, f.t_resume + MINUTE, self.say("sync_recovery", box=box))
        down = self.downtime(sub, f, "FRONTEND", self.say("sync_downtime", box=box))
        opened = f.t_resume + 10 * MINUTE
        iid = self.open_incident(f"Data integrity errors from {box}", box, f, opened,
                                 [(point, "symptom"), (e1, "symptom"), (e2, "action"), (down, "downtime")])
        self.store.label_incident(iid, "recovery_action", f"Reset the front-end of {box}", opened)
        self.certify(iid, f, sub)
        self.conclude(iid, box, f, f.t + 10 * DAY, None, [], self.say("sync_no_cause", box=box))
        self.plant(f, box, f.t + 5 * MINUTE, iid)

    def run_faults(self) -> None:
        comm = self.faults(FED_COMM_LOSS)
        comm_cause = comm[1].t + 4 * DAY if len(comm) >= 2 else None   # understood after it recurs
        cfg_cause = self.faults(CONFIGURE_FAILURE)[0].t + 6 * DAY
        for f in self.plan.faults:
            self.touched = []
            if f.mode == FED_COMM_LOSS:
                self.fed_comm_loss(f, comm_cause)
            elif f.mode == CONFIGURE_FAILURE:
                self.configure_failure(f, cfg_cause)
            elif f.mode == LV_DRIFT_TRIP:
                self.lv_drift_trip(f)
            elif f.mode == HOT_CHANNELS:
                self.hot_channels(f)
            elif f.mode == PLANNED_CHANGE:
                self.planned_change(f)
            elif f.mode == BOX_SYNC_LOSS:
                self.box_sync_loss(f)
            self.planted[-1]["entry_ids"] = sorted(set(self.touched))

    def finish_planted(self) -> None:
        """Work out, from the Record itself, what an honest answer is at each ask time."""
        for p in self.planted:
            if p["mode"] == PLANNED_CHANGE:
                p["expected"] = {"verdict": "not_a_fault", "next_step": "none", "precedents": [],
                                 "recovery_known": False, "cause_known": False}
                continue
            views = []
            for q in self.planted:
                if q["mode"] == p["mode"] and q["t_event"] < p["t_event"] and q["incident_id"]:
                    view = self.store.incident(q["incident_id"], as_of=p["ask_at"])
                    if view:
                        views.append(view)
            recovery = any(v.recovery_action for v in views)
            p["expected"] = {
                "verdict": "known" if views else "new",
                "next_step": "recovery_procedure" if recovery else "escalate",
                "precedents": [v.id for v in views],
                "recovery_known": recovery,
                "cause_known": any(v.confirmed_cause for v in views),
            }


# --------------------------------------------------------------------------------- entry point
def generate(cfg: DeviceConfig, out_dir: str | Path, force: bool = False) -> dict[str, Any]:
    """Write ``record.db``, ``planted.json`` and the control-system archive into ``out_dir``.

    The archive (``source/control_archive/``) stands in for an existing system; it is not
    part of the Record. Returns a short summary.
    """
    cfg, notes = fit_to_budget(cfg)
    out = Path(out_dir)
    db_path, planted_path = out / "record.db", out / "planted.json"
    archive_dir = out / "source" / "control_archive"
    if db_path.exists():
        if not force:
            raise FileExistsError(f"{db_path} exists; pass force=True (--force) to rebuild it")
        db_path.unlink()
    if archive_dir.exists():
        shutil.rmtree(archive_dir)

    model = build_model(cfg)
    plan = build_plan(cfg, model)
    store = RecordStore.create(db_path, meta={
        "banner": BANNER, "synthetic": "true", "producer": PRODUCER, "producer_version": VERSION,
        "preset": cfg.preset, "seed": str(cfg.seed), "config": json.dumps(asdict(cfg), sort_keys=True),
        "calendar_start": to_iso(plan.start), "calendar_end": to_iso(plan.end),
        "lumisection_s": str(LUMISECTION_S),
        "status_rules": json.dumps({q: r.describe() for q, r in readings.RULES.items()}, sort_keys=True),
    })
    write_model(store, model)
    gen = _Gen(store, cfg, model, plan, archive_dir)
    gen.background()
    gen.run_faults()
    gen.finish_planted()
    counts = store.counts()["tables"]
    store.close()

    size_mb = db_path.stat().st_size / 1e6
    archive_mb = sum(f.stat().st_size for f in archive_dir.iterdir()) / 1e6
    if size_mb + archive_mb > cfg.max_size_mb:
        db_path.unlink()
        shutil.rmtree(archive_dir)
        raise SizeBudgetError(f"Record ({size_mb:.1f} MB) plus archive ({archive_mb:.1f} MB) came out "
                              f"over the {cfg.max_size_mb} MB budget")

    out.mkdir(parents=True, exist_ok=True)
    planted_path.write_text(json.dumps({"banner": BANNER, "seed": cfg.seed, "preset": cfg.preset,
                                        "modes": texts.MODES, "planted": gen.planted}, indent=2) + "\n")
    return {"db": str(db_path), "planted": str(planted_path), "size_mb": round(size_mb, 2),
            "archive": str(archive_dir), "archive_mb": round(archive_mb, 2),
            "config": cfg, "adjustments": notes, "counts": counts, "n_planted": len(gen.planted),
            "fills": len(plan.fills), "runs": len(plan.runs)}
