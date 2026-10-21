import os

# Loads XGBoost, scikit-learn and PyTorch together: see ml/fraud/__init__.py.
os.environ.setdefault("OMP_NUM_THREADS", "1")
