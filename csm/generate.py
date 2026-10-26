"""Synthetic Nordic portfolio for Electrification X.

Every account is fictional. Each one is built around a "scenario" (a story the
radar should catch) by tweaking a handful of knobs on top of healthy defaults.
The random seed is fixed, so every run produces the same data.
"""

import random
from datetime import date, timedelta

from .config import AS_OF, HISTORY_WEEKS, SEED
from .db import init_db, insert_rows

REGIONS = [
    dict(country="NO", name="Norway", nis2_status="Expected", nis2_in_force=None,
         nis2_note="NIS1 applies (digitalsikkerhetsloven). NIS2 expected 2026, scope ~600 → ~5,000 organisations. Verify current status.",
         market_note="Many customers and many open opportunities right now. The regulatory push is still ahead."),
    dict(country="DK", name="Denmark", nis2_status="In force", nis2_in_force="2025-07-01",
         nis2_note="Energy-sector act in force 7 Mar 2025, general act 1 Jul 2025.",
         market_note="Only a few, large customers. Losing one would hit the region hard."),
    dict(country="SE", name="Sweden", nis2_status="In force", nis2_in_force="2026-01-15",
         nis2_note="Cybersäkerhetslag (2025:1506) in force 15 Jan 2026.",
         market_note="Customers are often reached only through partners, so Siemens sees less of the relationship directly."),
    dict(country="FI", name="Finland", nis2_status="In force", nis2_in_force="2025-04-08",
         nis2_note="Kyberturvallisuuslaki 124/2025 in force 8 Apr 2025.",
         market_note="No specific insight yet. A market to learn."),
]

MODULES = [
    dict(code="BASE", name="Base Package (tenant)", cluster="Platform", parent_code=None, list_price_eur=12000,
         description="Tenant and Connected Devices. Required for every feature set."),
    dict(code="ASSET", name="Asset Management", cluster="Reliability", parent_code=None, list_price_eur=30000,
         description="Asset transparency and condition monitoring at MV/LV level."),
    dict(code="NFM", name="Network Fault Management", cluster="Reliability", parent_code=None, list_price_eur=25000,
         description="Fault localisation and fault records across the network."),
    dict(code="OTC", name="OT Companion: OT Asset Transparency", cluster="Security", parent_code=None, list_price_eur=40000,
         description="OT inventory, baseline management, product catalogue (base feature)."),
    dict(code="OTC_VULN", name="OT Companion: Vulnerability Management", cluster="Security", parent_code="OTC", list_price_eur=15000,
         description="CVE-assessed vulnerability alerts for the customer's own devices (optional feature)."),
    dict(code="OTC_PATCH", name="OT Companion: Patch Workflow", cluster="Security", parent_code="OTC", list_price_eur=15000,
         description="IEC 62443-compliant patch task workflow (optional feature)."),
    dict(code="SIEM", name="SIEM as a Service", cluster="Security", parent_code=None, list_price_eur=60000,
         description="Detection and response. Pairs with OT Companion via log collectors."),
    dict(code="MDR", name="Managed Detection & Response", cluster="Security", parent_code=None, list_price_eur=80000,
         description="24/7 monitoring and incident analysis as a managed service."),
    dict(code="SEM", name="Sustainability / Energy Management", cluster="Capacity", parent_code=None, list_price_eur=20000,
         description="Energy, cost and emissions across sites."),
    dict(code="LM", name="Load Management", cluster="Capacity", parent_code=None, list_price_eur=25000,
         description="EV charging networks with dynamic load management."),
    dict(code="DGM", name="Distribution Grid Management", cluster="Capacity", parent_code=None, list_price_eur=35000,
         description="Autonomous feeder management for MV/LV distribution."),
    dict(code="PRM", name="Power Resource Management", cluster="Capacity", parent_code=None, list_price_eur=30000,
         description="Monitoring and control of industrial, PV and hybrid plants."),
]

# Modules with their own user activity (add-ons count towards their parent).
USAGE_MODULES = {"ASSET", "NFM", "OTC", "SIEM", "SEM", "LM", "DGM", "PRM"}

PARTNERS = [
    dict(id=1, name="Brokraft Systems AB", country="SE"),
    dict(id=2, name="Ljusnet Integration AB", country="SE"),
    dict(id=3, name="Kaamos Grid Partners Oy", country="FI"),
]

# Healthy defaults. Each account overrides only what makes its story.
DEFAULTS = dict(
    years=2,                 # contract years so far (sets contract start)
    renewal_in=180,          # days until renewal
    util=0.65,               # share of licensed users active in a week
    decline=None,            # (weeks, end multiplier): usage falls over the last N weeks
    top_share=0.32,          # share of activity from the busiest user
    site_cov=0.8,            # share of the estate's sites active
    new_sites=0,             # sites added in the last 12 weeks
    device_ratio=0.84,       # connected devices online / contracted
    offline=0,               # devices that dropped offline 10-40 days ago
    ack_rate=0.9,
    coverage=0.82,           # OT assets inventoried / expected
    crit_open=6,             # open critical/high CVEs on own devices
    unack_share=0.1,
    mttp=24,                 # mean time to patch, days
    tickets_90d=3,
    crit_open_tickets=0,
    review_gap=60,           # days since the last review
    objectives=True,
    partner_only_gap=None,   # days since Siemens itself last met the customer
    sponsor_left=None,       # days ago
    champion_left=None,      # days ago
    nps=8,
    downgrade=None,          # days ago
    started=None,            # days ago, for brand-new customers
)

ACCOUNTS = [
    # Norway: many customers, many opportunities
    dict(name="Fjordlys Nett AS", country="NO", segment="DSO", tier="Core", size=1.4, sites=60,
         mods=["BASE", "ASSET", "OTC", "OTC_VULN", "OTC_PATCH"], scenario="Expander: device limit and new sites",
         util=0.78, coverage=0.86, device_ratio=0.98, new_sites=4, renewal_in=200),
    dict(name="Kystlinje Nett AS", country="NO", segment="DSO", tier="Core", size=1.1, sites=45,
         mods=["BASE", "ASSET", "OTC", "OTC_VULN"], scenario="Silent churner before renewal",
         decline=(16, 0.35), renewal_in=55, review_gap=190, nps=6, ack_rate=0.72),
    dict(name="Viddekraft AS", country="NO", segment="Municipal utility", tier="Growth", size=0.8, sites=30,
         mods=["BASE", "ASSET"], scenario="Asset Management only, OT Companion is the next step"),
    dict(name="Nordstjerne Nett AS", country="NO", segment="DSO", tier="Core", size=1.0, sites=40,
         mods=["BASE", "OTC"], scenario="Stalled onboarding", started=150, years=1, renewal_in=215,
         util=0.28, device_ratio=0.22, coverage=0.25, review_gap=95),
    dict(name="Isbre Kraft AS", country="NO", segment="Generator", tier="Core", size=1.2, sites=25,
         mods=["BASE", "ASSET", "OTC", "OTC_VULN"], scenario="Vulnerability alerts nobody triages",
         crit_open=34, unack_share=0.8, mttp=95, ack_rate=0.45),
    dict(name="Polarlading AS", country="NO", segment="Charge point operator", tier="Growth", size=0.9, sites=35,
         mods=["BASE", "LM"], scenario="Growing charging network", new_sites=5, device_ratio=0.93, util=0.72),
    dict(name="Trollvegg Nett AS", country="NO", segment="DSO", tier="Core", size=1.3, sites=55,
         mods=["BASE", "ASSET", "OTC", "OTC_VULN", "OTC_PATCH"], scenario="Mature OT Companion, no SIEM",
         coverage=0.97, util=0.7),
    dict(name="Skjærgård Nett AS", country="NO", segment="DSO", tier="Growth", size=0.6, sites=18,
         mods=["BASE", "OTC", "OTC_VULN"], scenario="Everything depends on one person",
         top_share=0.86, util=0.3),
    dict(name="Sørkapp Nett AS", country="NO", segment="DSO", tier="Core", size=1.0, sites=38,
         mods=["BASE", "OTC", "OTC_VULN"], scenario="Many CVEs, patching tracked outside the tool",
         crit_open=22, unack_share=0.15, mttp=52),
    dict(name="Ishavet Datasenter AS", country="NO", segment="Data center", tier="Core", size=1.5, sites=4,
         mods=["BASE", "ASSET", "PRM", "SEM"], scenario="Healthy, NIS2 in scope without OT Companion"),
    dict(name="Fonnfjell Energi AS", country="NO", segment="Municipal utility", tier="Growth", size=0.7, sites=22,
         mods=["BASE", "ASSET", "NFM"], scenario="Unhappy: support problems, no reviews",
         tickets_90d=11, crit_open_tickets=3, review_gap=215, nps=4, objectives=False, ack_rate=0.66, util=0.45),

    # Denmark: few, large customers
    dict(name="Sundlys Elnet A/S", country="DK", segment="DSO", tier="Strategic", size=3.4, sites=140,
         mods=["BASE", "ASSET", "OTC", "OTC_VULN", "OTC_PATCH", "SIEM", "DGM"], scenario="Strategic, healthy, rolling out", coverage=0.94, device_ratio=0.95,
         new_sites=3, years=3, renewal_in=240, util=0.7),
    dict(name="Hedeland Net A/S", country="DK", segment="DSO", tier="Strategic", size=3.0, sites=120,
         mods=["BASE", "ASSET", "OTC", "OTC_VULN", "NFM"], scenario="Key account with early warnings",
         sponsor_left=70, review_gap=220, decline=(10, 0.75), renewal_in=120, nps=6, years=3),
    dict(name="Vesterhav Energi A/S", country="DK", segment="Generator", tier="Strategic", size=2.6, sites=30,
         mods=["BASE", "ASSET", "PRM", "SEM"], scenario="Strategic, healthy, NIS2 in force without OT Companion",
         years=3, renewal_in=300),

    # Sweden: often through partners
    dict(name="Älvdal Nät AB", country="SE", segment="DSO", tier="Core", size=1.2, sites=50, partner=1,
         mods=["BASE", "ASSET", "OTC", "OTC_VULN"], scenario="Partner-led, Siemens has no direct view",
         partner_only_gap=260, ack_rate=0.7, crit_open=12, unack_share=0.6, mttp=58),
    dict(name="Ekskog Elnät AB", country="SE", segment="DSO", tier="Core", size=1.0, sites=42, partner=1,
         mods=["BASE", "ASSET"], scenario="Partner-led, NIS2 in force without OT Companion", partner_only_gap=120),
    dict(name="Granit Kraftnät AB", country="SE", segment="DSO", tier="Core", size=1.6, sites=70,
         mods=["BASE", "ASSET", "OTC", "OTC_VULN", "OTC_PATCH"], scenario="Mature OT Companion, no SIEM (direct)",
         coverage=0.95),
    dict(name="Laddstig AB", country="SE", segment="Charge point operator", tier="Growth", size=1.2, sites=28, partner=2,
         mods=["BASE", "LM"], scenario="Downgraded in the subscription store",
         downgrade=40, decline=(12, 0.45), util=0.8, partner_only_gap=300, nps=5, renewal_in=110),
    dict(name="Sjöbris Energi AB", country="SE", segment="Municipal utility", tier="Growth", size=0.7, sites=20, partner=2,
         mods=["BASE", "OTC"], scenario="Partner-run onboarding stalled", started=200, years=1, renewal_in=165,
         device_ratio=0.45, coverage=0.4, util=0.35, partner_only_gap=200),
    dict(name="Ekdala Industripark AB", country="SE", segment="Industrial", tier="Growth", size=0.9, sites=6,
         mods=["BASE", "SEM", "PRM"], scenario="Out of user licences", util=0.95),

    # Finland: no specific insight yet
    dict(name="Järvilaakso Verkko Oy", country="FI", segment="DSO", tier="Core", size=1.3, sites=58,
         mods=["BASE", "ASSET", "OTC", "OTC_VULN", "OTC_PATCH"], scenario="Healthy reference customer", coverage=0.88),
    dict(name="Revontuli Verkko Oy", country="FI", segment="DSO", tier="Core", size=1.1, sites=44,
         mods=["BASE", "OTC", "OTC_VULN"], scenario="Champion left, usage dropping",
         champion_left=45, renewal_in=140),
    dict(name="Tunturi Energia Oy", country="FI", segment="Generator", tier="Core", size=1.2, sites=16,
         mods=["BASE", "ASSET", "PRM"], scenario="NIS2 in force without OT Companion"),
    dict(name="Kuura Datakeskus Oy", country="FI", segment="Data center", tier="Growth", size=1.0, sites=3,
         mods=["BASE", "PRM", "SEM"], scenario="Near the device limit", device_ratio=0.97),
    dict(name="Koivu Teollisuus Oy", country="FI", segment="Industrial", tier="Growth", size=0.7, sites=5, partner=3,
         mods=["BASE", "SEM"], scenario="Low adoption close to renewal", util=0.15, renewal_in=80,
         partner_only_gap=190, nps=5, objectives=False),
]

FIRST_NAMES = {
    "NO": ["Ingrid", "Lars", "Kari", "Ola", "Silje", "Henrik", "Marte", "Eirik", "Hanne", "Jonas"],
    "DK": ["Mette", "Rasmus", "Sofie", "Mads", "Freja", "Anders", "Line", "Søren"],
    "SE": ["Elin", "Johan", "Karin", "Erik", "Maja", "Oskar", "Linnea", "Gustav"],
    "FI": ["Aino", "Mikko", "Laura", "Juha", "Emilia", "Antti", "Sanna", "Ville"],
}
LAST_NAMES = {
    "NO": ["Berg", "Haugen", "Lie", "Dahl", "Moen", "Strand", "Solberg", "Bakken"],
    "DK": ["Nielsen", "Jensen", "Holm", "Lund", "Krogh", "Vestergaard"],
    "SE": ["Lindqvist", "Ek", "Sjöberg", "Holmgren", "Nyström", "Åberg"],
    "FI": ["Virtanen", "Korhonen", "Mäkinen", "Laine", "Heikkinen", "Koskinen"],
}
TICKET_TOPICS = ["Device connectivity", "User access / SiemensID", "Data gaps", "Report export",
                 "Alarm configuration", "Integration question", "Performance", "Billing"]


def _d(days_ago):
    return (AS_OF - timedelta(days=days_ago)).isoformat()


def _slug(text):
    """ASCII e-mail part. The .example domain is reserved, so these addresses never reach anyone."""
    for src, dst in {"æ": "ae", "ø": "o", "å": "a", "ä": "a", "ö": "o", "é": "e"}.items():
        text = text.lower().replace(src, dst)
    return "".join(ch for ch in text if ch.isalnum())


def _round_price(value):
    return int(round(value / 100.0) * 100)


def build(path=None):
    rng = random.Random(SEED)
    conn = init_db(path) if path else init_db()
    rows = {name: [] for name in ["accounts", "contacts", "reviews", "surveys", "tickets", "subscriptions",
                                  "subscription_events", "devices", "usage_weekly", "otc_weekly"]}
    ids = {name: 0 for name in rows}

    def add(table, **row):
        ids[table] += 1
        if table not in ("usage_weekly", "otc_weekly"):
            row = {"id": ids[table], **row}
        rows[table].append(row)
        return ids[table]

    prices = {m["code"]: m["list_price_eur"] for m in MODULES}

    for spec in ACCOUNTS:
        a = {**DEFAULTS, **spec}
        # Natural variation between healthy accounts.
        if "util" not in spec:
            a["util"] = rng.uniform(0.5, 0.75)
        if "nps" not in spec:
            a["nps"] = rng.choice([8, 8, 9])
        if "renewal_in" not in spec:
            a["renewal_in"] = rng.randint(100, 340)
        if "ack_rate" not in spec:
            a["ack_rate"] = rng.uniform(0.78, 0.93)
        acc_id = ids["accounts"] + 1
        renewal = AS_OF + timedelta(days=a["renewal_in"])
        start_days = a["started"] if a["started"] else 365 * a["years"] - a["renewal_in"]
        contract_start = _d(start_days)
        partner_id = a.get("partner")
        nis2_scope = int(a["segment"] in ("DSO", "TSO", "Municipal utility", "Generator", "Data center"))
        ot_expected = int(a["sites"] * rng.uniform(11, 15) + 20)
        add("accounts", name=a["name"], country=a["country"], segment=a["segment"], tier=a["tier"],
            channel="Partner" if partner_id else "Direct", partner_id=partner_id, size_factor=a["size"],
            sites_total=a["sites"], ot_assets_expected=ot_expected, nis2_in_scope=nis2_scope,
            contract_start=contract_start, renewal_date=renewal.isoformat(), scenario=a["scenario"])

        # Contacts ------------------------------------------------------------
        names = rng.sample(FIRST_NAMES[a["country"]], 4)
        surnames = [rng.choice(LAST_NAMES[a["country"]]) for _ in names]
        contacts = [
            ("Head of Grid Operations", 0, 1, _d(a["sponsor_left"]) if a["sponsor_left"] else None),
            ("OT Security Engineer", 1, 0, _d(a["champion_left"]) if a["champion_left"] else None),
            ("SCADA Specialist", 0, 0, None),
            ("Procurement Manager", 0, 0, None),
        ]
        for (title, champ, sponsor, left), first, last in zip(contacts, names, surnames):
            add("contacts", account_id=acc_id, name=f"{first} {last}", title=title,
                email=f"{_slug(first)}.{_slug(last)}@{_slug(a['name'].split()[0])}.example",
                is_champion=champ, is_sponsor=sponsor, left_on=left)

        # Subscriptions -------------------------------------------------------
        base_users = max(3, int(round(8 * a["size"])))
        contracted_devices = max(4, int(round(a["sites"] * 0.7)))
        for i, code in enumerate(a["mods"]):
            # Modules beyond the first two were added later (land and expand).
            if i <= 1:
                sub_start_days = start_days
            else:
                sub_start_days = max(60, int(start_days * rng.uniform(0.3, 0.7)))
            value = _round_price(prices[code] * a["size"])
            licensed = 0 if code in ("BASE", "OTC_VULN", "OTC_PATCH", "MDR") else int(base_users * rng.uniform(0.8, 1.3))
            add("subscriptions", account_id=acc_id, module_code=code, start_date=_d(sub_start_days),
                end_date=None, licensed_users=licensed,
                contracted_devices=contracted_devices if code == "BASE" else 0, annual_value_eur=value)
            add("subscription_events", account_id=acc_id, module_code=code, date=_d(sub_start_days),
                event="subscribe" if i <= 1 else "upgrade", delta_eur=value)
        if a["downgrade"]:
            code = a["mods"][1]
            sub = next(s for s in rows["subscriptions"] if s["account_id"] == acc_id and s["module_code"] == code)
            cut = _round_price(sub["annual_value_eur"] * 0.3)
            sub["annual_value_eur"] -= cut
            sub["licensed_users"] = max(2, int(sub["licensed_users"] * 0.6))
            add("subscription_events", account_id=acc_id, module_code=code, date=_d(a["downgrade"]),
                event="downgrade", delta_eur=-cut)

        # Devices -------------------------------------------------------------
        ratio = a["device_ratio"] if a["device_ratio"] != DEFAULTS["device_ratio"] else a["device_ratio"] * rng.uniform(0.92, 1.05)
        online = int(round(contracted_devices * ratio))
        for n in range(online + a["offline"]):
            site = f"Site {n % a['sites'] + 1:02d}"
            if a["started"] and a["device_ratio"] < 0.5:
                onboarded = rng.randint(start_days - 60, start_days - 5)   # stalled after the first weeks
            else:
                onboarded = rng.randint(30, max(31, start_days - 5))
            last_seen = rng.randint(0, 1) if n < online else rng.randint(10, 40)
            add("devices", account_id=acc_id, site=site, device_type=rng.choice(["IPC227E", "Virtual", "SICAM GridEdge"]),
                onboarded_on=_d(onboarded), last_seen=_d(last_seen))

        # Weekly usage per module -------------------------------------------------
        subs = [s for s in rows["subscriptions"] if s["account_id"] == acc_id]
        base_sites = max(1, int(round(a["sites"] * a["site_cov"])) - a["new_sites"])
        for sub in subs:
            if sub["module_code"] not in USAGE_MODULES:
                continue
            sub_start = date.fromisoformat(sub["start_date"])
            for k in range(HISTORY_WEEKS, 0, -1):
                week = AS_OF - timedelta(weeks=k)
                if week < sub_start:
                    continue
                weeks_live = (week - sub_start).days // 7
                ramp = min(1.0, 0.3 + weeks_live / 10)
                mult = 1.0
                if a["decline"]:
                    n_weeks, end_mult = a["decline"]
                    if k <= n_weeks:
                        mult = 1 - (1 - end_mult) * (n_weeks - k + 1) / n_weeks
                top_share = a["top_share"]
                if a["champion_left"]:
                    left_weeks_ago = a["champion_left"] / 7
                    if k <= left_weeks_ago:
                        mult *= max(0.55, 1 - 0.07 * (left_weeks_ago - k + 1))
                        top_share = 0.45
                    else:
                        top_share = 0.6
                users = max(0, round(sub["licensed_users"] * a["util"] * mult * ramp * rng.uniform(0.9, 1.1)))
                if users <= 1:
                    top_share = 1.0 if users == 1 else 0.0
                sites = base_sites + (a["new_sites"] * max(0, 12 - k + 1) // 12 if k <= 12 else 0)
                add("usage_weekly", account_id=acc_id, module_code=sub["module_code"], week_start=week.isoformat(),
                    active_users=users, logins=int(users * rng.uniform(3, 6)),
                    top_user_share=round(min(1.0, top_share * rng.uniform(0.95, 1.05)), 3),
                    active_sites=min(a["sites"], sites),
                    ack_rate=round(min(1.0, a["ack_rate"] * mult ** 0.3 * rng.uniform(0.95, 1.04)), 3))

        # OT Companion outcome data ---------------------------------------------
        otc = next((s for s in subs if s["module_code"] == "OTC"), None)
        if otc:
            has_vuln = "OTC_VULN" in a["mods"]
            has_patch = "OTC_PATCH" in a["mods"]
            otc_start = date.fromisoformat(otc["start_date"])
            for k in range(HISTORY_WEEKS, 0, -1):
                week = AS_OF - timedelta(weeks=k)
                if week < otc_start:
                    continue
                weeks_live = (week - otc_start).days // 7
                ramp = min(1.0, 0.15 + weeks_live / 14)
                inventoried = int(ot_expected * a["coverage"] * ramp * rng.uniform(0.98, 1.0))
                crit = int(max(0, a["crit_open"] * min(1.0, 0.5 + weeks_live / 20) * rng.uniform(0.85, 1.15))) if has_vuln else 0
                created = rng.randint(3, 9) if has_patch else 0
                add("otc_weekly", account_id=acc_id, week_start=week.isoformat(),
                    assets_inventoried=inventoried,
                    baseline_deviations_open=int(max(0, rng.gauss(3 if a["coverage"] > 0.8 else 9, 2))),
                    crit_vulns_open=crit, crit_vulns_unack=int(round(crit * a["unack_share"])),
                    mttp_days=round(a["mttp"] * rng.uniform(0.9, 1.1), 1) if has_vuln else None,
                    patch_tasks_created=created,
                    patch_tasks_completed=max(0, created - rng.randint(0, 2)) if has_patch else 0)

        # Tickets ---------------------------------------------------------------
        for quarter in range(4):
            count = a["tickets_90d"] if quarter == 0 else rng.randint(1, 4)
            for _ in range(count):
                opened = rng.randint(quarter * 91 + 1, quarter * 91 + 90)
                if opened > start_days:
                    continue
                priority = rng.choices(["Low", "Medium", "High"], weights=[4, 4, 2])[0]
                closed = opened - rng.randint(2, 20)
                add("tickets", account_id=acc_id, opened_on=_d(opened),
                    closed_on=_d(closed) if closed > 0 else None, priority=priority,
                    topic=rng.choice(TICKET_TOPICS))
        for _ in range(a["crit_open_tickets"]):
            add("tickets", account_id=acc_id, opened_on=_d(rng.randint(5, 40)), closed_on=None,
                priority="Critical", topic=rng.choice(TICKET_TOPICS[:3]))

        # Reviews (roughly quarterly), surveys ------------------------------------
        day = a["review_gap"]
        while day < start_days:
            partner_only = bool(a["partner_only_gap"]) and day < a["partner_only_gap"]
            add("reviews", account_id=acc_id, date=_d(day),
                kind="Partner review" if partner_only else rng.choice(["QBR", "Success review"]),
                siemens_present=0 if partner_only else 1,
                objectives_documented=int(a["objectives"]),
                sentiment=1 if a["nps"] >= 8 else (0 if a["nps"] >= 6 else -1))
            day += rng.randint(80, 100)
        for day in (rng.randint(20, 60), rng.randint(200, 240)):
            if day < start_days:
                add("surveys", account_id=acc_id, date=_d(day), nps=max(0, min(10, a["nps"] + rng.choice([-1, 0, 0, 1]))))

    insert_rows(conn, "regions", REGIONS)
    insert_rows(conn, "modules", MODULES)
    insert_rows(conn, "partners", PARTNERS)
    for table in rows:
        insert_rows(conn, table, rows[table])
    conn.commit()
    return conn
