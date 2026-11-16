import json

import pytest

from aggregator import RecordStore
from example_device import generate, preset


@pytest.fixture(scope="session")
def tiny(tmp_path_factory):
    """The tiny synthetic Record, built once per test session."""
    out = tmp_path_factory.mktemp("tiny")
    result = generate(preset("tiny"), out)
    result["planted_cases"] = json.loads((out / "planted.json").read_text())["planted"]
    return result


@pytest.fixture()
def store(tiny):
    s = RecordStore.open(tiny["db"])
    yield s
    s.close()


@pytest.fixture()
def end(store):
    """An 'as of' time after everything in the Record is known."""
    return store.latest_known_at()
