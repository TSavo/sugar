// SPDX-License-Identifier: Apache-2.0
//
// The superposition report: a VERDICT VIEW over the discharge the verifier
// already performs. It owns no solver. The verifier compiles each callsite
// obligation to z3 exactly once (consistency.rs / `emit_asserted`) — we compile
// to z3 N times, where N is the universe count — and records an
// `ObligationVerdict` per callsite. This module folds those N results, grouped
// by the callee symbol under test, into a per-symbol report.
//
// The dig is the verifier's: a unit test asserts a contract on the CALLSITE, and
// `body_discharge` resolves the callee body and reduces the obligation. So each
// row here is "the callee body, walked, checked against one sworn answer":
//
//   discharged   -> the reading holds (a SAT-equivalent licensing universe)
//   unsatisfied  -> the body contradicts the sworn answer (a vendor FINDING)
//   disagreement -> the body and the vendor disagree (a FINDING)
//   undecidable  -> no decision (neither licenses nor accuses)
//   refused      -> no sound discharger (neither licenses nor accuses)
//
// The keystone: >=1 discharged licenses the lift, so its findings are vendor
// findings; 0 discharged retracts the lift (our overreach, never an accusation).

use std::collections::BTreeMap;

use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};

use crate::types::Report;

/// Strength = the count of surviving consistent readings (universes).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Strength {
    /// Exactly one reading held: the output is pinned.
    Strong,
    /// More than one consistent-yet-mutually-exclusive reading: the logic is
    /// sound, only WHICH is unpinned. Bugs here live in ordering, not logic.
    Weak,
    /// No reading held: the code contradicts its own sworn assertions.
    Undecidable,
}

impl Strength {
    pub fn tag(self) -> &'static str {
        match self {
            Strength::Strong => "strong",
            Strength::Weak => "weak",
            Strength::Undecidable => "undecidable",
        }
    }

    pub fn verdict(self) -> &'static str {
        match self {
            Strength::Strong => "Only one reading made sense.",
            Strength::Weak => {
                "Multiple consistent but mutually-exclusive readings — \
                 bugs live in ordering, not logic. Collapse it: pin it, or get \
                 the side effect off the critical path."
            }
            Strength::Undecidable => {
                "No consistent world — the code contradicts its own assertions. \
                 Get your act together."
            }
        }
    }
}

/// The two levers a vendor pulls to collapse a weak/undecidable output.
pub fn collapse_levers() -> Vec<String> {
    vec![
        "pin it: add a vendor assertion that selects one reading".to_string(),
        "get the side effect off the critical path".to_string(),
    ]
}

/// One per-symbol superposition report — a content-addressed, recomputable node.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SuperpositionReport {
    /// The callee symbol under test (the bridge ir name).
    pub symbol: String,
    pub strength: Strength,
    pub verdict: String,
    /// Empty for Strong; the two levers for Weak/Undecidable.
    pub levers: Vec<String>,
    /// Pin ids whose discharge held (the licensing universes).
    pub licensing: Vec<String>,
    /// Pin ids the body contradicts (vendor findings: unsatisfied/disagreement).
    pub findings: Vec<String>,
    pub cid: String,
}

impl SuperpositionReport {
    fn build(symbol: String, mut licensing: Vec<String>, mut findings: Vec<String>) -> Self {
        licensing.sort();
        licensing.dedup();
        findings.sort();
        findings.dedup();
        // Universe count = surviving consistent readings. With the body warrant
        // licensed, the holding readings agree on one reading; each contradicting
        // pin is a fork into a second reading (the vendor's sworn-but-wrong answer).
        let strength = if findings.is_empty() {
            Strength::Strong
        } else {
            Strength::Weak
        };
        let levers = match strength {
            Strength::Strong => Vec::new(),
            Strength::Weak | Strength::Undecidable => collapse_levers(),
        };
        let node = Value::object(vec![
            (
                "findings".to_string(),
                Value::array(findings.iter().cloned().map(Value::string).collect()),
            ),
            ("kind".to_string(), Value::string("superposition-report")),
            (
                "levers".to_string(),
                Value::array(levers.iter().cloned().map(Value::string).collect()),
            ),
            (
                "licensing".to_string(),
                Value::array(licensing.iter().cloned().map(Value::string).collect()),
            ),
            ("strength".to_string(), Value::string(strength.tag())),
            ("symbol".to_string(), Value::string(symbol.clone())),
            ("verdict".to_string(), Value::string(strength.verdict())),
        ]);
        let cid = blake3_512_of(encode_jcs(&node).as_bytes());
        SuperpositionReport {
            symbol,
            strength,
            verdict: strength.verdict().to_string(),
            levers,
            licensing,
            findings,
            cid,
        }
    }
}

/// Fold per-callsite discharge outcomes into per-symbol reports. Each item is
/// `(callee symbol, verdict status, pin id)` — one z3 compile the verifier
/// already ran. The keystone: a symbol with no holding reading is RETRACTED (no
/// report — our overreach, never an accusation); otherwise it gets a report
/// whose findings are the readings the body refutes.
pub fn fold_verdicts(items: &[(String, String, String)]) -> Vec<SuperpositionReport> {
    let mut by_symbol: BTreeMap<String, (Vec<String>, Vec<String>)> = BTreeMap::new();
    for (symbol, status, pin) in items {
        let entry = by_symbol.entry(symbol.clone()).or_default();
        match status.as_str() {
            "discharged" => entry.0.push(pin.clone()),
            "unsatisfied" | "disagreement" => entry.1.push(pin.clone()),
            // undecidable / refused: neither licenses nor accuses.
            _ => {}
        }
    }
    let mut out = Vec::new();
    for (symbol, (licensing, findings)) in by_symbol {
        if licensing.is_empty() {
            // No discharged reading -> no SAT licenses the lift -> retract. The
            // findings (if any) are NOT accusations without a license (the
            // no-false-accusation guarantee).
            continue;
        }
        out.push(SuperpositionReport::build(symbol, licensing, findings));
    }
    out
}

/// The verdict view over a completed verifier `Report`: group its discharge rows
/// by the callsite symbol under test and fold them into superposition reports.
pub fn reports_from_report(report: &Report) -> Vec<SuperpositionReport> {
    let items: Vec<(String, String, String)> = report
        .rows
        .iter()
        .map(|r| (symbol_of_row(r), r.status.clone(), pin_id(r)))
        .collect();
    fold_verdicts(&items)
}

/// The callee symbol under test for a row. Bridge-callsite rows carry it in
/// `bridge_ir_name`; consistency rows carry it in the property name:
///   `consistency:SYMBOL#euf#callresult_...`  (per-callsite, args after #euf#)
///   `consistency:tests/file.rs::testfn`       (per-test-fn)
/// Stripping `consistency:` and the `#euf#...` arg tail groups the per-argument
/// universes of one callsite under that callsite's symbol.
fn symbol_of_row(row: &crate::types::ReportRow) -> String {
    let bridge = &row.callsite.bridge_ir_name;
    if !bridge.is_empty() {
        return bridge.clone();
    }
    let prop = &row.callsite.property_name;
    if let Some(rest) = prop.strip_prefix("consistency:") {
        let sym = rest.split("#euf#").next().unwrap_or(rest);
        return sym.strip_suffix("::assertion").unwrap_or(sym).to_string();
    }
    if !prop.is_empty() {
        return prop.clone();
    }
    "<unkeyed>".to_string()
}

/// A stable id for the pin (the asserted reading): the property CID if present,
/// else the callsite's producer locus.
fn pin_id(row: &crate::types::ReportRow) -> String {
    let cs = &row.callsite;
    if !cs.property_cid.is_empty() {
        return cs.property_cid.clone();
    }
    match (&cs.producer_file, cs.producer_line) {
        (Some(f), Some(l)) => format!("{f}:{l}"),
        _ => format!("{}::{}", cs.bridge_ir_name, cs.property_name),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn item(sym: &str, status: &str, pin: &str) -> (String, String, String) {
        (sym.to_string(), status.to_string(), pin.to_string())
    }

    #[test]
    fn all_discharged_is_strong_no_levers() {
        let items = vec![
            item("double", "discharged", "p1"),
            item("double", "discharged", "p2"),
        ];
        let reports = fold_verdicts(&items);
        assert_eq!(reports.len(), 1);
        let r = &reports[0];
        assert_eq!(r.strength, Strength::Strong);
        assert!(r.findings.is_empty());
        assert!(r.levers.is_empty());
        assert!(r.verdict.contains("one reading"));
    }

    #[test]
    fn a_contradicted_reading_is_a_finding_weak() {
        // double has a holding pin (licenses) and a contradicted one (finding).
        let items = vec![
            item("double", "discharged", "p_good"),
            item("double", "unsatisfied", "p_bad"),
        ];
        let reports = fold_verdicts(&items);
        assert_eq!(reports.len(), 1);
        let r = &reports[0];
        assert_eq!(r.strength, Strength::Weak);
        assert_eq!(r.findings, vec!["p_bad"]);
        assert_eq!(r.licensing, vec!["p_good"]);
        assert_eq!(r.levers.len(), 2);
        assert!(r.verdict.contains("ordering, not logic"));
    }

    #[test]
    fn no_discharged_reading_retracts_no_report() {
        // Every reading refuted and none discharged -> no SAT licenses -> retract.
        // No accusation against the vendor (no-false-accusation guarantee).
        let items = vec![
            item("bogus", "unsatisfied", "p1"),
            item("bogus", "unsatisfied", "p2"),
        ];
        assert!(fold_verdicts(&items).is_empty());
    }

    #[test]
    fn undecidable_and_refused_neither_license_nor_accuse() {
        let items = vec![
            item("f", "undecidable", "p1"),
            item("f", "refused", "p2"),
        ];
        assert!(
            fold_verdicts(&items).is_empty(),
            "no licensing reading -> no report"
        );
    }

    #[test]
    fn disagreement_counts_as_a_finding_when_licensed() {
        let items = vec![
            item("g", "discharged", "ok"),
            item("g", "disagreement", "conflict"),
        ];
        let reports = fold_verdicts(&items);
        assert_eq!(reports[0].strength, Strength::Weak);
        assert_eq!(reports[0].findings, vec!["conflict"]);
    }

    #[test]
    fn report_cid_recomputes_from_the_node() {
        let r = SuperpositionReport::build(
            "sym".to_string(),
            vec!["a".to_string()],
            vec!["b".to_string()],
        );
        let r2 = SuperpositionReport::build(
            "sym".to_string(),
            vec!["a".to_string()],
            vec!["b".to_string()],
        );
        assert_eq!(r.cid, r2.cid, "deterministic, recomputable");
        assert!(r.cid.starts_with("blake3-512:"));
    }

    #[test]
    fn distinct_symbols_get_distinct_reports() {
        let items = vec![
            item("a", "discharged", "p"),
            item("b", "discharged", "p"),
        ];
        let reports = fold_verdicts(&items);
        assert_eq!(reports.len(), 2);
        assert_ne!(reports[0].cid, reports[1].cid);
    }
}
