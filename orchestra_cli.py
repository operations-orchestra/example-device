"""Command line for the Operations Orchestra prototype.

    orchestra synth [--preset tiny] [--seed 1] [--max-size-mb N] [--out out] [--force]
    orchestra info  [--db out/record.db] [--as-of TIME]
    orchestra show  INCIDENT_ID [--as-of TIME]
    orchestra plot  ELEMENT [--from TIME] [--to TIME] [--as-of TIME] [--out FILE]

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
    print(f"Wrote {result['db']} ({result['size_mb']} MB of {cfg.max_size_mb} MB allowed)")
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
    path = plot_element(store, args.element, out,
                        t0=from_iso(args.t_from) if args.t_from else None,
                        t1=from_iso(args.t_to) if args.t_to else None, as_of=_as_of(args))
    print(f"Wrote {path}")
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
