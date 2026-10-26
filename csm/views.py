"""Data shaping for the dashboard (no Streamlit here, so it can be tested)."""

import json

import pandas as pd

from .config import AS_OF, health_band
from .db import load_tables, read
from .signals import SEVERITY_POINTS

READY, CHECK, FIX = "Ready", "Check first", "Fix value first"


def readiness(health):
    if health >= 75:
        return READY
    if health >= 60:
        return CHECK
    return FIX


def load(conn):
    data = load_tables(conn, ["accounts", "regions", "partners", "modules", "subscriptions", "usage_weekly",
                              "otc_weekly", "module_kpi_weekly", "contacts", "reviews", "tickets", "signals", "devices"])
    data["health"] = read(conn, "SELECT * FROM health_scores")
    metrics = read(conn, "SELECT account_id, data_json FROM account_metrics WHERE as_of = ?", (AS_OF.isoformat(),))
    data["metrics"] = {int(r.account_id): json.loads(r.data_json) for r in metrics.itertuples()}
    data["summary"] = account_summary(data)
    data["opportunities"] = opportunities(data)
    return data


def account_summary(data):
    acc = data["accounts"].merge(data["partners"][["id", "name"]].rename(columns={"id": "partner_id", "name": "partner"}),
                                 on="partner_id", how="left")
    current = data["health"][data["health"]["as_of"] == AS_OF.isoformat()].drop(columns="as_of")
    acc = acc.merge(current.rename(columns={"account_id": "id", "total": "health"}), on="id")
    sig = data["signals"].copy()
    sig["points"] = sig["severity"].map(SEVERITY_POINTS)
    risks = sig[sig["kind"] == "risk"].groupby("account_id").agg(risk_points=("points", "sum"), n_risks=("id", "count"))
    exp = sig[sig["kind"] == "expansion"].groupby("account_id").agg(n_expansion=("id", "count"))
    acc = acc.merge(risks, left_on="id", right_index=True, how="left").merge(exp, left_on="id", right_index=True, how="left")
    acc[["risk_points", "n_risks", "n_expansion"]] = acc[["risk_points", "n_risks", "n_expansion"]].fillna(0).astype(int)
    m = data["metrics"]
    acc["arr_eur"] = acc["id"].map(lambda i: m[i]["arr_eur"])
    acc["days_to_renewal"] = acc["id"].map(lambda i: m[i]["days_to_renewal"])
    acc["country_arr_share"] = acc["id"].map(lambda i: m[i]["country_arr_share"])
    acc["band"] = acc["health"].map(health_band)
    critical = sig[(sig["kind"] == "risk") & (sig["severity"] == "critical")]["account_id"]
    acc["at_risk"] = (acc["health"] < 60) | acc["id"].isin(critical)
    acc["focus"] = acc["id"].map(focus_areas(sig))
    acc["focus"] = acc["focus"].fillna("—")
    # Same problem ranks higher where one account carries much of the region (Denmark).
    acc["priority"] = (acc["risk_points"] * (1 + 2 * acc["country_arr_share"])).round(1)
    return acc


AREAS = ["Security", "Capacity", "Reliability"]
SOFTWARE = ["ASSET", "NFM", "OTC", "SIEM", "MDR", "DGM", "LM", "PRM", "SEM"]
# Which customer types a module fits (others show as "not relevant" on the coverage map).
FIT = {
    "NFM": {"DSO", "TSO", "Municipal utility"},
    "DGM": {"DSO", "TSO", "Municipal utility"},
    "LM": {"Charge point operator", "Industrial", "Data center"},
    "PRM": {"Generator", "Industrial", "Data center"},
}


def focus_areas(sig):
    """The problem area with the most pressure per account: risk severity points, plus half for opportunities."""
    s = sig[sig["area"].isin(AREAS)].copy()
    if s.empty:
        return {}
    s["w"] = s["points"] * s["kind"].map({"risk": 1.0, "expansion": 0.5})
    best = s.groupby(["account_id", "area"])["w"].sum().reset_index().sort_values("w", ascending=False)
    return best.drop_duplicates("account_id").set_index("account_id")["area"].to_dict()


def coverage(data):
    """Account x module grid: used well / not delivering / opportunity / not used / not relevant."""
    s = data["summary"]
    opp = data["opportunities"]
    rows = []
    for a in s.itertuples():
        m = data["metrics"][a.id]
        for code in SOFTWARE:
            relevant = a.segment in FIT.get(code, {a.segment})
            o = opp[(opp["account_id"] == a.id) & (opp["module_code"] == code)] if not opp.empty else opp
            if m.get(f"has_{code}"):
                score = m["module_health"].get(code)
                state = "Used well" if score is None or score >= 70 else "Not delivering"
            elif not o.empty:
                state, score = "Opportunity", None
            else:
                state, score = ("Not used" if relevant else "Not relevant"), None
            rows.append({"account_id": a.id, "account": a.name, "country": a.country, "module_code": code,
                         "state": state, "score": score,
                         "value": int(o["est_value_eur"].iloc[0]) if not o.empty else None})
    return pd.DataFrame(rows)


def opportunities(data):
    """One row per account and suggested module, merging rules that point the same way."""
    sig = data["signals"][data["signals"]["kind"] == "expansion"]
    if sig.empty:
        return pd.DataFrame()
    summary = data["summary"].set_index("id")
    modules = data["modules"].set_index("code")
    rows = []
    for (acc_id, code), g in sig.groupby(["account_id", "module_code"]):
        acc = summary.loc[acc_id]
        rows.append({
            "account_id": acc_id,
            "account": acc["name"],
            "country": acc["country"],
            "channel": acc["channel"],
            "partner": acc["partner"],
            "health": acc["health"],
            "readiness": readiness(acc["health"]),
            "module_code": code,
            "module": "More sites or users" if code == "BASE" else modules.loc[code, "name"],
            "kind": "Software" if code == "BASE" else modules.loc[code, "kind"],
            "area": g["area"].iloc[0],
            "est_value_eur": int(g["est_value_eur"].max()),
            "titles": list(g["title"]),
            "reasons": list(g["reason"]),
            "playbooks": list(g["playbook"]),
            "rule_ids": list(g["rule_id"]),
        })
    order = {READY: 0, CHECK: 1, FIX: 2}
    df = pd.DataFrame(rows)
    df["_order"] = df["readiness"].map(order)
    return df.sort_values(["_order", "est_value_eur"], ascending=[True, False]).drop(columns="_order")


def region_summary(data):
    s = data["summary"]
    opp = data["opportunities"]
    rows = []
    for r in data["regions"].itertuples():
        acc = s[s["country"] == r.country]
        arr = acc["arr_eur"].sum()
        o = opp[opp["country"] == r.country] if not opp.empty else opp
        rows.append({
            "country": r.country,
            "name": r.name,
            "nis2_status": r.nis2_status,
            "nis2_note": r.nis2_note,
            "market_note": r.market_note,
            "grid_pressure": r.grid_pressure,
            "grid_note": r.grid_note,
            "grid_accounts": int(data["accounts"].loc[data["accounts"]["country"] == r.country, "grid_constrained"].sum()),
            "accounts": len(acc),
            "arr_eur": int(arr),
            "health_arr_weighted": round((acc["health"] * acc["arr_eur"]).sum() / arr, 1) if arr else None,
            "arr_at_risk": int(acc.loc[acc["at_risk"], "arr_eur"].sum()),
            "top_account_share": round(acc["arr_eur"].max() / arr, 3) if arr else None,
            "partner_share": round(acc.loc[acc["channel"] == "Partner", "arr_eur"].sum() / arr, 3) if arr else None,
            "open_risks": int(acc["n_risks"].sum()),
            "expansion_eur": int(o["est_value_eur"].sum()) if not o.empty else 0,
            "expansion_ready_eur": int(o.loc[o["readiness"] == READY, "est_value_eur"].sum()) if not o.empty else 0,
        })
    return pd.DataFrame(rows)


def sales_note(opp, metrics):
    """Short handover text for Sales: context first, not a pitch."""
    lines = [
        f"Account: {opp['account']} ({opp['country']}, {metrics['segment']}, ARR €{metrics['arr_eur']:,.0f})",
        f"Suggested next step: {opp['module']} (estimated €{opp['est_value_eur']:,.0f} per year)",
        f"Health: {opp['health']:.0f} ({opp['readiness'].lower()})",
        "Why now:",
        *[f"  - {r}" for r in opp["reasons"]],
        f"Renewal in {metrics['days_to_renewal']} days.",
    ]
    if isinstance(opp["partner"], str):
        lines.append(f"Partner-led account: align with {opp['partner']} before contacting the customer.")
    return "\n".join(lines)


# --- The CSM's own input (journal) ----------------------------------------------------

def journal_state(jconn, data):
    """Decisions, notes, assessments and plans, plus the decision status of every signal."""
    from . import journal

    decisions = [dict(r) for r in jconn.execute("SELECT * FROM decisions ORDER BY created_on DESC, id DESC")]
    sig = data["signals"].copy()
    statuses = [journal.signal_status(decisions, r.account_id, r.rule_id) for r in sig.itertuples()]
    sig["status"] = [s for s, _ in statuses]
    sig["decision_id"] = [d["id"] if d else None for _, d in statuses]
    names = data["accounts"].set_index("id")["name"]
    dec = pd.DataFrame(decisions)
    if not dec.empty:
        dec["account"] = dec["account_id"].map(names)
    notes = pd.DataFrame([dict(r) for r in jconn.execute("SELECT * FROM notes ORDER BY written_on DESC")])
    assessments = pd.DataFrame([dict(r) for r in jconn.execute(
        "SELECT * FROM assessments ORDER BY written_on DESC, id DESC")])
    latest = assessments.drop_duplicates("account_id").set_index("account_id") if not assessments.empty else assessments
    plans = {r["account_id"]: dict(r) for r in jconn.execute("SELECT * FROM account_plans")}
    return {"decisions": dec, "signals": sig, "notes": notes, "assessments": assessments,
            "assessment": latest, "plans": plans}


def needs_decision(state):
    return state["signals"][state["signals"]["status"] == "Needs decision"]


def effectiveness(state, data, weeks_after=4):
    """Health change from the week an action started to `weeks_after` weeks later."""
    dec = state["decisions"]
    if dec.empty:
        return pd.DataFrame()
    done = dec[(dec["status"] == "done") & ~dec["decision"].isin(["Monitor", "Dismiss"])]
    h = data["health"]
    rows = []
    for d in done.itertuples():
        hist = h[h["account_id"] == d.account_id].sort_values("as_of")
        before = hist[hist["as_of"] <= d.created_on]
        after_day = (pd.Timestamp(d.created_on) + pd.Timedelta(weeks=weeks_after)).date().isoformat()
        after = hist[hist["as_of"] <= after_day]
        if before.empty or after.empty or after["as_of"].iloc[-1] <= before["as_of"].iloc[-1]:
            continue
        rows.append({"decision": d.decision, "outcome": d.outcome,
                     "health_change": after["total"].iloc[-1] - before["total"].iloc[-1]})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.groupby("decision").agg(
        actions=("outcome", "count"),
        health_change=("health_change", "mean"),
        helped=("outcome", lambda o: (o.isin(["Solved", "Improved"])).mean()),
    ).reset_index().sort_values("helped", ascending=False)


def main_contact(data, account_id):
    """Champion if still there, otherwise the sponsor, otherwise anyone still at the customer."""
    c = data["contacts"]
    c = c[(c["account_id"] == account_id) & c["left_on"].isna()]
    for flag in ("is_champion", "is_sponsor"):
        hit = c[c[flag] == 1]
        if not hit.empty:
            return hit.iloc[0]
    return c.iloc[0] if not c.empty else None
