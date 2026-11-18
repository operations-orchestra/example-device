# example-device

A prototype of the **CMS Operations Orchestra** on a synthetic, HCAL-like example device:
the Operations Record (every entry with when it happened and when it became known), a
browser to look inside it and replay incidents as a crew met them, and a diagnosis agent
that answers "has this been seen before, and what should we do?" with cited evidence.

> **Synthetic, not CMS data.** Detector names follow public CMS naming (HB, HF, readout
> boxes, FEDs). Every event, time, run number, reading and logbook line is invented by a
> seeded generator, which writes the Record directly: none of the software that would build
> it from real sources runs yet.

## Try it

- **No installation:** open the single-file demo in a browser,
  `out/small/demo/orchestra-demo.html` (rebuild it with
  `pixi run orchestra export-static --db out/small/record.db`). It is a snapshot of one
  30-day Record: every page, and Replay with the agent's answer at every step of every
  incident.
- **Live:** `pixi install`, then `pixi run orchestra synth --preset small --out out/small`
  and `pixi run orchestra view --db out/small/record.db`, then open http://127.0.0.1:8765/.
- **Terminal:** `pixi run orchestra demo` prints the proposal's Fig. 2 story: one problem,
  met twice by two crews.

Read the pages in their numbered order: the detector, how the Record is built, what is in
it, the planted scenarios, Replay, and the agent.

## Next design tasks: where we would like your input

Everything below is open. The prototype fixes a first answer to each so the rest could be
built; none of those answers is settled. The relevant work package from the proposal is
given in brackets.

**The Record**

1. **A realistic detector model.** Replace the toy detector with cmscoord (channels and
   their logical, frontend, backend, trigger and physical addressing, versioned by
   conditions); parts and their cabling then change over time like everything else. Plan:
   [docs/DETECTOR_PLAN.md](docs/DETECTOR_PLAN.md). Open: where a low-voltage map comes from;
   whether a real cabling map may appear in a public repository. [WP1]
2. **What the Record keeps of bulk sources.** Readings and per-run data quality stay in
   their sources; the Record keeps only status changes, decided by hand-picked rules. Who owns
   each subsystem's rules, and what should they be? Is a coarse baseline needed for
   anticipation (Q2)? [WP1, WP4]
3. **Plots relevant to an incident.** Keep the few plots experts relied on, mostly
   logbook attachments: who or what selects them, and copy or point? [WP2]
4. **Vocabulary.** The kinds of symptom, the roles a part plays in a record (filed,
   mentioned, affected, suspected, cause), the incident labels (recovery, cause,
   certification). Do these match how experts think? [WP2, WP3]
5. **Routine volume.** Shift notes are now 43% of entries, mostly "run started". Keep,
   summarize, or drop? [WP1]

**The feed into the Record** (interfaces only today; see the browser's "Interfaces of
unbuilt parts")

6. **Which source first**, with real records: logbook, downtime, certification, run control,
   control system. [WP1]
7. **Anonymizer and summarizer:** the two-pass design, its audit, and which local models.
   [WP1]
8. **What triggers the agent** in production: a crew's question, or an automatic watcher on
   failed configures, downtime and status changes. The demo cheats here: it takes the
   symptoms from the incident the generator later writes. [WP3]

**The agent**

9. **The confidence.** "Seen before" is a number learned from precedent reviews, with expert
   priors and thresholds (known from 70%, new below 30%). Are those right, and should there
   be more kinds of match (for example "same subdetector")? [WP3, WP5]
10. **The review loop.** The confidence learns from people confirming or rejecting a
    recalled precedent. Who reviews, where, and when? In the demo the generator invents the
    reviews. [WP2, WP5]
11. **LLM brains against the scripted brain** on the same moments, through the profiles in
    `config/llm.yaml` (ignored by git). Which models, and how to score them. [WP3, WP4]

**Evaluation**

12. **Is the synthetic data plausible?** Fault signatures, the delays before a recovery and a
    cause are written down, the logbook wording. Only experts can say. [WP2]
13. **Real incidents.** Replay curated HCAL incidents (the 2023 case study) through the same
    as-of path; the synthetic results say only that the plumbing works. [WP4, WP5]

**Infrastructure**

14. SQLite to PostgreSQL with per-subsystem write roles; splitting the folders into the
    organization's repositories; persisting the agent's query log. [WP3, WP6]

To contribute: open an issue in this repository, or comment on the Record browser's pages
during the walkthrough. The design history and decisions are in
[docs/DESIGN.md](docs/DESIGN.md), the browser's in [docs/GUI_PLAN.md](docs/GUI_PLAN.md).

## Rule for this repository

Real detector **names** are fine. Real **events** are never used: no real incidents,
run or fill numbers, timestamps, host names, or logbook text. The generator enforces
this by construction (the calendar starts in 2040, run numbers at 900001, fill numbers
at 50001) and a test checks it.

## Status

Work in progress on the branch `prototype/synthetic-record`.

| Folder | What it is | State |
|---|---|---|
| `utils/` | the shared entry definition and time helpers | runs |
| `aggregator/` | the Operations Record (SQLite), its write and read APIs, viewing tools ([README](aggregator/README.md)) | runs |
| `example_device/` | the seeded generator for the synthetic device and its simulated source archives | runs |
| `adapters/` | reads a source on demand; two so far, for the simulated control-system and data-quality archives | runs |
| `orchestrator/` | the agent's six read-only tools, its confidence, the scripted brain, and an LLM brain | runs; the LLM brain has not yet been tried on a real endpoint |
| `viewer/` | the Record browser, and its single-file export | runs |
| `anonymizer/`, `summarizer/`, `sparsifier/`, `adapters/base.py`, `aggregator/linker.py` | the rest of the feed, and the direct-link builder | interfaces only |

The folders are named after the repositories of the `operations-orchestra` organization
so each can move to its own repository later. A test keeps their imports separate.

## Quick start

```bash
pixi install
pixi run orchestra synth                 # builds out/record.db, out/planted.json, and a simulated
                                         # control-system archive in out/source/ (not part of the Record)
pixi run orchestra view                  # open http://127.0.0.1:8765/ to browse the Record
pixi run orchestra demo                  # the Fig. 2 story in the terminal
pixi run orchestra export-static         # the browser as one HTML file, no server needed
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
5. **Replay**: wind the Record back to a moment and step through an incident, with the
   agent's answer at each step. Only here does a time control appear; while it is on,
   every page shows the Record as it stood then.
6. **The agent**: what it does, and how it did on every incident.

See [docs/GUI_PLAN.md](docs/GUI_PLAN.md), sections 11 and 12.

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

## The LLM brain

The agent's scripted brain needs nothing. To compare it with a language model, list your
endpoints in `config/llm.yaml`, which git ignores (`$ORCHESTRA_LLM_CONFIG` overrides). Start
from `config/llm.example.yaml`. Profiles name endpoints and models, never keys: each says
which variable holds its key (`api_key_env`). Only the keys live outside the repository.

Each key is looked up first in the environment, then in `~/.config/orchestra/keys.env`, one
`NAME=value` per line, which must be readable only by you:

```bash
mkdir -p ~/.config/orchestra && touch ~/.config/orchestra/keys.env && chmod 600 ~/.config/orchestra/keys.env
# then add lines such as  GATEWAY_API_KEY=...  with an editor
```

- `pixi run orchestra profiles` lists the profiles and whether each key is found, never the key.
- `pixi run orchestra ask 10 --profile gateway` asks one question in the terminal.
- In Replay, "Compare with an LLM brain" asks the chosen profile and shows its answer under the
  scripted brain's, with the same check. Nothing is sent until you press "Ask"; what is sent is
  the question and the Record entries the model asks for, which here are synthetic. Restart
  `orchestra view` after changing profiles or keys.
