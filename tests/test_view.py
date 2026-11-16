"""The viewing tools run and respect 'as of'."""
import pytest

from aggregator.view import info, plot_element, show_incident


def test_info_lists_incidents(store):
    text = info(store)
    assert "NOT CMS DATA" in text and "Incidents as of" in text and "#1" in text


def test_show_incident_respects_as_of(tiny, store):
    first, second = [c for c in tiny["planted_cases"] if c["mode"] == "configure_failure"]
    at_second = show_incident(store, first["incident_id"], as_of=second["ask_at"])
    assert "Power-cycle the control module" in at_second
    assert "confirmed cause (not known at this time)" in at_second
    assert "re-lock" not in at_second
    assert "re-lock" in show_incident(store, first["incident_id"])
    assert "is not known" in show_incident(store, first["incident_id"], as_of=first["ask_at"])


@pytest.mark.parametrize("element", ["HFP02", "HB", "LV-HB-02", "FED-HB-01", "HCAL"])
def test_plot_writes_a_png(store, tmp_path, element):
    pytest.importorskip("matplotlib")
    path = plot_element(store, element, tmp_path / f"{element}.png")
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
