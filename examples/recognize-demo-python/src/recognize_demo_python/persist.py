# SPDX-License-Identifier: MIT OR Apache-2.0

from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional, Tuple


def connect_db(database_path: str) -> sqlite3.Connection:
    return sqlite3.connect(database_path)


def execute_sql(conn: sqlite3.Connection, statement: str, values: Any = ()) -> sqlite3.Cursor:
    return conn.execute(statement, values)


def query_one(
    conn: sqlite3.Connection,
    statement: str,
    values: Any = (),
) -> Optional[Tuple]:
    cursor = conn.execute(statement, values)
    return cursor.fetchone()


def install_schema(conn: sqlite3.Connection) -> None:
    execute_sql(
        conn,
        "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, type TEXT NOT NULL, user TEXT NOT NULL, payload TEXT NOT NULL)",
        (),
    )
    conn.commit()


def insert_event(conn: sqlite3.Connection, event: dict[str, Any]) -> int:
    payload_text = json.dumps(event["payload"], separators=(",", ":"))
    cursor = execute_sql(
        conn,
        "INSERT INTO events (type, user, payload) VALUES (?, ?, ?)",
        (event["event_type"], event["user"], payload_text),
    )
    conn.commit()
    rowid = cursor.lastrowid
    if rowid is None:
        raise RuntimeError("sqlite insert did not expose lastrowid")
    return int(rowid)
