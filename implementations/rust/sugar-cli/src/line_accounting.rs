// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Criterion 14 total line accounting (#3706, part of #3686): classify every
// physical source line of a lifted file into exactly one of three terminal
// states:
//
//   warrant -- proofir-bearing, CID-followable (a discharged callsite row
//              with a followable targetCid/propertyCid/callsiteBundleCid).
//   support -- affirmatively-classified-inert (imports, docstrings, blanks,
//              bare def/class signature lines).
//   effect  -- a named typed effect with grounds anchored to the line (a
//              refused row: the row's callee names the effect, `reason` is
//              its grounds).
//
// A line the report claims none of the above for is the outlawed fourth
// state and stays unaccounted -- residue, never invented.
//
// ONE WAY LAW: this module is the single owner of the classification.
// `report_fmt::report_to_json` calls `row_line_accounting` (warrant/effect,
// no source text needed) and `cmd_lift::render_report_json` layers
// `support_line_accounting` (and, after it, `expand_body_span_line_accounting`)
// on top for lines the rows leave unclaimed (it alone has source-file
// access). Nothing else may grow a second, parallel classifier of the same
// lines.
//
// `report_fmt::format_report_pretty`'s `--visual` per-row status coloring
// calls `line_class_for_row` -- the exact same per-row rule
// `row_line_accounting` uses -- so that painter is now a render of this
// classifier, not a second one (#3706 follow-up). Still-named residue: the
// separate, older `--visual` SOURCE-annotation painter in `cmd_lift.rs`
// (`visual_factory_walk_rows` and friends), which tones GREEN/RED per
// source line from `LiftSourceReport.factory_walk` -- a richer, differently
// shaped structure (per-symbol universes, superposition) than the
// `sugar_verifier::Report` rows this module classifies. Routing that
// painter through this same classifier is real, further work (its own
// follow-up under #3706), not silently duplicated logic in the meantime.

use serde_json::{json, Value as Json};
use std::collections::HashSet;
use sugar_verifier::{ObligationVerdict, ReportRow};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LineClass {
    Warrant,
    Support,
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

#[derive(Debug, Clone)]
pub struct LineAccountingEntry {
    pub file: String,
    pub line: usize,
    pub class: LineClass,
    /// Warrant: the followable CID. Effect: the grounds (refusal reason).
    /// Support: a short name for the inert category (e.g. "blank", "import").
    pub grounds: Option<String>,
}

impl LineAccountingEntry {
    pub fn to_json(&self) -> Json {
        json!({
            "file": self.file,
            "line": self.line,
            "class": self.class.as_str(),
            "grounds": self.grounds,
        })
    }
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

/// The single per-row classification rule: what class (if any) does this row
/// carry, and what is its grounds. `row_line_accounting` (the JSON path) and
/// `format_report_pretty`'s `--visual` row painter (the human-facing path)
/// both call this ONE function so the tone painted for a row's status can
/// never drift from the class its own JSON `lineAccounting` entry carries --
/// there is exactly one classifier, and visual output is a render of it, not
/// a second, parallel decision. Mirrors `tools/criterion14_conservation.py`'s
/// own warrant classification exactly: a discharged row without a followable
/// CID is NOT a warrant, it stays unclassified (`None`).
pub fn line_class_for_row(row: &ReportRow) -> Option<(LineClass, String)> {
    match row.status {
        ObligationVerdict::Discharged => row_cid(row).map(|cid| (LineClass::Warrant, cid)),
        ObligationVerdict::Refused => {
            let grounds = if !row.reason.is_empty() {
                row.reason.clone()
            } else {
                row.callsite
                    .callee
                    .clone()
                    .unwrap_or_else(|| "refused".to_string())
            };
            Some((LineClass::Effect, grounds))
        }
        _ => None,
    }
}

/// Warrant + effect entries derivable from callsite rows alone: no source
/// text is needed, so this is what `report_fmt::report_to_json` can always
/// emit, for `sugar prove`/`sugar verify`/`sugar lift`.
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
        if let Some((class, grounds)) = line_class_for_row(row) {
            entries.push(LineAccountingEntry {
                file,
                line,
                class,
                grounds: Some(grounds),
            });
        }
    }
    entries
}

/// A trailer is "inert" if there is nothing left after it but whitespace, or
/// whatever remains is itself just a `#` comment. Anything else is a
/// semantic statement riding along on the same physical line (a
/// semicolon-chained call after an `import`, a one-line `def f(): return x`
/// body, code stacked after a docstring's closing delimiter) and must NOT be
/// swallowed as support.
fn trailer_is_inert(rest: &str) -> bool {
    let rest = rest.trim();
    rest.is_empty() || rest.starts_with('#')
}

/// Bare import line safety check: legitimate `import`/`from` statements never
/// contain a top-level semicolon. A semicolon on the line means a second,
/// chained statement (e.g. `import os; os.system(...)`) rides along, so the
/// whole line must not be claimed as support even though it starts with
/// `import `/`from `.
fn import_line_is_pure(trimmed: &str) -> bool {
    let code = match trimmed.find('#') {
        Some(idx) => &trimmed[..idx],
        None => trimmed,
    };
    !code.contains(';')
}

/// Find the block-opening colon of a `def`/`class`/`async def` signature,
/// skipping any colons that appear inside the parameter list (type
/// annotations, default dict/slice literals). Returns everything after that
/// colon, so the caller can check it is either empty or a trailing comment
/// (a genuine multi-line signature) rather than an inline statement body.
fn signature_trailer(trimmed: &str) -> Option<&str> {
    let search_start = trimmed.rfind(')').map(|i| i + 1).unwrap_or(0);
    let rel = trimmed[search_start..].find(':')?;
    let colon_idx = search_start + rel;
    Some(&trimmed[colon_idx + 1..])
}

/// Classify every physical line of `source_text` not already present in
/// `claimed_lines` as `support` when it is affirmatively inert: a blank
/// line, a whole-line `#` comment, a pure `import`/`from` line, a line
/// inside or bounding a triple-quoted docstring, or a bare
/// `def`/`class`/`async def` signature line with no inline body. Any other
/// unclaimed line is left alone: genuine residue, never invented support.
/// Every branch guards against a semantic line disguised inside/adjacent to
/// the support context (planted twins), never widening to swallow it.
pub fn support_line_accounting(
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
        let mut classified: Option<&'static str> = None;

        if let Some(delim) = in_docstring {
            if let Some(close_rel) = trimmed.find(delim) {
                let after_close = &trimmed[close_rel + delim.len()..];
                if trailer_is_inert(after_close) {
                    classified = Some("docstring");
                }
                // Whether or not the trailer was inert, the docstring state
                // ends here: the delimiter closed. A twin planted after it
                // stays unaccounted rather than being invented as support.
                in_docstring = None;
            } else {
                classified = Some("docstring");
            }
        } else if trimmed.is_empty() {
            classified = Some("blank");
        } else if trimmed.starts_with('#') {
            classified = Some("comment");
        } else if (trimmed.starts_with("import ") || trimmed.starts_with("from "))
            && import_line_is_pure(trimmed)
        {
            classified = Some("import");
        } else if trimmed.starts_with("def ")
            || trimmed.starts_with("class ")
            || trimmed.starts_with("async def ")
        {
            if let Some(trailer) = signature_trailer(trimmed) {
                if trailer_is_inert(trailer) {
                    classified = Some("signature");
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
                    classified = Some("docstring");
                }
            } else {
                classified = Some("docstring");
                in_docstring = Some(delim);
            }
        }

        if let Some(label) = classified {
            entries.push(LineAccountingEntry {
                file: file.to_string(),
                line: line_no,
                class: LineClass::Support,
                grounds: Some(label.to_string()),
            });
        }
    }
    entries
}

pub fn entries_to_json(entries: &[LineAccountingEntry]) -> Json {
    Json::Array(entries.iter().map(LineAccountingEntry::to_json).collect())
}

/// Physical `(body_start, body_end)` 1-based line ranges for every top-level
/// `def`/`async def` in `source_text`, found by indentation alone: a
/// function's body is every line strictly more indented than its `def`,
/// running from the line after the signature until the next non-blank line
/// at or below the `def`'s own indentation (or EOF). Coarse on purpose --
/// callers only ever fill gaps between already-claimed lines inside a range,
/// so a body range that also spans already-claimed support lines (a
/// docstring, a blank line) is harmless: those lines are simply skipped.
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

/// Criterion 14 residue drain (#3706 follow-up): a `warrant`/`effect` entry
/// claims its enclosing function's full body span IFF it genuinely covers
/// that span -- never by widening the schema past what the row actually
/// proves.
///
/// THE RULE: within one function body range, take every existing
/// `warrant`/`effect` entry already anchored inside it, in ascending line
/// order. Each anchor claims every still-unclaimed line strictly between
/// the previous anchor (or the function's first body line, if none) and
/// itself, under the SAME class and the SAME grounds (the same followable
/// CID, or the same refusal reason) as the anchor. This is honest because
/// those in-between lines are ordinary straight-line statements that must
/// execute, unconditionally, on every path that reaches the anchor
/// callsite -- they are covered by the exact same proof/refusal the anchor
/// already carries, not a new one invented for them.
///
/// This never invents coverage past the LAST anchor in a function: trailing
/// body lines after the final warrant/effect stay unaccounted, same as a
/// function with zero rows contributes zero expansion (the honesty rule --
/// a line inside a function whose lift produced NO row stays residue).
/// Lines already claimed (by an earlier row, or by `support_line_accounting`)
/// are never reclassified, so a line is still claimed at most once.
pub fn expand_body_span_line_accounting(
    source_text: &str,
    entries: &[LineAccountingEntry],
) -> Vec<LineAccountingEntry> {
    let mut claimed: HashSet<usize> = entries.iter().map(|e| e.line).collect();
    let mut new_entries = Vec::new();

    for (body_start, body_end) in function_body_ranges(source_text) {
        let mut anchors: Vec<&LineAccountingEntry> = entries
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
                        file: anchor.file.clone(),
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

#[cfg(test)]
mod tests {
    use super::*;
    use sugar_canonicalizer::blake3_512_of;
    use sugar_verifier::{CallSite, MementoCid};

    fn cid() -> MementoCid {
        MementoCid::try_parse(blake3_512_of(b"warrant-target")).expect("test CID must parse")
    }

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

    #[test]
    fn support_classifies_blank_import_docstring_and_signature_lines() {
        let source =
            "\"\"\"Module doc.\n\nMore.\n\"\"\"\n\nimport base64\n\n\ndef f(x):\n    return x\n";
        let claimed: HashSet<usize> = [10].into_iter().collect(); // the return line is warrant elsewhere
        let entries = support_line_accounting("f.py", source, &claimed);
        let classes: HashSet<usize> = entries.iter().map(|e| e.line).collect();
        // lines 1-4 docstring, 5 blank, 6 import, 7-8 blank, 9 def signature
        for line in [1, 2, 3, 4, 5, 6, 7, 8, 9] {
            assert!(
                classes.contains(&line),
                "expected line {line} classified support: {entries:?}"
            );
        }
        assert!(
            !classes.contains(&10),
            "claimed line must not be reclassified"
        );
    }

    #[test]
    fn body_span_expansion_fills_gap_up_to_sole_anchor() {
        let source = "def f(x):\n    if isinstance(x, str):\n        x = x.encode(\"utf-8\")\n    return g(x)\n";
        let entries = vec![LineAccountingEntry {
            file: "f.py".into(),
            line: 4,
            class: LineClass::Warrant,
            grounds: Some("cid:sha256:abc".into()),
        }];
        let expanded = expand_body_span_line_accounting(source, &entries);
        let by_line: std::collections::BTreeMap<usize, &LineAccountingEntry> =
            expanded.iter().map(|e| (e.line, e)).collect();
        assert_eq!(
            by_line.len(),
            2,
            "expected lines 2 and 3 filled: {expanded:?}"
        );
        for line in [2, 3] {
            let entry = by_line.get(&line).expect("line must be filled");
            assert!(matches!(entry.class, LineClass::Warrant));
            assert_eq!(entry.grounds.as_deref(), Some("cid:sha256:abc"));
        }
    }

    #[test]
    fn body_span_expansion_never_touches_already_claimed_lines() {
        let source = "def f(x):\n    \"\"\"doc\"\"\"\n    if isinstance(x, str):\n        x = x.encode(\"utf-8\")\n    return g(x)\n";
        let mut entries = vec![LineAccountingEntry {
            file: "f.py".into(),
            line: 5,
            class: LineClass::Warrant,
            grounds: Some("cid:sha256:abc".into()),
        }];
        entries.push(LineAccountingEntry {
            file: "f.py".into(),
            line: 2,
            class: LineClass::Support,
            grounds: Some("docstring".into()),
        });
        let expanded = expand_body_span_line_accounting(source, &entries);
        let lines: HashSet<usize> = expanded.iter().map(|e| e.line).collect();
        assert_eq!(lines, [3, 4].into_iter().collect::<HashSet<_>>());
    }

    #[test]
    fn body_span_expansion_never_fills_past_last_anchor() {
        let source = "def f(x):\n    return g(x)\n\n\n";
        let entries = vec![LineAccountingEntry {
            file: "f.py".into(),
            line: 2,
            class: LineClass::Warrant,
            grounds: Some("cid:sha256:abc".into()),
        }];
        let expanded = expand_body_span_line_accounting(source, &entries);
        assert!(
            expanded.is_empty(),
            "trailing lines past the last anchor must stay residue: {expanded:?}"
        );
    }

    #[test]
    fn body_span_expansion_contributes_nothing_with_zero_rows_in_function() {
        // Honesty rule: a function with NO warrant/effect anchor at all gets
        // zero expansion, even though its body is discoverable by the
        // indentation scan.
        let source = "def f(x):\n    if isinstance(x, str):\n        x = x.encode(\"utf-8\")\n";
        let entries: Vec<LineAccountingEntry> = Vec::new();
        assert!(expand_body_span_line_accounting(source, &entries).is_empty());
    }

    #[test]
    fn support_never_claims_ordinary_statement_lines() {
        let source = "if isinstance(string, str):\n    string = string.encode(\"utf-8\")\n";
        let claimed = HashSet::new();
        let entries = support_line_accounting("f.py", source, &claimed);
        assert!(
            entries.is_empty(),
            "ordinary statement lines must stay unaccounted, not be invented as support: {entries:?}"
        );
    }

    /// One line number -> its class label, if any support entry claims it.
    fn class_of(entries: &[LineAccountingEntry], line: usize) -> Option<&str> {
        entries
            .iter()
            .find(|e| e.line == line)
            .and_then(|e| e.grounds.as_deref())
    }

    // -- Discrimination suite: one test per support class proving the
    // -- positive case, one adversarial planted-twin test per class proving
    // -- a semantic line disguised in/adjacent to that context is never
    // -- swallowed as support (#3733, part of #3707/#3686/#3503).

    #[test]
    fn class_blank_positive() {
        let source = "x = 1\n\ny = 2\n";
        let entries = support_line_accounting("f.py", source, &HashSet::new());
        assert_eq!(class_of(&entries, 2), Some("blank"));
    }

    #[test]
    fn class_blank_twin_whitespace_only_never_hides_adjacent_code() {
        // A line that is genuinely whitespace-only is inert by construction
        // (there is no way to plant a semantic statement inside true
        // emptiness); the twin here proves the adjacent code lines around
        // the blank line are never absorbed into its support classification.
        let source = "result = dangerous_call()\n   \nother = mutate(result)\n";
        let entries = support_line_accounting("f.py", source, &HashSet::new());
        assert_eq!(class_of(&entries, 2), Some("blank"));
        assert_eq!(
            class_of(&entries, 1),
            None,
            "call on line 1 must not be swallowed as support"
        );
        assert_eq!(
            class_of(&entries, 3),
            None,
            "mutation on line 3 must not be swallowed as support"
        );
    }

    #[test]
    fn class_comment_positive() {
        let source = "# a whole-line comment\n";
        let entries = support_line_accounting("f.py", source, &HashSet::new());
        assert_eq!(class_of(&entries, 1), Some("comment"));
    }

    #[test]
    fn class_comment_twin_trailing_comment_does_not_hide_code() {
        // Code with a trailing comment on the same physical line is a
        // semantic statement, not a comment line, and must stay unaccounted.
        let source = "assert user.is_admin()  # TODO revisit this check\n";
        let entries = support_line_accounting("f.py", source, &HashSet::new());
        assert_eq!(
            class_of(&entries, 1),
            None,
            "assertion sharing a line with a trailing comment must not classify as support: {entries:?}"
        );
    }

    #[test]
    fn class_import_positive() {
        let source = "import base64\n";
        let entries = support_line_accounting("f.py", source, &HashSet::new());
        assert_eq!(class_of(&entries, 1), Some("import"));
    }

    #[test]
    fn class_import_twin_semicolon_chained_side_effect_does_not_hide() {
        // A side-effecting call chained onto an import line via `;` is a
        // second statement riding the same physical line and must not be
        // swallowed by the import heuristic.
        let source = "import os; os.system(\"rm -rf /\")\n";
        let entries = support_line_accounting("f.py", source, &HashSet::new());
        assert_eq!(
            class_of(&entries, 1),
            None,
            "semicolon-chained side effect after import must not classify as support: {entries:?}"
        );
    }

    #[test]
    fn class_docstring_positive() {
        let source = "\"\"\"A short module docstring.\"\"\"\n";
        let entries = support_line_accounting("f.py", source, &HashSet::new());
        assert_eq!(class_of(&entries, 1), Some("docstring"));
    }

    #[test]
    fn class_docstring_twin_value_expression_is_not_a_docstring() {
        // A triple-quoted string used as an ordinary value (assigned to a
        // name, not a bare statement in docstring position) must not be
        // classified as support: the assignment target makes this line
        // semantic regardless of the string's contents.
        let source = "payload = \"\"\"assert compromised()\"\"\"\n";
        let entries = support_line_accounting("f.py", source, &HashSet::new());
        assert_eq!(
            class_of(&entries, 1),
            None,
            "assigned triple-quoted value must not classify as docstring support: {entries:?}"
        );
    }

    #[test]
    fn class_docstring_twin_code_after_closing_delimiter_does_not_hide() {
        // A statement stacked after a docstring's closing delimiter on the
        // same physical line (single-line or multi-line-closing) must not
        // be absorbed into the docstring's support classification.
        let source = "\"\"\"short\"\"\"; os.system(\"rm -rf /\")\n";
        let entries = support_line_accounting("f.py", source, &HashSet::new());
        assert_eq!(
            class_of(&entries, 1),
            None,
            "code stacked after closing triple-quote must not classify as support: {entries:?}"
        );
    }

    #[test]
    fn class_docstring_twin_code_after_multiline_close_does_not_hide() {
        let source = "\"\"\"\ndoc body\n\"\"\"; os.system(\"rm -rf /\")\n";
        let entries = support_line_accounting("f.py", source, &HashSet::new());
        assert_eq!(class_of(&entries, 1), Some("docstring"));
        assert_eq!(class_of(&entries, 2), Some("docstring"));
        assert_eq!(
            class_of(&entries, 3),
            None,
            "code stacked after the closing delimiter of a multi-line docstring must not classify as support: {entries:?}"
        );
    }

    #[test]
    fn class_signature_positive() {
        let source = "def f(x):\n    return x\n";
        let claimed: HashSet<usize> = [2].into_iter().collect();
        let entries = support_line_accounting("f.py", source, &claimed);
        assert_eq!(class_of(&entries, 1), Some("signature"));
    }

    #[test]
    fn class_signature_twin_one_line_body_does_not_hide() {
        // A one-line function body riding on the same physical line as the
        // `def` signature is a semantic return, not a bare signature, and
        // must not classify as support.
        let source = "def f(): return dangerous()\n";
        let entries = support_line_accounting("f.py", source, &HashSet::new());
        assert_eq!(
            class_of(&entries, 1),
            None,
            "inline def body must not classify as signature support: {entries:?}"
        );
    }

    #[test]
    fn class_signature_twin_class_one_line_body_does_not_hide() {
        let source = "class Foo: mutate_global_state()\n";
        let entries = support_line_accounting("f.py", source, &HashSet::new());
        assert_eq!(
            class_of(&entries, 1),
            None,
            "inline class body must not classify as signature support: {entries:?}"
        );
    }
}
