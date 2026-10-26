"""Analysis step: metrics -> health scores -> signals, written back to SQLite."""

import json
from datetime import timedelta

from . import health, signals
from .config import AS_OF, HEALTH_HISTORY_WEEKS
from .db import connect, insert_rows, load_tables
from .metrics import MetricContext, compute_all

SOURCE_TABLES = ["accounts", "regions", "partners", "modules", "subscriptions", "subscription_events",
                 "devices", "usage_weekly", "otc_weekly", "tickets", "reviews", "surveys", "contacts"]


def analyse(conn=None, as_of=AS_OF):
    conn = conn or connect()
    tables = load_tables(conn, SOURCE_TABLES)
    ctx = MetricContext(tables)
    rules = signals.load_rules()
    prices = dict(zip(tables["modules"]["code"], tables["modules"]["list_price_eur"]))

    for table in ["account_metrics", "health_scores", "signals"]:
        conn.execute(f"DELETE FROM {table}")

    health_rows, signal_rows = [], []
    for k in range(HEALTH_HISTORY_WEEKS - 1, -1, -1):
        day = as_of - timedelta(weeks=k)
        for m in compute_all(ctx, day):
            h = health.score(m)
            health_rows.append({"account_id": m["account_id"], "as_of": day.isoformat(), **h})
            if k == 0:
                m["health"] = h["total"]
                conn.execute("INSERT INTO account_metrics VALUES (?, ?, ?)",
                             (m["account_id"], day.isoformat(), json.dumps(m, default=str)))
                for s in signals.evaluate(m, rules, prices):
                    signal_rows.append({**s, "as_of": day.isoformat()})

    insert_rows(conn, "health_scores", health_rows)
    insert_rows(conn, "signals", signal_rows)
    conn.commit()
    return len(health_rows), len(signal_rows)
