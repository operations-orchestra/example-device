"""Logbook wording. Hand-written templates, several per situation, no language model.

Authors are operational roles, never people. The text is more regular than a real
logbook, which makes recall easier here than it will be on real records.
"""
from __future__ import annotations

SHIFT_LEADER = "Shift leader"
DAQ_SHIFTER = "DAQ shifter"
DCS_SHIFTER = "DCS shifter"
DQM_SHIFTER = "DQM shifter"
HCAL_DOC = "HCAL DOC"
HCAL_EXPERT = "HCAL expert"
RUN_COORDINATOR = "Run coordinator"

T: dict[str, list[str]] = {
    "shift_start": [
        "Shift started. HCAL status: OK.",
        "New shift crew in. No open HCAL issues handed over.",
        "Shift handover done. HCAL included and healthy.",
    ],
    "run_start": [
        "Run {run} started, all HCAL partitions in.",
        "Started run {run} in fill {fill}. HCAL in.",
        "Run {run} ongoing, HCAL OK.",
    ],
    "known_dead": [
        "Reminder: {channel} is a known dead channel and stays masked. No action needed.",
    ],
    # --- FED communication loss -----------------------------------------------------------
    "fed_symptom": [
        "Run stopped: {fed} went out of sync, HCAL is not sending data.",
        "{fed} out of sync, communication to {sub} readout lost. Stopping the run.",
        "DAQ stuck, {fed} reports OUT_OF_SYNC. Run stopped, calling HCAL DOC.",
    ],
    "fed_recovery": [
        "Reconfigured HCAL, {fed} back in sync. Running again.",
        "HCAL reconfigured after the {fed} problem. New run started.",
        "{fed} recovered by a full HCAL reconfigure. Data taking resumed.",
    ],
    "fed_downtime": ["communication problem with {fed}"],
    "fed_cause": [
        "Link firmware on the {fed} uplink loses lock after a single-event upset; a reconfigure "
        "restores it. Same firmware on all HCAL FEDs. No permanent fix yet, firmware update requested.",
    ],
    # --- configure failure ----------------------------------------------------------------
    "cfg_symptom": [
        "HCAL fails to configure for fill {fill}. Three automatic recoveries failed. Run control "
        "shows HCAL in error with no further detail. Calling HCAL DOC.",
        "Cannot configure: HCAL goes to error. Automatic recovery tried three times without "
        "success. Nothing visible on our side about what blocks it. HCAL DOC called.",
    ],
    "cfg_recovery_terse": [
        "HCAL DOC intervened, HCAL configured. Run started.",
        "HCAL back after expert intervention. Data taking started.",
    ],
    "cfg_downtime": ["HCAL fails to configure"],
    "cfg_followup": [
        "Follow-up on the configure failure in fill {fill}: the control module of {box} had lost "
        "its control link after the low-voltage power cycle. Power-cycled the control module of "
        "{box} and ran a local configure; global configure then succeeded.",
    ],
    "cfg_cause": [
        "The control module of {box} does not re-lock its clock after a low-voltage off/on. It "
        "must be power-cycled after every access or stop in which {supply} is switched off.",
    ],
    # --- low-voltage drift and trip -------------------------------------------------------
    "lv_symptom": [
        "LV supply {supply} tripped. {boxes} off. Run stopped, calling HCAL DOC.",
        "{supply} is in tripped state, lost {boxes}. Stopped the run.",
        "Trip of {supply}; {boxes} without low voltage. HCAL DOC informed.",
    ],
    "lv_recovery": [
        "Power-cycled {supply}, {boxes} back. Running again.",
        "{supply} switched back on by the DOC, boxes recovered. New run started.",
    ],
    "lv_downtime": ["{supply} tripped"],
    "lv_cause": [
        "Ageing regulator module in {supply}: the output voltage sagged for about {hours} hours "
        "before the trip. Module replaced.",
    ],
    # --- hot channels ---------------------------------------------------------------------
    "hot_symptom": [
        "Hot spot in the {sub} occupancy map, {box} region. Noted for the HCAL DOC.",
        "{sub} occupancy shows a few hot towers around {box}. Not stopping the run.",
        "DQM: hot channels visible in {sub} near {box}. Flagged to HCAL.",
    ],
    "hot_followup": [
        "Masked {channels} of {box} from the next fill.",
        "Hot channels {channels} in {box} are masked as of the next fill.",
    ],
    "hot_cause": [
        "Noisy photosensor bias on {channels}. The channels stay masked until the next access.",
    ],
    "hot_no_cause": [
        "No cause found for the hot channels {channels} in {box}; they stay masked. Closing as unresolved.",
    ],
    # --- planned change (not a fault) -----------------------------------------------------
    "change_announce": [
        "Planned: the zero-suppression threshold on {sub} will be lowered before fill {fill}. "
        "Expect higher occupancy in {sub}.",
        "For information: {sub} zero-suppression threshold goes down before fill {fill}, as "
        "agreed with HCAL. Occupancy in {sub} will rise.",
    ],
    # --- loss of synchronisation on a box -------------------------------------------------
    "sync_symptom": [
        "Data integrity errors from {box}. Run stopped.",
        "{box} sends corrupted data, integrity error counter rising fast. Stopping the run.",
    ],
    "sync_recovery": [
        "Reset the front-end of {box}. Errors gone, running again.",
        "Front-end reset on {box} cleared the integrity errors. New run started.",
    ],
    "sync_downtime": ["data integrity errors from {box}"],
    "sync_no_cause": [
        "No cause found for the integrity errors on {box}. Closing as unresolved.",
    ],
}

QUESTIONS = {
    "fed_comm_loss": "{element} is out of sync and the run has stopped. Has this been seen before, and what should we do?",
    "configure_failure": "HCAL fails to configure and three automatic recoveries have failed. What should we do?",
    "lv_drift_trip": "LV supply {element} has tripped and the run has stopped. Has this been seen before, and what should we do?",
    "hot_channels": "There is a hot spot in the occupancy map near {element}. Is this known?",
    "planned_change": "Occupancy in {element} is higher than in the last fill. Is something wrong?",
    "box_sync_loss": "{element} is sending data integrity errors and the run has stopped. What should we do?",
}

# What each fault script does, in words. Written into planted.json for people to read.
MODES = {
    "configure_failure": {
        "title": "Configure failure after a low-voltage power cycle",
        "story": "A readout box's control module loses its control link when its low voltage is "
                 "switched back on. Hours later HCAL fails to configure and three automatic "
                 "recoveries fail. The crew sees only 'HCAL in error'. An expert power-cycles the "
                 "module. The logbook says only that the expert intervened; what was done is "
                 "written 6 hours later, and the cause 6 days later. It happens on the first two "
                 "fills after the technical stop.",
    },
    "fed_comm_loss": {
        "title": "FED communication loss",
        "story": "A FED goes out of sync and the run stops. Reconfiguring HCAL fixes it, and the "
                 "logbook says so at once. The cause is understood only 4 days after the problem "
                 "has happened a second time; if it never recurs it is closed as unresolved.",
    },
    "lv_drift_trip": {
        "title": "Low-voltage sag, then a trip",
        "story": "A supply's output voltage sags by 0.35 V over 6 hours and then trips. The boxes "
                 "it powers go dead and the run stops. Power-cycling restores running. The data "
                 "from the trip to the run stop are certified bad. Two weeks later an expert names "
                 "the cause and links the falling voltage readings to it.",
    },
    "hot_channels": {
        "title": "Hot channels",
        "story": "Two or three channels of one box become noisy until the end of the fill. There "
                 "is no downtime. The DQM shifter notes a hot spot, the data are certified bad, and "
                 "the channels are masked for the next fill. A cause is given 5 days later in 70% of "
                 "cases; otherwise it is closed as unresolved.",
    },
    "box_sync_loss": {
        "title": "Data integrity errors, never explained",
        "story": "A readout box sends corrupted data and the run stops. A front-end reset fixes it. "
                 "No cause is ever found; it is closed as unresolved 10 days later.",
    },
    "planned_change": {
        "title": "Planned threshold change (not a fault)",
        "story": "The run coordinator announces a lower zero-suppression threshold for one "
                 "subdetector three hours ahead. From the next fill the occupancy is 12 to 20% "
                 "higher. Nothing is wrong, and no incident exists. It is planted to check that a "
                 "change in the data is not mistaken for a fault.",
    },
}
