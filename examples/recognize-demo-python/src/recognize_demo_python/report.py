# SPDX-License-Identifier: MIT OR Apache-2.0

from __future__ import annotations

import json
import sqlite3

from .persist import query_one


def compose_report(conn: sqlite3.Connection, rowid: int) -> dict:
    row = query_one(
        conn,
        "SELECT type, user, payload FROM events WHERE id = ?",
        (rowid,),
    )
    if row is None:
        raise LookupError(f"event row not found: {rowid}")
    event_type, user, payload_text = row
    return {
        "rowid": rowid,
        "user": user,
        "type": event_type,
        "payload": json.loads(payload_text),
    }
