// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Bundled SMT-LIB v2.6 IR compiler. Extracted from the inline
// sugar-verifier::smt_emitter so the same code serves both the
// in-process fast path (verifier deps directly on this crate) and the
// standalone subprocess binary `sugar-ir-smt-lib`.
//
// Spec: protocol/specs/2026-04-30-ir-compiler-protocol.md.

use serde_json::Value as Json;

use sugar_ir_compiler::{
    Capabilities, CompileError, CompiledFormula, CompilerInput, IrCompiler, OpacityManifest,
    PROTOCOL_VERSION,
};

pub mod derive_query;
mod emitter;
mod isinstance_encoding;
mod literal_encoding;
pub mod regex_regln;

pub const DIALECT: &str = "smt-lib-v2.6";
pub const COMPILER_NAME: &str = "smt-lib-reference";
pub const COMPILER_VERSION: &str = env!("CARGO_PKG_VERSION");

/// SMT-LIB v2.6 compiler. Stateless; one instance suffices for any
/// number of compile calls.
pub struct SmtLibCompiler;

impl SmtLibCompiler {
    pub fn new() -> Self {
        Self
    }
}

impl Default for SmtLibCompiler {
    fn default() -> Self {
        Self::new()
    }
}

impl IrCompiler for SmtLibCompiler {
    fn compile_typed(
        &self,
        ir: &CompilerInput,
        dialect: &str,
    ) -> Result<CompiledFormula, CompileError> {
        if dialect != DIALECT {
            return Err(CompileError::UnsupportedDialect(dialect.to_string()));
        }
        compile_input_to_parts(ir)
    }

    fn capabilities(&self) -> Capabilities {
        Capabilities {
            name: COMPILER_NAME.to_string(),
            version: COMPILER_VERSION.to_string(),
            protocol_version: PROTOCOL_VERSION.to_string(),
            dialects: vec![DIALECT.to_string()],
            supported_sorts: vec![
                "Int".to_string(),
                "Bool".to_string(),
                "Real".to_string(),
                "String".to_string(),
            ],
            supported_predicates: vec![
                "=".to_string(),
                "identity".to_string(),
                "distinct".to_string(),
                "<".to_string(),
                "<=".to_string(),
                ">".to_string(),
                ">=".to_string(),
                "and".to_string(),
                "or".to_string(),
                "not".to_string(),
                "implies".to_string(),
                "forall".to_string(),
                "exists".to_string(),
                "\u{2260}".to_string(), // ≠
                "\u{2264}".to_string(), // ≤
                "\u{2265}".to_string(), // ≥
            ],
        }
    }
}

/// Walk an IrTerm tree; reject any `Var` with an empty `name`. Spec
/// requires variable names to be non-empty identifiers; an empty name
/// would lower to an empty SMT-LIB symbol which the solver rejects
/// (or worse, silently aliases to another symbol). Validate at the
/// boundary so callers see an honest error instead of a malformed
/// emit.
fn validate_term(term: &sugar_ir_types::IrTerm) -> Result<(), String> {
    match term {
        sugar_ir_types::IrTerm::Var { name } => {
            if name.is_empty() {
                return Err("var name must not be empty".to_string());
            }
            Ok(())
        }
        sugar_ir_types::IrTerm::Const { .. } => Ok(()),
        sugar_ir_types::IrTerm::Ctor { args, .. } => args.iter().try_for_each(validate_term),
        sugar_ir_types::IrTerm::Lambda { body, .. } => validate_term(body),
        sugar_ir_types::IrTerm::Let { body, .. } => validate_term(body),
    }
}

/// H1 [B7]: mixed-sort conjunction detection.
///
/// A conjoined formula can equate the SAME `#euf#` ctor term to a String
/// literal in one row (String-theory regime: the ctor's return sort is SMT
/// `String`) and to an Int/Bool literal in another row (legacy opaque-Int
/// regime: return sort `Int`). One `(declare-fun ...)` cannot carry both
/// return sorts, so the emitted script would be ill-sorted -> z3 parse
/// error -> an OPAQUE Undecidable. Detect the conflict at emit time and
/// return a NAMED error instead, which the verifier surfaces as a loud
/// Undecidable with the reason intact.
///
/// Regime attribution mirrors `literal_encoding::routes_to_string_theory`
/// exactly (same gate the emitter uses to pick the encoding), so detection
/// can never disagree with emission.
fn check_mixed_sort_conjunction(formula: &sugar_ir_types::IrFormula) -> Result<(), String> {
    use std::collections::BTreeMap;
    let mut regimes: BTreeMap<String, &'static str> = BTreeMap::new();
    walk_mixed_sort(formula, &mut regimes)
}

fn mark_regime(
    name: &str,
    regime: &'static str,
    regimes: &mut std::collections::BTreeMap<String, &'static str>,
) -> Result<(), String> {
    if let Some(prev) = regimes.get(name) {
        if *prev != regime {
            return Err(format!(
                "mixed-sort conjunction on {name}: String vs Int \
                 (same ctor equated to a String literal in one row and an \
                 Int/Bool literal in another; one declare-fun cannot carry \
                 both return sorts)"
            ));
        }
    } else {
        regimes.insert(name.to_string(), regime);
    }
    Ok(())
}

fn walk_mixed_sort(
    formula: &sugar_ir_types::IrFormula,
    regimes: &mut std::collections::BTreeMap<String, &'static str>,
) -> Result<(), String> {
    use sugar_ir_types::{IrFormula, IrTerm};
    match formula {
        IrFormula::Atomic { name, args } => {
            let is_real_ctor = |t: &IrTerm| matches!(t, IrTerm::Ctor { name, args } if !(name == "None" && args.is_empty()));
            if literal_encoding::routes_to_string_theory(name, args) {
                // String regime: every non-None ctor in this atom gets SMT
                // `String` return sort from the string-theory emitter.
                for a in args {
                    if let IrTerm::Ctor { name: cn, .. } = a {
                        if is_real_ctor(a) {
                            mark_regime(cn, "String", regimes)?;
                        }
                    }
                }
            } else if name == "=" && args.len() == 2 {
                // Legacy regime: a ctor equated to an Int/Bool literal (or a
                // String literal NOT carrying the String sort -- the opaque
                // strlit_ Int encoding) is declared with Int return sort.
                let is_legacy_const = |t: &IrTerm| {
                    matches!(
                        t,
                        IrTerm::Const {
                            value: serde_json::Value::Number(_) | serde_json::Value::Bool(_),
                            ..
                        }
                    ) || matches!(
                        t,
                        IrTerm::Const {
                            value: serde_json::Value::String(_),
                            sort,
                        } if !matches!(sort, sugar_ir_types::Sort::Primitive { name } if name == "String")
                    )
                };
                for (i, j) in [(0usize, 1usize), (1, 0)] {
                    if is_real_ctor(&args[i]) && is_legacy_const(&args[j]) {
                        if let IrTerm::Ctor { name: cn, .. } = &args[i] {
                            mark_regime(cn, "Int", regimes)?;
                        }
                    }
                }
            }
            Ok(())
        }
        IrFormula::And { operands }
        | IrFormula::Or { operands }
        | IrFormula::Not { operands }
        | IrFormula::Implies { operands } => operands
            .iter()
            .try_for_each(|o| walk_mixed_sort(o, regimes)),
        IrFormula::Forall { body, .. }
        | IrFormula::Exists { body, .. }
        | IrFormula::Choice { body, .. } => walk_mixed_sort(body, regimes),
        IrFormula::Substitute { .. }
        | IrFormula::Apply { .. }
        | IrFormula::DivergenceBetween { .. } => Ok(()),
    }
}

fn validate_formula(formula: &sugar_ir_types::IrFormula) -> Result<(), String> {
    match formula {
        sugar_ir_types::IrFormula::Atomic { args, .. } => args.iter().try_for_each(validate_term),
        sugar_ir_types::IrFormula::And { operands }
        | sugar_ir_types::IrFormula::Or { operands }
        | sugar_ir_types::IrFormula::Not { operands }
        | sugar_ir_types::IrFormula::Implies { operands } => {
            operands.iter().try_for_each(validate_formula)
        }
        sugar_ir_types::IrFormula::Forall { body, .. }
        | sugar_ir_types::IrFormula::Exists { body, .. }
        | sugar_ir_types::IrFormula::Choice { body, .. } => validate_formula(body),
        // wp-rule schema nodes (spec 2026-05-13-wp-as-formula.md §2.3):
        // `substitute` / `apply` appear only inside an unreduced `wp_rule`
        // term; `libsugar::wp` eliminates them before any formula reaches
        // the SMT-LIB backend. Reaching this arm means a `wp_rule` schema was
        // handed to the solver without instantiation.
        sugar_ir_types::IrFormula::Substitute { .. } | sugar_ir_types::IrFormula::Apply { .. } => {
            Err(
                "wp-rule schema node (substitute/apply) reached the SMT-LIB validator; \
             it must be reduced via libsugar::wp before solving"
                    .to_string(),
            )
        }
        sugar_ir_types::IrFormula::DivergenceBetween { .. } => Err(
            "platform divergence formula reached the SMT-LIB validator; \
             stage 4 must lower it before solving"
                .to_string(),
        ),
    }
}

fn compile_input_to_parts(input: &CompilerInput) -> Result<CompiledFormula, CompileError> {
    match input {
        CompilerInput::Formula(formula) => compile_formula_to_parts(formula.formula()),
        CompilerInput::Term(term) => compile_term_to_parts(term),
        CompilerInput::EquationalTheory(_) => Err(CompileError::UnsupportedPredicate(
            "equational_theory".to_string(),
        )),
    }
}

pub fn compile_formula_to_parts(
    formula: &sugar_ir_types::Formula,
) -> Result<CompiledFormula, CompileError> {
    validate_formula(formula).map_err(CompileError::MalformedIr)?;
    check_mixed_sort_conjunction(formula).map_err(CompileError::UnsupportedSort)?;
    emitter::compile_formula(formula)
}

pub fn compile_asserted_formula_to_parts(
    formula: &sugar_ir_types::Formula,
) -> Result<CompiledFormula, CompileError> {
    validate_formula(formula).map_err(CompileError::MalformedIr)?;
    check_mixed_sort_conjunction(formula).map_err(CompileError::UnsupportedSort)?;
    emitter::compile_asserted_formula(formula)
}

pub fn compile_term_to_parts(term: &sugar_ir_types::Term) -> Result<CompiledFormula, CompileError> {
    validate_term(term).map_err(CompileError::MalformedIr)?;
    Ok(CompiledFormula {
        preamble: String::new(),
        body: emitter::emit_term(term),
        free_vars: vec![],
        opacity_manifest: OpacityManifest::default(),
        metadata: Json::Null,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture_compile_to_parts(ir_formula: &Json) -> Result<CompiledFormula, CompileError> {
        let input = CompilerInput::decode_json(ir_formula.clone())?;
        compile_input_to_parts(&input)
    }

    fn fixture_compile_asserted_to_parts(
        ir_formula: &Json,
    ) -> Result<CompiledFormula, CompileError> {
        let input = CompilerInput::decode_json(ir_formula.clone())?;
        let CompilerInput::Formula(formula) = input else {
            return Err(CompileError::MalformedIr(
                "asserted SMT-LIB compile expects a formula input".to_string(),
            ));
        };
        compile_asserted_formula_to_parts(formula.formula())
    }

    fn eq(a: serde_json::Value, b: serde_json::Value) -> serde_json::Value {
        serde_json::json!({"kind": "atomic", "name": "=", "args": [a, b]})
    }
    fn ctor(name: &str, args: Vec<serde_json::Value>) -> serde_json::Value {
        serde_json::json!({"kind": "ctor", "name": name, "args": args})
    }
    fn var(name: &str) -> serde_json::Value {
        serde_json::json!({"kind": "var", "name": name})
    }

    // REGRESSION (main red since 2026-06-10): `version.to_string() == "1.2.3"`
    // is a string-routed equality whose subject is a method callresult. The
    // receiver `v` is the OPAQUE call target, not a string -- only the call
    // RESULT is String. The ctor-decl pass declares `method:to_string` as
    // `(Int) String` (opaque receiver -> String result), so the free-var pass
    // must declare `v` as Int to MATCH. The string-context free-var collector
    // wrongly marked it String, desyncing the param sort from the var decl;
    // z3 then rejected the ill-sorted `(method:to_string <String>)` with
    // `unknown constant method:to_string (String)` -> sound refuse -> every
    // to_string/Display showcase row (std-core, url, semver, uuid, itertools)
    // went red.
    #[test]
    fn method_callresult_receiver_is_opaque_not_string() {
        let inv = eq(
            ctor("method:to_string", vec![var("v")]),
            string_const("1.2.3"),
        );
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            !script.contains("(declare-const v String)"),
            "receiver var must NOT be String -- only the call result is String:\n{script}"
        );
        assert!(
            script.contains("(declare-const v Int)"),
            "receiver var must be Int (opaque), matching method:to_string's (Int) param:\n{script}"
        );
    }

    #[test]
    fn method_callresult_string_equality_is_well_sorted_for_z3() {
        let z3 = which_z3().expect("z3 required for well-sortedness check");
        let inv = eq(
            ctor("method:to_string", vec![var("v")]),
            string_const("1.2.3"),
        );
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert!(
            !out.contains("unknown constant"),
            "string-routed method-callresult equality must be well-sorted (no unknown constant):\n{out}\n--- script ---\n{script}"
        );
        assert!(
            !out.to_lowercase().contains("error"),
            "z3 must not error on a well-sorted script:\n{out}\n--- script ---\n{script}"
        );
    }

    #[test]
    fn monadic_method_adaptors_own_receiver_and_return_sorts() {
        let inv = eq(
            ctor("method:ok", vec![ctor("call:parse", vec![var("s")])]),
            ctor("opt:none", vec![]),
        );
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            script.contains("(declare-fun |call:parse| (Int) SugarResult)"),
            "parse receiver of Result::ok must return SugarResult:\n{script}"
        );
        assert!(
            script.contains("(declare-fun |method:ok| (SugarResult) SugarOption)"),
            "Result::ok must consume SugarResult and return SugarOption:\n{script}"
        );

        let inv = eq(
            ctor(
                "method:unwrap",
                vec![ctor("method:as_mut", vec![var("ptr")])],
            ),
            var("out"),
        );
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            script.contains("(declare-fun |method:as_mut| (Int) SugarOption)"),
            "as_mut Option adaptor must return SugarOption when unwrap consumes it:\n{script}"
        );
        assert!(
            script.contains("(declare-fun |method:unwrap| (SugarOption) Int)"),
            "unwrap over an Option adaptor must consume SugarOption:\n{script}"
        );

        let inv = eq(
            ctor("method:unwrap", vec![ctor("call:get", vec![var("xs")])]),
            var("out"),
        );
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            script.contains("(declare-fun |call:get| (Int) Int)"),
            "an opaque call result is not monadic unless a monadic adaptor owns that sort:\n{script}"
        );
        assert!(
            script.contains("(declare-fun |method:unwrap| (Int) Int)"),
            "unwrap over an opaque callsite must stay Int-sorted rather than guessing Option:\n{script}"
        );
    }

    #[test]
    fn quoted_symbols_escape_pipe_and_exact_underscore() {
        let inv = serde_json::json!({"kind":"and","operands":[
            eq(ctor("_", vec![]), int_const(1)),
            eq(ctor("closure:z", vec![]), int_const(0)),
            eq(ctor("closure:a | b", vec![int_const(1)]), int_const(2)),
            eq(ctor("closure:a | b", vec![int_const(1), int_const(2)]), int_const(3))
        ]});
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            script.contains("|sugar:_|"),
            "exact `_` must be mapped to a legal stable SMT symbol:\n{script}"
        );
        assert!(
            script.contains("|closure:z#arity0|")
                && !script.contains("|closure:z|")
                && script.contains("|closure:a \\| b#arity1|")
                && script.contains("|closure:a \\| b#arity2|"),
            "closure symbols must be escaped and arity-mangled, including nullary closures:\n{script}"
        );
        if let Some(z3) = which_z3() {
            let out = run_z3(&z3, &script);
            assert!(
                !out.to_lowercase().contains("error")
                    && !out.contains("unknown constant")
                    && out.contains("sat"),
                "escaped symbols must produce a real z3 verdict:\n{out}\n--- script ---\n{script}"
            );
        }
    }

    #[test]
    fn string_tainted_vars_drive_method_receiver_declarations() {
        let recv = var("displayed");
        let prefix = string_const("DynMetadata(0x");
        let inv = serde_json::json!({"kind":"and","operands":[
            string_theory_atom("prefix-of", vec![prefix.clone(), recv.clone()]),
            eq(ctor("method:starts_with", vec![recv, prefix]), int_const(1))
        ]});
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            script.contains("(declare-const displayed String)"),
            "prefix-of forces the receiver var to String:\n{script}"
        );
        assert!(
            script.contains("(declare-fun |method:starts_with| (String Int) Int)"),
            "method:starts_with must consume the same String-sorted receiver z3 sees:\n{script}"
        );
        if let Some(z3) = which_z3() {
            let out = run_z3(&z3, &script);
            assert!(
                !out.to_lowercase().contains("error") && !out.contains("unknown constant"),
                "string-tainted method receiver must be well-sorted:\n{out}\n--- script ---\n{script}"
            );
        }
    }

    #[test]
    fn ref_and_deref_monomorphize_adt_argument_sorts() {
        let result_ref = ctor("ref", vec![ctor("res:ok", vec![int_const(3)])]);
        let option_deref = ctor("deref", vec![ctor("opt:some", vec![int_const(4)])]);
        let int_ref = ctor("ref", vec![int_const(3)]);
        let inv = serde_json::json!({"kind":"and","operands":[
            eq(result_ref.clone(), result_ref),
            eq(option_deref.clone(), option_deref),
            eq(int_ref.clone(), int_ref)
        ]});
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            script.contains("(declare-fun |ref#args:SugarResult| (SugarResult) Int)")
                && script.contains("(declare-fun |deref#args:SugarOption| (SugarOption) Int)")
                && script.contains("(declare-fun ref (Int) Int)"),
            "generic ref/deref wrappers need one SMT head per argument sort:\n{script}"
        );
        if let Some(z3) = which_z3() {
            let out = run_z3(&z3, &script);
            assert!(
                !out.to_lowercase().contains("error") && !out.contains("unknown constant"),
                "sort-monomorphized ref/deref wrappers must be well-sorted:\n{out}\n--- script ---\n{script}"
            );
        }
    }

    #[test]
    fn nested_option_result_adts_are_declared_sort_correctly() {
        let try_find = ctor("method:try_find", vec![var("xs")]);
        let ok_none = ctor("res:ok", vec![ctor("opt:none", vec![])]);
        let try_reduce = ctor("method:try_reduce", vec![var("ys")]);
        let some_some = ctor("opt:some", vec![ctor("opt:some", vec![int_const(15)])]);
        let inv = serde_json::json!({"kind":"and","operands":[
            eq(try_find, ok_none),
            eq(try_reduce.clone(), some_some),
            eq(try_reduce, ctor("opt:none", vec![]))
        ]});
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            script.contains("SugarOptionOption")
                && script.contains("SugarResultOption")
                && script.contains("|opt:some#option|")
                && script.contains("|opt:none#option|")
                && script.contains("|res:ok#option|"),
            "nested Option/Result constructors must use nested ADT heads:\n{script}"
        );
        if let Some(z3) = which_z3() {
            let out = run_z3(&z3, &script);
            assert!(
                !out.to_lowercase().contains("error") && !out.contains("unknown constant"),
                "nested monadic ADT script must be well-sorted:\n{out}\n--- script ---\n{script}"
            );
        }
    }

    #[test]
    fn mixed_sort_conjunction_is_named_error_not_ill_sorted_script() {
        // H1 [B7]: a GENUINELY String-sorted `call:f` ctor (string-tainted by a
        // chars-in-set universe over it -> String return sort) equated to an Int
        // literal in another row (legacy regime -> Int return sort). One
        // declare-fun cannot carry both; the compiler must return a NAMED error
        // at emit time rather than an ill-sorted script.
        //
        // NOTE: a bare `call:f == "abc"` with NO universe is NOT a mixed-sort
        // since the string-contagion fix -- the untainted ctor stays opaque-Int
        // ("abc" -> strlit_), so `call:f == "abc" ∧ call:f == 7` now refutes
        // cleanly as UNSAT (see genuine_string_vs_int_conflict_still_caught_now_via_distinctness).
        // The named-error STOP is reserved for the REAL String-vs-Int collision:
        // a universe forces String, another row forces Int.
        let subject = ctor(
            "call:f",
            vec![serde_json::json!(
            {"kind":"const","value":1,"sort":{"kind":"primitive","name":"Int"}})],
        );
        let universe_row = string_theory_atom(
            "str.chars-in-set",
            vec![subject.clone(), string_const("abc")],
        );
        let int_row = eq(
            subject,
            serde_json::json!({"kind":"const","value":7,"sort":{"kind":"primitive","name":"Int"}}),
        );
        let ir = serde_json::json!({"kind":"and","operands":[universe_row, int_row]});

        for result in [
            fixture_compile_to_parts(&ir),
            fixture_compile_asserted_to_parts(&ir),
        ] {
            let err = result.expect_err("mixed-sort conjunction must be refused, not emitted");
            let msg = err.to_string();
            assert!(
                msg.contains("mixed-sort conjunction on call:f"),
                "error must name the conflict and the ctor: {msg}"
            );
            assert!(
                msg.contains("String vs Int"),
                "error must name both regimes: {msg}"
            );
        }
    }

    #[test]
    fn same_regime_conjunction_still_compiles() {
        // Discrimination twin for B7: two rows equating the same ctor to TWO
        // DIFFERENT Int literals are contradictory but NOT mixed-sort -- the
        // conjunction must still compile (the solver, not the emitter, rules
        // on satisfiability). The detector must not over-trigger.
        let mk = |v: i64| {
            eq(
                ctor(
                    "call:f",
                    vec![serde_json::json!(
                    {"kind":"const","value":1,"sort":{"kind":"primitive","name":"Int"}})],
                ),
                serde_json::json!({"kind":"const","value":v,"sort":{"kind":"primitive","name":"Int"}}),
            )
        };
        let ir = serde_json::json!({"kind":"and","operands":[mk(7), mk(8)]});
        fixture_compile_to_parts(&ir).expect("same-regime conjunction must compile");

        // And the all-String twin: same ctor equated to two String literals.
        let mks = |s: &str| {
            eq(
                ctor(
                    "call:g",
                    vec![serde_json::json!(
                    {"kind":"const","value":"x","sort":{"kind":"primitive","name":"String"}})],
                ),
                serde_json::json!({"kind":"const","value":s,"sort":{"kind":"primitive","name":"String"}}),
            )
        };
        let ir2 = serde_json::json!({"kind":"and","operands":[mks("a"), mks("b")]});
        fixture_compile_to_parts(&ir2).expect("all-String conjunction must compile");
    }

    #[test]
    fn negated_path_declares_non_builtin_ctors_as_uninterpreted_fns() {
        // The reflexive-discharge encoding: a non-arithmetic ctor head
        // (`Ok`) must be DECLARED as an uninterpreted function on the
        // negated (validity) path, not left undeclared. Before this, the
        // whitelist had to refuse such terms because the negated path could
        // not render them.
        let ir = eq(ctor("Ok", vec![var("x")]), ctor("Ok", vec![var("x")]));
        let parts = fixture_compile_to_parts(&ir).expect("compile");
        assert!(
            parts.preamble.contains("(declare-fun Ok ("),
            "Ok must be declared as an uninterpreted fn on the negated path: {}",
            parts.preamble
        );
        // The body asserts the NEGATION (prove validity via unsat).
        assert!(
            parts.body.contains("(assert (not"),
            "negated path must assert (not ...): {}",
            parts.body
        );
    }

    fn atomic(name: &str, args: Vec<serde_json::Value>) -> serde_json::Value {
        serde_json::json!({"kind": "atomic", "name": name, "args": args})
    }
    fn implies(a: serde_json::Value, b: serde_json::Value) -> serde_json::Value {
        serde_json::json!({"kind": "implies", "operands": [a, b]})
    }

    #[test]
    fn non_builtin_atomic_predicate_in_boolean_position_is_declared() {
        // A user predicate (`is_some`) sitting as a boolean atom in an
        // implication -- the panic-freedom guard-discharge shape -- must be
        // declared `(declare-fun is_some (Int) Bool)`. Before the
        // predicate-decl pass it was left undeclared and z3 rejected the
        // script with `unknown constant is_some`. This is the COMPLEMENT of the
        // builtin set, so it is generic and language-blind (no `is_some`
        // special-casing).
        let ir = implies(
            atomic("is_some", vec![var("opt")]),
            atomic("is_some", vec![var("opt")]),
        );
        let parts = fixture_compile_to_parts(&ir).expect("compile");
        assert!(
            parts.preamble.contains("(declare-fun is_some (Int) Bool)"),
            "is_some must be declared as a Bool-returning fn: {}",
            parts.preamble
        );
    }

    #[test]
    fn mixed_numeric_python_equality_uses_explicit_to_real_bridge() {
        let integer = int_const(3);
        let real = serde_json::json!({
            "kind": "const",
            "value": "3.5",
            "sort": {"kind": "primitive", "name": "Real"}
        });
        let stated = atomic("py.eq", vec![integer.clone(), real.clone()]);
        let promoted = ctor("to_real", vec![integer]);
        let inv = implies(stated.clone(), eq(promoted, real));
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        assert!(
            parts.body.contains("(to_real 3)"),
            "promotion must be explicit in the emitted bridge:\n{}",
            parts.body
        );
        assert!(
            !parts.preamble.contains("declare-fun to_real"),
            "to_real is an interpreted SMT bridge, not an implicit EUF:\n{}",
            parts.preamble
        );
        assert!(
            parts.body.contains("py.eq"),
            "stated atom must remain py.eq"
        );
    }

    #[test]
    fn python_less_equal_compiles_to_native_ordering_and_lying_twin_refutes() {
        let z3 = which_z3().expect("z3 required for py.le round-trip");
        for (name, left, right, native) in [
            ("py.le", 1, 12, "(<= 1 12)"),
            ("py.gt", 12, 1, "(> 12 1)"),
            ("py.ge", 12, 1, "(>= 12 1)"),
        ] {
            let parts =
                fixture_compile_to_parts(&atomic(name, vec![int_const(left), int_const(right)]))
                    .expect("compile comparison-family atom");
            assert!(
                parts.body.contains(native),
                "{name} must compile as native SMT ordering:\n{}",
                parts.body
            );
            assert!(
                !parts.preamble.contains(&format!("declare-fun {name}")),
                "{name} must not be declared as an uninterpreted predicate:\n{}",
                parts.preamble
            );
        }

        let truthful = atomic("py.le", vec![int_const(1), int_const(12)]);
        let lying = atomic("py.le", vec![int_const(12), int_const(1)]);

        let truthful_parts = fixture_compile_to_parts(&truthful).expect("compile truthful");
        let lying_parts = fixture_compile_to_parts(&lying).expect("compile lying");
        let truthful_script = format!("{}{}", truthful_parts.preamble, truthful_parts.body);
        let lying_script = format!("{}{}", lying_parts.preamble, lying_parts.body);

        assert_eq!(run_z3(&z3, &truthful_script).trim(), "unsat");
        assert_eq!(run_z3(&z3, &lying_script).trim(), "sat");
    }

    #[test]
    fn float_refinement_predicate_uses_real_call_result_sort_and_has_unsat_teeth() {
        let z3 = which_z3().expect("z3 required for float refinement predicate check");
        for (predicate, call_name) in [
            ("float.f64.is_nan", "method:div_duration_f64"),
            ("float.f32.is_infinite", "method:div_duration_f32"),
            ("float.f64.is_normal", "method:normal_value_f64"),
            ("float.f64.is_sign_positive", "method:positive_value_f64"),
            ("float.f64.is_sign_negative", "method:negative_value_f64"),
        ] {
            let call = ctor(call_name, vec![]);
            let atom = atomic(predicate, vec![call.clone()]);
            let inv = serde_json::json!({
                "kind": "and",
                "operands": [
                    atom.clone(),
                    {"kind": "not", "operands": [atom]},
                ]
            });
            let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
            assert!(
                parts
                    .preamble
                    .contains(&format!("(declare-fun |{call_name}| () Real)")),
                "float call result must be declared Real: {}",
                parts.preamble
            );
            assert!(
                parts
                    .preamble
                    .contains(&format!("(declare-fun {predicate} (Real) Bool)")),
                "float refinement predicate must accept Real: {}",
                parts.preamble
            );

            let script = format!("{}{}", parts.preamble, parts.body);
            let out = run_z3(&z3, &script);
            assert_eq!(
                out.trim(),
                "unsat",
                "P(call) and not P(call) must be UNSAT, got: {out}\nscript:\n{script}"
            );
        }
    }

    #[test]
    fn builtin_atomic_predicates_are_not_declared() {
        // DISCRIMINATION: builtin/theory predicates (`=`, `<`, ...) must NOT be
        // declared (they are SMT-LIB primitives). Declaring them would be a
        // redefinition error.
        let zero = serde_json::json!({"kind":"const","value":0,
            "sort":{"kind":"primitive","name":"Int"}});
        let ir = implies(
            atomic(">", vec![var("n"), zero]),
            atomic("=", vec![var("n"), var("n")]),
        );
        let parts = fixture_compile_to_parts(&ir).expect("compile");
        assert!(
            !parts.preamble.contains("(declare-fun = ")
                && !parts.preamble.contains("(declare-fun > "),
            "builtin predicates must not be declared: {}",
            parts.preamble
        );
    }

    #[test]
    fn guarded_pre_implication_discharges_bare_pre_does_not() {
        // STRUCTURAL end-to-end (panic-freedom soundness). The guard-discharge
        // obligation `(=> (is_some opt) (is_some opt))` is valid -> negation
        // unsat -> discharged (panic-safe). The bare unguarded pre `is_some(opt)`
        // over a free `opt` is NOT valid -> negation sat -> undecidable (the
        // refuse-floor negative control). With the predicate declared, z3 RUNS
        // (no `unknown constant` error) and discriminates the two correctly.
        let Some(z3) = which_z3() else {
            eprintln!("z3 not found; skipping panic-freedom end-to-end check");
            return;
        };

        let guarded = fixture_compile_to_parts(&implies(
            atomic("is_some", vec![var("opt")]),
            atomic("is_some", vec![var("opt")]),
        ))
        .expect("compile guarded");
        let g_out = run_z3(&z3, &format!("{}{}", guarded.preamble, guarded.body));
        assert!(
            g_out.contains("unsat"),
            "guarded `(=> is_some(opt) is_some(opt))` must be unsat (discharged): {g_out}"
        );

        let bare =
            fixture_compile_to_parts(&atomic("is_some", vec![var("opt")])).expect("compile bare");
        let b_out = run_z3(&z3, &format!("{}{}", bare.preamble, bare.body));
        assert!(
            b_out.contains("sat") && !b_out.contains("unsat"),
            "bare unguarded `is_some(opt)` must be sat (NOT discharged): {b_out}"
        );
    }

    #[test]
    fn reflexive_equality_is_unsat_under_z3_and_distinct_is_sat() {
        // End-to-end soundness check via z3 IF available. `(= (Ok x) (Ok
        // x))` is valid -> its negation is unsat -> discharged by
        // congruence over an uninterpreted `Ok`. `(= (Ok x) (Err x))` is
        // NOT valid -> its negation is sat -> the encoding does NOT
        // launder a mismatched post. This is the soundness guard for the
        // encoder: reflexivity, not blanket-pass.
        let z3 = which_z3();
        let Some(z3) = z3 else {
            eprintln!("z3 not found; skipping end-to-end congruence check");
            return;
        };

        let reflexive =
            fixture_compile_to_parts(&eq(ctor("Ok", vec![var("x")]), ctor("Ok", vec![var("x")])))
                .expect("compile reflexive");
        let r_out = run_z3(&z3, &format!("{}{}", reflexive.preamble, reflexive.body));
        assert!(
            r_out.contains("unsat"),
            "reflexive `Ok(x) == Ok(x)` must be unsat (discharged): {r_out}"
        );

        let distinct =
            fixture_compile_to_parts(&eq(ctor("Ok", vec![var("x")]), ctor("Err", vec![var("x")])))
                .expect("compile distinct");
        let d_out = run_z3(&z3, &format!("{}{}", distinct.preamble, distinct.body));
        assert!(
            d_out.contains("sat") && !d_out.contains("unsat"),
            "distinct `Ok(x) == Err(x)` must be sat (NOT discharged): {d_out}"
        );
    }

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

    // ── String-literal encoding tests ─────────────────────────────────────
    // POSITIVE: `=(r,"{"a":1}")` is satisfiable (single consistent assertion).
    // RED before fix: z3 returns a parse error; test asserts no parse error + real verdict.
    // GREEN after fix: real sat/unsat, no `(error ...` output.

    fn string_const(s: &str) -> serde_json::Value {
        serde_json::json!({"kind":"const","value":s,"sort":{"kind":"primitive","name":"String"}})
    }

    #[test]
    fn string_literal_equality_single_no_parse_error() {
        // POSITIVE: `assert r == '{"a":1}'` — a single string-equality assertion.
        // Must compile without error and produce a real sat/unsat, not a parse error.
        let z3 = which_z3().expect("z3 must be present for string-literal soundness check");
        let inv = eq(var("r"), string_const(r#"{"a":1}"#));
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile must succeed");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert!(
            !out.contains("(error"),
            "string-literal equality must produce no z3 parse error; got: {out}\nscript:\n{script}"
        );
        assert!(
            out.contains("sat") || out.contains("unsat"),
            "string-literal equality must produce a real sat/unsat verdict; got: {out}"
        );
    }

    #[test]
    fn two_distinct_string_literals_same_var_is_unsat() {
        // DISCRIMINATION: `=(r,"a") ∧ =(r,"b")` with two distinct string literals.
        // A single var cannot equal two different string constants -> UNSAT.
        // RED before fix: parse error -> undecidable (false pass of consistency).
        // GREEN after fix: real unsat verdict.
        let z3 = which_z3().expect("z3 must be present for string-literal soundness check");
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                eq(var("r"), string_const("a")),
                eq(var("r"), string_const("b")),
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile must succeed");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert!(
            !out.contains("(error"),
            "two-literal contradiction must produce no parse error; got: {out}\nscript:\n{script}"
        );
        assert_eq!(
            out.trim(),
            "unsat",
            "=(r,'a') ∧ =(r,'b') with distinct literals must be UNSAT (refused); \
             z3 said: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn string_literal_with_brace_backslash_unicode_no_parse_error() {
        // Weird-char cases: brace, backslash, control char (\x01), unicode (≥).
        // All must compile without parse error and give a real verdict.
        let z3 = which_z3().expect("z3 must be present for string-literal soundness check");
        let weird_cases = vec![
            r#"{"a":"x"}"#,    // braces
            r#"path\to\file"#, // backslashes
            "\x01",            // control char
            "≥ ≤ ≠",           // unicode operators
        ];
        for s in weird_cases {
            let inv = eq(var("r"), string_const(s));
            let parts = fixture_compile_asserted_to_parts(&inv).expect("compile must succeed");
            let script = format!("{}{}", parts.preamble, parts.body);
            let out = run_z3(&z3, &script);
            assert!(
                !out.contains("(error"),
                "weird-char literal {:?} must produce no z3 parse error; got: {out}\nscript:\n{script}",
                s
            );
            assert!(
                out.contains("sat") || out.contains("unsat"),
                "weird-char literal {:?} must produce real sat/unsat; got: {out}",
                s
            );
        }
    }

    fn string_theory_atom(name: &str, args: Vec<serde_json::Value>) -> serde_json::Value {
        serde_json::json!({"kind": "atomic", "name": name, "args": args})
    }

    fn str_len(s: &str) -> serde_json::Value {
        serde_json::json!({"kind": "ctor", "name": "str.len", "args": [string_const(s)]})
    }

    #[test]
    fn string_contains_prefix_suffix_route_to_z3_string_theory() {
        let z3 = which_z3().expect("z3 required for string theory check");
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                string_theory_atom("contains", vec![string_const("abcde"), string_const("bcd")]),
                string_theory_atom("prefix-of", vec![string_const("ab"), string_const("abcde")]),
                string_theory_atom("suffix-of", vec![string_const("de"), string_const("abcde")]),
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            script.contains(r#"(str.contains "abcde" "bcd")"#),
            "contains must lower to z3 string theory, got:\n{script}"
        );
        assert!(
            script.contains(r#"(str.prefixof "ab" "abcde")"#),
            "prefix-of must lower to z3 string theory, got:\n{script}"
        );
        assert!(
            script.contains(r#"(str.suffixof "de" "abcde")"#),
            "suffix-of must lower to z3 string theory, got:\n{script}"
        );
        assert!(
            !script.contains("strlit_"),
            "string-theory atoms must not use opaque equality literals:\n{script}"
        );
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "sat",
            "true string predicates must be SAT: {out}"
        );
    }

    #[test]
    fn string_theory_bad_twin_is_unsat() {
        let z3 = which_z3().expect("z3 required for string theory check");
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                string_theory_atom("contains", vec![string_const("abcde"), string_const("bcd")]),
                {"kind": "not", "operands": [
                    string_theory_atom("contains", vec![string_const("abcde"), string_const("bcd")])
                ]},
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "contradictory string predicate twin must be UNSAT, got: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn string_len_and_ascii_class_predicates_route_to_z3_string_theory() {
        let z3 = which_z3().expect("z3 required for string theory check");
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                // Five U+FF5E fullwidth tildes. Python len() == 5 (CODE
                // POINTS). Before the smt_string_char fix these emitted as raw
                // multibyte UTF-8 and z3 counted 15 (bytes) -- a real
                // divergence from Python semantics; now \u{ff5e}-escaped, z3
                // counts 5 code points, matching len().
                eq(str_len("～～～～～"), int_const(5)),
                string_theory_atom("str.is_ascii", vec![string_const("banana\0\u{7f}")]),
                string_theory_atom("str.is_ascii_alphabetic", vec![string_const("A")]),
                string_theory_atom("str.is_ascii_alphanumeric", vec![string_const("A")]),
                string_theory_atom("str.is_ascii_digit", vec![string_const("9")]),
                string_theory_atom("str.is_ascii_octdigit", vec![string_const("7")]),
                string_theory_atom("str.is_ascii_lowercase", vec![string_const("z")]),
                string_theory_atom("str.is_ascii_uppercase", vec![string_const("Z")]),
                string_theory_atom("str.is_ascii_hexdigit", vec![string_const("f")]),
                string_theory_atom("str.is_ascii_punctuation", vec![string_const("!")]),
                string_theory_atom("str.is_ascii_graphic", vec![string_const("~")]),
                string_theory_atom("str.is_ascii_whitespace", vec![string_const(" ")]),
                string_theory_atom("str.is_ascii_control", vec![string_const("\u{7f}")]),
                {"kind": "not", "operands": [
                    string_theory_atom("str.is_ascii_alphabetic", vec![string_const("0")])
                ]},
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            script.contains("(str.len \"\\u{ff5e}\\u{ff5e}\\u{ff5e}\\u{ff5e}\\u{ff5e}\")"),
            "str.len subject must \\u-escape non-ASCII (code-point semantics), got:\n{script}"
        );
        assert!(
            script.contains("str.in_re"),
            "ascii predicates must lower to z3 regex string checks, got:\n{script}"
        );
        assert!(
            script.contains("(re.range \"0\" \"9\")"),
            "digit regex missing: {script}"
        );
        assert!(
            script.contains("(re.range \"0\" \"7\")"),
            "octdigit regex missing: {script}"
        );
        assert!(
            script.contains("(re.range \"a\" \"z\")"),
            "lowercase regex missing: {script}"
        );
        assert!(
            script.contains("(re.range \"A\" \"Z\")"),
            "uppercase regex missing: {script}"
        );
        assert!(
            script.contains("(re.range \"!\" \"/\")"),
            "punctuation regex missing: {script}"
        );
        assert!(
            script.contains("(re.range \"!\" \"~\")"),
            "graphic regex missing: {script}"
        );
        assert!(
            script.contains("(re.range \"\\u{0}\" \"\\u{1f}\")"),
            "control regex missing: {script}"
        );
        assert!(
            script.contains("(re.union"),
            "union-based ascii class regex missing: {script}"
        );
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "sat",
            "true len/ascii predicate set must be SAT, got: {out}\nscript:\n{script}"
        );
    }

    // ── G1: str.chars-in-set (universe membership over a walked charset) ──
    // The Java kit's universe pass emits `str.chars-in-set(subject, set)`
    // where `set` is the encode table walked from the vendor's static-final
    // AST. Lowering: (str.in_re subject (re.* (re.union (str.to_re "c") ...))).

    /// The G1 conjoin subject: a `callresult_*` ctor with a string-literal
    /// arg, exactly the shape the Java kit's `buildUniverseContract` /
    /// `buildStringContract` emit over the same `#euf#` contract name.
    fn callresult(name: &str, str_arg: &str) -> serde_json::Value {
        ctor(name, vec![string_const(str_arg)])
    }

    #[test]
    fn werkzeug_subscript_member_plus_string_eq_no_crosssort() {
        // REGRESSION (Werkzeug test_double_slash_path, the Int/String cross-sort
        // tail): `"x" not in r.json["A"]` (member, opaque-Int) conjoined with
        // `r.json["B"] == "y"` (string const). The subscript ctor was String-
        // routed in the equality but Int in the membership -> one `subscript`
        // function declared with two return sorts -> z3 "Sorts Int and String
        // incompatible" -> undecidable. With the string-contagion fix the
        // subscript is UNTAINTED (no string predicate over it) so the equality
        // stays opaque-Int, all consistent, z3 returns sat.
        let z3 = which_z3().expect("z3");
        let sub = |key: &str| {
            serde_json::json!({"kind":"ctor","name":"subscript","args":[
            {"kind":"ctor","name":"python:attribute","args":[{"kind":"var","name":"r"},{"kind":"const","value":"json","sort":{"kind":"primitive","name":"String"}}]},
            {"kind":"const","value":key,"sort":{"kind":"primitive","name":"String"}}]})
        };
        let inv = serde_json::json!({"kind":"and","operands":[
            {"kind":"not","operands":[{"kind":"atomic","name":"member","args":[
                {"kind":"const","value":"double-slash","sort":{"kind":"primitive","name":"String"}}, sub("HTTP_HOST")]}]},
            {"kind":"atomic","name":"=","args":[sub("PATH_INFO"), {"kind":"const","value":"/double-slash","sort":{"kind":"primitive","name":"String"}}]}]});
        let parts = fixture_compile_asserted_to_parts(&inv).expect("must compile, no mixed-sort");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            !script.contains("String)"),
            "subscript must NOT be declared String-returning:\n{script}"
        );
        assert_eq!(
            run_z3(&z3, &script).trim(),
            "sat",
            "the werkzeug shape is consistent, not a sort-error undecidable:\n{script}"
        );
    }

    #[test]
    fn nonascii_string_equality_is_well_formed_and_consistent() {
        // REGRESSION (Werkzeug corpus mint): a sworn equality over a string
        // with C1 control chars / non-ASCII (UTF-8 header value, IRI, cookie)
        // must emit a WELL-FORMED SMT-LIB literal -- every non-printable-ASCII
        // code point as \u{...}, never raw -- so z3 returns sat (consistent),
        // not a parse/sort error miscategorized as a false violation.
        let z3 = which_z3().expect("z3 required");
        // "â\u{9c}\u{93}" -- the UTF-8 bytes of U+2713 stored as a 3-char str,
        // exactly werkzeug test_return_type_is_str's "\xe2\x9c\x93".
        let subj = callresult("c:callresult_header_a1", "x");
        // A universe (chars-not-in-set) over the subject string-TAINTS it, so
        // the sworn equality routes to string theory -- the case where escaping
        // matters (a bare equality with no universe now stays opaque-Int since
        // the string-contagion fix, where the non-ASCII content is an opaque
        // strlit_ token and escaping is moot).
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                string_theory_atom("str.chars-not-in-set", vec![subj.clone(), string_const("+")]),
                eq(subj, string_const("\u{e2}\u{9c}\u{93}")),
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            script.contains("\\u{9c}") && script.contains("\\u{93}") && script.contains("\\u{e2}"),
            "C1/non-ASCII chars must be \\u{{}}-escaped, not raw:\n{script}"
        );
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "sat",
            "a lone non-ASCII equality is consistent, not an error/violation: {out}\n{script}"
        );
    }

    #[test]
    fn chars_in_set_with_in_set_literal_is_sat() {
        // POSITIVE: universe row + the vendor's sworn equality over the SAME
        // callresult subject is consistent. "Zm9v" over a base64-table-shaped
        // set — the GOOD-suite conjoin.
        let z3 = which_z3().expect("z3 required for chars-in-set check");
        let call = callresult("c:callresult_encodeBase64String_a1", "foo");
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                string_theory_atom(
                    "str.chars-in-set",
                    vec![call.clone(), string_const("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")],
                ),
                eq(call, string_const("Zm9v")),
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            script.contains("(re.* (re.union (str.to_re \"+\")"),
            "chars-in-set must lower to re.* over str.to_re union (sorted+deduped):\n{script}"
        );
        assert!(
            script.contains("(Int) String)"),
            "the callresult subject must be declared with String return sort:\n{script}"
        );
        assert!(
            script.contains("\"Zm9v\""),
            "the string-routed equality must render a real String literal:\n{script}"
        );
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "sat",
            "universe row + in-set sworn literal must be SAT, got: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn chars_in_set_with_out_of_set_char_is_unsat() {
        // DISCRIMINATION: the BAD-twin shape. Universe = the URL_SAFE table
        // (no '+', no '/'); the consumer's claimed equality over the same
        // callresult contains '+' and '/'. The conjunction must be UNSAT —
        // z3 string theory refutes an input the vendor never tested.
        let z3 = which_z3().expect("z3 required for chars-in-set check");
        let call = callresult("c:callresult_encodeBase64URLSafeString_a1", "bar");
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                string_theory_atom(
                    "str.chars-in-set",
                    vec![call.clone(), string_const("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")],
                ),
                eq(call, string_const("YmFy+/x=")),
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "universe row + out-of-set literal must be UNSAT, got: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn string_routed_equality_does_not_capture_legacy_var_regime() {
        // GUARD: the legacy Python opaque-Int regime is byte-identical. A
        // free-VAR equality (`r == "a"`) must NOT route to string theory —
        // cross-type consistency (`r == "a" ∧ r == 1` UNSAT via distinctness)
        // depends on it. Same for `None == "x"`.
        let var_eq =
            fixture_compile_asserted_to_parts(&eq(var("r"), string_const("a"))).expect("compile");
        let script = format!("{}{}", var_eq.preamble, var_eq.body);
        assert!(
            script.contains("strlit_") && script.contains("(declare-const r Int)"),
            "var equality must stay in the opaque-Int regime:\n{script}"
        );
        let none_eq = fixture_compile_asserted_to_parts(&eq(
            serde_json::json!({"kind":"ctor","name":"None","args":[]}),
            string_const("x"),
        ))
        .expect("compile");
        let script = format!("{}{}", none_eq.preamble, none_eq.body);
        assert!(
            script.contains("strlit_"),
            "None equality must stay in the opaque-Int regime:\n{script}"
        );
    }

    #[test]
    fn chars_in_set_round_trips_through_emit_asserted() {
        // STRUCTURAL: the predicate survives the asserted path end-to-end —
        // no opaque strlit_ laundering of the set, no undeclared-predicate
        // fallback, and the empty string is in the Kleene-star universe (SAT
        // alone). Quote char in the set must be escaped SMT-style ("" not \").
        let inv = string_theory_atom("str.chars-in-set", vec![var("r"), string_const("a\"b")]);
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            script.contains("(str.in_re r (re.* (re.union (str.to_re \"\"\"\") (re.union (str.to_re \"a\") (str.to_re \"b\")))))"),
            "round-trip rendering wrong:\n{script}"
        );
        assert!(
            !script.contains("strlit_"),
            "the set must lower to string theory, not opaque literals:\n{script}"
        );
        assert!(
            !script.contains("(declare-fun str.chars-in-set")
                && !script.contains("(declare-fun |str.chars-in-set|"),
            "chars-in-set must be a theory lowering, not an uninterpreted predicate:\n{script}"
        );
        if let Some(z3) = which_z3() {
            let out = run_z3(&z3, &script);
            assert_eq!(out.trim(), "sat", "lone universe row must be SAT: {out}");
        }
    }

    // ── Door 3: str.in-regex (@Pattern regular-language membership) ──────────
    // The Java kit's @Pattern universe pass emits `str.in-regex(subject, regex)`
    // where `regex` is the verbatim `@Pattern(regexp="…")` literal walked from the
    // annotation AST. Lowering: (str.in_re subject <regex-as-RegLan>), the regex
    // parsed + lowered by `crate::regex_regln` — the single lowering authority.

    #[test]
    fn in_regex_matching_claim_is_sat() {
        // POSITIVE (GOOD): a validity claim about an input the @Pattern ACCEPTS.
        // Pattern: ^[a-z]+@example\.com$ ; claim: getEmail("a@example.com") valid.
        let z3 = which_z3().expect("z3 required for str.in-regex check");
        let call = callresult("c:callresult_getEmail_a1", "a@example.com");
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                string_theory_atom(
                    "str.in-regex",
                    vec![call.clone(), string_const("^[a-z]+@example\\.com$")],
                ),
                eq(call, string_const("a@example.com")),
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            script.contains("str.in_re") && script.contains("(str.to_re \"@\")"),
            "str.in-regex must lower to native z3 str.in_re over a walked RegLan:\n{script}"
        );
        assert!(
            !script.contains("(declare-fun str.in-regex")
                && !script.contains("(declare-fun |str.in-regex|"),
            "str.in-regex must be a theory lowering, not an uninterpreted predicate:\n{script}"
        );
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "sat",
            "matching input's validity claim must be SAT, got: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn in_regex_nonmatching_claim_is_unsat() {
        // DISCRIMINATION (BAD): a NON-matching input claimed valid. The walked
        // regex refutes it by MEMBERSHIP — z3 string theory returns unsat. Not a
        // within-test contradiction; the regex alone does the refutation.
        // Pattern ^[a-z]+@example\.com$ rejects "ADMIN@evil.com".
        let z3 = which_z3().expect("z3 required for str.in-regex check");
        let call = callresult("c:callresult_getEmail_a1", "ADMIN@evil.com");
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                string_theory_atom(
                    "str.in-regex",
                    vec![call.clone(), string_const("^[a-z]+@example\\.com$")],
                ),
                eq(call, string_const("ADMIN@evil.com")),
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "non-matching input claimed valid must be UNSAT, got: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn in_regex_spotlight_accepts_more_than_intuited() {
        // THE SPOTLIGHT: the permissive-email dark. An author writes
        //   ^[\w.+-]+@[\w.-]+\.\w+$
        // believing it pins a benign address. The walked language ACCEPTS
        // "a+x@host.computer" (the '+' subaddress and the multi-label host the
        // author never intended). A claim that this string is valid is SAT —
        // proving, mechanically, the regex's language is wider than intuition.
        let z3 = which_z3().expect("z3 required for str.in-regex check");
        let call = callresult("c:callresult_getEmail_a1", "a+x@host.computer");
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                string_theory_atom(
                    "str.in-regex",
                    vec![call.clone(), string_const("^[\\w.+-]+@[\\w.-]+\\.\\w+$")],
                ),
                eq(call, string_const("a+x@host.computer")),
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "sat",
            "the permissive pattern ACCEPTS the unintended input (spotlight): {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn in_regex_nonregular_feature_refuses() {
        // REFUSE BY NAME (backstop): a non-regular regex (lookahead) must NOT
        // render an approximated language or become an uninterpreted predicate.
        let inv = string_theory_atom("str.in-regex", vec![var("r"), string_const("foo(?=bar)")]);
        let err =
            fixture_compile_asserted_to_parts(&inv).expect_err("non-regular regex must refuse");
        let msg = err.to_string();
        assert!(
            msg.contains("str.in-regex")
                && msg.contains("lookahead")
                && msg.contains("refusing rather than weakening"),
            "non-regular regex must refuse by name: {msg}"
        );
    }

    // ── G1b: str.chars-not-in-set (complement universe from a translate table) ──
    // The Python kit's translate walk emits `str.chars-not-in-set(subject, set)`
    // where `set` is the FROM side of a vendor bytes.maketrans literal: a total
    // translate maps every listed char away, so the output contains none of
    // them. Lowering: (and (not (str.contains subject "c")) ...).

    #[test]
    fn chars_not_in_set_with_clean_literal_is_sat() {
        // POSITIVE: the translate universe + a sworn equality whose literal
        // contains none of the forbidden chars — the GOOD-twin conjoin.
        let z3 = which_z3().expect("z3 required for chars-not-in-set check");
        let call = callresult("c:callresult_urlsafe_b64encode_a1", "bar");
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                string_theory_atom(
                    "str.chars-not-in-set",
                    vec![call.clone(), string_const("+/")],
                ),
                eq(call, string_const("YmFy-_x=")),
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "sat",
            "complement universe + clean sworn literal must be SAT, got: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn chars_not_in_set_with_forbidden_char_is_unsat() {
        // DISCRIMINATION: the python marquee shape. The walked maketrans
        // table swears urlsafe output never contains '+' or '/'; the consumer
        // asserts an output with '+'. UNSAT — refuted on an input the vendor
        // never tested, from two byte literals in the vendor's own source.
        let z3 = which_z3().expect("z3 required for chars-not-in-set check");
        let call = callresult("c:callresult_urlsafe_b64encode_a1", "bar");
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                string_theory_atom(
                    "str.chars-not-in-set",
                    vec![call.clone(), string_const("+/")],
                ),
                eq(call, string_const("YmFy+x=")),
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "complement universe + forbidden-char literal must be UNSAT, got: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn chars_not_in_set_with_python_bytes_forbidden_payload_is_unsat() {
        // DISCRIMINATION: Python bytes literals travel as hex in ProofIR. When
        // the URL-safe translate universe string-taints the call result, the
        // compiler must compare decoded byte content, not the hex transport
        // spelling. b"YmFy+x=" contains '+', so this is UNSAT.
        let z3 = which_z3().expect("z3 required for python:bytes charset check");
        let call = callresult("c:callresult_urlsafe_b64encode_a1", "bar");
        let python_bytes = ctor("python:bytes", vec![string_const("596d46792b783d")]);
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                string_theory_atom(
                    "str.chars-not-in-set",
                    vec![call.clone(), string_const("+/")],
                ),
                eq(call, python_bytes),
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "complement universe + decoded python:bytes literal must be UNSAT, got: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn chars_not_in_set_round_trips_through_emit_asserted() {
        // STRUCTURAL: conjunction of negated str.contains, sorted+deduped,
        // quote escaped, no opaque strlit_ laundering, no uninterpreted
        // predicate fallback; the lone row is SAT (empty string qualifies).
        let inv = string_theory_atom("str.chars-not-in-set", vec![var("r"), string_const("/+/")]);
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            script.contains("(and (not (str.contains r \"+\")) (not (str.contains r \"/\")))"),
            "round-trip rendering wrong (must sort+dedup to +,/):\n{script}"
        );
        assert!(
            !script.contains("strlit_"),
            "the set must lower to string theory, not opaque literals:\n{script}"
        );
        assert!(
            !script.contains("(declare-fun str.chars-not-in-set")
                && !script.contains("(declare-fun |str.chars-not-in-set|"),
            "chars-not-in-set must be a theory lowering, not an uninterpreted predicate:\n{script}"
        );
        let single = string_theory_atom("str.chars-not-in-set", vec![var("r"), string_const("+")]);
        let single_parts = fixture_compile_asserted_to_parts(&single).expect("compile");
        let single_script = format!("{}{}", single_parts.preamble, single_parts.body);
        assert!(
            single_script.contains("(not (str.contains r \"+\"))")
                && !single_script.contains("(and (not"),
            "single-char set must degenerate without the and:\n{single_script}"
        );
        if let Some(z3) = which_z3() {
            let out = run_z3(&z3, &script);
            assert_eq!(out.trim(), "sat", "lone complement row must be SAT: {out}");
        }
    }

    #[test]
    fn bytes_wrapped_equality_conjoins_with_complement_universe() {
        // CONTACT: the python kit lifts b"..." as python:bytes(<String const>).
        // The sworn bytes equality must meet the complement universe in string
        // theory -- a disconnected (opaque-Int) bytes row would be vacuously
        // SAT against any universe. Forbidden char present -> UNSAT; clean ->
        // SAT. This is the marquee's actual bytes path.
        let z3 = which_z3().expect("z3 required for bytes conjoin check");
        let call = callresult("c:callresult_urlsafe_b64encode_a1", "bar");
        let bad = serde_json::json!({
            "kind": "and",
            "operands": [
                string_theory_atom(
                    "str.chars-not-in-set",
                    vec![call.clone(), string_const("+/")],
                ),
                eq(call.clone(), ctor("python:bytes", vec![string_const("YmFy+x=")])),
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&bad).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            script.contains("\"YmFy+x=\""),
            "python:bytes must unwrap to a real String literal:\n{script}"
        );
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "bytes equality with forbidden char must refute against the universe, got: {out}\nscript:\n{script}"
        );
        let good = serde_json::json!({
            "kind": "and",
            "operands": [
                string_theory_atom(
                    "str.chars-not-in-set",
                    vec![call.clone(), string_const("+/")],
                ),
                eq(call, ctor("python:bytes", vec![string_const("YmFy-x=")])),
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&good).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "sat",
            "clean bytes equality must be consistent with the universe, got: {out}\nscript:\n{script}"
        );
    }

    // ── Cross-type literal distinctness (Python `==` semantics) ───────────
    // Helpers for int / bool / None literal terms.
    fn int_const(n: i64) -> serde_json::Value {
        serde_json::json!({"kind":"const","value":n,"sort":{"kind":"primitive","name":"Int"}})
    }
    fn bool_const(b: bool) -> serde_json::Value {
        serde_json::json!({"kind":"const","value":b,"sort":{"kind":"primitive","name":"Bool"}})
    }
    fn none_ctor() -> serde_json::Value {
        serde_json::json!({"kind":"ctor","name":"None","args":[]})
    }
    fn and2(a: serde_json::Value, b: serde_json::Value) -> serde_json::Value {
        serde_json::json!({"kind":"and","operands":[a,b]})
    }
    fn not_formula(a: serde_json::Value) -> serde_json::Value {
        serde_json::json!({"kind":"not","operands":[a]})
    }

    #[test]
    fn identity_relation_has_sat_unsat_teeth_under_z3() {
        // `identity` is the language-neutral object-identity relation. Kits
        // like Python lower `is` to this predicate; the shared compiler lowers
        // it to equality over identity-denotation terms, so z3 remains the
        // authority instead of the lifter.
        let z3 = which_z3().expect("z3 required for identity relation check");

        let good = and2(
            atomic("identity", vec![var("r"), none_ctor()]),
            atomic("identity", vec![var("r"), none_ctor()]),
        );
        let parts = fixture_compile_asserted_to_parts(&good).expect("compile good identity");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            !script.contains("(declare-fun identity"),
            "identity is a compiler relation, not an uninterpreted predicate:\n{script}"
        );
        assert!(
            script.contains("(declare-sort SugarIdentity 0)")
                && script.contains("(declare-const |identity:var:r| SugarIdentity)")
                && !script.contains("(declare-const r Int)"),
            "identity facts must ride their own SugarIdentity sort:\n{script}"
        );
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "sat",
            "same identity facts must be SAT, got: {out}\nscript:\n{script}"
        );

        let bad = and2(
            atomic("identity", vec![var("r"), none_ctor()]),
            atomic("identity", vec![var("r"), bool_const(true)]),
        );
        let parts = fixture_compile_asserted_to_parts(&bad).expect("compile bad identity");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert!(
            !script.contains("(declare-fun identity"),
            "identity is a compiler relation, not an uninterpreted predicate:\n{script}"
        );
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "identity(r,None) ∧ identity(r,True) must be UNSAT, got: {out}\nscript:\n{script}"
        );

        let bool_vs_int_identity = and2(
            atomic("identity", vec![var("r"), bool_const(true)]),
            atomic("identity", vec![var("r"), int_const(1)]),
        );
        let parts = fixture_compile_asserted_to_parts(&bool_vs_int_identity)
            .expect("compile bool/int identity");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "identity(r,True) ∧ identity(r,1) must be UNSAT even though True == 1 is SAT; got: {out}\nscript:\n{script}"
        );

        let negated_good = and2(
            atomic("identity", vec![var("r"), bool_const(true)]),
            not_formula(atomic("identity", vec![var("r"), none_ctor()])),
        );
        let parts =
            fixture_compile_asserted_to_parts(&negated_good).expect("compile negated identity");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "sat",
            "identity(r,True) ∧ not(identity(r,None)) must be SAT, got: {out}\nscript:\n{script}"
        );

        let negated_bad = and2(
            atomic("identity", vec![var("r"), none_ctor()]),
            not_formula(atomic("identity", vec![var("r"), none_ctor()])),
        );
        let parts =
            fixture_compile_asserted_to_parts(&negated_bad).expect("compile negated contradiction");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "identity(r,None) ∧ not(identity(r,None)) must be UNSAT, got: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn str_literal_distinct_from_int_literal_is_unsat() {
        // Python: `"5" != 5`. `r == "5" ∧ r == 5` is contradictory -> UNSAT.
        // RED before fix: both collapse into Int universe with no distinctness
        // axiom -> z3 picks strlit == 5 -> SAT (false consistent).
        let z3 = which_z3().expect("z3 required");
        let inv = and2(eq(var("r"), string_const("5")), eq(var("r"), int_const(5)));
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "`r==\"5\" ∧ r==5` must be UNSAT (Python str≠int); got: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn none_distinct_from_int_literal_is_unsat() {
        // Python: `None != 5`. `r is None ∧ r == 5` is contradictory -> UNSAT.
        let z3 = which_z3().expect("z3 required");
        let inv = and2(eq(var("r"), none_ctor()), eq(var("r"), int_const(5)));
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "`r is None ∧ r==5` must be UNSAT (Python None≠int); got: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn none_distinct_from_str_literal_is_unsat() {
        // Python: `None != "x"`. `r is None ∧ r == "x"` is contradictory -> UNSAT.
        let z3 = which_z3().expect("z3 required");
        let inv = and2(eq(var("r"), none_ctor()), eq(var("r"), string_const("x")));
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "`r is None ∧ r==\"x\"` must be UNSAT (Python None≠str); got: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn none_distinct_from_bool_false_is_unsat() {
        // Python: `None != False` (and False==0). `r is None ∧ r == False`
        // is contradictory -> UNSAT. This is the discriminating test for the
        // "bool must join the concrete-int distinctness target set" wiring:
        // False encodes as 0, and None must be distinct from 0.
        let z3 = which_z3().expect("z3 required");
        let inv = and2(eq(var("r"), none_ctor()), eq(var("r"), bool_const(false)));
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "`r is None ∧ r==False` must be UNSAT (Python None≠False); got: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn bool_true_consistent_with_int_one_is_sat() {
        // Python: `True == 1`. `r == True ∧ r == 1` is CONSISTENT -> SAT.
        // This is the OVER-DISTINCTNESS GUARD: bool literals must encode to
        // their int values (True->1) and must NOT be asserted distinct from
        // int. A false-refusal here would mean over-distinctness. Permanent.
        let z3 = which_z3().expect("z3 required");
        let inv = and2(eq(var("r"), bool_const(true)), eq(var("r"), int_const(1)));
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert!(
            !out.contains("(error"),
            "`r==True ∧ r==1` must not parse-error; got: {out}\nscript:\n{script}"
        );
        assert_eq!(
            out.trim(),
            "sat",
            "`r==True ∧ r==1` must be SAT (Python True==1); got: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn bool_false_consistent_with_int_zero_is_sat() {
        // Python: `False == 0`. `r == False ∧ r == 0` is CONSISTENT -> SAT.
        let z3 = which_z3().expect("z3 required");
        let inv = and2(eq(var("r"), bool_const(false)), eq(var("r"), int_const(0)));
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "sat",
            "`r==False ∧ r==0` must be SAT (Python False==0); got: {out}\nscript:\n{script}"
        );
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

    #[test]
    fn functionsort_quantifier_emits_opacity_entry() {
        // forall (f: Function) . true: FunctionSort in quantifier.
        // After fix: the quantifier is emitted soundly over a CID-derived
        // uninterpreted sort instead of collapsing to `true`.
        let ir = serde_json::json!({
            "kind": "forall",
            "name": "f",
            "sort": { "kind": "function", "args": [], "return": { "kind": "primitive", "name": "Bool" } },
            "body": { "kind": "atomic", "name": "true", "args": [] }
        });
        let result = fixture_compile_to_parts(&ir).expect("compile succeeds");
        assert_eq!(result.opacity_manifest.opacities.len(), 1);
        assert_eq!(
            result.opacity_manifest.opacities[0].reason_code,
            "predicate_quantification"
        );
        // Sound encoding: the body now contains a real quantifier, not `true`.
        assert!(
            result.body.contains("(assert (not (forall ((f S_"),
            "must emit sound quantifier, got: {}",
            result.body
        );
        assert!(
            !result.body.contains("(assert (not true))"),
            "must not collapse quantifier to true: {}",
            result.body
        );
        // The opaque sort is declared in the preamble, not emitted raw.
        assert!(
            result.preamble.contains("(declare-sort S_"),
            "opaque sort must be declared in preamble: {}",
            result.preamble
        );
    }

    #[test]
    fn dependent_sort_quantifier_emits_opacity_entry() {
        // exists (n: Dependent) . true: DependentSort in quantifier.
        // After fix: emitted soundly over a CID-derived uninterpreted sort.
        let ir = serde_json::json!({
            "kind": "exists",
            "name": "n",
            "sort": { "kind": "dependent", "name": "Vec<n>", "indexVar": "n", "indexSort": { "kind": "primitive", "name": "Int" } },
            "body": { "kind": "atomic", "name": "true", "args": [] }
        });
        let result = fixture_compile_to_parts(&ir).expect("compile succeeds");
        assert_eq!(result.opacity_manifest.opacities.len(), 1);
        assert_eq!(
            result.opacity_manifest.opacities[0].reason_code,
            "dependent_type"
        );
        // Sound encoding: real quantifier, not collapsed to `true`.
        assert!(
            result.body.contains("(assert (not (exists ((n S_"),
            "must emit sound existential quantifier, got: {}",
            result.body
        );
        assert!(
            !result.body.contains("(assert (not true))"),
            "must not collapse quantifier to true: {}",
            result.body
        );
    }

    #[test]
    fn primitive_sort_quantifier_no_opacity() {
        // forall (x: Int) . x >= 0: Int is supported
        let ir = serde_json::json!({
            "kind": "forall",
            "name": "x",
            "sort": { "kind": "primitive", "name": "Int" },
            "body": { "kind": "atomic", "name": ">=", "args": [
                { "kind": "var", "name": "x" },
                { "kind": "const", "value": 0, "sort": { "kind": "primitive", "name": "Int" } }
            ]}
        });
        let result = fixture_compile_to_parts(&ir).expect("compile succeeds");
        assert!(result.opacity_manifest.opacities.is_empty());
        assert!(result.body.contains("(forall ((x Int))"));
    }

    #[test]
    fn opaque_primitive_sort_quantifier_emits_opacity_entry() {
        // Rust source sorts such as `Ref<Connection>` are valid IR
        // primitive-sort labels for identity, but not SMT-LIB builtin sorts.
        // The SMT backend must not emit them raw.
        // After fix: emitted soundly over a CID-derived uninterpreted sort.
        let ir = serde_json::json!({
            "kind": "forall",
            "name": "conn",
            "sort": { "kind": "primitive", "name": "Ref<Connection>" },
            "body": { "kind": "atomic", "name": "true", "args": [] }
        });
        let result = fixture_compile_to_parts(&ir).expect("compile succeeds");
        assert_eq!(result.opacity_manifest.opacities.len(), 1);
        assert_eq!(
            result.opacity_manifest.opacities[0].reason_code,
            "opaque_primitive_sort:Ref<Connection>"
        );
        assert!(
            !result.body.contains("Ref<Connection>"),
            "opaque Rust source sort must not be emitted as raw SMT-LIB: {}",
            result.body
        );
        // Sound encoding: real quantifier over CID-derived sort, not `true`.
        assert!(
            result.body.contains("(assert (not (forall ((conn S_"),
            "must emit sound quantifier, got: {}",
            result.body
        );
        assert!(
            !result.body.contains("(assert (not true))"),
            "must not collapse quantifier to true: {}",
            result.body
        );
        // The opaque sort is declared in the preamble via (declare-sort S_... 0).
        assert!(
            result.preamble.contains("(declare-sort S_"),
            "opaque sort must be declared in preamble: {}",
            result.preamble
        );
    }

    #[test]
    fn opacity_manifest_has_correct_envelope() {
        let ir = serde_json::json!({
            "kind": "forall",
            "name": "f",
            "sort": { "kind": "function", "args": [], "return": { "kind": "primitive", "name": "Bool" } },
            "body": { "kind": "atomic", "name": "true", "args": [] }
        });
        let result = fixture_compile_to_parts(&ir).expect("compile succeeds");
        let manifest = &result.opacity_manifest;
        assert_eq!(manifest.protocol_version, "ir-compiler-protocol/2");
        assert_eq!(manifest.compiler, "smt-lib-v2.6");
        assert!(!manifest.compiler_version.is_empty());
    }

    #[test]
    fn opacity_entries_sorted_by_position_cid() {
        // Two quantifiers over opaque sorts: entries should be sorted.
        let ir = serde_json::json!({
            "kind": "and",
            "operands": [
                { "kind": "forall", "name": "f",
                  "sort": { "kind": "function", "args": [], "return": { "kind": "primitive", "name": "Bool" } },
                  "body": { "kind": "atomic", "name": "true", "args": [] } },
                { "kind": "exists", "name": "n",
                  "sort": { "kind": "dependent", "name": "Vec<n>", "indexVar": "n", "indexSort": { "kind": "primitive", "name": "Int" } },
                  "body": { "kind": "atomic", "name": "true", "args": [] } }
            ]
        });
        let result = fixture_compile_to_parts(&ir).expect("compile succeeds");
        assert_eq!(result.opacity_manifest.opacities.len(), 2);
        let cids: Vec<&str> = result
            .opacity_manifest
            .opacities
            .iter()
            .map(|e| e.position_cid.as_str())
            .collect();
        assert!(
            cids[0] <= cids[1],
            "opacities must be sorted by positionCid"
        );
    }

    // ACCEPTANCE DETECTOR (issue #1717 soundness fix):
    //
    // Positive:       forall x:opaque. true  -> DISCHARGED (negation is unsat)
    // Discrimination: forall x:opaque. false -> NOT DISCHARGED (negation is sat)
    //
    // Before the fix both collapsed to `true`, making the negation
    // `(assert (not true))` which z3 returns `unsat` for -- a false pass.
    // After the fix the negated `false` case emits:
    //   `(assert (not (forall ((x S_...)) false)))` == `(assert (exists ((x S_...)) true))`
    // Over a nonempty uninterpreted sort, z3 returns `sat` -> not discharged.
    // The `true` body case emits:
    //   `(assert (not (forall ((x S_...)) true)))` == `(assert (exists ((x S_...)) false))`
    // which z3 returns `unsat` -> discharged. Both are correct.
    //
    // This test HARD-FAILS if z3 is not present (no skip): a skipped solver
    // test is a false green (per product invariant falsePass=0).

    #[test]
    fn opaque_sort_forall_true_is_discharged_under_z3() {
        // POSITIVE case: `forall x:opaque. true` must be discharged (negation unsat).
        let z3 = which_z3().expect(
            "z3 must be available for opaque-sort soundness check; \
             install z3 and re-run (a missing z3 is a false green)",
        );
        let ir = serde_json::json!({
            "kind": "forall",
            "name": "x",
            "sort": { "kind": "primitive", "name": "OpaqueT" },
            "body": { "kind": "atomic", "name": "true", "args": [] }
        });
        let result = fixture_compile_to_parts(&ir).expect("compile succeeds");
        // Sanity: check the sound quantifier is present in the body.
        assert!(
            result.body.contains("(forall ((x S_"),
            "must emit real quantifier over opaque sort, got: {}",
            result.body
        );
        let script = format!("{}{}", result.preamble, result.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "forall x:opaque. true must be discharged (negation unsat); z3 said: {}",
            out
        );
    }

    #[test]
    fn opaque_sort_forall_false_is_not_discharged_under_z3() {
        // DISCRIMINATION case: `forall x:opaque. false` must NOT be discharged
        // (negation sat). Before fix this falsely returned `unsat` (false pass).
        let z3 = which_z3().expect(
            "z3 must be available for opaque-sort soundness check; \
             install z3 and re-run (a missing z3 is a false green)",
        );
        let ir = serde_json::json!({
            "kind": "forall",
            "name": "x",
            "sort": { "kind": "primitive", "name": "OpaqueT" },
            "body": { "kind": "atomic", "name": "false", "args": [] }
        });
        let result = fixture_compile_to_parts(&ir).expect("compile succeeds");
        // Sanity: the body must contain the real quantifier, not collapsed true.
        assert!(
            result.body.contains("(forall ((x S_"),
            "must emit real quantifier over opaque sort, got: {}",
            result.body
        );
        assert!(
            !result.body.contains("(assert (not true))"),
            "quantifier must not have been collapsed to true: {}",
            result.body
        );
        let script = format!("{}{}", result.preamble, result.body);
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "sat",
            "forall x:opaque. false must NOT be discharged (negation must be sat); \
             z3 said: {} -- this is the false-pass soundness hole from issue #1717",
            out
        );
    }

    // ── G2: int32.eq-bv-expr (numeric universe walked from JDK Math.abs body) ──
    //
    // The walked body is `(a < 0) ? -a : a` → bv32.ite(bv32.slt(a,0), bv32.neg(a), a).
    // Under two's complement: bvneg(#x80000000) == #x80000000 == -2147483648.
    // Therefore: abs(MIN_VALUE) == MIN_VALUE (the industry-confounding truth).
    //
    // Test 1 (GOOD): abs(MIN_VALUE)==MIN_VALUE + walked universe → SAT (discharged).
    // Test 2 (BAD):  abs(MIN_VALUE)==MAX_VALUE + walked universe → UNSAT (refuted).
    // Test 3: no bv32 ctors declared as uninterpreted functions (no shadow).
    // Test 4: no free vars leak from bv32 atom (var "a" is not declared (declare-const a)).
    // Test 5: legacy Int regime unchanged (equality over a plain int callresult stays Int).

    /// Build the BV tree term for `(a < 0) ? -a : a`
    /// (bv32.ite(bv32.slt(a, 0), bv32.neg(a), a))
    fn abs_bv_tree() -> serde_json::Value {
        serde_json::json!({
            "kind": "ctor",
            "name": "bv32.ite",
            "args": [
                {
                    "kind": "ctor",
                    "name": "bv32.slt",
                    "args": [
                        {"kind": "var", "name": "a"},
                        {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                    ]
                },
                {
                    "kind": "ctor",
                    "name": "bv32.neg",
                    "args": [{"kind": "var", "name": "a"}]
                },
                {"kind": "var", "name": "a"}
            ]
        })
    }

    /// Build an int32.eq-bv-expr atom for abs(arg_val).
    fn abs_bv_atom(arg_val: i64) -> serde_json::Value {
        serde_json::json!({
            "kind": "atomic",
            "name": "int32.eq-bv-expr",
            "args": [
                {
                    "kind": "ctor",
                    "name": "call:abs",
                    "args": [
                        {"kind": "const", "value": arg_val, "sort": {"kind": "primitive", "name": "Int"}}
                    ]
                },
                abs_bv_tree()
            ]
        })
    }

    /// Build a sworn equality: `=(call:abs(arg_val), expected)` (both Int).
    fn abs_eq_atom(arg_val: i64, expected: i64) -> serde_json::Value {
        serde_json::json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                {
                    "kind": "ctor",
                    "name": "call:abs",
                    "args": [
                        {"kind": "const", "value": arg_val, "sort": {"kind": "primitive", "name": "Int"}}
                    ]
                },
                {"kind": "const", "value": expected, "sort": {"kind": "primitive", "name": "Int"}}
            ]
        })
    }

    #[test]
    fn abs_universe_truth_at_min_value_is_sat() {
        // GOOD: the BV universe row for abs(MIN_VALUE), compiled standalone,
        // is the REAL marquee conjunction the kit emits per #euf# name:
        //   =(call:abs(MIN), MIN)  ∧  int32.eq-bv-expr(call:abs(MIN), ite(...))
        // The sworn equality carries an Int const; the bv32-contagion pre-pass
        // promotes it to bv32 because call:abs also appears in the universe atom.
        // Under two's complement bvneg(#x80000000) == #x80000000, so both hold:
        // SAT → discharged. Nobody believes abs(MIN)==MIN. Sugar proves it.
        let z3 = which_z3().expect("z3 required for BV32 check");
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                abs_eq_atom(-2147483648, -2147483648),
                abs_bv_atom(-2147483648)
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        // The sworn equality must have been promoted to bv32 (BV hex literal,
        // NOT a bare Int numeral -2147483648). Contagion proof.
        assert!(
            script.contains("#x80000000"),
            "MIN_VALUE must be encoded as BV hex #x80000000 (contagion promoted the equality):\n{script}"
        );
        assert!(
            !script.contains("(- 2147483648)") && !script.contains(" -2147483648"),
            "the sworn Int const must NOT leak as a bare Int numeral — it must be bv32:\n{script}"
        );
        // call:abs declared ONCE, as a BV32 function (no Int) Int duplicate.
        assert!(
            script.contains("(declare-fun |call:abs| ((_ BitVec 32)) (_ BitVec 32))"),
            "call:abs must be declared once as a BV32 function:\n{script}"
        );
        assert!(
            !script.contains("(declare-fun |call:abs| (Int) Int)"),
            "call:abs must NOT also be declared as an Int function (mixed-sort):\n{script}"
        );
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "sat",
            "=(abs(MIN),MIN) ∧ universe must be SAT (two's complement truth, contagion routed);\
             \ngot: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn abs_universe_false_belief_at_min_value_is_unsat() {
        // BAD: the industry belief. The kit's conjunction per #euf# name:
        //   =(call:abs(MIN), MAX)  ∧  int32.eq-bv-expr(call:abs(MIN), ite(...))
        // The sworn equality (Int const MAX=2147483647) is promoted to bv32 by
        // contagion → (= |call:abs| #x7fffffff). The universe atom forces
        // |call:abs| = ite(...) = #x80000000. #x80000000 ≠ #x7fffffff → UNSAT.
        // The false belief abs(MIN)==MAX is refuted by the walked body.
        let z3 = which_z3().expect("z3 required for BV32 check");
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                abs_eq_atom(-2147483648, 2147483647),
                abs_bv_atom(-2147483648)
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        // Both BV literals must appear (the false claim #x7fffffff and the
        // walked-body subject #x80000000).
        assert!(
            script.contains("#x7fffffff") && script.contains("#x80000000"),
            "both BV literals must appear (false-claim MAX + subject MIN):\n{script}"
        );
        let out = run_z3(&z3, &script);
        assert_eq!(
            out.trim(),
            "unsat",
            "=(abs(MIN),MAX) ∧ universe must be UNSAT (industry belief refuted by walked body);\
             \ngot: {out}\nscript:\n{script}"
        );
    }

    #[test]
    fn bv32_ctors_not_declared_as_uninterpreted_functions() {
        // STRUCTURAL: BV operator ctors (bv32.ite, bv32.slt, bv32.neg) must NOT
        // appear in `(declare-fun ...)` statements — they are SMT-LIB theory
        // builtins. Declaring them as uninterpreted would shadow the theory and
        // let z3 pick a false interpretation.
        let inv = abs_bv_atom(-2147483648);
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        for forbidden in &[
            "declare-fun bv32",
            "declare-fun |bv32",
            "declare-fun bvslt",
            "declare-fun bvneg",
            "declare-fun ite",
        ] {
            assert!(
                !script.contains(forbidden),
                "BV32 operator must not be declared as uninterpreted: {forbidden}\n{script}"
            );
        }
        // The subject ctor (call:abs) MUST be declared with BV32 sort
        assert!(
            script.contains("BitVec 32"),
            "call:abs must be declared with (_ BitVec 32) sort:\n{script}"
        );
    }

    #[test]
    fn bv32_var_a_not_leaked_as_free_var() {
        // STRUCTURAL: the `var "a"` node in the BV tree is a method-parameter
        // name substituted at emit time. It must NOT be emitted as a
        // `(declare-const a ...)` free variable in the SMT script.
        let inv = abs_bv_atom(-2147483648);
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let preamble = &parts.preamble;
        assert!(
            !preamble.contains("declare-const a "),
            "var 'a' from BV tree must not be declared as a free constant:\n{preamble}"
        );
    }

    #[test]
    fn bv32_atom_does_not_affect_legacy_int_equality() {
        // LEGACY GUARD: a plain int-equality contract over the same callresult
        // ctor (without any BV atom) must continue to render in the opaque-Int
        // regime, byte-for-byte unchanged from before G2. The presence of G2
        // emitters must not retroactively reroute plain int contracts.
        let call_ctor = serde_json::json!({
            "kind": "ctor",
            "name": "call:abs",
            "args": [{"kind": "const", "value": 5, "sort": {"kind": "primitive", "name": "Int"}}]
        });
        let eq_atom = serde_json::json!({
            "kind": "atomic",
            "name": "=",
            "args": [
                call_ctor,
                {"kind": "const", "value": 5, "sort": {"kind": "primitive", "name": "Int"}}
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&eq_atom).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        // Must be in Int regime — no BV sort in preamble
        assert!(
            !script.contains("BitVec"),
            "plain int equality must not trigger BV regime:\n{script}"
        );
        // Must use regular equality, not bvslt/bvneg
        assert!(
            !script.contains("bvslt") && !script.contains("bvneg"),
            "plain int equality must not contain BV operators:\n{script}"
        );
        // The call:abs ctor must be declared with Int sort
        assert!(
            script.contains("Int) Int"),
            "call:abs must be declared with Int sort in the legacy regime:\n{script}"
        );
    }

    #[test]
    fn bv32_contagion_does_not_trip_b7_mixed_sort_stop() {
        // GUARD: the marquee conjunction — Int sworn equality + bv32 universe
        // row over the SAME call:abs term — must NOT be flagged as a B7
        // mixed-sort conflict. bv32+Int-equality-on-same-term is the SAME term
        // promoted to bv32, not a String-vs-Int conflict. It must compile.
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                abs_eq_atom(-2147483648, -2147483648),
                abs_bv_atom(-2147483648)
            ]
        });
        // fixture_compile_asserted_to_parts runs check_mixed_sort_conjunction first;
        // it must NOT return Err.
        let result = fixture_compile_asserted_to_parts(&inv);
        assert!(
            result.is_ok(),
            "bv32 universe + Int sworn equality on same term must compile (no B7 STOP); \
             got: {:?}",
            result.err()
        );
    }

    #[test]
    fn genuine_string_vs_int_conflict_still_caught_now_via_distinctness() {
        // A `call:f == "x"` (no universe) and `call:f == 5` conflict. Since the
        // string-contagion fix, the UNTAINTED ctor `== "x"` stays opaque-Int
        // ("x" -> strlit_), so this is no longer a mixed-sort STOP -- it
        // compiles and the conflict is caught MORE PRECISELY as UNSAT (a clean
        // refutation, not an undecidable). Cross-type distinctness
        // (strlit_("x") distinct from 5) is what convicts it.
        let z3 = which_z3().expect("z3");
        let call = serde_json::json!({
            "kind": "ctor",
            "name": "call:f",
            "args": [{"kind": "const", "value": 1, "sort": {"kind": "primitive", "name": "Int"}}]
        });
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                {"kind": "atomic", "name": "=", "args": [
                    call.clone(),
                    {"kind": "const", "value": "x", "sort": {"kind": "primitive", "name": "String"}}
                ]},
                {"kind": "atomic", "name": "=", "args": [
                    call,
                    {"kind": "const", "value": 5, "sort": {"kind": "primitive", "name": "Int"}}
                ]}
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv)
            .expect("untainted ctor == string is now opaque-Int, compiles");
        let script = format!("{}{}", parts.preamble, parts.body);
        assert_eq!(
            run_z3(&z3, &script).trim(),
            "unsat",
            "the genuine conflict must still be caught, now as a refutation:\n{script}"
        );
    }

    #[test]
    fn g1_string_regime_unchanged_without_bv32_atom() {
        // GUARD: a G1 string conjunction (universe + sworn String equality) with
        // NO bv32 atom present must be byte-for-byte unchanged — the contagion
        // pre-pass must be a no-op when there are no bv32 subjects.
        let call = serde_json::json!({
            "kind": "ctor",
            "name": "c:callresult_enc_a1",
            "args": [{"kind": "const", "value": "foo", "sort": {"kind": "primitive", "name": "String"}}]
        });
        let inv = serde_json::json!({
            "kind": "and",
            "operands": [
                {"kind": "atomic", "name": "str.chars-in-set", "args": [
                    call.clone(),
                    {"kind": "const", "value": "Zmo9v", "sort": {"kind": "primitive", "name": "String"}}
                ]},
                {"kind": "atomic", "name": "=", "args": [
                    call,
                    {"kind": "const", "value": "Zm9v", "sort": {"kind": "primitive", "name": "String"}}
                ]}
            ]
        });
        let parts = fixture_compile_asserted_to_parts(&inv).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        // Must stay in string theory: no BV sort, no int32.eq-const promotion.
        assert!(
            !script.contains("BitVec") && !script.contains("int32.eq-const"),
            "G1 string regime must be untouched by bv32 contagion:\n{script}"
        );
        assert!(
            script.contains("str.in_re") && script.contains("\"Zm9v\""),
            "string-theory lowering must be intact:\n{script}"
        );
    }
}
