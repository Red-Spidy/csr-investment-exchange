"""Synthetic CSR world: NGOs with hidden traits, their projects and outcomes,
and their yearly spending.

Columns prefixed `hidden_` drive everything else but are never model features.
Models see only their noisy consequences -- a track record, a spending
pattern, a budget -- so they have to infer the hidden traits rather than read
back the rule that generated the data. Because the hidden values are kept, the
evaluation can also report how close a model gets to an oracle that sees them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from synth.anchors import FRAUD_RATE, SECTOR_OUTCOME_OFFSET, SECTOR_SHARE, STATE_DISTRICTS, STATES
from synth.catalog import ADMIN_BUDGET_ITEM, SECTOR_PROFILE

# Delivery capacity ~ Beta(4, 3): mean 0.571, most NGOs middling, few
# exceptional or hopeless.
CAPACITY_A, CAPACITY_B = 4.0, 3.0
CAPACITY_MEAN = CAPACITY_A / (CAPACITY_A + CAPACITY_B)

# Outcome model: how each driver moves the fraction of the claim delivered.
# The intercept is tuned so the overall mean lands on the IEG mean (0.616)
# after the penalties below pull it down.
OUTCOME_INTERCEPT = 0.68
CAPACITY_EFFECT = 0.65
ADEQUACY_EFFECT = 0.25   # per log-unit of funding vs need; capped, padding buys little
ADEQUACY_CAP = 0.15
AMBITION_PENALTY = 0.12  # per unit of claim beyond a typical one
FRAUD_PENALTY = 0.22     # diverted money does not reach the project
OUTCOME_NOISE = 0.19     # luck, local conditions: what no model can see
PAST_OUTCOME_NOISE = 0.20

# Proposal amounts: honest budgets scatter around need; fraudulent NGOs pad.
ADEQUACY_SIGMA = 0.35
FRAUD_PADDING_MEDIAN, FRAUD_PADDING_SIGMA = 1.45, 0.15
AMOUNT_MIN, AMOUNT_MAX, AMOUNT_STEP = 300_000, 50_000_000, 10_000
CLAIM_SIGMA = 0.40
SAME_STATE_SHARE = 0.85

SPLIT_SHARE = {"val": 0.15, "test": 0.15}   # remainder is train

# Spending history covers FY19-20 .. FY23-24 (start years 2019..2023).
FY_START_YEARS = range(2019, 2024)
LEGIT_SPIKE_RATE = 0.04      # honest NGO years with a one-off large grant

# Fraud manipulates 1-4 of these per anomalous year, never all of them, and by
# amounts that stay believable -- misuse an auditor could plausibly miss.
# Each entry: (how to apply the shift, low, high).
_FRAUD_SHIFTS = {
    "admin_expense_ratio": ("add", 0.06, 0.18),
    "round_number_freq": ("add", 0.12, 0.40),
    "vendor_concentration": ("add", 0.15, 0.45),
    "report_latency_days": ("mul", 1.5, 3.5),
    "burn_rate_vs_schedule": ("add", 0.25, 0.70),
    "category_mix_drift": ("add", 0.10, 0.30),
    "cost_per_beneficiary": ("mul", 1.3, 2.2),
}
FRAUD_FEATURES_PER_YEAR = (1, 4)
# Ceilings no real filing would exceed without being an obvious outlier.
MAX_ADMIN_RATIO, MAX_ROUND_FREQ, MAX_VENDOR_CONC, MAX_LATENCY_DAYS = 0.45, 0.75, 0.95, 120

_SECTOR_CODE = {
    "education": "EDU",
    "healthcare": "HLT",
    "livelihood": "LIV",
    "environment": "ENV",
    "water_sanitation": "WAT",
}
_NAME_PREFIX = (
    "Vidya", "Arogya", "Jal", "Prakriti", "Udyam", "Gramin", "Seva", "Jyoti",
    "Sankalp", "Disha", "Asha", "Navjeevan", "Sahyog", "Pragati", "Samarth", "Ujjwal",
)
_NAME_SUFFIX = ("Foundation", "Trust", "Samiti", "Society", "Mission", "Collective", "Sansthan")


@dataclass(frozen=True)
class World:
    ngos: pd.DataFrame
    projects: pd.DataFrame
    spending: pd.DataFrame


def generate_world(seed: int = 7, n_ngos: int = 500, n_projects: int = 2000) -> World:
    """Build the whole world from one seed. Same seed, same world."""
    rng = np.random.default_rng(seed)
    ngos = _make_ngos(rng, n_ngos)
    projects = _make_projects(rng, ngos, n_projects)
    spending = _make_spending(rng, ngos)
    return World(ngos=ngos, projects=projects, spending=spending)


def _outcome(capacity, sector_offset, is_fraud, noise, adequacy=1.0, ambition=1.0):
    """Fraction of a project's claimed improvement actually delivered, in [0, 1]."""
    latent = (
        CAPACITY_EFFECT * (capacity - CAPACITY_MEAN)
        + ADEQUACY_EFFECT * np.minimum(np.log(adequacy), ADEQUACY_CAP)
        - AMBITION_PENALTY * np.maximum(0.0, ambition - 1.0)
        + sector_offset
        - FRAUD_PENALTY * is_fraud
        + noise
    )
    return np.clip(OUTCOME_INTERCEPT + latent, 0.0, 1.0)


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


# --------------------------------------------------------------------- NGOs

def _allocate(shares: dict[str, float], n: int) -> list[str]:
    """Exactly n labels in proportion to shares (largest-remainder rounding),
    so the sector mix matches the anchor instead of drifting with the seed."""
    raw = {k: v * n for k, v in shares.items()}
    counts = {k: int(np.floor(v)) for k, v in raw.items()}
    short = n - sum(counts.values())
    for k in sorted(raw, key=lambda k: raw[k] - counts[k], reverse=True)[:short]:
        counts[k] += 1
    return [k for k, c in counts.items() for _ in range(c)]


def _past_delivery_rate(rng, capacity, sector_offset, is_fraud, k) -> float:
    """Mean outcome of an NGO's k completed projects -- a proxy for capacity
    whose noise shrinks as the record grows. NaN when there is no record."""
    if k == 0:
        return np.nan
    noise = rng.normal(0, PAST_OUTCOME_NOISE, size=k)
    return float(_outcome(capacity, sector_offset, is_fraud, noise).mean())


def _assign_splits(rng, is_fraud: np.ndarray) -> np.ndarray:
    """Split by NGO, stratified on fraud, so every split has fraudulent NGOs
    and no NGO's projects or spending appear in two splits."""
    split = np.empty(len(is_fraud), dtype=object)
    for group in (True, False):
        idx = rng.permutation(np.flatnonzero(is_fraud == group))
        n_val = round(SPLIT_SHARE["val"] * len(idx))
        n_test = round(SPLIT_SHARE["test"] * len(idx))
        split[idx[:n_val]] = "val"
        split[idx[n_val:n_val + n_test]] = "test"
        split[idx[n_val + n_test:]] = "train"
    return split


def _make_ngos(rng, n: int) -> pd.DataFrame:
    sectors = rng.permutation(_allocate(SECTOR_SHARE, n))
    is_fraud = np.zeros(n, dtype=bool)
    is_fraud[rng.choice(n, size=round(FRAUD_RATE * n), replace=False)] = True

    capacity = rng.beta(CAPACITY_A, CAPACITY_B, size=n)
    established = rng.integers(1990, 2023, size=n)          # 1990..2022
    # Older NGOs have completed more projects; very young ones often none.
    past_projects = np.minimum(rng.poisson(0.3 * (2024 - established)), 25)

    past_rate = [
        _past_delivery_rate(rng, capacity[i], SECTOR_OUTCOME_OFFSET[sectors[i]],
                            is_fraud[i], past_projects[i])
        for i in range(n)
    ]
    ids = np.arange(1, n + 1)
    return pd.DataFrame({
        "ngo_id": ids,
        "name": [f"{rng.choice(_NAME_PREFIX)} {rng.choice(_NAME_SUFFIX)}" for _ in range(n)],
        "registration_no": [f"NGO-{_SECTOR_CODE[s]}-{i:04d}" for s, i in zip(sectors, ids)],
        "sector": sectors,
        "state": rng.choice(STATES, size=n),
        "established_year": established,
        "past_projects": past_projects,
        "past_delivery_rate": np.round(past_rate, 4),
        "hidden_capacity": np.round(capacity, 4),
        "hidden_is_fraudulent": is_fraud,
        "split": _assign_splits(rng, is_fraud),
    })


# --------------------------------------------------------------------- projects

def _claim(rng, metric) -> tuple[float, float, float]:
    """Stated baseline and target, rounded the way proposals round them. The
    claim is never zero and stays physically possible: a percentage cannot
    pass 100, an incidence cannot fall below zero."""
    lo, hi = metric.baseline_range
    baseline = round(rng.uniform(lo, hi) / metric.step) * metric.step
    delta = metric.typical_delta * rng.lognormal(0, CLAIM_SIGMA)
    if metric.direction == "decrease":
        delta = min(delta, baseline - metric.step)
    elif metric.unit in ("percentage_points", "percent"):
        delta = min(delta, 100 - baseline)
    delta = max(metric.step, round(delta / metric.step) * metric.step)
    target = baseline - delta if metric.direction == "decrease" else baseline + delta
    return float(baseline), float(target), float(delta)


def _budget_lines(rng, profile, amount: int, is_fraud: bool) -> list[dict]:
    """3-5 line items summing exactly to the requested amount. Fraudulent NGOs
    carry a heavier administration line."""
    items = [str(i) for i in rng.choice(profile.budget_items, size=rng.integers(2, 5), replace=False)]
    admin_share = rng.uniform(0.05, 0.12) + (0.08 if is_fraud else 0.0)
    shares = rng.dirichlet(np.full(len(items), 3.0)) * (1 - admin_share)
    amounts = [int(round(amount * s / 1000)) * 1000 for s in shares]
    lines = [{"item": i, "amount": a} for i, a in zip(items, amounts)]
    # The rounding remainder lands on administration so the total is exact.
    lines.append({"item": ADMIN_BUDGET_ITEM, "amount": amount - sum(amounts)})
    return lines


def _make_projects(rng, ngos: pd.DataFrame, n: int) -> pd.DataFrame:
    rows = []
    for pid, i in enumerate(rng.integers(0, len(ngos), size=n), start=1):
        ngo = ngos.iloc[i]
        sector = str(ngo["sector"])
        profile = SECTOR_PROFILE[sector]
        capacity = float(ngo["hidden_capacity"])
        is_fraud = bool(ngo["hidden_is_fraudulent"])

        state = str(ngo["state"]) if rng.random() < SAME_STATE_SHARE else str(rng.choice(STATES))
        district = str(rng.choice(STATE_DISTRICTS[state]))
        activities = [str(a) for a in rng.choice(list(profile.activities), size=rng.integers(2, 4), replace=False)]
        sdgs = sorted({g for a in activities for g in profile.activities[a]})

        metric = profile.metrics[rng.integers(len(profile.metrics))]
        baseline, target, delta = _claim(rng, metric)
        beneficiaries = int(max(50, round(profile.median_beneficiaries * rng.lognormal(0, 0.7), -1)))

        need = beneficiaries * profile.cost_per_beneficiary
        padding = rng.lognormal(np.log(FRAUD_PADDING_MEDIAN), FRAUD_PADDING_SIGMA) if is_fraud else 1.0
        raw = need * rng.lognormal(0, ADEQUACY_SIGMA) * padding
        amount = int(np.clip(round(raw / AMOUNT_STEP) * AMOUNT_STEP, AMOUNT_MIN, AMOUNT_MAX))
        adequacy = amount / (need * padding)       # money that reaches the work, vs need
        ambition = delta / metric.typical_delta

        delivered = round(float(_outcome(
            capacity, SECTOR_OUTCOME_OFFSET[sector], is_fraud,
            rng.normal(0, OUTCOME_NOISE), adequacy, ambition,
        )), 4)
        duration = int(rng.integers(profile.duration_months[0], profile.duration_months[1] + 1))
        skill = capacity - CAPACITY_MEAN           # weaker NGOs write vaguer proposals

        rows.append({
            "project_id": pid,
            "ngo_id": int(ngo["ngo_id"]),
            "sector": sector,
            "state": state,
            "district": district,
            "title": f"{activities[0][0].upper()}{activities[0][1:]} and {activities[1]}, {district}",
            "activities": activities,
            "sdgs": sdgs,
            "metric_name": metric.name,
            "metric_unit": metric.unit,
            "metric_direction": metric.direction,
            "baseline": baseline,
            "target": target,
            "beneficiaries": beneficiaries,
            "beneficiary_group": str(rng.choice(profile.beneficiary_groups)),
            "requested_amount": amount,
            "duration_months": duration,
            "num_phases": int(np.clip(round(duration / 6), 2, 4)),
            "budget_lines": _budget_lines(rng, profile, amount, is_fraud),
            "states_baseline": bool(rng.random() < _sigmoid(1.0 + 4.0 * skill)),
            "states_beneficiaries": bool(rng.random() < _sigmoid(1.8 + 3.0 * skill)),
            "states_budget_breakdown": bool(rng.random() < _sigmoid(1.0 + 3.0 * skill - 1.2 * is_fraud)),
            "hidden_budget_adequacy": round(adequacy, 4),
            "hidden_ambition": round(ambition, 4),
            "delivered_fraction": delivered,
            "achieved_delta": round((target - baseline) * delivered, 4),
            "split": str(ngo["split"]),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------- spending

def _fy_label(start: int) -> str:
    return f"FY{start % 100:02d}-{(start + 1) % 100:02d}"


def _make_spending(rng, ngos: pd.DataFrame) -> pd.DataFrame:
    """Yearly spending per NGO. Every NGO has its own normal. Fraudulent NGOs
    break it in 1-3 recent years on a few features; honest NGOs occasionally
    have a legitimate spike -- a big one-off grant -- that moves spend and pace
    but none of the fraud markers."""
    rows = []
    for ngo in ngos.itertuples(index=False):
        years = [y for y in FY_START_YEARS if y >= ngo.established_year]
        size = rng.lognormal(np.log(2_000_000), 0.6)
        growth = rng.normal(0.07, 0.03)
        base = {
            "admin_expense_ratio": float(np.clip(rng.beta(2, 18), 0.02, 0.30)),
            "round_number_freq": rng.beta(2, 12),
            "vendor_concentration": rng.beta(3, 8),
            "report_latency_days": rng.lognormal(np.log(10), 0.4),
            "category_mix_drift": rng.uniform(0.02, 0.08),
            "cost_per_beneficiary": SECTOR_PROFILE[ngo.sector].cost_per_beneficiary * rng.lognormal(0, 0.25),
        }

        fraud_years: set[int] = set()
        if ngo.hidden_is_fraudulent:
            recent = years[-3:]
            k = int(rng.integers(1, min(3, len(recent)) + 1))
            fraud_years = {int(y) for y in rng.choice(recent, size=k, replace=False)}

        for year in years:
            row = {
                "total_spend": size * (1 + growth) ** (year - FY_START_YEARS[0]) * rng.lognormal(0, 0.08),
                "admin_expense_ratio": base["admin_expense_ratio"] + rng.normal(0, 0.012),
                "burn_rate_vs_schedule": rng.normal(1.0, 0.06),
                "category_mix_drift": base["category_mix_drift"] + abs(rng.normal(0, 0.02)),
                "round_number_freq": base["round_number_freq"] + rng.normal(0, 0.025),
                "vendor_concentration": base["vendor_concentration"] + rng.normal(0, 0.03),
                "report_latency_days": base["report_latency_days"] * rng.lognormal(0, 0.2),
                "cost_per_beneficiary": base["cost_per_beneficiary"] * rng.lognormal(0, 0.08),
            }
            if year in fraud_years:
                kind = "fraud"
                lo_n, hi_n = FRAUD_FEATURES_PER_YEAR
                for col in rng.choice(list(_FRAUD_SHIFTS), size=rng.integers(lo_n, hi_n + 1), replace=False):
                    how, lo, hi = _FRAUD_SHIFTS[col]
                    shift = rng.uniform(lo, hi)
                    row[col] = row[col] + shift if how == "add" else row[col] * shift
            elif not ngo.hidden_is_fraudulent and rng.random() < LEGIT_SPIKE_RATE:
                kind = "legit_spike"
                row["total_spend"] *= rng.uniform(2.0, 4.0)
                row["burn_rate_vs_schedule"] += rng.uniform(0.3, 0.8)
                row["category_mix_drift"] += rng.uniform(0.15, 0.30)
            else:
                kind = "none"

            rows.append({
                "ngo_id": int(ngo.ngo_id),
                "fy": _fy_label(year),
                "total_spend": round(float(row["total_spend"]), 2),
                "admin_expense_ratio": round(float(np.clip(row["admin_expense_ratio"], 0, MAX_ADMIN_RATIO)), 4),
                "burn_rate_vs_schedule": round(float(np.clip(row["burn_rate_vs_schedule"], 0.3, 5.0)), 4),
                "category_mix_drift": round(float(np.clip(row["category_mix_drift"], 0, 1)), 4),
                "round_number_freq": round(float(np.clip(row["round_number_freq"], 0, MAX_ROUND_FREQ)), 4),
                "vendor_concentration": round(float(np.clip(row["vendor_concentration"], 0, MAX_VENDOR_CONC)), 4),
                "report_latency_days": int(np.clip(round(row["report_latency_days"]), 1, MAX_LATENCY_DAYS)),
                "cost_per_beneficiary": round(float(row["cost_per_beneficiary"]), 2),
                "is_anomalous_truth": kind == "fraud",
                "hidden_anomaly_kind": kind,
                "split": str(ngo.split),
            })
    return pd.DataFrame(rows)
