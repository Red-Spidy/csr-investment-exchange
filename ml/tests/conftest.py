import pytest

from synth.world import generate_world


@pytest.fixture(scope="session")
def world():
    """One full-size world shared by every test. Generation is deterministic,
    so sharing it cannot leak state between tests."""
    return generate_world(seed=7)
