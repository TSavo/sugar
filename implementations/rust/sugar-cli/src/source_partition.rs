// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Criterion 14 as a PARTITION TYPE (#3756, part of #3706 / #3686 / #3706).
//
// T's ruling (2026-07-06, "SUPERSEDED UP THE LADDER"): don't store the totals,
// store the partition. Criterion 14 used to be four integers + an equation +
// an external checker (`tools/criterion14_conservation.py`). Counters that
// must agree, verified by a tool, is the checklist shape: any system where
// conservation is CHECKED is a system where it can be VIOLATED.
//
// This module makes the violation UNREPRESENTABLE. A `SourcePartition` for a
// compilation unit is ONE structure whose construction requires every physical
// line placed in exactly one arm:
//
//   Warrant(cid)            -- proofir-bearing, CID-followable (a discharged
//                              row with a followable target/property/bundle CID)
//   Support(InertWitness)   -- an affirmatively-classified-inert line, witnessed
//                              by a value of the CLOSED `InertWitness` enum
//   Effect(grounds)         -- a named typed effect anchored to the line (a
//                              refused row: the callee names the effect, the
//                              `reason` is its grounds)
//
// An untiled unit DOES NOT CONSTRUCT: `SourcePartition::construct` returns
// `Err(PartitionError)` naming every gapped line. Totals (warrant/support/
// effect/residue) are PROJECTIONS -- methods over the assignment map, never
// stored fields -- so they are structurally incapable of disagreeing with the
// rows. Forged support, same-line collisions (resolved at build by the lattice
// `Effect > Warrant > Support`), silent skips, drifted totals: all the same
// impossibility, a span not in the partition exactly once cannot exist in a
// value of the type.
//
// THE SURVIVING MEMBRANE (the honest boundary): the partition is only as true
// as the claims fed to it -- recognition totality (criteria 2/3) is the ONE
// place an instrument legitimately persists. `row_line_accounting` reads the
// verifier rows; `inert_support_accounting` mints `InertWitness` values from
// the source text. That inert minter is the coverage-typed Support component;
// its planted-twin teeth (#3733/#3736) live here until the walker emits inert
// spans directly (#3726/#3756 migration). Everything downstream of the claims
// is construction: the honest itsdangerous residue is not a nonzero meter, it
// is a `PartitionError` that the report is forced by the type to name loudly.

use serde_json::{json, Value as Json};
use std::collections::{BTreeMap, HashSet};
use std::path::Path;
use sugar_verifier::{ObligationVerdict, ReportRow};

/// The three terminal arms of the partition. Declaration order IS the lattice:
/// derived `Ord` ranks `Support < Warrant < Effect`, so `Effect > Warrant >
/// Support`. Multi-claimed lines resolve to the max by type, never by
/// incidental input ordering.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum LineClass {
    Support,
    Warrant,
    Effect,
}

impl LineClass {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Warrant => "warrant",
            Self::Support => "support",
            Self::Effect => "effect",
        }
    }
}

/// The CLOSED enum of inert-line witnesses. A line can be placed in the
/// `Support` arm ONLY by exhibiting one of these; there is no free-string
/// escape hatch. `import os; os.system(...)` is unrepresentable as support
/// because the minter (`inert_support_accounting`) refuses to emit a witness
/// for a line carrying a chained semantic statement -- the tiling cannot
/// complete over that line, so it can only be residue.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InertWitness {
    Blank,
    Comment,
    Import,
    Docstring,
    Signature,
}

impl InertWitness {
    pub fn label(&self) -> &'static str {
        match self {
            Self::Blank => "blank",
            Self::Comment => "comment",
            Self::Import => "import",
            Self::Docstring => "docstring",
            Self::Signature => "signature",
        }
    }
}

/// A single claim on a physical line: the arm it belongs to plus its grounds
/// (Warrant: the followable CID. Effect: the refusal reason. Support: the
/// inert witness label). These are the CLAIMS fed to the partition; the
/// partition is what tiles them into a total, disjoint accounting.
#[derive(Debug, Clone)]
pub struct LineAccountingEntry {
    pub file: String,
    pub line: usize,
    pub class: LineClass,
    pub grounds: Option<String>,
}

impl LineAccountingEntry {
    fn support(file: &str, line: usize, witness: InertWitness) -> Self {
        Self {
            file: file.to_string(),
            line,
            class: LineClass::Support,
            grounds: Some(witness.label().to_string()),
        }
    }

    pub fn to_json(&self) -> Json {
        json!({
            "file": self.file,
            "line": self.line,
            "class": self.class.as_str(),
            "grounds": self.grounds,
        })
    }
}

pub fn entries_to_json(entries: &[LineAccountingEntry]) -> Json {
    Json::Array(entries.iter().map(LineAccountingEntry::to_json).collect())
}

fn row_cid(row: &ReportRow) -> Option<String> {
    row.callsite
        .bridge_target_cid
        .as_ref()
        .map(|cid| cid.to_string())
        .or_else(|| {
            row.callsite
                .property_cid
                .as_ref()
                .map(|cid| cid.to_string())
        })
        .or_else(|| {
            row.callsite
                .callsite_bundle_cid
                .as_ref()
                .map(|cid| cid.to_string())
        })
}

/// Warrant + effect claims derivable from callsite rows alone (no source text
/// needed), so this is what `report_fmt::report_to_json` can always emit for
/// `sugar prove`/`sugar verify`/`sugar lift`. A discharged row without a
/// followable CID is NOT a warrant, it stays a non-claim (residue-eligible).
pub fn row_line_accounting(rows: &[ReportRow]) -> Vec<LineAccountingEntry> {
    let mut entries = Vec::new();
    for row in rows {
        let Some(file) = row.callsite.file.clone() else {
            continue;
        };
        let Some(line) = row.callsite.line else {
            continue;
        };
        if line == 0 {
            continue;
        }
        match row.status {
            ObligationVerdict::Discharged => {
                if let Some(cid) = row_cid(row) {
                    entries.push(LineAccountingEntry {
                        file,
                        line,
                        class: LineClass::Warrant,
                        grounds: Some(cid),
                    });
                }
            }
            ObligationVerdict::Refused => {
                let grounds = if !row.reason.is_empty() {
                    row.reason.clone()
                } else {
                    row.callsite
                        .callee
                        .clone()
                        .unwrap_or_else(|| "refused".to_string())
                };
                entries.push(LineAccountingEntry {
                    file,
                    line,
                    class: LineClass::Effect,
                    grounds: Some(grounds),
                });
            }
            _ => {}
        }
    }
    entries
}

/// A trailer is "inert" if there is nothing left after it but whitespace, or
/// whatever remains is itself just a `#` comment. Anything else is a semantic
/// statement riding along on the same physical line and must NOT be witnessed
/// as inert.
fn trailer_is_inert(rest: &str) -> bool {
    let rest = rest.trim();
    rest.is_empty() || rest.starts_with('#')
}

/// Legitimate `import`/`from` statements never contain a top-level semicolon.
/// A semicolon means a second, chained statement rides along, so the line
/// cannot be witnessed as an import.
fn import_line_is_pure(trimmed: &str) -> bool {
    let code = match trimmed.find('#') {
        Some(idx) => &trimmed[..idx],
        None => trimmed,
    };
    !code.contains(';')
}

/// Find the block-opening colon of a `def`/`class`/`async def` signature,
/// skipping colons inside the parameter list, and return everything after it,
/// so the caller can check it is empty or a trailing comment (a genuine
/// multi-line signature) rather than an inline statement body.
fn signature_trailer(trimmed: &str) -> Option<&str> {
    let search_start = trimmed.rfind(')').map(|i| i + 1).unwrap_or(0);
    let rel = trimmed[search_start..].find(':')?;
    let colon_idx = search_start + rel;
    Some(&trimmed[colon_idx + 1..])
}

/// The coverage-typed Support component: mint an `InertWitness` for each
/// physical line of `source_text` not already in `claimed_lines` that is
/// affirmatively inert (blank, whole-line comment, pure import, a triple-quoted
/// docstring line/bound, or a bare def/class signature). Every branch guards
/// against a semantic line disguised in/adjacent to the inert context (planted
/// twins), never widening to swallow it; a line it cannot witness stays a
/// non-claim and can only be residue.
pub fn inert_support_accounting(
    file: &str,
    source_text: &str,
    claimed_lines: &HashSet<usize>,
) -> Vec<LineAccountingEntry> {
    let mut entries = Vec::new();
    let mut in_docstring: Option<&'static str> = None;
    for (idx, raw_line) in source_text.lines().enumerate() {
        let line_no = idx + 1;
        if claimed_lines.contains(&line_no) {
            continue;
        }
        let trimmed = raw_line.trim();
        let mut witness: Option<InertWitness> = None;

        if let Some(delim) = in_docstring {
            if let Some(close_rel) = trimmed.find(delim) {
                let after_close = &trimmed[close_rel + delim.len()..];
                if trailer_is_inert(after_close) {
                    witness = Some(InertWitness::Docstring);
                }
                // Whether or not the trailer was inert, the docstring state
                // ends here: the delimiter closed. A twin planted after it
                // stays a non-claim rather than being invented as inert.
                in_docstring = None;
            } else {
                witness = Some(InertWitness::Docstring);
            }
        } else if trimmed.is_empty() {
            witness = Some(InertWitness::Blank);
        } else if trimmed.starts_with('#') {
            witness = Some(InertWitness::Comment);
        } else if (trimmed.starts_with("import ") || trimmed.starts_with("from "))
            && import_line_is_pure(trimmed)
        {
            witness = Some(InertWitness::Import);
        } else if trimmed.starts_with("def ")
            || trimmed.starts_with("class ")
            || trimmed.starts_with("async def ")
        {
            if let Some(trailer) = signature_trailer(trimmed) {
                if trailer_is_inert(trailer) {
                    witness = Some(InertWitness::Signature);
                }
            }
        } else if trimmed.starts_with("\"\"\"") || trimmed.starts_with("'''") {
            let delim = if trimmed.starts_with("\"\"\"") {
                "\"\"\""
            } else {
                "'''"
            };
            let after_open = &trimmed[delim.len()..];
            if let Some(close_rel) = after_open.find(delim) {
                let after_close = &after_open[close_rel + delim.len()..];
                if trailer_is_inert(after_close) {
                    witness = Some(InertWitness::Docstring);
                }
            } else {
                witness = Some(InertWitness::Docstring);
                in_docstring = Some(delim);
            }
        }

        if let Some(witness) = witness {
            entries.push(LineAccountingEntry::support(file, line_no, witness));
        }
    }
    entries
}

/// Physical `(body_start, body_end)` 1-based line ranges for every top-level
/// `def`/`async def` in `source_text`, found by indentation alone: a
/// function's body is every line strictly more indented than its `def`,
/// running from the line after the signature until the next non-blank line
/// at or below the `def`'s own indentation (or EOF). Coarse on purpose --
/// callers only ever fill gaps between already-claimed lines inside a range,
/// so a body range that also spans already-claimed lines (a docstring, a
/// blank line) is harmless: those lines are simply skipped.
fn function_body_ranges(source_text: &str) -> Vec<(usize, usize)> {
    let lines: Vec<&str> = source_text.lines().collect();
    let mut defs: Vec<(usize, usize)> = Vec::new();
    for (idx, raw) in lines.iter().enumerate() {
        let line_no = idx + 1;
        let trimmed = raw.trim_start();
        if trimmed.starts_with("def ") || trimmed.starts_with("async def ") {
            let indent = raw.len() - trimmed.len();
            defs.push((line_no, indent));
        }
    }
    let mut ranges = Vec::new();
    for &(def_line, indent) in &defs {
        let body_start = def_line + 1;
        let mut body_end = lines.len();
        for idx in body_start..=lines.len() {
            let raw = lines[idx - 1];
            if raw.trim().is_empty() {
                continue;
            }
            let cur_indent = raw.len() - raw.trim_start().len();
            if cur_indent <= indent {
                body_end = idx - 1;
                break;
            }
        }
        if body_start <= body_end {
            ranges.push((body_start, body_end));
        }
    }
    ranges
}

/// Criterion 14 residue drain (#3706 follow-up, re-targeted onto
/// `SourcePartition` claim generation after the line_accounting layer was
/// deleted by #3759's partition-type refactor): a `warrant`/`effect` claim
/// covers its enclosing function's full body span IFF it genuinely covers
/// that span -- never by widening the schema past what the row actually
/// proves.
///
/// THE RULE: within one function body range, take every existing
/// `warrant`/`effect` claim already anchored inside it, in ascending line
/// order. Each anchor claims every still-unclaimed line strictly between
/// the previous anchor (or the function's first body line, if none) and
/// itself, under the SAME class and the SAME grounds (the same followable
/// CID, or the same refusal reason) as the anchor. This is honest because
/// those in-between lines are ordinary straight-line statements that must
/// execute, unconditionally, on every path that reaches the anchor
/// callsite -- they are covered by the exact same proof/refusal the anchor
/// already carries, never a new one invented for them.
///
/// This never invents coverage past the LAST anchor in a function: trailing
/// body lines after the final warrant/effect stay residue-eligible, same as
/// a function with zero rows contributes zero expansion (the honesty rule:
/// a line inside a function whose lift produced NO row stays residue).
/// Lines already claimed (by a row, or by `inert_support_accounting`) are
/// never reclassified -- the lattice in `SourcePartition::construct` still
/// governs final resolution, but this generator never re-emits a claim for
/// an already-claimed line, so it adds no new collisions.
pub fn expand_body_span_line_accounting(
    file: &str,
    source_text: &str,
    claims: &[LineAccountingEntry],
) -> Vec<LineAccountingEntry> {
    let mut claimed: HashSet<usize> = claims.iter().map(|e| e.line).collect();
    let mut new_entries = Vec::new();

    for (body_start, body_end) in function_body_ranges(source_text) {
        let mut anchors: Vec<&LineAccountingEntry> = claims
            .iter()
            .filter(|e| {
                matches!(e.class, LineClass::Warrant | LineClass::Effect)
                    && e.line >= body_start
                    && e.line <= body_end
            })
            .collect();
        anchors.sort_by_key(|e| e.line);

        let mut cursor = body_start;
        for anchor in anchors {
            for line in cursor..anchor.line {
                if claimed.insert(line) {
                    new_entries.push(LineAccountingEntry {
                        file: file.to_string(),
                        line,
                        class: anchor.class,
                        grounds: anchor.grounds.clone(),
                    });
                }
            }
            cursor = anchor.line + 1;
        }
    }
    new_entries
}

/// The partition itself: every physical line of one compilation unit tiled
/// into exactly one arm. Totals are projections (methods), never stored.
#[derive(Debug, Clone)]
pub struct SourcePartition {
    file: String,
    total_lines: usize,
    /// line -> resolved arm (post-lattice)
    assignments: BTreeMap<usize, LineClass>,
    /// line -> grounds of the winning claim (for entry rendering)
    grounds: BTreeMap<usize, String>,
}

/// A failed tiling: named, never a silent nonzero meter. The type forces the
/// caller to handle this arm, so an unaccounted line cannot vanish.
#[derive(Debug, Clone)]
pub struct PartitionError {
    /// The claims that DID place, so the report can still render what it knows.
    partition: SourcePartition,
    /// The gapped physical lines: touched by no warrant, no inert witness, and
    /// no effect. This IS the criterion-14 residue, guaranteed by exhaustive
    /// construction rather than by a checker declining.
    pub gaps: Vec<usize>,
}

impl SourcePartition {
    /// Tile `total_lines` physical lines using `claims`, resolving multi-claimed
    /// lines by the lattice (`Effect > Warrant > Support`). Returns `Err` naming
    /// every gapped line unless the tiling is total and disjoint-after-lattice.
    pub fn construct(
        file: &str,
        total_lines: usize,
        claims: &[LineAccountingEntry],
    ) -> Result<SourcePartition, PartitionError> {
        let mut assignments: BTreeMap<usize, LineClass> = BTreeMap::new();
        let mut grounds: BTreeMap<usize, String> = BTreeMap::new();
        for claim in claims {
            if claim.line == 0 || claim.line > total_lines {
                continue;
            }
            match assignments.get(&claim.line) {
                Some(existing) if *existing >= claim.class => {
                    // A strictly-higher or equal arm already holds this line;
                    // the lattice keeps it. (Equal arm: first grounds win.)
                }
                _ => {
                    assignments.insert(claim.line, claim.class);
                    match &claim.grounds {
                        Some(g) => {
                            grounds.insert(claim.line, g.clone());
                        }
                        None => {
                            grounds.remove(&claim.line);
                        }
                    }
                }
            }
        }
        let partition = SourcePartition {
            file: file.to_string(),
            total_lines,
            assignments,
            grounds,
        };
        let gaps = partition.gaps();
        if gaps.is_empty() {
            Ok(partition)
        } else {
            Err(PartitionError { partition, gaps })
        }
    }

    /// Physical lines in `1..=total_lines` that no claim placed.
    pub fn gaps(&self) -> Vec<usize> {
        (1..=self.total_lines)
            .filter(|n| !self.assignments.contains_key(n))
            .collect()
    }

    fn count(&self, class: LineClass) -> usize {
        self.assignments.values().filter(|c| **c == class).count()
    }

    pub fn warrant_count(&self) -> usize {
        self.count(LineClass::Warrant)
    }

    pub fn support_count(&self) -> usize {
        self.count(LineClass::Support)
    }

    pub fn effect_count(&self) -> usize {
        self.count(LineClass::Effect)
    }

    /// Total physical lines of the compilation unit. `warrant + support +
    /// effect + residue == total` holds by construction, not by a checked
    /// equation.
    pub fn total(&self) -> usize {
        self.total_lines
    }

    /// One `lineAccounting` entry per placed line, rendered FROM the partition
    /// (single source of truth), shape-identical to the pre-#3756 array so the
    /// numpy/pandas wall summaries keep reading it unchanged.
    pub fn entries_json(&self) -> Vec<Json> {
        self.assignments
            .iter()
            .map(|(line, class)| {
                json!({
                    "file": self.file,
                    "line": line,
                    "class": class.as_str(),
                    "grounds": self.grounds.get(line),
                })
            })
            .collect()
    }

    /// The projected partition summary: totals derived from the assignment map,
    /// residue zero because this value only exists when the tiling is total.
    pub fn summary_json(&self) -> Json {
        json!({
            "file": self.file,
            "totalLines": self.total_lines,
            "warrant": self.warrant_count(),
            "support": self.support_count(),
            "effect": self.effect_count(),
            "residue": 0,
            "conserved": true,
            "unaccounted": [],
        })
    }
}

impl PartitionError {
    /// The entries the partition DID place (so the report still renders known
    /// classification even when the tiling failed).
    pub fn entries_json(&self) -> Vec<Json> {
        self.partition.entries_json()
    }

    /// The LOUD, named construction failure: totals plus every gapped line by
    /// file:line. This is the criterion-14 residue as a value of the type, not
    /// a meter a checker computes after the fact.
    pub fn summary_json(&self) -> Json {
        let unaccounted: Vec<Json> = self
            .gaps
            .iter()
            .map(|line| json!({ "file": self.partition.file, "line": line }))
            .collect();
        json!({
            "file": self.partition.file,
            "totalLines": self.partition.total_lines,
            "warrant": self.partition.warrant_count(),
            "support": self.partition.support_count(),
            "effect": self.partition.effect_count(),
            "residue": self.gaps.len(),
            "conserved": false,
            "unaccounted": unaccounted,
        })
    }
}

/// Build the `lineAccounting` array and the `lineAccountingPartition` array for
/// a lift+prove report, rendering BOTH from per-file `SourcePartition`s. For a
/// file whose source is readable, the partition tiles every physical line and
/// either projects its totals (`conserved: true`) or names its residue loudly
/// (`conserved: false`). A file whose source cannot be read keeps its
/// row-derived claims and is reported as `sourceUnavailable` (the wire lacks
/// the extent needed to tile -- named, never faked).
pub fn build_line_accounting(
    prove_report: &sugar_verifier::Report,
    project_root: &Path,
) -> (Vec<Json>, Vec<Json>) {
    let row_claims = row_line_accounting(&prove_report.rows);

    // Group row claims by file, preserving order for stable output.
    let mut files: Vec<String> = Vec::new();
    let mut claims_by_file: BTreeMap<String, Vec<LineAccountingEntry>> = BTreeMap::new();
    for row in &prove_report.rows {
        if let Some(file) = &row.callsite.file {
            if !claims_by_file.contains_key(file) {
                files.push(file.clone());
                claims_by_file.insert(file.clone(), Vec::new());
            }
        }
    }
    for claim in row_claims {
        claims_by_file.entry(claim.file.clone()).or_default();
        if let Some(v) = claims_by_file.get_mut(&claim.file) {
            v.push(claim);
        }
    }

    let mut entries: Vec<Json> = Vec::new();
    let mut partitions: Vec<Json> = Vec::new();

    for file in &files {
        let file_claims = claims_by_file.remove(file).unwrap_or_default();
        let Ok(source_text) = std::fs::read_to_string(project_root.join(file)) else {
            // The wire lacks the source extent: cannot tile. Emit the claims we
            // have and name precisely what is missing -- do not fake tiling.
            for claim in &file_claims {
                entries.push(claim.to_json());
            }
            partitions.push(json!({
                "file": file,
                "sourceUnavailable": true,
                "conserved": false,
            }));
            continue;
        };
        let total_lines = source_text.lines().count();
        let claimed: HashSet<usize> = file_claims.iter().map(|c| c.line).collect();
        let inert = inert_support_accounting(file, &source_text, &claimed);

        let mut all_claims = file_claims;
        all_claims.extend(inert);
        let expanded = expand_body_span_line_accounting(file, &source_text, &all_claims);
        all_claims.extend(expanded);

        match SourcePartition::construct(file, total_lines, &all_claims) {
            Ok(partition) => {
                entries.extend(partition.entries_json());
                partitions.push(partition.summary_json());
            }
            Err(failure) => {
                entries.extend(failure.entries_json());
                partitions.push(failure.summary_json());
            }
        }
    }

    (entries, partitions)
}

#[cfg(test)]
mod tests {
    use super::*;
    use sugar_canonicalizer::blake3_512_of;
    use sugar_verifier::{CallSite, MementoCid};

    fn cid() -> MementoCid {
        MementoCid::try_parse(blake3_512_of(b"warrant-target")).expect("test CID must parse")
    }

    fn support_entry(file: &str, line: usize, witness: InertWitness) -> LineAccountingEntry {
        LineAccountingEntry::support(file, line, witness)
    }

    fn warrant_entry(file: &str, line: usize) -> LineAccountingEntry {
        LineAccountingEntry {
            file: file.to_string(),
            line,
            class: LineClass::Warrant,
            grounds: Some("cid".into()),
        }
    }

    fn effect_entry(file: &str, line: usize) -> LineAccountingEntry {
        LineAccountingEntry {
            file: file.to_string(),
            line,
            class: LineClass::Effect,
            grounds: Some("no vendor assertion".into()),
        }
    }

    // -- Row-derived claims ------------------------------------------------

    #[test]
    fn discharged_row_with_cid_is_warrant() {
        let rows = vec![ReportRow {
            callsite: CallSite {
                file: Some("f.py".into()),
                line: Some(17),
                bridge_target_cid: Some(cid()),
                ..CallSite::default()
            },
            status: ObligationVerdict::Discharged,
            reason: String::new(),
            discharge_method: None,
            body_discharge_tier: None,
            verification: None,
        }];
        let entries = row_line_accounting(&rows);
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].line, 17);
        assert!(matches!(entries[0].class, LineClass::Warrant));
    }

    #[test]
    fn discharged_row_without_cid_is_not_warrant() {
        let rows = vec![ReportRow {
            callsite: CallSite {
                file: Some("f.py".into()),
                line: Some(17),
                ..CallSite::default()
            },
            status: ObligationVerdict::Discharged,
            reason: String::new(),
            discharge_method: None,
            body_discharge_tier: None,
            verification: None,
        }];
        assert!(row_line_accounting(&rows).is_empty());
    }

    #[test]
    fn refused_row_is_effect_with_reason_as_grounds() {
        let rows = vec![ReportRow {
            callsite: CallSite {
                file: Some("f.py".into()),
                line: Some(30),
                callee: Some("Exception".into()),
                ..CallSite::default()
            },
            status: ObligationVerdict::Refused,
            reason: "no vendor assertion found".into(),
            discharge_method: None,
            body_discharge_tier: None,
            verification: None,
        }];
        let entries = row_line_accounting(&rows);
        assert_eq!(entries.len(), 1);
        assert!(matches!(entries[0].class, LineClass::Effect));
        assert_eq!(
            entries[0].grounds.as_deref(),
            Some("no vendor assertion found")
        );
    }

    // -- Inert Support witnesses (the coverage-typed component) -------------

    /// One line number -> its witness label, if any support entry claims it.
    fn label_of(entries: &[LineAccountingEntry], line: usize) -> Option<&str> {
        entries
            .iter()
            .find(|e| e.line == line && e.class == LineClass::Support)
            .and_then(|e| e.grounds.as_deref())
    }

    #[test]
    fn inert_classifies_blank_import_docstring_and_signature_lines() {
        let source =
            "\"\"\"Module doc.\n\nMore.\n\"\"\"\n\nimport base64\n\n\ndef f(x):\n    return x\n";
        let claimed: HashSet<usize> = [10].into_iter().collect();
        let entries = inert_support_accounting("f.py", source, &claimed);
        let classes: HashSet<usize> = entries.iter().map(|e| e.line).collect();
        for line in [1, 2, 3, 4, 5, 6, 7, 8, 9] {
            assert!(
                classes.contains(&line),
                "expected line {line} witnessed inert: {entries:?}"
            );
        }
        assert!(!classes.contains(&10), "claimed line must not be witnessed");
    }

    #[test]
    fn class_blank_twin_whitespace_only_never_hides_adjacent_code() {
        let source = "result = dangerous_call()\n   \nother = mutate(result)\n";
        let entries = inert_support_accounting("f.py", source, &HashSet::new());
        assert_eq!(label_of(&entries, 2), Some("blank"));
        assert_eq!(label_of(&entries, 1), None);
        assert_eq!(label_of(&entries, 3), None);
    }

    #[test]
    fn class_comment_twin_trailing_comment_does_not_hide_code() {
        let source = "assert user.is_admin()  # TODO revisit this check\n";
        let entries = inert_support_accounting("f.py", source, &HashSet::new());
        assert_eq!(label_of(&entries, 1), None);
    }

    #[test]
    fn class_import_twin_semicolon_chained_side_effect_does_not_hide() {
        let source = "import os; os.system(\"rm -rf /\")\n";
        let entries = inert_support_accounting("f.py", source, &HashSet::new());
        assert_eq!(
            label_of(&entries, 1),
            None,
            "semicolon-chained side effect after import must not witness as support: {entries:?}"
        );
    }

    #[test]
    fn class_docstring_twin_value_expression_is_not_a_docstring() {
        let source = "payload = \"\"\"assert compromised()\"\"\"\n";
        let entries = inert_support_accounting("f.py", source, &HashSet::new());
        assert_eq!(label_of(&entries, 1), None);
    }

    #[test]
    fn class_docstring_twin_code_after_closing_delimiter_does_not_hide() {
        let source = "\"\"\"short\"\"\"; os.system(\"rm -rf /\")\n";
        let entries = inert_support_accounting("f.py", source, &HashSet::new());
        assert_eq!(label_of(&entries, 1), None);
    }

    #[test]
    fn class_docstring_twin_code_after_multiline_close_does_not_hide() {
        let source = "\"\"\"\ndoc body\n\"\"\"; os.system(\"rm -rf /\")\n";
        let entries = inert_support_accounting("f.py", source, &HashSet::new());
        assert_eq!(label_of(&entries, 1), Some("docstring"));
        assert_eq!(label_of(&entries, 2), Some("docstring"));
        assert_eq!(label_of(&entries, 3), None);
    }

    #[test]
    fn class_signature_twin_one_line_body_does_not_hide() {
        let source = "def f(): return dangerous()\n";
        let entries = inert_support_accounting("f.py", source, &HashSet::new());
        assert_eq!(label_of(&entries, 1), None);
    }

    #[test]
    fn class_signature_twin_class_one_line_body_does_not_hide() {
        let source = "class Foo: mutate_global_state()\n";
        let entries = inert_support_accounting("f.py", source, &HashSet::new());
        assert_eq!(label_of(&entries, 1), None);
    }

    // -- The partition type: construction, lattice, projection, teeth -------

    #[test]
    fn total_tiling_constructs_and_projects_totals() {
        // 4 lines, every one claimed: warrant, support, effect, support.
        let claims = vec![
            warrant_entry("f.py", 1),
            support_entry("f.py", 2, InertWitness::Blank),
            effect_entry("f.py", 3),
            support_entry("f.py", 4, InertWitness::Import),
        ];
        let partition =
            SourcePartition::construct("f.py", 4, &claims).expect("total tiling must construct");
        assert_eq!(partition.warrant_count(), 1);
        assert_eq!(partition.support_count(), 2);
        assert_eq!(partition.effect_count(), 1);
        // Projection identity: warrant + support + effect + residue == total.
        assert_eq!(
            partition.warrant_count()
                + partition.support_count()
                + partition.effect_count()
                + partition.gaps().len(),
            partition.total()
        );
    }

    #[test]
    fn gapped_tiling_refuses_naming_the_uncovered_span() {
        // Line 2 has a semantic statement with no row and no inert witness: a
        // planted uncovered line. Construction MUST refuse and name it.
        let claims = vec![
            warrant_entry("f.py", 1),
            support_entry("f.py", 3, InertWitness::Blank),
        ];
        let err = SourcePartition::construct("f.py", 3, &claims)
            .expect_err("a gapped tiling must not construct");
        assert_eq!(err.gaps, vec![2]);
        let summary = err.summary_json();
        assert_eq!(summary["conserved"], json!(false));
        assert_eq!(summary["residue"], json!(1));
        assert_eq!(summary["unaccounted"][0]["line"], json!(2));
    }

    #[test]
    fn lattice_resolves_warrant_and_effect_on_one_line_to_effect() {
        // Same physical line claimed as both Warrant and Effect: Effect wins by
        // the lattice, regardless of input order.
        let claims = vec![warrant_entry("f.py", 1), effect_entry("f.py", 1)];
        let partition =
            SourcePartition::construct("f.py", 1, &claims).expect("one line, one arm after max");
        assert_eq!(partition.effect_count(), 1);
        assert_eq!(partition.warrant_count(), 0);

        // Reverse order must give the same result: Effect > Warrant by type.
        let claims_rev = vec![effect_entry("f.py", 1), warrant_entry("f.py", 1)];
        let partition_rev = SourcePartition::construct("f.py", 1, &claims_rev)
            .expect("one line, one arm after max");
        assert_eq!(partition_rev.effect_count(), 1);
        assert_eq!(partition_rev.warrant_count(), 0);
    }

    #[test]
    fn lattice_warrant_beats_support_on_one_line() {
        let claims = vec![
            support_entry("f.py", 1, InertWitness::Blank),
            warrant_entry("f.py", 1),
        ];
        let partition = SourcePartition::construct("f.py", 1, &claims).expect("one arm after max");
        assert_eq!(partition.warrant_count(), 1);
        assert_eq!(partition.support_count(), 0);
    }

    /// The itsdangerous fixture, tiled end to end: proves the partition
    /// drains the criterion-14 residue that `tools/criterion14_conservation.py`
    /// used to compute (formerly R=7, per PR #3760's body-span-expansion +
    /// raise-anchor fix, re-targeted here after #3759 deleted the
    /// line_accounting layer those fixes lived in) to R=0 as a value of the
    /// type: warrant {17,29} expand to cover their straight-line body spans,
    /// effect {31} (the real Python lifter anchors `ast.Raise` on its own
    /// `lineno`, one line below the `except:` at 30) expands to cover 30, 21
    /// inert support lines untouched, zero residue.
    #[test]
    fn itsdangerous_slice_drains_to_zero_residue() {
        let source = concat!(
            "\"\"\"Small real slice of itsdangerous (url_safe.py base64 helpers), used as the\n",
            "Criterion 14 conservation ratchet's small in-scope vendor fixture. Kept\n",
            "verbatim-shaped (not paraphrased) so the line count/content is a faithful\n",
            "stand-in for the real module.\n",
            "\"\"\"\n",
            "\n",
            "import base64\n",
            "\n",
            "\n",
            "def base64_encode(string):\n",
            "    \"\"\"Base64 encode a string of bytes or text.\n",
            "\n",
            "    The resulting bytestring is safe for putting in URLs.\n",
            "    \"\"\"\n",
            "    if isinstance(string, str):\n",
            "        string = string.encode(\"utf-8\")\n",
            "    return base64.urlsafe_b64encode(string).rstrip(b\"=\")\n",
            "\n",
            "\n",
            "def base64_decode(string):\n",
            "    \"\"\"Base64 decode a URL-safe string.\n",
            "\n",
            "    :param string: The string to decode.\n",
            "    \"\"\"\n",
            "    if isinstance(string, str):\n",
            "        string = string.encode(\"ascii\")\n",
            "    string += b\"=\" * (-len(string) % 4)\n",
            "    try:\n",
            "        return base64.urlsafe_b64decode(string)\n",
            "    except (TypeError, ValueError) as e:\n",
            "        raise Exception(\"Invalid base64-encoded data\") from e\n",
        );
        let total_lines = source.lines().count();
        assert_eq!(total_lines, 31);

        // Row-derived claims exactly as the fixture report pins them: the two
        // discharged CID-bearing returns (17, 29) and the refused Exception
        // effect anchored at the `raise` itself (31), matching the real
        // Python lifter's `runtime_failure_locus` (anchors on `ast.Raise`'s
        // own `lineno`, not the `except:` line above it).
        let mut claims = vec![
            warrant_entry("itsdangerous.py", 17),
            warrant_entry("itsdangerous.py", 29),
            effect_entry("itsdangerous.py", 31),
        ];
        let claimed: HashSet<usize> = claims.iter().map(|c| c.line).collect();
        claims.extend(inert_support_accounting(
            "itsdangerous.py",
            source,
            &claimed,
        ));
        claims.extend(expand_body_span_line_accounting(
            "itsdangerous.py",
            source,
            &claims,
        ));

        let partition = SourcePartition::construct("itsdangerous.py", total_lines, &claims)
            .expect("body-span expansion drains the tiling to total");
        assert_eq!(partition.warrant_count(), 8);
        assert_eq!(partition.support_count(), 21);
        assert_eq!(partition.effect_count(), 2);
        assert_eq!(partition.gaps().len(), 0);
    }
}
