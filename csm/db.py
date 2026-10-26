"""Database connection and small query helpers."""

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "csm.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def connect(path=DB_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path=DB_PATH):
    """Create a fresh database (drops any existing file)."""
    path = Path(path)
    if path.exists():
        path.unlink()
    conn = connect(path)
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


def insert_rows(conn, table, rows):
    if not rows:
        return
    cols = list(rows[0].keys())
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
    conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows])


def read(conn, sql, params=()):
    return pd.read_sql_query(sql, conn, params=params)


def load_tables(conn, names):
    return {name: read(conn, f"SELECT * FROM {name}") for name in names}
