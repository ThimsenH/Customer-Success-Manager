"""The CSM's own input: decisions on signals, actions, notes, assessments and
account plans.

Stored in a separate database (data/journal.db) so regenerating the synthetic
portfolio never deletes what the CSM entered. In production this would live in
the CRM (Salesforce tasks and notes) and be read back from there.
"""

import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import AS_OF, SEED
from .db import ROOT

JOURNAL_PATH = ROOT / "data" / "journal.db"

# Decision types: (label, counts as direct contact, counts as success review)
DECISIONS = {
    "Call": (True, False),
    "On-site visit": (True, False),
    "Success review / QBR": (True, True),
    "Email / check-in": (False, False),
    "Training / workshop": (True, False),
    "Escalate internally": (False, False),
    "Involve Sales": (False, False),
    "Go through partner": (False, False),
    "Monitor": (False, False),
    "Dismiss": (False, False),
}
ACTION_TYPES = [d for d in DECISIONS if d not in ("Monitor", "Dismiss")]
OUTCOMES = ["Solved", "Improved", "No change", "Worse"]
ASSESSMENTS = ["Healthy", "Watch", "At risk", "Critical"]

# How long a decision keeps a signal quiet before it comes back.
DISMISS_DAYS = 90
AFTER_DONE_DAYS = 30
DUE_DAYS = {"critical": 2, "high": 7, "medium": 14, "low": 30}

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id                INTEGER PRIMARY KEY,
    account_id        INTEGER NOT NULL,
    rule_ids          TEXT NOT NULL,          -- comma-separated rules this decision answers
    decision          TEXT NOT NULL,          -- see DECISIONS
    status            TEXT NOT NULL,          -- open / done / cancelled / monitoring / dismissed
    created_on        TEXT NOT NULL,
    due_on            TEXT,                   -- actions
    review_on         TEXT,                   -- monitor / dismiss: when the signal may come back
    completed_on      TEXT,
    note              TEXT,
    outcome           TEXT,                   -- Solved / Improved / No change / Worse
    objectives_agreed INTEGER,                -- for success reviews
    crm_task_id       TEXT,                   -- placeholder for the Salesforce task id
    demo              INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY,
    account_id  INTEGER NOT NULL,
    written_on  TEXT NOT NULL,
    text        TEXT NOT NULL,
    demo        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS assessments (   -- the CSM's own view, latest row wins
    id          INTEGER PRIMARY KEY,
    account_id  INTEGER NOT NULL,
    written_on  TEXT NOT NULL,
    rating      TEXT NOT NULL,
    reason      TEXT,
    demo        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS account_plans (
    account_id  INTEGER PRIMARY KEY,
    objectives  TEXT,
    strategy    TEXT,
    updated_on  TEXT NOT NULL
);
"""


def today():
    """The demo runs on a fixed date; in production this is date.today()."""
    return AS_OF


def connect(path=JOURNAL_PATH, seed=True):
    path = Path(path)
    is_new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    if is_new and seed:
        seed_demo(conn)
    return conn


def reset(path=JOURNAL_PATH):
    path = Path(path)
    if path.exists():
        path.unlink()
    return connect(path)


def _crm_id(rng):
    return "00T" + "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789") for _ in range(12))


# --- Writing -----------------------------------------------------------------------

def decide(conn, account_id, rule_ids, decision, note="", due_on=None, review_on=None):
    account_id = int(account_id)  # numpy integers would be stored as blobs
    created = today()
    if decision == "Monitor":
        status = "monitoring"
    elif decision == "Dismiss":
        status = "dismissed"
        review_on = review_on or created + timedelta(days=DISMISS_DAYS)
    else:
        status = "open"
    crm_id = _crm_id(random.Random()) if status == "open" else None
    cur = conn.execute(
        "INSERT INTO decisions (account_id, rule_ids, decision, status, created_on, due_on, review_on, note, crm_task_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (account_id, ",".join(rule_ids), decision, status, created.isoformat(),
         due_on.isoformat() if due_on else None, review_on.isoformat() if review_on else None, note, crm_id))
    conn.commit()
    return cur.lastrowid


def complete(conn, decision_id, outcome, note="", objectives_agreed=None):
    decision_id = int(decision_id)
    row = conn.execute("SELECT note FROM decisions WHERE id = ?", (decision_id,)).fetchone()
    combined = "\n".join(x for x in [row["note"], note] if x)
    conn.execute("UPDATE decisions SET status = 'done', completed_on = ?, outcome = ?, note = ?, objectives_agreed = ?"
                 " WHERE id = ?", (today().isoformat(), outcome, combined,
                                   None if objectives_agreed is None else int(objectives_agreed), decision_id))
    conn.commit()


def cancel(conn, decision_id):
    conn.execute("UPDATE decisions SET status = 'cancelled', completed_on = ? WHERE id = ?",
                 (today().isoformat(), int(decision_id)))
    conn.commit()


def add_note(conn, account_id, text):
    conn.execute("INSERT INTO notes (account_id, written_on, text) VALUES (?, ?, ?)",
                 (int(account_id), datetime.now().isoformat(timespec="minutes"), text))
    conn.commit()


def set_assessment(conn, account_id, rating, reason):
    conn.execute("INSERT INTO assessments (account_id, written_on, rating, reason) VALUES (?, ?, ?, ?)",
                 (int(account_id), datetime.now().isoformat(timespec="minutes"), rating, reason))
    conn.commit()


def save_plan(conn, account_id, objectives, strategy):
    conn.execute("INSERT INTO account_plans (account_id, objectives, strategy, updated_on) VALUES (?, ?, ?, ?)"
                 " ON CONFLICT(account_id) DO UPDATE SET objectives = excluded.objectives,"
                 " strategy = excluded.strategy, updated_on = excluded.updated_on",
                 (int(account_id), objectives, strategy, today().isoformat()))
    conn.commit()


# --- Reading -----------------------------------------------------------------------

def touches(conn):
    """Completed actions that count as Siemens meeting the customer, for the metrics."""
    rows = conn.execute("SELECT account_id, decision, completed_on, objectives_agreed FROM decisions"
                        " WHERE status = 'done'").fetchall()
    out = []
    for r in rows:
        direct, review = DECISIONS[r["decision"]]
        if direct:
            out.append({"account_id": r["account_id"], "date": date.fromisoformat(r["completed_on"]),
                        "is_review": review, "objectives_agreed": bool(r["objectives_agreed"])})
    return out


def signal_status(decisions, account_id, rule_id, on=None):
    """What the CSM has decided about one signal. `decisions` are rows, newest first."""
    on = on or today()
    for d in decisions:
        if d["account_id"] != account_id or rule_id not in d["rule_ids"].split(","):
            continue
        if d["status"] == "open":
            return "In progress", d
        if d["status"] == "monitoring" and d["review_on"] and date.fromisoformat(d["review_on"]) >= on:
            return "Monitoring", d
        if d["status"] == "dismissed" and d["review_on"] and date.fromisoformat(d["review_on"]) >= on:
            return "Dismissed", d
        if d["status"] == "done" and date.fromisoformat(d["completed_on"]) + timedelta(days=AFTER_DONE_DAYS) >= on:
            return "Action done", d
        break  # the latest decision has expired: the signal needs a new decision
    return "Needs decision", None


# --- Demo history --------------------------------------------------------------------

# (account, weeks ago, decision, rules, outcome or status, note)
DEMO_HISTORY = [
    ("Fjordlys Nett AS", 20, "Involve Sales", "E01", "Solved", "Sales extended the device contract by 10 units."),
    ("Trollvegg Nett AS", 18, "Training / workshop", "R18", "Improved", "Trained the field technicians on patch tasks."),
    ("Sundlys Elnet A/S", 16, "On-site visit", "E02", "Improved", "Visited the control centre; rollout plan for 12 more substations agreed."),
    ("Granit Kraftnät AB", 15, "Email / check-in", "R15", "No change", "Sent survey follow-up, no reply."),
    ("Järvilaakso Verkko Oy", 14, "Call", "R01", "Solved", "Usage dip was the summer holiday. Back to normal."),
    ("Sørkapp Nett AS", 13, "Call", "R08", "Improved", "Agreed that the OT engineer reviews alerts every Monday."),
    ("Ishavet Datasenter AS", 12, "Email / check-in", "R13", "No change", "Asked for objectives by email, no answer."),
    ("Vesterhav Energi A/S", 12, "Success review / QBR", "R12", "Improved", "QBR with operations; three objectives agreed."),
    ("Polarlading AS", 11, "Escalate internally", "R10", "Solved", "Two connectivity tickets fixed after escalation."),
    ("Tunturi Energia Oy", 10, "Email / check-in", "R07", "No change", "Reminded them about offline devices."),
    ("Ekdala Industripark AB", 9, "Call", "R03", "No change", "Agreed to onboard a second user, but nobody was named."),
    ("Kuura Datakeskus Oy", 9, "Training / workshop", "R18", "No change", "Workshop held, but only two people joined."),
    ("Viddekraft AS", 8, "Email / check-in", "R15", "Worse", "Generic follow-up email; NPS dropped further."),
    ("Isbre Kraft AS", 22, "Email / check-in", "R08", "No change", "Sent the list of unacknowledged CVEs. Nothing happened."),
    ("Koivu Teollisuus Oy", 20, "Go through partner", "R18", "No change", "Partner was asked to run a training. Not done yet."),
    ("Trollvegg Nett AS", 6, "Email / check-in", "E05", "Improved", "Sent a SIEM overview; they asked for a demo."),
    ("Granit Kraftnät AB", 7, "Call", "R15", "Worse", "Customer was annoyed about a billing error. Escalated afterwards."),
    ("Polarlading AS", 3, "Call", "E02", "Improved", "Rollout plan for eight more charging sites shared. Sales informed."),
    ("Ekskog Elnät AB", 2, "Go through partner", "E04", "No change", "Asked Brokraft to raise NIS2 readiness. Waiting for a date."),
]
DEMO_OPEN = [
    ("Kystlinje Nett AS", 0, "Call", "R01", 3, "Call the OT engineer before the renewal talk."),
    ("Fonnfjell Energi AS", 3, "Success review / QBR", "R12", -6, "Review planned, but the customer postponed twice."),
]
DEMO_MONITOR = [
    ("Skjærgård Nett AS", 1, "R03", 30, "Small team: one OT engineer is normal here. Check again next month."),
]
DEMO_NOTES = [
    ("Hedeland Net A/S", 2, "Heard from the SCADA team that a new head of grid operations starts in November. Need an introduction."),
    ("Hedeland Net A/S", 9, "Hedeland is evaluating Omny for OT risk. Keep the value story ready."),
    ("Kystlinje Nett AS", 4, "Budget freeze announced internally. Renewal may be questioned."),
    ("Isbre Kraft AS", 6, "Only one person reads the vulnerability alerts, and she is on leave until December."),
    ("Älvdal Nät AB", 5, "Partner says all is fine, but we haven't spoken to the customer ourselves since January."),
    ("Järvilaakso Verkko Oy", 7, "Happy to be a reference customer for other Finnish DSOs."),
]
DEMO_ASSESSMENTS = [
    ("Hedeland Net A/S", "At risk", "Sponsor gone and a competitor is in the door. Worse than the score shows."),
    ("Isbre Kraft AS", "At risk", "The tool works; the problem is one person on leave. Fixable."),
    ("Järvilaakso Verkko Oy", "Healthy", "Strong relationship, potential reference."),
]
DEMO_PLANS = [
    ("Hedeland Net A/S", "1. Full OT inventory of all 120 substations by Q2\n2. Evidence pack for the NIS2 audit\n3. Mean time to patch under 30 days",
     "Win the new head of grid operations as sponsor. Position SIEM once the audit is passed."),
    ("Kystlinje Nett AS", "1. Weekly alert triage\n2. Reduce open critical CVEs by half",
     "Show value before the renewal: savings vs. manual inventory."),
]


def seed_demo(conn, account_ids=None):
    """Plausible history so the action views aren't empty. Marked demo=1."""
    if account_ids is None:
        from .db import DB_PATH
        portfolio = sqlite3.connect(DB_PATH)
        account_ids = dict(portfolio.execute("SELECT name, id FROM accounts").fetchall())
        portfolio.close()
    rng = random.Random(SEED)
    for name, weeks, decision, rules, outcome, note in DEMO_HISTORY:
        created = AS_OF - timedelta(weeks=weeks)
        done = created + timedelta(days=rng.randint(2, 10))
        conn.execute("INSERT INTO decisions (account_id, rule_ids, decision, status, created_on, due_on, completed_on,"
                     " note, outcome, objectives_agreed, crm_task_id, demo) VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
                     (account_ids[name], rules, decision, "done", created.isoformat(),
                      (created + timedelta(days=7)).isoformat(), done.isoformat(), note, outcome,
                      1 if decision == "Success review / QBR" else None, _crm_id(rng)))
    for name, weeks, decision, rules, due_in, note in DEMO_OPEN:
        created = AS_OF - timedelta(weeks=weeks, days=2)
        conn.execute("INSERT INTO decisions (account_id, rule_ids, decision, status, created_on, due_on, note,"
                     " crm_task_id, demo) VALUES (?,?,?,?,?,?,?,?,1)",
                     (account_ids[name], rules, decision, "open", created.isoformat(),
                      (AS_OF + timedelta(days=due_in)).isoformat(), note, _crm_id(rng)))
    for name, weeks, rules, days, note in DEMO_MONITOR:
        created = AS_OF - timedelta(weeks=weeks)
        conn.execute("INSERT INTO decisions (account_id, rule_ids, decision, status, created_on, review_on, note, demo)"
                     " VALUES (?,?,?,?,?,?,?,1)",
                     (account_ids[name], rules, "Monitor", "monitoring", created.isoformat(),
                      (created + timedelta(days=days)).isoformat(), note))
    for name, weeks, text in DEMO_NOTES:
        written = datetime.combine(AS_OF - timedelta(weeks=weeks), datetime.min.time()).replace(hour=9)
        conn.execute("INSERT INTO notes (account_id, written_on, text, demo) VALUES (?,?,?,1)",
                     (account_ids[name], written.isoformat(timespec="minutes"), text))
    for name, rating, reason in DEMO_ASSESSMENTS:
        written = datetime.combine(AS_OF - timedelta(days=5), datetime.min.time()).replace(hour=9)
        conn.execute("INSERT INTO assessments (account_id, written_on, rating, reason, demo) VALUES (?,?,?,?,1)",
                     (account_ids[name], written.isoformat(timespec="minutes"), rating, reason))
    for name, objectives, strategy in DEMO_PLANS:
        conn.execute("INSERT INTO account_plans VALUES (?,?,?,?)",
                     (account_ids[name], objectives, strategy, (AS_OF - timedelta(days=20)).isoformat()))
    conn.commit()
