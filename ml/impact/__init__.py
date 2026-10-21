import os

# XGBoost, scikit-learn and PyTorch each bundle an OpenMP runtime. Loaded
# together and multi-threaded they deadlock (the test suite hung at 0% CPU),
# and the scoring pipeline loads all three. One OpenMP thread avoids it; the
# models are small and BERT runs on the GPU. Must run before those imports.
os.environ.setdefault("OMP_NUM_THREADS", "1")
