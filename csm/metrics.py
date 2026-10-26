"""Per-account metrics as of a given date.

Every metric here is something a CSM could explain to a customer. The rules in
rules.toml and the health score in health.py only read from this dictionary.
"""

from datetime import date, timedelta

import pandas as pd

from . import catalog

from .config import AS_OF as SNAPSHOT_DATE  # date the device snapshot was taken

# Shown on the "How it works" page: metric -> (source system, meaning)
METRIC_DOCS = {
    "days_to_renewal": ("CRM", "Days until the subscription term renews"),
    "arr_eur": ("Subscription Manager", "Annual recurring revenue of active subscriptions"),
    "country_arr_share": ("Subscription Manager", "Account's share of its country's ARR (concentration)"),
    "device_online_ratio": ("Platform: tenant", "Connected Devices online in the last 7 days ÷ contracted"),
    "devices_offline": ("Platform: tenant", "Devices that were onboarded but have been silent for more than 7 days"),
    "license_utilization": ("Platform: SiemensID", "Weekly active users ÷ licensed users (last 4 weeks)"),
    "usage_change_pct": ("Platform: SiemensID", "Active users, last 4 weeks vs. 9–12 weeks ago"),
    "top_user_share": ("Platform: SiemensID", "Share of all activity coming from the single busiest user"),
    "new_sites_90d": ("Platform: tenant", "Increase in active sites over the last 12 weeks"),
    "ack_rate": ("Platform: modules", "Alarms and alerts acknowledged within target time"),
    "inventory_coverage": ("OT Companion", "OT assets inventoried ÷ assets the customer expects to have"),
    "crit_vulns_open": ("OT Companion", "Open critical/high CVEs affecting the customer's own devices"),
    "crit_vulns_unack": ("OT Companion", "Of those, alerts nobody has acknowledged"),
    "mttp_days": ("OT Companion", "Mean time to patch critical vulnerabilities (rolling 90 days)"),
    "patch_completion": ("OT Companion", "Patch tasks completed ÷ created (last 12 weeks)"),
    "tickets_90d": ("Support desk", "Tickets opened in the last 90 days"),
    "crit_tickets_open": ("Support desk", "Open tickets with priority Critical"),
    "days_since_review": ("CRM", "Days since the last success review or QBR (any participant)"),
    "days_since_direct_touch": ("CRM", "Days since Siemens itself last met the customer"),
    "objectives_documented": ("CRM", "Latest review has written, agreed objectives"),
    "sponsor_present": ("CRM", "An executive sponsor is named and still at the customer"),
    "champion_left_days": ("CRM", "Days since the champion left (empty if still there)"),
    "nps_latest": ("Survey tool", "Latest NPS answer (0–10)"),
    "downgrade_180d": ("Subscription Manager", "Downgrade or cancellation in the last 180 days"),
    "nis2_status": ("Reference: regulation", "NIS2 status in the account's country"),
}


def _days_between(later, earlier):
    return (later - earlier).days


def _by_account(df):
    return {k: g for k, g in df.groupby("account_id")} if len(df) else {}


class MetricContext:
    """Holds all source tables once, grouped by account, so metrics can be
    computed for many accounts and dates cheaply."""

    def __init__(self, tables, touches=()):
        self.accounts = tables["accounts"].set_index("id")
        self.regions = tables["regions"].set_index("country")
        self.partners = tables["partners"].set_index("id")
        self.groups = {}
        for name in ["subscriptions", "subscription_events", "devices", "usage_weekly", "otc_weekly",
                     "module_kpi_weekly", "tickets", "reviews", "surveys", "contacts"]:
            df = tables[name].copy()
            for col in ["start_date", "end_date", "date", "onboarded_on", "last_seen", "week_start",
                        "opened_on", "closed_on", "left_on"]:
                if col in df.columns:
                    df[col] = df[col].map(lambda v: date.fromisoformat(v) if isinstance(v, str) else None)
            self.groups[name] = _by_account(df)
        # Add-ons (e.g. OT Companion features) count towards their parent module.
        mods = tables["modules"]
        self.parent = {r.code: (r.parent_code if isinstance(r.parent_code, str) else r.code) for r in mods.itertuples()}
        # Completed CSM actions (calls, visits, reviews) from the journal.
        self.touches = {}
        for t in touches:
            self.touches.setdefault(t["account_id"], []).append(t)

    def table(self, name, account_id):
        return self.groups[name].get(account_id, pd.DataFrame())

    def active_subscriptions(self, account_id, as_of):
        subs = self.table("subscriptions", account_id)
        if subs.empty:
            return subs
        mask = (subs["start_date"] <= as_of) & (subs["end_date"].isna() | (subs["end_date"] > as_of))
        return subs[mask]

    def arr(self, account_id, as_of):
        subs = self.active_subscriptions(account_id, as_of)
        return int(subs["annual_value_eur"].sum()) if not subs.empty else 0


def compute(ctx, account_id, as_of, country_arr=None):
    acc = ctx.accounts.loc[account_id]
    m = {
        "account_id": int(account_id),
        "name": acc["name"],
        "country": acc["country"],
        "segment": acc["segment"],
        "tier": acc["tier"],
        "channel": acc["channel"],
        "partner": ctx.partners.loc[acc["partner_id"], "name"] if pd.notna(acc["partner_id"]) else None,
        "nis2_in_scope": bool(acc["nis2_in_scope"]),
        "nis2_status": ctx.regions.loc[acc["country"], "nis2_status"],
        "size_factor": float(acc["size_factor"]),
        "is_grid_operator": acc["segment"] in ("DSO", "TSO", "Municipal utility"),
        "grid_constrained": bool(acc["grid_constrained"]),
        "grid_area": acc["grid_area"] if isinstance(acc["grid_area"], str) else None,
        "grid_pressure": ctx.regions.loc[acc["country"], "grid_pressure"],
    }

    # Commercial ------------------------------------------------------------------
    renewal = date.fromisoformat(acc["renewal_date"])
    m["days_to_renewal"] = _days_between(renewal, as_of)
    m["arr_eur"] = ctx.arr(account_id, as_of)
    if country_arr:
        m["country_arr_share"] = round(m["arr_eur"] / country_arr[acc["country"]], 3)
    subs = ctx.active_subscriptions(account_id, as_of)
    codes = set(subs["module_code"]) if not subs.empty else set()
    m["modules"] = sorted(codes)
    for code in ["ASSET", "NFM", "OTC", "OTC_VULN", "OTC_PATCH", "SIEM", "MDR", "SEM", "LM", "DGM", "PRM"]:
        m[f"has_{code}"] = code in codes
    events = ctx.table("subscription_events", account_id)
    recent = events[(events["date"] <= as_of) & (events["date"] > as_of - timedelta(days=180))] if not events.empty else events
    m["downgrade_180d"] = bool(not recent.empty and recent["event"].isin(["downgrade", "cancel"]).any())
    days_live = _days_between(as_of, date.fromisoformat(acc["contract_start"]))
    m["days_since_start"] = days_live

    # Onboarding --------------------------------------------------------------------
    contracted = int(subs.loc[subs["module_code"] == "BASE", "contracted_devices"].sum()) if not subs.empty else 0
    dev = ctx.table("devices", account_id)
    if not dev.empty:
        dev = dev[dev["onboarded_on"] <= as_of]
        # last_seen is a snapshot: for past dates, a device counts as online unless it went silent before then.
        silent = dev["last_seen"] < min(as_of, SNAPSHOT_DATE) - timedelta(days=7)
        online = int((~silent).sum())
        offline = int(silent.sum())
    else:
        online = offline = 0
    m["devices_contracted"] = contracted
    m["devices_online"] = online
    m["devices_offline"] = offline
    m["device_online_ratio"] = round(online / contracted, 3) if contracted else None

    # Adoption ----------------------------------------------------------------------
    usage = ctx.table("usage_weekly", account_id)
    if not usage.empty:
        usage = usage[usage["week_start"] < as_of]
    if not usage.empty:
        weekly = usage.groupby("week_start").agg(active_users=("active_users", "sum"),
                                                 active_sites=("active_sites", "max")).sort_index()
        last4 = weekly["active_users"].iloc[-4:].mean()
        base = weekly["active_users"].iloc[-12:-8].mean() if len(weekly) >= 12 else None
        licensed = int(subs["licensed_users"].sum()) if not subs.empty else 0
        m["active_users"] = round(float(last4), 1)
        m["licensed_users"] = licensed
        m["license_utilization"] = round(last4 / licensed, 3) if licensed else None
        m["usage_change_pct"] = round(last4 / base - 1, 3) if base else None
        recent_usage = usage[usage["week_start"] >= weekly.index[-min(4, len(weekly))]]
        weights = recent_usage["active_users"].clip(lower=1)
        m["top_user_share"] = round(float((recent_usage["top_user_share"] * weights).sum() / weights.sum()), 3)
        m["ack_rate"] = round(float(recent_usage["ack_rate"].mean()), 3)
        m["active_sites"] = int(weekly["active_sites"].iloc[-1])
        m["new_sites_90d"] = int(weekly["active_sites"].iloc[-1] - weekly["active_sites"].iloc[-13]) if len(weekly) >= 13 else 0
        m["usage_by_module"] = {code: int(g.sort_values("week_start")["active_users"].iloc[-4:].mean())
                                for code, g in recent_usage.groupby("module_code")}
    else:
        for key in ["active_users", "license_utilization", "usage_change_pct", "top_user_share", "ack_rate"]:
            m[key] = None
        m["licensed_users"] = 0
        m["active_sites"] = 0
        m["new_sites_90d"] = 0
        m["usage_by_module"] = {}

    # Module ARR (add-ons included in their parent), used to weight module health.
    weights = {}
    for r in subs.itertuples():
        parent = ctx.parent.get(r.module_code, r.module_code)
        weights[parent] = weights.get(parent, 0) + r.annual_value_eur
    m["module_arr"] = {k: int(v) for k, v in weights.items() if k != "BASE"}

    # Outcome KPIs of the other modules (catalog.toml): mean of the last 2 weeks ----------
    kpi_rows = ctx.table("module_kpi_weekly", account_id)
    if not kpi_rows.empty:
        kpi_rows = kpi_rows[kpi_rows["week_start"] < as_of]
    m["module_kpis"] = {}
    for kpi in catalog.kpis():
        name = catalog.metric_name(kpi)
        m[name] = None
        if kpi["module"] not in codes or kpi_rows.empty:
            continue
        series = kpi_rows[(kpi_rows["module_code"] == kpi["module"]) & (kpi_rows["kpi"] == kpi["id"])]
        if series.empty:
            continue
        values = series.sort_values("week_start")["value"]
        m[name] = round(float(values.iloc[-2:].mean()), 3)
        m["module_kpis"].setdefault(kpi["module"], {})[kpi["id"]] = m[name]

    # OT Companion outcomes -------------------------------------------------------------
    otc = ctx.table("otc_weekly", account_id)
    if not otc.empty:
        otc = otc[otc["week_start"] < as_of].sort_values("week_start")
    if m["has_OTC"] and not otc.empty:
        last = otc.iloc[-1]
        m["ot_assets_expected"] = int(acc["ot_assets_expected"])
        m["ot_assets_inventoried"] = int(last["assets_inventoried"])
        m["inventory_coverage"] = round(last["assets_inventoried"] / acc["ot_assets_expected"], 3)
        m["baseline_deviations_open"] = int(last["baseline_deviations_open"])
        if m["has_OTC_VULN"]:
            m["crit_vulns_open"] = int(last["crit_vulns_open"])
            m["crit_vulns_unack"] = int(last["crit_vulns_unack"])
            m["mttp_days"] = float(last["mttp_days"]) if pd.notna(last["mttp_days"]) else None
        else:
            m["crit_vulns_open"] = m["crit_vulns_unack"] = m["mttp_days"] = None
        tail = otc.iloc[-12:]
        created = tail["patch_tasks_created"].sum()
        m["patch_completion"] = round(tail["patch_tasks_completed"].sum() / created, 3) if created else None
    else:
        for key in ["inventory_coverage", "crit_vulns_open", "crit_vulns_unack", "mttp_days", "patch_completion",
                    "ot_assets_inventoried", "baseline_deviations_open"]:
            m[key] = None
        m["ot_assets_expected"] = int(acc["ot_assets_expected"])

    # Relationship and support ------------------------------------------------------------
    tickets = ctx.table("tickets", account_id)
    if not tickets.empty:
        tickets = tickets[tickets["opened_on"] <= as_of]
        is_open = tickets["closed_on"].isna() | (tickets["closed_on"] > as_of)
        m["tickets_90d"] = int((tickets["opened_on"] > as_of - timedelta(days=90)).sum())
        m["tickets_open"] = int(is_open.sum())
        m["crit_tickets_open"] = int((is_open & (tickets["priority"] == "Critical")).sum())
    else:
        m["tickets_90d"] = m["tickets_open"] = m["crit_tickets_open"] = 0

    reviews = ctx.table("reviews", account_id)
    if not reviews.empty:
        reviews = reviews[reviews["date"] <= as_of]
    # Logged success reviews count as reviews; every logged call or visit counts as direct contact.
    touches = [t for t in ctx.touches.get(int(account_id), []) if t["date"] <= as_of]
    logged = pd.DataFrame([{"date": t["date"], "siemens_present": 1, "objectives_documented": int(t["objectives_agreed"])}
                           for t in touches if t["is_review"]])
    if not logged.empty:
        reviews = pd.concat([reviews, logged], ignore_index=True) if not reviews.empty else logged
    if not reviews.empty:
        reviews = reviews.sort_values("date")
        m["days_since_review"] = _days_between(as_of, reviews["date"].iloc[-1])
        direct = reviews[reviews["siemens_present"] == 1]
        m["days_since_direct_touch"] = _days_between(as_of, direct["date"].iloc[-1]) if not direct.empty else days_live
        m["objectives_documented"] = bool(reviews["objectives_documented"].iloc[-1])
    else:
        m["days_since_review"] = m["days_since_direct_touch"] = days_live
        m["objectives_documented"] = False
    if touches:
        latest = max(t["date"] for t in touches)
        m["days_since_direct_touch"] = min(m["days_since_direct_touch"], _days_between(as_of, latest))

    contacts = ctx.table("contacts", account_id)
    still_there = contacts["left_on"].isna() | (contacts["left_on"] > as_of)
    m["sponsor_present"] = bool((contacts["is_sponsor"].astype(bool) & still_there).any())
    champ_left = contacts[contacts["is_champion"].astype(bool) & ~still_there]
    m["champion_left_days"] = _days_between(as_of, champ_left["left_on"].iloc[0]) if not champ_left.empty else None

    surveys = ctx.table("surveys", account_id)
    if not surveys.empty:
        surveys = surveys[surveys["date"] <= as_of].sort_values("date")
    m["nps_latest"] = int(surveys["nps"].iloc[-1]) if not surveys.empty else None
    return m


def compute_all(ctx, as_of):
    country_arr = {}
    for acc_id, acc in ctx.accounts.iterrows():
        country_arr[acc["country"]] = country_arr.get(acc["country"], 0) + ctx.arr(acc_id, as_of)
    country_arr = {k: v or 1 for k, v in country_arr.items()}
    return [compute(ctx, acc_id, as_of, country_arr) for acc_id in ctx.accounts.index]
