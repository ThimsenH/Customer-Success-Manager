"""Module KPI catalog (catalog.toml): loading, scoring and formatting."""

import tomllib
from functools import lru_cache
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent / "catalog.toml"


@lru_cache(maxsize=1)
def kpis():
    with open(CATALOG_PATH, "rb") as f:
        return tuple(tomllib.load(f)["kpi"])


def kpis_for(module):
    return [k for k in kpis() if k["module"] == module]


def modules():
    return sorted({k["module"] for k in kpis()})


def metric_name(kpi):
    """Name under which the KPI appears in the metrics and rules."""
    return f"kpi_{kpi['module']}_{kpi['id']}"


def score(kpi, value):
    """0-100: how close the value is to the target (100 = at or beyond target)."""
    if value is None:
        return None
    if kpi["better"] == "higher":
        ratio = value / kpi["target"]
    else:
        ratio = 1.0 if value <= 0 else kpi["target"] / value
    # At target = 100, half of target (or twice the target for "lower") = 0.
    return max(0.0, min(1.0, (ratio - 0.5) / 0.5)) * 100


def fmt(kpi, value):
    if value is None:
        return "n/a"
    unit = kpi["unit"]
    if unit == "share":
        return f"{value:.0%}"
    if unit == "minutes":
        return f"{value:.0f} min"
    if unit == "hours":
        return f"{value:.1f} h"
    if unit == "per_week":
        return f"{value:.1f} / week"
    return f"{value:.0f}"
