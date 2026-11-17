"""The Record keeps what is notable; the routine stays in the calendar or in the sources."""
from adapters.dqm_archive import DqmArchive


def test_routine_run_control_is_in_the_calendar_not_in_entries(tiny, store, end):
    types = {t for _, _, t, _, _ in store.counts_by_type(end)}
    assert not types & {"run_start", "beam_mode", "occupancy_summary"}
    runs = store.runs(end)
    assert len(runs) == tiny["runs"] and len(store.fills(end)) == tiny["fills"]
    stops = store.entries(end, types=["run_stop"])
    assert stops and all(e.payload["reason"] not in ("new run", "beam dump") for e in stops)
    configures = store.entries(end, types=["configure"])
    assert all(e.payload["result"] == "failed" or e.payload["attempt"] != "initial" for e in configures)


def test_a_run_end_is_hidden_until_it_is_known(store):
    run = store.runs(store.latest_known_at())[3]
    mid = (run["t_start"] + run["t_end"]) // 2
    during = next(r for r in store.runs(mid) if r["run"] == run["run"])
    assert during["t_end"] is None and during["stop_reason"] is None and during["n_ls"] is None
    assert all(r["t_start"] <= mid for r in store.runs(mid))


def test_certification_good_is_inferred_bad_is_stored(tiny, store, end):
    bad = store.entries(end, types=["cert_flag"])
    assert bad and all(e.payload["status"] == "BAD" for e in bad)
    flag = bad[0]
    run, sub = flag.payload["run"], flag.element
    a, b = flag.payload["bad_ls"][0]
    done = next(c["completed_at"] for c in store.certification(end, [sub]) if c["run"] == run)
    assert store.lumisection_status(run, sub, a, as_of=done - 1) == "not certified yet"
    assert store.lumisection_status(run, sub, a, as_of=done) == "bad"
    if a > 1:
        assert store.lumisection_status(run, sub, a - 1, as_of=done) == "good"
    other = next(s for s in store.elements("subdetector") if s != sub)
    assert store.lumisection_status(run, other, 1, as_of=end) == "good"


def test_quality_numbers_stay_in_the_source_only_changes_are_entries(tiny, store, end):
    dqm = DqmArchive.find(tiny["db"])
    box = store.elements("readout_box")[0]
    t0, t1 = store.time_span()
    assert len(dqm.fetch(box, t0, t1, end)) == tiny["runs"]
    statuses = store.entries(end, types=["quality_status"])
    assert len(statuses) < tiny["runs"]
    # the planted change shows up as "occupancy high" until the experts re-reference
    change = next(c for c in tiny["planted_cases"] if c["mode"] == "planned_change")
    sub_boxes = store.children(change["true_element"])
    after = [e.payload["value"] for e in statuses if e.element in sub_boxes and e.t_start >= change["t_event"]]
    assert "occupancy high" in after
    reref = store.entries(end, elements=[change["true_element"]], types=["quality_reference"])[-1]
    assert reref.payload["value"] > 1
    if any(r["t_start"] > reref.t_start for r in store.runs(end)):   # runs after the re-reference read normal again
        assert after[-1] == "normal"


def test_every_entry_is_filed_under_exactly_one_part(store, end):
    for e in store.entries(end):
        filed = [r for r in store.parts(end, entry_id=e.id) if r.role == "filed"]
        assert [r.element for r in filed] == [e.element]


def test_part_references_arrive_with_their_own_times(tiny, store, end):
    first, second = [c for c in tiny["planted_cases"] if c["mode"] == "configure_failure"]
    iid = first["incident_id"]
    final = {(r.role, r.element): r for r in store.parts(end, incident_id=iid)}
    assert ("reported", "HCAL") in final
    assert ("suspected", first["true_element"]) in final and final[("suspected", first["true_element"])].status == "proposed"
    supply = next(n for rel, n in store.related(first["true_element"]) if rel == "powered_by")
    assert {("cause", first["true_element"]), ("cause", supply)} <= set(final)
    opened = store.incident(iid, end).known_at
    assert [(r.role, r.element) for r in store.parts(opened, incident_id=iid)] == [("reported", "HCAL")]
    # so the incident is found on the box only once the box has been named
    named = final[("suspected", first["true_element"])].known_at
    assert iid not in [i.id for i in store.incidents(named - 1, elements=[first["true_element"]])]
    assert iid in [i.id for i in store.incidents(named, elements=[first["true_element"]])]
    # an entry about the box's supply: the root cause names both, filed under the box
    cause = next(e for r, e in store.incident_entries(iid, end) if r == "cause")
    assert {(r.role, r.element) for r in store.parts(end, entry_id=cause.id)} >= {("filed", first["true_element"]), ("cause", supply)}
