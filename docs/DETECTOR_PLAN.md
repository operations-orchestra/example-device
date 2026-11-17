# Plan: a realistic detector model, by integrating cmscoord

Status: plan only, 17 November 2026. Nothing here is built. The demo keeps its own toy
detector until this plan is carried out.

## 1. Why

Everything in the Record is about a part of the detector, so the detector model sits under
everything else. The toy model in this repository (`example_device/model.py`, stored in the
`element` and `element_relation` tables) was enough to get started, and is now the limit:

| Limit of the toy model | Consequence |
|---|---|
| A handful of invented parts: subdetector, readout box, channel, supply, FED | Nothing resembles the real addressing schemes experts use (ieta/iphi/depth, RBX/RM/QIE, crate/slot/fiber) |
| One parent per part, plus hand-made "powered by" and "read out by" links | Questions like "which channels does this fiber cover" cannot be asked |
| Every entry and incident names exactly one part | A root cause involving a box and its supply, or two subsystems, cannot be recorded (to-do in DESIGN.md 7b) |
| The parts and links have no times | Recabling, replacements and additions over 16 years cannot be represented; the map is not "as of" a moment like everything else |
| The low-voltage supplies and their links are invented | The voltage-sag scenario has no real counterpart yet |

## 2. cmscoord

cmscoord (repository: `git@github.com:kakwok/cmscoord.git`) is a separate tool, written
before the Orchestra; the project lead will introduce it to the other PIs. It translates sets of CMS channels between the schemes that address them, and is
meant to become part of the Orchestra as its detector model. What it already has:

- **Channels as units, grouped in several views ("layers")**: logical (ieta, iphi, depth),
  frontend (RBX, RM, QIE card, channel), backend (crate, slot, uHTR/FED, fiber), trigger,
  and physical. HCAL, ECAL and CSC are done. HCAL is about 21,000 channels.
- **Three tables**: units (one row per channel atom, with position), components (every named
  part in every layer, as a tree per layer), membership (unit to its leaf part per layer).
  Going between views is a join through the units, so "which FEDs does this RBX feed" is
  derived, never hand-entered.
- **Map versions tied to time.** A version is identified by the hash of the conditions
  payloads that produced it, and covers the runs over which the cabling was constant. A map is
  opened by (global tag, run), never "latest".
- **A clean split.** Maps are built on cmslpc with CMSSW; the query library needs only Python,
  pyarrow and PyYAML. A synthetic fixture of about 100 HCAL units, in the real file formats,
  lets everything run and be tested without CMS infrastructure.
- **Its own validation GUI**: select a part in one view and see its channels in every other.

What it does not have, and the Orchestra needs:

- **No low-voltage, high-voltage or DCS layer.** cmscoord's own reconnaissance found no HCAL
  DCS map in the conditions database at all. A source for "which supply powers what" still has
  to be found.
- **Maps are keyed by run; the Record is keyed by time.** A lookup from time to run is needed
  (the lumisection clock, already named in the design notes).

## 3. Decisions

| Decision | Date |
|---|---|
| cmscoord becomes the Orchestra's detector model, used as a dependency through its query library, not copied. It stays its own repository. | 17 November 2026 |
| For now the demo keeps the toy detector in this repository; this plan is written down and carried out later. | 17 November 2026 |

## 4. Target design

### 4.1 One interface, two implementations

A new `detector/` package. Everything else (the generator, the aggregator's readers, the GUI,
later the agent's tools) talks to the detector only through it:

| Call | Returns |
|---|---|
| `at(t)` | the detector map in force at time `t` (a handle; all calls below go through it) |
| `layers()` | the views available, with their levels, and the views declared absent |
| `part(id)` / `children(id)` / `parent(id)` | a part and its place in its view |
| `units(id)` | the channels a part covers |
| `translate(ids, to_layer, level)` | the parts in another view that cover them, with how much of each |
| `layout(layer)` | how to draw a view (cmscoord's manifest declares a 2D grid per layer) |

Implementations:

1. **Toy** (first): today's generator model reshaped to fit, with two layers (detector side,
   service side). Lets everything be moved onto the interface without changing behaviour.
2. **cmscoord** (second): a thin adapter over cmscoord's `open_map`, `resolve`, `translate`,
   `layers`, `describe`. Uses the synthetic fixture by default; a real map when one is given
   as a local path.

### 4.2 How the Record refers to parts

| Today | After |
|---|---|
| `entry.element_id`, one part per entry | a separate table: entry, part identifier, role (for example affected, suspected, reported on) |
| `element` and `element_relation` own the detector | the Record stores part identifiers as given by the detector model (for example `HCAL/backend/crate12/slot3`); it does not own the tree |
| No map version | each entry records the map version in force when it was written, so it stays readable after recabling |

The `element` table may survive as a cache of the parts the Record actually mentions, for
fast reads and for a Record copied away from the maps.

### 4.3 Concepts, side by side

| Orchestra | cmscoord |
|---|---|
| element (a part) | component, in one layer |
| channel | unit (a channel's share of one trigger tower; count channels by distinct DetId) |
| parent pointer | `parent_id` within a layer |
| "read out by" link | derived: `translate(units(box), "backend", level="fed")` |
| "powered by" link | no counterpart yet (no LV layer); stays an overlay |
| "as of" a moment | map version for the run at that time |

### 4.4 The low-voltage gap

Until a real source exists, supply-to-part links stay an **overlay owned by the Orchestra**,
in the same format as a cmscoord layer, marked as invented in the demo. When a real source is
found it becomes a cmscoord layer and the overlay is dropped.

## 5. Stages

| Stage | Build | Done when |
|---|---|---|
| A | `detector/` interface; toy implementation from `example_device/model.py` | everything reads the detector through the interface; all tests still pass; the GUI looks the same |
| B | Several parts per entry and per incident (to-do 7b) | the generator can name a box and its supply on one cause; the "same element" precedent rule becomes "shares a part" |
| C | cmscoord adapter on its synthetic fixture; the low-voltage overlay | the generator plants its faults on cmscoord parts (RBX, crate/slot, FED); the detector page draws the frontend and backend views; the GUI links to cmscoord's own GUI for cross-view checks |
| D | Time-dependent maps: time to run, run to map version | a replay before and after a recabling shows the map in force at each moment |
| E | A real HCAL map, local only | the generator runs on the real structure; nothing from the real map is committed |

## 6. Open questions

1. **Can a real cabling map be used in a public repository?** It comes from the conditions
   database. Until cleared, real maps stay local and uncommitted.
2. **Where would a low-voltage map come from**, if not CondDB? Possibly the DCS configuration
   database or an HCAL operations spreadsheet.
3. **Transport.** Import cmscoord as a library (planned), or serve it over MCP as the earlier
   design notes suggested? Deferred until the agent needs it.
4. **Introducing cmscoord to the other PIs**: the project lead will do this.

## 7. What this absorbs

- To-do "let an entry or incident name several elements" (DESIGN.md 7b) becomes stage B.
- The note that the detector map has no times becomes stage D.
- The demo's invented supply links become the low-voltage overlay.
