# example-device

A synthetic, HCAL-like example device with heterogeneous operations records, and a
prototype of the Operations Orchestra that runs on it.

> **Synthetic, not CMS data.** Detector names follow public CMS naming (HB, HF, readout
> boxes, FEDs). Every event, time, run number, reading and logbook line is invented by a
> seeded generator.

## Rule for this repository

Real detector **names** are fine. Real **events** are never used: no real incidents,
run or fill numbers, timestamps, host names, or logbook text. The generator enforces
this by construction (the calendar starts in 2040, run numbers at 900001, fill numbers
at 50001) and a test checks it.

## Status

Work in progress on the branch `prototype/synthetic-record`. The design, the decisions
behind it, the next steps and hand-off notes are in [docs/DESIGN.md](docs/DESIGN.md).

| Folder | What it is | State |
|---|---|---|
| `utils/` | the shared entry definition and time helpers | runs |
| `aggregator/` | the Operations Record (SQLite), its write and read APIs, viewing tools | runs |
| `example_device/` | the seeded generator for the synthetic device | runs |
| `viewer/` | a local, read-only web page for looking inside the Record and its components | runs |
| `adapters/` | reads a source system on demand; one so far, for the simulated control-system archive | runs |
| `orchestrator/` | typed query tools and the diagnosis agent | not built yet |
| `anonymizer/`, `summarizer/`, `sparsifier/`, other adapters | the rest of the feed into the Record | not built yet |

The folders are named after the repositories of the `operations-orchestra` organization
so each can move to its own repository later. A test keeps their imports separate.

## Quick start

```bash
pixi install
pixi run orchestra synth                 # builds out/record.db, out/planted.json, and a simulated
                                         # control-system archive in out/source/ (not part of the Record)
pixi run orchestra view                  # open http://127.0.0.1:8765/ to browse the Record
pixi run orchestra info                  # row counts, entry types, incident list
pixi run orchestra show 3                # one incident as a text timeline
pixi run orchestra show 3 --as-of 2040-03-02T12:06   # the same incident as the Record knew it then
pixi run orchestra plot HFP02 --from 2040-03-01T10:00 --to 2040-03-02T20:00
pixi run pytest -q
```

Without pixi: `pip install -e '.[plot,dev]'` on Python 3.10 or later.

## The Record browser

`orchestra view` starts a local web page (Python standard library only, bound to
localhost, Record opened read-only). Use `--db out/small/record.db` for the larger preset.

It is ordered for a first-time reader:

1. **The detector**: the model everything else refers to.
2. **How the Record is built**: the designed feed next to what the demo does instead,
   and the design choices the demo fixes silently.
3. **What is in the Record**: tables, entries, incidents, timelines, shown complete.
4. **Scenarios in this demo**: the situations the generator planted.
5. **Replay**: wind the Record back to a moment and step through an incident. Only
   here does a time control appear; while it is on, every page shows the Record as it
   stood then.

See [docs/GUI_PLAN.md](docs/GUI_PLAN.md), section 11.

## The synthetic Record

Sizes: `--preset tiny` (default, about 1 MB, 3 days), `small` (about 10 MB, 30 days),
`full` (up to 100 MB). `--max-size-mb` sets a budget; the generator coarsens or shortens
the data to fit and refuses anything above 100 MB. Generated files are not committed.

Every entry has two times: when it **happened** and when it became **known to the
Record**. Every read takes an "as of" time and returns only what was known by then, so
a question about a past moment cannot see how things turned out.

Planted situations:

| Mode | What it is |
|---|---|
| `configure_failure` | HCAL fails to configure on the first two fills after a technical stop |
| `fed_comm_loss` | a FED goes out of sync; recurs, and is understood only after it recurs |
| `lv_drift_trip` | a low-voltage supply sags for hours, then trips |
| `hot_channels` | no downtime, but the data are certified bad |
| `box_sync_loss` | recovered by a reset and never explained |
| `planned_change` | a deliberate threshold change that looks like a fault and is not one |

`out/planted.json` lists what was planted and the honest answer at each moment. It is
for tests and is never part of the Record.

## Known limits

- Logbook text comes from a few hand-written templates per situation. It is far more
  regular than a real logbook, so finding a precedent is easier here than in reality.
- Data-quality records are numbers only; there are no plot images yet.
- The device writes the Record directly. It does not yet emit raw-format source records,
  which is what the feed stages would consume.
- SQLite has no write roles; per-subsystem write access is not modelled.
- A Record built here shows that the plumbing works. It says nothing about diagnostic
  ability on real records.
