// SPDX-License-Identifier: Apache-2.0
//
// sugar-ir-symbolic: Rust kit. Mirrors the C++ kit at
// implementations/cpp/sugar-ir-symbolic/include/sugar/ir.hpp.
//
// Maximal-uniformity IR per protocol/specs/2026-04-30-ir-formal-grammar.md
// (catalog v1.1.0). Every node has `kind`, then `name` (when applicable),
// then payload. Five formula kinds (atomic / and / or / not / implies /
// forall / exists, the four connectives sharing one struct), three term
// kinds (var / const / ctor).
//
// Authoring surface:
//
//   contract(name, ContractArgs { pre, post, inv, out_binding? })
//   must(name, precondition)            -- alias for contract(.., {pre})
//   forall(sort, |v| body) / exists(sort, |v| body)
//   and_(vec![..]), or_(vec![..]), not_(a), implies(a, b)
//   eq, ne, gt, gte, lt, lte            -- atomic predicates
//   num, real_const, str_const, parse_int -- term primitives
//   out()                               -- references the post return value
//
// We use `Rc` (not `Box`) for formula and term nodes; sub-trees are
// shared between primitives (e.g. `out()` reused in two atomics) and
// the kit's authoring style returns owned smart pointers.

use std::cell::RefCell;
use std::rc::Rc;
use std::sync::Arc;

use sugar_canonicalizer::Value;

pub mod convert;
pub mod parse;
pub mod parse_expr;
pub mod serialize;

// Re-export serde types so consumers can use both authoring API and
// generated compiler types from a single import.
pub use sugar_ir_types as ir_types;

// ---------------------------------------------------------------------------
// Sort
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Sort {
    pub name: String, // "Int" / "Real" / "String" / "Bool"
}

impl Sort {
    pub fn int() -> Self {
        Self { name: "Int".into() }
    }
    pub fn real() -> Self {
        Self {
            name: "Real".into(),
        }
    }
    pub fn string() -> Self {
        Self {
            name: "String".into(),
        }
    }
    pub fn bool() -> Self {
        Self {
            name: "Bool".into(),
        }
    }
}

#[allow(non_snake_case)]
pub fn Int() -> Sort {
    Sort::int()
}
#[allow(non_snake_case)]
pub fn Real() -> Sort {
    Sort::real()
}
#[allow(non_snake_case)]
pub fn String_() -> Sort {
    Sort::string()
}
#[allow(non_snake_case)]
pub fn Bool() -> Sort {
    Sort::bool()
}

// ---------------------------------------------------------------------------
// Term: VarTerm (no sort), ConstTerm (sort kept), CtorTerm (no sort)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub enum ConstValue {
    // i128 carrier: a wide Rust literal (u64::MAX, u128 within i128 range,
    // large isize) is an EXACT mathematical-Int constant. The FOL/SMT `Int`
    // sort is unbounded, so the literal IS its exact integer value -- there is
    // no "too large" for anything representable in i128. Values beyond i128
    // range are refused upstream ("number too large"), an honest BAIL.
    Int(i128),
    Real(String),
    String(String),
    Bool(bool),
}

#[derive(Debug, Clone)]
pub enum Term {
    Var {
        name: String,
    },
    Const {
        value: ConstValue,
        sort: Sort,
    },
    Ctor {
        name: String,
        args: Vec<Rc<Term>>,
    },
    Lambda {
        param_name: String,
        param_sort: Sort,
        body: Rc<Term>,
    },
    Let {
        bindings: Vec<LetBinding>,
        body: Rc<Term>,
    },
}

#[derive(Debug, Clone)]
pub struct LetBinding {
    pub name: String,
    pub bound_term: Rc<Term>,
}

pub fn make_var<S: Into<String>>(name: S) -> Rc<Term> {
    Rc::new(Term::Var { name: name.into() })
}

pub fn num(value: i128) -> Rc<Term> {
    Rc::new(Term::Const {
        value: ConstValue::Int(value),
        sort: Sort::int(),
    })
}

pub fn real_const<S: Into<String>>(value: S) -> Rc<Term> {
    Rc::new(Term::Const {
        value: ConstValue::Real(value.into()),
        sort: Sort::real(),
    })
}

pub fn str_const<S: Into<String>>(value: S) -> Rc<Term> {
    Rc::new(Term::Const {
        value: ConstValue::String(value.into()),
        sort: Sort::string(),
    })
}

/// `out()` references the return value within a post formula. Compiles
/// to a VarTerm whose name matches the enclosing contract's outBinding
/// (default "out").
pub fn out() -> Rc<Term> {
    make_var("out")
}

/// `parse_int(s)`: bridge primitive. Registers with the bridge
/// registry on first call (process-local). Returns a CtorTerm.
pub fn parse_int(s: Rc<Term>) -> Rc<Term> {
    ensure_kit_bridges_registered();
    Rc::new(Term::Ctor {
        name: "parseInt".into(),
        args: vec![s],
    })
}

// ---------------------------------------------------------------------------
// Formula: three kinds: atomic / connective / quantifier
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub enum Formula {
    Atomic {
        name: String,
        args: Vec<Rc<Term>>,
    },
    Connective {
        kind: String, // "and" / "or" / "not" / "implies"
        operands: Vec<Rc<Formula>>,
    },
    Quantifier {
        kind: String, // "forall" / "exists"
        name: String,
        sort: Sort,
        body: Rc<Formula>,
    },
    Choice {
        var_name: String,
        sort: Sort,
        body: Rc<Formula>,
    },
}

pub fn atomic_<S: Into<String>>(name: S, args: Vec<Rc<Term>>) -> Rc<Formula> {
    Rc::new(Formula::Atomic {
        name: name.into(),
        args,
    })
}

pub fn gt(a: Rc<Term>, b: Rc<Term>) -> Rc<Formula> {
    atomic_(">", vec![a, b])
}
pub fn gte(a: Rc<Term>, b: Rc<Term>) -> Rc<Formula> {
    atomic_("\u{2265}", vec![a, b])
}
pub fn lt(a: Rc<Term>, b: Rc<Term>) -> Rc<Formula> {
    atomic_("<", vec![a, b])
}
pub fn lte(a: Rc<Term>, b: Rc<Term>) -> Rc<Formula> {
    atomic_("\u{2264}", vec![a, b])
}
pub fn eq(a: Rc<Term>, b: Rc<Term>) -> Rc<Formula> {
    atomic_("=", vec![a, b])
}
pub fn ne(a: Rc<Term>, b: Rc<Term>) -> Rc<Formula> {
    atomic_("\u{2260}", vec![a, b])
}

pub fn connective_<S: Into<String>>(kind: S, operands: Vec<Rc<Formula>>) -> Rc<Formula> {
    Rc::new(Formula::Connective {
        kind: kind.into(),
        operands,
    })
}
pub fn not_(a: Rc<Formula>) -> Rc<Formula> {
    connective_("not", vec![a])
}
pub fn implies(antecedent: Rc<Formula>, consequent: Rc<Formula>) -> Rc<Formula> {
    connective_("implies", vec![antecedent, consequent])
}
pub fn and_(operands: Vec<Rc<Formula>>) -> Rc<Formula> {
    connective_("and", operands)
}
pub fn or_(operands: Vec<Rc<Formula>>) -> Rc<Formula> {
    connective_("or", operands)
}

// ---------------------------------------------------------------------------
// Quantifier counter: fresh names for bound variables
// ---------------------------------------------------------------------------

thread_local! {
    static QUANTIFIER_COUNTER: RefCell<i32> = const { RefCell::new(0) };
}

pub fn fresh_var_name() -> String {
    QUANTIFIER_COUNTER.with(|c| {
        let mut n = c.borrow_mut();
        let v = *n;
        *n = v + 1;
        format!("_x{v}")
    })
}

pub fn reset_collector() {
    QUANTIFIER_COUNTER.with(|c| *c.borrow_mut() = 0);
    CONTRACT_COLLECTOR.with(|c| c.borrow_mut().clear());
    BRIDGE_COLLECTOR.with(|c| c.borrow_mut().clear());
}

pub fn forall<F>(sort: Sort, body: F) -> Rc<Formula>
where
    F: FnOnce(Rc<Term>) -> Rc<Formula>,
{
    let vname = fresh_var_name();
    let var = make_var(&vname);
    let inner = body(var);
    Rc::new(Formula::Quantifier {
        kind: "forall".into(),
        name: vname,
        sort,
        body: inner,
    })
}

pub fn exists<F>(sort: Sort, body: F) -> Rc<Formula>
where
    F: FnOnce(Rc<Term>) -> Rc<Formula>,
{
    let vname = fresh_var_name();
    let var = make_var(&vname);
    let inner = body(var);
    Rc::new(Formula::Quantifier {
        kind: "exists".into(),
        name: vname,
        sort,
        body: inner,
    })
}

// ---------------------------------------------------------------------------
// Lambda terms (first-class functions)
// ---------------------------------------------------------------------------

pub fn lambda(param_name: String, param_sort: Sort, body: Rc<Term>) -> Rc<Term> {
    Rc::new(Term::Lambda {
        param_name,
        param_sort,
        body,
    })
}

// ---------------------------------------------------------------------------
// Let terms (local bindings)
// ---------------------------------------------------------------------------

pub fn let_term(bindings: Vec<LetBinding>, body: Rc<Term>) -> Rc<Term> {
    Rc::new(Term::Let { bindings, body })
}

// ---------------------------------------------------------------------------
// Choice formula (definite description)
// ---------------------------------------------------------------------------

pub fn choice<F>(var_name: String, sort: Sort, body: F) -> Rc<Formula>
where
    F: FnOnce(Rc<Term>) -> Rc<Formula>,
{
    let var = make_var(&var_name);
    let inner = body(var);
    Rc::new(Formula::Choice {
        var_name,
        sort,
        body: inner,
    })
}

// ---------------------------------------------------------------------------
// Evidence
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EvidenceCertificate {
    pub tool: String,
    pub version: String,
    pub formula_hash: String,
    pub proof_data: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EvidenceTerm {
    pub proof_type: String, // "smt-lib" | "coq" | "custom"
    pub certificate: EvidenceCertificate,
}

// ---------------------------------------------------------------------------
// Contract collector
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Default)]
pub struct ContractArgs {
    pub pre: Option<Rc<Formula>>,
    pub post: Option<Rc<Formula>>,
    pub inv: Option<Rc<Formula>>,
    pub out_binding: Option<String>,
    pub evidence: Option<EvidenceTerm>,
    pub panic_loci: Vec<Arc<Value>>,
}

#[derive(Debug, Clone)]
pub struct ContractDecl {
    pub name: String,
    pub pre: Option<Rc<Formula>>,
    pub post: Option<Rc<Formula>>,
    pub inv: Option<Rc<Formula>>,
    pub out_binding: String,
    pub evidence: Option<EvidenceTerm>,
    /// Header-only panic provenance carried through minting as opaque
    /// canonical JSON. The verifier reads it to attribute panic obligations,
    /// but it does not participate in contract CID derivation.
    pub panic_loci: Vec<Arc<Value>>,
    /// Human-supplied concept name extracted from a `// concept: <name>` (or
    /// `/// concept: <name>`) annotation immediately preceding the function.
    ///
    /// - `None`  -- no annotation found
    /// - `Some("UNNAMED-CONCEPT-N")` -- placeholder emitted by the substrate
    /// - `Some("<real-name>")` -- human-supplied name ready for catalog binding
    ///
    /// This field is METADATA ONLY.  It does NOT participate in the
    /// canonical-bytes / CID derivation.  Changing the annotation never
    /// rewrites the shape identity.
    pub concept_hint: Option<String>,
}

thread_local! {
    static CONTRACT_COLLECTOR: RefCell<Vec<ContractDecl>> = const { RefCell::new(Vec::new()) };
}

pub fn begin_collecting() {
    CONTRACT_COLLECTOR.with(|c| c.borrow_mut().clear());
}

pub fn contract<S: Into<String>>(name: S, args: ContractArgs) {
    if args.pre.is_none() && args.post.is_none() && args.inv.is_none() {
        // Validate at mint time and fail loud, per Sir's instruction.
        panic!(
            "contract: at least one of pre/post/inv must be non-null (name was {})",
            name.into()
        );
    }
    CONTRACT_COLLECTOR.with(|c| {
        c.borrow_mut().push(ContractDecl {
            name: name.into(),
            pre: args.pre,
            post: args.post,
            inv: args.inv,
            out_binding: args.out_binding.unwrap_or_else(|| "out".into()),
            evidence: args.evidence,
            panic_loci: args.panic_loci,
            concept_hint: None,
        });
    });
}

/// Precondition-only convenience alias.
pub fn must<S: Into<String>>(name: S, precondition: Rc<Formula>) {
    contract(
        name,
        ContractArgs {
            pre: Some(precondition),
            ..Default::default()
        },
    )
}

pub fn finish() -> Vec<ContractDecl> {
    CONTRACT_COLLECTOR.with(|c| std::mem::take(&mut *c.borrow_mut()))
}

// ---------------------------------------------------------------------------
// Bridge declaration collector + registry (process-local)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct BridgeDecl {
    pub source_symbol: String,
    pub source_layer: String,
    pub target_contract_name: String,
    pub target_layer: String,
    pub ir_arg_sorts: Vec<String>,
    pub ir_return_sort: String,
    pub notes: String,
}

thread_local! {
    static BRIDGE_COLLECTOR: RefCell<Vec<BridgeDecl>> = const { RefCell::new(Vec::new()) };
    static BRIDGE_REGISTERED_DEFAULTS: RefCell<bool> = const { RefCell::new(false) };
}

pub fn bridge_decl(d: BridgeDecl) {
    BRIDGE_COLLECTOR.with(|c| c.borrow_mut().push(d));
}

pub fn finish_bridges() -> Vec<BridgeDecl> {
    BRIDGE_COLLECTOR.with(|c| std::mem::take(&mut *c.borrow_mut()))
}

pub fn ensure_kit_bridges_registered() {
    BRIDGE_REGISTERED_DEFAULTS.with(|done| {
        let mut d = done.borrow_mut();
        if *d {
            return;
        }
        *d = true;
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn must_pushes_into_collector() {
        reset_collector();
        must("parseInt", forall(Int(), |n| gt(n, num(0))));
        let decls = finish();
        assert_eq!(decls.len(), 1);
        assert_eq!(decls[0].name, "parseInt");
        assert!(decls[0].pre.is_some());
        assert_eq!(decls[0].out_binding, "out");
    }

    #[test]
    #[should_panic]
    fn empty_contract_panics() {
        reset_collector();
        contract("noop", ContractArgs::default());
    }
}
