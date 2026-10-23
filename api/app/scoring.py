"""The trained models, for the routes that need them.

Loaded on first use, not at startup: the API starts in a second and its other
routes never touch PyTorch. Inference is serialised with a lock -- one BERT
model shared by request threads should not run two passes at once.
"""

import sys
import threading
from pathlib import Path

ML = Path(__file__).resolve().parents[2] / "ml"
NOT_TRAINED = "the models are not trained yet: run make train and make train-bert"


class PipelineScorer:
    def __init__(self, artifacts: Path = ML / "artifacts"):
        self.artifacts = artifacts
        self._models = None
        self._embedder = None
        self._lock = threading.Lock()

    @staticmethod
    def _pipeline():
        if str(ML) not in sys.path:
            sys.path.insert(0, str(ML))
        import pipeline.score as score   # noqa: PLC0415 -- deliberately lazy
        return score

    def _load(self):
        with self._lock:
            if self._models is None:
                if not (self.artifacts / "bert" / "reader.json").exists():
                    raise RuntimeError(NOT_TRAINED)
                self._models = self._pipeline().Models.load(self.artifacts)
            return self._models

    def score(self, conn, project_id: int) -> dict:
        """Run every model over one project and grade it (ml/pipeline/score.py)."""
        models = self._load()
        with self._lock:
            return self._pipeline().score_project(conn, models, project_id)

    def score_database(self, conn) -> dict:
        """What `make score` does: embed every rulebook, then score and grade every project."""
        models = self._load()
        score = self._pipeline()
        with self._lock:
            rulebooks = score.embed_rulebooks(conn, models)
            with conn.cursor() as cur:
                ids = [r["id"] if isinstance(r, dict) else r[0]
                       for r in cur.execute("SELECT id FROM projects ORDER BY id").fetchall()]
            for pid in ids:
                score.score_project(conn, models, pid)
        return {"projects": len(ids), "rulebooks": rulebooks}

    def embed_rulebook(self, requirement_text, focus_areas, preferred_states, target_sdgs) -> list[float]:
        """The same MiniLM embedding, over the same canonical text, as `make score`."""
        score = self._pipeline()
        text = score.rulebook_canonical_text(requirement_text, focus_areas, preferred_states, target_sdgs)
        with self._lock:
            if self._embedder is None:
                if self._models is not None:
                    self._embedder = self._models.embedder
                else:
                    from sentence_transformers import SentenceTransformer  # noqa: PLC0415
                    self._embedder = SentenceTransformer(score.EMBEDDING_MODEL)
            return self._embedder.encode([text], normalize_embeddings=True, show_progress_bar=False)[0].tolist()
