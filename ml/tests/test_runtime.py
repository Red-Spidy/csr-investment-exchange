"""Loading the fraud, impact and BERT models in one process must not deadlock.

XGBoost, scikit-learn and PyTorch each ship their own OpenMP runtime. With all
three loaded and multi-threaded, the full test suite hung at 0% CPU -- and so
would the scoring pipeline, which loads all three. Each model package limits
OpenMP to one thread on import, unless the caller has already chosen."""

import os
import subprocess
import sys
from pathlib import Path

ML = Path(__file__).resolve().parents[1]


def _omp_threads_after_import(env_extra):
    env = {k: v for k, v in os.environ.items() if k != "OMP_NUM_THREADS"} | env_extra
    code = "import fraud.model, impact.model, nlp.reader, os; print(os.environ['OMP_NUM_THREADS'])"
    out = subprocess.run([sys.executable, "-c", code], env=env | {"PYTHONPATH": str(ML)},
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_importing_the_model_packages_limits_openmp_to_one_thread():
    assert _omp_threads_after_import({}) == "1"


def test_an_explicit_choice_by_the_caller_is_respected():
    assert _omp_threads_after_import({"OMP_NUM_THREADS": "4"}) == "4"
