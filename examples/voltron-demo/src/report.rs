// SPDX-License-Identifier: MIT OR Apache-2.0
//
// report.rs — the cross-vendor seam, in user code. Owns no vendor
// boundaries itself. Uses persist::sql_query_row (SQL vendor) to read
// row fields, then ingest::json_parse (JSON vendor) to re-decode the
// payload column. This is precisely the seam where one vendor's post
// (SQL row text) must establish another vendor's pre (JSON parseable
// string) for the spine to discharge.

use crate::ingest::json_parse;
use crate::persist::sql_query_row;
use rusqlite::Connection;

#[derive(Debug, Clone, PartialEq)]
pub struct Report {
    pub user: String,
    pub event_type: String,
    pub payload_summary: String,
}

// =============================================================================
// User-side function: compose_report.
// Lifter-derived contract:
//   pre:  conn has events table populated (established by install_schema +
//         insert_event posts)
//         rowid > 0 (established by insert_event's post)
//   post: result.user / event_type match the row at `rowid`
//
// Cross-vendor seam: payload_text from SQL is fed into JSON parse;
// this is the M-file equivalent of the missing-edge case — IF SQL's
// post does not establish JSON's pre on the payload column, prove refuses.
// =============================================================================

pub fn compose_report(conn: &Connection, rowid: i64) -> Result<Report, String> {
    if rowid <= 0 {
        return Err("report: rowid must be positive".into());
    }
    let event_type: String = sql_query_row(
        conn,
        "SELECT type FROM events WHERE id = ?1",
        [&rowid as &dyn rusqlite::ToSql],
        |row| row.get(0),
    )
    .map_err(|e| format!("report: query type: {e}"))?;
    let user: String = sql_query_row(
        conn,
        "SELECT user FROM events WHERE id = ?1",
        [&rowid as &dyn rusqlite::ToSql],
        |row| row.get(0),
    )
    .map_err(|e| format!("report: query user: {e}"))?;
    let payload_text: String = sql_query_row(
        conn,
        "SELECT payload FROM events WHERE id = ?1",
        [&rowid as &dyn rusqlite::ToSql],
        |row| row.get(0),
    )
    .map_err(|e| format!("report: query payload: {e}"))?;
    // Cross-vendor seam: SQL string → JSON Value
    let payload = json_parse(&payload_text)?;
    let payload_summary = format!("{}", payload);
    Ok(Report {
        user,
        event_type,
        payload_summary,
    })
}
