# aggregator

The aggregator owns the **Operations Record**: the database, the code that writes to it,
and the code that reads from it. Everything else in this repository goes through it:
the synthetic device writes through it, and the GUI (and later the agent's tools) read
through it. It is the only folder that contains SQL.

> The Record here is filled by a synthetic generator (`example_device/`), not by real
> sources. The aggregator itself does not know or care; it would accept entries from a
> real feed through the same write API.

## Files

| File | What it is |
|---|---|
| `schema.sql` | The eight tables, in portable SQL |
| `store.py` | `RecordStore`: the write API, the as-of read API, and inspection helpers |
| `schema_doc.py` | What every table and column means, for people (shown by the GUI's Tables page) |
| `view.py` | Terminal and PNG views: `orchestra info`, `show`, `plot` |

The entry envelope itself (`Entry`) is defined in `utils/entry.py`, because producers that
never touch the database need it too.

## What has been done

**The tables.** `element` (parts of the detector), `element_relation` (which supply powers a
box, which FED reads it), `entry` (one row per recorded thing), `part_ref` (every part an entry
or incident concerns, with a role and its own time), `link` (between two entries), `incident` and
`incident_entry` (problems and the entries that belong to them), the calendar (`fill`, `run`,
`beam_mode`), `certification` (when each run was certified per subdetector), `query_log` (every
read the agent's tools will make), `meta` (what built this Record).

**The write API.** `add_element`, `relate`, `add_entry`, `supersede`, `add_link`,
`open_incident`, `attach`, `label_incident`, `set_incident_end`, `close_incident`,
`log_query`. Every write states its own known-at time.

**The read API.** Every read that returns Record content takes `as_of` and returns
nothing the Record learned later: `entries`, `count_entries`, `get_entry`, `state_at`,
`links`, `incidents`, `incident`, `incident_entries`, plus element navigation (`parent`,
`ancestors`, `children`, `subtree`, `related`). Replay helpers (`incident_frame`,
`incident_entries_seen`, `incident_step_times`, `next_known_at`, `became_known`) return
times or a frame, never later content.

**Tested** in `tests/test_store.py`, `tests/test_as_of.py`, and through the GUI's service in
`tests/test_viewer.py`.

## Choices, and why

| Choice | Why | Cost |
|---|---|---|
| **Two times per entry**: when it happened (`t_start`, `t_end`) and when the Record learned of it (`known_at`). Every read names a moment. | A question about the past must not see how things turned out. This is what makes replay, the precedent test and fair evaluation possible. The same code serves live use (moment = now) and replay. | Every read method must carry `as_of`; easy to forget when adding one. Tests sample random moments to catch it. |
| **Append-only.** A correction is a new entry naming the one it supersedes. Incident labels are written once. | Expert verdicts and history must survive reprocessing (proposal Sec. 3.1). A replay at an earlier moment still sees the old version. | Storage grows; reads must hide superseded rows. |
| **Three incident labels kept apart**, each with its own known-at: recovery action, confirmed cause, certification. Status is derived, not stored. | What restored running is not why it happened, and the two are learned days or weeks apart. Many problems never get a cause. | More columns than a single "resolution" field. |
| **One common envelope, free-form payload.** Source, class, kind, type, element, times, pointer, producer are fixed; the payload is whatever the source gives. | Normalize the envelope, never the payload: a new source needs no schema change. | Nothing checks a payload's shape; see "Next steps". |
| **Four kinds of entry**: state (holds until the next change), point (an instant), report (a statement about an interval), feature (a summary of bulk data over a window). | Sources mean different things by a timestamp. `state_at` must look back to the last change however old, or a quiet supply looks like missing data. | `feature` was added during the build and was not in the agreed design. |
| **No time series in the Record.** A reading is recorded only when its status changes (normal, drifting, low, high, off), as a state entry pointing into the source archive. The series itself is fetched from the source on demand (`adapters/control_archive.py`). | Storing windows grew as parts × quantities × windows: 90% of all entries. Averaging in advance cannot be undone; the source keeps full resolution. Decided by the project lead, 17 November 2026. | What the Record says about a reading depends on the status rule. Anything the rule misses is only in the source. |
| **Service relations as their own table.** | A fault in a supply shows up in every box it powers. One parent pointer cannot say that. | Two kinds of neighbour to follow instead of one. |
| **SQLite for now, all SQL in `store.py`.** | One file, no server, easy to hand to co-PIs. Confining SQL to one module makes a move to PostgreSQL a rewrite of one file. | No write roles, no range types, no concurrent writers (see below). |
| **Opened read-only by default.** | The GUI and the agent must not be able to change the Record. | Writers must ask for write access explicitly. |

## Known limits

- **Part references are written by the generator**, which knows where it planted each fault.
  In production the summarizer would propose them and experts confirm them.
- **Entry types are free strings.** There are 19 in the `tiny` Record and 20 in `small`,
  because that is what the generator writes. Nothing lists them, defines them, or says
  which class and kind each belongs to; the class is repeated on every row.
- **Status changes depend on a hand-picked rule** (`example_device/readings.py`): a band
  around the setpoint, a slope threshold, and a 10-minute hold. Before 17 November the Record
  stored window summaries instead, 90% of all entries in `tiny`; it now stores 24 status
  entries there (8%), and 112 of 5,084 in `small`.
- **The producer writes the links.** In the proposal the aggregator builds direct links
  itself from shared identifiers and times. Here the generator writes them.
- **No write roles.** The proposal's per-subsystem write access (Sec. 3.2) is not modelled.
- **No plots or attachments.** There is no way yet to keep an image an expert relied on.
- **`query_log` is empty** until the agent's tools exist.

## Next steps

In rough order of how much else depends on them:

1. **The detector model**: integrate cmscoord (`docs/DETECTOR_PLAN.md`); `part_ref` would then
   hold cmscoord part identifiers.
2. **A catalogue of entry types**: one row per (source, type) with its class, kind, unit,
   meaning, expected payload fields and owning subsystem. The class moves off each entry.
   New types are registered, not invented; the GUI can group and colour by it.
3. **Status rules per quantity, owned by the subsystem**, instead of one hand-picked rule
   in the generator; and the same treatment for the other bulk source, data quality.
4. **Build direct links in the aggregator**, not in producers.
5. **Plots attached to incidents**: an entry holding a pointer to an image, in practice
   mostly logbook attachments (`docs/DESIGN.md` 7a).
6. **PostgreSQL port with write roles**, once the schema settles.

## Changes on 17 November 2026

Decided by the project lead, to stop routine records dominating the Record (`small` went from
5,084 entries to 763):

| What | Before | Now |
|---|---|---|
| Per-run data quality per box | one entry per run and box (62%) | numbers stay in a data-quality archive; one `quality_status` entry per change, against a reference per subdetector (`quality_reference`) |
| Runs, fills, beam modes | entries (8% plus 2%) | calendar tables `run`, `fill`, `beam_mode`; only fault stops and non-routine configure attempts stay entries |
| Certification | a flag per run and subdetector (15%) | `certification` records when each was completed; only bad ranges are entries; good is inferred (`lumisection_status`) |
| Parts | one element per entry and incident | `part_ref`, with roles and times; `entry.element_id` and `incident.element_id` keep a copy of the filed or reported part |

The "same element" precedent rule became "shares a part".
