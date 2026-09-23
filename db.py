"""SQLite storage: one row per run, one row per saved person."""

import json
import sqlite3
from datetime import datetime, timezone

DB_PATH = "scout.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    target      TEXT,
    model       TEXT,
    turns       INTEGER,
    cost        REAL,
    stop_reason TEXT,
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS people (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT,
    name         TEXT,
    role         TEXT,
    firm         TEXT,
    why_fit      TEXT,
    email        TEXT,
    linkedin_url TEXT,
    x_url        TEXT,
    source_urls  TEXT,  -- JSON list
    opener       TEXT,
    created_at   TEXT
);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)  # creates the tables the first time; no-op after that
    return conn


def save_person(conn, run_id, person):
    conn.execute(
        """INSERT INTO people (run_id, name, role, firm, why_fit, email, linkedin_url, x_url,
                               source_urls, opener, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id, person["name"], person["role"], person["firm"], person["why_fit"],
            person["email"], person["linkedin_url"], person["x_url"],
            json.dumps(person["source_urls"]), person["opener"], now(),
        ),
    )
    conn.commit()


def update_person(conn, run_id, person):
    conn.execute(
        """UPDATE people SET email = ?, linkedin_url = ?, x_url = ?, source_urls = ?
           WHERE run_id = ? AND name = ? AND firm = ?""",
        (
            person["email"], person["linkedin_url"], person["x_url"], json.dumps(person["source_urls"]),
            run_id, person["name"], person["firm"],
        ),
    )
    conn.commit()


def save_run(conn, run_id, target, model, turns, cost, stop_reason):
    conn.execute(
        "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, target, model, turns, cost, stop_reason, now()),
    )
    conn.commit()
