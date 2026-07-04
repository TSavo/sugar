// SPDX-License-Identifier: MIT OR Apache-2.0
//
// HAND-MAINTAINED. isinstance disjointness axioms for the Python pytest lifter.
//
// ── What this module encodes, and why ────────────────────────────────────
//
// The Python pytest lifter lifts ``assert isinstance(x, T)`` to:
//   ``atomic("isinstance", [x_term, ctor("pytype_T", [])])``
//
// The predicate-decl pass in emitter.rs declares ``isinstance`` as an
// uninterpreted Bool function. Without additional axioms, z3 would treat
// ``isinstance(x, pytype_int) ∧ isinstance(x, pytype_str)`` as SATISFIABLE
// (it assigns them both true) — a falsePass: in Python a value cannot be
// both an int and a str.
//
// To close the falsePass gap, this module emits GROUND disjointness clauses:
//   ``(assert (not (and (isinstance <subj> pytype_A) (isinstance <subj> pytype_B))))``
//
// for each subject that appears with a GENUINELY-DISJOINT pair (A, B) in the
// formula. "Genuinely disjoint" means every pair EXCEPT {int, bool}:
//   isinstance(True, int) is True in Python → bool IS a subtype of int.
//   An int/bool disjointness clause would falsely refuse isinstance(x,int) ∧
//   isinstance(x,bool), which is a Python-true consistent assertion.
//
// GROUND (subject-specific, quantifier-free) clauses are chosen deliberately:
//   - No ``unknown`` from z3 (quantifier-free ⇒ decidable in EUF).
//   - Different subjects never share a clause: isinstance(x,int); isinstance(y,str)
//     with different subjects x ≠ y → no clause emitted → PROVEN (correct).
//   - Only pairs with BOTH type names present in the formula get a clause
//     (byte-identity: formulas without isinstance atoms are unchanged).
//
// SOUNDNESS PRINCIPLE (mirrors literal_encoding.rs):
//   Every clause we assert is a Python-TRUE fact. Asserting a true fact
//   can only ELIMINATE spurious models (close falsePass), never invent one.
//   A wrong disjointness clause → false-refusal. So: only assert pairs that
//   are CERTAINLY disjoint in Python's builtin type graph.
//
// BYTE-IDENTITY: clauses are emitted ONLY when isinstance atoms are present
// in the formula, and ONLY for pairs that are both (a) recognized builtins
// and (b) genuinely disjoint. Pure arithmetic formulas are unchanged.

use std::collections::{BTreeMap, BTreeSet};
use sugar_ir_types::*;

/// The set of concrete builtin Python type names we emit disjointness for.
/// This MUST match ``_ISINSTANCE_CONCRETE_BUILTINS`` in layer2.py exactly.
/// A type not in this set → no clause emitted (safe under-refusal).
const KNOWN_BUILTINS: &[&str] = &[
    "int",
    "str",
    "float",
    "complex",
    "bytes",
    "bytearray",
    "list",
    "tuple",
    "dict",
    "set",
    "frozenset",
    "bool",
    "NoneType",
    "type",
];

/// The SMT symbol the lifter emits for a Python type name T:
/// ``pytype_<T>`` (ASCII alnum + underscore; matches layer2.py ``f"pytype_{type_name}"``).
fn pytype_symbol(type_name: &str) -> String {
    format!("pytype_{}", type_name)
}

/// Return true iff the two builtin type names are GENUINELY DISJOINT in Python.
///
/// Every distinct pair is disjoint EXCEPT {int, bool}: bool IS a subtype of
/// int (``isinstance(True, int) is True``). Asserting int/bool disjoint would
/// falsely refuse ``isinstance(x,int) ∧ isinstance(x,bool)`` → inadmissible.
///
/// All other pairs in KNOWN_BUILTINS are pairwise disjoint in CPython's
/// builtin type hierarchy.
fn are_disjoint(a: &str, b: &str) -> bool {
    if a == b {
        return false; // same type is never disjoint from itself
    }
    // The ONE exception: int and bool are NOT disjoint (bool ⊂ int).
    let is_int_bool = (a == "int" && b == "bool") || (a == "bool" && b == "int");
    !is_int_bool
}

/// Walk a formula collecting all isinstance atoms.
/// Polarity-blind (we collect under ``not`` too): the disjointness clause is a
/// background axiom, true regardless of polarity.
pub struct IsinstanceClauses {
    /// Map from subject SMT string → set of type names seen with that subject.
    by_subject: BTreeMap<String, BTreeSet<String>>,
}

impl IsinstanceClauses {
    /// Collect all isinstance atoms from a formula.
    pub fn from_formula(formula: &Formula) -> Self {
        let mut by_subject: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        collect_isinstance_formula(formula, &mut by_subject);
        Self { by_subject }
    }

    /// Emit the preamble lines asserting disjointness for genuinely-disjoint
    /// builtin type pairs that share the same subject in this formula.
    ///
    /// For each subject S with types {A, B, ...} where A and B are in
    /// KNOWN_BUILTINS AND are_disjoint(A, B):
    ///   ``(assert (not (and (isinstance <S> pytype_A) (isinstance <S> pytype_B))))``
    ///
    /// Emits nothing if no isinstance atoms are present.
    pub fn preamble(&self) -> String {
        let mut out = String::new();
        for (subject, types) in &self.by_subject {
            // Filter to recognized builtins only (defense in depth).
            let known: Vec<&str> = types
                .iter()
                .map(|s| s.as_str())
                .filter(|t| KNOWN_BUILTINS.contains(t))
                .collect();
            // Emit one clause per genuinely-disjoint pair.
            for i in 0..known.len() {
                for j in (i + 1)..known.len() {
                    let a = known[i];
                    let b = known[j];
                    if are_disjoint(a, b) {
                        out.push_str(&format!(
                            "(assert (not (and (isinstance {} {}) (isinstance {} {}))))\n",
                            subject,
                            pytype_symbol(a),
                            subject,
                            pytype_symbol(b),
                        ));
                    }
                }
            }
        }
        out
    }
}

/// Emit the subject term as a raw SMT string for use as a map key.
/// Must match what `emit_term` in emitter.rs would produce so that
/// same-subject atoms cluster correctly.
fn render_subject(term: &Term) -> Option<String> {
    match term {
        Term::Var { name, .. } => {
            // Mirror smt_quote: only alpha/special chars need quoting.
            // For variable names from the pytest lifter (plain identifiers),
            // this is just the name. We replicate the simple-symbol test
            // from emitter.rs::smt_quote.
            Some(smt_quote_subject(name))
        }
        // Non-var subjects (ctor, const, ...) are not common in isinstance;
        // refuse gracefully (return None → no clause for this atom).
        _ => None,
    }
}

fn smt_quote_subject(name: &str) -> String {
    let simple = !name.is_empty()
        && !name.chars().next().is_some_and(|c| c.is_ascii_digit())
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "~!@$%^&*_-+=<>.?/".contains(c));
    if simple {
        name.to_string()
    } else {
        format!("|{}|", name)
    }
}

fn collect_isinstance_formula(formula: &Formula, out: &mut BTreeMap<String, BTreeSet<String>>) {
    match formula {
        Formula::Atomic { name, args } => {
            // Recognize: isinstance(<subject>, <ctor "pytype_T">)
            if name == "isinstance" && args.len() == 2 {
                if let Term::Ctor {
                    name: ctor_name,
                    args: ctor_args,
                } = &args[1]
                {
                    if ctor_args.is_empty() {
                        if let Some(type_name) = ctor_name.strip_prefix("pytype_") {
                            if let Some(subject_smt) = render_subject(&args[0]) {
                                out.entry(subject_smt)
                                    .or_default()
                                    .insert(type_name.to_string());
                            }
                        }
                    }
                }
            }
        }
        Formula::And { operands }
        | Formula::Or { operands }
        | Formula::Not { operands }
        | Formula::Implies { operands } => {
            for o in operands {
                collect_isinstance_formula(o, out);
            }
        }
        Formula::Forall { body, .. }
        | Formula::Exists { body, .. }
        | Formula::Choice { body, .. } => {
            collect_isinstance_formula(body, out);
        }
        Formula::Substitute { .. } | Formula::Apply { .. } => {}
        Formula::DivergenceBetween { source, target } => {
            collect_isinstance_formula(source, out);
            collect_isinstance_formula(target, out);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn var(name: &str) -> Term {
        serde_json::from_value(json!({"kind":"var","name":name})).unwrap()
    }

    fn pytype_ctor(type_name: &str) -> Term {
        serde_json::from_value(json!({
            "kind": "ctor",
            "name": format!("pytype_{}", type_name),
            "args": []
        }))
        .unwrap()
    }

    fn isinstance_atom(subject: Term, type_name: &str) -> Formula {
        Formula::Atomic {
            name: "isinstance".to_string(),
            args: vec![subject, pytype_ctor(type_name)],
        }
    }

    fn and2(a: Formula, b: Formula) -> Formula {
        Formula::And {
            operands: vec![a, b],
        }
    }

    fn not1(a: Formula) -> Formula {
        Formula::Not { operands: vec![a] }
    }

    // ── Structural tests (preamble emission) ──────────────────────────────

    #[test]
    fn no_isinstance_emits_empty_preamble() {
        // Pure arithmetic formula → no isinstance atoms → byte-identical empty.
        let formula = Formula::Atomic {
            name: "=".to_string(),
            args: vec![var("x"), var("y")],
        };
        let ic = IsinstanceClauses::from_formula(&formula);
        assert_eq!(
            ic.preamble(),
            "",
            "no isinstance → empty preamble (byte-identical)"
        );
    }

    #[test]
    fn single_isinstance_atom_no_pair_emits_empty() {
        // A single isinstance atom: no disjoint pair possible → empty preamble.
        let formula = isinstance_atom(var("x"), "int");
        let ic = IsinstanceClauses::from_formula(&formula);
        assert_eq!(
            ic.preamble(),
            "",
            "single isinstance → no disjoint pair → empty"
        );
    }

    #[test]
    fn disjoint_pair_same_subject_emits_clause() {
        // isinstance(x, int) ∧ isinstance(x, str) → emit disjointness clause.
        let formula = and2(
            isinstance_atom(var("x"), "int"),
            isinstance_atom(var("x"), "str"),
        );
        let ic = IsinstanceClauses::from_formula(&formula);
        let preamble = ic.preamble();
        assert!(
            preamble.contains(
                "(assert (not (and (isinstance x pytype_int) (isinstance x pytype_str))))"
            ) || preamble.contains(
                "(assert (not (and (isinstance x pytype_str) (isinstance x pytype_int))))"
            ),
            "int/str same-subject must emit disjointness clause: {preamble}"
        );
    }

    #[test]
    fn int_bool_same_subject_no_clause() {
        // isinstance(x, int) ∧ isinstance(x, bool): bool⊂int → NOT disjoint → no clause.
        // This is the PERMANENT false-refusal guard.
        let formula = and2(
            isinstance_atom(var("x"), "int"),
            isinstance_atom(var("x"), "bool"),
        );
        let ic = IsinstanceClauses::from_formula(&formula);
        let preamble = ic.preamble();
        assert!(
            preamble.is_empty(),
            "int/bool must NOT emit a disjointness clause (bool⊂int): {preamble}"
        );
    }

    #[test]
    fn different_subjects_no_clause() {
        // isinstance(x, int) ∧ isinstance(y, str): different subjects → no clause.
        let formula = and2(
            isinstance_atom(var("x"), "int"),
            isinstance_atom(var("y"), "str"),
        );
        let ic = IsinstanceClauses::from_formula(&formula);
        let preamble = ic.preamble();
        assert!(
            preamble.is_empty(),
            "different subjects must NOT emit a disjointness clause: {preamble}"
        );
    }

    #[test]
    fn polarity_blind_collects_under_not() {
        // isinstance collected under `not` too (background axiom, polarity-blind).
        let formula = and2(
            isinstance_atom(var("x"), "int"),
            not1(isinstance_atom(var("x"), "str")),
        );
        let ic = IsinstanceClauses::from_formula(&formula);
        // x has both int and str (one under not); should emit clause.
        let preamble = ic.preamble();
        assert!(
            preamble.contains("isinstance x pytype_int")
                && preamble.contains("isinstance x pytype_str"),
            "polarity-blind: must emit clause even when one atom is under not: {preamble}"
        );
    }

    #[test]
    fn unrecognized_type_name_no_clause() {
        // isinstance(x, pytype_MyClass): unrecognized → no clause (safe under-refusal).
        let formula = and2(
            isinstance_atom(var("x"), "MyClass"),
            isinstance_atom(var("x"), "int"),
        );
        let ic = IsinstanceClauses::from_formula(&formula);
        let preamble = ic.preamble();
        // MyClass is not in KNOWN_BUILTINS → no int/MyClass pair → empty.
        assert!(
            preamble.is_empty(),
            "unrecognized type must not emit a clause: {preamble}"
        );
    }

    // ── End-to-end soundness via z3 ───────────────────────────────────────
    // These tests gate on z3 availability (hard-fail like literal_encoding).

    fn which_z3() -> Option<String> {
        for cand in [
            "z3",
            "/opt/homebrew/bin/z3",
            "/usr/local/bin/z3",
            "/usr/bin/z3",
        ] {
            if std::process::Command::new(cand)
                .arg("--version")
                .output()
                .map(|o| o.status.success())
                .unwrap_or(false)
            {
                return Some(cand.to_string());
            }
        }
        None
    }

    fn run_z3(z3: &str, script: &str) -> String {
        use std::io::Write;
        let mut child = std::process::Command::new(z3)
            .args(["-smt2", "-in"])
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .spawn()
            .expect("spawn z3");
        child
            .stdin
            .as_mut()
            .unwrap()
            .write_all(script.as_bytes())
            .unwrap();
        let out = child.wait_with_output().unwrap();
        String::from_utf8_lossy(&out.stdout).to_string()
    }

    // Helper: build a minimal SMT script that asserts isinstance(x,A) ∧ isinstance(x,B)
    // and check-sats it, INCLUDING the disjointness preamble.
    fn isinstance_script(subject: &str, type_a: &str, type_b: &str) -> String {
        let pa = pytype_symbol(type_a);
        let pb = pytype_symbol(type_b);
        // Build minimal formula to collect from.
        let formula = and2(
            isinstance_atom(var(subject), type_a),
            isinstance_atom(var(subject), type_b),
        );
        let ic = IsinstanceClauses::from_formula(&formula);
        let disjointness_preamble = ic.preamble();
        format!(
            "(set-logic ALL)\n\
             (declare-const {subject} Int)\n\
             (declare-const {pa} Int)\n\
             (declare-const {pb} Int)\n\
             (declare-fun isinstance (Int Int) Bool)\n\
             {disjointness_preamble}\
             (assert (isinstance {subject} {pa}))\n\
             (assert (isinstance {subject} {pb}))\n\
             (check-sat)\n"
        )
    }

    #[test]
    fn isinstance_int_str_same_subject_is_unsat_under_z3() {
        // DISCRIMINATION: isinstance(x,int) ∧ isinstance(x,str) → UNSAT (disjoint).
        // RED before encoder: sat (spurious model). GREEN after: unsat.
        let z3 = which_z3().expect(
            "z3 must be available for isinstance soundness check; \
             install z3 and re-run (a missing z3 is a false green)",
        );
        let script = isinstance_script("x", "int", "str");
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "isinstance(x,int) ∧ isinstance(x,str) must be UNSAT (disjoint types); \
             z3 said: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn isinstance_int_bool_same_subject_is_sat_under_z3() {
        // FALSE-REFUSAL GUARD (PERMANENT): isinstance(x,int) ∧ isinstance(x,bool)
        // must be SAT (bool⊂int in Python; True IS an int). MUST NEVER be unsat.
        let z3 = which_z3().expect(
            "z3 must be available for isinstance bool⊂int guard; \
             install z3 and re-run (a missing z3 is a false green)",
        );
        let script = isinstance_script("x", "int", "bool");
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "sat",
            "isinstance(x,int) ∧ isinstance(x,bool) must be SAT (bool⊂int); \
             z3 said: {out}\nscript:\n{script} — \
             THIS IS THE PERMANENT FALSE-REFUSAL GUARD; MUST NOT BE REMOVED"
        );
    }

    #[test]
    fn isinstance_different_subjects_is_sat_under_z3() {
        // DISCRIMINATION: isinstance(x,int) ∧ isinstance(y,str) with DIFFERENT
        // subjects must be SAT (independent, no disjointness clause applies).
        let z3 = which_z3().expect(
            "z3 must be available for isinstance different-subjects check; \
             install z3 and re-run",
        );
        // Build script manually for different subjects.
        let formula = and2(
            isinstance_atom(var("x"), "int"),
            isinstance_atom(var("y"), "str"),
        );
        let ic = IsinstanceClauses::from_formula(&formula);
        let disjointness_preamble = ic.preamble();
        let script = format!(
            "(set-logic ALL)\n\
             (declare-const x Int)\n\
             (declare-const y Int)\n\
             (declare-const pytype_int Int)\n\
             (declare-const pytype_str Int)\n\
             (declare-fun isinstance (Int Int) Bool)\n\
             {disjointness_preamble}\
             (assert (isinstance x pytype_int))\n\
             (assert (isinstance y pytype_str))\n\
             (check-sat)\n"
        );
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "sat",
            "isinstance(x,int) ∧ isinstance(y,str) with different subjects must be SAT; \
             z3 said: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn isinstance_same_type_self_contradiction_is_unsat_under_z3() {
        // DISCRIMINATION: isinstance(x,int) ∧ ¬isinstance(x,int) → UNSAT (P∧¬P).
        // No disjointness axiom needed — pure propositional contradiction.
        let z3 = which_z3().expect("z3 must be available");
        let script = format!(
            "(set-logic ALL)\n\
             (declare-const x Int)\n\
             (declare-const pytype_int Int)\n\
             (declare-fun isinstance (Int Int) Bool)\n\
             (assert (isinstance x pytype_int))\n\
             (assert (not (isinstance x pytype_int)))\n\
             (check-sat)\n"
        );
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "isinstance(x,int) ∧ ¬isinstance(x,int) must be UNSAT (P∧¬P); z3 said: {out}"
        );
    }
}
