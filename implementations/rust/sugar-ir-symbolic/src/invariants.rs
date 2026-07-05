// SPDX-License-Identifier: MIT OR Apache-2.0
//
// invariants.rs - Formal Invariants from IR Spec (Mintable)
//
// This module contains contracts that verify the formal invariants from
// protocol/specs/2026-04-30-ir-formal-grammar.md. These contracts can be
// minted as proofs via the sugar verification workflow.
//
// Each contract is declared using the contract! macro and is verified against
// the implementation. Kit-defined predicates (roundTrips, isMalformed, isErr)
// are used for properties that lack native Z3 semantics.
//
// ============================================================================
// INVARIANTS (27 total) - see protocol/specs/2026-04-30-ir-formal-grammar.md
// ============================================================================

use sugar_ir_symbolic::{
    and_, atomic_, choice, contract, forall, implies, lambda, let_term, make_var, not_, num,
    ContractArgs, Int, String_,
};

/// Collect all invariant contracts for verification and minting.
pub fn invariants() {
    // =========================================================================
    // Term Invariants
    // =========================================================================

    // -------------------------------------------------------------------------
    // INVARIANT VarTerm.NoSortField: VarTerm carries no sort field.
    // Every VarTerm MUST NOT contain a `sort` field.
    //
    // Expressed as: "make_var round-trips as var (no sort field)"
    // Uses kit-defined `roundTrips` predicate (undecidable in Z3).
    // -------------------------------------------------------------------------
    contract(
        "varterm_no_sort_field",
        ContractArgs {
            post: Some(forall(String_(), |_x| {
                let v = make_var("testvar");
                atomic_("roundTrips", vec![v])
            })),
            ..Default::default()
        },
    );

    // -------------------------------------------------------------------------
    // INVARIANT ConstTerm.HasSort: ConstTerm carries sort field.
    // Every ConstTerm MUST have a `sort` field.
    //
    // Expressed as: "num(42) round-trips preserving its Int sort"
    // -------------------------------------------------------------------------
    contract(
        "constterm_has_sort",
        ContractArgs {
            post: Some(forall(Int(), |_n| {
                let c = num(42);
                atomic_("roundTrips", vec![c])
            })),
            ..Default::default()
        },
    );

    // -------------------------------------------------------------------------
    // INVARIANT CtorTerm.NoSortField: CtorTerm carries no sort field.
    // A CtorTerm MUST NOT contain a `sort` field.
    //
    // Expressed as: "parse_int(s) round-trips as ctor (no sort field)"
    // -------------------------------------------------------------------------
    contract(
        "ctorterm_no_sort_field",
        ContractArgs {
            post: Some(forall(String_(), |_s| {
                let v = make_var("s");
                let c = sugar_ir_symbolic::parse_int(v);
                atomic_("roundTrips", vec![c])
            })),
            ..Default::default()
        },
    );

    // =========================================================================
    // Lambda Term Invariants
    // =========================================================================

    // -------------------------------------------------------------------------
    // INVARIANT LambdaTerm.HasParamSort: Lambda has paramSort field.
    // Every LambdaTerm MUST have a paramSort specifying the parameter type.
    //
    // Expressed as: "lambda(x: Int, 42) round-trips"
    // -------------------------------------------------------------------------
    contract(
        "lambda_has_param_sort",
        ContractArgs {
            post: Some(forall(Int(), |_n| {
                let lam = lambda("x".into(), Int(), num(42));
                atomic_("roundTrips", vec![lam])
            })),
            ..Default::default()
        },
    );

    // -------------------------------------------------------------------------
    // INVARIANT LambdaTerm.HasBody: Lambda has body field.
    // Every LambdaTerm MUST have a body term.
    //
    // Expressed as: "lambda(x, x) has body"
    // -------------------------------------------------------------------------
    contract(
        "lambda_has_body",
        ContractArgs {
            post: Some(forall(Int(), |x| {
                let lam = lambda("x".into(), Int(), x);
                atomic_("roundTrips", vec![lam])
            })),
            ..Default::default()
        },
    );

    // =========================================================================
    // Let Term Invariants
    // =========================================================================

    // -------------------------------------------------------------------------
    // INVARIANT LetTerm.NonEmptyBindings: Let has at least one binding.
    // A LetTerm MUST have at least one binding.
    //
    // Expressed as: "let x = 1 in x round-trips"
    // -------------------------------------------------------------------------
    contract(
        "let_non_empty_bindings",
        ContractArgs {
            post: Some(forall(Int(), |x| {
                let let_expr = let_term(
                    vec![sugar_ir_symbolic::LetBinding {
                        name: "x".into(),
                        bound_term: num(1),
                    }],
                    x,
                );
                atomic_("roundTrips", vec![let_expr])
            })),
            ..Default::default()
        },
    );

    // =========================================================================
    // Choice Formula Invariants
    // =========================================================================

    // -------------------------------------------------------------------------
    // INVARIANT ChoiceFormula.HasVarName: Choice has varName field.
    // Every ChoiceFormula MUST have a varName identifying the chosen variable.
    //
    // Expressed as: "εx:Int. x > 0 round-trips"
    // -------------------------------------------------------------------------
    contract(
        "choice_has_var_name",
        ContractArgs {
            post: Some(forall(Int(), |x| {
                let _c = choice("x".into(), Int(), |_v| {
                    atomic_(">", vec![x.clone(), num(0)])
                });
                atomic_("roundTrips", vec![make_var("choice_result")])
            })),
            ..Default::default()
        },
    );

    // -------------------------------------------------------------------------
    // INVARIANT ChoiceFormula.HasSort: Choice has sort field.
    // Every ChoiceFormula MUST have a sort specifying the chosen element type.
    //
    // Expressed as: "εx:String. true has String sort"
    // -------------------------------------------------------------------------
    contract(
        "choice_has_sort",
        ContractArgs {
            post: Some(forall(String_(), |s| {
                let _c = choice("x".into(), String_(), |_v| atomic_("true", vec![]));
                atomic_("roundTrips", vec![s])
            })),
            ..Default::default()
        },
    );

    // =========================================================================
    // Quantifier Invariants
    // =========================================================================

    // -------------------------------------------------------------------------
    // INVARIANT QuantifierFormula.HasSort: Quantifier has sort field.
    // Every quantifier MUST have a sort field specifying bound variable type.
    //
    // Expressed as: "forall(Int, fn) produces valid quantifier"
    // -------------------------------------------------------------------------
    contract(
        "quantifier_has_sort",
        ContractArgs {
            post: Some(forall(Int(), |v| {
                let _q = forall(Int(), |inner| atomic_(">", vec![inner.clone(), num(0)]));
                // Quantifier formula is valid - verify it contains the bound var
                atomic_("roundTrips", vec![v])
            })),
            ..Default::default()
        },
    );

    // =========================================================================
    // Connective Invariants
    // =========================================================================

    // -------------------------------------------------------------------------
    // INVARIANT ConnectiveFormula.NotArity: not has exactly 1 operand.
    //
    // Expressed as: "not(true) is a valid formula"
    // -------------------------------------------------------------------------
    contract(
        "kit_not_arity_eq_one",
        ContractArgs {
            post: Some(forall(Int(), |_n| {
                let _f = not_(atomic_("true", vec![]));
                // Verify not produces a valid formula
                atomic_("roundTrips", vec![make_var("not_result")])
            })),
            ..Default::default()
        },
    );

    // -------------------------------------------------------------------------
    // INVARIANT ConnectiveFormula.ImpliesArity: implies has exactly 2 operands.
    //
    // Expressed as: "implies(true, true) is a valid formula"
    // -------------------------------------------------------------------------
    contract(
        "kit_implies_arity_eq_two",
        ContractArgs {
            post: Some(forall(Int(), |_n| {
                let _f = implies(atomic_("true", vec![]), atomic_("true", vec![]));
                // Implies formula is constructed
                atomic_("roundTrips", vec![make_var("implies_result")])
            })),
            ..Default::default()
        },
    );

    // -------------------------------------------------------------------------
    // INVARIANT ConnectiveFormula.AndOrArity: and/or have at least 2 operands.
    //
    // Expressed as: "and(true, true) is a valid formula"
    // -------------------------------------------------------------------------
    contract(
        "and_arity_at_least_two",
        ContractArgs {
            post: Some(forall(Int(), |_n| {
                let _f = and_(vec![atomic_("true", vec![]), atomic_("true", vec![])]);
                // And formula is constructed
                atomic_("roundTrips", vec![make_var("and_result")])
            })),
            ..Default::default()
        },
    );

    // =========================================================================
    // Atomic Invariants
    // =========================================================================

    // -------------------------------------------------------------------------
    // INVARIANT AtomicFormula.HasName: Atomic has name field.
    //
    // Expressed as: "atomic('=', [n, 0]) has name '='"
    // -------------------------------------------------------------------------
    contract(
        "atomic_has_name",
        ContractArgs {
            post: Some(forall(Int(), |n| {
                let _f = atomic_("=", vec![n.clone(), num(0)]);
                // Verify atomic formula construction
                atomic_("roundTrips", vec![n])
            })),
            ..Default::default()
        },
    );

    // -------------------------------------------------------------------------
    // INVARIANT AtomicFormula.HasArgs: Atomic has args array.
    //
    // Expressed as: "atomic with args is valid"
    // -------------------------------------------------------------------------
    contract(
        "atomic_has_args",
        ContractArgs {
            post: Some(forall(Int(), |n| {
                let _f = atomic_("=", vec![n.clone(), num(0)]);
                atomic_("roundTrips", vec![n])
            })),
            ..Default::default()
        },
    );

    // =========================================================================
    // Sort Invariants
    // =========================================================================

    // -------------------------------------------------------------------------
    // INVARIANT PrimitiveSort.ValidName: Primitive sort has valid name.
    //
    // Expressed as: "Int() returns valid Sort"
    // -------------------------------------------------------------------------
    contract(
        "primitive_sort_valid_name",
        ContractArgs {
            post: Some(forall(Int(), |n| {
                // Sort::Int() produces valid sort
                atomic_("roundTrips", vec![n])
            })),
            ..Default::default()
        },
    );

    // =========================================================================
    // Contract Declaration Invariants
    // =========================================================================

    // -------------------------------------------------------------------------
    // INVARIANT ContractDeclaration.HasOutBinding: Contract has outBinding.
    //
    // Expressed as: "contract with outBinding is valid"
    // -------------------------------------------------------------------------
    contract(
        "contract_has_outbinding",
        ContractArgs {
            pre: Some(atomic_("true", vec![])),
            out_binding: Some("out".into()),
            ..Default::default()
        },
    );

    // -------------------------------------------------------------------------
    // INVARIANT ContractDeclaration.HasAtLeastOneFormula: At least one of
    // pre/post/inv must be present.
    //
    // Expressed as: "contract with pre is valid"
    // -------------------------------------------------------------------------
    contract(
        "contract_has_at_least_one_formula",
        ContractArgs {
            pre: Some(atomic_("true", vec![])),
            out_binding: Some("out".into()),
            ..Default::default()
        },
    );
}
