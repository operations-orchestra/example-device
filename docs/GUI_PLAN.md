# Plan: a GUI to understand and check what has been built

**The GUI was remade on 16 November 2026. Section 11 describes it as it is now and
supersedes the page list, the three marks and the switches in sections 4 to 6 and 10.**

Earlier status: steps 1 to 5 and the Read API page were built (16 November 2026). Not built: the
Build-a-Record control (still an open decision), and the Tools, Agent and Feed pages, which
wait for the orchestrator. See section 10 for what was built differently from this plan.
Read [DESIGN.md](DESIGN.md) first for vocabulary and the current state of the code.

## 1. Purpose

So far the prototype can only be inspected through four terminal commands and static
plots. That is not enough for a person to understand what each component does, or to
judge whether the synthetic data is believable.

The GUI has one job: **let a person see inside each component and operate it by hand.**
It is not a product for shift crews and it is not a test suite.

It must be good enough to answer two questions that are currently blocked:

- **Q1.** Does the synthetic data look plausible to a detector expert?
- **Q2.** What should count as a precedent: the same element, or the same symptom
  anywhere in the detector?

## 2. What "understand a component" means here

For each component the GUI should show three things: what goes in, what comes out, and
what happens when you change something.

| Component | See | Operate |
|---|---|---|
| **Example device** (the generator) | the detector tree, the calendar of fills and runs, each fault script and exactly what it wrote | choose preset, seed and size; build a new Record; compare it with the previous one |
| **The Record** (aggregator) | the tables, every entry with its full envelope, links, incidents | filter and search entries; follow a link; open an incident |
| **As-of reads** | the same screen at two different moments | move one time control and watch entries, labels and links appear |
| **Read API** | each read method, its arguments and what it returns | fill in a form, run the call, see the rows that come back |
| **Query tools** (once built) | the five agent tools and the query log | run a tool by hand exactly as the agent would |
| **Agent** (once built) | the question, each tool call, the structured proposal, every citation | ask a question at a chosen moment, switch between the two brains |
| **Feed interfaces** (once built) | what each stage must accept and return | nothing to run; shown as documentation |

## 3. Ground rules

1. **The GUI calls the real code.** Every number on screen comes from the same Python
   read methods the agent will use. The browser does no filtering of its own, so what you
   see is what the tools do.
2. **One time control at the top of every page.** Nothing shown is ever later than it.
3. **The Record is never modified.** "Build a new Record" writes a new file in a scratch
   folder and switches the GUI to it.
4. **Demo-only features are visibly separate from production-like ones.** See section 4.
5. **Runs offline from a clone,** with one command and no build step.
6. **Every page says "synthetic, not CMS data".**

## 4. Demo-only versus production-like

Because the data is synthetic, we hold all the answers: we know which faults exist, where
they are and what the right diagnosis is. A real Record has none of that. The GUI must
make it obvious which features rely on that knowledge, so nobody mistakes a demo
convenience for something the production system will have.

Every page, panel and field carries one of three marks:

| Mark | Meaning | Examples |
|---|---|---|
| **Production-like** (no badge, normal style) | Works the same on a Record built from real sources. Uses only what is in the Record. | Record pages, Timeline, Incident, time control, Read API, later the query tools and the agent |
| **Expert-filled** (outlined badge) | Present in a real Record only where experts have reviewed an incident. Here the generator wrote it for every incident. | incident grouping, recovery and cause labels, links with a stated reason |
| **Demo only** (coloured band and badge) | Exists only because the data is synthetic. Has no counterpart in production. | the Device page and its fault scripts, building a Record, planted answers, expected verdicts, the knowledge that a planned change is a trap |

How this shows in the GUI:

- The navigation is split into two groups, **Record** and **Demo only**.
- A switch at the top, **"Production view"**, hides everything marked demo only. With it
  on, the GUI shows exactly what an operator of a real Record would have.
- Demo-only content never appears inside a production-like page unless the switch
  "show planted answers" is on, and then it is drawn in the demo style.
- The Home page states the split in two sentences and lists which pages fall where.

One consequence for the Precedents page: "same symptom" must be worked out from what is
in the Record (entry types, elements, wording), never from the generator's fault mode.
The generator's fault mode may be shown beside it, as a demo-only column, to check the
match.

## 5. Pages

In the headings below, **[R]** is production-like and **[D]** is demo only.

### 5.1 Home [R]

- What Record is loaded: preset, seed, size, date range.
- A strip of the whole calendar: fills, the technical stop, downtime, incidents. Click
  anywhere to set the time control.
- A diagram of the components (the one in DESIGN.md) where each box links to its page.

### 5.2 Device [D]

*Understand the generator.*

- **Detector map.** The tree `CMS > HCAL > subdetector > readout box > channel`, with the
  supply that powers each box and the FED that reads it. Click an element to open its
  timeline.
- **Calendar.** Fills, runs, the stop, as a table and a strip.
- **Fault catalogue.** One card per fault mode. Each card explains the script in words and
  then shows a real occurrence from the loaded Record as a table:

  | What was written | Happened | Known to the Record |
  |---|---|---|

  This is the page for **Q1**. For each mode you can step through every occurrence.
- **Build a Record.** Runs the generator from the page instead of the terminal: choose
  preset, seed and size budget, press Build, and the GUI switches to the freshly generated
  Record. It does not capture or save anything from the Record on screen; it makes a new
  synthetic one. Useful for seeing how seed and size change the data.

### 5.3 Record [R]

*Understand the database.*

- **Tables.** The eight tables with row counts and a one-line description of each.
- **Entries.** A table you can filter by class, source, type, kind, element and time, and
  search by text. Counts update as you filter.
- **Entry detail.** The full envelope, the payload, the producer, the source pointer,
  links in and out, and any corrected versions.
- **Incidents.** The list with status as of the time control; click to open one.

### 5.4 Timeline [R]

*See what a fault looks like.*

- Pick an element. Readings are drawn for it and its surroundings: voltage, temperature,
  dead and hot channel fractions, occupancy. One quantity per panel.
- **Zoom and pan,** with all panels moving together. A "fit to data in view" button
  rescales the vertical axis, so a 0.35 V sag is visible next to a trip to 0 V.
- Below the readings, the same strip as today's static plot: stable beams, downtime,
  certified-bad ranges, state changes, fault events, logbook notes.
- Hover a mark to read it; click it to open the entry.

### 5.5 Incident [R, labels and links expert-filled]

*See how knowledge arrived.*

- Header: status and the three labels (recovery, cause, certification), each shown as
  "not known yet" until the time control passes its known-at time.
- **Two rows on one time axis:** when each entry *happened* (top) and when it became
  *known* (bottom), joined by a line. A root cause written two weeks later is a long
  slanted line; a control-system reading is a vertical one.
- The expert's links, each with its stated reason.
- A "play" button steps the time control through each moment something became known.

### 5.6 Time control (on every page) [R]

- A date and time field, a slider across the calendar, and two buttons: "previous thing
  that became known" and "next thing that became known".
- A small panel listing what the last step added (entries, labels, links).
- A "compare with…" option that pins a second moment and marks what differs.

### 5.7 Precedents [R, with a demo-only check column]

*The page for **Q2**.*

For one chosen problem at its ask time, two columns side by side:

| Same element | Same symptom anywhere |
|---|---|
| earlier incidents on this element | earlier incidents of this kind on any element |

Each row shows what was known about that earlier incident at the ask time: recovery,
cause, or neither. A summary line counts, across the whole Record, how many problems
would be called "known" under each rule. Run it on the `small` preset, where there are
23 incidents and the two rules disagree.

### 5.8 Read API [R]

*Operate the Record by hand.*

- One form per read method that exists today: entries in a window, state at a time,
  incidents, one incident's entries, links of an entry, element relations.
- Run it and see the returned rows, the time it used, and the equivalent Python call to
  copy.

### 5.9 Planted answers [D]

- The list of planted cases: mode, element, event time, ask time, expected verdict.
- "Go to ask time" sets the time control so you can check the expectation against what
  the Record shows.

### 5.10 Later, after the orchestrator exists [R, expected verdicts D]

- **Tools.** The Read API page gains the five agent tools and a view of the query log,
  with a "run again" button on every logged call.
- **Agent.** Ask a question at a chosen moment; choose the scripted or the model brain;
  watch each tool call and its result; read the structured proposal with every citation
  linked to its entry. With the switch on, the expected verdict is shown beside it.
- **Feed.** The four interface definitions, rendered as documentation.

## 6. How it is built

A new folder `viewer/`. It may import `utils`, `aggregator`, `example_device` (only for
the Build button) and, later, `orchestrator`.

```
viewer/
  server.py      local web service on the Python standard library, localhost only
  api.py         one function per endpoint; each is a thin call to RecordStore
  static/
    index.html   one page, tabs for the sections above
    app.js       plain JavaScript, no framework, no build step
    style.css
    vendor/      one charting library, copied in so it works offline
```

Command: `orchestra view [--db out/record.db] [--port 8765]`, which starts the service and
prints the address to open.

Choices made in this plan, and why:

| Choice | Reason | Alternative considered |
|---|---|---|
| Local service plus a static page | the page shows results of the real read methods; no heavy dependency | Streamlit: quicker to write, but a large dependency and awkward for the linked two-row incident view |
| No framework, no build step | anyone can open `app.js` and follow it; easy to hand over | React or similar: nicer for a large app, more to maintain |
| One vendored chart library (uPlot, MIT licence) | small, fast on tens of thousands of points, has synchronized zoom | Plotly: more features, about 3 MB |
| Read-only service; Build writes a new file | the Record on screen cannot be damaged by the GUI | editing in place |

Every endpoint that reads the Record requires an `as_of` argument and refuses the call
without it.

## 7. Order of work

Each step ends with something you can open and judge.

| Step | Build | You can then |
|---|---|---|
| 1 | Service, page shell, time control, the three marks and the "Production view" switch, Home, Record pages | browse every entry and incident at any moment |
| 2 | Timeline with zoom | look at each fault's readings and records together |
| 3 | Incident page with the two-row view and play button | watch how knowledge about one incident arrived |
| 4 | Device page: detector map, calendar, fault catalogue | **answer Q1** |
| 5 | Planted answers and Precedents pages | **answer Q2** |
| 6 | Build-a-Record controls and the Read API page | change the generator's inputs and query by hand |
| 7 | Tools, Agent and Feed pages | after the orchestrator is built |

Steps 1 to 5 use only code that exists today.

## 8. How I will check it

- **Automated:** each endpoint refuses a call without `as_of`; at sampled moments no
  endpoint returns anything known later; the page loads and lists the incidents; the
  Build endpoint never touches the loaded Record file.
- **By eye:** I load each page in a browser and check it against the terminal commands
  for the same Record. Where I cannot open a browser from this environment, I will say so
  and the check is yours.
- **Yours:** steps 4 and 5 exist for your judgment; nothing automated replaces it.

## 9. Decisions

Settled on 16 November 2026: the page list is right; a local web page is the form; demo-only
and production-like features must be clearly distinguished (section 4).

Open: whether the Build control is wanted at all (step 6).

## 10. As built

Run `orchestra view` and open the address it prints.

| Plan | As built |
|---|---|
| Pages 5.1 to 5.9 | built, except the Build-a-Record control on the Device page |
| Tables as a collapsed list on the Entries page | a **Tables** page: a diagram of the eight tables and how their columns point to each other, the meaning of every column, real example rows, and one incident followed row by row through the tables. Column meanings live in `aggregator/schema_doc.py`; a test checks they match the real columns. |
| Detector map as a list on the demo-only Device page | a **Detector map** page (also shown on Home), production-like because it is read from the Record: supplies, boxes with their channels, and FEDs drawn with their connections, each with its state and open issues at the time control |
| A vendored charting library (uPlot) | not used. The charts are about 150 lines of hand-written SVG in `app.js` (`buildChart`, `knowledgeChart`), so there is no third-party code and nothing to download. Revisit if a Record with far more points per series must be drawn. |
| `viewer` may import `example_device` for the Build control | it does not import it. The fault descriptions and the list of entries each fault wrote come from `planted.json`. |
| "Compare with..." | the "Pin for comparison" button: pin a moment, move the time, and the panel under the time control lists what the Record learned in between |
| Incident view on a linear time axis | a compressed axis relative to the incident start (each step is about ten times longer), so minutes and weeks fit together |
| Precedents: "same symptom" | an earlier incident sharing a symptom kind, where the kind is the entry type plus its result, value or flag (for example `configure:failed`). Logbook notes are ignored because every incident has them. Wording is not compared. The code is `viewer/precedents.py`; it should move to the orchestrator once a rule is chosen. |

**Where a local LLM would be at work.** A fourth kind of mark, added after the plan, with its
own switch ("Highlight LLM content", on by default) and a page, **Who writes what**:

| Mark | Meaning |
|---|---|
| LLM-written | text a local model composes in production (summaries of expert material) |
| LLM draft, expert confirms | a model proposes, a person decides (indirect links, incident grouping, recovery and cause labels) |
| LLM-anonymized | a person wrote it; a model only removes remaining names (logbook text, certification cause, downtime description) |

The page lists every part of the Record with who writes it in production and how the demo
produces it instead. In the demo no language model is used anywhere. The table is
`viewer/provenance.py`; a test checks that every entry type in the Record is covered. Two
rows are marked "assumed" because the proposal does not say who does the work: deciding
which element a free-text note is about, and treating expert follow-ups and root causes as
LLM summaries of slides and threads. Both need the project's confirmation.

Endpoints that may be called without `as_of`, and why: `provenance` (explanatory text, reads
nothing from the Record), `meta` (which Record is loaded and
its time range), `next_known` (returns a time, never content), and the two demo-only
endpoints that read `planted.json`. A test pins this list.

How it was checked: `tests/test_viewer.py` (as-of refusal on every reading endpoint, no
endpoint returns anything known later at sampled moments, the Record file is unchanged
after serving, path traversal is refused). Home, Timeline, Incident, Device, Precedents,
Planted answers and Entries were each loaded once in headless Chrome and looked at.
Not checked by anyone yet: interactive behaviour in a real browser (drag to zoom, hover
values, Play, the two switches, the Read API form), dark mode, and narrow screens.

## 11. The remake

**Why.** The first version did three jobs at once: reference material, browsing, and
replay. The time control sat on every page, including pages it meant nothing for, and
almost every page carried "as known at the time control" wording. Three switches and five
kinds of badge added noise. The project lead's reading order is: understand what the
Record is, then browse it, then replay.

**Structure now.**

| # | Page | Job |
|---|---|---|
| 1 | The detector (landing) | The detector model. States up front that the data is invented and that the Record was written directly by a generator. |
| 2 | How the Record is built | The designed feed beside what runs in the demo. Three sources (a voltage reading, a data-quality plot, a logbook note) followed into real entries. Links and incidents. A table of the design choices the demo fixes on the feed's behalf. |
| 3 | What is in the Record | Tables, Entries, Incidents, Timeline. The complete Record, no time control. |
| 4 | Scenarios in this demo | The planted situations and what the generator wrote for each. |
| 5 | Replay | Pick an incident; the page compares the two precedent rules for each. |
| - | For developers: read API | Linked from the foot of the navigation. |

**Replay is a mode.** Outside it, every read is made as of the end of the Record and no
time wording appears; an empty label reads "none recorded". A replay is started from the
Replay page, an incident, or a scenario. While it is on, every page shows the Record as it
stood then, an empty label reads "not known yet", and a slim banner on every page says so,
with "Back to the replay" and "Exit replay". A step is the next moment the Record learned
something about the incident being followed. Steps are times only.

**The replay page holds the controls** (changed after review; there is no control bar at
the top). In order: previous step, next step, Play and three jumps; then one chart with a
row of step marks (past filled, current highlighted, later ones hollow and clickable) above
the happened and known rows, with the future shaded; what the Record says now and what the
last step added; then collapsible sections for the detector at this moment, the timeline up
to this moment, "has this been seen before", the entries, and the answer key. The detector
and timeline sections call the same drawing functions as the full pages (`mapSvg`,
`mountTimeline`) with the same as-of data.

**"How the Record is built"** went through two rounds of review. It now opens with its
message in three numbered statements (the feed does not exist here; a generator stands in
for it; so structure is real, contents and the feed's choices are the generator's). Below
the two-path diagram, a box in the generator's colour holds two tables, "It writes the
entries the feed would have produced" and "It also writes what experts and software would
add on top". Their columns are: what, what the demo does, an example from this Record,
what the feed would do instead. Every row has a real example (an entry, a direct link, an
indirect link, an incident) and a link to the code that does it. Guidance from the review:
details may be shortened, the message may not; show examples and people will get it.

**Source links.** `/source/<file>#L<line>` shows one project source file with numbered
lines, read-only, limited to `.py` and `.sql` files under the four package folders. Line
numbers are looked up from a marker text at request time (`SOURCE_SPOTS` in
`viewer/api.py`), so links follow the code as it changes; a test checks each marker is
found. GitHub links were not used because the branch is not pushed.

**What a replay shows before the incident is opened.** Only the problem's symptoms: they
are what the crew is looking at. Evidence that an expert attaches later is not listed
until that attachment is recorded, because listing it early would point at the answer.
The replay knows which problem it follows (title, element, start); it says so on the page.

**Demo-only material has three homes** instead of a group and a switch: the generator is
drawn on "How the Record is built" as the stand-in for the feed; the planted situations
are the Scenarios page; the planted answers are an answer key revealed inside Replay.

**Removed:** the Home page, the "Demo only" navigation group, the "Production view" and
"Show planted answers" switches, the expert-filled, demo-only and LLM badges, the
"Who writes what" page and `viewer/provenance.py`, the slider, and "Pin for comparison".
That nothing in the demo is written by a language model is now one sentence on page 2.

**Checked:** `tests/test_viewer.py`, including that a replay returns nothing known later and
no early evidence. Every page, and three pages inside a replay, were loaded in headless
Chrome and confirmed to render; five were looked at as screenshots. Not checked by anyone:
clicking through a replay (step, Play, jumps, Exit), drag-to-zoom, and the answer-key box.

## 12. Changes on 17 November 2026

- **Readings come from the source archive**, not the Record (see DESIGN.md 7a). The timeline
  fetches them for the range in view and asks again on zoom; a "Reading status" row shows
  what the Record keeps instead.
- **Entries page**: a tree (class, then source, then type) with one colour per class wherever
  an entry is listed. Clicking a selected branch, or its arrow, collapses it.
- **Detector map**: each box's states sit on the left and its channels on the right, so they
  cannot overlap; states are abbreviated (link, LV, temp) and a state that is not normal is red.
- **Timeline of CMS or HCAL**: every readout box is drawn, one thin line each, coloured by
  subdetector. Up to four boxes are still coloured one by one. Incident labels too close
  together are left out until you zoom in.
- **Loading a different Record**: the "Record:" button at the top right lists the Record
  files under the starting folder (`out/`) with preset, seed, entries and size, and takes a
  typed path. The service switches with `POST /api/use`; the file must open as a Record.
  Files are still opened read-only.
- **How time series are treated** (on "How the Record is built"): the scheme in two lines of
  boxes (source, status rule, Record; and the adapter fetching on demand), one real series from
  the archive drawn with the few entries the Record keeps for it, and the four options with
  which are used. The generator's own row now says only what the generator does.
- **Interfaces of unbuilt parts** (under section 2): one card per unbuilt part, read from its
  skeleton code by `viewer/api.py` (`interfaces`), with what it takes and gives, its data
  records, contracts and method signatures linked to the source, the implementations still to
  write, and one real entry of the kind it would produce.
- **After the Record was slimmed down** (aggregator/README.md, "Changes on 17 November 2026"):
  timelines fetch per-run data quality from the data-quality archive and add "Quality status"
  and "Not certified yet" rows; beams and runs come from the calendar tables; entries, incidents
  and the replay page list the parts they concern, with roles and times; the map shows an open
  issue on every part it concerns; the Tables page shows the five new tables.
