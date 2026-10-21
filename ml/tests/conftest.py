import os

# See ml/fraud/__init__.py: several OpenMP runtimes in one process deadlock.
os.environ.setdefault("OMP_NUM_THREADS", "1")

import pytest

from synth.world import generate_world


@pytest.fixture(scope="session")
def world():
    """One full-size world shared by every test. Generation is deterministic,
    so sharing it cannot leak state between tests."""
    return generate_world(seed=7)


@pytest.fixture(scope="session")
def tokenizer():
    """A real fast tokenizer already in the local cache, so NLP tests run
    offline. Training-time code uses bert-base-cased; the alignment logic
    under test is identical for any fast tokenizer."""
    from transformers import AutoTokenizer
    name = "sentence-transformers/all-MiniLM-L6-v2"
    try:
        return AutoTokenizer.from_pretrained(name, local_files_only=True)
    except OSError:                       # a fresh machine or CI: fetch it once
        return AutoTokenizer.from_pretrained(name)
