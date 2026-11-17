# Martin: Orchestra prototype on synthetic data, and a GUI to understand it

Martin set the goal of a two-part Operations Orchestra prototype on synthetic data, then redirected the work from building the agent to a GUI that lets people understand what was built. He rejected the first GUI as doing too much at once and set its reading order, its message, and several design constraints for the Record.

## What Martin did

| Approve | Claim |
| :-- | --- |
| ☑ H1<br>🎯 Direction | Build a full prototype of the CMS Operations Orchestra on synthetic data, in two clear parts: skeleton code that feeds the Record, and orchestra code given a synthetic Record.<br>**Why key:** the premise; every later decision builds on it. |
| ☑ H14<br>🛠️ Correction | The GUI is confusing: it does too many things at once, with replay wording on every page next to static information.<br>**Why key:** reversed the GUI design; the remake and five later claims follow.<br>corrects: the first GUI, with a time control, switches and badges on every page<br>led_to: #H15, #H16, #H17, #H18, #H23 |
| ☑ H10<br>🛠️ Correction | The next step is not a verify command. People must first understand what was built, through a Record viewer and a GUI for each component.<br>**Why key:** moved the work from the agent to the GUI.<br>corrects: AI design doc proposing an `orchestra verify` report as the human-facing tool<br>refines: #H9 |

<details><summary>Also (22 more)</summary>

| Approve | Claim |
| :-- | --- |
| ☑ H20<br>🎯 Direction | That the Record is written directly by a generator, with no feed software running, must be among the first things a reader learns. |
| ☑ H7<br>🎯 Direction | Make it a rule: real detector names are fine in synthetic data, but never any real events. |
| ☑ H24<br>🛠️ Correction | Tying a root cause to a single element is unrealistic. Allowing several is a to-do, noted on the Tables page; expect large GUI changes.<br>corrects: AI schema giving every entry and incident exactly one element |
| ☑ H19<br>🎯 Direction | How readings are sparsified (four numbers per 15-minute window) is a key design choice. Expose it on the build page; do not build a sparsifier now. |
| ☑ H21<br>💡 Origination | The Record should keep the plots relevant to an incident, a tiny fraction of all plots: ideally a pointer from the logbook entry, in practice mostly logbook image attachments. |
| ☑ H18<br>🎯 Direction | Understanding the Record starts with the detector model, so the GUI opens on it.<br>depends_on: #H14 |
| ☑ H15<br>🔀 Choice | The GUI serves three jobs in this order: understand what the Record is, browse it, then replay an incident.<br>depends_on: #H14 |
| ☑ H25<br>🛠️ Correction | The build page must keep its message. Show the generator's role with real examples, including direct and indirect links, and link to the source code.<br>corrects: AI version cut down to a diagram and terse tables with no stated message |
| ☑ H23<br>🛠️ Correction | Replay keeps its own page but no top control panel: mark the incident's steps on the chart, add collapsible detector and timeline views, and a banner that all pages show as-of data.<br>corrects: AI replay control bar across the top of every page |
| ☑ H11<br>💡 Origination | The GUI must show clearly which features exist only because the synthetic demo holds all the answers, and which are production-like.<br>refined by: #H17 |
| ☑ H17<br>🎯 Direction | Re-assign the role of the demo-only features and the planted answers in the GUI.<br>refines: #H11 |
| ☑ H16<br>🎯 Direction | Replace "who writes what" with a section illustrating how the Record is built. Marking LLM-written content is moot for now, since almost nothing is.<br>supersedes: #H13 |
| ☑ H3<br>🎯 Direction | The orchestra part also includes the diagnosis agent, not only the Record schema and query tools.<br>supersedes: #H2 |
| ☑ H5<br>🛠️ Correction | The work goes on a branch of the shared `operations-orchestra/example-device` repository.<br>corrects: AI proposal of a new local `orchestra-prototype/` directory |
| ☑ H9<br>🎯 Direction | After the generator checkpoint, the next steps are a GUI and tools for people, guided by a design document that also serves hand-off.<br>refined by: #H10 |
| ☑ H4<br>🎯 Direction | Generated data stays under 100 MB, with the size as a generator parameter, and the first pass smaller still. |
| ☑ H6<br>📚 Knowledge | The organization already has six repositories (example-device, orchestrator, aggregator, anonymizer, sparsifier, utils); keep everything in one repository for now. |
| ☑ H22<br>🎯 Direction | Entries need several logical views, ordered from low-level to high-level understanding. |
| ☑ H12<br>🎯 Direction | Illustrate the tables of the Record, and make the detector map visible. |
| ☑ H8<br>🎯 Direction | Include tools for people to visualize the numbers, since the first pass stores no plot images. |
| ☑ H13<br>🎯 Direction | Highlight in the GUI what a local LLM would generate in production, and how the demo generates it now.<br>superseded by: #H16 |
| ☑ H2<br>🔀 Choice | Of the orchestra components offered, only the Record schema and query tools must run.<br>superseded by: #H3 |

</details>

## AI decisions

☑ All AI claims and minor details below are recorded accurately

| Endorse | AI decision |
| :-- | --- |
| ☐ A1 | Every entry has two times, when it happened and when the Record learned of it; every read names a moment and returns nothing learned later. |
| ☐ A6 | The generator writes the Record directly through a real write API; adapters, anonymizer, summarizer and sparsifier are interfaces only and are not simulated. |
| ☐ A15 | GUI remake: five ordered pages (detector, how the Record is built, what is in it, scenarios, replay); the complete Record by default; replay is a mode entered on purpose.<br>depends_on: #H14 |
| ☐ A3 | Synthetic data is an HCAL-shaped, seeded generator with planted fault situations; the hidden answers live in a separate file, never in the Record. |
| ☐ A2 | Purpose: a runnable demo of the proposal's Fig. 2 story (a second crew recalls the first crew's incident) that can seed the public repository. |
| ☐ A4 | The Record is one SQLite file for now, with all SQL confined to one module so it can move to PostgreSQL. |
| ☐ A16 | Demo-only material gets three homes: the generator on the build page, a Scenarios page, and an answer key revealed inside Replay.<br>depends_on: #H17 |
| ☐ A5 | Agent design, not yet built: typed read-only tools with no raw SQL, a validated structured proposal, and two brains (a fixed script and an OpenAI-compatible endpoint). |
| ☐ A14 | Two candidate precedent rules, both computed only from the Record: same element, or same kind of symptom on any element. Shown side by side, not decided.<br>Never discussed |
| ☐ A17 | Before an incident is opened, a replay lists only its symptoms; evidence an expert links later is withheld so it cannot point at the answer.<br>Never discussed |
| ☐ A9 | Planted situations: configure failure after a stop, recurring FED communication loss, voltage sag then trip, hot channels, a planned change that is not a fault, an unexplained recovery; knowledge arrives at fixed delays. |
| ☐ A12 | The GUI is a local, read-only web service on the Python standard library plus one static page, calling the Record's own read methods; charts are hand-written, with no third-party library.<br>Never discussed |
| ☐ A7 | Top-level folders are named after the organization's repositories, and a test enforces which folder may import which.<br>depends_on: #H6 |
| ☐ A8 | Schema additions beyond the agreed six tables: a table of service connections between elements, a table of settings, and a fourth entry kind for window summaries.<br>Never discussed |
| ☐ A10 | The calendar starts in 2040 and run numbers at 900001; data-quality records are numbers only; logbook text comes from hand-written templates. |
| ☐ A11 | Verification in five test layers, a stop for review after the generator, and the real-model run deferred (tested against a fake server only). |
| ☐ A18 | "Where in the code" links open a local read-only view of the source file at the right line, because the branch is not pushed.<br>Never discussed |
| ☐ A13 | First GUI: three marks (production-like, expert-filled, demo only) and a "Production view" switch; later removed in the remake.<br>depends_on: #H11 |
| ☐ A19 | All commits stay local on the branch; nothing is pushed or opened as a pull request until Martin says so. |

<details><summary>Minor details (9)</summary>

- M1 Asked for design questions to be phrased plainly, with more context and one decision each.
- M2 Agreed structured agent output is better because open-weight models have less reasoning power.
- M3 Accepted template-generated logbook text, to be revisited.
- M4 Dropped the "Production view" switch.
- M5 Asked for fewer words on the "How the Record is built" page, before H25 restored its message.
- M6 AI: kept the design and GUI plan documents in the repository rather than a shared page (never discussed).
- M7 AI: planned skeleton files for the summarizer and adapters, which have no repository yet; none of the feed skeletons is built.
- M8 AI: left out the Build-a-Record button (never discussed).
- M9 AI: used a pixi environment because the system Python is broken (never discussed).

</details>

## Open questions
- Does the synthetic data look plausible to a detector expert? Asked twice, not yet answered.
- What counts as a precedent: the same element, or the same symptom anywhere? Not yet answered.
- Which entry views to build (H22)? The AI suggested by type, by run and by incident first; no choice yet.
- H1's two parts are incomplete: the query tools, the agent and the feed skeletons are not built.
- This record has 25 boxed human claims. Consider splitting it at "The next steps are GUI and tools for human…" (prototype design before, GUI after).
- The member handle `martin` and `product_type: endorsed` are assumed: there is no `.claudoperation/policy.yml`.
- The validator could not be run (node is not installed); the record was checked by hand.

<details><summary>Links and evidence</summary>

- H1, H3, A2, A5, A6 → docs/DESIGN.md §1, §6
- H4, H7, A3, A9, A10 → example_device/, README.md "Rule for this repository", tests/test_generator.py
- H5, H6, A7, A19 → branch `prototype/synthetic-record`, tests/test_boundaries.py
- A1, A4, A8 → aggregator/schema.sql, aggregator/store.py, tests/test_as_of.py
- H9, H10, H11, H14 to H18, H23, A12, A13, A15, A16 → docs/GUI_PLAN.md §4, §10, §11; viewer/
- H19, H21, H24 → docs/DESIGN.md §7a, §7b; note on the Tables page
- H20, H25, A18 → "How the Record is built" page (viewer/static/app.js, viewer/api.py `SOURCE_SPOTS`)
- A14, A17 → viewer/precedents.py, tests/test_viewer.py
</details>

<details><summary>Record details</summary>

| Field | Value |
| --- | --- |
| claudoperation | 0.3 |
| session | 2026-11-16-orchestra-prototype-gui |
| member | martin |
| product | example-device (branch prototype/synthetic-record) |
| product_type | endorsed |
| span | 2026-11-16 |
| approval | bulk |
</details>
