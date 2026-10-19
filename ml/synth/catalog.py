"""What a project looks like in each sector.

Activities carry the SDGs they serve, so a project's SDG labels follow from
what its proposal actually describes rather than being assigned separately.

ASSUMPTIONS: cost per beneficiary and beneficiary scale mirror the demo
scenario in db/seed.sql (e.g. ~Rs 560 per student, ~Rs 2,300 per weaver), so
the trained models score the demo projects in a range they have seen.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    name: str
    unit: str
    direction: str                      # 'increase' | 'decrease'
    baseline_range: tuple[float, float]
    typical_delta: float                # a normal, non-ambitious claim
    step: float                         # proposals state round values


@dataclass(frozen=True)
class SectorProfile:
    activities: dict[str, tuple[int, ...]]
    metrics: tuple[Metric, ...]
    beneficiary_groups: tuple[str, ...]
    median_beneficiaries: int
    cost_per_beneficiary: float         # INR for a fully funded project
    duration_months: tuple[int, int]
    budget_items: tuple[str, ...]


ADMIN_BUDGET_ITEM = "administration and monitoring"

SECTOR_PROFILE: dict[str, SectorProfile] = {
    "education": SectorProfile(
        activities={
            "midday meal support": (2, 4),
            "teacher training": (4,),
            "girls' scholarships": (4, 5),
            "digital classrooms": (4, 9),
            "remedial classes": (4,),
            "school toilet construction": (4, 6),
        },
        metrics=(
            Metric("attendance_rate", "percentage_points", "increase", (50, 80), 8, 1),
            Metric("learning_outcome_score", "percentage_points", "increase", (35, 60), 9, 1),
        ),
        beneficiary_groups=("primary school children", "students in grades 6-8", "adolescent girls"),
        median_beneficiaries=3000,
        cost_per_beneficiary=450,
        duration_months=(9, 24),
        budget_items=("learning materials", "teacher training", "community mobilisers", "infrastructure upgrades"),
    ),
    "healthcare": SectorProfile(
        activities={
            "mobile health camps": (3,),
            "antenatal checkups": (3, 5),
            "anaemia screening": (2, 3),
            "immunisation drives": (3,),
            "telemedicine kiosks": (3, 9),
            "community health worker training": (3,),
        },
        metrics=(
            Metric("antenatal_coverage", "percentage_points", "increase", (40, 70), 14, 1),
            Metric("child_immunisation_rate", "percentage_points", "increase", (55, 80), 12, 1),
        ),
        beneficiary_groups=("pregnant women", "children under five", "village residents"),
        median_beneficiaries=5000,
        cost_per_beneficiary=700,
        duration_months=(12, 24),
        budget_items=("medical supplies", "health worker stipends", "mobile camp operations", "diagnostic equipment"),
    ),
    "water_sanitation": SectorProfile(
        activities={
            "handpump rehabilitation": (6,),
            "toilet block construction": (6,),
            "water chlorination": (3, 6),
            "rainwater harvesting": (6, 13),
            "hygiene awareness sessions": (3, 6),
            "menstrual hygiene programmes": (5, 6),
        },
        metrics=(
            Metric("waterborne_disease_incidence", "percent", "decrease", (10, 30), 6, 1),
            Metric("households_with_safe_water", "percentage_points", "increase", (30, 65), 20, 1),
        ),
        beneficiary_groups=("village residents", "school children", "slum households"),
        median_beneficiaries=20000,
        cost_per_beneficiary=70,
        duration_months=(6, 18),
        budget_items=("civil works", "materials and pipes", "community training", "water quality testing"),
    ),
    "environment": SectorProfile(
        activities={
            "native sapling plantation": (13, 15),
            "mangrove restoration": (13, 14, 15),
            "solar street lighting": (7, 13),
            "waste segregation drives": (11, 12),
            "check dam construction": (6, 15),
            "clean cookstove distribution": (3, 7, 13),
        },
        metrics=(
            Metric("tree_cover", "hectares", "increase", (0, 0), 250, 10),
            Metric("waste_diverted", "tonnes_per_month", "increase", (0, 0), 40, 1),
        ),
        beneficiary_groups=("community members", "farming households", "coastal villagers"),
        median_beneficiaries=4000,
        cost_per_beneficiary=600,
        duration_months=(18, 36),
        budget_items=("saplings and materials", "field staff", "community engagement", "survival monitoring"),
    ),
    "livelihood": SectorProfile(
        activities={
            "vocational skill training": (4, 8),
            "self-help group microcredit": (1, 5, 8),
            "market linkage for artisans": (8,),
            "drip irrigation for smallholders": (2, 8),
            "dairy cooperative support": (1, 2, 8),
            "artisan design training": (8,),
        },
        metrics=(
            Metric("household_monthly_income", "percent_increase", "increase", (0, 0), 22, 1),
            Metric("women_in_paid_work", "percentage_points", "increase", (15, 40), 10, 1),
        ),
        beneficiary_groups=("handloom weavers", "smallholder farmers", "women in self-help groups"),
        median_beneficiaries=900,
        cost_per_beneficiary=2500,
        duration_months=(12, 30),
        budget_items=("training costs", "equipment and inputs", "market linkage", "working capital support"),
    ),
}
