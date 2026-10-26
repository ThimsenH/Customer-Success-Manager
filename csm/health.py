"""Health score: four parts, each 0-100, weighted into a total.

Deliberately simple and explainable: every part is a short formula over metrics
the CSM can show the customer. Weights live in config.HEALTH_WEIGHTS.
"""

from . import catalog
from .config import HEALTH_WEIGHTS, WEAKEST_PART_MARGIN


def _clamp(x):
    return max(0.0, min(1.0, x)) * 100


def _avg(parts):
    """Weighted average over the parts that have data."""
    present = [(score, w) for score, w in parts if score is not None]
    if not present:
        return None
    return sum(s * w for s, w in present) / sum(w for _, w in present)


def onboarding(m):
    ratio = m["device_online_ratio"]
    return 100.0 if ratio is None else _clamp(ratio / 0.9)


def adoption(m):
    util = m["license_utilization"]
    change = m["usage_change_pct"]
    top = m["top_user_share"]
    return _avg([
        (None if util is None else _clamp(util / 0.75), 0.4),                # 75% of licences active = full marks
        (None if change is None else _clamp(1 + change / 0.4), 0.35),        # -40% or worse = zero
        (None if top is None else _clamp((0.9 - top) / 0.5), 0.25),          # one person doing 90% = zero
    ]) or 0.0


def otc_outcome(m):
    cov = m["inventory_coverage"]
    unack = m["crit_vulns_unack"]
    mttp = m["mttp_days"]
    return _avg([
        (None if cov is None else _clamp(cov / 0.9), 1.0),
        (None if unack is None else _clamp(1 - unack / 20), 1.0),
        (None if mttp is None else _clamp((90 - mttp) / 60), 1.0),         # 30 days = full, 90 days = zero
    ])


def module_scores(m):
    """Outcome score (0-100) per subscribed module: OT Companion from its own data, the others from catalog KPIs."""
    scores = {}
    if m["has_OTC"]:
        scores["OTC"] = otc_outcome(m)
    for module, values in m.get("module_kpis", {}).items():
        kpis = {k["id"]: k for k in catalog.kpis_for(module)}
        scores[module] = _avg([(catalog.score(kpis[kid], v), 1.0) for kid, v in values.items()])
    return {k: round(v, 1) for k, v in scores.items() if v is not None}


def outcomes(m):
    """Alerts acknowledged, plus the modules' outcome scores: half the ARR-weighted average,
    half the weakest module, so one module that isn't delivering can't hide behind the others."""
    ack = m["ack_rate"]
    parts = [(None if ack is None else _clamp((ack - 0.4) / 0.5), 1.0)]
    scores = module_scores(m)
    weights = {k: m["module_arr"].get(k, 0) for k in scores}
    if scores and sum(weights.values()):
        weighted = sum(scores[k] * weights[k] for k in scores) / sum(weights.values())
        parts.append(((weighted + min(scores.values())) / 2, 3.0))
    return _avg(parts) or 0.0


def relationship(m):
    support = 1 - 0.25 * m["crit_tickets_open"] - 0.05 * max(0, m["tickets_90d"] - 3)
    nps = m["nps_latest"]
    return _avg([
        (_clamp((270 - m["days_since_review"]) / 180), 0.3),               # within 90 days = full
        (100.0 if m["sponsor_present"] else 30.0, 0.2),
        (_clamp(support), 0.25),
        (70.0 if nps is None else nps * 10.0, 0.15),
        (100.0 if m["objectives_documented"] else 60.0, 0.1),
    ])


def score(m):
    parts = {
        "onboarding": onboarding(m),
        "adoption": adoption(m),
        "outcomes": outcomes(m),
        "relationship": relationship(m),
    }
    weighted = sum(parts[k] * w for k, w in HEALTH_WEIGHTS.items())
    # A strong part cannot hide a broken one: the total stays within
    # WEAKEST_PART_MARGIN points of the weakest part.
    total = min(weighted, min(parts.values()) + WEAKEST_PART_MARGIN)
    return {"total": round(total, 1), **{k: round(v, 1) for k, v in parts.items()}}
