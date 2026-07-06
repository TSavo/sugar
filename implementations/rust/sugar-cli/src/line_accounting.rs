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
// `support_line_accounting` on top for lines the rows leave unclaimed (it
// alone has source-file access). Nothing else may grow a second, parallel
// classifier of the same lines; the `--visual` renderer's own tone painting
// predates this module and is tracked as residue to route through it in a
// follow-up (#3706), not silently duplicated logic.

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

/// Warrant + effect entries derivable from callsite rows alone: no source
/// text is needed, so this is what `report_fmt::report_to_json` can always
/// emit, for `sugar prove`/`sugar verify`/`sugar lift`. Mirrors
/// `tools/criterion14_conservation.py`'s own warrant classification exactly:
/// a discharged row without a followable CID is NOT a warrant, it stays
/// unaccounted.
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
