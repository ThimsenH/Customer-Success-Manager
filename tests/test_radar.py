"""The synthetic scenarios must trigger the signals they were built for."""

import pytest

from csm import generate, health, journal, pipeline
from csm.db import read
from csm.signals import evaluate, matches

EXPECTED = {
    "Kystlinje Nett AS": {"R01", "R02"},          # silent churner before renewal
    "Isbre Kraft AS": {"R08", "R09"},             # alerts nobody triages
    "Skjærgård Nett AS": {"R03"},                 # one-person dependency
    "Fonnfjell Energi AS": {"R10", "R12"},        # support problems, no reviews
    "Hedeland Net A/S": {"R05", "R16"},           # Danish key account under pressure
    "Älvdal Nät AB": {"R17"},                     # partner-led blind spot
    "Laddstig AB": {"R14"},                       # downgrade
    "Revontuli Verkko Oy": {"R04"},               # champion left
    "Fjordlys Nett AS": {"E01", "E02"},           # device limit, new sites
    "Viddekraft AS": {"E03", "E04"},              # Asset Management -> OT Companion
    "Trollvegg Nett AS": {"E05"},                 # mature OT Companion -> SIEM
    "Sørkapp Nett AS": {"E06"},                   # patch workflow add-on
    # Whole portfolio: other modules, grid capacity, hardware and services
    "Lofotlinja Nett AS": {"R19", "R20"},         # autonomous grid control switched off
    "Nordkyst Nett AS": {"E09"},                  # constrained grid without Distribution Grid Management
    "Varanger Kraftnett AS": {"E10"},             # grid management delivering -> more sensors and fuses
    "Fjellading AS": {"R21", "E11"},              # chargers breaching the DSO limit -> load controller
    "Sognehamn Kraft AS": {"R23"},                # monitoring only
    "Norrsken Laddnät AB": {"R22"},               # chargers offline
    "Bergslagen Elnät AB": {"R28", "R29"},        # SIEM collectors offline
    "Vätterstrand Energi AB": {"R24", "R25"},     # energy reports unread, no targets
    "Pohjoisranta Verkko Oy": {"R26", "E12"},     # fault location slower -> fault sensors
    "Saaristo Sähkö Oy": {"R29", "E13"},          # small team -> MDR
    "Merituuli Energia Oy": {"E14"},              # control in place -> energy reporting
    "Nordstjerne Nett AS": {"R06", "E16"},        # stalled onboarding -> installation service
}


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    folder = tmp_path_factory.mktemp("db")
    conn = generate.build(folder / "test.db")
    jconn = journal.connect(folder / "journal.db", seed=False)
    journal.seed_demo(jconn, dict(conn.execute("SELECT name, id FROM accounts").fetchall()))
    pipeline.analyse(conn, journal_conn=jconn)
    return conn


def test_scenarios_fire_expected_rules(conn):
    fired = read(conn, "SELECT a.name, s.rule_id FROM signals s JOIN accounts a ON a.id = s.account_id")
    by_account = fired.groupby("name")["rule_id"].apply(set).to_dict()
    for name, rules in EXPECTED.items():
        assert rules <= by_account.get(name, set()), f"{name}: expected {rules}, got {by_account.get(name)}"


def test_healthy_reference_has_no_risks(conn):
    risks = read(conn, """SELECT s.rule_id FROM signals s JOIN accounts a ON a.id = s.account_id
                          WHERE a.name = 'Järvilaakso Verkko Oy' AND s.kind = 'risk'""")
    assert risks.empty


def test_health_history_is_complete(conn):
    counts = read(conn, "SELECT account_id, COUNT(*) n FROM health_scores GROUP BY account_id")
    assert counts["n"].nunique() == 1


def test_missing_metric_never_matches():
    rule = {"when": [["mttp_days", ">", 60]]}
    assert not matches(rule, {"mttp_days": None})
    assert matches(rule, {"mttp_days": 61})


def test_reason_handles_missing_values():
    rule = {"id": "X", "kind": "risk", "title": "t", "severity": "low", "playbook": "p",
            "when": [["a", ">", 0]], "reason": "{a} and {b:.0f}"}
    out = evaluate({"account_id": 1, "a": 1, "b": None}, [rule], {})
    assert out[0]["reason"] == "1 and n/a"


def test_weakest_part_caps_total(monkeypatch):
    monkeypatch.setattr(health, "onboarding", lambda m: 10.0)
    for part in ("adoption", "outcomes", "relationship"):
        monkeypatch.setattr(health, part, lambda m: 100.0)
    assert health.score({})["total"] == 25.0


def test_every_subscribed_module_has_its_kpis(conn):
    from csm import catalog
    rows = read(conn, "SELECT DISTINCT module_code, kpi FROM module_kpi_weekly")
    have = set(zip(rows["module_code"], rows["kpi"]))
    subscribed = set(read(conn, "SELECT DISTINCT module_code FROM subscriptions")["module_code"])
    for kpi in catalog.kpis():
        if kpi["module"] in subscribed:
            assert (kpi["module"], kpi["id"]) in have, kpi


def test_kpi_score_bounds():
    from csm import catalog
    higher = {"better": "higher", "target": 0.8}
    lower = {"better": "lower", "target": 30}
    assert catalog.score(higher, 0.8) == 100 and catalog.score(higher, 0.4) == 0
    assert catalog.score(lower, 30) == 100 and catalog.score(lower, 60) == 0 and catalog.score(lower, 0) == 100
