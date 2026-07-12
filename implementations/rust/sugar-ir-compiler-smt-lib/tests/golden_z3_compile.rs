// SPDX-License-Identifier: MIT OR Apache-2.0
//
// LANE C golden pair (1/2): z3-compile golden.
//
// This is the FIRST per-target golden unit test keyed on the ONE object
// (ProofIR IrFormula -> compiled SMT-LIB script). It fixtures a small,
// CID-pinned IrFormula (atomic + and + implies, plus a sort declaration)
// and asserts the emitted SMT-LIB v2.6 script matches a golden string
// EXACTLY, byte for byte. No solver is invoked; this is a pure compiler
// unit test.
//
// The companion z3-solve golden lives in
// sugar-verifier/tests/golden_z3_solve.rs and feeds a golden SMT-LIB
// script (not this one -- a hand-written SAT/UNSAT pair) to the actual z3
// binary through the Solver trait. Together the two tests are the
// template for the other compiler targets (coq, lean): one golden test
// per crate, pinned on the compiler-shape object each crate owns
// (compile-to-script here, solve-a-script there).
//
// -- Why this fixture triggers a sort declaration --
//
// The `identity` atomic (`Formula::Atomic { name: "identity", args: [a, b] }`)
// is Sugar's language-neutral identity predicate. Whenever it appears
// anywhere in the formula tree, the SMT-LIB backend declares a fixed
// uninterpreted sort `SugarIdentity` in the preamble
// (`sugar-ir-compiler-smt-lib/src/emitter.rs`, `IDENTITY_SORT` /
// `has_identity_predicate`) and renders each identity-compared variable as
// `|identity:var:<name>|`, a const of that sort. This is the SIMPLEST
// deterministic sort-declaration path in the emitter: the sort name is a
// fixed string (no CID hash to reproduce by hand in a golden test), unlike
// the CID-derived `S_<hash>` opaque-quantifier-sort path or the
// hash-suffixed identity CONST encoding (both of which pin fine, but only
// via a live compile since the hash is CID-derived and not meant to be
// hand-computed in a test fixture).
//
// Fixture shape: `implies(and(identity(a, b), (x > 0)), true)`.
//   - `identity(a, b)`  -- atomic, triggers `(declare-sort SugarIdentity 0)`
//                          and declares `a`, `b` as `SugarIdentity` consts.
//   - `x > 0`           -- atomic, ordinary Int free var + Int const.
//   - `and(...)`        -- connective.
//   - `implies(..., true)` -- connective, with the builtin nullary `true`.

use serde_json::json;

use sugar_ir_compiler::{CompilerInput, IrCompiler};
use sugar_ir_compiler_smt_lib::{SmtLibCompiler, DIALECT};

/// The fixture IrFormula, as raw IR-JSON. CID-pinned below via its exact
/// JCS-canonical serialization bytes (`fixture_bytes_are_pinned`), so any
/// drift in the fixture's shape -- not just the emitted script -- fails
/// loudly instead of silently re-baselining.
fn fixture() -> serde_json::Value {
    json!({
        "kind": "implies",
        "operands": [
            {
                "kind": "and",
                "operands": [
                    {
                        "kind": "atomic",
                        "name": "identity",
                        "args": [
                            {"kind": "var", "name": "a"},
                            {"kind": "var", "name": "b"}
                        ]
                    },
                    {
                        "kind": "atomic",
                        "name": ">",
                        "args": [
                            {"kind": "var", "name": "x"},
                            {
                                "kind": "const",
                                "value": 0,
                                "sort": {"kind": "primitive", "name": "Int"}
                            }
                        ]
                    }
                ]
            },
            {"kind": "atomic", "name": "true", "args": []}
        ]
    })
}

/// The fixture's content address: `blake3-512` over its JCS-canonical
/// (sorted-key) serialization, via the project's one public JSON-CID bridge
/// (`sugar_canonicalizer::jcs_cid_of_json`). Pinned so a future edit to
/// `fixture()` that silently changes its shape (key order is irrelevant to
/// JCS, but an added/removed field or retyped literal is NOT) is caught here
/// even if the compiled-script assertion below happens not to move.
const FIXTURE_CID: &str = "blake3-512:aa50491c92d94bd2c9ccf1214203f0c766fa5c9564ee113057091640916b4d579812d3cc888d4441f88b27be8c5f2b5bf2839f46eaacaab7469c2bc92be096ed";

fn compile(ir: &serde_json::Value) -> String {
    let input = CompilerInput::decode_json(ir.clone()).expect("fixture decodes as CompilerInput");
    SmtLibCompiler::new()
        .compile_typed(&input, DIALECT)
        .expect("fixture compiles")
        .script()
}

#[test]
fn fixture_bytes_are_pinned() {
    // Content-address the live fixture value the same way the rest of the
    // codebase content-addresses any JSON artifact (canonical Value -> JCS
    // -> blake3-512), so this pin tracks the fixture's *meaning* (its JCS
    // bytes) rather than its Rust literal's insertion order.
    let cid = sugar_canonicalizer::jcs_cid_of_json(&fixture());
    assert_eq!(
        cid, FIXTURE_CID,
        "fixture IrFormula drifted from its CID-pinned bytes; if this \
         change is intentional, re-derive FIXTURE_CID (print it, don't \
         hand-compute it) and update the golden script below in the same \
         commit"
    );
}

const GOLDEN_SCRIPT: &str = "(set-logic ALL)\n\
(declare-sort SugarIdentity 0)\n\
(declare-const |identity:var:a| SugarIdentity)\n\
(declare-const |identity:var:b| SugarIdentity)\n\
(declare-const x Int)\n\
(assert (not (=> (and (= |identity:var:a| |identity:var:b|) (> x 0)) true)))\n\
(check-sat)\n";

#[test]
fn z3_compile_golden_script_matches_exactly() {
    let script = compile(&fixture());
    assert_eq!(
        script, GOLDEN_SCRIPT,
        "emitted SMT-LIB script drifted from the golden byte-for-byte baseline\n\
         --- actual ---\n{script}\n--- golden ---\n{GOLDEN_SCRIPT}"
    );
}

#[test]
fn golden_script_declares_the_sort_from_the_identity_atomic() {
    let script = compile(&fixture());
    assert!(
        script.contains("(declare-sort SugarIdentity 0)"),
        "golden fixture must exercise a sort declaration:\n{script}"
    );
}

#[test]
fn golden_script_carries_atomic_and_implies() {
    let script = compile(&fixture());
    assert!(
        script.contains("(> x 0)"),
        "atomic predicate missing:\n{script}"
    );
    assert!(
        script.contains("(and "),
        "and connective missing:\n{script}"
    );
    assert!(
        script.contains("(=> "),
        "implies connective missing:\n{script}"
    );
}
