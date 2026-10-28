"""Check the whole project end to end, the way the demo runs it.

    make demo-check

1. Rebuild, seed and score the database with the trained models (make demo, make score).
2. Start the API and the built frontend on spare ports, so a running `make api` is untouched.
3. Walk the deck's workflow through the API the frontend uses, checking every step.
4. Render every page in headless Chrome: a screenshot each, and its text checked.
5. Click through the whole product in Chrome as each party (web/e2e/journey.mjs).
6. Reset and rescore through the API, the sidebar's Reset path, so the demo starts clean.

Screenshots go to demo-check/ (gitignored). Exits 1 if any check fails.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo-check"
API_PORT, WEB_PORT = 8021, 4321
API = f"http://127.0.0.1:{API_PORT}/api"
WEB = f"http://127.0.0.1:{WEB_PORT}"
DB_URL = "postgresql://csr:csr@localhost:5433/csr_exchange"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

PROPOSAL = {
    "ngoId": 2, "title": "Girls science clubs, Gaya", "sector": "education", "state": "Bihar",
    "requestedAmount": 1200000, "durationMonths": 12, "numPhases": 2,
    "proposalText": (
        "Gramin Shiksha Trust will run after-school science clubs for 2,400 adolescent girls in 30 "
        "government schools of Gaya district, Bihar. The average science score of these girls is 41% "
        "today; with weekly lab sessions, scholarships for science kits and teacher training, we aim to "
        "raise it from 41% to 55% within 12 months. We request Rs 12 lakh."),
}
# Words that mean a page rendered a broken value.
BROKEN = ("NaN", "undefined", "[object Object]", "from null", "Cannot reach the server")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok, detail: str = "") -> bool:
    results.append((name, bool(ok), detail))
    print(f"  {'✓' if ok else '✗'} {name}" + (f"  ({detail})" if detail and not ok else ""))
    return bool(ok)


def run(*cmd: str, cwd: Path = ROOT, quiet: bool = True) -> None:
    out = subprocess.DEVNULL if quiet else None
    subprocess.run(cmd, cwd=cwd, check=True, stdout=out, stderr=out)


def start(cmd: list[str], cwd: Path, env: dict, log: Path) -> subprocess.Popen:
    return subprocess.Popen(cmd, cwd=cwd, env={**os.environ, **env}, stdout=log.open("w"),
                            stderr=subprocess.STDOUT, start_new_session=True)


def stop(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=20)


def wait_for(url: str, seconds: int = 90) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=3).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


# --------------------------------------------------------------------- workflow

def workflow(c: httpx.Client) -> dict:
    """The deck's workflow, step by step, through the API. Returns ids the page checks use."""
    get = lambda path: c.get(path).raise_for_status().json()
    post = lambda path, body=None: c.post(path, json=body or {}).raise_for_status().json()
    seen: dict = {}

    print("\nThe scored demo")
    board = get("/scorecard")
    check("8 seeded projects, every one graded", len(board) == 8 and all(r["grade"] for r in board))
    two = get("/projects/2")
    check("BERT, XGBoost and the Isolation Forest wrote the evidence",
          two["extraction"]["modelVersion"] == "bert-v1" and two["prediction"]["modelVersion"] == "xgb-v1"
          and two["fraud"]["modelVersion"] == "iforest-v1")
    eight = get("/projects/8")
    check("the planted spending anomaly at NGO 4 is caught and sent to review",
          eight["fraud"]["isAnomaly"] and eight["project"]["status"] == "flagged")

    print("\nAn NGO submits a proposal")
    sub = post("/projects", PROPOSAL)
    by = [e["by"] for e in sub.get("effects", [])]
    check("it is saved, then read, scored and graded", sub["ok"] and by[-1:] == ["fn_grade_project"]
          and {"BERT", "Isolation Forest", "XGBoost"} <= set(by), str(by))
    new = get(f"/projects/{sub['projectId']}")
    check("its status is the grade's decision", new["project"]["status"] == new["risk"]["decision"])
    seen["new_project"] = sub["projectId"]

    print("\nA reviewer settles a flagged project")
    rev = post("/projects/3/review", {"approve": True, "note": "baseline confirmed with the district office"})
    check("approving project 3 puts it in the matching pool",
          rev["ok"] and get("/projects/3")["project"]["status"] == "approved")
    check("a project that was not flagged cannot be reviewed", post("/projects/2/review", {"approve": True})["ok"] is False)

    print("\npgvector matching")
    rulebook = next(r for r in get("/rulebooks") if r["companyId"] == 2)
    ranked = get(f"/rulebooks/{rulebook['id']}/matches")["ranked"]
    check("the healthcare company's rulebook now ranks project 3",
          any(m["projectId"] == 3 for m in ranked), str([m["projectId"] for m in ranked]))

    print("\nAtomic commitment and double funding")
    commit = post("/commitments", {"companyId": 2, "projectId": 3})
    check("committing funds locks them in one transaction", commit["ok"] and commit.get("commitmentId"))
    cid = commit.get("commitmentId")
    check("a second commitment to the same project is refused", post("/commitments", {"companyId": 1, "projectId": 3})["ok"] is False)
    view = next(v for v in get("/commitments") if v["commitment"]["id"] == cid)
    check("the phase schedule and milestones were generated by trigger",
          len(view["phases"]) == view["project"]["numPhases"] and all(p["status"] == "locked" for p in view["phases"]))
    milestones = sorted(view["milestones"], key=lambda m: m["phaseNo"])

    print("\nMilestones: no proof, no release")
    m1, m2 = milestones[0], milestones[1]
    post(f"/milestones/{m1['id']}/evidence", {"metric": 60})
    check("verifying milestone 1 releases phase 1", post(f"/milestones/{m1['id']}/verify")["ok"])
    view = next(v for v in get("/commitments") if v["commitment"]["id"] == cid)
    check("phase 1 released, the rest still locked",
          [p["status"] for p in sorted(view["phases"], key=lambda p: p["phaseNo"])][:2] == ["released", "locked"])
    post(f"/milestones/{m2['id']}/evidence", {"metric": 61})
    check("failing milestone 2 holds its money", post(f"/milestones/{m2['id']}/fail")["ok"])
    view = next(v for v in get("/commitments") if v["commitment"]["id"] == cid)
    check("phase 2 held, project flagged",
          sorted(view["phases"], key=lambda p: p["phaseNo"])[1]["status"] == "held"
          and get("/projects/3")["project"]["status"] == "flagged")
    term = post(f"/commitments/{cid}/terminate", {"reason": "milestone 2 evidence did not hold up"})
    ledger = [l for l in get("/ledger") if l["commitmentId"] == cid]
    check("terminating refunds what was not released, and the ledger records it",
          term["ok"] and any(l["type"] == "refund" for l in ledger))

    print("\nWindow functions")
    before = len(get("/esg-timeline"))
    check("an NGO's monthly report is accepted", post("/projects/1/impact-reports", {"value": 1.4})["ok"])
    check("company_esg_timeline gains the new month", len(get("/esg-timeline")) == before + 1)

    print("\nSafeguards")
    any_row = get("/ledger")[0]["id"]
    attempt = post(f"/ledger/{any_row}/attempts", {"op": "UPDATE"})
    check("the ledger refuses an UPDATE", attempt["ok"] is False and "append-only" in attempt.get("error", ""))
    approved = next((r for r in get("/scorecard") if r["status"] == "approved"), None)
    sundar = next(co for co in get("/companies") if co["id"] == 3)
    over = post("/commitments", {"companyId": 3, "projectId": approved["projectId"] if approved else 0,
                                 "amount": sundar["mandatedBudget"] - sundar["committedBudget"] + 400000})
    check("committing more than the mandated budget is refused by the budget check",
          over["ok"] is False and "remaining, cannot commit" in over.get("error", ""), over.get("error", ""))
    race = post("/safeguards/race", {"statusCheck": True, "guardTrigger": True, "uniqueIndex": True})
    check("two sessions race for one project and exactly one wins",
          race["winner"] in ("A", "B") and race["activeCommitments"] == 1)

    print("\nA company writes a new rulebook")
    rb = post("/rulebooks", {"companyId": 3, "requirementText": "Safe drinking water for villages in Rajasthan.",
                             "focusAreas": ["water_sanitation"], "preferredStates": ["Rajasthan"],
                             "targetSdgs": [6], "minBudget": 500000, "maxBudget": 5000000})
    check("it is saved and embedded for matching",
          rb["ok"] and any("Embedded" in e["text"] for e in rb["effects"]), str(rb.get("effects")))
    seen["rulebook"] = rb.get("rulebookId")
    return seen


# --------------------------------------------------------------------- pages

# (screenshot name, path, text the page must show). The sign-in page has no live indicator.
PAGES = [
    ("signin", "/", ["Sign in", "Company CSR team", "Exchange reviewer"]),
    ("ngo-home", "/ngo/1", ["My projects", "Needs you now"]),
    ("ngo-new", "/ngo/1/new", ["New proposal", "What gets a proposal approved"]),
    ("ngo-project", "/ngo/1/projects/1", ["Your proposal", "Submit evidence"]),
    ("company-overview", "/company/1", ["Overview", "Your projects"]),
    ("company-find", "/company/2/find", ["Find projects", "Your criteria"]),
    ("company-funding", "/company/2/funding", ["Funding", "Ledger", "Terminated"]),
    ("company-impact", "/company/1/impact", ["Impact", "NGO leaderboard"]),
    ("company-project", "/company/1/projects/2", ["Expected impact", "Overall score"]),
    ("review-queue", "/review", ["Review queue", "Proposals to decide"]),
    ("review-projects", "/review/projects", ["All projects"]),
    ("review-decision", "/review/projects/7", ["Your decision", "Spending check"]),
    ("review-milestones", "/review/milestones", ["Milestones", "Ledger"]),
    ("review-safeguards", "/review/safeguards", ["Safeguards", "Race two sessions"]),
]


def render(name: str, path: str) -> str:
    profile = OUT / ".chrome-profile"
    base = [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            f"--user-data-dir={profile}", "--window-size=1440,1400", "--virtual-time-budget=20000"]
    subprocess.run([*base, f"--screenshot={OUT / (name + '.png')}", WEB + path],
                   check=True, capture_output=True, timeout=120)
    return subprocess.run([*base, "--dump-dom", WEB + path], check=True, capture_output=True,
                          text=True, timeout=120).stdout


def pages(seen: dict) -> None:
    print("\nEvery page, rendered in Chrome")
    new = ("ngo-new-project", f"/ngo/{PROPOSAL['ngoId']}/projects/{seen.get('new_project')}", [PROPOSAL["title"]])
    for name, path, must in [*PAGES, new]:
        dom = render(name, path)
        missing = [m for m in [*(["Connected"] if path != "/" else []), *must] if m not in dom]
        broken = [b for b in BROKEN if b in dom]
        check(f"{path} renders with live data", not missing and not broken,
              f"missing {missing}" if missing else f"shows {broken}")


def journey() -> None:
    """Click through the product as an NGO, the reviewer and companies would (web/e2e/journey.mjs)."""
    print("\nThe product, used through the browser")
    out = subprocess.run(["node", "e2e/journey.mjs"], cwd=ROOT / "web", capture_output=True, text=True,
                         timeout=900, env={**os.environ, "WEB": WEB, "OUT": str(OUT / "journey") + "/"})
    lines = [l for l in out.stdout.splitlines() if l.strip()]
    for line in lines:
        if line.lstrip().startswith(("✓", "✗")) or line.startswith("      "):
            print("  " + line)
    summary = next((l for l in reversed(lines) if "steps passed" in l), out.stderr.strip()[-300:] or "no output")
    problems = [l for l in lines if l.startswith("  [")]
    check(f"UI journey: {summary}", out.returncode == 0 and not problems,
          "; ".join(problems[:3]) if problems else summary)


# --------------------------------------------------------------------- main

def main() -> int:
    if not Path(CHROME).exists():
        print(f"needs Google Chrome at {CHROME} for the page checks")
        return 2
    OUT.mkdir(exist_ok=True)
    print("Rebuilding, seeding and scoring the database (make demo, make score)...")
    run("make", "demo")
    run("make", "score")
    print("Building the frontend...")
    run("npm", "run", "build", cwd=ROOT / "web")

    api = web = None
    try:
        api = start([str(ROOT / ".venv/bin/python"), "-m", "uvicorn", "app.main:app", "--app-dir", "api",
                     "--port", str(API_PORT)], ROOT, {"DATABASE_URL": DB_URL, "CSR_ALLOW_RESET": "1"},
                    OUT / "api.log")
        web = start(["npx", "vite", "preview", "--host", "127.0.0.1", "--port", str(WEB_PORT), "--strictPort"],
                    ROOT / "web", {"API_URL": f"http://127.0.0.1:{API_PORT}"}, OUT / "web.log")
        if not (check("the API is up", wait_for(f"{API}/health")) and check("the frontend is up", wait_for(WEB))):
            return 1
        with httpx.Client(base_url=API, timeout=180) as client:
            seen = workflow(client)
            pages(seen)
            journey()
            print("\nLeaving a clean demo")
            reset = client.post("/reset", json={"score": True}).raise_for_status().json()
            check("Reset database rebuilds and rescores with the models",
                  reset.get("scored", {}).get("projects") == 8, str(reset))
    finally:
        stop(web)
        stop(api)

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed. Screenshots: {OUT.relative_to(ROOT)}/")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
