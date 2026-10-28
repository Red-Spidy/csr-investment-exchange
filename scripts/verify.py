"""Is everything working? One command, three stages, one summary.

    make verify            everything, about 3 minutes
    make verify QUICK=1    skip the end-to-end stage, about 1 minute

1. Preflight: is the machine set up (Docker, Postgres, schema, Python, models, Node,
   Chrome)? Each failure says how to fix it, and stages that need it are skipped.
2. Layer tests: the database, ML, API and web suites, each on its own.
3. End to end: the browser's offline engine against the real API (make test-parity), then
   make demo-check: the deck's workflow through the API, every page in Chrome, and a
   browser journey through all three portals. It leaves a clean, scored demo.

Logs for every stage go to demo-check/verify/. Exits 1 if anything failed.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "demo-check" / "verify"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PSQL = ["docker", "exec", "-i", "csr_db", "psql", "-U", "csr", "-d", "csr_exchange", "-qtAX", "-c"]
QUICK = os.environ.get("QUICK", "") not in ("", "0")

rows: list[tuple[str, str, str, str]] = []   # stage, name, result, detail


def sh(cmd: list[str] | str, cwd: Path = ROOT, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=isinstance(cmd, str))


def sql(query: str) -> str | None:
    try:
        out = sh([*PSQL, query], timeout=15)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


# ---------------------------------------------------------------------------- preflight

def preflight() -> set[str]:
    """Run the setup checks; return what is available (db, python, models, node, chrome)."""
    print("Preflight: is the machine set up?")
    have: set[str] = set()

    def check(key: str | None, name: str, ok: bool, fix: str, warn: bool = False) -> bool:
        mark = "✓" if ok else ("!" if warn else "✗")
        print(f"  {mark} {name}" + ("" if ok else f"\n      {'note' if warn else 'fix'}: {fix}"))
        rows.append(("preflight", name, "ok" if ok else ("warn" if warn else "FAIL"), "" if ok else fix))
        if ok and key:
            have.add(key)
        return ok

    docker = shutil.which("docker") is not None and sh(["docker", "info"], timeout=20).returncode == 0
    check(None, "Docker is running", docker, "start Docker Desktop")
    health = sh(["docker", "inspect", "-f", "{{.State.Health.Status}}", "csr_db"]).stdout.strip() if docker else ""
    if check(None, "Postgres container csr_db is healthy", health == "healthy", "make up"):
        schema = sql("SELECT (SELECT count(*) FROM pg_extension WHERE extname = 'vector') "
                     "+ (SELECT count(DISTINCT proname) FROM pg_proc WHERE proname IN "
                     "('fn_commit_funds','fn_match_projects','fn_terminate_commitment','fn_grade_project','fn_review_project'))")
        if check("db", "Schema has all 8 migrations (pgvector, funding, matching, grading)", schema == "6",
                 "make demo   (rebuilds the database from db/migrations and seeds it)"):
            n = sql("SELECT count(*) FROM projects") or "0"
            scored = sql("SELECT count(*) FROM project_extractions WHERE model_version <> 'seed-placeholder'") or "0"
            check(None, f"Demo data is loaded and scored ({n} projects, {scored} read by BERT)",
                  int(n) >= 8 and int(scored) >= 8, "make demo score   (the end-to-end stage also does this)", warn=True)

    py = ROOT / ".venv" / "bin" / "python"
    imports = "import fastapi, httpx, psycopg, sklearn, torch, transformers, xgboost"
    check("python", "Python environment (.venv) has the API and ML packages",
          py.exists() and sh([str(py), "-c", imports], timeout=120).returncode == 0,
          "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt")
    art = ROOT / "ml" / "artifacts"
    check("models", "Trained models are in ml/artifacts (BERT, Isolation Forest, XGBoost)",
          (art / "bert").is_dir() and (art / "fraud_iforest.joblib").exists() and (art / "impact_xgb.joblib").exists(),
          "make train train-bert   (BERT takes about an hour on an M-series Mac)")
    nm = ROOT / "web" / "node_modules"
    check("node", "Frontend packages are installed (web/node_modules)",
          (nm / ".bin" / "vite").exists() and (nm / "playwright-core").is_dir(), "cd web && npm install")
    check("chrome", "Google Chrome is installed (page and browser checks)", Path(CHROME).exists(),
          "install Google Chrome")

    env = ROOT / ".env"
    keys = dict(re.findall(r"^([A-Z_]+)=(.*)$", env.read_text(), re.M)) if env.exists() else {}
    check(None, "GEMINI_API_KEY is set in .env (only needed to generate new training proposals)",
          bool(keys.get("GEMINI_API_KEY", "").strip()), "not needed for testing or the demo", warn=True)
    return have


# ---------------------------------------------------------------------------- stages

def count(log: str, kind: str) -> str:
    if kind == "db":
        failed = len(re.findall(r"ERROR:|^\s*FAIL", log, re.M))
        return f"{log.count('PASS ')} passed" + (f", {failed} failed" if failed else "")
    if kind == "pytest":
        m = re.findall(r"(\d+) (passed|failed|error)", log)
        return ", ".join(f"{n} {w}" for n, w in m[-2:]) if m else ""
    if kind == "vitest":
        m = re.search(r"Tests\s+(.+?)\s*\(", log)
        return m.group(1).strip() if m else ""
    if kind == "parity":
        m = re.search(r"Tests\s+(.+?)\s*\(", log)
        return m.group(1).strip() if m else ""
    if kind == "e2e":
        m = re.search(r"(\d+ of \d+) checks passed", log) or re.search(r"(\d+ of \d+ checks .*)", log)
        return f"{m.group(1)} checks" if m else ""
    return ""


def stage(group: str, name: str, cmd: str, kind: str, needs: set[str], have: set[str], timeout: int) -> None:
    missing = needs - have
    slug = re.sub(r"[^a-z]+", "-", name.split(":")[0].lower()).strip("-")
    if missing:
        print(f"  - {name}: skipped, needs {', '.join(sorted(missing))} (see preflight)")
        rows.append((group, name, "skipped", f"needs {', '.join(sorted(missing))}"))
        return
    live = sys.stdout.isatty()
    if live:
        print(f"  … {name}", end="", flush=True)
    t0 = time.time()
    try:
        out = sh(cmd, timeout=timeout)
        log, ok = out.stdout + out.stderr, out.returncode == 0
    except subprocess.TimeoutExpired as e:
        log, ok = f"{e.stdout or ''}{e.stderr or ''}\nTimed out after {timeout}s", False
    secs = time.time() - t0
    (LOGS / f"{slug}.log").write_text(log)
    detail = count(log, kind)
    print(f"{chr(13) if live else ''}  {'✓' if ok else '✗'} {name}  {detail}  ({secs:.0f}s)")
    if not ok:
        tail = [l for l in log.splitlines() if l.strip()][-15:]
        print("      " + "\n      ".join(tail))
        print(f"      full log: demo-check/verify/{slug}.log   rerun: {cmd}")
    rows.append((group, name, "ok" if ok else "FAIL", detail or f"{secs:.0f}s"))


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    have = preflight()

    print("\nLayer tests: each part on its own")
    stage("layers", "Database: triggers, funding rules, races, window functions, grading",
          "make test-db", "db", {"db"}, have, 300)
    stage("layers", "ML: synthetic world, fraud, impact, BERT readers, scoring pipeline",
          "make test-ml", "pytest", {"db", "python"}, have, 900)
    stage("layers", "API: every route, against a throwaway copy of the database",
          "make test-api", "pytest", {"db", "python"}, have, 600)
    stage("layers", "Web: unit tests, type check, production build",
          "make test-web", "vitest", {"node"}, have, 300)

    print("\nEnd to end: the product, as the demo uses it")
    if QUICK:
        print("  - skipped (QUICK=1)")
        rows.append(("e2e", "end to end", "skipped", "QUICK=1"))
    else:
        stage("e2e", "Offline engine: the browser's copy of the rules equals the real API",
              "make test-parity", "parity", {"db", "python", "node"}, have, 600)
        stage("e2e", "Demo check: API workflow, every page, browser journey, clean reset",
              "make demo-check", "e2e", {"db", "python", "models", "node", "chrome"}, have, 1200)

    failed = [r for r in rows if r[2] == "FAIL"]
    skipped = [r for r in rows if r[2] == "skipped" and r[3] != "QUICK=1"]
    mins, secs = divmod(int(time.time() - t0), 60)
    took = f"in {mins}m {secs:02d}s"
    if failed:
        print(f"\nFAILED {took}: " + "; ".join(r[1].split(':')[0] for r in failed)
              + ". Fix the first one first; its log is in demo-check/verify/.")
    elif skipped:
        print(f"\nNothing failed, but {len(skipped)} stage(s) could not run {took}: "
              + "; ".join(r[1].split(':')[0] for r in skipped) + ". See the preflight fixes above.")
    elif QUICK:
        print(f"\nAll layer tests passed {took}. Run make verify without QUICK=1 for the end-to-end stage.")
    else:
        print(f"\nEverything passed {took}. The demo data is clean and scored.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
