"""Rating NGO progress updates, for the routes that take them (ml/progress/rate.py).

A rating is written after the update itself has been saved and committed, so a rater
that is slow or down never loses an NGO's report: it stays unrated and `make rate`
rates it later. The rating is advice for the reviewer; no route reads it to move money.
"""
import sys
from pathlib import Path
from typing import Any, Literal

ML = Path(__file__).resolve().parents[2] / "ml"


def _rate_module():
    if str(ML) not in sys.path:
        sys.path.insert(0, str(ML))
    import progress.rate as rate   # noqa: PLC0415 -- ml/ is on the path only from here on
    return rate


def rater_from_env() -> Any:
    """Gemini when GEMINI_API_KEY is set, the rules otherwise; None when CSR_RATER=off."""
    rate = _rate_module()
    return rate.rater_from_env(rate.read_env())


def rule_rater() -> Any:
    return _rate_module().RuleRater()


def rate_update(conn: Any, rater: Any, kind: Literal["report", "milestone"], row_id: int) -> dict[str, str] | None:
    """Rate one saved update and store the rating; the receipt line, or None if there is nothing to rate."""
    rate = _rate_module()
    try:
        ctx = rate.load_report(conn, row_id) if kind == "report" else rate.load_milestone(conn, row_id)
        if not ctx.update.strip():
            return None
        r = rater.rate(ctx)
        rate.store(conn, "impact_reports" if kind == "report" else "milestones", row_id, r)
    except Exception as err:   # noqa: BLE001 -- any rating failure leaves the update saved and unrated
        return {"by": "rating", "text": f"Not rated yet: {err}. The update is saved; make rate rates it later."}
    by = "the rules" if r.rated_by.startswith("rules") else r.rated_by
    flags = f" Flags: {'; '.join(r.flags)}." if r.flags else ""
    return {"by": "rating", "text": f"Rated {r.rating} of 5 by {by}: {r.reason}{flags}"}
