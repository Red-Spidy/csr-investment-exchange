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


# How the proposal checker recognises that an activity is actually described.
# Each activity lists alternatives; an alternative matches when every "+"-joined
# part appears in the lowercased text. Spelling variants are listed because
# LLMs write both "anaemia" and "anemia".
ACTIVITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "midday meal support": ("midday meal", "mid-day meal", "mid day meal"),
    "teacher training": ("teacher+train",),
    "girls' scholarships": ("scholarship",),
    "digital classrooms": ("digital+classroom", "smart class", "digital learning"),
    "remedial classes": ("remedial", "catch-up class", "bridge class"),
    "school toilet construction": ("toilet",),
    "mobile health camps": ("health camp", "mobile clinic", "mobile medical"),
    "antenatal checkups": ("antenatal", "ante-natal", "prenatal"),
    "anaemia screening": ("anaemia", "anemia", "haemoglobin", "hemoglobin"),
    "immunisation drives": ("immunisation", "immunization", "vaccinat"),
    "telemedicine kiosks": ("telemedicine", "tele-medicine", "teleconsult"),
    "community health worker training": ("health worker", "asha+train"),
    "handpump rehabilitation": ("handpump", "hand pump", "hand-pump"),
    "toilet block construction": ("toilet",),
    "water chlorination": ("chlorin",),
    "rainwater harvesting": ("rainwater", "rain water"),
    "hygiene awareness sessions": ("hygiene awareness", "hygiene education", "hygiene session",
                                   "hygiene practice", "handwashing", "hand washing", "hand-washing"),
    "menstrual hygiene programmes": ("menstrua",),
    "native sapling plantation": ("sapling", "tree planting", "plantation", "plant+tree"),
    "mangrove restoration": ("mangrove",),
    "solar street lighting": ("solar",),
    "waste segregation drives": ("segregat",),
    "check dam construction": ("check dam", "check-dam", "checkdam"),
    "clean cookstove distribution": ("cookstove", "cook stove", "cook-stove", "chulha"),
    "vocational skill training": ("vocational", "skill training", "skills training", "skilling"),
    "self-help group microcredit": ("self-help group", "self help group", "shg", "microcredit",
                                    "micro-credit", "microfinance"),
    "market linkage for artisans": ("market linkage", "market access", "link+market"),
    "drip irrigation for smallholders": ("drip",),
    "dairy cooperative support": ("dairy",),
    "artisan design training": ("design training", "design+artisan", "product design"),
}


# How the proposal prompt describes each activity. Two phrasings per activity,
# chosen per project, so the corpus never hands every proposal the same
# catalogue label to copy. Every phrasing must satisfy ACTIVITY_KEYWORDS --
# a test enforces it -- so a proposal that copies one is still accepted.
ACTIVITY_DESCRIPTIONS: dict[str, tuple[str, ...]] = {
    "midday meal support": ("hot cooked mid-day meals served at school every day",
                            "a daily midday meal so children do not study hungry"),
    "teacher training": ("workshops that train government teachers in activity-based teaching",
                         "regular training for teachers on classroom methods"),
    "girls' scholarships": ("scholarships that cover fees and supplies for girls",
                            "small scholarship grants so girls can stay enrolled"),
    "digital classrooms": ("digital classrooms with projectors and offline learning content",
                           "turning classrooms into digital learning spaces with tablets"),
    "remedial classes": ("after-school remedial classes for children who have fallen behind",
                         "remedial sessions in reading and arithmetic"),
    "school toilet construction": ("building separate toilets for girls and boys at schools",
                                   "new school toilets with running water"),
    "mobile health camps": ("regular health camps run by a doctor and nurse in each village",
                            "a mobile medical unit that visits remote hamlets"),
    "antenatal checkups": ("regular antenatal check-ups for pregnant women",
                           "antenatal care visits that track blood pressure and weight"),
    "anaemia screening": ("haemoglobin testing to detect anaemia early",
                          "screening women and adolescents for anaemia, with iron supplements"),
    "immunisation drives": ("catch-up immunisation sessions for children who missed vaccines",
                            "vaccination drives run with the local health centre"),
    "telemedicine kiosks": ("telemedicine kiosks where villagers consult doctors by video",
                            "a telemedicine point linking patients to specialists in the city"),
    "community health worker training": ("training village health workers to track pregnancies and refer cases",
                                         "refresher courses for local health workers"),
    "handpump rehabilitation": ("repairing broken handpumps and replacing worn parts",
                                "restoring hand pumps so every hamlet has a working water source"),
    "toilet block construction": ("building community toilet blocks",
                                  "household and community toilets with safe drainage"),
    "water chlorination": ("chlorination of village wells and tanks",
                           "regular chlorine dosing of drinking water sources"),
    "rainwater harvesting": ("rooftop rainwater harvesting structures",
                             "rain water collection tanks for the dry months"),
    "hygiene awareness sessions": ("hygiene education sessions on handwashing and safe water storage",
                                   "hygiene awareness meetings in schools and hamlets"),
    "menstrual hygiene programmes": ("menstrual hygiene sessions and low-cost sanitary pads for girls",
                                     "awareness on menstrual health with safe disposal facilities"),
    "native sapling plantation": ("planting native saplings on degraded land",
                                  "raising and planting native tree species with village groups"),
    "mangrove restoration": ("replanting and protecting mangroves along the coast",
                             "restoring degraded mangrove belts"),
    "solar street lighting": ("solar-powered street lights in village lanes",
                              "solar lamps at junctions and schools"),
    "waste segregation drives": ("door-to-door collection with segregation of wet and dry waste",
                                 "teaching households to segregate waste at source"),
    "check dam construction": ("small check dams on seasonal streams to recharge groundwater",
                               "check dams that hold monsoon run-off"),
    "clean cookstove distribution": ("distributing smokeless cookstoves to households",
                                     "replacing open fires with efficient cook stoves"),
    "vocational skill training": ("vocational courses in trades with local demand",
                                  "skill training linked to apprenticeships"),
    "self-help group microcredit": ("forming women's self-help groups with access to small loans",
                                    "microcredit through self-help groups for small enterprises"),
    "market linkage for artisans": ("connecting artisans to buyers through market linkage",
                                    "online and wholesale market access for craft producers"),
    "drip irrigation for smallholders": ("drip irrigation kits for small farmers",
                                         "helping smallholders switch to drip watering"),
    "dairy cooperative support": ("strengthening a village dairy cooperative with chilling equipment",
                                  "dairy training and milk collection for cooperative members"),
    "artisan design training": ("product design training for artisans",
                                "design workshops so artisans can make products buyers want"),
}


# Alternative phrasings the prompt picks from, so the corpus does not repeat
# catalogue names ("administration and monitoring" was in 48% of the pilot).
# Neither is a label: BERT's labels are the numbers and SDGs, not these words.
METRIC_PHRASES: dict[str, tuple[str, ...]] = {
    "attendance rate": ("attendance rate", "average daily attendance", "school attendance"),
    "learning outcome score": ("learning outcome score", "average assessment score",
                               "learning levels in reading and maths"),
    "antenatal coverage": ("antenatal coverage", "antenatal care coverage",
                           "the share of pregnant women receiving antenatal care"),
    "child immunisation rate": ("child immunisation rate", "full immunisation coverage among children",
                                "the share of fully vaccinated children"),
    "waterborne disease incidence": ("waterborne disease incidence", "the rate of waterborne illness",
                                     "cases of diarrhoea and other waterborne disease"),
    "households with safe water": ("households with safe water", "access to safe drinking water",
                                   "the share of households with safe drinking water"),
    "tree cover": ("tree cover", "green cover", "forest cover"),
    "waste diverted": ("waste diverted", "waste kept out of landfill"),
    "household monthly income": ("household monthly income", "monthly household earnings", "family income"),
    "women in paid work": ("women in paid work", "the share of women earning an income",
                           "women's participation in paid work"),
}

BUDGET_ITEM_PHRASES: dict[str, tuple[str, ...]] = {
    "learning materials": ("learning materials", "books and teaching aids", "classroom materials"),
    "teacher training": ("teacher training", "teacher workshops", "training of teachers"),
    "community mobilisers": ("community mobilisers", "field mobilisers", "community outreach staff"),
    "infrastructure upgrades": ("infrastructure upgrades", "building repairs", "civil works"),
    "medical supplies": ("medical supplies", "medicines and consumables", "drugs and supplies"),
    "health worker stipends": ("health worker stipends", "honoraria for health workers", "field staff stipends"),
    "mobile camp operations": ("mobile camp operations", "running the health camps", "camp logistics"),
    "diagnostic equipment": ("diagnostic equipment", "testing kits and equipment", "diagnostics"),
    "civil works": ("civil works", "construction", "masonry and fittings"),
    "materials and pipes": ("materials and pipes", "pipes and fittings", "hardware"),
    "community training": ("community training", "village trainings", "awareness and training"),
    "water quality testing": ("water quality testing", "water testing", "lab testing of water"),
    "saplings and materials": ("saplings and materials", "nursery stock", "plants and inputs"),
    "field staff": ("field staff", "project staff", "field team salaries"),
    "community engagement": ("community engagement", "village meetings", "outreach"),
    "survival monitoring": ("survival monitoring", "plant survival checks", "monitoring and maintenance"),
    "training costs": ("training costs", "training", "course fees"),
    "equipment and inputs": ("equipment and inputs", "tools and raw materials", "equipment"),
    "market linkage": ("market linkage", "marketing and buyer connections", "market access"),
    "working capital support": ("working capital support", "working capital", "seed capital"),
    ADMIN_BUDGET_ITEM: (ADMIN_BUDGET_ITEM, "admin and reporting", "overheads and monitoring", "management costs"),
}
