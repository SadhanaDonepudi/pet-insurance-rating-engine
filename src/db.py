"""SQLite database helpers.

PostgreSQL mapping (honest labeling): this project runs on SQLite locally.
The DDL in sql/schema.sql is PostgreSQL-compatible (standard types, no
SQLite-only syntax); to run on PostgreSQL, point DATABASE_URL at a Postgres
server and execute the same schema file — table and column names are
identical. SQLite is used here because no Postgres server is available in
this environment.
"""

import os
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
