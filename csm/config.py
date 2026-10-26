"""Shared constants."""

from datetime import date

# The demo runs "as of" a fixed date so results are the same on every run.
AS_OF = date(2026, 10, 26)  # a Monday
HISTORY_WEEKS = 52          # telemetry history generated
HEALTH_HISTORY_WEEKS = 26   # weeks of health score history computed
SEED = 42

HEALTH_WEIGHTS = {"onboarding": 0.15, "adoption": 0.35, "outcomes": 0.30, "relationship": 0.20}
WEAKEST_PART_MARGIN = 15    # total health is at most this many points above the weakest part

# (lower bound, label, status role)
HEALTH_BANDS = [
    (75, "Healthy", "good"),
    (60, "Watch", "warning"),
    (45, "At risk", "serious"),
    (0, "Critical", "critical"),
]


def health_band(score):
    for lower, label, _ in HEALTH_BANDS:
        if score >= lower:
            return label
    return HEALTH_BANDS[-1][1]
