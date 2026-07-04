// SPDX-License-Identifier: MIT OR Apache-2.0
//
// persist.rs — SQL persistence module. Three boundary stubs for rusqlite
// (open_in_memory, sql_execute, sql_query_row_string) + user-side
// install_schema and insert_event functions. The cross-vendor seam STARTS
// here: insert_event receives a ValidEvent (string fields from JSON
// ingest) and binds them into SQL parameters — json's post must
// establish sql's pre for the spine to discharge.

use crate::ingest::ValidEvent;
use rusqlite::Connection;

// =============================================================================
// Boundary: concept:sql-connection-open  →  sugar-shim-rusqlite
// =============================================================================
pub fn open_in_memory() -> rusqlite::Result<Connection> {
    Connection::open_in_memory()
}

// =============================================================================
// Boundary: concept:sql-execute  →  sugar-shim-rusqlite
// =============================================================================
pub fn sql_execute(
    conn: &Connection,
    sql: &str,
    args: &[&dyn rusqlite::ToSql],
) -> rusqlite::Result<usize> {
    conn.execute(sql, args)
}

// =============================================================================
// Boundary: concept:sql-query-row  →  sugar-shim-rusqlite
//
// Matches the rusqlite shim's 4-param mapper form (Gap #5 user-side
// adoption per issue #1575). The user passes a closure mapping
// &Row<'_> -> Result<T>; persist's typed-row post → report's typed-input
// pre at the cross-vendor seam.
// =============================================================================
pub fn sql_query_row<T, P, F>(conn: &Connection, sql: &str, params: P, mapper: F) -> rusqlite::Result<T>
where
    P: rusqlite::Params,
    F: FnOnce(&rusqlite::Row<'_>) -> rusqlite::Result<T>,
{
    conn.query_row(sql, params, mapper)
}

// =============================================================================
// User-side function: install_schema.
// Lifter-derived contract:
//   pre:  conn is an open connection (rust type system)
//   post: events table exists with columns (id, type, user, payload)
// =============================================================================

pub fn install_schema(conn: &Connection) -> rusqlite::Result<()> {
    sql_execute(
        conn,
        "CREATE TABLE events (id INTEGER PRIMARY KEY, type TEXT NOT NULL, user TEXT NOT NULL, payload TEXT NOT NULL)",
        &[],
    )?;
    Ok(())
}

// =============================================================================
// User-side function: insert_event.
// Lifter-derived contract:
//   pre:  conn has events table (established by install_schema's post)
//         event.user is non-empty (established by parse_event's post)
//   post: result is the inserted rowid > 0 (the panic on rowid<=0
//         guard lifts to the post-condition)
//
// Cross-vendor seam: event.event_type / event.user / event.payload_text
// are JSON-vendor outputs; here they become SQL-vendor inputs as
// rusqlite::ToSql trait objects. Substrate discharges that morphism.
// =============================================================================

pub fn insert_event(conn: &Connection, event: &ValidEvent) -> rusqlite::Result<i64> {
    let event_type: &dyn rusqlite::ToSql = &event.event_type;
    let user: &dyn rusqlite::ToSql = &event.user;
    let payload: &dyn rusqlite::ToSql = &event.payload_text;
    sql_execute(
        conn,
        "INSERT INTO events (type, user, payload) VALUES (?1, ?2, ?3)",
        &[event_type, user, payload],
    )?;
    let rowid: i64 = sql_query_row(conn, "SELECT last_insert_rowid()", [], |row| row.get(0))?;
    if rowid <= 0 {
        panic!("persist: SQL INTEGER PRIMARY KEY post violated — rowid <= 0");
    }
    Ok(rowid)
}
