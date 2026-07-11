// SPDX-License-Identifier: MIT OR Apache-2.0
//
// report_mode.rs: project the dual-axis report into paint ranges for the IDE.
//
// #4149 — Report mode is sugar-lsp product surface, not the VS host.
//
// Palette (locked):
//   blue   = facts (under oath)
//   green  = dig/walk still open
//   red    = dig-stop effect (walk) OR crime
//   yellow = Minority / ungoverned (voiceless)
//   unsat  = prove channel (red squiggle; separate from dig-stop)
//
// P1 projects prove consistency rows into fact/unsat ranges. Factory dig-stop
// green→red and Minority yellow join when liftCoverage/factoryWalk feed this
// module (same numbers as `sugar lift --report --visual`).

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::Value as Json;
use tower_lsp::lsp_types::{Position, Range};

/// Paint kind for report mode. Wire string is stable for the VS host.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReportPaint {
    /// FACT — warranted, under oath.
    Fact,
    /// Dig/walk still open.
    WalkOpen,
    /// Effect that stops a dig.
    DigStop,
    /// Minority / voiceless body.
    Minority,
    /// Crime 1 — silently_unaccounted.
    Silent,
    /// Crime 2 — forged warrant.
    Forged,
    /// Prove unsat (diagnostic channel; not dig-stop).
    Unsat,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ReportModeRange {
    pub kind: ReportPaint,
    pub range: Range,
    pub label: String,
    /// Optional source excerpt (Minority / silent) — prefer full body later.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct ReportModeTotals {
    pub stated: u64,
    pub accounted: u64,
    pub silently_unaccounted: u64,
    pub minority_present: u64,
    pub minority_dug: u64,
    pub minority_un_asserted: u64,
    /// Prove-channel counts for this buffer.
    pub facts: u64,
    pub unsat: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ReportModePayload {
    pub uri: String,
    pub totals: ReportModeTotals,
    pub ranges: Vec<ReportModeRange>,
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

fn locus_range(row: &Json) -> Option<Range> {
    let line = row.get("line").and_then(|v| v.as_u64())?;
    if line == 0 {
        return None;
    }
    let column = row.get("column").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
    let line0 = (line as u32).saturating_sub(1);
    Some(Range {
        start: Position {
            line: line0,
            character: column,
        },
        end: Position {
            line: line0,
            character: u32::MAX,
        },
    })
}

/// Project prove consistency rows into report-mode paint for `target_file`.
///
/// * `discharged` / non-red status → **Fact** (blue)
/// * `unsatisfied` / `undecidable` → **Unsat** (prove red squiggle channel)
///
/// Dig-stop / Minority / silent / forged require liftCoverage feed (later).
pub fn project_from_prove_rows(
    uri: &str,
    rows: &[Json],
    target_file: &Path,
    project_root: &Path,
) -> ReportModePayload {
    let mut ranges = Vec::new();
    let mut facts = 0u64;
    let mut unsat = 0u64;

    for row in rows {
        let Some(property) = row.get("property").and_then(|v| v.as_str()) else {
            continue;
        };
        if !property.starts_with("consistency:") {
            continue;
        }
        let Some(status) = row.get("status").and_then(|v| v.as_str()) else {
            continue;
        };
        let Some(file) = row.get("file").and_then(|v| v.as_str()) else {
            continue;
        };
        let resolved = resolve_row_file(file, project_root);
        if !same_file(&resolved, target_file) {
            continue;
        }
        let Some(range) = locus_range(row) else {
            continue;
        };

        let is_unsat = status == "unsatisfied" || status == "undecidable";
        if is_unsat {
            unsat += 1;
            ranges.push(ReportModeRange {
                kind: ReportPaint::Unsat,
                range,
                label: format!("UNSAT {status}"),
                source: None,
            });
        } else if status == "discharged" || status == "sat" || status == "proven" {
            // "discharged" is the prove success wire; accept common aliases.
            facts += 1;
            ranges.push(ReportModeRange {
                kind: ReportPaint::Fact,
                range,
                label: "FACT".to_string(),
                source: None,
            });
        }
    }

    ReportModePayload {
        uri: uri.to_string(),
        totals: ReportModeTotals {
            // Full dual-axis totals when liftCoverage is wired; prove slice for now.
            stated: facts + unsat,
            accounted: facts,
            silently_unaccounted: 0,
            minority_present: 0,
            minority_dug: 0,
            minority_un_asserted: 0,
            facts,
            unsat,
        },
        ranges,
    }
}

/// Merge liftCoverage minority/silent/forged loci into an existing payload.
pub fn merge_lift_coverage(payload: &mut ReportModePayload, coverage: &Json, project_root: &Path) {
    let totals = coverage.get("totals").cloned().unwrap_or(Json::Null);
    let assertions = coverage.get("assertions").cloned().unwrap_or(Json::Null);
    let minority = coverage.get("minority").cloned().unwrap_or(Json::Null);

    if let Some(n) = totals.get("stated").and_then(|v| v.as_u64()) {
        payload.totals.stated = n;
    }
    if let Some(n) = totals.get("accounted").and_then(|v| v.as_u64()) {
        payload.totals.accounted = n;
    }
    if let Some(n) = totals
        .get("silently_unaccounted")
        .or_else(|| assertions.get("silently_unaccounted"))
        .and_then(|v| v.as_u64())
    {
        payload.totals.silently_unaccounted = n;
    }
    if let Some(n) = totals
        .get("minority_present")
        .or_else(|| minority.get("present"))
        .and_then(|v| v.as_u64())
    {
        payload.totals.minority_present = n;
    }
    if let Some(n) = totals
        .get("minority_dug")
        .or_else(|| minority.get("dug"))
        .and_then(|v| v.as_u64())
    {
        payload.totals.minority_dug = n;
    }
    if let Some(n) = totals
        .get("minority_un_asserted")
        .or_else(|| minority.get("un_asserted"))
        .and_then(|v| v.as_u64())
    {
        payload.totals.minority_un_asserted = n;
    }

    if let Some(silent) = assertions.get("silent_loci").and_then(|v| v.as_array()) {
        for locus in silent {
            if let Some(r) = locus_to_range(locus, project_root) {
                let preview = locus
                    .get("preview")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                payload.ranges.push(ReportModeRange {
                    kind: ReportPaint::Silent,
                    range: r,
                    label: "Crime 1 silent".to_string(),
                    source: if preview.is_empty() {
                        None
                    } else {
                        Some(preview)
                    },
                });
            }
        }
    }

    if let Some(un) = minority.get("un_asserted_loci").and_then(|v| v.as_array()) {
        for locus in un {
            if let Some(r) = body_locus_to_range(locus, project_root) {
                let name = locus
                    .get("qualname")
                    .or_else(|| locus.get("name"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("?");
                payload.ranges.push(ReportModeRange {
                    kind: ReportPaint::Minority,
                    range: r,
                    label: format!("Minority {name}"),
                    source: None,
                });
            }
        }
    }

    if let Some(crime2) = coverage.get("crime2") {
        if let Some(forged) = crime2.get("forged_loci").and_then(|v| v.as_array()) {
            for locus in forged {
                if let Some(r) = locus_to_range(locus, project_root) {
                    payload.ranges.push(ReportModeRange {
                        kind: ReportPaint::Forged,
                        range: r,
                        label: "Crime 2 forged".to_string(),
                        source: None,
                    });
                }
            }
        }
    }
}

fn locus_to_range(locus: &Json, _project_root: &Path) -> Option<Range> {
    let line = locus.get("line").and_then(|v| v.as_u64())?;
    if line == 0 {
        return None;
    }
    let col = locus
        .get("col")
        .or_else(|| locus.get("column"))
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as u32;
    let line0 = (line as u32).saturating_sub(1);
    Some(Range {
        start: Position {
            line: line0,
            character: col,
        },
        end: Position {
            line: line0,
            character: u32::MAX,
        },
    })
}

fn body_locus_to_range(locus: &Json, project_root: &Path) -> Option<Range> {
    let line = locus.get("line").and_then(|v| v.as_u64())?;
    if line == 0 {
        return None;
    }
    let start = (line as u32).saturating_sub(1);
    // Prefer end_line when present; else load indent suite from disk.
    if let Some(end) = locus
        .get("end_line")
        .or_else(|| locus.get("endLine"))
        .and_then(|v| v.as_u64())
    {
        let end0 = (end as u32).saturating_sub(1).max(start);
        return Some(Range {
            start: Position {
                line: start,
                character: 0,
            },
            end: Position {
                line: end0,
                character: u32::MAX,
            },
        });
    }
    let file = locus.get("file").and_then(|v| v.as_str())?;
    let path = {
        let p = Path::new(file);
        if p.is_absolute() {
            p.to_path_buf()
        } else {
            project_root.join(p)
        }
    };
    let source = std::fs::read_to_string(path).ok()?;
    let lines: Vec<&str> = source.lines().collect();
    let idx = (line as usize).saturating_sub(1);
    if idx >= lines.len() {
        return None;
    }
    let header_indent = lines[idx].chars().take_while(|c| c.is_whitespace()).count();
    let mut end_idx = idx + 1;
    let max_end = (idx + 64).min(lines.len());
    while end_idx < max_end {
        let l = lines[end_idx];
        if l.trim().is_empty() {
            end_idx += 1;
            continue;
        }
        let indent = l.chars().take_while(|c| c.is_whitespace()).count();
        if indent <= header_indent {
            break;
        }
        end_idx += 1;
    }
    let end_line0 = (end_idx as u32).saturating_sub(1).max(start);
    Some(Range {
        start: Position {
            line: start,
            character: 0,
        },
        end: Position {
            line: end_line0,
            character: u32::MAX,
        },
    })
}


/// Merge factory walk rows into dig green→red paint for `target_file`.
///
/// * warranted / support / complete → **WalkOpen** (green — dig may continue)
/// * unresolved / gap / effect / incomplete boundary → **DigStop** (red — effect stops dig)
pub fn merge_factory_walk(
    payload: &mut ReportModePayload,
    factory_walk: &[Json],
    target_file: &Path,
    project_root: &Path,
) {
    for row in factory_walk {
        let status = row
            .get("status")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        let verdict = row
            .get("verdict")
            .or_else(|| row.get("output"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_ascii_lowercase();

        let Some((range, file_hint)) = factory_row_range(row, project_root) else {
            continue;
        };
        if let Some(ref f) = file_hint {
            let resolved = resolve_row_file(f, project_root);
            if !same_file(&resolved, target_file) {
                let tf = target_file.file_name().and_then(|s| s.to_str()).unwrap_or("");
                let rf = resolved.file_name().and_then(|s| s.to_str()).unwrap_or("");
                if !tf.is_empty() && tf != rf {
                    continue;
                }
            }
        }

        let is_stop = matches!(
            status.as_str(),
            "unresolved" | "boundary" | "effect" | "incomplete"
        ) || matches!(verdict.as_str(), "gap" | "effect" | "red" | "incomplete");
        let is_open = matches!(
            status.as_str(),
            "warranted" | "support" | "complete" | "inactive"
        ) || matches!(verdict.as_str(), "warranted" | "green" | "complete");

        let reason = row
            .get("reason")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        if is_stop {
            payload.ranges.push(ReportModeRange {
                kind: ReportPaint::DigStop,
                range,
                label: if reason.is_empty() {
                    format!("DIG-STOP {status}/{verdict}")
                } else {
                    format!("DIG-STOP {reason}")
                },
                source: None,
            });
        } else if is_open {
            payload.ranges.push(ReportModeRange {
                kind: ReportPaint::WalkOpen,
                range,
                label: "DIG-OPEN".to_string(),
                source: None,
            });
        }
    }
}

fn factory_row_range(row: &Json, _project_root: &Path) -> Option<(Range, Option<String>)> {
    if let Some(memento) = row.get("sourceMemento").or_else(|| row.get("source_memento")) {
        if let Some(span) = memento.get("span") {
            let start_line = span.get("start_line").and_then(|v| v.as_u64()).unwrap_or(0);
            if start_line > 0 {
                let end_line = span
                    .get("end_line")
                    .and_then(|v| v.as_u64())
                    .unwrap_or(start_line)
                    .max(start_line);
                let start_col = span.get("start_col").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
                let file = memento
                    .get("file")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());
                return Some((
                    Range {
                        start: Position {
                            line: (start_line as u32).saturating_sub(1),
                            character: start_col,
                        },
                        end: Position {
                            line: (end_line as u32).saturating_sub(1),
                            character: u32::MAX,
                        },
                    },
                    file,
                ));
            }
        }
    }
    let line = row.get("line").and_then(|v| v.as_u64()).unwrap_or(0);
    if line == 0 {
        return None;
    }
    let col = row
        .get("col")
        .or_else(|| row.get("column"))
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as u32;
    let file = row.get("file").and_then(|v| v.as_str()).map(|s| s.to_string());
    Some((
        Range {
            start: Position {
                line: (line as u32).saturating_sub(1),
                character: col,
            },
            end: Position {
                line: (line as u32).saturating_sub(1),
                character: u32::MAX,
            },
        },
        file,
    ))
}

/// Apply kit lift-report response (factoryWalk + liftCoverage) onto payload.
pub fn merge_report_lift_response(
    payload: &mut ReportModePayload,
    response: &Json,
    target_file: &Path,
    project_root: &Path,
) {
    if let Some(coverage) = response
        .get("liftCoverage")
        .or_else(|| response.get("lift_coverage"))
    {
        merge_lift_coverage(payload, coverage, project_root);
    }
    let walk = response
        .get("factoryAuditSummary")
        .and_then(|s| s.get("factoryWalk"))
        .or_else(|| response.get("factoryWalk"))
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    if !walk.is_empty() {
        merge_factory_walk(payload, &walk, target_file, project_root);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn prove_rows_project_fact_and_unsat() {
        let rows = vec![
            json!({
                "property": "consistency:foo",
                "status": "discharged",
                "file": "/tmp/t.py",
                "line": 10,
                "column": 4
            }),
            json!({
                "property": "consistency:bar",
                "status": "unsatisfied",
                "file": "/tmp/t.py",
                "line": 20,
                "column": 0
            }),
        ];
        let path = PathBuf::from("/tmp/t.py");
        let payload = project_from_prove_rows("file:///tmp/t.py", &rows, &path, Path::new("/tmp"));
        assert_eq!(payload.totals.facts, 1);
        assert_eq!(payload.totals.unsat, 1);
        assert_eq!(payload.ranges.len(), 2);
        assert_eq!(payload.ranges[0].kind, ReportPaint::Fact);
        assert_eq!(payload.ranges[1].kind, ReportPaint::Unsat);
    }

    #[test]
    fn merge_factory_walk_green_until_red() {
        let mut payload = ReportModePayload {
            uri: "file:///tmp/t.py".into(),
            totals: ReportModeTotals::default(),
            ranges: vec![],
        };
        let walk = vec![
            json!({
                "status": "warranted",
                "verdict": "warranted",
                "file": "/tmp/t.py",
                "line": 3
            }),
            json!({
                "status": "unresolved",
                "verdict": "gap",
                "reason": "FactoryGap",
                "file": "/tmp/t.py",
                "line": 8
            }),
        ];
        merge_factory_walk(
            &mut payload,
            &walk,
            Path::new("/tmp/t.py"),
            Path::new("/tmp"),
        );
        assert!(payload.ranges.iter().any(|r| r.kind == ReportPaint::WalkOpen));
        assert!(payload.ranges.iter().any(|r| r.kind == ReportPaint::DigStop));
    }

    #[test]
    fn merge_silent_and_minority_from_coverage() {
        let mut payload = ReportModePayload {
            uri: "file:///tmp/t.py".into(),
            totals: ReportModeTotals::default(),
            ranges: vec![],
        };
        let coverage = json!({
            "totals": {
                "stated": 2,
                "accounted": 1,
                "silently_unaccounted": 1,
                "minority_present": 1,
                "minority_dug": 0,
                "minority_un_asserted": 1
            },
            "assertions": {
                "silently_unaccounted": 1,
                "silent_loci": [{"file": "/tmp/t.py", "line": 5, "preview": "assert not x"}]
            },
            "minority": {
                "present": 1,
                "dug": 0,
                "un_asserted": 1,
                "un_asserted_loci": [{"file": "/tmp/t.py", "line": 1, "name": "orphan", "end_line": 2}]
            }
        });
        merge_lift_coverage(&mut payload, &coverage, Path::new("/tmp"));
        assert_eq!(payload.totals.silently_unaccounted, 1);
        assert_eq!(payload.totals.minority_un_asserted, 1);
        assert!(payload.ranges.iter().any(|r| r.kind == ReportPaint::Silent));
        assert!(payload
            .ranges
            .iter()
            .any(|r| r.kind == ReportPaint::Minority));
    }
}
