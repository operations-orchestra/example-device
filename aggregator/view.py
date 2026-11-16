"""Viewing tools for people: text summaries and a timeline plot of the Record's numbers.

Read-only. Plotting needs matplotlib (``pip install .[plot]``); the text views do not.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from utils import to_iso

from .store import RecordStore, StoredEntry

# Chart colours: categorical series in a fixed order, and reserved status colours.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
SURFACE, INK, INK_2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
CRITICAL, SERIOUS, NEUTRAL_FILL = "#d03b3b", "#ec835a", "#c3c2b7"


def describe(entry: StoredEntry, width: int = 100) -> str:
    """One line saying what an entry holds."""
    p = entry.payload
    if "text" in p:
        s = f'{p.get("author_role", "?")}: {p["text"]}'
    elif entry.type in ("lv_voltage", "temperature"):
        s = f'mean {p["mean"]} {p["unit"]}, slope {p["slope_per_h"]}/h'
    elif entry.type == "downtime":
        s = f'{p["duration_s"] // 60} min, {p["lost_lumi_pb"]} /pb lost, {p["category"]}: {p["details"]}'
    else:
        s = ", ".join(f"{k}={v}" for k, v in p.items())
    return s if len(s) <= width else s[: width - 1] + "…"


def info(store: RecordStore, as_of: Optional[int] = None) -> str:
    as_of = store.latest_known_at() if as_of is None else as_of
    meta, counts = store.meta(), store.counts()
    t0, t1 = store.time_span()
    out = [meta.get("banner", ""), "",
           f"Record: {store.path}  ({store.path.stat().st_size / 1e6:.2f} MB)",
           f"preset {meta.get('preset')}, seed {meta.get('seed')}, schema {meta.get('schema_version')}",
           f"event times {to_iso(t0)} to {to_iso(t1)}", "", "Rows per table:"]
    out += [f"  {name:<17}{n:>8}" for name, n in counts["tables"].items()]
    out += ["", "Elements: " + ", ".join(f"{n} {k}" for k, n in counts["elements_by_kind"].items()),
            "", "Entries by class, source and type:"]
    out += [f"  {c:<3} {s:<14}{t:<22}{k:<8}{n:>7}" for c, s, t, k, n in counts["entries_by_type"]]
    out += ["", f"Incidents as of {to_iso(as_of)}:"]
    for i in store.incidents(as_of):
        out.append(f"  #{i.id:<3} {to_iso(i.t_start)}  {i.status:<10} {i.element:<10} {i.title}")
    return "\n".join(out)


def show_incident(store: RecordStore, incident_id: int, as_of: Optional[int] = None) -> str:
    """An incident as a text timeline, with both times for every entry."""
    as_of = store.latest_known_at() if as_of is None else as_of
    inc = store.incident(incident_id, as_of)
    if inc is None:
        return f"Incident #{incident_id} is not known to the Record as of {to_iso(as_of)}."
    unknown = "(not known at this time)"
    out = [
        f"Incident #{inc.id}: {inc.title}",
        f"  as of           {to_iso(as_of)}",
        f"  element         {inc.element}",
        f"  status          {inc.status}",
        f"  started         {to_iso(inc.t_start)}",
        f"  ended           {to_iso(inc.t_end) if inc.t_end else unknown}",
        f"  recovery action {inc.recovery_action or unknown}",
        f"  confirmed cause {inc.confirmed_cause or unknown}",
        f"  certification   {inc.certification or unknown}",
        "",
        f"  {'happened':<21}{'known to the Record':<21}{'role':<14}{'id':>6}  {'source/type':<28}{'element':<12}what",
    ]
    for role, e in store.incident_entries(incident_id, as_of):
        out.append(f"  {to_iso(e.t_start):<21}{to_iso(e.known_at):<21}{role:<14}{e.id:>6}  "
                   f"{e.source + '/' + e.type:<28}{e.element:<12}{describe(e)}")
        for link in store.links(e.id, as_of):
            if link.link_type == "indirect" and link.src_entry_id == e.id:
                out.append(f"  {'':<56}  -> supports entry {link.dst_entry_id}: {link.rationale}")
    return "\n".join(out)


def scope(store: RecordStore, element: str) -> tuple[list[str], list[str]]:
    """(boxes whose readings are plotted, every element whose events are marked)."""
    kind = store.element_kind(element)
    related = [name for _, name in store.related(element)]
    if kind == "readout_box":
        boxes = [element]
    elif kind == "channel":
        boxes = [store.parent(element)]
    else:
        boxes = sorted(n for n in store.subtree(element) + related if store.element_kind(n) == "readout_box")
    marks = set(store.subtree(element)) | set(store.ancestors(element)) | set(related) | set(boxes)
    for b in boxes:
        marks |= set(store.ancestors(b)) | {name for _, name in store.related(b)}
    return boxes, sorted(marks)


def plot_element(store: RecordStore, element: str, out_path: str | Path,
                 t0: Optional[int] = None, t1: Optional[int] = None,
                 as_of: Optional[int] = None) -> Path:
    """Save a PNG timeline for one element: readings on top, what people recorded below."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("plotting needs matplotlib: pip install '.[plot]'") from exc

    as_of = store.latest_known_at() if as_of is None else as_of
    span = store.time_span()
    t0, t1 = (span[0] if t0 is None else t0), (span[1] if t1 is None else t1)
    boxes, marks = scope(store, element)
    shown = boxes[: len(SERIES)]
    ls_s = int(store.meta().get("lumisection_s", 23))

    def dt(t: int) -> datetime:
        return datetime.fromtimestamp(t, tz=timezone.utc)

    panels = [("lv_voltage", "mean", "Low voltage\n(V)"),
              ("temperature", "mean", "Temperature\n(°C)"),
              ("occupancy_summary", "worst_ls_dead_fraction", "Dead channels\n(fraction)"),
              ("occupancy_summary", "hot_fraction", "Hot channels\n(fraction)"),
              ("occupancy_summary", "mean_occupancy", "Occupancy\n(relative)")]
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": AXIS, "axes.labelcolor": INK_2,
                         "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK,
                         "axes.titlecolor": INK, "font.family": "sans-serif"})
    fig, axes = plt.subplots(len(panels) + 1, 1, figsize=(11, 10.5), sharex=True, facecolor=SURFACE,
                             gridspec_kw={"height_ratios": [1.3, 1, 1, 1, 1, 1.5], "hspace": 0.16})

    for ax, (etype, key, label) in zip(axes, panels):
        for box, colour in zip(shown, SERIES):
            es = store.entries(as_of, elements=[box], t0=t0, t1=t1, types=[etype])
            if etype == "occupancy_summary":       # one flat segment per run
                for n, e in enumerate(es):
                    ax.plot([dt(e.t_start), dt(e.t_end)], [e.payload[key]] * 2, color=colour, lw=2,
                            solid_capstyle="butt", label=box if n == 0 else None)
            else:
                xs = [dt((e.t_start + e.t_end) // 2) for e in es]
                ax.plot(xs, [e.payload[key] for e in es], color=colour, lw=2, label=box)
                if len(shown) == 1:
                    ax.fill_between(xs, [e.payload["min"] for e in es], [e.payload["max"] for e in es],
                                    color=colour, alpha=0.15, lw=0)
        ax.set_ylabel(label, fontsize=8)
        ax.margins(y=0.15)
        if key.endswith("fraction"):
            ax.set_ylim(-0.08, 1.08)

    # the bottom strip: what was recorded about this element and its surroundings
    strip = axes[-1]
    rows = ["Stable beams", "Downtime", "Certified bad", "State change", "Fault event", "Logbook note"]
    y = {name: len(rows) - 1 - i for i, name in enumerate(rows)}

    def bar(row: str, a: int, b: int, colour: str) -> None:
        a, b = max(a, t0), min(b, t1)
        if b > a:
            strip.barh(y[row], mdates.date2num(dt(b)) - mdates.date2num(dt(a)), left=mdates.date2num(dt(a)),
                       height=0.6, color=colour, edgecolor=SURFACE, lw=1)

    def tick(row: str, t: int, colour: str, marker: str) -> None:
        if t0 <= t <= t1:
            line = marker == "|"      # a line marker is drawn with its edge colour only
            strip.plot([dt(t)], [y[row]], marker=marker, color=colour, ms=11 if line else 7,
                       mec=colour if line else SURFACE, mew=2 if line else 1, ls="")

    exp = store.ancestors(element)[-1] if store.ancestors(element) else element
    beam = store.entries(as_of, elements=[exp], types=["beam_mode"])
    for cur, nxt in zip(beam, beam[1:] + [None]):
        if cur.payload["value"] == "STABLE BEAMS":
            bar("Stable beams", cur.t_start, nxt.t_start if nxt else t1, NEUTRAL_FILL)
    for e in store.entries(as_of, elements=marks, t0=t0, t1=t1):
        if e.type == "downtime":
            bar("Downtime", e.t_start, e.t_end, CRITICAL)
        elif e.type == "cert_flag":
            for a, b in e.payload["bad_ls"]:
                bar("Certified bad", e.t_start + (a - 1) * ls_s, e.t_start + b * ls_s, SERIOUS)
        elif e.kind == "state" and e.type != "beam_mode" and e.t_start > span[0]:
            tick("State change", e.t_start, INK_2, "D")
        elif e.type in ("fed_out_of_sync", "data_integrity_errors", "config_change"):
            tick("Fault event", e.t_start, CRITICAL if e.type != "config_change" else INK_2, "v")
        elif e.type == "configure" and e.payload.get("result") == "failed":
            tick("Fault event", e.t_start, CRITICAL, "v")
        elif e.type in ("shift_note", "followup", "root_cause", "closing_note") and e.element != exp:
            # routine notes sit on the detector; only show them when they say something specific
            routine = e.type == "shift_note" and e.element == marks_detector(store, element) \
                and e.payload.get("author_role") == "Shift leader" and "fail" not in e.payload["text"].lower() \
                and "interven" not in e.payload["text"].lower() and "expert" not in e.payload["text"].lower()
            if not routine:
                tick("Logbook note", e.t_start, INK_2, "|")
    strip.set_yticks(list(y.values()), list(y.keys()), fontsize=8, color=INK_2)
    strip.set_ylim(-0.6, len(rows) - 0.4)

    # incidents on these elements: a dashed line through every panel, labelled at the top
    for inc in store.incidents(as_of, elements=marks):
        if t0 <= inc.t_start <= t1:
            for ax in axes:
                ax.axvline(dt(inc.t_start), color=INK_2, lw=1, ls=(0, (4, 3)), zorder=0)
            axes[0].annotate(f"#{inc.id}", (dt(inc.t_start), 1.0), xycoords=("data", "axes fraction"),
                             xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8, color=INK_2)

    for ax in axes:
        ax.set_facecolor(SURFACE)
        ax.grid(True, axis="y", color=GRID, lw=0.6)
        ax.grid(True, axis="x", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(length=0)
    strip.grid(False, axis="y")
    if len(shown) > 1:
        axes[0].legend(loc="lower left", ncols=len(shown), frameon=False, fontsize=8,
                       bbox_to_anchor=(0, 1.12), borderaxespad=0)
    axes[0].set_xlim(dt(t0), dt(t1))
    locator = mdates.AutoDateLocator(minticks=5, maxticks=10, tz=timezone.utc)
    strip.xaxis.set_major_locator(locator)
    strip.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator, tz=timezone.utc))
    strip.set_xlabel("Time (UTC). Dashed lines: incidents, labelled #id above the top panel.", fontsize=8)

    more = f" (first {len(shown)} of {len(boxes)} readout boxes)" if len(boxes) > len(shown) else ""
    series = f"readings from {shown[0]}" if len(shown) == 1 else "readings per readout box" + more
    fig.suptitle(f"{element}: {series}", x=0.07, y=0.975, ha="left", fontsize=12, fontweight="bold")
    fig.text(0.07, 0.945, f"Synthetic, not CMS data.  Record as of {to_iso(as_of)}.", fontsize=8, color=INK_2)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return out_path


def marks_detector(store: RecordStore, element: str) -> str:
    """The detector-level element above ``element`` (where routine shift notes are filed)."""
    chain = [element] + store.ancestors(element)
    return chain[-2] if len(chain) >= 2 else chain[-1]
