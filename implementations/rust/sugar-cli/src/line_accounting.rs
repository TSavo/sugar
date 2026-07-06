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

/// Classify every physical line of `source_text` not already present in
/// `claimed_lines` as `support` when it is affirmatively inert: a blank
/// line, an `import`/`from` line, a line inside or bounding a triple-quoted
/// docstring, or a bare `def`/`class`/`async def` signature line. Any other
/// unclaimed line is left alone: genuine residue, never invented support.
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
            classified = Some("docstring");
            if trimmed.contains(delim) {
                in_docstring = None;
            }
        } else if trimmed.is_empty() {
            classified = Some("blank");
        } else if trimmed.starts_with("import ") || trimmed.starts_with("from ") {
            classified = Some("import");
        } else if trimmed.starts_with("def ")
            || trimmed.starts_with("class ")
            || trimmed.starts_with("async def ")
        {
            classified = Some("signature");
        } else if trimmed.starts_with("\"\"\"") || trimmed.starts_with("'''") {
            let delim = if trimmed.starts_with("\"\"\"") {
                "\"\"\""
            } else {
                "'''"
            };
            classified = Some("docstring");
            let after_open = &trimmed[delim.len()..];
            if !after_open.contains(delim) {
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
}
