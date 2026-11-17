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
box, which FED reads it), `entry` (one row per recorded thing), `link` (between two entries),
`incident` and `incident_entry` (problems and the entries that belong to them),
`query_log` (every read the agent's tools will make), `meta` (what built this Record).

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
| **Service relations as their own table.** | A fault in a supply shows up in every box it powers. One parent pointer cannot say that. | Two kinds of neighbour to follow instead of one. |
| **SQLite for now, all SQL in `store.py`.** | One file, no server, easy to hand to co-PIs. Confining SQL to one module makes a move to PostgreSQL a rewrite of one file. | No write roles, no range types, no concurrent writers (see below). |
| **Opened read-only by default.** | The GUI and the agent must not be able to change the Record. | Writers must ask for write access explicitly. |

## Known limits

- **One element per entry and per incident.** A root cause often involves several parts.
  This was a schema shortcut, not a modelling decision. (To do; see `docs/DESIGN.md` 7b.)
- **Entry types are free strings.** There are 19 in the `tiny` Record and 20 in `small`,
  because that is what the generator writes. Nothing lists them, defines them, or says
  which class and kind each belongs to; the class is repeated on every row.
- **Sparsified time series dominate.** In `tiny`, 2,304 of 2,569 entries (90%) are voltage
  and temperature window summaries; in `small`, 23,040 of 28,012 (82%). This grows as
  parts × quantities × windows and will not scale to a real detector.
- **The producer writes the links.** In the proposal the aggregator builds direct links
  itself from shared identifiers and times. Here the generator writes them.
- **No write roles.** The proposal's per-subsystem write access (Sec. 3.2) is not modelled.
- **No plots or attachments.** There is no way yet to keep an image an expert relied on.
- **`query_log` is empty** until the agent's tools exist.

## Next steps

In rough order of how much else depends on them:

1. **Several elements per entry and incident**: a table "this entry concerns these
   elements", each with a role. Changes the read API, the detector map, timelines and the
   "same element" precedent rule.
2. **A catalogue of entry types**: one row per (source, type) with its class, kind, unit,
   meaning, expected payload fields and owning subsystem. The class moves off each entry.
   New types are registered, not invented; the GUI can group and colour by it.
3. **Take bulk time series out of the entry table**: keep them in a separate series store
   (a table or columnar files) addressed by element, quantity and window, and let the
   Record hold only what something can be said about: state changes, excursions, and a
   pointer to the series. To be decided with the sparsifier design; see
   `docs/DESIGN.md` 7a.
4. **Build direct links in the aggregator**, not in producers.
5. **Plots attached to incidents**: an entry holding a pointer to an image, in practice
   mostly logbook attachments (`docs/DESIGN.md` 7a).
6. **PostgreSQL port with write roles**, once the schema settles.
