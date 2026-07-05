// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use serde::Serialize;
use serde_json::{json, Value};
use sugar_verifier::types::EffectSiteAnnotation;

pub const PANIC_ANNOTATIONS_RUNTIME_NAME: &str = "panic-annotations-runtime";
pub const PANIC_ANNOTATIONS_RUNTIME_ID: &str = "panic_annotations.census.joinable";
pub const PANIC_ANNOTATIONS_RUNTIME_DOMAIN: &str = "panic_annotations";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AnnotationCheckMode {
    // These modes intentionally parallel DoctorMode without importing it.
    // This module is a substrate census join used by doctor, self-check, and
    // future product surfaces; callers translate policy modes at the boundary.
    Structural,
    Strict,
    ReleaseGate,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AnnotationCheckStatus {
    Pass,
    Warn,
    Fail,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AnnotationCheckSeverity {
    Advisory,
    Hard,
}

#[derive(Debug, Clone)]
pub struct AnnotationRuntimeCheck {
    pub id: String,
    pub name: String,
    pub status: AnnotationCheckStatus,
    pub severity: AnnotationCheckSeverity,
    pub domain: String,
    pub detail: String,
    pub evidence: Value,
}

impl AnnotationRuntimeCheck {
    fn pass_with_severity(
        severity: AnnotationCheckSeverity,
        detail: impl Into<String>,
        evidence: Value,
    ) -> Self {
        Self::with_status_and_severity(AnnotationCheckStatus::Pass, severity, detail, evidence)
    }

    fn with_status_and_severity(
        status: AnnotationCheckStatus,
        severity: AnnotationCheckSeverity,
        detail: impl Into<String>,
        evidence: Value,
    ) -> Self {
        Self {
            id: PANIC_ANNOTATIONS_RUNTIME_ID.to_string(),
            name: PANIC_ANNOTATIONS_RUNTIME_NAME.to_string(),
            status,
            severity,
            domain: PANIC_ANNOTATIONS_RUNTIME_DOMAIN.to_string(),
            detail: detail.into(),
            evidence,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct PanicCensusRow {
    pub file: String,
    pub line: usize,
    pub callee: String,
    #[serde(rename = "callsiteBundleCid", skip_serializing_if = "Option::is_none")]
    pub callsite_bundle_cid: Option<String>,
    pub status: String,
    pub reason: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub category: Option<String>,
    #[serde(rename = "tierToClose", skip_serializing_if = "Option::is_none")]
    pub tier_to_close: Option<String>,
}

pub type AnnotatedPanicCensusRow = PanicCensusRow;

#[derive(Debug, Clone)]
pub struct AnnotationRuntimeOutcome {
    pub rows: Vec<AnnotatedPanicCensusRow>,
    pub check: AnnotationRuntimeCheck,
}

#[derive(Debug, Clone)]
pub struct AnnotationCheckError {
    pub check: AnnotationRuntimeCheck,
}

impl std::fmt::Display for AnnotationCheckError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.check.detail)
    }
}

impl std::error::Error for AnnotationCheckError {}

#[derive(Debug, Clone)]
struct RuntimeAnnotation {
    bundle_cid: Option<String>,
    file: String,
    line: usize,
    callee: String,
    status: String,
    category: String,
    tier_to_close: String,
    reason: String,
}

impl RuntimeAnnotation {
    fn key(&self) -> (String, usize, String) {
        (self.file.clone(), self.line, self.callee.clone())
    }

    fn scoped_key(&self) -> Option<(String, String, usize, String)> {
        self.bundle_cid.as_ref().map(|bundle| {
            (
                bundle.clone(),
                self.file.clone(),
                self.line,
                self.callee.clone(),
            )
        })
    }
}

#[derive(Debug, Clone)]
struct RuntimeAnnotationManifest {
    present: bool,
    annotations: Vec<RuntimeAnnotation>,
    issues: Vec<Value>,
}

pub fn annotation_runtime_check(
    target_path: &Path,
    panic_census: &[PanicCensusRow],
    mode: AnnotationCheckMode,
) -> Result<AnnotationRuntimeOutcome, AnnotationCheckError> {
    annotation_runtime_check_with_mementos(target_path, panic_census, &[], mode)
}

pub fn annotation_runtime_check_with_mementos(
    target_path: &Path,
    panic_census: &[PanicCensusRow],
    memento_annotations: &[EffectSiteAnnotation],
    mode: AnnotationCheckMode,
) -> Result<AnnotationRuntimeOutcome, AnnotationCheckError> {
    let manifest = runtime_annotation_manifest(target_path);
    if !manifest.present && memento_annotations.is_empty() {
        return Ok(AnnotationRuntimeOutcome {
            rows: panic_census.to_vec(),
            check: AnnotationRuntimeCheck::pass_with_severity(
                AnnotationCheckSeverity::Advisory,
                "no panic annotation manifest present",
                json!({
                    "manifestPresent": false,
                    "rowCount": panic_census.len(),
                }),
            ),
        });
    }

    let mut issues = manifest.issues;
    let memento_annotations = runtime_annotations_from_mementos(memento_annotations, &mut issues);
    let memento_annotation_count = memento_annotations.len();
    let mut rows = panic_census.to_vec();
    let before_k = count_proven_rows(&rows);
    let (row_index, scoped_row_index) = build_row_indexes(&rows, &mut issues);
    let mut annotated_rows = BTreeMap::<usize, String>::new();

    for annotation in manifest.annotations {
        apply_runtime_annotation(
            annotation,
            &row_index,
            &scoped_row_index,
            &mut annotated_rows,
            &mut rows,
            &mut issues,
        );
    }
    for annotation in memento_annotations {
        apply_runtime_annotation(
            annotation,
            &row_index,
            &scoped_row_index,
            &mut annotated_rows,
            &mut rows,
            &mut issues,
        );
    }

    let after_k = count_proven_rows(&rows);
    if before_k != after_k {
        issues.push(json!({
            "kind": "k_instability",
            "detail": format!("panic annotation runtime changed proven count from {before_k} to {after_k}"),
            "before": before_k,
            "after": after_k,
        }));
    }

    let evidence = json!({
        "manifestPresent": manifest.present,
        "rowCount": panic_census.len(),
        "mementoAnnotationCount": memento_annotation_count,
        "annotatedRowCount": rows
            .iter()
            .filter(|row| row.category.is_some() || row.tier_to_close.is_some())
            .count(),
        "errors": issues,
    });

    if evidence
        .get("errors")
        .and_then(Value::as_array)
        .map_or(false, |errors| !errors.is_empty())
    {
        let (status, severity) = annotation_drift_policy(mode);
        let check = AnnotationRuntimeCheck::with_status_and_severity(
            status,
            severity,
            format!(
                "panic annotation runtime check found {} drift issue(s)",
                evidence
                    .get("errors")
                    .and_then(Value::as_array)
                    .map(Vec::len)
                    .unwrap_or(0)
            ),
            evidence,
        );
        if mode == AnnotationCheckMode::Structural {
            Ok(AnnotationRuntimeOutcome { rows, check })
        } else {
            Err(AnnotationCheckError { check })
        }
    } else {
        Ok(AnnotationRuntimeOutcome {
            rows,
            check: AnnotationRuntimeCheck::pass_with_severity(
                AnnotationCheckSeverity::Advisory,
                "panic annotation manifest joins current panic census",
                evidence,
            ),
        })
    }
}

fn runtime_annotations_from_mementos(
    annotations: &[EffectSiteAnnotation],
    issues: &mut Vec<Value>,
) -> Vec<RuntimeAnnotation> {
    let mut out = Vec::new();
    let mut seen = BTreeMap::<(String, String, usize, String), String>::new();
    for annotation in annotations {
        let key = (
            annotation.bundle_cid.clone(),
            annotation.file.clone(),
            annotation.line,
            annotation.callee.clone(),
        );
        if let Some(previous) = seen.insert(key.clone(), annotation.memento_cid.clone()) {
            issues.push(json!({
                "kind": "effect-site-annotation-duplicate",
                "bundleCid": key.0,
                "file": key.1,
                "line": key.2,
                "callee": key.3,
                "firstMementoCid": previous,
                "secondMementoCid": annotation.memento_cid,
            }));
            continue;
        }
        out.push(RuntimeAnnotation {
            bundle_cid: Some(annotation.bundle_cid.clone()),
            file: annotation.file.clone(),
            line: annotation.line,
            callee: annotation.callee.clone(),
            status: annotation.status.clone(),
            category: annotation.category.clone(),
            tier_to_close: annotation.tier_to_close.clone(),
            reason: annotation.reason.clone(),
        });
    }
    out
}

fn apply_runtime_annotation(
    annotation: RuntimeAnnotation,
    row_index: &BTreeMap<(String, usize, String), Option<usize>>,
    scoped_row_index: &BTreeMap<(String, String, usize, String), Option<usize>>,
    annotated_rows: &mut BTreeMap<usize, String>,
    rows: &mut [PanicCensusRow],
    issues: &mut Vec<Value>,
) {
    let index = match annotation.scoped_key() {
        Some(scoped_key) => match scoped_row_index.get(&scoped_key).copied().flatten() {
            Some(index) => Some(index),
            None if scoped_row_index.contains_key(&scoped_key) => {
                issues.push(annotation_issue(
                    "panic-census-row-duplicate",
                    &format!(
                        "duplicate panic census row for scoped key {}:{} {} in bundle {}",
                        annotation.file, annotation.line, annotation.callee, scoped_key.0
                    ),
                    Some(&annotation),
                ));
                return;
            }
            None => None,
        },
        None => match row_index.get(&annotation.key()).copied().flatten() {
            Some(index) => Some(index),
            None if row_index.contains_key(&annotation.key()) => {
                issues.push(annotation_issue(
                    "panic-census-row-ambiguous",
                    &format!(
                        "ambiguous panic census row for unscoped annotation {}:{} {}",
                        annotation.file, annotation.line, annotation.callee
                    ),
                    Some(&annotation),
                ));
                return;
            }
            None => None,
        },
    };
    let Some(index) = index else {
        issues.push(annotation_issue(
            "stale",
            &format!(
                "stale panic-site annotation for {}:{} {}",
                annotation.file, annotation.line, annotation.callee
            ),
            Some(&annotation),
        ));
        return;
    };
    if let Some(previous) = annotated_rows.get(&index) {
        issues.push(annotation_issue(
            "effect-site-annotation-duplicate",
            &format!(
                "duplicate panic-site annotation for {}:{} {}; first source {previous}",
                annotation.file, annotation.line, annotation.callee
            ),
            Some(&annotation),
        ));
        return;
    }
    if rows[index].status == "proven" {
        issues.push(annotation_issue(
            "proven_site_collision",
            &format!(
                "proven panic-site annotation for {}:{} {}",
                annotation.file, annotation.line, annotation.callee
            ),
            Some(&annotation),
        ));
        return;
    }
    annotated_rows.insert(index, annotation_source(&annotation));
    rows[index].status = annotation.status;
    rows[index].category = Some(annotation.category);
    rows[index].tier_to_close = Some(annotation.tier_to_close);
    rows[index].reason = annotation.reason;
}

fn build_row_indexes(
    rows: &[PanicCensusRow],
    issues: &mut Vec<Value>,
) -> (
    BTreeMap<(String, usize, String), Option<usize>>,
    BTreeMap<(String, String, usize, String), Option<usize>>,
) {
    let mut row_index = BTreeMap::<(String, usize, String), Option<usize>>::new();
    let mut scoped_row_index = BTreeMap::<(String, String, usize, String), Option<usize>>::new();

    for (index, row) in rows.iter().enumerate() {
        let key = (row.file.clone(), row.line, row.callee.clone());
        match row_index.get_mut(&key) {
            Some(slot) => *slot = None,
            None => {
                row_index.insert(key, Some(index));
            }
        }

        let Some(bundle) = &row.callsite_bundle_cid else {
            continue;
        };
        let scoped_key = (
            bundle.clone(),
            row.file.clone(),
            row.line,
            row.callee.clone(),
        );
        match scoped_row_index.get_mut(&scoped_key) {
            Some(slot) => {
                *slot = None;
                issues.push(json!({
                    "kind": "panic-census-row-duplicate",
                    "bundleCid": scoped_key.0,
                    "file": scoped_key.1,
                    "line": scoped_key.2,
                    "callee": scoped_key.3,
                    "secondRowIndex": index,
                }));
            }
            None => {
                scoped_row_index.insert(scoped_key, Some(index));
            }
        }
    }

    (row_index, scoped_row_index)
}

fn annotation_source(annotation: &RuntimeAnnotation) -> String {
    annotation
        .bundle_cid
        .as_ref()
        .map(|bundle| format!("memento:{bundle}"))
        .unwrap_or_else(|| "manifest".to_string())
}

fn runtime_annotation_manifest(target_path: &Path) -> RuntimeAnnotationManifest {
    let path = target_path.join(".sugar").join("residue.toml");
    if !path.is_file() {
        return RuntimeAnnotationManifest {
            present: false,
            annotations: Vec::new(),
            issues: Vec::new(),
        };
    }

    let text = match fs::read_to_string(&path) {
        Ok(text) => text,
        Err(error) => {
            return RuntimeAnnotationManifest {
                present: true,
                annotations: Vec::new(),
                issues: vec![json!({
                    "kind": "malformed",
                    "path": path.display().to_string(),
                    "detail": format!("read panic annotation manifest: {error}"),
                })],
            };
        }
    };
    let value = match text.parse::<toml::Value>() {
        Ok(value) => value,
        Err(error) => {
            return RuntimeAnnotationManifest {
                present: true,
                annotations: Vec::new(),
                issues: vec![json!({
                    "kind": "malformed",
                    "path": path.display().to_string(),
                    "detail": format!("parse panic annotation manifest: {error}"),
                })],
            };
        }
    };

    let mut annotations = Vec::new();
    let mut issues = Vec::new();
    let mut seen = BTreeMap::<(String, usize, String), String>::new();
    collect_runtime_annotations(
        &value,
        "residue",
        "residue",
        &mut seen,
        &mut annotations,
        &mut issues,
    );
    collect_runtime_annotations(
        &value,
        "tier_to_close",
        "unproven",
        &mut seen,
        &mut annotations,
        &mut issues,
    );

    RuntimeAnnotationManifest {
        present: true,
        annotations,
        issues,
    }
}

fn collect_runtime_annotations(
    value: &toml::Value,
    table: &str,
    status: &str,
    seen: &mut BTreeMap<(String, usize, String), String>,
    annotations: &mut Vec<RuntimeAnnotation>,
    issues: &mut Vec<Value>,
) {
    let Some(entries) = value.get(table) else {
        return;
    };
    let Some(entries) = entries.as_array() else {
        issues.push(json!({
            "kind": "malformed",
            "table": table,
            "detail": format!("{table} must be an array of tables"),
        }));
        return;
    };
    for (index, entry) in entries.iter().enumerate() {
        match runtime_annotation_from_value(entry, table, index, status) {
            Ok(annotation) => {
                let key = annotation.key();
                if let Some(previous) = seen.insert(key.clone(), table.to_string()) {
                    issues.push(json!({
                        "kind": "duplicate",
                        "file": key.0,
                        "line": key.1,
                        "callee": key.2,
                        "firstTable": previous,
                        "secondTable": table,
                    }));
                } else {
                    annotations.push(annotation);
                }
            }
            Err(issue) => issues.push(issue),
        }
    }
}

fn runtime_annotation_from_value(
    entry: &toml::Value,
    table: &str,
    index: usize,
    status: &str,
) -> Result<RuntimeAnnotation, Value> {
    let file = runtime_annotation_str(entry, "file", table, index)?;
    let line = entry
        .get("line")
        .and_then(toml::Value::as_integer)
        .filter(|line| *line >= 0)
        .map(|line| line as usize)
        .ok_or_else(|| {
            annotation_malformed_issue(table, index, "line", "line must be a nonnegative integer")
        })?;
    let callee = runtime_annotation_str(entry, "callee", table, index)?;
    let category = runtime_annotation_str(entry, "category", table, index)?;
    let tier_to_close = entry
        .get("tier_to_close")
        .or_else(|| entry.get("tierToClose"))
        .and_then(toml::Value::as_str)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .ok_or_else(|| {
            annotation_malformed_issue(
                table,
                index,
                "tier_to_close",
                "tier_to_close must be a nonempty string",
            )
        })?;
    let reason = runtime_annotation_str(entry, "reason", table, index)?;
    Ok(RuntimeAnnotation {
        bundle_cid: None,
        file,
        line,
        callee,
        status: status.to_string(),
        category,
        tier_to_close,
        reason,
    })
}

fn runtime_annotation_str(
    entry: &toml::Value,
    field: &str,
    table: &str,
    index: usize,
) -> Result<String, Value> {
    entry
        .get(field)
        .and_then(toml::Value::as_str)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .ok_or_else(|| {
            annotation_malformed_issue(
                table,
                index,
                field,
                &format!("{field} must be a nonempty string"),
            )
        })
}

fn annotation_malformed_issue(table: &str, index: usize, field: &str, detail: &str) -> Value {
    json!({
        "kind": "malformed",
        "table": table,
        "index": index,
        "field": field,
        "detail": detail,
    })
}

fn annotation_issue(kind: &str, detail: &str, annotation: Option<&RuntimeAnnotation>) -> Value {
    let mut issue = json!({
        "kind": kind,
        "detail": detail,
    });
    if let (Some(obj), Some(annotation)) = (issue.as_object_mut(), annotation) {
        if let Some(bundle) = &annotation.bundle_cid {
            obj.insert("bundleCid".to_string(), Value::String(bundle.clone()));
        }
        obj.insert("file".to_string(), Value::String(annotation.file.clone()));
        obj.insert("line".to_string(), json!(annotation.line));
        obj.insert(
            "callee".to_string(),
            Value::String(annotation.callee.clone()),
        );
    }
    issue
}

fn count_proven_rows(rows: &[PanicCensusRow]) -> usize {
    rows.iter().filter(|row| row.status == "proven").count()
}

fn annotation_drift_policy(
    mode: AnnotationCheckMode,
) -> (AnnotationCheckStatus, AnnotationCheckSeverity) {
    match mode {
        AnnotationCheckMode::Structural => (
            AnnotationCheckStatus::Warn,
            AnnotationCheckSeverity::Advisory,
        ),
        AnnotationCheckMode::Strict | AnnotationCheckMode::ReleaseGate => {
            (AnnotationCheckStatus::Fail, AnnotationCheckSeverity::Hard)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn runtime_panic_row(file: &str, line: usize, callee: &str, status: &str) -> PanicCensusRow {
        PanicCensusRow {
            file: file.to_string(),
            line,
            callee: callee.to_string(),
            callsite_bundle_cid: None,
            status: status.to_string(),
            reason: "synthetic runtime row".to_string(),
            category: None,
            tier_to_close: None,
        }
    }

    fn runtime_panic_row_with_bundle(
        bundle: &str,
        file: &str,
        line: usize,
        callee: &str,
        status: &str,
    ) -> PanicCensusRow {
        PanicCensusRow {
            file: file.to_string(),
            line,
            callee: callee.to_string(),
            status: status.to_string(),
            reason: "synthetic runtime row".to_string(),
            category: None,
            tier_to_close: None,
            callsite_bundle_cid: Some(bundle.to_string()),
        }
    }

    fn effect_annotation(
        bundle: &str,
        file: &str,
        line: usize,
        callee: &str,
        status: &str,
        category: &str,
        tier_to_close: &str,
        reason: &str,
    ) -> EffectSiteAnnotation {
        EffectSiteAnnotation {
            effect_kind: "panic-freedom".to_string(),
            file: file.to_string(),
            line,
            callee: callee.to_string(),
            status: status.to_string(),
            category: category.to_string(),
            tier_to_close: tier_to_close.to_string(),
            reason: reason.to_string(),
            memento_cid: format!("blake3-512:memento-{line}"),
            bundle_cid: bundle.to_string(),
        }
    }

    fn write_runtime_annotation_manifest(target: &Path, body: &str) {
        let sugar = target.join(".sugar");
        fs::create_dir_all(&sugar).expect("create .sugar");
        fs::write(sugar.join("residue.toml"), body).expect("write residue manifest");
    }

    #[test]
    fn annotation_runtime_no_manifest_passes_with_unchanged_census() {
        let td = tempfile::tempdir().unwrap();
        let rows = vec![runtime_panic_row(
            "src/lib.rs",
            10,
            "method:expect",
            "unproven",
        )];

        let outcome = annotation_runtime_check(td.path(), &rows, AnnotationCheckMode::Strict)
            .expect("no manifest");

        assert_eq!(outcome.check.status, AnnotationCheckStatus::Pass);
        assert_eq!(
            outcome
                .check
                .evidence
                .get("manifestPresent")
                .and_then(Value::as_bool),
            Some(false)
        );
        assert_eq!(outcome.rows, rows);
    }

    #[test]
    fn annotation_runtime_valid_residue_enriches_unproven_row() {
        let td = tempfile::tempdir().unwrap();
        write_runtime_annotation_manifest(
            td.path(),
            r#"
[[residue]]
file = "src/lib.rs"
line = 10
callee = "method:expect"
category = "lock_poisoning_residue"
tier_to_close = "irreducible"
reason = "lock poisoning is runtime residue"
"#,
        );
        let rows = vec![runtime_panic_row(
            "src/lib.rs",
            10,
            "method:expect",
            "unproven",
        )];

        let outcome = annotation_runtime_check(td.path(), &rows, AnnotationCheckMode::Strict)
            .expect("valid residue");
        let row = &outcome.rows[0];

        assert_eq!(outcome.check.status, AnnotationCheckStatus::Pass);
        assert_eq!(row.status, "residue");
        assert_eq!(row.category.as_deref(), Some("lock_poisoning_residue"));
        assert_eq!(row.tier_to_close.as_deref(), Some("irreducible"));
        assert_eq!(row.reason, "lock poisoning is runtime residue");
    }

    #[test]
    fn annotation_runtime_valid_tier_to_close_preserves_unproven_status() {
        let td = tempfile::tempdir().unwrap();
        write_runtime_annotation_manifest(
            td.path(),
            r#"
[[tier_to_close]]
file = "src/lib.rs"
line = 10
callee = "method:expect"
category = "D-lib"
tier_to_close = "per-type totality proof"
reason = "close with a manifest-backed function postcondition"
"#,
        );
        let rows = vec![runtime_panic_row(
            "src/lib.rs",
            10,
            "method:expect",
            "unproven",
        )];

        let outcome = annotation_runtime_check(td.path(), &rows, AnnotationCheckMode::Strict)
            .expect("valid tier");
        let row = &outcome.rows[0];

        assert_eq!(row.status, "unproven");
        assert_eq!(row.category.as_deref(), Some("D-lib"));
        assert_eq!(
            row.tier_to_close.as_deref(),
            Some("per-type totality proof")
        );
    }

    #[test]
    fn annotation_runtime_stale_annotation_warns_in_structural() {
        let td = tempfile::tempdir().unwrap();
        write_runtime_annotation_manifest(
            td.path(),
            r#"
[[residue]]
file = "src/lib.rs"
line = 99
callee = "method:expect"
category = "lock_poisoning_residue"
tier_to_close = "irreducible"
reason = "stale row"
"#,
        );
        let rows = vec![runtime_panic_row(
            "src/lib.rs",
            10,
            "method:expect",
            "unproven",
        )];

        let outcome = annotation_runtime_check(td.path(), &rows, AnnotationCheckMode::Structural)
            .expect("warn only");

        assert_eq!(outcome.check.status, AnnotationCheckStatus::Warn);
        assert_eq!(outcome.check.severity, AnnotationCheckSeverity::Advisory);
        assert!(
            outcome.check.evidence.to_string().contains("stale"),
            "stale warning should be named: {:#?}",
            outcome.check
        );
        assert_eq!(outcome.rows, rows);
    }

    #[test]
    fn annotation_runtime_stale_annotation_fails_hard_in_strict() {
        let td = tempfile::tempdir().unwrap();
        write_runtime_annotation_manifest(
            td.path(),
            r#"
[[residue]]
file = "src/lib.rs"
line = 99
callee = "method:expect"
category = "lock_poisoning_residue"
tier_to_close = "irreducible"
reason = "stale row"
"#,
        );
        let rows = vec![runtime_panic_row(
            "src/lib.rs",
            10,
            "method:expect",
            "unproven",
        )];

        let err = annotation_runtime_check(td.path(), &rows, AnnotationCheckMode::Strict)
            .expect_err("strict stale annotations must fail");

        assert_eq!(err.check.status, AnnotationCheckStatus::Fail);
        assert_eq!(err.check.severity, AnnotationCheckSeverity::Hard);
        assert!(
            err.check.evidence.to_string().contains("src/lib.rs")
                && err.check.evidence.to_string().contains("99"),
            "strict stale evidence should name the entry: {:#?}",
            err.check
        );
    }

    #[test]
    fn annotation_runtime_duplicate_keys_fail_hard_in_release_gate() {
        let td = tempfile::tempdir().unwrap();
        write_runtime_annotation_manifest(
            td.path(),
            r#"
[[residue]]
file = "src/lib.rs"
line = 10
callee = "method:expect"
category = "first"
tier_to_close = "irreducible"
reason = "first"

[[tier_to_close]]
file = "src/lib.rs"
line = 10
callee = "method:expect"
category = "second"
tier_to_close = "later"
reason = "second"
"#,
        );
        let rows = vec![runtime_panic_row(
            "src/lib.rs",
            10,
            "method:expect",
            "unproven",
        )];

        let err = annotation_runtime_check(td.path(), &rows, AnnotationCheckMode::ReleaseGate)
            .expect_err("releaseGate duplicate annotations must fail");

        assert_eq!(err.check.status, AnnotationCheckStatus::Fail);
        assert!(
            err.check.evidence.to_string().contains("duplicate"),
            "duplicate evidence should be named: {:#?}",
            err.check
        );
    }

    #[test]
    fn annotation_runtime_unscoped_manifest_refuses_ambiguous_bundle_rows() {
        let td = tempfile::tempdir().unwrap();
        write_runtime_annotation_manifest(
            td.path(),
            r#"
[[residue]]
file = "src/lib.rs"
line = 10
callee = "method:expect"
category = "lock_poisoning_residue"
tier_to_close = "irreducible"
reason = "ambiguous without bundle"
"#,
        );
        let rows = vec![
            runtime_panic_row_with_bundle(
                "blake3-512:bundle-a",
                "src/lib.rs",
                10,
                "method:expect",
                "unproven",
            ),
            runtime_panic_row_with_bundle(
                "blake3-512:bundle-b",
                "src/lib.rs",
                10,
                "method:expect",
                "unproven",
            ),
        ];

        let err = annotation_runtime_check(td.path(), &rows, AnnotationCheckMode::Strict)
            .expect_err("unscoped annotation over bundle-ambiguous rows must fail");

        assert!(
            err.check.evidence.to_string().contains("ambiguous"),
            "ambiguous base-key evidence should be named: {:#?}",
            err.check
        );
    }

    #[test]
    fn annotation_runtime_scoped_memento_disambiguates_ambiguous_bundle_rows() {
        let td = tempfile::tempdir().unwrap();
        let rows = vec![
            runtime_panic_row_with_bundle(
                "blake3-512:bundle-a",
                "src/lib.rs",
                10,
                "method:expect",
                "unproven",
            ),
            runtime_panic_row_with_bundle(
                "blake3-512:bundle-b",
                "src/lib.rs",
                10,
                "method:expect",
                "unproven",
            ),
        ];
        let annotations = vec![effect_annotation(
            "blake3-512:bundle-b",
            "src/lib.rs",
            10,
            "method:expect",
            "residue",
            "lock_poisoning_residue",
            "irreducible",
            "scoped dependency memento",
        )];

        let outcome = annotation_runtime_check_with_mementos(
            td.path(),
            &rows,
            &annotations,
            AnnotationCheckMode::Strict,
        )
        .expect("bundle-scoped memento must disambiguate ambiguous base key");

        let annotated = outcome
            .rows
            .iter()
            .find(|row| row.callsite_bundle_cid.as_deref() == Some("blake3-512:bundle-b"))
            .expect("bundle-b row");
        assert_eq!(
            annotated.category.as_deref(),
            Some("lock_poisoning_residue")
        );
        assert_eq!(annotated.reason, "scoped dependency memento");
        let untouched = outcome
            .rows
            .iter()
            .find(|row| row.callsite_bundle_cid.as_deref() == Some("blake3-512:bundle-a"))
            .expect("bundle-a row");
        assert_eq!(untouched.category, None);
    }

    #[test]
    fn annotation_runtime_duplicate_scoped_rows_fail_closed() {
        let td = tempfile::tempdir().unwrap();
        let rows = vec![
            runtime_panic_row_with_bundle(
                "blake3-512:bundle-a",
                "src/lib.rs",
                10,
                "method:expect",
                "unproven",
            ),
            runtime_panic_row_with_bundle(
                "blake3-512:bundle-a",
                "src/lib.rs",
                10,
                "method:expect",
                "unproven",
            ),
        ];
        let annotations = vec![effect_annotation(
            "blake3-512:bundle-a",
            "src/lib.rs",
            10,
            "method:expect",
            "residue",
            "lock_poisoning_residue",
            "irreducible",
            "duplicate scoped row",
        )];

        let err = annotation_runtime_check_with_mementos(
            td.path(),
            &rows,
            &annotations,
            AnnotationCheckMode::Strict,
        )
        .expect_err("duplicate scoped rows must fail closed");

        assert!(
            err.check.evidence.to_string().contains("duplicate"),
            "duplicate scoped-row evidence should be named: {:#?}",
            err.check
        );
    }

    #[test]
    fn annotation_runtime_proven_site_collision_fails_hard() {
        let td = tempfile::tempdir().unwrap();
        write_runtime_annotation_manifest(
            td.path(),
            r#"
[[residue]]
file = "src/lib.rs"
line = 10
callee = "method:expect"
category = "lock_poisoning_residue"
tier_to_close = "irreducible"
reason = "should not annotate proven rows"
"#,
        );
        let rows = vec![runtime_panic_row(
            "src/lib.rs",
            10,
            "method:expect",
            "proven",
        )];

        let err = annotation_runtime_check(td.path(), &rows, AnnotationCheckMode::Strict)
            .expect_err("proven-site annotation must fail");

        assert_eq!(err.check.status, AnnotationCheckStatus::Fail);
        assert!(
            err.check
                .evidence
                .to_string()
                .contains("proven_site_collision"),
            "proven collision evidence should be typed: {:#?}",
            err.check
        );
    }

    #[test]
    fn annotation_runtime_malformed_manifest_warns_in_structural_and_fails_in_strict() {
        let td = tempfile::tempdir().unwrap();
        write_runtime_annotation_manifest(
            td.path(),
            r#"
[[residue]]
file = "src/lib.rs"
line = 10
callee = "method:expect"
category = "lock_poisoning_residue"
reason = "missing tier_to_close"
"#,
        );
        let rows = vec![runtime_panic_row(
            "src/lib.rs",
            10,
            "method:expect",
            "unproven",
        )];

        let structural =
            annotation_runtime_check(td.path(), &rows, AnnotationCheckMode::Structural)
                .expect("warn");
        assert_eq!(structural.check.status, AnnotationCheckStatus::Warn);
        assert!(
            structural.check.evidence.to_string().contains("malformed"),
            "structural malformed evidence should be typed: {:#?}",
            structural.check
        );

        let strict = annotation_runtime_check(td.path(), &rows, AnnotationCheckMode::Strict)
            .expect_err("strict malformed manifest must fail");
        assert_eq!(strict.check.status, AnnotationCheckStatus::Fail);
    }

    #[test]
    fn annotation_runtime_reports_all_drift_errors_together() {
        let td = tempfile::tempdir().unwrap();
        write_runtime_annotation_manifest(
            td.path(),
            r#"
[[residue]]
file = "src/lib.rs"
line = 10
callee = "method:expect"
category = "dup-one"
tier_to_close = "irreducible"
reason = "duplicate one"

[[tier_to_close]]
file = "src/lib.rs"
line = 10
callee = "method:expect"
category = "dup-two"
tier_to_close = "later"
reason = "duplicate two"

[[residue]]
file = "src/lib.rs"
line = 99
callee = "method:expect"
category = "stale"
tier_to_close = "irreducible"
reason = "stale"
"#,
        );
        let rows = vec![runtime_panic_row(
            "src/lib.rs",
            10,
            "method:expect",
            "proven",
        )];

        let err = annotation_runtime_check(td.path(), &rows, AnnotationCheckMode::Strict)
            .expect_err("multiple drift errors must fail");
        let evidence = err.check.evidence.to_string();

        assert!(evidence.contains("duplicate"), "{evidence}");
        assert!(evidence.contains("stale"), "{evidence}");
        assert!(evidence.contains("proven_site_collision"), "{evidence}");
    }

    #[test]
    fn annotation_runtime_preserves_proven_count() {
        let td = tempfile::tempdir().unwrap();
        write_runtime_annotation_manifest(
            td.path(),
            r#"
[[residue]]
file = "src/lib.rs"
line = 20
callee = "method:expect"
category = "lock_poisoning_residue"
tier_to_close = "irreducible"
reason = "runtime residue"
"#,
        );
        let rows = vec![
            runtime_panic_row("src/lib.rs", 10, "method:expect", "proven"),
            runtime_panic_row("src/lib.rs", 20, "method:expect", "unproven"),
        ];

        let before = rows.iter().filter(|row| row.status == "proven").count();
        let outcome =
            annotation_runtime_check(td.path(), &rows, AnnotationCheckMode::Strict).expect("valid");
        let after = outcome
            .rows
            .iter()
            .filter(|row| row.status == "proven")
            .count();

        assert_eq!(before, after, "annotation must not move K");
    }

    #[test]
    fn annotation_runtime_memento_annotation_enriches_matching_bundle_row() {
        let td = tempfile::tempdir().unwrap();
        let rows = vec![runtime_panic_row_with_bundle(
            "blake3-512:dep-bundle",
            "src/lib.rs",
            10,
            "method:expect",
            "unproven",
        )];
        let annotations = vec![effect_annotation(
            "blake3-512:dep-bundle",
            "src/lib.rs",
            10,
            "method:expect",
            "residue",
            "dependency_memento_residue",
            "irreducible",
            "dependency memento residue",
        )];

        let outcome = annotation_runtime_check_with_mementos(
            td.path(),
            &rows,
            &annotations,
            AnnotationCheckMode::Strict,
        )
        .expect("memento annotation");
        let row = &outcome.rows[0];

        assert_eq!(row.status, "residue");
        assert_eq!(row.category.as_deref(), Some("dependency_memento_residue"));
        assert_eq!(row.reason, "dependency memento residue");
    }

    #[test]
    fn annotation_runtime_manifest_and_memento_distinct_keys_union() {
        let td = tempfile::tempdir().unwrap();
        write_runtime_annotation_manifest(
            td.path(),
            r#"
[[residue]]
file = "src/local.rs"
line = 1
callee = "method:unwrap"
category = "lock_poisoning_residue"
tier_to_close = "irreducible"
reason = "local manifest residue"
"#,
        );
        let rows = vec![
            runtime_panic_row("src/local.rs", 1, "method:unwrap", "unproven"),
            runtime_panic_row_with_bundle(
                "blake3-512:dep-bundle",
                "src/dep.rs",
                2,
                "method:expect",
                "unproven",
            ),
        ];
        let annotations = vec![effect_annotation(
            "blake3-512:dep-bundle",
            "src/dep.rs",
            2,
            "method:expect",
            "unproven",
            "D-lib",
            "future totality proof",
            "dependency memento tier",
        )];

        let outcome = annotation_runtime_check_with_mementos(
            td.path(),
            &rows,
            &annotations,
            AnnotationCheckMode::Strict,
        )
        .expect("union");

        assert_eq!(outcome.rows.len(), 2);
        assert_eq!(
            outcome.rows[0].category.as_deref(),
            Some("lock_poisoning_residue")
        );
        assert_eq!(outcome.rows[1].category.as_deref(), Some("D-lib"));
    }

    #[test]
    fn annotation_runtime_manifest_and_memento_same_key_fails_closed() {
        let td = tempfile::tempdir().unwrap();
        write_runtime_annotation_manifest(
            td.path(),
            r#"
[[residue]]
file = "src/lib.rs"
line = 10
callee = "method:expect"
category = "lock_poisoning_residue"
tier_to_close = "irreducible"
reason = "local manifest residue"
"#,
        );
        let rows = vec![runtime_panic_row_with_bundle(
            "blake3-512:target-bundle",
            "src/lib.rs",
            10,
            "method:expect",
            "unproven",
        )];
        let annotations = vec![effect_annotation(
            "blake3-512:target-bundle",
            "src/lib.rs",
            10,
            "method:expect",
            "unproven",
            "D-lib",
            "future totality proof",
            "duplicate memento annotation",
        )];

        let err = annotation_runtime_check_with_mementos(
            td.path(),
            &rows,
            &annotations,
            AnnotationCheckMode::Strict,
        )
        .expect_err("duplicate manifest/memento annotation must fail closed");

        assert!(
            err.check
                .evidence
                .to_string()
                .contains("effect-site-annotation-duplicate"),
            "duplicate evidence should carry structured tag: {:#?}",
            err.check
        );
    }

    #[test]
    fn annotation_runtime_stale_memento_annotation_fails_hard() {
        let td = tempfile::tempdir().unwrap();
        let rows = vec![runtime_panic_row_with_bundle(
            "blake3-512:dep-bundle",
            "src/live.rs",
            1,
            "method:expect",
            "unproven",
        )];
        let annotations = vec![effect_annotation(
            "blake3-512:dep-bundle",
            "src/stale.rs",
            99,
            "method:expect",
            "residue",
            "stale",
            "irreducible",
            "stale dependency memento residue",
        )];

        let err = annotation_runtime_check_with_mementos(
            td.path(),
            &rows,
            &annotations,
            AnnotationCheckMode::Strict,
        )
        .expect_err("strict stale memento annotation must fail");

        assert!(
            err.check.evidence.to_string().contains("stale"),
            "stale evidence should be named: {:#?}",
            err.check
        );
    }

    #[test]
    fn annotation_runtime_memento_annotation_on_proven_site_fails_closed() {
        let td = tempfile::tempdir().unwrap();
        let rows = vec![runtime_panic_row_with_bundle(
            "blake3-512:dep-bundle",
            "src/lib.rs",
            10,
            "method:expect",
            "proven",
        )];
        let annotations = vec![effect_annotation(
            "blake3-512:dep-bundle",
            "src/lib.rs",
            10,
            "method:expect",
            "residue",
            "lock_poisoning_residue",
            "irreducible",
            "should not annotate proven rows",
        )];

        let err = annotation_runtime_check_with_mementos(
            td.path(),
            &rows,
            &annotations,
            AnnotationCheckMode::Strict,
        )
        .expect_err("proven-site memento annotation must fail");

        assert!(
            err.check
                .evidence
                .to_string()
                .contains("proven_site_collision"),
            "proven collision evidence should be typed: {:#?}",
            err.check
        );
    }

    #[test]
    fn annotation_runtime_memento_annotations_preserve_proven_count() {
        let td = tempfile::tempdir().unwrap();
        let rows = vec![
            runtime_panic_row_with_bundle(
                "blake3-512:dep-bundle",
                "src/lib.rs",
                10,
                "method:expect",
                "proven",
            ),
            runtime_panic_row_with_bundle(
                "blake3-512:dep-bundle",
                "src/lib.rs",
                20,
                "method:expect",
                "unproven",
            ),
        ];
        let annotations = vec![effect_annotation(
            "blake3-512:dep-bundle",
            "src/lib.rs",
            20,
            "method:expect",
            "residue",
            "lock_poisoning_residue",
            "irreducible",
            "runtime residue",
        )];
        let before = rows.iter().filter(|row| row.status == "proven").count();

        let outcome = annotation_runtime_check_with_mementos(
            td.path(),
            &rows,
            &annotations,
            AnnotationCheckMode::Strict,
        )
        .expect("valid memento annotation");
        let after = outcome
            .rows
            .iter()
            .filter(|row| row.status == "proven")
            .count();

        assert_eq!(before, after, "annotation mementos must not move K");
    }

    #[test]
    fn annotation_runtime_check_is_not_coupled_to_self_check_scoreboard() {
        let source = include_str!("panic_annotations_runtime.rs");
        let start = source
            .find("pub fn annotation_runtime_check")
            .expect("annotation runtime function");
        let body = &source[start
            ..source[start..]
                .find("fn runtime_annotation_manifest")
                .unwrap()
                + start];

        assert!(!body.contains("SelfCheckScoreboard"));
        assert!(!body.contains("cmd_self_check"));
    }
}
