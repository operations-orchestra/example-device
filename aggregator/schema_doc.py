"""What each table and column of the Record means, for people. Kept next to schema.sql.

Each column is (name, meaning, points_to), where points_to is "table.column" or "".
"""
from __future__ import annotations

TABLES: list[dict] = [
    {"name": "element", "purpose": "The parts of the device. Every entry is about one element.",
     "columns": [
         ("id", "row number", ""),
         ("name", "the element's name, e.g. HFP02", ""),
         ("kind", "experiment, detector, subdetector, readout_box, channel, lv_supply or fed", ""),
         ("parent_id", "the element this one is part of", "element.id")]},
    {"name": "element_relation", "purpose": "Service connections that cut across the hierarchy: which supply powers a box, which FED reads it out.",
     "columns": [
         ("element_id", "the element that depends on another", "element.id"),
         ("related_id", "the element it depends on", "element.id"),
         ("relation", "powered_by or read_out_by", "")]},
    {"name": "entry", "purpose": "One row per thing recorded: a reading summary, an event, a logbook note, a flag. All share this one envelope.",
     "columns": [
         ("id", "row number", ""),
         ("source", "the system it came from: dcs, dqm, elog, runcontrol, ...", ""),
         ("record_class", "MS machine state, QA quality assurance, HI human interpretation", ""),
         ("kind", "state, point, report or feature: what the times mean", ""),
         ("type", "what it is within its source, e.g. lv_voltage", ""),
         ("element_id", "the element it is about", "element.id"),
         ("t_start", "when it happened or began to hold", ""),
         ("t_end", "when it ended, if it covers an interval", ""),
         ("known_at", "when the Record learned of it; reads never return rows later than their as-of time", ""),
         ("payload", "the content, in whatever shape the source gives", ""),
         ("raw_ref", "pointer to the underlying source data, never a copy", ""),
         ("producer", "the software or model that wrote this row", ""),
         ("producer_version", "its version", ""),
         ("review_status", "unreviewed, proposed, confirmed, corrected or rejected", ""),
         ("supersedes", "the earlier entry this one corrects", "entry.id")]},
    {"name": "link", "purpose": "A connection between two entries. Direct: same place and time. Indirect: an expert's reasoning, with the reason stated.",
     "columns": [
         ("id", "row number", ""),
         ("src_entry_id", "the entry the link starts from", "entry.id"),
         ("dst_entry_id", "the entry it points to", "entry.id"),
         ("link_type", "direct or indirect", ""),
         ("relation", "what the link says, e.g. supports, stopped_run", ""),
         ("status", "proposed, confirmed, corrected or rejected", ""),
         ("rationale", "the reason given", ""),
         ("known_at", "when the Record learned of the link", ""),
         ("producer", "who or what made the link", ""),
         ("producer_version", "its version", "")]},
    {"name": "incident", "purpose": "A problem that people grouped entries into. An open issue is an incident that is not yet closed. The three labels are kept apart, each with its own known-at time.",
     "columns": [
         ("id", "row number", ""),
         ("title", "a short description of the symptom", ""),
         ("element_id", "the element the problem was reported on", "element.id"),
         ("t_start", "when the problem began", ""),
         ("t_end", "when running was restored", ""),
         ("known_at", "when the incident was opened in the Record", ""),
         ("recovery_action", "what restored running", ""),
         ("recovery_known_at", "when that was recorded", ""),
         ("confirmed_cause", "why it happened; may never be filled", ""),
         ("cause_known_at", "when the cause was recorded", ""),
         ("certification", "whether the recorded data were usable", ""),
         ("certification_known_at", "when that was recorded", ""),
         ("final_status", "closed, or unresolved if no cause was found", ""),
         ("closed_known_at", "when it was closed", "")]},
    {"name": "incident_entry", "purpose": "Which entries belong to which incident, and in what role.",
     "columns": [
         ("incident_id", "the incident", "incident.id"),
         ("entry_id", "the entry", "entry.id"),
         ("role", "symptom, action, downtime, evidence, cause, certification or closing_note", ""),
         ("known_at", "when the entry was attached to the incident", "")]},
    {"name": "query_log", "purpose": "Every read made by the agent's tools, so each claim can be re-run. Empty until the tools exist.",
     "columns": [
         ("id", "row number", ""), ("session", "which agent session", ""), ("tool", "which tool", ""),
         ("args", "its arguments", ""), ("as_of", "the moment it asked about", ""),
         ("result_ids", "the entries it got back", "")]},
    {"name": "meta", "purpose": "What built this Record: banner, preset, seed, schema version.",
     "columns": [("key", "name of the setting", ""), ("value", "its value", "")]},
]
