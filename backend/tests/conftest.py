import os

# Tests use their own graph; set before claimbridge.config is imported.
os.environ["GRAPH"] = "claimbridge_test"
os.environ.setdefault("LEASE_TTL_S", "4")
os.environ.setdefault("HEARTBEAT_S", "1")
os.environ.setdefault("POLL_S", "0.3")
# Tests never call a real LLM: the fake provider is deterministic and offline.
os.environ["LLM_PLATFORM"] = "fake"
os.environ["LLM_MODE"] = "live"

import pytest  # noqa: E402

from claimbridge import db  # noqa: E402


@pytest.fixture(scope="module")
def seeded():
    from claimbridge.seed.load import reset
    reset()
    return db.connect()


@pytest.fixture(scope="module")
def truth():
    from claimbridge.seed.generate import load_truth
    return load_truth()
