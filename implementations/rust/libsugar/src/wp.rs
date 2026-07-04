// SPDX-License-Identifier: MIT OR Apache-2.0
//
//! `libsugar::wp` — the weakest-precondition evaluator.
//!
//! This module is the consumer of the `wp_rule` data introduced by spec
//! `protocol/specs/2026-05-13-wp-as-formula.md`. It is the *outer*
//! structural recursion over a program term plus the per-op
//! *rule-instantiation*, with the per-op rule carried as data (an
//! `IrFormula` over the op's formals plus the reserved meta-variables `Q`
//! and `wp_<slot>`) rather than as hardcoded match-arms in each lifter.
//!
//! Three things live here:
//!
//! 1. **The substitution algebra** — capture-avoiding, single-variable
//!    substitution over `IrFormula` / `IrTerm`, plus free-variable
//!    computation. This was previously duplicated between
//!    `sugar-walk`'s `wp.rs` and `libsugar::compose`; both now
//!    consume it from here. (CCP §5: one primitive, every consumer.)
//!
//! 2. **The two grammar-node reductions** — `substitute` and `apply`
//!    (the wp-rule schema nodes, spec §2.3) reduce to the existing
//!    grammar: a `Substitute { target, var, term }` node with a ground
//!    `target` is eliminated by performing the substitution; an
//!    `Apply { fn: "wp_<slot>", args: [X] }` node is eliminated by
//!    inlining the actual slot transformer once the evaluator knows it.
//!    After `wp(t, Q)` runs with a ground `Q`, the result formula
//!    contains no `Substitute` or `Apply` nodes.
//!
//! 3. **The evaluator** (`wp`) — `wp(t, Q)` computed by structural
//!    recursion over the term `t`. For each op node: look up the op's
//!    contract; take its authored `wp_rule`, or *synthesize* one for a
//!    value-op from `pre`/`post` (`pre ∧ Q[result := value_expr]`, with
//!    `value_expr` read off the `post`'s `result == value_expr` shape);
//!    instantiate that rule with this `Q`, the recursively-computed
//!    `wp`s of `t`'s `Stmt`-typed sub-terms (substituted for the
//!    `wp_<slot>` meta-vars), and the values of `t`'s value-typed
//!    sub-terms (substituted for the formals); the result is a formula
//!    in the same IR-formula language.
//!
//!    The evaluator is **total** (it always returns a formula or a
//!    `Refusal` naming the missing memento; it never panics, never
//!    returns garbage), **deterministic** (the recursion order is fixed
//!    by the term's slot order, substitution is deterministic, rule
//!    lookup is by op name; the computed `wp` is canonicalized and
//!    content-addressed downstream, so nondeterminism would be a
//!    correctness bug), and makes **no solver call** (it produces a
//!    formula; the solver work, the refinement check of spec §3, happens
//!    later).
//!
//! ## The postcondition placeholder
//!
//! `Q` appears in a `wp_rule` *as a formula*: the spec's worked examples
//! write it `{ "kind": "var", "name": "Q" }`, but the IR formula grammar
//! has no `var` node — a propositional variable is the nullary atomic
//! predicate `Atomic { name, args: [] }` (the grammar's open-extension
//! `AtomicPredicateName = ... / tstr` covers it). So the placeholder is
//! [`postcondition_placeholder()`] = `Atomic { name: "Q", args: [] }`;
//! `reduce_formula` replaces every occurrence of that shape with the
//! actual postcondition. Likewise a control-flow rule mentions its
//! condition slot as `Atomic { name: "cond", args: [] }` (or a real
//! comparison `Atomic { name: "bop_eq", args: [..] }`, whichever the
//! lifted source is).

use std::collections::{BTreeMap, HashSet};

use sugar_ir_types::{
    AggregationStrategy, CompoundContractMemento, EvidenceMemento, IrFormula, IrTerm, LetBinding,
    LossRecord, VerdictKind,
};

use crate::core::types::{Cid, SlotSort, Term};

// ============================================================
// Reserved meta-variable names (spec §1.1).
// ============================================================

/// The reserved postcondition meta-variable name. A `wp_rule` is
/// parametric in `Q`: a formula-sorted meta-variable standing for the
/// postcondition the rule is applied to, written as the nullary atomic
/// predicate `Atomic { name: "Q", args: [] }`. The evaluator replaces
/// every occurrence of that shape with the actual postcondition.
pub const RESERVED_POSTCONDITION: &str = "Q";

/// The reserved prefix for slot-transformer meta-variables. For each
/// `Stmt`-sorted slot `s` of an op, `wp_<s>` is a function-typed
/// meta-variable standing for "the `wp` transformer of the term plugged
/// into slot `s`": `apply(wp_<s>, X)` is "the weakest precondition of
/// that sub-term with respect to X." The evaluator inlines the actual
/// slot transformer for any `apply { fn }` whose `fn` starts with this
/// prefix.
pub const SLOT_TRANSFORMER_PREFIX: &str = "wp_";

/// The reserved variable name a value-op's `post` equates with its value
/// expression (`post == (result == value_expr)`), and the variable a
/// synthesized value-op `wp_rule` substitutes into the postcondition.
/// The spec's worked examples write `result_value`; the contracts in
/// this repo write `result`. The synthesizer accepts either on the
/// `post` side and substitutes for whatever name the contract's
/// [`OpContractInfo::result_var`] declares (default `result`).
pub const DEFAULT_RESULT_VAR: &str = "result";

/// The postcondition placeholder formula: `Atomic { name: "Q", args: [] }`.
pub fn postcondition_placeholder() -> IrFormula {
    IrFormula::Atomic {
        name: RESERVED_POSTCONDITION.to_string(),
        args: vec![],
    }
}

/// True iff `f` is the postcondition placeholder shape
/// `Atomic { name: "Q", args: [] }`.
pub fn is_postcondition_placeholder(f: &IrFormula) -> bool {
    matches!(f, IrFormula::Atomic { name, args } if name == RESERVED_POSTCONDITION && args.is_empty())
}

/// Build the slot-transformer meta-variable name for a slot.
pub fn slot_transformer_name(slot_name: &str) -> String {
    format!("{SLOT_TRANSFORMER_PREFIX}{slot_name}")
}

/// True iff `name` is a slot-transformer meta-variable name (`wp_<slot>`
/// with a non-empty `<slot>`).
pub fn is_slot_transformer_name(name: &str) -> bool {
    name.starts_with(SLOT_TRANSFORMER_PREFIX) && name.len() > SLOT_TRANSFORMER_PREFIX.len()
}

// ============================================================
// Refusal — the evaluator's "I cannot compute this yet" report.
// ============================================================

/// The evaluator's principled refusal point: a term whose `wp` is not
/// yet computable because a required memento has not landed in the pool
/// (or a rule the contract carries is malformed). This is not a failure
/// of the evaluator; it is the evaluator correctly reporting that the
/// contract is not yet load-bearing, the same posture as a contract
/// carrying an `opaque_loop` / `opaque_call` effect refusing downstream
/// composition.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum Refusal {
    /// A loop op whose `wp_rule` references the loop invariant `inv`,
    /// with no matching `LoopInvariantMemento` (`loopCid == loop`) in the
    /// pool. Naming the loop CID makes the refusal precise: this is the
    /// invariant memento the pool is missing.
    #[error("wp-opaque-loop: no LoopInvariantMemento for loop {loop_cid}")]
    OpaqueLoop {
        /// The content CID of the loop term whose invariant memento is missing.
        loop_cid: Cid,
    },
    /// A call op whose callee `FunctionContractMemento` has not landed
    /// (an unresolved or indirect call), or an op the resolver does not
    /// know. `wp(call f(args), Q)` is not computable until the callee
    /// contract is in the pool.
    #[error("wp-unresolved-call: no callee contract for `{callee}`")]
    OpaqueCall {
        /// The name of the callee whose contract is missing.
        callee: String,
    },
}

// ============================================================
// Operation-contract view + resolver.
// ============================================================

/// Whether a slot of an operation is `Stmt`-typed (a sub-statement whose
/// `wp` transformer the rule composes via a `wp_<slot>` meta-variable) or
/// value-typed (a sub-expression whose value the rule substitutes for the
/// formal).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SlotKind {
    /// A value-sorted slot (`Int`, `Bool`, a user sort — anything not
    /// `Stmt`). The slot's value expression is substituted for the
    /// corresponding formal in the rule.
    Value,
    /// A `Stmt`-sorted slot. The slot's `wp` transformer is substituted
    /// for the corresponding `wp_<slot>` meta-variable in the rule.
    Stmt,
}

impl SlotKind {
    /// Map the language-signature `SlotSort` plus a statement-or-not
    /// hint onto a `SlotKind`. Only `SlotSort::Term` slots can be
    /// `Stmt`-typed; type / identifier / literal slots are never
    /// statements. (When a richer statement-vs-value distinction lands on
    /// the signature, this is the place to thread it through; for now the
    /// caller supplies the kind directly via [`SlotInfo`].)
    pub fn from_slot_sort_and_hint(slot_sort: SlotSort, is_stmt: bool) -> Self {
        match slot_sort {
            SlotSort::Term if is_stmt => SlotKind::Stmt,
            _ => SlotKind::Value,
        }
    }
}

/// One slot of an operation, as the evaluator needs to see it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SlotInfo {
    /// Canonical slot name (the `<slot>` in `wp_<slot>`).
    pub name: String,
    /// Whether the slot is `Stmt`-typed or value-typed.
    pub kind: SlotKind,
}

impl SlotInfo {
    /// A value-typed slot.
    pub fn value(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            kind: SlotKind::Value,
        }
    }
    /// A `Stmt`-typed slot.
    pub fn stmt(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            kind: SlotKind::Stmt,
        }
    }
}

/// A read-only view of an operation contract, as the evaluator consumes
/// it. `wp_rule` is authored for `Stmt`-sorted ops and absent
/// (synthesizable) for value-ops; `pre`/`post` are present for value-ops
/// so the synthesis has something to read.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpContractInfo {
    /// The op's named slots, in slot order (= the order of `Term::Op`'s
    /// `args`).
    pub slots: Vec<SlotInfo>,
    /// The op's precondition formula, if the contract carries one.
    pub pre: Option<IrFormula>,
    /// The op's postcondition formula, if the contract carries one. For
    /// a value-op this has the shape `result == value_expr`.
    pub post: Option<IrFormula>,
    /// The op's authored `wp_rule`, if present. When absent the
    /// evaluator synthesizes one from `pre`/`post` for a value-op.
    pub wp_rule: Option<IrFormula>,
    /// The variable name the `post` equates with the value expression,
    /// and the variable a synthesized rule substitutes into the
    /// postcondition. Defaults to [`DEFAULT_RESULT_VAR`].
    pub result_var: String,
    /// `Some(callee)` iff this op is an unresolved / indirect call whose
    /// callee contract has not landed. The evaluator refuses with
    /// [`Refusal::OpaqueCall`] for such ops.
    pub unresolved_call: Option<String>,
    /// `Some(loop_cid)` iff this op's `wp_rule` references a loop
    /// invariant `inv` bound by a `LoopInvariantMemento` keyed on the
    /// loop term's content CID, and no such memento is in the pool. The
    /// evaluator refuses with [`Refusal::OpaqueLoop`] naming that CID.
    /// (When the memento *is* present the resolver supplies the
    /// instantiated `wp_rule` and leaves this `None`.)
    pub opaque_loop: Option<Cid>,
}

impl OpContractInfo {
    /// A bare contract view with no `pre`/`post`/`wp_rule`, the default
    /// result-var name, and no refusal flags. A starting point for test
    /// fixtures and the catalog adapter.
    pub fn new(slots: Vec<SlotInfo>) -> Self {
        Self {
            slots,
            pre: None,
            post: None,
            wp_rule: None,
            result_var: DEFAULT_RESULT_VAR.to_string(),
            unresolved_call: None,
            opaque_loop: None,
        }
    }

    /// Find the value expression of a value-op: the right-hand side of
    /// `post == (result == value_expr)`. Returns `None` if `post` is
    /// absent or does not have a recognizable `result = ...` equation.
    pub fn value_expr(&self) -> Option<IrTerm> {
        self.post
            .as_ref()
            .and_then(|p| find_result_equation(p, &self.result_var))
    }

    /// Synthesize the value-op `wp_rule`: `pre ∧ Q[result := value_expr]`
    /// (spec §1.2). Returns `None` if the synthesis cannot proceed (no
    /// `post`, or no recognizable value expression). A `pre` that is
    /// literally `true` is dropped (`true ∧ φ = φ`).
    pub fn synthesize_value_rule(&self) -> Option<IrFormula> {
        let value_expr = self.value_expr()?;
        let subst = IrFormula::Substitute {
            target: Box::new(postcondition_placeholder()),
            term: value_expr,
            var: self.result_var.clone(),
        };
        let conj = match &self.pre {
            Some(pre) if !is_atomic_true(pre) => vec![pre.clone(), subst],
            _ => vec![subst],
        };
        Some(if conj.len() == 1 {
            conj.into_iter().next().unwrap()
        } else {
            IrFormula::And { operands: conj }
        })
    }

    /// The op's `wp_rule`: authored if present, otherwise synthesized for
    /// a value-op.
    pub fn rule(&self) -> Option<IrFormula> {
        self.wp_rule
            .clone()
            .or_else(|| self.synthesize_value_rule())
    }
}

/// Resolves an operation name to its contract view. The test fixtures
/// implement this over an in-memory map; the catalog-backed
/// implementation lands with the hub-op migration (PR2 of this
/// sub-project). The evaluator looks up by *name* (the op CID rides
/// along on the term but is not used for lookup in this PR).
pub trait OpContractResolver {
    /// Return the contract view for `op_name`, or `None` if no contract
    /// is known. A `None` is treated as an unresolved call: the
    /// evaluator refuses with [`Refusal::OpaqueCall`].
    fn lookup(&self, op_name: &str) -> Option<OpContractInfo>;
}

// ============================================================
// The evaluator.
// ============================================================

/// Errors the evaluator can return that are *not* principled refusals:
/// a contract whose slot count does not match the term's arity, or a
/// value-op contract with no synthesizable rule. These are bugs, not
/// "missing memento" situations. A principled refusal is surfaced as
/// [`WpError::Refused`].
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum WpError {
    /// The op's contract declared `expected` slots but the term supplied
    /// `actual` args.
    #[error("op `{op}`: contract declares {expected} slots but term supplies {actual} args")]
    ArityMismatch {
        /// The op name.
        op: String,
        /// The slot count the contract declares.
        expected: usize,
        /// The arg count the term supplies.
        actual: usize,
    },
    /// A value-op (no `Stmt` slots) whose contract carries neither a
    /// `wp_rule` nor a synthesizable `pre`/`post`.
    #[error("op `{op}`: value-op contract has no wp_rule and no synthesizable pre/post")]
    NoRule {
        /// The op name.
        op: String,
    },
    /// The op's `wp_rule` is malformed: it `apply`s a `wp_<slot>`
    /// meta-var for a slot the op does not have (or that was classified
    /// value-typed), or `apply`s something that is not a slot
    /// transformer at all.
    #[error(
        "op `{op}`: wp_rule applies `{fn_name}`, which is not a Stmt-slot transformer of this op"
    )]
    MalformedRule {
        /// The op name.
        op: String,
        /// The `fn` the rule tried to apply.
        fn_name: String,
    },
    /// The evaluator's principled refusal (a missing memento). Surfaced
    /// through the same `Result` so callers handle one error type; match
    /// on this variant to distinguish "not a bug, just not yet
    /// load-bearing" from the others.
    #[error(transparent)]
    Refused(#[from] Refusal),
    /// The compound's `aggregation_strategy` is spec'd but not implemented
    /// in v0. Only `Conjunction` is wired; `BestConfidence`,
    /// `LoudlyBoundedDisjunction`, and `Other` return this error.
    #[error("aggregation strategy `{strategy}` is spec'd but not implemented in v0")]
    UnimplementedAggregationStrategy {
        /// The wire-format string of the strategy that was encountered.
        strategy: String,
    },
}

/// Compute `wp(t, Q)` — the weakest precondition of term `t` with
/// respect to postcondition formula `Q` — by structural recursion over
/// `t`, using `resolver` to look up each op's contract.
///
/// On success the returned formula contains no `Substitute` / `Apply`
/// schema nodes (they have all been reduced once `Q` is known). On a
/// missing memento it returns `Err(WpError::Refused(..))` naming what is
/// missing; on a malformed contract / rule it returns the other
/// `WpError` variants. It never panics.
pub fn wp<R: OpContractResolver + ?Sized>(
    t: &Term,
    q: &IrFormula,
    resolver: &R,
) -> Result<IrFormula, WpError> {
    wp_with_result_var(t, q, resolver, DEFAULT_RESULT_VAR)
}

/// Like [`wp`] but with an explicit "result" variable name for the leaf
/// cases (`var` / `const` substitute the leaf's value into `Q` for this
/// variable). Op nodes use the per-contract `result_var`.
pub fn wp_with_result_var<R: OpContractResolver + ?Sized>(
    t: &Term,
    q: &IrFormula,
    resolver: &R,
    result_var: &str,
) -> Result<IrFormula, WpError> {
    match t {
        // Leaf: substitute the value of the leaf into `Q`.
        Term::Var { name } => Ok(substitute_in_formula(
            q.clone(),
            result_var,
            &IrTerm::Var { name: name.clone() },
        )),
        Term::Const { value, sort } => Ok(substitute_in_formula(
            q.clone(),
            result_var,
            &IrTerm::Const {
                value: value.clone(),
                sort: sort.clone(),
            },
        )),
        // `unit` carries no value; `wp(unit, Q) = Q` (the postcondition
        // is unchanged — there is nothing to substitute).
        Term::Unit => Ok(q.clone()),
        // Op: look up the contract, take or synthesize its `wp_rule`,
        // instantiate it.
        Term::Op { name, args, .. } => wp_op(name, args, q, resolver),
    }
}

fn wp_op<R: OpContractResolver + ?Sized>(
    op_name: &str,
    args: &[Term],
    q: &IrFormula,
    resolver: &R,
) -> Result<IrFormula, WpError> {
    let Some(contract) = resolver.lookup(op_name) else {
        // Unknown op — treat as an unresolved call (the principled
        // refusal posture; spec §2.1, §6).
        return Err(Refusal::OpaqueCall {
            callee: op_name.to_string(),
        }
        .into());
    };

    // Principled refusals first.
    if let Some(callee) = &contract.unresolved_call {
        return Err(Refusal::OpaqueCall {
            callee: callee.clone(),
        }
        .into());
    }
    if let Some(loop_cid) = &contract.opaque_loop {
        return Err(Refusal::OpaqueLoop {
            loop_cid: loop_cid.clone(),
        }
        .into());
    }

    if contract.slots.len() != args.len() {
        return Err(WpError::ArityMismatch {
            op: op_name.to_string(),
            expected: contract.slots.len(),
            actual: args.len(),
        });
    }

    let rule = contract.rule().ok_or_else(|| WpError::NoRule {
        op: op_name.to_string(),
    })?;

    // Bind the slots: `Stmt`-typed slots become slot transformers (a
    // sub-term recursed via the evaluator), value-typed slots become
    // formal ↦ value-expression substitutions. The recursion bottoms out
    // at value-ops (no `Stmt` slots) and at leaves, so it terminates on
    // every finite term — and a loop op does not recurse "into the loop
    // forever": its rule references the invariant memento, supplied (or
    // refused) by the resolver, not a sub-term.
    let mut stmt_transformers: Vec<(String, &Term)> = Vec::new();
    let mut value_substs: Vec<(String, IrTerm)> = Vec::new();
    for (slot, arg) in contract.slots.iter().zip(args) {
        match slot.kind {
            SlotKind::Stmt => stmt_transformers.push((slot.name.clone(), arg)),
            SlotKind::Value => {
                value_substs.push((slot.name.clone(), value_expr_of_term(arg, resolver)?));
            }
        }
    }

    // Instantiate the rule:
    //   1. substitute the value-slot expressions for the formals,
    //   2. reduce: replace the postcondition placeholder with `q`,
    //      perform every `substitute` whose target is now ground, and
    //      inline every `apply(wp_<slot>, X)` by recursing into the
    //      slot's sub-term with `X`.
    let mut instantiated = rule;
    for (formal, value) in &value_substs {
        instantiated = substitute_in_formula(instantiated, formal, value);
    }
    reduce_formula(instantiated, q, &stmt_transformers, op_name, resolver)
}

/// Read the value expression a sub-term evaluates to, for substitution
/// into a value-slot formal. A `var` is itself; a `const` is itself; an
/// `op` whose contract is a value-op is its value expression (with the
/// op's own value-slot args substituted in recursively), or the bare
/// constructor `op(name, <recursed args>)` when the contract carries no
/// usable `post`; a `unit` is the `unit` constructor.
///
/// `pub` so that `sugar-verifier`'s body-discharge spine can reduce
/// nested-call terms in the NESTED-CALL tier (reduce-in-place). Treat
/// this as verifier-internal infrastructure, not a stable public API.
pub fn value_expr_of_term<R: OpContractResolver + ?Sized>(
    t: &Term,
    resolver: &R,
) -> Result<IrTerm, WpError> {
    match t {
        Term::Var { name } => Ok(IrTerm::Var { name: name.clone() }),
        Term::Const { value, sort } => Ok(IrTerm::Const {
            value: value.clone(),
            sort: sort.clone(),
        }),
        Term::Unit => Ok(IrTerm::Ctor {
            name: "unit".to_string(),
            args: vec![],
        }),
        Term::Op { name, args, .. } => {
            let Some(contract) = resolver.lookup(name) else {
                // No contract for this nested op. This is NOT a refusal in
                // value position: an enum/struct constructor (`Ok`, `Err`,
                // `Some`), a `format!`/`json!` macro term, a field
                // projection (`field`), a method (`method:foo`), or a call
                // whose callee has no contract is a perfectly good
                // UNINTERPRETED value. Keep it as the bare constructor
                // `op(name, <recursed args>)`. The verifier's SMT lowering
                // declares it as an uninterpreted function symbol, so a
                // self-derived post `result == Ok(<...>)` against a body
                // returning `Ok(<...>)` reduces to `Ok(..) == Ok(..)` and
                // discharges by reflexivity. Refusing here is what forced
                // every `Ok(macro!)`-shaped body-bearing obligation to
                // `wp-unresolved-call` undecidable instead of a sound
                // reflexive discharge.
                let recursed_args = args
                    .iter()
                    .map(|a| value_expr_of_term(a, resolver))
                    .collect::<Result<Vec<_>, _>>()?;
                return Ok(IrTerm::Ctor {
                    name: name.clone(),
                    args: recursed_args,
                });
            };
            if let Some(callee) = &contract.unresolved_call {
                // The contract EXISTS but is explicitly marked an
                // unresolved call (the lifter could not resolve the callee
                // at lift time). Honor that as a principled refusal: unlike
                // the no-contract case above, the lifter asserted this op is
                // unresolved, which is a different claim than "uninterpreted
                // constructor."
                return Err(Refusal::OpaqueCall {
                    callee: callee.clone(),
                }
                .into());
            }
            if contract.slots.len() != args.len() {
                return Err(WpError::ArityMismatch {
                    op: name.clone(),
                    expected: contract.slots.len(),
                    actual: args.len(),
                });
            }
            let mut formal_substs: Vec<(String, IrTerm)> = Vec::new();
            let mut recursed_args: Vec<IrTerm> = Vec::with_capacity(args.len());
            for (slot, arg) in contract.slots.iter().zip(args) {
                let v = value_expr_of_term(arg, resolver)?;
                if slot.kind == SlotKind::Value {
                    formal_substs.push((slot.name.clone(), v.clone()));
                }
                recursed_args.push(v);
            }
            match contract.value_expr() {
                Some(mut expr) => {
                    for (formal, value) in &formal_substs {
                        expr = substitute_in_term(expr, formal, value);
                    }
                    Ok(expr)
                }
                None => Ok(IrTerm::Ctor {
                    name: name.clone(),
                    args: recursed_args,
                }),
            }
        }
    }
}

// ============================================================
// Schema-node reduction: eliminate `substitute` / `apply`.
// ============================================================

/// Reduce a `wp_rule` formula to a normal `IrFormula`, given the actual
/// postcondition `q` (which the placeholder `Atomic { name: "Q",
/// args: [] }` stands for) and the `Stmt`-slot transformers (`wp_<slot>`
/// ↦ the sub-term in that slot, recursed with the supplied argument).
///
/// After this returns, the formula contains no `Substitute` / `Apply`
/// nodes and no postcondition placeholder: every `substitute` whose
/// target is ground has been performed, every `apply(wp_<slot>, X)` has
/// been replaced by `wp(slot_term, X)` (recursing through the
/// evaluator), and every `Atomic { name: "Q", args: [] }` has become
/// `q`.
fn reduce_formula<R: OpContractResolver + ?Sized>(
    f: IrFormula,
    q: &IrFormula,
    stmt_transformers: &[(String, &Term)],
    op_name: &str,
    resolver: &R,
) -> Result<IrFormula, WpError> {
    if is_postcondition_placeholder(&f) {
        // The postcondition placeholder `Atomic { name: "Q", args: [] }`.
        return Ok(q.clone());
    }
    match f {
        // A genuine atomic predicate (its term args cannot contain schema
        // nodes — those are formula-level — so it passes through
        // unchanged).
        a @ IrFormula::Atomic { .. } => Ok(a),
        IrFormula::And { operands } => Ok(IrFormula::And {
            operands: reduce_each(operands, q, stmt_transformers, op_name, resolver)?,
        }),
        IrFormula::Or { operands } => Ok(IrFormula::Or {
            operands: reduce_each(operands, q, stmt_transformers, op_name, resolver)?,
        }),
        IrFormula::Not { operands } => Ok(IrFormula::Not {
            operands: reduce_each(operands, q, stmt_transformers, op_name, resolver)?,
        }),
        IrFormula::Implies { operands } => Ok(IrFormula::Implies {
            operands: reduce_each(operands, q, stmt_transformers, op_name, resolver)?,
        }),
        IrFormula::Forall { name, sort, body } => Ok(IrFormula::Forall {
            name,
            sort,
            body: Box::new(reduce_formula(
                *body,
                q,
                stmt_transformers,
                op_name,
                resolver,
            )?),
        }),
        IrFormula::Exists { name, sort, body } => Ok(IrFormula::Exists {
            name,
            sort,
            body: Box::new(reduce_formula(
                *body,
                q,
                stmt_transformers,
                op_name,
                resolver,
            )?),
        }),
        IrFormula::Choice {
            var_name,
            sort,
            body,
        } => Ok(IrFormula::Choice {
            var_name,
            sort,
            body: Box::new(reduce_formula(
                *body,
                q,
                stmt_transformers,
                op_name,
                resolver,
            )?),
        }),
        // `substitute { target, var, term }` — reduce the target first
        // (so the postcondition placeholder becomes `q` and any nested
        // `apply` is inlined), then perform the capture-avoiding
        // substitution of `term` for `var`.
        IrFormula::Substitute { target, term, var } => {
            let reduced_target = reduce_formula(*target, q, stmt_transformers, op_name, resolver)?;
            Ok(substitute_in_formula(reduced_target, &var, &term))
        }
        // `apply { fn: "wp_<slot>", args: [X] }` — inline the actual
        // slot transformer: recurse into the slot's sub-term with the
        // (reduced) argument `X` as the postcondition.
        IrFormula::Apply { args, r#fn } => {
            if !is_slot_transformer_name(&r#fn) {
                return Err(WpError::MalformedRule {
                    op: op_name.to_string(),
                    fn_name: r#fn,
                });
            }
            let slot_name = &r#fn[SLOT_TRANSFORMER_PREFIX.len()..];
            let Some((_, slot_term)) = stmt_transformers.iter().find(|(n, _)| n == slot_name)
            else {
                return Err(WpError::MalformedRule {
                    op: op_name.to_string(),
                    fn_name: r#fn,
                });
            };
            let arg = match args.into_iter().next() {
                Some(a) => reduce_formula(a, q, stmt_transformers, op_name, resolver)?,
                None => q.clone(),
            };
            wp(slot_term, &arg, resolver)
        }
        IrFormula::DivergenceBetween { source, target } => Ok(IrFormula::DivergenceBetween {
            source: Box::new(reduce_formula(
                *source,
                q,
                stmt_transformers,
                op_name,
                resolver,
            )?),
            target: Box::new(reduce_formula(
                *target,
                q,
                stmt_transformers,
                op_name,
                resolver,
            )?),
        }),
    }
}

fn reduce_each<R: OpContractResolver + ?Sized>(
    operands: Vec<IrFormula>,
    q: &IrFormula,
    stmt_transformers: &[(String, &Term)],
    op_name: &str,
    resolver: &R,
) -> Result<Vec<IrFormula>, WpError> {
    operands
        .into_iter()
        .map(|o| reduce_formula(o, q, stmt_transformers, op_name, resolver))
        .collect()
}

// ============================================================
// `result == value_expr` extraction (shared with `compose`).
// ============================================================

/// Find the term-side of `var_name = <expr>` (in either argument order)
/// inside a conjunction-or-atomic formula. This is how a value-op's
/// `post == (result == value_expr)` yields `value_expr`.
pub fn find_result_equation(formula: &IrFormula, var_name: &str) -> Option<IrTerm> {
    match formula {
        IrFormula::Atomic { name, args } if name == "=" && args.len() == 2 => {
            if let IrTerm::Var { name: n } = &args[0] {
                if n == var_name {
                    return Some(args[1].clone());
                }
            }
            if let IrTerm::Var { name: n } = &args[1] {
                if n == var_name {
                    return Some(args[0].clone());
                }
            }
            None
        }
        IrFormula::And { operands } => operands
            .iter()
            .find_map(|f| find_result_equation(f, var_name)),
        _ => None,
    }
}

fn is_atomic_true(f: &IrFormula) -> bool {
    matches!(f, IrFormula::Atomic { name, args } if name == "true" && args.is_empty())
}

// ============================================================
// Substitution algebra (capture-avoiding) over IrFormula / IrTerm.
//
// Single canonical home. `sugar-walk`'s `wp.rs` re-exports these;
// `libsugar::compose` imports them. (Previously duplicated in both;
// CCP §5: one primitive, every consumer.)
// ============================================================

/// Substitute `replacement` for every free occurrence of
/// `Var { name == var_name }` in `formula`. Capture-avoiding: a binder
/// whose bound name appears free in `replacement` is alpha-renamed to a
/// fresh name before the substitution proceeds; a binder that rebinds
/// `var_name` shadows it (substitution stops at the binder).
///
/// Note on the schema nodes: `substitute` and `apply` are *not* binders
/// over the surrounding scope (`substitute`'s `var` is a substitution
/// operator's bound name; `apply`'s `fn` is a meta-var name), so
/// term-substitution passes straight through them — they keep their
/// shape and their sub-parts are substituted into. (`reduce_formula` is
/// what eliminates these nodes; this function only moves a *term* into a
/// formula's leaves.) The postcondition placeholder
/// `Atomic { name: "Q", args: [] }` has no term args and is therefore
/// unaffected by term-substitution, which is correct: a value-slot value
/// must not be substituted *into* the postcondition until the rule is
/// applied to a concrete `Q`.
pub fn substitute_in_formula(
    formula: IrFormula,
    var_name: &str,
    replacement: &IrTerm,
) -> IrFormula {
    match formula {
        IrFormula::Atomic { name, args } => IrFormula::Atomic {
            name,
            args: args
                .into_iter()
                .map(|t| substitute_in_term(t, var_name, replacement))
                .collect(),
        },
        IrFormula::And { operands } => IrFormula::And {
            operands: operands
                .into_iter()
                .map(|f| substitute_in_formula(f, var_name, replacement))
                .collect(),
        },
        IrFormula::Or { operands } => IrFormula::Or {
            operands: operands
                .into_iter()
                .map(|f| substitute_in_formula(f, var_name, replacement))
                .collect(),
        },
        IrFormula::Not { operands } => IrFormula::Not {
            operands: operands
                .into_iter()
                .map(|f| substitute_in_formula(f, var_name, replacement))
                .collect(),
        },
        IrFormula::Implies { operands } => IrFormula::Implies {
            operands: operands
                .into_iter()
                .map(|f| substitute_in_formula(f, var_name, replacement))
                .collect(),
        },
        IrFormula::Forall { name, sort, body } => {
            let (name, body) = handle_formula_binder(name, body, var_name, replacement);
            IrFormula::Forall { name, sort, body }
        }
        IrFormula::Exists { name, sort, body } => {
            let (name, body) = handle_formula_binder(name, body, var_name, replacement);
            IrFormula::Exists { name, sort, body }
        }
        IrFormula::Choice {
            var_name: bound,
            sort,
            body,
        } => {
            let (bound, body) = handle_formula_binder(bound, body, var_name, replacement);
            IrFormula::Choice {
                var_name: bound,
                sort,
                body,
            }
        }
        IrFormula::Substitute { target, term, var } => IrFormula::Substitute {
            target: Box::new(substitute_in_formula(*target, var_name, replacement)),
            term: substitute_in_term(term, var_name, replacement),
            var,
        },
        IrFormula::Apply { args, r#fn } => IrFormula::Apply {
            args: args
                .into_iter()
                .map(|f| substitute_in_formula(f, var_name, replacement))
                .collect(),
            r#fn,
        },
        IrFormula::DivergenceBetween { source, target } => IrFormula::DivergenceBetween {
            source: Box::new(substitute_in_formula(*source, var_name, replacement)),
            target: Box::new(substitute_in_formula(*target, var_name, replacement)),
        },
    }
}

/// Common alpha-rename + substitute logic for `Forall` / `Exists` /
/// `Choice`. Returns the (possibly-renamed) bound name and the body with
/// the substitution applied.
fn handle_formula_binder(
    bound: String,
    body: Box<IrFormula>,
    var_name: &str,
    replacement: &IrTerm,
) -> (String, Box<IrFormula>) {
    if bound == var_name {
        // Shadowing: the binder rebinds `var_name`; do not substitute under it.
        return (bound, body);
    }
    let replacement_free = free_vars_term(replacement);
    if replacement_free.contains(&bound) {
        // Capture risk: alpha-rename `bound` to a fresh name first.
        let mut taken = replacement_free;
        taken.extend(free_vars_formula(&body));
        taken.insert(var_name.to_string());
        taken.insert(bound.clone());
        let fresh = fresh_name(&taken, &bound);
        let renamed = substitute_in_formula(
            *body,
            &bound,
            &IrTerm::Var {
                name: fresh.clone(),
            },
        );
        let substituted = substitute_in_formula(renamed, var_name, replacement);
        (fresh, Box::new(substituted))
    } else {
        let body_subst = substitute_in_formula(*body, var_name, replacement);
        (bound, Box::new(body_subst))
    }
}

/// Substitute `replacement` for every free occurrence of
/// `Var { name == var_name }` in `term`. Capture-avoiding over `Lambda`
/// / `Let` binders.
pub fn substitute_in_term(term: IrTerm, var_name: &str, replacement: &IrTerm) -> IrTerm {
    match term {
        IrTerm::Var { name } => {
            if name == var_name {
                replacement.clone()
            } else {
                IrTerm::Var { name }
            }
        }
        IrTerm::Const { value, sort } => IrTerm::Const { value, sort },
        IrTerm::Ctor { name, args } => IrTerm::Ctor {
            name,
            args: args
                .into_iter()
                .map(|t| substitute_in_term(t, var_name, replacement))
                .collect(),
        },
        IrTerm::Lambda {
            param_name,
            param_sort,
            body,
        } => {
            if param_name == var_name {
                // Shadowing: stop substitution at this binder.
                IrTerm::Lambda {
                    param_name,
                    param_sort,
                    body,
                }
            } else {
                let replacement_free = free_vars_term(replacement);
                if replacement_free.contains(&param_name) {
                    // Capture risk: alpha-rename `param_name` to fresh first.
                    let mut taken = replacement_free;
                    taken.extend(free_vars_term(&body));
                    taken.insert(var_name.to_string());
                    taken.insert(param_name.clone());
                    let fresh = fresh_name(&taken, &param_name);
                    let renamed = substitute_in_term(
                        *body,
                        &param_name,
                        &IrTerm::Var {
                            name: fresh.clone(),
                        },
                    );
                    let substituted = substitute_in_term(renamed, var_name, replacement);
                    IrTerm::Lambda {
                        param_name: fresh,
                        param_sort,
                        body: Box::new(substituted),
                    }
                } else {
                    let body = Box::new(substitute_in_term(*body, var_name, replacement));
                    IrTerm::Lambda {
                        param_name,
                        param_sort,
                        body,
                    }
                }
            }
        }
        IrTerm::Let { bindings, body } => {
            // Sequential let with capture-avoidance: each binding's
            // bound_term sees prior bindings (and the var_name →
            // replacement substitution until shadowed). When a binding's
            // name appears free in `replacement`, alpha-rename that
            // binding's name to fresh and propagate the rename to
            // subsequent bound_terms and the body.
            let replacement_free = free_vars_term(replacement);
            let mut new_bindings: Vec<LetBinding> = Vec::with_capacity(bindings.len());
            let mut shadowed = false;
            let mut prior_renames: Vec<(String, IrTerm)> = Vec::new();

            for b in bindings.into_iter() {
                // Apply prior alpha-renames first; these are pure renames
                // and capture-free by construction (fresh names were
                // chosen to avoid every name in scope).
                let mut bound_term = b.bound_term;
                for (old, new) in &prior_renames {
                    bound_term = substitute_in_term(bound_term, old, new);
                }
                let bound_term = if shadowed {
                    bound_term
                } else {
                    substitute_in_term(bound_term, var_name, replacement)
                };

                let new_name = if b.name == var_name {
                    // Shadowing: this binder rebinds `var_name`; stop
                    // downstream subst.
                    shadowed = true;
                    b.name
                } else if !shadowed && replacement_free.contains(&b.name) {
                    // Capture risk on this binder: alpha-rename to fresh.
                    let mut taken = replacement_free.clone();
                    taken.insert(var_name.to_string());
                    taken.insert(b.name.clone());
                    for existing in &new_bindings {
                        taken.insert(existing.name.clone());
                    }
                    let fresh = fresh_name(&taken, &b.name);
                    prior_renames.push((
                        b.name.clone(),
                        IrTerm::Var {
                            name: fresh.clone(),
                        },
                    ));
                    fresh
                } else {
                    b.name
                };
                new_bindings.push(LetBinding {
                    name: new_name,
                    bound_term,
                });
            }

            let mut body = *body;
            for (old, new) in &prior_renames {
                body = substitute_in_term(body, old, new);
            }
            let body = if shadowed {
                body
            } else {
                substitute_in_term(body, var_name, replacement)
            };

            IrTerm::Let {
                bindings: new_bindings,
                body: Box::new(body),
            }
        }
    }
}

// ============================================================
// Free-variable computation.
// ============================================================

/// Free variables of an `IrTerm` (those not bound by an enclosing
/// `Lambda` or `Let` binder). Sequential `Let` semantics: each binding's
/// bound term sees only the bindings strictly to its left.
pub fn free_vars_term(t: &IrTerm) -> HashSet<String> {
    let mut acc = HashSet::new();
    free_vars_term_into(t, &mut acc);
    acc
}

fn free_vars_term_into(t: &IrTerm, acc: &mut HashSet<String>) {
    match t {
        IrTerm::Var { name } => {
            acc.insert(name.clone());
        }
        IrTerm::Const { .. } => {}
        IrTerm::Ctor { args, .. } => {
            for a in args {
                free_vars_term_into(a, acc);
            }
        }
        IrTerm::Lambda {
            param_name, body, ..
        } => {
            let mut inner = HashSet::new();
            free_vars_term_into(body, &mut inner);
            inner.remove(param_name);
            acc.extend(inner);
        }
        IrTerm::Let { bindings, body } => {
            // Sequential semantics: bindings[i] sees names bound by bindings[0..i].
            let mut bound_so_far: HashSet<String> = HashSet::new();
            for b in bindings {
                let mut bf = HashSet::new();
                free_vars_term_into(&b.bound_term, &mut bf);
                for name in &bound_so_far {
                    bf.remove(name);
                }
                acc.extend(bf);
                bound_so_far.insert(b.name.clone());
            }
            let mut bf = HashSet::new();
            free_vars_term_into(body, &mut bf);
            for name in &bound_so_far {
                bf.remove(name);
            }
            acc.extend(bf);
        }
    }
}

/// Free variables of an `IrFormula`. The schema nodes contribute the
/// free variables of their sub-parts; `substitute`'s `var` is a
/// substitution operator's bound name (not a free variable of the
/// surrounding scope) and `apply`'s `fn` is a meta-var name (likewise),
/// so neither is collected.
pub fn free_vars_formula(f: &IrFormula) -> HashSet<String> {
    let mut acc = HashSet::new();
    free_vars_formula_into(f, &mut acc);
    acc
}

fn free_vars_formula_into(f: &IrFormula, acc: &mut HashSet<String>) {
    match f {
        IrFormula::Atomic { args, .. } => {
            for a in args {
                free_vars_term_into(a, acc);
            }
        }
        IrFormula::And { operands }
        | IrFormula::Or { operands }
        | IrFormula::Not { operands }
        | IrFormula::Implies { operands } => {
            for o in operands {
                free_vars_formula_into(o, acc);
            }
        }
        IrFormula::Forall { name, body, .. } | IrFormula::Exists { name, body, .. } => {
            let mut inner = HashSet::new();
            free_vars_formula_into(body, &mut inner);
            inner.remove(name);
            acc.extend(inner);
        }
        IrFormula::Choice { var_name, body, .. } => {
            let mut inner = HashSet::new();
            free_vars_formula_into(body, &mut inner);
            inner.remove(var_name);
            acc.extend(inner);
        }
        IrFormula::Substitute { target, term, .. } => {
            free_vars_formula_into(target, acc);
            free_vars_term_into(term, acc);
        }
        IrFormula::Apply { args, .. } => {
            for a in args {
                free_vars_formula_into(a, acc);
            }
        }
        IrFormula::DivergenceBetween { source, target } => {
            free_vars_formula_into(source, acc);
            free_vars_formula_into(target, acc);
        }
    }
}

/// Pick a name not in `taken`, biased toward `base` when available.
/// Append `_1`, `_2`, … to disambiguate.
fn fresh_name(taken: &HashSet<String>, base: &str) -> String {
    if !taken.contains(base) {
        return base.to_string();
    }
    let mut n: u32 = 1;
    loop {
        let candidate = format!("{}_{}", base, n);
        if !taken.contains(&candidate) {
            return candidate;
        }
        n += 1;
    }
}

// ============================================================
// Compound-aware discharge (PR-F of #716).
// ============================================================

/// The verdict for one `EvidenceMemento` within a compound discharge.
///
/// Derived by running `wp(target_term, evidence.predicate, resolver)`:
///
/// - `Ok(formula)` where `formula == evidence.predicate` → `Exact`
/// - `Ok(formula)` where `formula != evidence.predicate` → `LoudlyBoundedLossy`
///   (structural divergence: wp produced a formula, but it differs from
///   the evidence's asserted predicate)
/// - `Err(WpError::Refused(_))` → `Refuse`
/// - `Err(other)` → propagated as `Err`; the caller sees a hard error, not
///   a verdict (this is a contract bug, not a "no memento" situation)
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EvidenceVerdict {
    /// The `EvidenceMemento.cid` of the evidence this verdict covers.
    pub evidence_cid: String,
    /// Per-evidence trichotomy verdict.
    pub verdict: VerdictKind,
    /// Non-empty iff `verdict == LoudlyBoundedLossy`. Key
    /// `"structural_divergence"` maps to the formula wp actually produced
    /// when it differed from the evidence predicate.
    pub loss_record: LossRecord,
}

/// The compound discharge report returned by [`wp_compound`].
///
/// Spec: `protocol/specs/2026-05-13-compound-contract-memento.md` §2.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CompoundDischargeReport {
    /// The `CompoundContractMemento.cid` of the compound that was discharged.
    pub compound_cid: String,
    /// Per-evidence verdict, one entry per `EvidenceMemento` passed in.
    pub per_evidence_verdicts: Vec<EvidenceVerdict>,
    /// Compound-level trichotomy verdict derived from per-evidence verdicts
    /// under `compound.aggregation_strategy` (§2.1).
    pub compound_verdict: VerdictKind,
    /// Union of per-evidence loss records for `LoudlyBoundedLossy` evidences.
    /// Empty when `compound_verdict == Exact`.
    pub composed_loss_record: LossRecord,
}

/// Discharge a `CompoundContractMemento` against `target_term`.
///
/// For each evidence in `evidences`, runs `wp(target_term, evidence.predicate,
/// resolver)` and derives a per-evidence [`EvidenceVerdict`]. Then aggregates
/// under `compound.aggregation_strategy` to produce the compound verdict.
///
/// # Evidence resolution
///
/// The caller is responsible for pre-resolving `CompoundContractMemento.evidences`
/// (a `Vec<EvidenceRef>`, CIDs only) to full `EvidenceMemento` bytes before
/// calling this function. The order of `evidences` need not match the order of
/// `compound.evidences`; CIDs are used only for reporting.
///
/// # Aggregation strategies (v0)
///
/// Only `AggregationStrategy::Conjunction` is wired. Encountering
/// `BestConfidence`, `LoudlyBoundedDisjunction`, or `Other` returns
/// `Err(WpError::UnimplementedAggregationStrategy)` without panicking.
///
/// # Empty compounds (§5.2)
///
/// A compound with zero evidences is vacuously exact: compound verdict is
/// `Exact`, composed loss record is empty.
///
/// # Hard errors vs verdicts
///
/// A per-evidence `wp` that returns `Err(WpError::Refused(_))` becomes a
/// `Refuse` verdict for that evidence. Any other `WpError` is a contract
/// bug and is propagated as `Err` to the caller (not converted to a verdict).
pub fn wp_compound(
    compound: &CompoundContractMemento,
    target_term: &Term,
    evidences: &[EvidenceMemento],
    resolver: &dyn OpContractResolver,
) -> Result<CompoundDischargeReport, WpError> {
    // Guard: only Conjunction is wired in v0.
    match &compound.aggregation_strategy {
        AggregationStrategy::Conjunction => {}
        other => {
            return Err(WpError::UnimplementedAggregationStrategy {
                strategy: String::from(other.clone()),
            });
        }
    }

    // Per-evidence discharge.
    let mut per_evidence_verdicts: Vec<EvidenceVerdict> = Vec::with_capacity(evidences.len());

    for evidence in evidences {
        let ev = discharge_one_evidence(evidence, target_term, resolver)?;
        per_evidence_verdicts.push(ev);
    }

    // Conjunction aggregation (spec §2.1).
    let (compound_verdict, composed_loss_record) = aggregate_conjunction(&per_evidence_verdicts);

    Ok(CompoundDischargeReport {
        compound_cid: compound.cid.clone(),
        per_evidence_verdicts,
        compound_verdict,
        composed_loss_record,
    })
}

/// Run wp for one evidence and return an `EvidenceVerdict`.
///
/// - `Err(WpError::Refused)` → `Refuse` verdict (principled refusal, not a bug).
/// - `Err(other)` → propagated (contract bug; the caller surfaces it).
/// - `Ok(formula) == evidence.predicate` → `Exact`.
/// - `Ok(formula) != evidence.predicate` → `LoudlyBoundedLossy`.
fn discharge_one_evidence(
    evidence: &EvidenceMemento,
    target_term: &Term,
    resolver: &dyn OpContractResolver,
) -> Result<EvidenceVerdict, WpError> {
    match wp(target_term, &evidence.predicate, resolver) {
        Err(WpError::Refused(_)) => Ok(EvidenceVerdict {
            evidence_cid: evidence.cid.clone(),
            verdict: VerdictKind::Refuse,
            loss_record: LossRecord(BTreeMap::new()),
        }),
        Err(other) => Err(other),
        Ok(computed) => {
            if computed == evidence.predicate {
                Ok(EvidenceVerdict {
                    evidence_cid: evidence.cid.clone(),
                    verdict: VerdictKind::Exact,
                    loss_record: LossRecord(BTreeMap::new()),
                })
            } else {
                // Structural divergence: wp succeeded but result differs.
                let mut loss = BTreeMap::new();
                loss.insert("structural_divergence".to_string(), computed);
                Ok(EvidenceVerdict {
                    evidence_cid: evidence.cid.clone(),
                    verdict: VerdictKind::LoudlyBoundedLossy,
                    loss_record: LossRecord(loss),
                })
            }
        }
    }
}

/// Conjunction aggregation rule (spec §2.1):
///
/// - all `Exact` → `Exact`
/// - any `Refuse` → `Refuse` (regardless of other verdicts)
/// - otherwise → `LoudlyBoundedLossy`, union of per-evidence loss records
///
/// Returns `(compound_verdict, composed_loss_record)`.
pub(crate) fn aggregate_conjunction(verdicts: &[EvidenceVerdict]) -> (VerdictKind, LossRecord) {
    // Empty compound: vacuously exact (spec §5.2).
    if verdicts.is_empty() {
        return (VerdictKind::Exact, LossRecord(BTreeMap::new()));
    }

    let has_refuse = verdicts.iter().any(|v| v.verdict == VerdictKind::Refuse);
    let has_lossy = verdicts
        .iter()
        .any(|v| v.verdict == VerdictKind::LoudlyBoundedLossy);
    let all_exact = verdicts.iter().all(|v| v.verdict == VerdictKind::Exact);

    if has_refuse {
        // Any refuse makes the compound refuse; loss record is empty (refuse has no loss).
        return (VerdictKind::Refuse, LossRecord(BTreeMap::new()));
    }

    if all_exact {
        return (VerdictKind::Exact, LossRecord(BTreeMap::new()));
    }

    // has_lossy (and no refuse): compose loss records.
    // Spec §2.1: "per-dimension union of each loudly-bounded-lossy evidence's
    // loss-record". Union under the same dimension key is the logical AND of
    // the per-evidence formulas: both divergence constraints must hold.
    debug_assert!(has_lossy);
    let mut composed: BTreeMap<String, IrFormula> = BTreeMap::new();
    for v in verdicts {
        if v.verdict == VerdictKind::LoudlyBoundedLossy {
            for (k, formula) in &v.loss_record.0 {
                match composed.get(k) {
                    None => {
                        composed.insert(k.clone(), formula.clone());
                    }
                    Some(existing) => {
                        let combined = IrFormula::And {
                            operands: vec![existing.clone(), formula.clone()],
                        };
                        composed.insert(k.clone(), combined);
                    }
                }
            }
        }
    }
    (VerdictKind::LoudlyBoundedLossy, LossRecord(composed))
}

#[cfg(test)]
mod tests;
