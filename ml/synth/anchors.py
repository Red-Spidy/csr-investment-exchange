"""Real-world figures the synthetic world is anchored to.

Every constant here is either sourced or explicitly marked as an assumption.
The data card (ml/datasets/README.md) repeats them for the report.
"""

# Share of CSR spend by sector.
#   RED Lab, FY24, 1,871 listed companies (Rs 29,987 cr): education 33%,
#   healthcare 23%, rural development 17%, environment 7%, livelihood 6%.
#   Water and sanitation ~5.5%: National CSR Portal FY24 puts health and
#   sanitation at Rs 9,087.41 cr, of which healthcare is Rs 7,150.81 cr, against
#   a Rs 34,908.75 cr total.
# Rural development is folded into livelihood, the same pooling the earlier
# IEG impact work used. The five shares are renormalised to sum to 1.
_RAW_SECTOR_SHARE = {
    "education": 33.0,
    "healthcare": 23.0,
    "livelihood": 6.0 + 17.0,
    "environment": 7.0,
    "water_sanitation": 5.5,
}
SECTOR_SHARE = {
    sector: share / sum(_RAW_SECTOR_SHARE.values())
    for sector, share in _RAW_SECTOR_SHARE.items()
}
SECTORS = tuple(SECTOR_SHARE)

# Project outcome = fraction of the claimed improvement actually delivered.
# Calibrated to IEG World Bank project ratings (12,752 rated projects, mapped
# to [0,1]): mean 0.616, SD 0.243. Source: docs/impact-model-findings.md,
# commit cffde19.
OUTCOME_MEAN = 0.616
OUTCOME_SD = 0.243

# Each sector's mean outcome minus the global mean, from the same IEG ratings
# (education 0.6510, healthcare 0.5773, water 0.5927, environment 0.5992,
# livelihood pooled 0.5964; global 0.6156). Sector moves the mean by a few
# points only -- project-level variation dominates, as in the real data.
SECTOR_OUTCOME_OFFSET = {
    "education": +0.0354,
    "healthcare": -0.0383,
    "water_sanitation": -0.0229,
    "environment": -0.0164,
    "livelihood": -0.0192,
}

# ASSUMPTION: no public figure exists for the share of CSR-funded NGOs that
# misuse funds. 6% gives every split enough fraudulent NGOs to evaluate on
# while keeping fraud rare, which is what Isolation Forest assumes.
FRAUD_RATE = 0.06

# ASSUMPTION: a spread of states with significant CSR activity, sampled
# uniformly. Districts are real districts of each state.
STATE_DISTRICTS = {
    "Maharashtra": ("Yavatmal", "Nandurbar", "Gadchiroli"),
    "Rajasthan": ("Barmer", "Jaisalmer", "Banswara"),
    "Bihar": ("Gaya", "Purnia", "Araria"),
    "Uttar Pradesh": ("Bahraich", "Shravasti", "Sonbhadra"),
    "Madhya Pradesh": ("Jhabua", "Barwani", "Mandla"),
    "Odisha": ("Bargarh", "Koraput", "Kalahandi"),
    "Jharkhand": ("Pakur", "Sahibganj", "Gumla"),
    "Karnataka": ("Uttara Kannada", "Raichur", "Yadgir"),
    "Tamil Nadu": ("Ramanathapuram", "Dharmapuri", "Virudhunagar"),
    "Gujarat": ("Dahod", "Narmada", "Kutch"),
    "Assam": ("Dhubri", "Goalpara", "Barpeta"),
    "Telangana": ("Adilabad", "Jogulamba Gadwal", "Bhadradri Kothagudem"),
}
STATES = tuple(STATE_DISTRICTS)
