# Martin: Slimming the Record, several parts per record, and the agent

Martin reshaped the Operations Record, the prototype's time-stamped log of what was known about the detector and when: it now keeps a reading only when its status changes, and any entry or incident can name several detector parts. He also turned the diagnosis agent's judgement that a new problem matches a past incident into a confidence learned from expert reviews, not a yes/no rule.

## What Martin did

| Approve | Claim |
| :-- | --- |
| ☑ H12<br>🛠️ Correction | When a new problem comes in, the agent looks for a past incident like it (a precedent). Whether the match means "the same problem, seen before" is now a confidence learned from experts confirming or rejecting earlier matches, not a yes/no rule.<br>**Example:** hot channels on HF, when the only earlier hot channels were on HO: the agent answers "uncertain" rather than "known" or "new" (incident 8 in the demo).<br>**Why key:** reversed the agent's decision rule; its scoring, reviews and analytics follow.<br>corrects: the AI's proposal to call a problem known only when it shares both a part and a symptom with the precedent<br>led_to: #A9, #A10, #A11 |
| ☑ H1<br>🛠️ Correction | The Record stored low-voltage and temperature readings and per-run data-quality numbers as summary entries, 90% of all entries. Martin judged this would not scale to a real detector and asked for a better way.<br>**Now:** the Record keeps a reading only when its status changes (normal, drifting, low, high, off), with a pointer into the source; the full series is fetched from the source when needed.<br>**Example:** a low-voltage supply that sags for hours and then trips becomes a few status entries (drifting, then off) instead of one entry per 15 minutes. With the related changes below, the 30-day demo Record went from 5,084 entries to 763.<br>**Why key:** reshaped the Record; readings and data quality moved to their sources.<br>corrects: the AI's design storing four numbers per 15-minute window of readings as entries<br>led_to: #H2, #A1, #A2 |
| ☑ H11<br>🎯 Direction | An entry or incident often concerns several detector parts: the one it was filed on, others it mentions, the one later found to be the cause. Martin asked for one uniform way to record this for every such field, not a fix for the root cause alone.<br>**Before:** each entry and incident named a single part.<br>**Now:** part references, each part listed with its role (filed, mentioned, affected, suspected, cause) and when that became known.<br>**Example:** an incident reported on a readout box whose cause is later traced to its low-voltage supply names both; the cause is added with the time it was found, so a replay of an earlier moment does not see it.<br>**Why key:** became part references with roles and times, used everywhere.<br>refines: 2026-11-16-orchestra-prototype-gui#H24<br>led_to: #A5, #A6 |

<details><summary>Also (11 more)</summary>

| Approve | Claim |
| :-- | --- |
| ☐ H10<br>🛠️ Correction | Certification defaults to "not certified yet"; store only bad lumisection ranges and infer good.<br>corrects: AI recommendation to leave certification flags as they were<br>led_to: #A4 |
| ☐ H4<br>💡 Origination | The detector view needs a dedicated module with realistic CMS geometry; cmscoord is that attempt. |
| ☐ H5<br>🎯 Direction | cmscoord becomes part of the Orchestra as a dependency; for now keep the repository's toy detector and only write the integration plan.<br>refines: #H4<br>led_to: #A16 |
| ☐ H16<br>🛠️ Correction | LLM profiles live in the repository (the real file ignored by git, an example tracked); only the keys live in ~/.config; no max-token or timeout settings.<br>corrects: AI placing the profiles file in ~/.config/orchestra |
| ☐ H9<br>🎯 Direction | Next, reduce the entry types that dominate (per-run data quality, run control), then fix references to several parts.<br>led_to: #A2, #A3 |
| ☐ H2<br>🎯 Direction | In the demo, keep the full time series as if retrieved from the source, beside the slimmed entries.<br>refines: #H1 |
| ☐ H3<br>🛠️ Correction | No entry-type catalogue for now: the problem it fixes was not clear.<br>corrects: AI proposal of a catalogue of entry types |
| ☐ H7<br>🛠️ Correction | "How the Record is built" is written by hand and can drift from the Record; mark it as not part of the production browser.<br>corrects: AI presenting it as an ordinary page of the browser |
| ☐ H13<br>💡 Origination | An agent page: first what the agent does, then how it did across incidents. |
| ☐ H15<br>📚 Knowledge | LLM endpoints as named profiles (backend, base URL, model, the variable holding the key), as in another project. |
| ☐ H14<br>🎯 Direction | Compare an LLM brain with the scripted brain next, and always show which brain answered. |

</details>

## AI decisions

☐ All AI claims and minor details below are recorded accurately

| Endorse | AI decision |
| :-- | --- |
| ☐ A9 | Confidence per recalled incident: a starting value per kind of match learned from precedent reviews with expert priors (3:1, 1:2, 1:3), odds ×3 per piece of evidence found again; known from 0.7, new below 0.3.<br>depends_on: #H12 |
| ☐ A1 | The Record keeps a reading only when its status changes (normal, drifting, low, high, off) under a fixed rule, pointing into a simulated control-system archive that an adapter reads on demand.<br>depends_on: #H1 |
| ☐ A5 | Part references: every part an entry or incident concerns, with a role (filed, reported, mentioned, affected, suspected, cause) and its own known-at time; the filed or reported part is also kept on the row.<br>depends_on: #H11 |
| ☐ A2 | Per-run data quality stays in a simulated data-quality archive; the Record keeps quality status changes against a per-subdetector reference that experts update. |
| ☐ A3 | Runs, fills and beam modes moved to calendar tables; only fault stops and non-routine configure attempts stay entries. The small Record went from 5,084 entries to 763. |
| ☐ A4 | A table records when each run was certified per subdetector, so "good" differs from "not certified yet".<br>depends_on: #H10 |
| ☐ A10 | Precedent reviews are a table; in the demo the generator invents them (same planted fault: confirmed; a different fault sharing a part: rejected). |
| ☐ A8 | Six read-only agent tools, including fetching a series from the source archive; calls are logged in memory per session, not in the Record. |
| ☐ A7 | A replay step counts a symptom at its own time and any other entry when it is linked, so steps never hint at evidence early.<br>Never discussed |
| ☐ A11 | The agent page judges each answer by the precedent reviews written after the incident closed, not by the answer key.<br>Never discussed |
| ☐ A6 | The "same element" precedent rule became "shares a part", using the parts known at the time.<br>Never discussed |
| ☐ A16 | The cmscoord integration plan in five stages: interface with the toy detector, several parts per record, cmscoord's fixture, maps over time, a real map kept local.<br>depends_on: #H5 |
| ☐ A13 | Keys are read from the environment, then ~/.config/orchestra/keys.env (refused unless only its owner can read it), or the Keychain; never shown or sent except to their endpoint. |
| ☐ A12 | Unbuilt parts are written as skeleton code with a role and an example each, and the interfaces page is read from that code.<br>Never discussed |
| ☐ A15 | The single-file demo embeds precomputed answers for the finished Record and every replay step (12.6 MB for the small Record).<br>Never discussed |
| ☐ A14 | Folded two unpushed commits into one so the real endpoint addresses never enter the branch history.<br>Never discussed |
| ☐ A17 | Entries are organised as a class, source, type tree, with one colour per class wherever an entry is listed. |

<details><summary>Minor details (16)</summary>

- M1 Asked for a README of the aggregator's own: what was done, the choices and why, next steps.
- M2 Asked whether the 19 entry types scale, and for the entries to be grouped (tree, class colours).
- M3 Asked for "click again to collapse" in the entries tree.
- M4 Reported overlapping text on the detector map; asked for a CMS-wide timeline.
- M5 Asked for a way to load a different Record file in the GUI.
- M6 Gave the cmscoord repository link and will introduce cmscoord to the other PIs.
- M7 Asked for a page illustrating the interfaces of the unbuilt parts.
- M8 Asked for fewer details in the time-series section: the rule, and "fetched" against "stored".
- M9 Asked for the text of what happened on the replay's "Happened" line, and for steps to be explained.
- M10 Asked for short timestamps on screen with the full time on hover.
- M11 Moved "About this Record" to the top of the detector page; removed the shading on readings.
- M12 Asked for the agent panel to separate its output clearly, and for sortable incident tables.
- M13 Agreed to an example profiles file in the repository; recreated the real one after deleting it by accident.
- M14 AI: dropped the shading's meaning (min–max per drawn point) rather than relabelling it (never discussed).
- M15 AI: a replay link to a moment the static demo does not hold snaps to the nearest earlier held moment (never discussed).
- M16 AI: the policy file's layout is this repository's own reading of the claudoperation design; the plugin publishes no schema (never discussed).

</details>

## Open questions
- This record has 14 boxed human claims. Consider splitting it at "ok what should I build next?" (the Record before, the agent after).
- The session changed both code and documents; by the policy it is functional because most changes were code.
- The validator could not be run (node is not installed); the record was checked by hand.

<details><summary>Links and evidence</summary>

- H1, H2, A1 → example_device/readings.py, adapters/control_archive.py, docs/DESIGN.md 7a
- A2, A3, A4, H9, H10 → aggregator/README.md "Changes on 17 November 2026", example_device/quality.py
- H11, A5, A6 → aggregator/schema.sql (part_ref), tests/test_record_shape.py
- H12, A8–A11 → orchestrator/, viewer/api.py (agent, agent_report), tests/test_agent.py
- H4, H5, A16 → docs/DETECTOR_PLAN.md
- H15, H16, A13, A14 → orchestrator/llm_config.py, config/llm.example.yaml, .gitignore
- A15 → viewer/static_export.py, .claudoperation/policy.yml
- author: summary rewritten to give readers outside the session the context; the 3 key claims now say what they mean, what was there before and an example.
- author: removed H17 (the wrap-up for the PI meeting); the README's "Next design tasks" section it produced was dropped afterwards.
</details>

<details><summary>Record details</summary>

| Field | Value |
| --- | --- |
| claudoperation | 0.3 |
| session | 2026-11-17-record-and-agent |
| member | martin |
| product | example-device (branch prototype/synthetic-record) |
| product_type | functional |
| span | 2026-11-17 → 2026-11-18 |
| approval | individual |
</details>
