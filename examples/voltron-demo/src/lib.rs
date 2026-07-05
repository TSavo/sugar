// SPDX-License-Identifier: MIT OR Apache-2.0
//
// voltron-demo: smallest non-trivial two-vendor Sugar consumer.
//
//   M = 3 modules (ingest, persist, report) + a tiny bin entry.
//   N = 2 vendors (serde_json via sugar-shim-serde-json-rust,
//                  rusqlite   via sugar-shim-rusqlite).
//
// The spine `run_voltron_demo()` calls into each module; the modules
// own the boundary stubs that `sugar materialize` fills with vendor
// sugar. User-side functions (parse_event, install_schema, insert_event,
// compose_report) have implicit pre/post that the lifter derives from
// panics + early returns (per the rust-missing-edge pattern). When
// `sugar prove` runs, the pool unions:
//
//   1. voltron-demo.proof              (the head — this crate's spine)
//   2. sugar-shim-serde-json-rust.proof   (JSON lion)
//   3. sugar-shim-rusqlite.proof          (SQL  lion)
//
// surfaced through the rust kit's `sugar.plugin.resolve_dependency_proofs`
// RPC (cargo's resolved tree). Discharge composes across every cross-vendor
// seam in the spine.

pub mod ingest;
pub mod persist;
pub mod report;

pub use ingest::{parse_event, ValidEvent};
pub use persist::{insert_event, install_schema, open_in_memory};
pub use report::{compose_report, Report};

/// The spine. Threads JSON ingest → SQL persist → cross-vendor report read.
/// Returns the JSON-encoded report string.
pub fn run_voltron_demo(json_input: &str) -> Result<String, String> {
    let event = parse_event(json_input)?;
    let conn = open_in_memory().map_err(|e| format!("open_in_memory: {e}"))?;
    install_schema(&conn).map_err(|e| format!("install_schema: {e}"))?;
    let rowid = insert_event(&conn, &event).map_err(|e| format!("insert_event: {e}"))?;
    let report = compose_report(&conn, rowid)?;
    Ok(format!(
        "voltron round-trip: rowid={} user={} type={} report={:?}",
        rowid, report.user, report.event_type, report.payload_summary
    ))
}
