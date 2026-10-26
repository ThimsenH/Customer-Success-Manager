"""The CSM's decisions: signal status and feedback into the metrics."""

from datetime import timedelta

import pytest

from csm import generate, journal, pipeline
from csm.db import read


@pytest.fixture()
def dbs(tmp_path):
    conn = generate.build(tmp_path / "portfolio.db")
    jconn = journal.connect(tmp_path / "journal.db", seed=False)
    pipeline.analyse(conn, journal_conn=jconn)
    ids = dict(conn.execute("SELECT name, id FROM accounts").fetchall())
    return conn, jconn, ids


def rules_for(conn, account_id):
    return set(read(conn, "SELECT rule_id FROM signals WHERE account_id = ?", (account_id,))["rule_id"])


def test_logged_call_clears_partner_blind_spot(dbs):
    conn, jconn, ids = dbs
    acc = ids["Älvdal Nät AB"]
    assert "R17" in rules_for(conn, acc)
    decision = journal.decide(jconn, acc, ["R17"], "Call", due_on=journal.today())
    journal.complete(jconn, decision, "Improved")
    pipeline.analyse(conn, journal_conn=jconn, history=False)
    assert "R17" not in rules_for(conn, acc)


def test_email_does_not_count_as_contact(dbs):
    conn, jconn, ids = dbs
    acc = ids["Älvdal Nät AB"]
    decision = journal.decide(jconn, acc, ["R17"], "Email / check-in", due_on=journal.today())
    journal.complete(jconn, decision, "No change")
    pipeline.analyse(conn, journal_conn=jconn, history=False)
    assert "R17" in rules_for(conn, acc)


def test_signal_status_lifecycle(dbs):
    _, jconn, ids = dbs
    acc = ids["Kystlinje Nett AS"]
    rows = lambda: [dict(r) for r in jconn.execute("SELECT * FROM decisions ORDER BY created_on DESC, id DESC")]
    assert journal.signal_status(rows(), acc, "R01")[0] == "Needs decision"
    journal.decide(jconn, acc, ["R01"], "Monitor", review_on=journal.today() + timedelta(days=14))
    assert journal.signal_status(rows(), acc, "R01")[0] == "Monitoring"
    # After the monitoring date the signal needs a decision again.
    later = journal.today() + timedelta(days=15)
    assert journal.signal_status(rows(), acc, "R01", on=later)[0] == "Needs decision"


def test_demo_history_seeds(tmp_path, dbs):
    _, _, ids = dbs
    jconn = journal.connect(tmp_path / "seeded.db", seed=False)
    journal.seed_demo(jconn, ids)
    assert jconn.execute("SELECT COUNT(*) FROM decisions WHERE status = 'open'").fetchone()[0] == 2
