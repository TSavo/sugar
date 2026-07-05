# SPDX-License-Identifier: MIT OR Apache-2.0

from __future__ import annotations

from .ingest import fetch_event_response
from .persist import connect_db, insert_event, install_schema
from .report import compose_report

__all__ = ["run_demo"]


def run_demo(url: str, db_path: str = ":memory:") -> dict:
    conn = connect_db(db_path)
    try:
        install_schema(conn)
        response = fetch_event_response("GET", url, {"Accept": "application/json"}, None)
        event = response.json()
        rowid = insert_event(conn, event)
        return compose_report(conn, rowid)
    finally:
        conn.close()
