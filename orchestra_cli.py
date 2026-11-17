"""Command line for the Operations Orchestra prototype.

    orchestra synth [--preset tiny] [--seed 1] [--max-size-mb N] [--out out] [--force]
    orchestra info  [--db out/record.db] [--as-of TIME]
    orchestra show  INCIDENT_ID [--as-of TIME]
    orchestra plot  ELEMENT [--from TIME] [--to TIME] [--as-of TIME] [--out FILE]
    orchestra view  [--db out/record.db] [--port 8765]
    orchestra ask   INCIDENT [--as-of TIME] [--db FILE] [--model-url URL --model NAME]
    orchestra demo  [--db FILE]

TIME looks like 2040-03-02T01:05 (UTC).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from utils import from_iso


def _synth(args: argparse.Namespace) -> int:
    from example_device import SizeBudgetError, generate, preset

    overrides = {}
    if args.seed is not None:
        overrides["seed"] = args.seed
    if args.max_size_mb is not None:
        overrides["max_size_mb"] = args.max_size_mb
    try:
        result = generate(preset(args.preset, **overrides), args.out, force=args.force)
    except (SizeBudgetError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    cfg = result["config"]
    print(f"Wrote {result['db']} ({result['size_mb']} MB) and the control-system archive "
          f"{result['archive']} ({result['archive_mb']} MB); {cfg.max_size_mb} MB allowed in total")
    print(f"  preset {cfg.preset}, seed {cfg.seed}: {cfg.days} days, {result['fills']} fills, "
          f"{result['runs']} runs, {cfg.n_boxes} readout boxes, "
          f"{cfg.n_boxes * cfg.channels_per_box} channels")
    print(f"  {result['counts']['entry']} entries, {result['counts']['incident']} incidents, "
          f"{result['counts']['link']} links")
    for note in result["adjustments"]:
        print(f"  adjusted to fit the size budget: {note}")
    print(f"Wrote {result['planted']} ({result['n_planted']} planted cases; not part of the Record)")
    return 0


def _open(args: argparse.Namespace):
    from aggregator import RecordStore

    return RecordStore.open(args.db)


def _as_of(args: argparse.Namespace):
    return from_iso(args.as_of) if args.as_of else None


def _info(args: argparse.Namespace) -> int:
    from aggregator.view import info

    print(info(_open(args), _as_of(args)))
    return 0


def _show(args: argparse.Namespace) -> int:
    from aggregator.view import show_incident

    print(show_incident(_open(args), args.incident, _as_of(args)))
    return 0


def _plot(args: argparse.Namespace) -> int:
    from aggregator.view import plot_element

    store = _open(args)
    if not store.has_element(args.element):
        print(f"error: unknown element {args.element!r}. Elements: {', '.join(store.elements())}",
              file=sys.stderr)
        return 1
    out = args.out or Path(args.db).parent / f"plot_{args.element}.png"
    from adapters.control_archive import ControlArchive

    from adapters.dqm_archive import DqmArchive

    archive, dqm = ControlArchive.find(args.db), DqmArchive.find(args.db)
    path = plot_element(store, args.element, out, series=archive.fetch if archive else None,
                        quality=dqm.fetch if dqm else None,
                        t0=from_iso(args.t_from) if args.t_from else None,
                        t1=from_iso(args.t_to) if args.t_to else None, as_of=_as_of(args))
    print(f"Wrote {path}")
    return 0


def _view(args: argparse.Namespace) -> int:
    from viewer.server import serve

    try:
        serve(args.db, args.port)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _print_answer(store, result) -> None:
    from utils import to_iso

    p = result["proposal"]
    print(f"  verdict      {p.verdict}  (confidence {p.confidence:.2f}, {p.brain} brain)")
    print(f"  next step    {p.next_step.replace('_', ' ')}")
    print(f"  part         {p.element}")
    print(f"  diagnosis    {p.diagnosis}")
    for c in p.candidates[:3]:
        print(f"  candidate    #{c['id']} {c['title']}: {c['signature']} match, {c['confidence']:.2f}")
        for s in c["steps"]:
            print(f"                 {s}")
    for c in p.supporting:
        e = store.get_entry(c.entry_id, result["log"].calls[c.query_id - 1].as_of)
        print(f"  cites        entry {c.entry_id} via query {c.query_id} ({c.why}): {e.type} {e.element} {to_iso(e.t_start)}")
    for n in p.notes:
        print(f"  note         {n}")
    print(f"  tool calls   " + "; ".join(f"{c.id}:{c.tool}" for c in result["log"].calls))
    print(f"  check        " + ("passed" if result["accepted"] else "REJECTED: " + "; ".join(result["problems"])))


def _brain(args):
    from orchestrator.agent import ModelBrain, ScriptedBrain

    if getattr(args, "model_url", None):
        import os
        return ModelBrain(args.model_url, args.model, os.environ.get("ORCHESTRA_API_KEY", ""))
    return ScriptedBrain()


def _ask(args: argparse.Namespace) -> int:
    from adapters.control_archive import ControlArchive
    from orchestrator.agent import diagnose, trigger_for
    from viewer.precedents import first_ask_time

    store = _open(args)
    as_of = from_iso(args.as_of) if args.as_of else first_ask_time(store, args.incident)
    trig = trigger_for(store, args.incident, as_of)
    if trig is None:
        print("No symptom of that problem is on record at that moment.", file=sys.stderr)
        return 1
    print(f"Q: {trig.question}")
    _print_answer(store, diagnose(trig, _brain(args), store, ControlArchive.find(args.db)))
    return 0


def _demo(args: argparse.Namespace) -> int:
    """The proposal's Fig. 2 story on the synthetic Record: one problem met twice."""
    import json

    from adapters.control_archive import ControlArchive
    from orchestrator.agent import ScriptedBrain, diagnose, trigger_for
    from utils import to_iso

    store, archive = _open(args), ControlArchive.find(args.db)
    planted = json.loads((Path(args.db).parent / "planted.json").read_text())["planted"]
    first, second = [c for c in planted if c["mode"] == "configure_failure"][:2]
    end = store.latest_known_at()
    cases = [("1. Crew 1 meets a new problem", first, first["ask_at"]),
             ("2. Crew 2 meets it again, the next fill", second, second["ask_at"]),
             ("3. The same question, after the experts closed both incidents", second, end)]
    print("SYNTHETIC, NOT CMS DATA. Scripted brain: a fixed procedure, no language model.\n")
    for title, case, as_of in cases:
        trig = trigger_for(store, case["incident_id"], as_of)
        print(f"{title}  (as of {to_iso(as_of)})")
        print(f"Q: {trig.question}")
        _print_answer(store, diagnose(trig, ScriptedBrain(), store, archive))
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestra", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("synth", help="build a synthetic Record for the example device")
    p.add_argument("--preset", default="tiny", choices=["tiny", "small", "full"])
    p.add_argument("--seed", type=int)
    p.add_argument("--max-size-mb", type=float, help="size budget; never above 100")
    p.add_argument("--out", default="out", help="output directory (default: out)")
    p.add_argument("--force", action="store_true", help="rebuild if the Record already exists")
    p.set_defaults(func=_synth)

    def reader(name: str, help: str) -> argparse.ArgumentParser:
        q = sub.add_parser(name, help=help)
        q.add_argument("--db", default="out/record.db")
        q.add_argument("--as-of", help="show the Record as it stood at this time")
        return q

    p = reader("info", "row counts, entry types and the incident list")
    p.set_defaults(func=_info)

    p = reader("show", "one incident as a text timeline")
    p.add_argument("incident", type=int)
    p.set_defaults(func=_show)

    p = reader("plot", "PNG timeline of one element's readings and records")
    p.add_argument("element")
    p.add_argument("--from", dest="t_from")
    p.add_argument("--to", dest="t_to")
    p.add_argument("--out")
    p.set_defaults(func=_plot)

    p = sub.add_parser("view", help="open the Record in a local web page")
    p.add_argument("--db", default="out/record.db")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=_view)

    p = reader("ask", "ask the agent about a problem, as of a moment")
    p.add_argument("incident", type=int, help="the incident whose symptoms the crew is looking at")
    p.add_argument("--model-url", help="an OpenAI-compatible endpoint; without it the scripted brain answers")
    p.add_argument("--model", default="", help="model name for --model-url")
    p.set_defaults(func=_ask)

    p = reader("demo", "the Fig. 2 story: one problem met twice")
    p.set_defaults(func=_demo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
