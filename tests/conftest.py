import tempfile

import pytest


@pytest.fixture(autouse=True)
def isolated_session_database(monkeypatch):
    """Never let protocol tests write synthetic sessions into the real desktop library."""
    with tempfile.TemporaryDirectory(prefix="sfull-test-data-") as temp:
        monkeypatch.setenv("S_FULL_DATA_DIR", temp)
        yield
