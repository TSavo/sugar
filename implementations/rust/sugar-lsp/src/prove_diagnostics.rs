// SPDX-License-Identifier: MIT OR Apache-2.0
//
// prove_diagnostics.rs: map `sugar_verifier::report::row_to_json` rows (the
// SAME wire shape `sugar prove --json` / the daemon's `proveConsistency`
// produce) into LSP diagnostics anchored at the assertion's own source
// locus, using `fol_format::format_detail` for the message. Mirrors
// `editors/vscode-sugar/src/proveClient.ts`'s `diagnosticsFromRows` +
// `extension.ts`'s `proveToVsDiagnostic`/`provenValueOf`.

use std::path::{Path, PathBuf};

use serde_json::Value as Json;
use tower_lsp::lsp_types::{Position, Range};

use crate::fol_format::{self, ConjoinedFacts};

/// A `status` a consistency row can report that the editor paints as a red
/// diagnostic. `discharged` (proven) and `refused` (honestly undecided, not
/// a violation) are NOT painted -- only a decided contradiction / encoding
/// STOP. Mirrors `proveClient.ts`'s `isRedStatus`.
fn is_red_status(status: &str) -> bool {
    status == "unsatisfied" || status == "undecidable"
}

/// One non-discharged consistency row, resolved to an editor-anchorable
/// diagnostic: the range to squiggle, the three-fact message, and (when
/// reachable) the vendor's proven value for a Quick Fix.
#[derive(Debug, Clone)]
pub struct RowDiag {
    pub range: Range,
    pub message: String,
    pub proven_value: Option<String>,
}

fn resolve_row_file(file: &str, project_root: &Path) -> PathBuf {
    let p = PathBuf::from(file);
    if p.is_absolute() {
        p
    } else {
        project_root.join(p)
    }
}

fn same_file(a: &Path, b: &Path) -> bool {
    match (a.canonicalize(), b.canonicalize()) {
        (Ok(ca), Ok(cb)) => ca == cb,
        _ => a == b,
    }
}

/// Filter `rows` (the receipt's full row set) to the non-discharged
/// consistency rows anchored at `target_file`, and render each as a
/// `RowDiag`. Rows anchored at any OTHER file (a vendor's own internal
/// assertions, or a different consumer source) are dropped -- an editor
/// paints diagnostics for the open buffer, not the whole pool.
pub fn build_row_diags(rows: &[Json], target_file: &Path, project_root: &Path) -> Vec<RowDiag> {
    let mut out = Vec::new();
    for row in rows {
        let Some(property) = row.get("property").and_then(|v| v.as_str()) else {
            continue;
        };
        // Only consistency rows carry an assertion locus; only red ones squiggle.
        if !property.starts_with("consistency:") {
            continue;
        }
        let Some(status) = row.get("status").and_then(|v| v.as_str()) else {
            continue;
        };
        if !is_red_status(status) {
            continue;
        }
        let Some(file) = row.get("file").and_then(|v| v.as_str()) else {
            // No locus on this row: refuse to guess a line (no fake anchoring).
            continue;
        };
        let Some(line) = row.get("line").and_then(|v| v.as_u64()) else {
            continue;
        };
        let resolved = resolve_row_file(file, project_root);
        if !same_file(&resolved, target_file) {
            continue;
        }

        let column = row.get("column").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
        let line0 = (line as u32).saturating_sub(1);
        // Anchor at the locus; span the rest of the line so the squiggle is
        // visible (mirrors `proveToVsDiagnostic`'s `Number.MAX_SAFE_INTEGER`
        // end column).
        let range = Range {
            start: Position {
                line: line0,
                character: column,
            },
            end: Position {
                line: line0,
                character: u32::MAX,
            },
        };

        let verification = row.get("verification");
        let facts = ConjoinedFacts {
            vendor_universe_fol: verification
                .and_then(|v| v.get("vendorUniverseFol"))
                .and_then(|v| v.as_str()),
            client_fact_fol: verification
                .and_then(|v| v.get("clientFactFol"))
                .and_then(|v| v.as_str()),
            vendor_fact_fol: verification
                .and_then(|v| v.get("vendorFactFol"))
                .and_then(|v| v.as_str()),
        };
        let reason = row.get("reason").and_then(|v| v.as_str()).unwrap_or("");
        let message = fol_format::format_detail(&facts, status, reason);
        let proven_value = facts.vendor_fact_fol.and_then(fol_format::rhs_of);

        out.push(RowDiag {
            range,
            message,
            proven_value,
        });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn row(status: &str, file: &str, line: u64, verification: Json) -> Json {
        json!({
            "property": "consistency:demo.check#euf#c:1(2,3)::assertion",
            "status": status,
            "reason": "solver found a counterexample",
            "file": file,
            "line": line,
            "column": 4,
            "verification": verification,
        })
    }

    #[test]
    fn unsatisfied_row_at_target_file_becomes_a_diagnostic() {
        let project_root = std::env::temp_dir().join("prove-diag-test-a");
        std::fs::create_dir_all(&project_root).unwrap();
        let target = project_root.join("src").join("lib.rs");
        std::fs::create_dir_all(target.parent().unwrap()).unwrap();
        std::fs::write(&target, "fn main() {}").unwrap();

        let rows = vec![row(
            "unsatisfied",
            "src/lib.rs",
            3,
            json!({
                "vendorFactFol": "⊢ call:check(2,3) = 5",
                "clientFactFol": "⊢ call:check(2,3) = 6",
            }),
        )];
        let diags = build_row_diags(&rows, &target, &project_root);
        assert_eq!(diags.len(), 1, "expected one diagnostic: {diags:?}");
        assert_eq!(diags[0].range.start.line, 2);
        assert!(diags[0].message.contains("Vendor fact:"));
        assert_eq!(diags[0].proven_value.as_deref(), Some("5"));

        std::fs::remove_dir_all(&project_root).ok();
    }

    #[test]
    fn discharged_row_is_not_painted() {
        let project_root = PathBuf::from("/tmp/prove-diag-test-b");
        let target = project_root.join("src").join("lib.rs");
        let rows = vec![row("discharged", "src/lib.rs", 3, Json::Null)];
        let diags = build_row_diags(&rows, &target, &project_root);
        assert!(
            diags.is_empty(),
            "discharged rows must not squiggle: {diags:?}"
        );
    }

    #[test]
    fn row_anchored_at_a_different_file_is_dropped() {
        let project_root = PathBuf::from("/tmp/prove-diag-test-c");
        let target = project_root.join("src").join("lib.rs");
        let rows = vec![row("unsatisfied", "vendor/internal_test.py", 9, Json::Null)];
        let diags = build_row_diags(&rows, &target, &project_root);
        assert!(
            diags.is_empty(),
            "vendor-anchored rows must not paint the consumer buffer: {diags:?}"
        );
    }
}
