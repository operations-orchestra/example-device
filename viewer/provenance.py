"""Who writes each part of the Record: in production (per the proposal) and in this demo.

"by" is one of:
  source       copied from an existing system by a read-only adapter
  code         computed by deterministic pipeline code
  llm_anon     written by a person; a local LLM only removes remaining personal identifiers
  llm_written  composed by a local LLM (a summary, a proposed link, a drafted label)
  llm_expert   proposed by a local LLM, then confirmed, corrected or rejected by an expert

The production column follows the proposal's pipeline description (anonymizers, summarizers,
sparsifiers, aggregator, expert review). Rows with "assumed": True are this prototype's
reading where the proposal does not say; they need the project's confirmation.

In the demo no language model is involved anywhere: everything is written by
example_device, from hand-written templates, formulas and fault scripts.
"""
from __future__ import annotations

BY_LABEL = {
    "source": "source system", "code": "pipeline code", "llm_anon": "person, LLM-anonymized",
    "llm_written": "local LLM", "llm_expert": "local LLM, expert confirms",
}

ITEMS: list[dict] = [
    # ---- text written by people -----------------------------------------------------------
    {"scope": "entry", "match": ["elog/shift_note"], "field": "payload.text", "thing": "Logbook note text",
     "by": "llm_anon", "stage": "anonymizer",
     "production": "Written by a shifter or expert in the electronic logbook. Pass 1 (code) replaces the author and known names with roles; pass 2 (local open-weight LLM) finds names, initials and e-mail addresses left in the text.",
     "demo": "One of two or three hand-written templates per situation, picked at random by the seed, with element and run names filled in (example_device/texts.py)."},
    {"scope": "entry", "match": ["elog/shift_note", "expert/followup", "expert/root_cause", "expert/closing_note", "summary/daily_run_summary"],
     "field": "payload.author_role", "thing": "Author role in place of a name",
     "by": "code", "stage": "anonymizer",
     "production": "Pass 1 of the anonymizer looks the author up and writes the operational role; no key linking name and role is kept.",
     "demo": "A fixed role string chosen by the fault script (HCAL DOC, DAQ shifter, ...). There were never any names."},
    {"scope": "entry", "match": ["elog/shift_note"], "field": "element", "thing": "Which element a free-text note is about",
     "by": "llm_written", "stage": "summarizer", "assumed": True,
     "production": "A logbook note is free text; deciding that it concerns HFP02 rather than HCAL in general means reading it. Assumed here to be done by the summarizer LLM with CMS terminology, falling back to the subsystem.",
     "demo": "Set by the fault script, which knows where it planted the fault."},
    {"scope": "entry", "match": ["expert/followup", "expert/root_cause", "expert/closing_note"], "field": "payload.text",
     "thing": "Expert follow-up, root cause and closing notes", "by": "llm_written", "stage": "summarizer", "assumed": True,
     "production": "The expert's explanation usually lives in meeting slides or long logbook threads, days to months later. The summarizer LLM compresses the anonymized material into a short statement that cites its evidence; experts audit summaries for faithfulness.",
     "demo": "A single hand-written template per fault mode, written at a fixed delay after the event (6 hours, 5, 6, 10 or 14 days)."},
    {"scope": "entry", "match": ["summary/daily_run_summary"], "field": "payload.text", "thing": "Daily run summary",
     "by": "llm_anon", "stage": "anonymizer",
     "production": "Written by run coordination each day; anonymized like logbook text.",
     "demo": "One sentence assembled from counted runs and downtime minutes."},
    # ---- existing structured human records ------------------------------------------------
    {"scope": "entry", "match": ["certification/cert_flag"], "field": "payload.status, bad_ls", "thing": "Certification flag and bad lumisection ranges",
     "by": "source", "stage": "adapter",
     "production": "Read from the certification database, where experts enter good or bad per subsystem and lumisection.",
     "demo": "Computed from the planted faults: bad from a supply trip to the run stop, and for runs with hot channels."},
    {"scope": "entry", "match": ["certification/cert_flag"], "field": "payload.cause", "thing": "Certification cause text",
     "by": "llm_anon", "stage": "anonymizer",
     "production": "The free-text cause an expert typed; anonymized.",
     "demo": "A fixed phrase per fault mode, e.g. 'LV trip of LV-HB-02'."},
    {"scope": "entry", "match": ["downtime/downtime"], "field": "payload.duration_s, lost_lumi_pb, category", "thing": "Downtime interval, lost luminosity, category",
     "by": "source", "stage": "adapter",
     "production": "Read from the downtime database.",
     "demo": "Duration is the planted interruption; lost luminosity is duration times a constant; category is fixed per fault mode."},
    {"scope": "entry", "match": ["downtime/downtime"], "field": "payload.details", "thing": "Downtime description",
     "by": "llm_anon", "stage": "anonymizer",
     "production": "The short description an operator typed; anonymized.",
     "demo": "A fixed phrase per fault mode."},
    # ---- machine state and quality --------------------------------------------------------
    {"scope": "entry", "match": ["dcs/lv_voltage", "dcs/temperature"], "field": "payload.mean, min, max, slope_per_h", "thing": "Sparsified reading summaries",
     "by": "code", "stage": "sparsifier",
     "production": "The sparsifier reduces bulk control-system time series to compact features per window and a pointer to the raw range. Numerical code, not a language model.",
     "demo": "Five simulated samples per window from a formula (nominal value, daily cycle, planted drift, Gaussian noise), then mean, min, max and slope."},
    {"scope": "entry", "match": ["dqm/occupancy_summary", "dqm/channel_flag"], "field": "payload", "thing": "Data-quality numbers per run",
     "by": "code", "stage": "sparsifier",
     "production": "Numbers extracted from data-quality histograms by the sparsifier. A written description of what a plot shows would be a separate, LLM-written entry; the demo has none.",
     "demo": "Set directly from the planted faults (dead fraction, hot channels, occupancy factor) plus 1% noise."},
    {"scope": "entry", "match": ["dcs/supply_state", "dcs/control_link", "lhc/beam_mode", "daq/fed_out_of_sync", "daq/data_integrity_errors",
                                 "runcontrol/configure", "runcontrol/run_start", "runcontrol/run_stop", "runcontrol/config_change"],
     "field": "payload", "thing": "State changes and events from online systems",
     "by": "source", "stage": "adapter",
     "production": "Read from the control system, run control and DAQ by read-only adapters.",
     "demo": "Written by the calendar and the fault scripts at the planned times."},
    {"scope": "entry", "match": ["*"], "field": "known_at", "thing": "When the Record learned of an entry",
     "by": "code", "stage": "aggregator",
     "production": "The time the source record was created or changed, as given by the source; for generated entries, the time the pipeline produced them.",
     "demo": "Event time plus a delay chosen by the script: zero for machine readings, minutes for logbook notes, 1 to 3 days for certification, days to weeks for causes."},
    # ---- links, incidents, elements -------------------------------------------------------
    {"scope": "link", "match": ["direct"], "field": "row", "thing": "Direct links",
     "by": "code", "stage": "aggregator",
     "production": "Built from shared identifiers, timestamps and configuration. They establish context, not cause.",
     "demo": "Written by the fault script (downtime to the run it stopped)."},
    {"scope": "link", "match": ["indirect"], "field": "row, rationale", "thing": "Indirect links and their stated reason",
     "by": "llm_expert", "stage": "summarizer, expert review",
     "production": "Automated tools propose which observation supported which conclusion; an expert confirms, corrects or rejects each one in the review interface.",
     "demo": "Written by the fault script as already confirmed, with one fixed sentence as the reason, at the moment the cause is recorded."},
    {"scope": "incident", "match": ["grouping"], "field": "incident, incident_entry", "thing": "Grouping entries into an incident, and its title",
     "by": "llm_expert", "stage": "evidence packet, expert review",
     "production": "For selected incidents, the team prepares an evidence packet with LLM help and reconstructs the history with the experts who handled it. For the rest, grouping is automatic and unreviewed.",
     "demo": "Every planted fault gets a complete incident from its script, with a fixed title."},
    {"scope": "incident", "match": ["recovery_action", "confirmed_cause"], "field": "recovery_action, confirmed_cause", "thing": "Recovery action and confirmed cause labels",
     "by": "llm_expert", "stage": "summarizer, expert review",
     "production": "Drafted from the expert's own words by the summarizer and confirmed by the expert. A recovery without a supported cause stays a recovery.",
     "demo": "Fixed strings per fault mode, written at fixed delays."},
    {"scope": "incident", "match": ["certification"], "field": "certification", "thing": "Certification label on an incident",
     "by": "code", "stage": "aggregator",
     "production": "Taken from the certification flags that overlap the incident.",
     "demo": "Copied from the certification entry of the run in which the fault happened."},
    {"scope": "element", "match": ["element", "element_relation"], "field": "rows", "thing": "Detector elements and their connections",
     "by": "code", "stage": "adapter",
     "production": "Derived from the detector geometry and cabling maps in the CMS software.",
     "demo": "Generated from the preset: so many subdetectors, boxes per subdetector, boxes per supply and per FED."},
]

NOT_IN_DEMO = [
    "Summaries of long logbook threads and slide decks (the demo's notes are already one sentence).",
    "Written descriptions of data-quality plots (the demo has numbers only, no images).",
    "The agent's answers: diagnosis proposals and the plain-English front end. Designed, not built.",
    "The anonymization audit: there were never names in the demo, so there is nothing to audit.",
]


def lookup() -> dict:
    return {"items": ITEMS, "by_label": BY_LABEL, "not_in_demo": NOT_IN_DEMO}
