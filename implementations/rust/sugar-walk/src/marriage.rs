// SPDX-License-Identifier: Apache-2.0
//
// AST + MIR marriage. The point of running both layers isn't to
// produce two parallel contracts that happen to agree — that's
// coexistence. Marriage produces ONE FunctionContractMemento per
// function, with the predicate atoms from BOTH layers unioned and
// content-addressed as a single substrate record.
//
// What gets married
//   - Surface-AST lift via syn (lift.rs + capture-avoiding subst)
//   - Post-borrow-check MIR lift via Charon LLBC (llbc_lift.rs)
//
// The merged contract carries the AST's locus (it has source-line
// metadata; LLBC has spans but they're block-level, not function-
// level), formals, formal sorts, return sort, and body_cid. The pre
// and post formulas are the deduplicated union of conjuncts from
// both layers — atoms that BOTH layers see appear once; atoms only
// MIR sees (overflow checks, deref soundness) are added; atoms only
// AST sees (source-level patterns MIR optimized away) are kept.
//
// Per paper 07 §6, the substrate stores one memento per logical
// contract. Marriage is what makes that operational: downstream
// consumers see ONE content_cid per function, not two.
//
// Why this matters
//   - Cross-layer cache reuse on agreed predicates: minted once.
//   - MIR-exclusive predicates layer cleanly into the same memento
//     (overflow asserts, slice-bounds checks, drop-glue invariants
//     — all things rustc inserts that the surface AST doesn't see).
//   - The substrate is one body of evidence, not two.

use std::collections::HashSet;
use std::path::Path;

use sugar_ir_types::{IrFormula, IrTerm, Sort};
use thiserror::Error;

use crate::canonical::{cid_of_value, formula_to_canonical, jcs_bytes_of_value};
use crate::charon_runner::{invoke_charon_on_rs_source, RunnerError};
use crate::contract::{build_function_contract_with_file, Effect, FunctionContractMemento};
use crate::llbc::LlbcError;
use crate::llbc_lift::lift_llbc_function_with_types;
use crate::wp::atomic_true;

#[derive(Debug, Error)]
pub enum MarriageError {
    #[error("source read: {0}")]
    Io(#[from] std::io::Error),
    #[error("syn parse: {0}")]
    Syn(#[from] syn::Error),
    #[error("function not found in source: {0}")]
    FunctionNotFound(String),
    #[error("charon runner: {0}")]
    Runner(#[from] RunnerError),
    #[error("llbc: {0}")]
    Llbc(#[from] LlbcError),
}

/// Why LLBC contributed atoms AST did not see.
///
/// `TypePrecision` is the current catch-all: sort refinements such as
/// Int vs U32 that the surface AST cannot express. `LifetimeRelative`
/// covers Outlives predicates emitted by the C.9 lifter (#384 C.9),
/// classified by a predicate name starting with `"outlives"` OR any
/// predicate whose terms reference `Sort::Region`-tagged sorts.
/// `BorrowState` is reserved for mut/shared distinctions.
///
/// Classifier rules (checked in order):
/// 1. Atom predicate name starts with `"outlives"` -> `LifetimeRelative`
/// 2. Any term in the atom carries `Sort::Region` -> `LifetimeRelative`
/// 3. Everything else -> `TypePrecision`
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LlbcExtraCategory {
    /// Sort refinements (Int vs U32, Int vs Bool, etc.) and all
    /// other uncategorized LLBC-only atoms. Default category.
    TypePrecision,
    /// Outlives predicates derived from borrow regions. AST has no
    /// lifetime view, so these atoms are structurally AST-empty by
    /// design. Does NOT fail the marriage discipline.
    LifetimeRelative,
    /// Mutability / sharing distinctions. Reserved for future use.
    BorrowState,
}

/// How AST and LLBC layers compared on the conjuncts of pre and post.
/// `Identical` means byte-equal pre AND post; `LlbcExtra(cat)` means
/// LLBC contributed atoms AST did not see, classified by category;
/// `AstExtra` is rare (MIR optimized something away);
/// `Both(cat)` means both sides contributed extras, with category
/// assigned to the LLBC-side extras (the only categorizable axis).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LayerAgreement {
    Identical,
    LlbcExtra(LlbcExtraCategory),
    AstExtra,
    Both(LlbcExtraCategory),
}

/// The married result. Both diagnostic layer contracts and the merged
/// substrate-facing contract are exposed; downstream consumers should
/// use `merged`, while review tooling and cache instrumentation can
/// inspect `ast` and `llbc` independently.
pub struct MarriedContract {
    pub ast: FunctionContractMemento,
    pub llbc: FunctionContractMemento,
    pub merged: FunctionContractMemento,
    pub agreement: LayerAgreement,
}

/// Lift one function from a `.rs` source through both layers and
/// produce a married contract. Charon must be available; see
/// `charon_runner::find_charon_binary`.
pub fn lift_marriage(
    rs_source_path: &Path,
    fn_name: &str,
) -> Result<MarriedContract, MarriageError> {
    // AST layer
    let src = std::fs::read_to_string(rs_source_path)?;
    let file: syn::File = syn::parse_str(&src)?;
    let item_fn = file
        .items
        .into_iter()
        .find_map(|item| match item {
            syn::Item::Fn(f) if f.sig.ident == fn_name => Some(f),
            // sugar-audit: not-mine(top-level-marriage-lookup-continues-until-target-or-errors)
            _ => None,
        })
        .ok_or_else(|| MarriageError::FunctionNotFound(fn_name.to_string()))?;
    let ast = build_function_contract_with_file(&item_fn, None, rs_source_path.to_str());

    // LLBC layer via Charon
    let krate = invoke_charon_on_rs_source(rs_source_path, None)?;
    let f = krate
        .function_by_name(fn_name)
        .map_err(MarriageError::Llbc)?;
    let llbc = lift_llbc_function_with_types(f, rs_source_path.to_str(), krate.type_decls_raw())
        .map_err(MarriageError::Llbc)?;

    Ok(marry(ast, llbc))
}

/// Marry two already-built contracts. Useful when the layers come from
/// elsewhere (e.g. a vendored `.llbc` for tests, or a different lifter
/// stack). The merged contract takes the AST's metadata (locus,
/// formals, sorts, body_cid) and the union of both layers' predicate
/// atoms.
pub fn marry(ast: FunctionContractMemento, llbc: FunctionContractMemento) -> MarriedContract {
    let agreement = compare_layers(&ast, &llbc);
    let merged_pre = merge_formulas(&ast.pre, &llbc.pre);
    let merged_post = merge_formulas(&ast.post, &llbc.post);

    let mut merged = ast.clone();
    merged.pre = merged_pre;
    merged.post = merged_post;
    let value = crate::contract::build_memento_value(&merged);
    merged.canonical_bytes = jcs_bytes_of_value(&value);
    merged.cid = cid_of_value(&value);

    MarriedContract {
        ast,
        llbc,
        merged,
        agreement,
    }
}

fn compare_layers(ast: &FunctionContractMemento, llbc: &FunctionContractMemento) -> LayerAgreement {
    let ast_pre_atoms = atom_byte_set(&ast.pre);
    let llbc_pre_atoms = atom_byte_set(&llbc.pre);
    let ast_post_atoms = atom_byte_set(&ast.post);
    let llbc_post_atoms = atom_byte_set(&llbc.post);

    let ast_only = ast_pre_atoms.difference(&llbc_pre_atoms).next().is_some()
        || ast_post_atoms.difference(&llbc_post_atoms).next().is_some();
    let llbc_only = llbc_pre_atoms.difference(&ast_pre_atoms).next().is_some()
        || llbc_post_atoms.difference(&ast_post_atoms).next().is_some();

    // Collect the LLBC-exclusive atoms for category classification.
    let llbc_extras_pre: Vec<IrFormula> = conjuncts(&llbc.pre)
        .into_iter()
        .filter(|f| !is_trivially_true(f))
        .filter(|f| {
            let bytes = jcs_bytes_of_value(&formula_to_canonical(f));
            !ast_pre_atoms.contains(&bytes)
        })
        .collect();
    let llbc_extras_post: Vec<IrFormula> = conjuncts(&llbc.post)
        .into_iter()
        .filter(|f| !is_trivially_true(f))
        .filter(|f| {
            let bytes = jcs_bytes_of_value(&formula_to_canonical(f));
            !ast_post_atoms.contains(&bytes)
        })
        .collect();
    let llbc_extras: Vec<IrFormula> = llbc_extras_pre
        .into_iter()
        .chain(llbc_extras_post)
        .collect();

    let agreement = match (ast_only, llbc_only) {
        (false, false) => LayerAgreement::Identical,
        (false, true) => LayerAgreement::LlbcExtra(classify_extras(&llbc_extras)),
        (true, false) => LayerAgreement::AstExtra,
        (true, true) => LayerAgreement::Both(classify_extras(&llbc_extras)),
    };

    // Effect-based classification: PossibleAliasing is an LLBC-only effect
    // (AST cannot see borrow shape). When formulas agree but LLBC carries
    // PossibleAliasing that AST doesn't, classify as LlbcExtra(BorrowState).
    if agreement == LayerAgreement::Identical {
        let llbc_has_aliasing = llbc
            .effects
            .effects
            .iter()
            .any(|e| matches!(e, Effect::PossibleAliasing { .. }));
        let ast_has_aliasing = ast
            .effects
            .effects
            .iter()
            .any(|e| matches!(e, Effect::PossibleAliasing { .. }));
        if llbc_has_aliasing && !ast_has_aliasing {
            return LayerAgreement::LlbcExtra(LlbcExtraCategory::BorrowState);
        }
    }

    agreement
}

/// Classify a slice of LLBC-exclusive atoms into a category.
///
/// Rules (checked in order):
/// 1. If any atom's predicate name starts with `"outlives"`, the extras
///    are `LifetimeRelative`.
/// 2. If any atom references a `Sort::Region`-tagged term (via `Const`
///    sort or recursive descent through `Ctor` args), the extras are
///    `LifetimeRelative`.
/// 3. Otherwise `TypePrecision` is returned as the default catch-all.
pub fn classify_extras(extras: &[IrFormula]) -> LlbcExtraCategory {
    for formula in extras {
        if let IrFormula::Atomic { name, args } = formula {
            if name.to_lowercase().starts_with("outlives") {
                return LlbcExtraCategory::LifetimeRelative;
            }
            for arg in args {
                if term_has_region_sort(arg) {
                    return LlbcExtraCategory::LifetimeRelative;
                }
            }
        }
    }
    LlbcExtraCategory::TypePrecision
}

/// Walk an `IrTerm` to determine whether it carries a `Sort::Region`.
///
/// Checks `Const` sort fields and recurses through `Ctor` args and
/// `Lambda` bodies. `Var` nodes have no sort metadata and are skipped.
fn term_has_region_sort(term: &IrTerm) -> bool {
    match term {
        IrTerm::Const {
            sort: Sort::Region { .. },
            ..
        } => true,
        IrTerm::Const { .. } => false,
        IrTerm::Var { .. } => false,
        IrTerm::Ctor { args, .. } => args.iter().any(term_has_region_sort),
        IrTerm::Lambda {
            param_sort: Sort::Region { .. },
            ..
        } => true,
        IrTerm::Lambda { body, .. } => term_has_region_sort(body),
        IrTerm::Let { bindings, body } => {
            bindings.iter().any(|b| term_has_region_sort(&b.bound_term))
                || term_has_region_sort(body)
        }
    }
}

/// Check whether an `IrFormula` references a `Sort::Region` sort.
/// Used by composition-level region checks; kept here for proximity
/// to the term-level classifier.
#[allow(dead_code)]
fn term_has_region_sort_in_formula(f: &IrFormula) -> bool {
    match f {
        IrFormula::Atomic { args, .. } => args.iter().any(term_has_region_sort),
        IrFormula::And { operands } | IrFormula::Or { operands } => {
            operands.iter().any(term_has_region_sort_in_formula)
        }
        IrFormula::Not { operands } => operands.iter().any(term_has_region_sort_in_formula),
        IrFormula::Implies { operands } => operands.iter().any(term_has_region_sort_in_formula),
        IrFormula::Forall {
            sort: Sort::Region { .. },
            ..
        }
        | IrFormula::Exists {
            sort: Sort::Region { .. },
            ..
        }
        | IrFormula::Choice {
            sort: Sort::Region { .. },
            ..
        } => true,
        IrFormula::Forall { body, .. }
        | IrFormula::Exists { body, .. }
        | IrFormula::Choice { body, .. } => term_has_region_sort_in_formula(body),
        IrFormula::DivergenceBetween { source, target } => {
            term_has_region_sort_in_formula(source) || term_has_region_sort_in_formula(target)
        }
        // Substitute and Apply are meta-level; no region sort to detect.
        IrFormula::Substitute { .. } | IrFormula::Apply { .. } => false,
    }
}

fn atom_byte_set(f: &IrFormula) -> HashSet<Vec<u8>> {
    conjuncts(f)
        .into_iter()
        .filter(|c| !is_trivially_true(c))
        .map(|c| jcs_bytes_of_value(&formula_to_canonical(&c)))
        .collect()
}

/// Flatten an IrFormula into its top-level conjuncts. Non-And nodes
/// are returned as a singleton vec.
fn conjuncts(f: &IrFormula) -> Vec<IrFormula> {
    match f {
        IrFormula::And { operands } => operands.iter().flat_map(conjuncts).collect(),
        other => vec![other.clone()],
    }
}

fn is_trivially_true(f: &IrFormula) -> bool {
    matches!(f, IrFormula::Atomic { name, args } if name == "true" && args.is_empty())
}

/// Conjunction-merge two formulas: union of conjuncts deduplicated by
/// JCS-byte hash, with `true` atoms dropped (identity for ∧). Source
/// order is preserved (AST atoms first, then LLBC's extras).
pub fn merge_formulas(a: &IrFormula, b: &IrFormula) -> IrFormula {
    let mut atoms: Vec<IrFormula> = Vec::new();
    let mut seen: HashSet<Vec<u8>> = HashSet::new();
    for f in conjuncts(a).into_iter().chain(conjuncts(b)) {
        if is_trivially_true(&f) {
            continue;
        }
        let bytes = jcs_bytes_of_value(&formula_to_canonical(&f));
        if seen.insert(bytes) {
            atoms.push(f);
        }
    }
    if atoms.is_empty() {
        atomic_true().into_formula()
    } else if atoms.len() == 1 {
        atoms.into_iter().next().unwrap()
    } else {
        IrFormula::And { operands: atoms }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::canonical::{formula_to_canonical, jcs_bytes_of_value};
    use crate::charon_runner::find_charon_binary;
    use crate::contract::build_function_contract_with_file;
    use crate::envelope::{wrap_function_contract_cached, EnvelopeCache, DEV_SIGNER_SEED};
    use crate::llbc::LlbcCrate;
    use crate::llbc_lift::lift_llbc_function_with_types;

    fn fixture_path(name: &str) -> std::path::PathBuf {
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests")
            .join("fixtures")
            .join(name)
    }

    fn build_layers(
        rs: &str,
        llbc: &str,
        fn_name: &str,
    ) -> (FunctionContractMemento, FunctionContractMemento) {
        let src = std::fs::read_to_string(fixture_path(rs)).unwrap();
        let file: syn::File = syn::parse_str(&src).unwrap();
        let item_fn = file
            .items
            .into_iter()
            .find_map(|item| match item {
                syn::Item::Fn(f) if f.sig.ident == fn_name => Some(f),
                // sugar-audit: not-mine(test-helper-search-ignores-non-target-items)
                _ => None,
            })
            .unwrap();
        let ast = build_function_contract_with_file(&item_fn, None, Some(rs));
        let krate = LlbcCrate::from_path(fixture_path(llbc)).unwrap();
        let f = krate.function_by_name(fn_name).unwrap();
        let llbc = lift_llbc_function_with_types(f, Some(rs), krate.type_decls_raw()).unwrap();
        (ast, llbc)
    }

    #[test]
    fn marriage_on_agreed_layers_yields_identical() {
        let (ast, llbc) = build_layers("clean.rs", "clean.llbc", "f");
        let married = marry(ast, llbc);
        assert_eq!(
            married.agreement,
            LayerAgreement::Identical,
            "AST and LLBC agree on `if x<10 panic` => Identical"
        );
    }

    #[test]
    fn marriage_on_compound_or_yields_identical() {
        let (ast, llbc) = build_layers("compound_or.rs", "compound_or.llbc", "h");
        let married = marry(ast, llbc);
        assert_eq!(married.agreement, LayerAgreement::Identical);
    }

    #[test]
    fn merged_contract_carries_one_cid_for_substrate() {
        // The OPERATIONAL claim. The merged contract is what
        // downstream consumers see. ONE memento, ONE cid, ONE
        // substrate record per function — regardless of how many
        // layers contributed.
        let (ast, llbc) = build_layers("clean.rs", "clean.llbc", "f");
        let married = marry(ast, llbc);

        // Merged.cid is well-formed and stable.
        assert!(married.merged.cid.starts_with("blake3-512:"));
        assert_eq!(married.merged.fn_name, "f");

        // When layers agree, merged predicate bytes equal each layer's.
        let merged_pre = jcs_bytes_of_value(&formula_to_canonical(&married.merged.pre));
        let ast_pre = jcs_bytes_of_value(&formula_to_canonical(&married.ast.pre));
        let llbc_pre = jcs_bytes_of_value(&formula_to_canonical(&married.llbc.pre));
        assert_eq!(merged_pre, ast_pre);
        assert_eq!(merged_pre, llbc_pre);
    }

    #[test]
    fn married_contract_wraps_to_one_envelope_via_cache() {
        // Substrate-level claim: the married contract wraps once,
        // and wrapping it twice hits the cache. One mint, one record.
        let (ast, llbc) = build_layers("clean.rs", "clean.llbc", "f");
        let married = marry(ast, llbc);

        let mut cache = EnvelopeCache::new();
        let env1 = wrap_function_contract_cached(
            &married.merged,
            "2026-05-05T00:00:00Z",
            &DEV_SIGNER_SEED,
            &mut cache,
        )
        .unwrap();
        assert_eq!(cache.mints, 1);
        assert_eq!(cache.hits, 0);

        let env2 = wrap_function_contract_cached(
            &married.merged,
            "2026-05-05T00:00:00Z",
            &DEV_SIGNER_SEED,
            &mut cache,
        )
        .unwrap();
        assert_eq!(cache.mints, 1, "second wrap of merged must hit cache");
        assert_eq!(cache.hits, 1);
        assert_eq!(env1.cid, env2.cid);
        assert_eq!(env1.contract_cid, env2.contract_cid);
    }

    #[test]
    fn merge_formulas_dedups_identical_atoms() {
        // Direct unit on the conjunct merge: same atom from two
        // layers becomes one.
        use crate::wp::{atomic_ge, const_int, var};
        let a = atomic_ge(var("x"), const_int(10)).into_formula();
        let b = atomic_ge(var("x"), const_int(10)).into_formula();
        let merged = merge_formulas(&a, &b);
        // Single-atom conjunction collapses back to the bare atom.
        match merged {
            IrFormula::Atomic { name, .. } => assert_eq!(name, "≥"),
            other => panic!("expected single Atomic, got {:?}", other),
        }
    }

    #[test]
    fn merge_formulas_unions_distinct_atoms() {
        // x ≥ 10 (from AST) ∧ y ≥ 5 (from MIR-only) merges into the
        // union. This is the structural case of LlbcExtra: MIR sees
        // a predicate AST didn't.
        use crate::wp::{atomic_ge, const_int, var};
        let a = atomic_ge(var("x"), const_int(10)).into_formula();
        let b = atomic_ge(var("y"), const_int(5)).into_formula();
        let merged = merge_formulas(&a, &b);
        match merged {
            IrFormula::And { operands } => {
                assert_eq!(operands.len(), 2);
            }
            other => panic!("expected And, got {:?}", other),
        }
    }

    #[test]
    fn marriage_on_overflow_arithmetic_surfaces_mir_extras_in_merged() {
        // The "MIR sees more" lane. `fn g(x: u32) -> u32 { x * 2 }`
        // has no source-level preconditions — AST walk emits trivial-
        // true pre. MIR inserts an overflow assert (CheckedMul +
        // Assert on the overflow flag), so LLBC contributes a no-
        // overflow predicate AST never saw.
        //
        // Agreement here is `Both`, not `LlbcExtra`, because the AST
        // walk also derives `result = x * 2` from the trailing
        // return expression — and the LLBC lift doesn't yet emit
        // return-value derivations from MIR's tuple-projection +
        // CheckedOp pattern (tracked separately under #383). On the
        // pre side LLBC has more; on the post side AST has more.
        //
        // The OPERATIONAL claim — what the substrate sees — is that
        // the merged contract carries BOTH layers' contributions.
        // No information is lost in marriage.
        let (ast, llbc) = build_layers("overflow.rs", "overflow.llbc", "g");
        let married = marry(ast, llbc);

        // After the LLBC return-value derivation lands (#383), the
        // post side stops contributing AST-only atoms (both layers
        // see `result = x*2`); the only asymmetry is MIR's no-overflow
        // atom on the pre side. Agreement collapses to LlbcExtra.
        assert_eq!(
            married.agreement,
            LayerAgreement::LlbcExtra(LlbcExtraCategory::TypePrecision),
            "post sides converge after return-value derivation; MIR-only is the no-overflow"
        );

        // The MIR-only no-overflow atom is in the merged contract.
        // This is the empirical "MIR sees more" demonstration —
        // observable in the merged record, not asserted.
        let merged_pre_str = serde_json::to_string(&married.merged.pre).unwrap();
        assert!(
            merged_pre_str.contains("no-overflow:mul-wrap"),
            "merged pre carries the MIR-only no-overflow atom: {}",
            merged_pre_str
        );

        // AST's `result = x*2` derivation also survives in merged.
        // The marriage is symmetric: it doesn't drop AST's atoms in
        // favor of LLBC's, or vice versa.
        let merged_post_str = serde_json::to_string(&married.merged.post).unwrap();
        assert!(
            merged_post_str.contains("result"),
            "merged post still carries AST's result-equation: {}",
            merged_post_str
        );
    }

    #[test]
    fn marriage_on_slice_index_surfaces_bounds_check_atom() {
        // `fn at(s: &[u32], i: usize) -> u32 { s[i] }` — AST sees no
        // source-level guard. MIR inserts a BoundsCheck assert
        // (i < s.len()). Marriage should surface that as a MIR-only
        // atom in the merged contract's pre.
        let (ast, llbc) = build_layers("bounds.rs", "bounds.llbc", "at");
        let married = marry(ast, llbc);

        let merged_pre_str = serde_json::to_string(&married.merged.pre).unwrap();
        // The bounds atom: `Atomic("<", [Var("i"), Ctor("len", [Var("s")])])`.
        assert!(
            merged_pre_str.contains("\"i\""),
            "merged pre references the index formal: {}",
            merged_pre_str
        );
        assert!(
            merged_pre_str.contains("len"),
            "merged pre includes the slice length via PtrMetadata lift: {}",
            merged_pre_str
        );
        // LLBC contributes the BoundsCheck atom; AST sees no guard.
        // After the Index-rvalue post-collapse fix, both layers derive
        // `result = s[i]`, so the only asymmetry is the pre-side bounds
        // check — agreement collapses to LlbcExtra exactly.
        assert_eq!(
            married.agreement,
            LayerAgreement::LlbcExtra(LlbcExtraCategory::TypePrecision),
            "MIR sees the bounds check; both layers agree on post. got {:?}",
            married.agreement
        );

        // Both layers derive the result = s[i] postcondition.
        let merged_post_str = serde_json::to_string(&married.merged.post).unwrap();
        assert!(
            merged_post_str.contains("index"),
            "merged post carries the index postcondition (result = s[i]): {}",
            merged_post_str
        );
    }

    #[test]
    fn marriage_on_division_surfaces_div_by_zero_atom() {
        // `fn d(x: u32, y: u32) -> u32 { x / y }` — AST sees no guard.
        // MIR inserts DivisionByZero assert. Marriage merges in the
        // `y ≠ 0` predicate.
        let (ast, llbc) = build_layers("divmod.rs", "divmod.llbc", "d");
        let married = marry(ast, llbc);

        let merged_pre_str = serde_json::to_string(&married.merged.pre).unwrap();
        // The div-by-zero atom: `Atomic("≠", [Var("y"), Const(0)])`.
        assert!(
            merged_pre_str.contains("\"y\""),
            "merged pre references the divisor formal: {}",
            merged_pre_str
        );
        assert!(
            merged_pre_str.contains("\"\\u2260\"") || merged_pre_str.contains("≠"),
            "merged pre includes the ≠ predicate: {}",
            merged_pre_str
        );
        // After the BinaryOp object-form fix, both layers derive
        // `result = x / y`, so the only asymmetry is the pre-side
        // div-by-zero atom — agreement collapses to LlbcExtra exactly.
        assert_eq!(
            married.agreement,
            LayerAgreement::LlbcExtra(LlbcExtraCategory::TypePrecision),
            "MIR sees div-by-zero check; both layers agree on post. got {:?}",
            married.agreement
        );
    }

    #[test]
    fn marriage_on_multihop_let_binding_yields_identical() {
        // `fn f(x: u32) { let y = x; if y < 10 { panic!(); } }`
        //
        // AST walk sees `if y < 10 { panic!() }` and produces
        // `Atomic("≥", [Var("y"), Const(10)])` — `y` is a free Var at
        // the surface level.
        //
        // LLBC walk traces back through the discriminant chain:
        //   _3 := BinaryOp(Lt, Move(_4), Const(10))
        //   _4 := Use(Copy(_2))   -- _2 has source name "y"
        //   _2 := Use(Copy(_1))   -- _1 is formal "x"
        //
        // Without the named-local stop rule, LLBC would trace through
        // _2 to _1 and emit Var("x"), diverging from the AST walk's
        // Var("y"). With the stop rule: when _2 has name="y" in
        // Charon's locals table, we stop and emit Var("y") — matching
        // AST byte-for-byte. Agreement is Identical.
        let (ast, llbc) = build_layers("multihop.rs", "multihop.llbc", "f");
        let married = marry(ast, llbc);

        assert_eq!(
            married.agreement,
            LayerAgreement::Identical,
            "named-local stop rule: LLBC stops at Var(y) matching AST. got {:?}",
            married.agreement
        );

        // The pre formula is (y >= 10).
        let pre_str = serde_json::to_string(&married.merged.pre).unwrap();
        assert!(
            pre_str.contains("\"y\""),
            "pre references the let-binding name y, not the formal x: {}",
            pre_str
        );
    }

    #[test]
    fn end_to_end_marriage_via_charon_runner() {
        // Full pipeline: write .rs → AST lift + Charon → LLBC lift →
        // marry → ONE married contract. No vendored fixture.
        if find_charon_binary().is_none() {
            eprintln!("charon not found; skipping marriage e2e");
            return;
        }
        let path = fixture_path("clean.rs");
        let married = lift_marriage(&path, "f").expect("marriage runs end-to-end");
        assert_eq!(married.agreement, LayerAgreement::Identical);
        assert!(married.merged.cid.starts_with("blake3-512:"));
    }

    #[test]
    fn marriage_on_cast_yields_identical_result_equals_x() {
        // Task A: `fn c(x: u8) -> u32 { x as u32 }`.
        // AST: Expr::Cast(c) → lift inner expr → Var("x"), so post
        // derives `result = x`.
        // LLBC: Charon emits `UnaryOp([Cast{Scalar(U8,U32)}, Move(_1)])`.
        // After the Cast-transparent arm in rvalue_to_ir_term_for_post,
        // the inner operand traces back to the formal `x`, so post
        // derives `result = x` as well.
        // Cross-layer: byte-identical pre (trivial-true) and post
        // (result = x). LayerAgreement::Identical.
        let (ast, llbc) = build_layers("cast.rs", "cast.llbc", "c");
        let married = marry(ast, llbc);
        assert_eq!(
            married.agreement,
            LayerAgreement::Identical,
            "cast disappears at IR layer — both layers see `result = x`"
        );

        let post_str = serde_json::to_string(&married.merged.post).unwrap();
        assert!(
            post_str.contains("\"result\""),
            "merged post carries result equation: {}",
            post_str
        );
        assert!(
            post_str.contains("\"x\""),
            "merged post equates result with x: {}",
            post_str
        );
        // Verify `=` predicate is the bridge (not `≥`, not `no-overflow`)
        assert!(
            post_str.contains("\"=\""),
            "merged post is a result-equals predicate: {}",
            post_str
        );
    }

    #[test]
    fn marriage_on_bitwise_and_yields_identical_result_equals_x_and_y() {
        // Task B: `fn b(x: u32, y: u32) -> u32 { x & y }`.
        // AST: BinOp::BitAnd → Ctor("&", [Var("x"), Var("y")]).
        //   Post derives `result = x & y`.
        // LLBC: BinaryOp(["BitAnd", ...]) → mir_arith_op_to_ir_ctor("BitAnd")
        //   → "&" → Ctor("&", [Var("x"), Var("y")]).
        //   Post derives `result = x & y`.
        // No overflow assert for `&` in debug mode.
        // Cross-layer: byte-identical pre (trivial-true) and post.
        // LayerAgreement::Identical.
        let (ast, llbc) = build_layers("bitwise.rs", "bitwise.llbc", "b");
        let married = marry(ast, llbc);
        assert_eq!(
            married.agreement,
            LayerAgreement::Identical,
            "bitwise AND produces identical IR from both layers"
        );

        let post_str = serde_json::to_string(&married.merged.post).unwrap();
        assert!(
            post_str.contains("\"result\""),
            "merged post carries result equation: {}",
            post_str
        );
        assert!(
            post_str.contains("\"&\""),
            "merged post encodes the bitwise AND ctor: {}",
            post_str
        );
        assert!(
            post_str.contains("\"x\"") && post_str.contains("\"y\""),
            "merged post references both formals: {}",
            post_str
        );
    }

    // ---- Task 1: struct field access marriage ----

    #[test]
    fn marriage_on_struct_field_yields_identical() {
        // `fn p(p: &Point) -> u32 { p.x }` — no source-level guards,
        // no MIR-inserted asserts. Both layers derive `result =
        // Ctor("field", [Var("p"), Var(".x")])`. LayerAgreement::Identical.
        let (ast, llbc) = build_layers("struct_field.rs", "struct_field.llbc", "p");
        let married = marry(ast, llbc);
        assert_eq!(
            married.agreement,
            LayerAgreement::Identical,
            "struct field access: both layers agree; got {:?}",
            married.agreement
        );

        let post_str = serde_json::to_string(&married.merged.post).unwrap();
        assert!(
            post_str.contains("\".x\""),
            "merged post uses named field .x: {}",
            post_str
        );
    }

    // ---- Task 2: tuple element projection marriage ----

    #[test]
    fn marriage_on_tuple_field_yields_identical() {
        // `fn t(p: (u32, u32)) -> u32 { p.0 }` — no guards, no MIR
        // asserts. Both layers derive `result = Ctor("field", [Var("p"),
        // Var(".0")])`. LayerAgreement::Identical.
        let (ast, llbc) = build_layers("tuple_field.rs", "tuple_field.llbc", "t");
        let married = marry(ast, llbc);
        assert_eq!(
            married.agreement,
            LayerAgreement::Identical,
            "tuple field access: both layers agree; got {:?}",
            married.agreement
        );

        let post_str = serde_json::to_string(&married.merged.post).unwrap();
        assert!(
            post_str.contains("\".0\""),
            "merged post uses tuple index .0: {}",
            post_str
        );
    }

    // ---- Task A: SwitchInt multi-arm match marriage ----

    #[test]
    fn marriage_on_match_arms_yields_llbc_extra() {
        // `fn f(x: u32) { match x { 0 | 1 => panic!(), _ => {} } }`
        // AST walk: Expr::Match returns None from lift_expr_contribution,
        // so pre is trivially-true. AST contributes nothing to pre.
        // LLBC walk: Switch::SwitchInt arm [0,1] leads to Abort (via
        // fall-through to post-switch Abort). Lifter emits x != 0 /\ x != 1.
        // Agreement: LlbcExtra (LLBC sees more; AST sees nothing in pre;
        // both see trivial-true post since fn returns unit).
        let (ast, llbc) = build_layers("match_arms.rs", "match_arms.llbc", "f");
        let married = marry(ast, llbc);

        assert_eq!(
            married.agreement,
            LayerAgreement::LlbcExtra(LlbcExtraCategory::TypePrecision),
            "match arms: LLBC contributes != atoms AST doesn't see; got {:?}",
            married.agreement
        );

        // The merged pre carries the != atoms from LLBC.
        let merged_pre_str = serde_json::to_string(&married.merged.pre).unwrap();
        assert!(
            merged_pre_str.contains("\u{2260}"),
            "merged pre includes the != predicate: {}",
            merged_pre_str
        );
    }

    // ---- LifetimeRelative category: AST-empty LLBC-non-empty must not fail marriage ----

    #[test]
    fn lifetime_relative_llbc_extra_does_not_fail_marriage_discipline() {
        // Demonstrates the core purpose of LlbcExtraCategory::LifetimeRelative.
        //
        // Setup: AST emits no atoms (trivial-true pre, trivial-true post).
        // LLBC emits one atom whose name starts with "outlives", simulating
        // the shape the C.9 lifter (#384 C.9) will emit for Outlives predicates
        // derived from borrow regions. Sort::Region does not exist yet (#401);
        // we simulate the structural shape by constructing the atom directly.
        //
        // Expected: agreement is LlbcExtra(LifetimeRelative), not a failure.
        // The marriage discipline accepts this asymmetry as by-design: AST
        // has no lifetime view. The test asserts the category is recognized
        // and does not trigger any assertion failure.
        use crate::canonical::{cid_of_value, jcs_bytes_of_value};
        use crate::contract::{build_memento_value, EffectSet, FunctionContractMemento};
        use crate::locus::Locus;
        use sugar_ir_types::Sort;

        // Construct a fake Outlives atom: Atomic("outlives:'a:'b", []).
        // This simulates what the C.9 lifter will emit once Sort::Region
        // lands in #401. The predicate name prefix "outlives" is the sole
        // discriminant used by classify_extras today.
        let outlives_atom = IrFormula::Atomic {
            name: "outlives:'a:'b".to_string(),
            args: vec![],
        };

        // AST contract: trivial-true pre and post (AST cannot see lifetimes).
        // LLBC contract: outlives predicate in pre, trivial-true post.
        let base = FunctionContractMemento {
            fn_name: "stub_lifetime".to_string(),
            formals: vec![],
            formal_sorts: vec![],
            formal_regions: vec![],
            return_sort: Sort::Primitive {
                name: "Unit".to_string(),
            },
            return_region: None,
            body_cid: None,
            effects: EffectSet::empty(),
            locus: Locus::unknown(),
            pre: atomic_true().into_formula(),
            post: atomic_true().into_formula(),
            canonical_bytes: vec![],
            cid: String::new(),
            auto_minted_mementos: vec![],
            panic_loci: vec![],
            concept_hint: None,
        };

        let ast_contract = {
            let mut c = base.clone();
            let v = build_memento_value(&c);
            c.canonical_bytes = jcs_bytes_of_value(&v);
            c.cid = cid_of_value(&v);
            c
        };

        let llbc_contract = {
            let mut c = base.clone();
            // LLBC pre carries the outlives atom; AST sees nothing.
            c.pre = outlives_atom;
            let v = build_memento_value(&c);
            c.canonical_bytes = jcs_bytes_of_value(&v);
            c.cid = cid_of_value(&v);
            c
        };

        let married = marry(ast_contract, llbc_contract);

        // The asymmetry is categorized as LifetimeRelative, not TypePrecision.
        assert_eq!(
            married.agreement,
            LayerAgreement::LlbcExtra(LlbcExtraCategory::LifetimeRelative),
            "outlives atom must be classified LifetimeRelative, not TypePrecision"
        );

        // The merged contract carries the outlives atom: no information lost.
        let merged_pre_str = serde_json::to_string(&married.merged.pre).unwrap();
        assert!(
            merged_pre_str.contains("outlives"),
            "merged pre must include the outlives atom: {}",
            merged_pre_str
        );
    }

    // ---- Sort-equality invariant: AST and LLBC paths must agree ----

    #[test]
    fn ast_and_llbc_formal_sorts_agree_on_bounds_fixture() {
        // `fn at(s: &[u32], i: usize) -> u32 { s[i] }`
        //
        // This is the canonical cross-layer sort-equality check for the
        // type-sort collapse fix (CodeRabbit #370 + #384 A.1).
        //
        // AST path (syn_type_to_sort):
        //   s: &[u32]  → Sort::Primitive { name: "Ref<Slice<U32>>" }
        //   i: usize   → Sort::Primitive { name: "Usize" }
        //   return u32 → Sort::Primitive { name: "U32" }
        //
        // LLBC path (ty_to_sort from Charon JSON):
        //   s: {"Ref": [region, {"Slice": {"Literal": {"UInt":"U32"}}}, "Shared"]}
        //      → Sort::Primitive { name: "Ref<Slice<U32>>" }
        //   i: {"Literal": {"UInt": "Usize"}}
        //      → Sort::Primitive { name: "Usize" }
        //   return: {"Literal": {"UInt": "U32"}}
        //      → Sort::Primitive { name: "U32" }
        //
        // Before the fix, both paths collapsed to Sort::Primitive { name: "Int" }
        // (the old catch-all), causing false CID collisions between functions
        // with different argument types.
        let (ast, llbc) = build_layers("bounds.rs", "bounds.llbc", "at");

        assert_eq!(
            ast.formal_sorts, llbc.formal_sorts,
            "AST and LLBC paths must agree on formal_sorts for bounds::at.\n\
             ast: {:?}\n\
             llbc: {:?}",
            ast.formal_sorts, llbc.formal_sorts
        );
        assert_eq!(
            ast.return_sort, llbc.return_sort,
            "AST and LLBC paths must agree on return_sort for bounds::at.\n\
             ast: {:?}\n\
             llbc: {:?}",
            ast.return_sort, llbc.return_sort
        );

        // Verify the actual sort values are correct (not just equal-to-each-other).
        use sugar_ir_types::Sort;
        assert_eq!(
            ast.formal_sorts,
            vec![
                // Integers canonicalize to `Int` (width is a refinement, not a
                // sort); `&[u32]` -> `Ref<Slice<Int>>`, `usize` -> `Int`.
                Sort::Primitive {
                    name: "Ref<Slice<Int>>".to_string()
                },
                Sort::Primitive {
                    name: "Int".to_string()
                },
            ],
            "formal_sorts must be [Ref<Slice<Int>>, Int]: {:?}",
            ast.formal_sorts
        );
        assert_eq!(
            ast.return_sort,
            Sort::Primitive {
                name: "Int".to_string()
            },
            "return_sort must be Int (u32 canonicalizes to Int): {:?}",
            ast.return_sort
        );
    }

    // ---- C.9 marriage hookup: Outlives + Region classification ----

    #[test]
    fn outlives_predicate_classified_as_lifetime_relative() {
        // Test 1: Outlives atomic predicate classified as LifetimeRelative.
        let outlives_atom = IrFormula::Atomic {
            name: "Outlives".to_string(),
            args: vec![
                IrTerm::Var {
                    name: "'a".to_string(),
                },
                IrTerm::Var {
                    name: "'b".to_string(),
                },
            ],
        };
        let cat = classify_extras(&[outlives_atom]);
        assert_eq!(
            cat,
            LlbcExtraCategory::LifetimeRelative,
            "Outlives predicate must be LifetimeRelative"
        );
    }

    #[test]
    fn predicate_with_region_typed_term_classified_as_lifetime_relative() {
        // Test 2: Non-Outlives predicate with a Sort::Region-tagged term
        // still classified as LifetimeRelative.
        let region_term = IrTerm::Const {
            value: serde_json::json!("'a"),
            sort: Sort::Region {
                name: "'a".to_string(),
            },
        };
        let region_atom = IrFormula::Atomic {
            name: "borrow_region".to_string(),
            args: vec![region_term],
        };
        let cat = classify_extras(&[region_atom]);
        assert_eq!(
            cat,
            LlbcExtraCategory::LifetimeRelative,
            "predicate with Region-typed term must be LifetimeRelative"
        );
    }

    #[test]
    fn non_region_predicate_uses_default_classification() {
        // Test 3: Non-region predicate uses the default TypePrecision.
        let ge_atom = IrFormula::Atomic {
            name: "\u{2265}".to_string(),
            args: vec![
                IrTerm::Var {
                    name: "x".to_string(),
                },
                IrTerm::Const {
                    value: serde_json::json!(10),
                    sort: Sort::Primitive {
                        name: "U32".to_string(),
                    },
                },
            ],
        };
        let cat = classify_extras(&[ge_atom]);
        assert_eq!(
            cat,
            LlbcExtraCategory::TypePrecision,
            "non-region predicate must default to TypePrecision"
        );
    }

    #[test]
    fn marriage_with_outlives_in_llbc_only_succeeds() {
        // Test 4: Full marriage scenario with empty AST predicates and
        // one Outlives in LLBC. Marriage succeeds with LlbcExtra(LifetimeRelative).
        use crate::canonical::{cid_of_value, jcs_bytes_of_value};
        use crate::contract::{build_memento_value, EffectSet, FunctionContractMemento};
        use crate::locus::Locus;

        let outlives_atom = IrFormula::Atomic {
            name: "Outlives".to_string(),
            args: vec![
                IrTerm::Var {
                    name: "'a".to_string(),
                },
                IrTerm::Var {
                    name: "'b".to_string(),
                },
            ],
        };

        let base = FunctionContractMemento {
            fn_name: "test_outlives_marriage".to_string(),
            formals: vec![],
            formal_sorts: vec![],
            return_sort: Sort::Primitive {
                name: "Unit".to_string(),
            },
            body_cid: None,
            effects: EffectSet::empty(),
            locus: Locus::unknown(),
            pre: atomic_true().into_formula(),
            post: atomic_true().into_formula(),
            canonical_bytes: vec![],
            cid: String::new(),
            auto_minted_mementos: vec![],
            formal_regions: vec![],
            return_region: None,
            panic_loci: vec![],
            concept_hint: None,
        };

        let ast_contract = {
            let mut c = base.clone();
            let v = build_memento_value(&c);
            c.canonical_bytes = jcs_bytes_of_value(&v);
            c.cid = cid_of_value(&v);
            c
        };

        let llbc_contract = {
            let mut c = base.clone();
            c.pre = outlives_atom;
            let v = build_memento_value(&c);
            c.canonical_bytes = jcs_bytes_of_value(&v);
            c.cid = cid_of_value(&v);
            c
        };

        let married = marry(ast_contract, llbc_contract);

        assert_eq!(
            married.agreement,
            LayerAgreement::LlbcExtra(LlbcExtraCategory::LifetimeRelative),
            "marriage with Outlives in LLBC only must succeed as LifetimeRelative"
        );

        let merged_pre_str = serde_json::to_string(&married.merged.pre).unwrap();
        assert!(
            merged_pre_str.contains("Outlives"),
            "merged pre must carry the Outlives atom: {}",
            merged_pre_str
        );
    }
}
