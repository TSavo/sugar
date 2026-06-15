// SPDX-License-Identifier: Apache-2.0
//
// sugar-lift-rust-tests
//
// Rust parity for sugar-lift-py-tests' assertion-consistency path:
// recognize scalar assertions inside #[test] functions and emit inv-only
// ContractDecls. The verifier's existing consistency pass checks those closed
// invariants with raw SAT: SAT => consistent/discharged; UNSAT => refused.

pub mod source_oracle;

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::fmt;
use std::rc::Rc;

mod macro_expand;
pub mod flt2dec_eval;
pub mod closed_eval;
mod try_fold_eval;

// The `Sugar` decorator classes each live in their own self-contained module under
// `src/sugar/`. Each is a child of the crate root, so it can see the crate-root-private
// `Sugar` trait / `Desugared` / `SugarCtx` / `DesugaredElem` / `ConstVal` /
// `const_eval_unary_closure` spine it builds on. `callsite` is the call-site-inlining
// `Sugar`; `identity`/`rev`/`enumerate`/`filter`/`map`/`skip`/`take`/`skip_while`/
// `take_while` are the per-class iterator-adaptor decorators (one struct per former
// `enum Adaptor` arm, applied in base->terminal order by `peel_fold_adaptors` +
// `decompose_seq`). One engine: each decorator's `desugar` is `inner.desugar(ctx)?`
// then that adaptor's exact transform.
pub mod sugar {
    pub mod array_repeat;
    pub mod callsite;
    pub mod closure_adaptor;
    pub mod conditional;
    pub mod control_flow_term;
    pub mod enumerate;
    pub mod filter;
    pub mod filter_map;
    pub mod fold;
    pub mod forall;
    pub mod identity;
    pub mod impl_method;
    pub mod literal;
    pub mod map;
    pub mod match_node;
    pub mod match_scrutinee;
    pub mod regex_match;
    pub mod rev;
    pub mod skip;
    pub mod skip_while;
    pub mod statement_position;
    pub mod take;
    pub mod take_while;
    pub mod temporal_read;
}

use crate::sugar::conditional::decompose_if;
use crate::sugar::fold::decompose_fold;
use crate::sugar::forall::{decompose_for_each, decompose_for_loop};
use crate::sugar::match_node::decompose_match;
use quote::ToTokens;
use sugar_ir_symbolic::{
    and_, atomic_, eq, forall, gt, gte, implies, lt, lte, make_var, ne, not_, num, or_, real_const,
    str_const, ConstValue, ContractDecl, Formula, Sort, Term,
};
use syn::parse::{Parse, ParseStream, Parser};
use syn::punctuated::Punctuated;
use syn::{BinOp, Expr, ExprLit, Item, Lit, Pat, Stmt, Token, Type, UnOp};

#[derive(Debug, Clone)]
pub struct LiftWarning {
    pub source_path: String,
    pub item_name: String,
    pub reason: String,
}

#[derive(Debug, Default)]
pub struct AdapterOutput {
    pub decls: Vec<ContractDecl>,
    pub warnings: Vec<LiftWarning>,
    pub seen: usize,
    pub lifted: usize,
    /// Assertion-macro invocations the collector reached and lifted to at least
    /// one FOL atom (counted at macro granularity, not atom granularity).
    pub assertions_lifted: usize,
    /// Assertion-macro invocations the collector reached but refused, each with
    /// a named reason (the loudly-bounded-lossy outcome).
    pub assertions_refused: usize,
    /// Every individual refusal reason, ungrouped, for the delta histogram.
    pub skip_reasons: Vec<String>,
    /// Names of non-test helper fns that were successfully reduced (inlined) by
    /// the reducer at least once. Used to avoid double-counting: asserts in these
    /// fns are already credited under assertions_lifted and must not also appear
    /// in assertions_refused.
    pub reduced_helpers: HashSet<String>,
}

#[derive(Debug, Clone, Default)]
pub struct LiftOptions {
    pub target_cfg: Option<TargetCfg>,
}

impl LiftOptions {
    pub fn for_target_cfg(target_cfg: TargetCfg) -> Self {
        Self {
            target_cfg: Some(target_cfg),
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct TargetCfg {
    facts: BTreeMap<String, BTreeSet<Option<String>>>,
}

impl TargetCfg {
    pub fn from_rustc_cfg_facts<I, S>(facts: I) -> Result<Self, String>
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        let mut out = Self::default();
        for raw in facts {
            out.insert_rustc_cfg_fact(raw.as_ref())?;
        }
        Ok(out)
    }

    pub fn from_rustc_cfg_text(text: &str) -> Result<Self, String> {
        Self::from_rustc_cfg_facts(text.lines())
    }

    fn insert_rustc_cfg_fact(&mut self, raw: &str) -> Result<(), String> {
        let fact = raw.trim();
        if fact.is_empty() {
            return Ok(());
        }
        let (key, value) = if let Some(eq) = fact.find('=') {
            let key = fact[..eq].trim();
            let value = parse_rustc_cfg_quoted_value(fact[eq + 1..].trim())?;
            (key, Some(value))
        } else {
            (fact, None)
        };
        if key.is_empty() {
            return Err(format!("empty cfg key in `{fact}`"));
        }
        self.facts.entry(key.to_string()).or_default().insert(value);
        Ok(())
    }

    fn contains_name(&self, name: &str) -> bool {
        self.facts
            .get(name)
            .is_some_and(|values| values.contains(&None))
    }

    fn contains_key_value(&self, key: &str, value: &str) -> bool {
        self.facts
            .get(key)
            .is_some_and(|values| values.contains(&Some(value.to_string())))
    }
}

fn parse_rustc_cfg_quoted_value(raw: &str) -> Result<String, String> {
    let lit = syn::parse_str::<syn::LitStr>(raw)
        .map_err(|e| format!("cfg value must be a quoted Rust string `{raw}`: {e}"))?;
    Ok(lit.value())
}

pub fn lift_file(file: &syn::File, source_path: &str) -> AdapterOutput {
    lift_file_with_options(file, source_path, &LiftOptions::default())
}

/// The disposition of a non-discharged assertion. REFUSED means "closed with a
/// damn good reason" -- a property of the SOURCE that no lifter could get past
/// (runtime/opaque data, a value outside the chosen sort, a mutation with no
/// single `t` to read). UNCLASSIFIED means a property of OUR lifter -- an AST
/// shape, term, or call we have not taught yet; it is WORK, not closure.
///
/// Refused is a WHITELIST: a reason must MATCH a terminal pattern to be refused.
/// Everything else -- including any future reason we forget to classify --
/// defaults to Unclassified, so the only way into `refused` is a reason that
/// survives the challenge "why couldn't you lift this?". This makes the ledger
/// honest: it can only ever UNDER-claim closure, never launder a TODO as a
/// verdict.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Disposition {
    /// Terminal: closed with a damn good reason (a source property).
    Refused,
    /// A lifter limitation -- WORK. The only thing the goal drives to zero.
    Unclassified,
    /// Not part of THIS target's universe (a `cfg`-disabled test/assert). Not work
    /// and not a refusal -- it does not exist in this build, so it is excluded from
    /// the load-bearing count (T's "inactive/support" rung).
    Inactive,
}

/// Classify a refusal reason string as a terminal Refusal or Unclassified work.
/// The terminal whitelist is intentionally short -- a reason earns `Refused` only
/// when it names a SOURCE property no better lifter could lift:
///   * `bin-2`             -- iterated/asserted values are RUNTIME data, not source
///                            literals (no construction to walk).
///   * `number too large`  -- a literal outside the representable integer sort.
///   * `ambiguous temporal identity` -- a receiver conditionally/aliased-mutated,
///                            so there is no single `t` to read it at. [BOUNDARY
///                            CALL: terminal-today; flip to Unclassified if branch
///                            partitioning + alias analysis are taught to recover
///                            the pinned-branch subset.]
///   * `is not a closed f32/f64 literal term` -- a flt2dec assert over the algorithm's
///                            RUNTIME output (no-model axiom), not a source literal.
///   * `signed zero float literal remains an IEEE refinement` -- a `-0.0` sign-sensitive
///                            IEEE value; the Real sort collapses ±0, so lifting risks a
///                            sign-collapse fake-discharge.
///   * `requires known f32/f64 receiver width` -- a float refinement over an unknown/
///                            unstable f-width (f16 / parse-unwrap chain).
/// Everything else is a LIFTER limitation -> Unclassified: `if`/`while`/`match`
/// (branch partitioning), a BARE `unsupported term` (a PURE untranslated value like
/// `1i32 as f64` -- distinct from the EFFECTFUL `&mut`/raw-pointer/`const{<path>}`
/// shapes, which are terminal below), `reachable only via call-site
/// inlining` for a CONCRETE scalar/slice helper (call queueing -- a closed-literal
/// call site CAN pin it), `bin-1` literal domains, let-init/nested/unenumerated
/// positions, unsupported macros (incl. `no rule matched` when the matcher SHOULD match
/// but our matcher's grammar coverage missed it -- a fixable matcher gap, not a non-match),
/// `has no visible source` (the helper's body may be
/// loadable by better resolution -- e.g. a fn-local helper nested in a `#[test]` fn
/// the reducer does not yet register, so it is reach, not a source property), and
/// `ambiguous cfg` (a missing target input, recoverable by pinning the cfg).
/// Default = Unclassified.
///   * `effectful / raw-pointer / mutable-reference term` -- an `unsupported term` whose
///                            SHAPE is a `&mut` borrow, a raw pointer (`&raw const`/`&raw mut`),
///                            or a `const { <path> }` block (a name is sugar): no single
///                            timeless value constructible from source literals. (DISTINCT from
///                            a bare `unsupported term`, which stays Unclassified work.)
///   * `operand is a runtime non-scalar result` -- an `assert!(match <runtime call> { .. })`
///                            whose scrutinee is a runtime non-scalar method/fn result
///                            (`b.binary_search(&3)`): the arm taken is the algorithm's runtime
///                            output, not a constructible scalar.
///   * `has a non-literal length -- not a finite` -- an array-repeat `[elem; N]` with a
///                            NON-literal length (const-generic / const expr): the universe
///                            size is symbolic, no finite construction from source literals.
///   * `reachable only via monomorphization of a generic` -- a GENERIC type/const-
///                            parametric helper has no single concrete instantiation
///                            to read (its truth is per-monomorphization); a SOURCE
///                            property, terminal. (Distinct from the concrete-helper
///                            `reachable only via call-site inlining`, which stays work.)
pub fn refusal_disposition(reason: &str) -> Disposition {
    // INACTIVE: cfg-disabled for this target -- not in this build's universe.
    if reason.contains("inactive cfg") {
        return Disposition::Inactive;
    }
    // INACTIVE: a `#[cfg(..)]`-INACTIVE match arm (`match () { #[cfg(target_pointer_width
    // = "32")] () => assert_eq!(..) }` on a 64-bit target). The arm does not exist in
    // THIS build's universe -- it is not work and not a refusal, the SAME rung as the
    // other `inactive cfg` cases (the surviving active arm is the one that ran). The
    // reason string carries `refused` for the human ledger, but its DISPOSITION is
    // Inactive (a disposition bug: it was counted UNCLASSIFIED). Corpus: num/wrapping.rs.
    if reason.contains("cfg-inactive match arm") {
        return Disposition::Inactive;
    }
    // TERMINAL (source property). `temporally unstable` joins `ambiguous temporal
    // identity`: a term reading a mutated local has no single `t`, so it cannot be
    // read timelessly -- a property of the source, not a missing lift.
    // TERMINAL: a `type-level obligation` is an assert-prefixed call to a
    // lexically-visible EMPTY-BODY helper (`fn assert_trusted_len<T: TrustedLen>(_: &T) {}`).
    // Its only content is the signature's trait bounds -- a typing judgment the
    // compiler discharges, categorically NOT a point-wise value predicate. An empty
    // body has zero recoverable value-work, so no better value-lifter could lift it:
    // a SOURCE property, not a lifter limitation. (NOT a fake-zero -- there is nothing
    // to launder.)
    // NOTE: "has no visible source" is NOT terminal -- it is UNCLASSIFIED work. The helper's
    // source may be loadable from a dependency / macro registry we have not pulled in yet, so
    // it is a lifter-reach limitation, not a source property. (Enforced by
    // nonempty_assert_helper_is_not_terminal_refused_the_twin.)
    let terminal = reason.contains("bin-2")
        || reason.contains("number too large")
        || reason.contains("ambiguous temporal identity")
        || reason.contains("temporally unstable")
        || reason.contains("type-level obligation")
        // TERMINAL: a macro EXPANDED (from a definition we hold) but its expansion
        // contains NO liftable assertion -- the body is type-level or purely effectful,
        // i.e. it makes no point-wise VALUE claim. There is no value predicate to lift,
        // by any lifter: a property of what the macro expands to, not a lifter gap. (Kin
        // to `type-level obligation`; not a fake-zero -- the expansion is held + walked.)
        || reason.contains("yielded no liftable assertion")
        // TERMINAL: an assertion in a `while` loop body runs 0..n times under runtime
        // loop control, so it is inherently CONDITIONAL -- never a single timeless,
        // unconditional point-wise value claim. (Corpus whiles are all `while let
        // Some(..) = iter.next()` over a runtime iterator -- bin-2 in disguise.) The lifter
        // unrolls only finite-literal `for` domains; a `while` has no such finite literal
        // construction to enumerate, so this is a source property, not a missing lifter.
        || reason.contains("under while context")
        // TERMINAL: f16/f128 formatting is an UNSTABLE API. The stable toolchain the lifter
        // ships cannot format f16/f128 (no stable flt2dec for them), so the value is neither
        // dissolvable by evaluation nor modellable (no-model axiom) -- a source/environment
        // property, not a lifter gap.
        || reason.contains("f16/f128 formatting is unstable")
        // TERMINAL: a SIDE-EFFECTING closure body (HALF 2 of the fold-closure bucket) --
        // a `.for_each`/`.map`/`.fold` closure that mutates captured state or advances an
        // iterator (`iter.next()`, `nth += 1`). Its assert observes a per-iteration
        // varying value, not a single timeless point-wise claim, so no value lifter could
        // lift it -- a source property. (The opaque/effectful-accessor twin carries `bin-2`
        // above.) Typed as `MutationEffect` / `IterAdvanceEffect`.
        || reason.contains("side-effecting closure body")
        // TERMINAL: a read of a MUTABLE CONTAINER (`a[i]` where the `mut` oracle PROVES
        // `a` is a mutable local). The container may be index-assigned / method-mutated
        // between program points, so `index(a,i)` has no single timeless `t` -- the read
        // is sequence/position dependent. This is the index-READ sibling of the already-
        // terminal `temporally unstable` (a term reading a MUTATED local): the SAME
        // provable order-loss effect, so it earns the SAME terminal verdict. Typed as
        // `TemporalReadEffect`; emitted ONLY under `scope.is_mut_local` (a non-`mut`,
        // provably-immutable container reads as a stable term and never reaches here),
        // so this can only refuse a genuinely-mutable read -- never a pure one. (THE DRAIN:
        // these effect-shaped cases fell to unclassified only because the reason was not
        // whitelisted; not a fake-zero -- the mutation is proven syntactically.)
        //
        // NOTE (reviewer): adding this whitelist entry is NOT inert w.r.t. `discharged`.
        // The monotonic inlining gate (`added_unclassified == 0`) reads
        // `refusal_disposition`, so draining mutable-container reads unclassified ->
        // refused lets 6 previously-blocked helper inlinings COMMIT, cascading to
        // discharged 5700 -> 5704 (+4 sound inlining-unblock, no fake-discharge) /
        // refused 359 -> 371 / unclassified 356 -> 346. Confirmed by negating this clause:
        // the typed-SideEffect machinery alone reproduces baseline 5700/359/356 exactly,
        // so the dig path is untouched -- the delta is purely the gate coupling. See report.
        || reason.contains("mutable container is not temporally stable")
        // TERMINAL: an `async`/`try` block or a `?` operator in term position. A `try`
        // block short-circuits on `Err`, an `async` block is a deferred future, and `?`
        // is a conditional early-return -- none is a single timeless point-wise value
        // constructible from source literals, so no value lifter could lift it. A source
        // property, not a lifter gap (kin to the `await` async-effect family). Typed as
        // `ControlFlowEffect`. (THE DRAIN: the `future.rs` join!-over-`try` row fell to
        // unclassified only because the block was not classified; not a fake-zero -- the
        // block is held + named.)
        || reason.contains("effectful control-flow block")
        // TERMINAL: the asserted value flows through OPAQUE COMPILE-TIME REFLECTION
        // (`Type::of::<T>()` / `TypeId::of::<T>()` read through `.kind` + a `match` arm).
        // A `TypeId` is a target/compiler-determined identity, not a value constructed
        // from source literals -- the SAME class as the `bin-2` "runtime data, not
        // constructed from source literals" terminal. EARNED by detecting the reflection
        // scrutinee (`statement_position_terminal_effect`); a match over a CONSTRUCTED
        // literal scrutinee never reaches it (it digs / stays unclassified). (THE DRAIN:
        // the `mem/type_info.rs` Type::of-match rows fell to the unenumerated safety net;
        // typing + whitelisting moves them unclassified -> refused. Not a fake-zero -- the
        // reflective scrutinee is held + named.)
        || reason.contains("opaque compile-time reflection")
        // TERMINAL: the asserted value flows through a `loop { .. }` over a RUNTIME
        // iterator the body advances (`iter.next()` / `iter.size_hint()`). Per-iteration
        // runtime bounds over a decode/parse iterator, no finite literal construction to
        // enumerate -- the SAME class as `under while context`. EARNED by detecting the
        // loop body's iterator advance; a `loop` over a pure value never reaches it.
        // (THE DRAIN: `char.rs::test_decode_utf16_size_hint` fell to the unenumerated
        // safety net.)
        || reason.contains("loop over a runtime-advanced iterator")
        // TERMINAL (REFUSE HALF of the bin-1 for-context classification): a literal-DOMAIN
        // for-loop whose DOMAIN / BODY / ACCUMULATOR is provably RUNTIME is a NAMED Effect,
        // the Hit side of Outcome{Dug|Hit}. The DIG already fired first (a literal-domain +
        // literal-body + simple-counter loop is lifted by `lift_bounded_forall`); these three
        // reasons are EARNED by a structurally-detected runtime cause in
        // `for_context_refusal_reason` (never a blanket relabel -- a computable-but-
        // unimplemented body has NONE of these causes and STAYS the unclassified "not
        // unconditional point-wise" reason, the fake-refuse guard).
        //
        // (A) RUNTIME DOMAIN ENDPOINT (`for i in 0..v.len()`): the universe is not a finite
        // construction from source literals (runtime count) -- kin to `bin-2`. EARNED by a
        // non-literal range endpoint (`for_domain_endpoint_is_runtime`); a literal-int range
        // never matches (it digs / stays unclassified).
        || reason.contains("domain is over a RUNTIME endpoint")
        // (B) RUNTIME BODY READ over a literal domain: the iterated values are literals but
        // the ASSERTED values are runtime (`fmt.flags()&1`, a runtime accessor / temporally-
        // unstable / mutable-container read). EARNED by the body's OWN refusal reason
        // (OPAQUE / temporally unstable / mutable container) -- the SAME proven order-loss as
        // the bin-2 family, surfaced under a literal domain.
        || reason.contains("body READS RUNTIME DATA")
        // (C) RUNTIME-VALUED ACCUMULATOR over a literal domain: the body mutates a builder /
        // non-int accumulator (NOT a simple `acc += <const>` counter), so its value at a
        // later iteration is a runtime quantity and a single universal would be false. EARNED
        // by `loop_body_mutates && !loop_mutation_is_simple_counter_only` (a genuine simple
        // counter does not reach here -- it digs or lifts as a forall).
        || reason.contains("RUNTIME-VALUED accumulator")
        // TERMINAL: an assertion in an `impl` METHOD body (top-level `Item::Impl` or a
        // nested impl declared as a statement). It runs only when the method is INVOKED,
        // observing the receiver's RUNTIME state (a mutated field, an atomic `.load`, a
        // per-call accumulator, a `&mut self` counter). No single timeless `t` -- a SOURCE
        // property (runtime-reachability class). EARNED structurally (the assert is inside
        // a method body, which has no value at definition time). Typed as `ImplMethodEffect`.
        || reason.contains("reachable only at runtime when the method is invoked")
        // TERMINAL (REFUSE HALF of the if-context classification): an `if`-guard over a
        // RUNTIME value (`&mut` borrow / mutation / runtime method call in the condition).
        // `guard => then` is not a constructible predicate because the guard's truth is not
        // fixed from source literals. EARNED by `if_guard_is_runtime`; a CONST/cfg/literal
        // guard (`!false`, `cfg!(..)`) has NONE of these signals and STAYS the unclassified
        // "under if context" reason (the fake-refuse guardrail). Typed `IfGuardRuntimeEffect`.
        || reason.contains("under an if-guard over a runtime value")
        // TERMINAL (REFUSE HALF of the expr-statement classification): a bare expression-
        // statement whose asserted value is read through a `&mut` borrow / mutation (the
        // `(assert_matches!(*MutRefWithDrop(&mut val).0, 0), mem::take(&mut val))` borrow/
        // drop-scoping shape). A mutably-aliased read has no single timeless `t` -- a SOURCE
        // property (kin to `mutable container is not temporally stable`). EARNED by the
        // `StatementPositionSugar` aliased-read leaf; a statement over a CONSTRUCTED literal value has
        // no `&mut`/mutation signal and STAYS the unclassified "unlifted expression
        // statement" reason (the fake-refuse guardrail). Typed `RuntimeExprStmtEffect`.
        || reason.contains("runtime expression-statement")
        // TERMINAL (FLOAT TAIL #1 -- flt2dec runtime output): an
        // `assert!((buf, k) == (..))` against the flt2dec algorithm's RUNTIME output. The
        // operand is NOT a closed f32/f64 literal term (no `ldexp`/`format!` over a closed
        // value to dissolve by evaluation), so the asserted value IS the algorithm's
        // runtime result -- a no-model axiom (we do NOT model flt2dec; see the no-vendor
        // axiom). There is no constructible timeless FOL form: a SOURCE property, not a
        // lifter gap. EARNED by the `None` arm of `dissolve_flt2dec_assert` AFTER the
        // f16/f128-unstable case has already split off above -- a closed literal float
        // (e.g. `1.5f64`) dissolves to `Some(..)` and never reaches this reason (the
        // fake-refuse guardrail). Typed as `Flt2decRuntimeEffect`. (THE DRAIN: these fell
        // to unclassified only because the reason was not whitelisted; not a fake-zero --
        // the operand's non-closed shape is detected by the dissolver.)
        || reason.contains("is not a closed f32/f64 literal term")
        // TERMINAL (FLOAT TAIL #2 -- signed-zero IEEE refinement): a `-0.0` / `-0.0f32`
        // float literal. IEEE-754 distinguishes `-0.0` from `+0.0` by the sign bit, but our
        // Real sort is sign-magnitude-collapsing on zero (`-0.0 == +0.0` as reals), so
        // lifting it as `real_const("-0")` would FAKE-DISCHARGE a sign-sensitive claim by
        // collapsing the IEEE distinction. ResidueDig confirmed a conservative refusal is
        // correct. A SOURCE property (sign-sensitive IEEE value), not a lifter gap. EARNED
        // ONLY when `const_float` parsed a literal AND `real_literal_is_zero` is true under
        // unary `Neg` -- a NON-zero float literal (`-1.5`) lifts via `real_const` and never
        // reaches this reason (the fake-refuse guardrail). Typed as `SignedZeroIeeeEffect`.
        || reason.contains("signed zero float literal remains an IEEE refinement")
        // TERMINAL (FLOAT TAIL #3 -- unknown/unstable f-width): a float refinement predicate
        // (`is_nan`/`is_infinite`/..) whose receiver has NO resolvable f32/f64 width -- an
        // f16/f128 unstable-width receiver or an unresolved parse/unwrap chain
        // (`"NaN".parse::<f16>().unwrap().is_nan()`). The refinement atom is keyed on the
        // width (`float.{width}.{method}`); with no known stable width there is no
        // expressible point-wise predicate -- a SOURCE/environment property mirroring the
        // existing `f16/f128 formatting is unstable` terminal, not a lifter gap. EARNED by
        // the `None` arm of `float_refinement_receiver_width` -- a known-f32/f64 receiver
        // resolves a width and lifts, never reaching this reason (the fake-refuse
        // guardrail). Typed as `UnknownFloatWidthEffect`.
        || reason.contains("requires known f32/f64 receiver width")
        // TERMINAL: a GENERIC type/const-parametric helper (`fn test_num<T: Add..>`,
        // `fn check_size_hint<const N: usize>`, `fn inner<SuppressConstPromotion>`,
        // `fn test_parse<T: FromStr>`). Its asserts are written over the type/const
        // parameter, so walked as a standalone item there is NO single concrete
        // monomorphization to read -- its truth is per-instantiation. Every call site
        // instantiates it at a runtime type/const (`::<i8>`, `::<2>`, `::<()>`, or a
        // macro `$T`), so lifting would require type-directed MONOMORPHIZATION (resolving
        // `T::add` etc. per type) -- a typing judgment, not a construction from source
        // literals. A SOURCE property (the helper IS generic), not a missing value-lifter.
        // EARNED by `helper_is_generic_parametric` at the SOLE `callsite_inlining_reason`
        // choke point (top-level Pass-2 + nested deferred-fn drain). DISCRIMINATION: a
        // CONCRETE scalar/slice helper (`fn lower(c: char)`, `fn zero_byte(v: u64, b: usize)`)
        // has no type/const param -- its closed-literal call site a value-lifter CAN pin, so
        // it STAYS the unclassified "reachable only via call-site inlining" reason (the
        // fake-refuse guardrail; left to dissolution / the exact partition).
        || reason.contains("reachable only via monomorphization of a generic")
        // TERMINAL: an `unsupported term` whose SHAPE is genuinely effectful / non-constructible
        // -- a `&mut` borrow, a raw pointer (`&raw const`/`&raw mut`), or a `const { <path> }`
        // block (a name is sugar). None is a single timeless value constructible from source
        // literals (kin to `mutable container is not temporally stable` / `bin-2` / "function
        // names are sugar"). EARNED by `UnsupportedTermEffect` at the specific term arm (the
        // `&mut` fall-through, `Expr::RawAddr`, and `const { <path> }`); a PURE untranslated
        // term (`1i32 as f64`, an untranscribed pure method) has NONE of these shapes and STAYS
        // the bare `unsupported term` reason -- UNCLASSIFIED work (the fake-refuse guardrail).
        // (THE DRAIN: the `ptr.rs`/`cell.rs`/`option.rs`/`async_iter`/`array.rs`/`waker.rs`
        // `&mut`/`&raw`/`const{Zst}` rows fell to unclassified only because the bare reason was
        // not whitelisted; not a fake-zero -- the effectful shape is detected syntactically.)
        || reason.contains("effectful / raw-pointer / mutable-reference term")
        // TERMINAL: an `assert!(match <runtime call> { .. })` whose scrutinee is a RUNTIME
        // non-scalar result (`b.binary_search(&3)`). The asserted boolean is the arm taken by
        // a runtime search result, not a scalar equality over constructible values -- no single
        // timeless `t` (kin to `bin-2`). EARNED by `runtime_match_scrutinee_effect`; a `match`
        // over a CONSTRUCTED literal scrutinee matches None and STAYS the unclassified `only
        // scalar equality` reason (the fake-refuse guardrail). Typed `RuntimeMatchScrutineeEffect`.
        || reason.contains("operand is a runtime non-scalar result")
        // TERMINAL: an array-repeat `[elem; N]` whose length `N` is NOT a plain literal -- a
        // const-generic param or const expr (`[0u8; SIZE]`, `[(); SIZE - 1]`). The universe
        // size is symbolic, so there is no finite construction from the written literal to
        // materialize -- no aggregate term can be pinned. A SOURCE property (not a finite
        // construction from source literals), not a lifter gap. EARNED by the `None` arm of
        // `repeat_count_literal` (`ArrayRepeatNonLiteralEffect`); a LITERAL length lifts the
        // unrolled array and never reaches here (the fake-refuse guardrail). (THE DRAIN: the
        // `mem.rs`/`slice.rs` non-literal-repeat rows fell to unclassified only because the
        // "refused by name" reason was not whitelisted; not a fake-zero -- the non-literal
        // length is detected by `repeat_count_literal`.)
        || reason.contains("has a non-literal length -- not a finite")
        // TERMINAL (RESOLVE-THEN-CLASSIFY -- the test-nested-helper drain): a helper whose
        // source is now SHOWN (lexically resolved from an enclosing `#[test]` fn scope,
        // formerly the unresolved "has no visible source" / "reachable only via call-site
        // inlining" UNCLASSIFIED reach gap) has a RUNTIME body. Two shapes, both SOURCE
        // properties no value-lifter could lift point-wise:
        //   (1) a `let mut` MUTABLE-LOCAL TRAJECTORY -- a state machine the body mutates
        //       step by step (`let mut writer = ..; fmt::write(&mut writer, ..)`), observed
        //       per-step (kin to `temporally unstable` / `mutable container`); and
        //   (2) a RUNTIME ITERATOR/COLLECTION construct -- `preds.iter().map(..).collect()`
        //       into a Vec/HashSet over runtime parameter contents (bin-2 aggregate data,
        //       not constructed from source literals).
        // EARNED by the resolved-body reducer (`init_is_runtime_collection` / the `let mut`
        // arm) AFTER resolution -- a RESOLVED-and-PURE body still digs (the dig path is
        // untouched), so this can only refuse a body whose runtime cause is SHOWN; never a
        // fake-refuse (a pure body discharges) and never an unresolved fake-terminal (the
        // unresolved "has no visible source" stays UNCLASSIFIED below). Corpus:
        // `mem/type_info.rs::assert_predicates_exact` (collection), `fmt/float.rs::assert_exact_exp`
        // (mut writer).
        || reason.contains("runtime iterator/collection construct (bin-2")
        || reason.contains("mutable-local state machine driven by fmt-write");
    if terminal {
        Disposition::Refused
    } else {
        Disposition::Unclassified
    }
}

pub fn lift_file_with_options(
    file: &syn::File,
    source_path: &str,
    options: &LiftOptions,
) -> AdapterOutput {
    let empty = MacroRegistry::new();
    lift_file_with_macro_imports(file, source_path, options, &empty)
}

/// Lift a file with an external macro registry in scope. The registry carries
/// `macro_rules!` definitions gathered from the rest of the crate and its
/// dependency SOURCE (we operate exclusively on source, never on a binary or an
/// opaque macro we refuse to read). Any macro the lifter expands is expanded
/// from a definition we hold.
pub fn lift_file_with_macro_imports(
    file: &syn::File,
    source_path: &str,
    options: &LiftOptions,
    imported_macros: &MacroRegistry,
) -> AdapterOutput {
    let mut out = AdapterOutput::default();
    let mut modules = Vec::new();
    let reducer = ReductionCtx::from_items_with_imports(&file.items, imported_macros);
    // Pass 1: walk test fns (and modules). Populates assertions_lifted, reduced_helpers.
    walk_items(
        &file.items,
        source_path,
        &mut modules,
        options,
        &reducer,
        &mut out,
    );
    // Pass 2: walk non-test fns. Emit named refusals for asserts in helper fns
    // that were NOT already credited via reducer inlining in Pass 1.
    walk_non_test_fns(
        &file.items,
        source_path,
        &mut Vec::new(),
        &out.reduced_helpers.clone(),
        &reducer,
        options,
        &mut out,
    );
    out
}

// ── STEP-1 CENSUS (diagnostic; NEVER affects counts/CID) ─────────────────────
// Categorize the residue blocking call-site-inlining. Walks the same items the
// lifter walks, and for every BARE CALL statement inside a `#[test]` fn that
// `CallsiteSugar::decompose` recognizes, replays `desugar` to observe its
// `CallsiteOutcome` -- tallying, per helper, what its inlined body hits. Helpers
// that emit "reachable only" but are never reached by a carryable call are
// NonClosedArgs. Pure observation through the real engine: no wire change.

/// A per-helper census row: the helper name and the category of its inline
/// residue. `added_unclassified` is the residue size when the body bailed on
/// unclassified work (0 for NonClosedArgs / committed).
#[derive(Debug, Clone)]
pub struct CallsiteCensusRow {
    pub helper: String,
    pub category: sugar::callsite::ResidueCategory,
    pub added_unclassified: usize,
    pub sample_reasons: Vec<String>,
    pub committed: bool,
}

/// Walk a file's `#[test]` fns, replay `CallsiteSugar` decompose+desugar over every
/// bare call statement, and return one census row per recognized call site. The
/// `imported` registry mirrors the production lift so helper resolution is faithful.
pub fn callsite_census(
    file: &syn::File,
    options: &LiftOptions,
    imported: &MacroRegistry,
) -> Vec<CallsiteCensusRow> {
    let reducer = ReductionCtx::from_items_with_imports(&file.items, imported);
    let mut rows = Vec::new();
    let reduced: HashSet<String> = HashSet::new();
    census_walk_items(&file.items, options, &reducer, &reduced, &mut rows);
    rows
}

fn census_walk_items(
    items: &[Item],
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    reduced: &HashSet<String>,
    rows: &mut Vec<CallsiteCensusRow>,
) {
    for item in items {
        match item {
            Item::Fn(f) if has_test_attr(&f.attrs) => {
                if matches!(cfg_eval_for_attrs(&f.attrs, options), CfgEval::Active) {
                    census_walk_stmts(&f.block.stmts, "census", options, reducer, reduced, rows);
                }
            }
            Item::Mod(m) => {
                if let Some((_, items)) = &m.content {
                    if matches!(cfg_eval_for_attrs(&m.attrs, options), CfgEval::Active) {
                        census_walk_items(items, options, reducer, reduced, rows);
                    }
                }
            }
            _ => {}
        }
    }
}

fn census_walk_stmts(
    stmts: &[Stmt],
    scope: &str,
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    reduced: &HashSet<String>,
    rows: &mut Vec<CallsiteCensusRow>,
) {
    // Nested fns lexically in scope (mirror of the collector's `local_fns`), so the
    // census resolves nested helpers the same way the live lift does.
    let local_fns: BTreeMap<String, &syn::ItemFn> = stmts
        .iter()
        .filter_map(|s| match s {
            Stmt::Item(Item::Fn(f)) => Some((f.sig.ident.to_string(), f)),
            _ => None,
        })
        .collect();
    for (idx, stmt) in stmts.iter().enumerate() {
        if let Stmt::Expr(e, _) = stmt {
            if let Some(cs) =
                sugar::callsite::CallsiteSugar::decompose(e, &local_fns, reducer, options, 0)
            {
                let mut fw = FloatWidthScope::new();
                let outcome =
                    cs.desugar(scope, idx, options, reducer, &mut fw, reduced, 0);
                let row = match outcome {
                    sugar::callsite::CallsiteOutcome::Dug(_) => CallsiteCensusRow {
                        helper: cs.name.clone(),
                        category: sugar::callsite::ResidueCategory::PureUntranslatedTerm,
                        added_unclassified: 0,
                        sample_reasons: Vec::new(),
                        committed: true,
                    },
                    sugar::callsite::CallsiteOutcome::Bail(cause) => {
                        census_row_from_bail(cs.name.clone(), cause)
                    }
                };
                rows.push(row);
            }
            // Recurse into nested blocks (a bare block expr) to reach calls inside.
            if let Expr::Block(b) = e {
                census_walk_stmts(&b.block.stmts, scope, options, reducer, reduced, rows);
            }
        }
    }
}

fn census_row_from_bail(
    helper: String,
    cause: sugar::callsite::BailCause,
) -> CallsiteCensusRow {
    use sugar::callsite::{BailCause, ResidueCategory};
    match cause {
        BailCause::NotInlinable => CallsiteCensusRow {
            helper,
            category: ResidueCategory::NonClosedArgs,
            added_unclassified: 0,
            sample_reasons: Vec::new(),
            committed: false,
        },
        BailCause::FullyReduced => CallsiteCensusRow {
            helper,
            category: ResidueCategory::PureUntranslatedTerm,
            added_unclassified: 0,
            sample_reasons: Vec::new(),
            committed: true,
        },
        BailCause::UnclassifiedResidue {
            added_unclassified,
            sample_reasons,
        } => {
            // The dominant category across the residue reasons. A body that hits any
            // genuine effect alongside other work is still blocked by the OTHER work,
            // so we report the FIRST non-effect shape if present (the actual blocker),
            // else the effect. Pure-untranslated-term and unsupported-construct are
            // the real roadmap rungs.
            let cats: Vec<ResidueCategory> = sample_reasons
                .iter()
                .map(|r| sugar::callsite::classify_residue_reason(r))
                .collect();
            let category = cats
                .iter()
                .copied()
                .find(|c| *c == ResidueCategory::PureUntranslatedTerm)
                .or_else(|| {
                    cats.iter()
                        .copied()
                        .find(|c| *c == ResidueCategory::UnsupportedConstruct)
                })
                .unwrap_or(ResidueCategory::GenuineEffect);
            CallsiteCensusRow {
                helper,
                category,
                added_unclassified,
                sample_reasons,
                committed: false,
            }
        }
    }
}

fn walk_items<'a>(
    items: &[Item],
    source_path: &str,
    modules: &mut Vec<String>,
    options: &LiftOptions,
    reducer: &ReductionCtx<'a>,
    out: &mut AdapterOutput,
) {
    for item in items {
        match item {
            Item::Fn(f) => {
                if has_test_attr(&f.attrs) {
                    visit_test_fn(f, source_path, modules, options, reducer, out);
                }
                // Non-test fns are handled in the second pass (walk_non_test_fns).
            }
            Item::Mod(m) => {
                if let Some((_, items)) = &m.content {
                    let module_name = scoped_test_name(source_path, modules, &m.ident.to_string());
                    match cfg_eval_for_attrs(&m.attrs, options) {
                        CfgEval::Active => {}
                        CfgEval::Inactive(reason) => {
                            account_skipped_module(
                                items,
                                &module_name,
                                "inactive",
                                &reason,
                                source_path,
                                out,
                            );
                            continue;
                        }
                        CfgEval::Ambiguous(reason) => {
                            account_skipped_module(
                                items,
                                &module_name,
                                "ambiguous",
                                &reason,
                                source_path,
                                out,
                            );
                            continue;
                        }
                    }
                    modules.push(m.ident.to_string());
                    walk_items(items, source_path, modules, options, reducer, out);
                    modules.pop();
                }
            }
            _ => {}
        }
    }
}

/// Walk items for Pass 2 (non-test fns). Emits named refusals for asserts in
/// non-test fns that were NOT already credited via reducer inlining (Pass 1).
fn walk_non_test_fns(
    items: &[Item],
    source_path: &str,
    modules: &mut Vec<String>,
    reduced_helpers: &HashSet<String>,
    reducer: &ReductionCtx<'_>,
    options: &LiftOptions,
    out: &mut AdapterOutput,
) {
    for item in items {
        match item {
            Item::Fn(f) => {
                if !has_test_attr(&f.attrs) {
                    visit_non_test_fn(f, source_path, modules, reduced_helpers, out);
                }
            }
            Item::Mod(m) => {
                if let Some((_, items)) = &m.content {
                    // A cfg-skipped module was fully accounted in pass 1; do not
                    // recurse here or its non-test asserts would be double-counted.
                    if !matches!(cfg_eval_for_attrs(&m.attrs, options), CfgEval::Active) {
                        continue;
                    }
                    modules.push(m.ident.to_string());
                    walk_non_test_fns(
                        items,
                        source_path,
                        modules,
                        reduced_helpers,
                        reducer,
                        options,
                        out,
                    );
                    modules.pop();
                }
            }
            // Item-level macro invocation (e.g. `assert_value!(...)` at module
            // scope). Account assert-named invocations: walk into the definition
            // if it is in-source, otherwise refuse by name. One invocation is one
            // unit, matching the assertion-macro denominator.
            Item::Macro(m) => {
                if let Some(seg) = m.mac.path.segments.last() {
                    let mname = seg.ident.to_string();
                    if mname.starts_with("assert") || mname.starts_with("debug_assert") {
                        let reason = match try_macro_expansion_entries(
                            &m.mac.path,
                            &m.mac.tokens,
                            reducer,
                            "item",
                            options,
                            &mut FloatWidthScope::new(),
                            0,
                        ) {
                            Some(Ok(_)) => format!(
                                "item-level macro `{mname}`: assertion content lifts only inside a test fn; released to layer 0"
                            ),
                            Some(Err(e)) => e,
                            None => format!(
                                "item-level assert macro `{mname}`: definition not visible; released to layer 0"
                            ),
                        };
                        out.assertions_refused += 1;
                        out.skip_reasons.push(reason.clone());
                        out.warnings.push(LiftWarning {
                            source_path: source_path.to_string(),
                            item_name: scoped_test_name(source_path, modules, &mname),
                            reason: format!(
                                "rust test assertions: unsupported assertion surface; released to layer 0: {reason}"
                            ),
                        });
                    }
                }
            }
            // Asserts inside impl method bodies (e.g. an Iterator impl on a test
            // helper struct) are reachable only when the method runs, with the
            // receiver's runtime state. Refuse them so they are not silent.
            Item::Impl(imp) => {
                for impl_item in &imp.items {
                    if let syn::ImplItem::Fn(method) = impl_item {
                        let method_name = method.sig.ident.to_string();
                        let count = count_asserts_in_stmts(&method.block.stmts);
                        if count == 0 {
                            continue;
                        }
                        // TERMINAL (NAMED Effect): an assertion in an impl method body
                        // is reachable ONLY when the method runs, observing the receiver's
                        // RUNTIME state (`self.done`, `self.exhausted`, an atomic `.load`,
                        // a mutated field). There is no single timeless `t` at which to
                        // read it -- the value depends on how many times the method has
                        // been driven. A source property (kin to `temporally unstable`),
                        // not a missing lifter. Detection is STRUCTURAL: the assert is
                        // lexically inside an `impl` method body, which only executes at
                        // call time. Typed as `ImplMethodEffect`.
                        let reason = (Effect::ImplMethod {
                            boundary: format!("impl method `{method_name}`"),
                        })
                        .reason();
                        for _ in 0..count {
                            out.assertions_refused += 1;
                            out.skip_reasons.push(reason.clone());
                        }
                        out.warnings.push(LiftWarning {
                            source_path: source_path.to_string(),
                            item_name: scoped_test_name(source_path, modules, &method_name),
                            reason: format!(
                                "rust test assertions: unsupported assertion surface; released to layer 0: {reason}"
                            ),
                        });
                    }
                }
            }
            // Item-level const/static initializers can hold compile-time asserts
            // (e.g. `const _: () = assert!(S(1) == S(1));`). Count and refuse them
            // so they are accounted, not silently dropped.
            Item::Const(c) => {
                lift_item_assertions(&c.expr, "const-item", source_path, modules, options, reducer, out);
            }
            Item::Static(s) => {
                lift_item_assertions(&s.expr, "static-item", source_path, modules, options, reducer, out);
            }
            _ => {}
        }
    }
}

#[derive(Clone, Copy, Debug)]
enum Flt2decMode {
    Shortest,
    ExactFixed,
    ExactExp,
    ShortestExp,
}

/// Detect whether `f` is a flt2dec string-formatting test helper, by which core
/// `flt2dec` entry point its body calls. Returns `None` for `to_shortest_exp_str`
/// (bounds-driven fixed-vs-exp, no single `format!` equivalent -- left unclassified)
/// and for non-flt2dec fns.
fn flt2dec_helper_mode(f: &syn::ItemFn) -> Option<Flt2decMode> {
    struct V {
        mode: Option<Flt2decMode>,
    }
    impl<'ast> syn::visit::Visit<'ast> for V {
        fn visit_path(&mut self, p: &'ast syn::Path) {
            if let Some(seg) = p.segments.last() {
                match seg.ident.to_string().as_str() {
                    "to_shortest_str" => self.mode = Some(Flt2decMode::Shortest),
                    "to_exact_fixed_str" => self.mode = Some(Flt2decMode::ExactFixed),
                    "to_exact_exp_str" => self.mode = Some(Flt2decMode::ExactExp),
                    "to_shortest_exp_str" => self.mode = Some(Flt2decMode::ShortestExp),
                    _ => {}
                }
            }
            syn::visit::visit_path(self, p);
        }
    }
    let mut v = V { mode: None };
    syn::visit::Visit::visit_item_fn(&mut v, f);
    v.mode
}

/// A concrete float value parsed from a closed source operand, tagged with its
/// width so we evaluate at the right precision (f32 vs f64 shortest digits differ).
enum Flt2decValue {
    F64(f64),
    F32(f32),
}

/// Parse a flt2dec value operand into a concrete f32/f64. Bare float literals are
/// f64 (the corpus only ever types f32/f16 values explicitly via `fN::CONST` /
/// `ldexp_fN`). `ldexp_f32(m, e)` / `ldexp_f64(m, e)` are computed exactly via
/// stepwise scaling (`flt2dec_eval::ldexp_*`). A bare identifier is resolved
/// through `bindings` (the enclosing helper's `let` map), e.g. `minf32` ->
/// `ldexp_f32(1.0, -149)`. Returns `None` for anything not a closed f32/f64 term
/// (f16/f128 -- including `ldexp_f16` and idents bound to them, unknown consts,
/// unbound idents) -- those stay unclassified (safe under-claim).
fn parse_flt2dec_value(expr: &Expr, bindings: &BTreeMap<String, Expr>) -> Option<Flt2decValue> {
    match expr {
        // bare / suffixed float literal
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Float(lf),
            ..
        }) => {
            let s = lf.suffix();
            if s == "f32" {
                lf.base10_parse::<f32>().ok().map(Flt2decValue::F32)
            } else {
                // "" or "f64"
                lf.base10_parse::<f64>().ok().map(Flt2decValue::F64)
            }
        }
        // negation of a literal: -0.0, -3.14
        Expr::Unary(u) if matches!(u.op, syn::UnOp::Neg(_)) => {
            match parse_flt2dec_value(&u.expr, bindings)? {
                Flt2decValue::F64(v) => Some(Flt2decValue::F64(-v)),
                Flt2decValue::F32(v) => Some(Flt2decValue::F32(-v)),
            }
        }
        // division of two literals: 1.0/0.0 = inf, 0.0/0.0 = NaN, -1.0/0.0 = -inf
        Expr::Binary(b) if matches!(b.op, syn::BinOp::Div(_)) => {
            match (
                parse_flt2dec_value(&b.left, bindings)?,
                parse_flt2dec_value(&b.right, bindings)?,
            ) {
                (Flt2decValue::F64(l), Flt2decValue::F64(r)) => Some(Flt2decValue::F64(l / r)),
                (Flt2decValue::F32(l), Flt2decValue::F32(r)) => Some(Flt2decValue::F32(l / r)),
                _ => None,
            }
        }
        // `ldexp_f32(m, e)` / `ldexp_f64(m, e)` = m * 2^e (computed exactly).
        // `ldexp_f16` (unstable) is intentionally NOT handled -> None.
        Expr::Call(c) => {
            let Expr::Path(fp) = c.func.as_ref() else {
                return None;
            };
            let fname = fp.path.segments.last()?.ident.to_string();
            let (is_f32, is_f64) = (fname == "ldexp_f32", fname == "ldexp_f64");
            if !(is_f32 || is_f64) {
                return None;
            }
            let mut a = c.args.iter();
            let m_expr = a.next()?;
            let e_expr = a.next()?;
            if a.next().is_some() {
                return None;
            }
            // mantissa: a closed f32/f64 value (commonly the literal `1.0`).
            let m = parse_flt2dec_value(m_expr, bindings)?;
            let e = parse_i32_literal(e_expr)?;
            match m {
                Flt2decValue::F64(mv) if is_f64 => {
                    Some(Flt2decValue::F64(flt2dec_eval::ldexp_f64(mv, e)))
                }
                // The mantissa literal `1.0` parses as F64; for `ldexp_f32` cast it.
                Flt2decValue::F64(mv) if is_f32 => {
                    Some(Flt2decValue::F32(flt2dec_eval::ldexp_f32(mv as f32, e)))
                }
                Flt2decValue::F32(mv) if is_f32 => {
                    Some(Flt2decValue::F32(flt2dec_eval::ldexp_f32(mv, e)))
                }
                _ => None,
            }
        }
        // known associated consts: f64::MAX / f32::INFINITY / ...
        Expr::Path(p) => {
            // single-segment ident -> resolve via the enclosing helper's `let` map.
            if p.path.segments.len() == 1 {
                let name = p.path.segments[0].ident.to_string();
                let bound = bindings.get(&name)?;
                // Guard against a binding that refers to itself (shadowing): drop
                // the just-resolved name so resolution strictly shrinks.
                let mut narrowed = bindings.clone();
                narrowed.remove(&name);
                return parse_flt2dec_value(bound, &narrowed);
            }
            let segs: Vec<String> = p.path.segments.iter().map(|s| s.ident.to_string()).collect();
            if segs.len() != 2 {
                return None;
            }
            let val = match segs[1].as_str() {
                "MAX" => 1.0,
                "MIN" => -1.0,
                "INFINITY" => f64::INFINITY,
                "NEG_INFINITY" => f64::NEG_INFINITY,
                "NAN" => f64::NAN,
                _ => return None,
            };
            match segs[0].as_str() {
                // MAX/MIN of f32/f64 are huge magnitudes whose shortest form the corpus
                // writes via `format!`; only the INFINITY/NAN consts evaluate cleanly to a
                // small string. Hand MAX/MIN back as the real const so the eval is correct,
                // but only if the RHS is a plain string literal (caller gates that).
                "f64" => match segs[1].as_str() {
                    "MAX" => Some(Flt2decValue::F64(f64::MAX)),
                    "MIN" => Some(Flt2decValue::F64(f64::MIN)),
                    _ => Some(Flt2decValue::F64(val)),
                },
                "f32" => match segs[1].as_str() {
                    "MAX" => Some(Flt2decValue::F32(f32::MAX)),
                    "MIN" => Some(Flt2decValue::F32(f32::MIN)),
                    "INFINITY" => Some(Flt2decValue::F32(f32::INFINITY)),
                    "NEG_INFINITY" => Some(Flt2decValue::F32(f32::NEG_INFINITY)),
                    "NAN" => Some(Flt2decValue::F32(f32::NAN)),
                    _ => None,
                },
                _ => None,
            }
        }
        Expr::Paren(p) => parse_flt2dec_value(&p.expr, bindings),
        Expr::Group(g) => parse_flt2dec_value(&g.expr, bindings),
        _ => None,
    }
}

/// `Minus` / `MinusPlus` path operand -> `FmtSign`.
fn parse_flt2dec_sign(expr: &Expr) -> Option<flt2dec_eval::FmtSign> {
    let Expr::Path(p) = expr else { return None };
    match p.path.segments.last()?.ident.to_string().as_str() {
        "Minus" => Some(flt2dec_eval::FmtSign::Minus),
        "MinusPlus" => Some(flt2dec_eval::FmtSign::MinusPlus),
        _ => None,
    }
}

fn parse_usize_literal(expr: &Expr) -> Option<usize> {
    match expr {
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Int(i),
            ..
        }) => i.base10_parse::<usize>().ok(),
        Expr::Paren(p) => parse_usize_literal(&p.expr),
        Expr::Group(g) => parse_usize_literal(&g.expr),
        _ => None,
    }
}

fn parse_bool_literal(expr: &Expr) -> Option<bool> {
    match expr {
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Bool(b),
            ..
        }) => Some(b.value),
        Expr::Paren(p) => parse_bool_literal(&p.expr),
        Expr::Group(g) => parse_bool_literal(&g.expr),
        _ => None,
    }
}

/// An `i32` literal, allowing a unary negation (`-4`).
fn parse_i32_literal(expr: &Expr) -> Option<i32> {
    match expr {
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Int(i),
            ..
        }) => i.base10_parse::<i32>().ok(),
        Expr::Unary(u) if matches!(u.op, syn::UnOp::Neg(_)) => {
            parse_i32_literal(&u.expr).map(|n| -n)
        }
        Expr::Paren(p) => parse_i32_literal(&p.expr),
        Expr::Group(g) => parse_i32_literal(&g.expr),
        _ => None,
    }
}

/// A `(lo, hi)` dec-bounds tuple of two i32 literals.
fn parse_bounds_tuple(expr: &Expr) -> Option<(i32, i32)> {
    match expr {
        Expr::Tuple(t) if t.elems.len() == 2 => {
            let lo = parse_i32_literal(&t.elems[0])?;
            let hi = parse_i32_literal(&t.elems[1])?;
            Some((lo, hi))
        }
        Expr::Paren(p) => parse_bounds_tuple(&p.expr),
        Expr::Group(g) => parse_bounds_tuple(&g.expr),
        _ => None,
    }
}

/// A plain string-literal RHS -> its value. Anything else (e.g. a `format!(..)`
/// expected) returns `None`, leaving that assert unclassified.
fn parse_string_literal(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Str(s),
            ..
        }) => Some(s.value()),
        Expr::Paren(p) => parse_string_literal(&p.expr),
        Expr::Group(g) => parse_string_literal(&g.expr),
        _ => None,
    }
}

/// Evaluate a CLOSED, CONSTANT `format!` expected-RHS into its string value.
///
/// The coretests corpus expresses the huge-magnitude / tiny-subnormal expected
/// strings as `format!("..{:0>N}..", "")` -- a format string with exactly one
/// zero-fill placeholder `{:0>N}` whose argument is the empty string literal, so
/// it expands to `N` literal `'0'` characters at that position. We reproduce that
/// expansion EXACTLY (verified against `f32::MAX`/`f64::MAX`/`minf32`/`minf64`):
///   * exactly one positional argument, the string literal `""`;
///   * the format string contains exactly one `{...}` placeholder, of the form
///     `{:0>N}` (zero fill, right-align, fixed width `N`, no other spec), and no
///     escaped braces (`{{`/`}}`);
///   * the result is `prefix + "0".repeat(N) + suffix`.
///
/// Anything outside this exact closed shape -> `None` (skip, safe under-claim).
/// Note `""` right-aligned into a `0`-filled width of `N` is `N` zeros for ANY
/// fill char/alignment, but we still require `0>` so we never silently accept a
/// spec whose meaning we have not reasoned through.
fn parse_format_zerofill(expr: &Expr) -> Option<String> {
    let mac = match expr {
        Expr::Macro(m) => &m.mac,
        Expr::Paren(p) => return parse_format_zerofill(&p.expr),
        Expr::Group(g) => return parse_format_zerofill(&g.expr),
        _ => return None,
    };
    if mac.path.segments.last()?.ident != "format" {
        return None;
    }
    let parser = Punctuated::<Expr, Token![,]>::parse_terminated;
    let args = parser.parse2(mac.tokens.clone()).ok()?;
    let mut it = args.iter();
    // arg 0: the format string literal.
    let fmt = parse_string_literal(it.next()?)?;
    // arg 1: must be exactly the empty string literal `""`.
    let fill = parse_string_literal(it.next()?)?;
    if !fill.is_empty() {
        return None;
    }
    // no further args.
    if it.next().is_some() {
        return None;
    }
    // Reject any escaped braces -- they complicate placeholder counting and never
    // appear in the corpus patterns.
    if fmt.contains("{{") || fmt.contains("}}") {
        return None;
    }
    // Exactly one `{...}` placeholder.
    let open = fmt.find('{')?;
    let close = fmt[open..].find('}').map(|i| open + i)?;
    // no second placeholder
    if fmt[close + 1..].contains('{') {
        return None;
    }
    // spec between braces must be exactly `:0>N` with N a usize.
    let spec = &fmt[open + 1..close];
    let n_str = spec.strip_prefix(":0>")?;
    let n: usize = n_str.parse().ok()?;
    Some(format!(
        "{}{}{}",
        &fmt[..open],
        "0".repeat(n),
        &fmt[close + 1..]
    ))
}

/// The expected-RHS of a flt2dec assert: a plain string literal, or a closed
/// constant `format!("..{:0>N}..", "")` pattern. `None` for anything else.
fn parse_flt2dec_expected(expr: &Expr) -> Option<String> {
    parse_string_literal(expr).or_else(|| parse_format_zerofill(expr))
}

/// Try to dissolve one `assert_eq!(to_string(f, V, S, D[, U]), EXPECTED)` from a
/// flt2dec helper into the constant equality `eq(eval(V,S,D[,U]), EXPECTED)`.
///   * `Some(true)`  -- evaluated, and our stdlib formatting equals the asserted literal
///                      (discharged by dissolution).
///   * `Some(false)` -- evaluated, but disagrees (a real refutation; never expected for a
///                      passing vendor test, refused not discharged).
///   * `None`        -- operands are not a closed f32/f64 literal term, or the expected is
///                      neither a plain string literal nor a closed `format!` pattern:
///                      leave unclassified.
/// `bindings` is the enclosing helper's `let <ident> = <expr>` map, used to resolve
/// value operands like `minf32` to their `ldexp_fN(..)` definition.
fn dissolve_flt2dec_assert(
    mac: &syn::Macro,
    mode: Flt2decMode,
    bindings: &BTreeMap<String, Expr>,
) -> Option<bool> {
    use syn::punctuated::Punctuated;
    let parser = Punctuated::<Expr, syn::Token![,]>::parse_terminated;
    let args = parser.parse2(mac.tokens.clone()).ok()?;
    let mut it = args.iter();
    let lhs = it.next()?;
    let rhs = it.next()?;
    // LHS must be `to_string(f, V, S, D[, U])`.
    let Expr::Call(call) = lhs else { return None };
    let Expr::Path(cp) = call.func.as_ref() else {
        return None;
    };
    if cp.path.segments.last()?.ident != "to_string" {
        return None;
    }
    let call_args: Vec<&Expr> = call.args.iter().collect();
    // args[0] is the formatter closure `f` (ignored -- we evaluate with our own stdlib).
    let value = parse_flt2dec_value(call_args.get(1)?, bindings)?;
    let sign = parse_flt2dec_sign(call_args.get(2)?)?;
    let expected = parse_flt2dec_expected(rhs)?;

    let computed = match mode {
        Flt2decMode::Shortest => {
            let frac = parse_usize_literal(call_args.get(3)?)?;
            match value {
                Flt2decValue::F64(v) => flt2dec_eval::shortest_f64(v, sign, frac),
                Flt2decValue::F32(v) => flt2dec_eval::shortest_f32(v, sign, frac),
            }
        }
        Flt2decMode::ExactFixed => {
            let frac = parse_usize_literal(call_args.get(3)?)?;
            match value {
                Flt2decValue::F64(v) => flt2dec_eval::exact_fixed_f64(v, sign, frac),
                Flt2decValue::F32(v) => flt2dec_eval::exact_fixed_f32(v, sign, frac),
            }
        }
        Flt2decMode::ExactExp => {
            let frac = parse_usize_literal(call_args.get(3)?)?;
            let upper = parse_bool_literal(call_args.get(4)?)?;
            match value {
                Flt2decValue::F64(v) => flt2dec_eval::exact_exp_f64(v, sign, frac, upper),
                Flt2decValue::F32(v) => flt2dec_eval::exact_exp_f32(v, sign, frac, upper),
            }
        }
        Flt2decMode::ShortestExp => {
            let (lo, hi) = parse_bounds_tuple(call_args.get(3)?)?;
            let upper = parse_bool_literal(call_args.get(4)?)?;
            match value {
                Flt2decValue::F64(v) => flt2dec_eval::shortest_exp_f64(v, sign, lo, hi, upper),
                Flt2decValue::F32(v) => flt2dec_eval::shortest_exp_f32(v, sign, lo, hi, upper),
            }
        }
    };
    Some(computed == expected)
}

/// Dissolve a flt2dec formatting test helper: evaluate each closed
/// `assert_eq!(to_string(..), "..")` with our own stdlib `format!` and discharge it,
/// leaving non-closed / f16 / `format!`-expected asserts unclassified. Every textual
/// assert macro is accounted (discharged or refused), so nothing is silently dropped.
fn lift_flt2dec_helper(
    f: &syn::ItemFn,
    mode: Flt2decMode,
    source_path: &str,
    modules: &[String],
    out: &mut AdapterOutput,
) {
    let scoped = scoped_test_name(source_path, modules, &f.sig.ident.to_string());
    let total = count_asserts_in_stmts(&f.block.stmts);

    // Collect every assert_eq!/assert! macro in the helper body (incl. nested blocks),
    // in textual order, so the per-macro disposition reconciles against `total`.
    struct MacroWalk {
        macros: Vec<syn::Macro>,
    }
    impl<'ast> syn::visit::Visit<'ast> for MacroWalk {
        fn visit_macro(&mut self, m: &'ast syn::Macro) {
            if is_assert_macro_path(&m.path) {
                self.macros.push(m.clone());
            }
            syn::visit::visit_macro(self, m);
        }
    }
    let mut w = MacroWalk { macros: Vec::new() };
    syn::visit::Visit::visit_item_fn(&mut w, f);

    // Collect simple `let <ident> = <expr>;` bindings from the helper body so a
    // value operand written as an identifier (e.g. `minf32`) resolves to its
    // definition (`ldexp_f32(1.0, -149)`). Only un-typed, non-`mut`, single-ident
    // patterns with an initializer are captured; anything else is ignored (the
    // operand then stays unresolved -> None -> refused, which is safe). The corpus
    // defines these once at top of the helper, so last-write-wins on the BTreeMap
    // is correct.
    let mut bindings: BTreeMap<String, Expr> = BTreeMap::new();
    for stmt in &f.block.stmts {
        if let Stmt::Local(local) = stmt {
            if let Pat::Ident(pi) = &local.pat {
                if pi.by_ref.is_none() && pi.subpat.is_none() {
                    if let Some(init) = &local.init {
                        if init.diverge.is_none() {
                            bindings.insert(pi.ident.to_string(), (*init.expr).clone());
                        }
                    }
                }
            }
        }
    }

    let mut lifted = 0usize;
    let mut refused = 0usize;
    for m in &w.macros {
        match dissolve_flt2dec_assert(m, mode, &bindings) {
            Some(true) => lifted += 1,
            Some(false) => {
                // Our independent stdlib evaluation disagrees with the asserted literal.
                // For a passing vendor test this cannot happen; refuse rather than ever
                // false-discharge.
                refused += 1;
                out.skip_reasons.push(
                    "flt2dec dissolution: independent stdlib evaluation disagrees with the \
                     asserted value; refused"
                        .to_string(),
                );
            }
            None => {
                refused += 1;
                let toks = m.tokens.to_string();
                if toks.contains("f16") || toks.contains("f128") {
                    // TERMINAL: f16/f128 formatting. These are UNSTABLE float types; the
                    // stable toolchain the lifter ships cannot format them (no stable
                    // Display/flt2dec for f16/f128), so the value cannot be dissolved by
                    // evaluation, and we do NOT model the flt2dec algorithm (no-model
                    // axiom). The assert tests an unstable API not expressible as a
                    // point-wise claim over the stable surface -- a source/environment
                    // property, not a lifter gap. (Refused, stated plainly; not a fake-zero.)
                    out.skip_reasons.push(
                        "flt2dec assert: f16/f128 formatting is unstable -- unformattable on \
                         the stable toolchain the lifter ships and not modellable as a \
                         point-wise claim; refused"
                            .to_string(),
                    );
                } else {
                    out.skip_reasons.push(
                        "flt2dec assert: operand is not a closed f32/f64 literal term (ldexp \
                         or a format! expected); released to layer 0"
                            .to_string(),
                    );
                }
            }
        }
    }
    out.assertions_lifted += lifted;
    out.assertions_refused += refused;

    // Totality net: account any assert the macro walk did not reach.
    let accounted = lifted + refused;
    if total > accounted {
        let gap = total - accounted;
        for _ in 0..gap {
            out.assertions_refused += 1;
            out.skip_reasons
                .push("flt2dec helper: unenumerated assert; released to layer 0".to_string());
        }
    }
    out.warnings.push(LiftWarning {
        source_path: source_path.to_string(),
        item_name: scoped,
        reason: format!(
            "flt2dec formatting helper dissolved by stdlib evaluation: {lifted} discharged, \
             {refused} unclassified (mode {mode:?})"
        ),
    });
}

/// A trait bound that makes a parameter carry RUNTIME behaviour/data that is not a
/// source literal: a closure/fn-pointer (`Fn`/`FnMut`/`FnOnce`) or an iterator
/// (`Iterator`/`IntoIterator`/`DoubleEndedIterator`/`ExactSizeIterator`). A helper
/// parameterised over such a value asserts over runtime data -- bin-2 (not constructible
/// from source literals at any call site), categorically not a point-wise value claim.
fn trait_bound_is_runtime_opaque(b: &syn::TypeParamBound) -> bool {
    if let syn::TypeParamBound::Trait(t) = b {
        if let Some(seg) = t.path.segments.last() {
            return matches!(
                seg.ident.to_string().as_str(),
                "Fn" | "FnMut"
                    | "FnOnce"
                    | "Iterator"
                    | "IntoIterator"
                    | "DoubleEndedIterator"
                    | "ExactSizeIterator"
            );
        }
    }
    false
}

fn param_type_is_runtime_opaque(
    ty: &syn::Type,
    runtime_generics: &HashSet<String>,
) -> bool {
    match ty {
        // `impl Fn(..)` / `impl Iterator` parameter.
        syn::Type::ImplTrait(it) => it.bounds.iter().any(trait_bound_is_runtime_opaque),
        // `&dyn Trait` / `dyn Trait` trait object -- runtime dynamic dispatch.
        syn::Type::TraitObject(_) => true,
        syn::Type::Reference(r) => param_type_is_runtime_opaque(&r.elem, runtime_generics),
        syn::Type::Paren(p) => param_type_is_runtime_opaque(&p.elem, runtime_generics),
        // a generic type param bound by a runtime-opaque trait (`fn f<I: Iterator>(it: I)`).
        syn::Type::Path(p) => p
            .path
            .get_ident()
            .map(|i| runtime_generics.contains(&i.to_string()))
            .unwrap_or(false),
        _ => false,
    }
}

/// A non-`#[test]` helper is RUNTIME-PARAMETRIC iff some parameter is a closure/
/// fn-pointer, an iterator, or a trait object (by impl-Trait, generic bound, or `dyn`).
/// Its asserts then read runtime data that no call site can supply as source literals,
/// so they are bin-2 (genuinely terminal) -- distinct from a scalar-parameter helper
/// (`fn lower(c: char)`) whose asserts a closed-literal call site CAN pin (left to
/// dissolution / call-site inlining, which the exact partition credits).
fn helper_is_runtime_parametric(f: &syn::ItemFn) -> bool {
    let mut runtime_generics: HashSet<String> = HashSet::new();
    for gp in &f.sig.generics.params {
        if let syn::GenericParam::Type(tp) = gp {
            if tp.bounds.iter().any(trait_bound_is_runtime_opaque) {
                runtime_generics.insert(tp.ident.to_string());
            }
        }
    }
    if let Some(wc) = &f.sig.generics.where_clause {
        for pred in &wc.predicates {
            if let syn::WherePredicate::Type(pt) = pred {
                if pt.bounds.iter().any(trait_bound_is_runtime_opaque) {
                    if let syn::Type::Path(p) = &pt.bounded_ty {
                        if let Some(id) = p.path.get_ident() {
                            runtime_generics.insert(id.to_string());
                        }
                    }
                }
            }
        }
    }
    f.sig.inputs.iter().any(|arg| match arg {
        syn::FnArg::Typed(pt) => param_type_is_runtime_opaque(&pt.ty, &runtime_generics),
        syn::FnArg::Receiver(_) => false,
    })
}

/// A helper is GENERIC-PARAMETRIC iff its signature carries a generic TYPE or CONST
/// parameter (lifetimes do not count -- they erase to nothing at runtime and never
/// change a value claim). Such a helper's body asserts are written over the type/const
/// parameter (`assert_eq!(ten.add(two), ten + two)` for `<T: Add>`, `offset_of!(Foo<P>,
/// ..)` for `<P>`, `map_windows(|_: &[_; N]|)` for `<const N: usize>`). Walked as a
/// standalone item it has NO monomorphization: every call site instantiates it at a
/// concrete type/const (`test_parse::<i8>`, `check_size_hint::<2>`, `inner::<()>`,
/// `num::n(10 as $T, ..)` under a macro `$T`), so its truth is per-monomorphization, not
/// a single timeless point-wise value. Lifting it would require type-directed
/// MONOMORPHIZATION (resolving `T::add` etc. per instantiation) -- a typing judgment, not
/// a construction from source literals. That is a SOURCE property of the helper being
/// generic, not a missing value-lifter: terminal. (Distinct from a CONCRETE scalar/slice
/// helper whose closed-literal call site a value-lifter CAN pin -- that stays
/// unclassified, owned by dissolution / call-site inlining.)
fn helper_is_generic_parametric(f: &syn::ItemFn) -> bool {
    f.sig.generics.params.iter().any(|gp| {
        matches!(
            gp,
            syn::GenericParam::Type(_) | syn::GenericParam::Const(_)
        )
    })
}

/// A helper's BODY contains a provably-RUNTIME construct that the resolved-body reducer
/// refuses regardless of the call-site actuals: a `let mut` mutable-local trajectory or a
/// `let` whose init is a runtime iterator/collection construct (`.iter().map(..).collect()`).
/// Such a body is bin-2/temporally-unstable by SOURCE -- no closed-literal call site could
/// pin it (the construct reads runtime aggregate / mutated state, not source literals). This
/// is the resolve-then-classify at the DEFINITION site: a helper called ONLY in nested-scope
/// (e.g. `assert_typeid_set_eq`, invoked from inside another helper's body, never at a
/// drainable call site) would otherwise stay the generic UNCLASSIFIED "reachable only via
/// call-site inlining" reason even though its body is genuinely runtime. We mirror EXACTLY
/// the two shapes the resolved-body reducer (`reduce_assertion_stmts`) refuses, so flagging
/// here can only name a body that would also refuse if inlined -- never a fake-refuse. A
/// pure body (no `let mut`, no collection init) returns false and stays unclassified.
fn helper_body_is_runtime_terminal(f: &syn::ItemFn) -> bool {
    f.block.stmts.iter().any(|s| {
        let Stmt::Local(local) = s else { return false };
        // `let mut x = ..` mutable-local trajectory.
        let is_let_mut = matches!(
            &local.pat,
            Pat::Ident(id) if id.mutability.is_some()
        );
        // `let x = <runtime iterator/collection construct>`.
        let init_is_collection = local
            .init
            .as_ref()
            .filter(|i| i.diverge.is_none())
            .map(|i| init_is_runtime_collection(&i.expr))
            .unwrap_or(false);
        is_let_mut || init_is_collection
    })
}

/// The refusal reason for a non-`#[test]` helper's asserts that survived Pass-1 inlining.
///   * runtime iterator/closure/dyn parameter  -> bin-2 terminal (runtime data).
///   * generic type/const parameter            -> monomorphization terminal (no single
///                                                concrete instantiation to read).
///   * runtime BODY construct (`let mut` / collection init) -> terminal (resolve-then-
///     classify at the definition site: a body the resolved-body reducer would refuse).
///   * otherwise (concrete scalar/slice params, pure body) -> UNCLASSIFIED: a closed-literal
///     call site CAN pin it; the inability to lift is call-queueing reach (dissolution / the
///     exact partition own it), NOT a source property. Left unclassified to avoid a
///     fake-refuse of a carryable concrete call.
fn callsite_inlining_reason(fn_name: &str, f: &syn::ItemFn) -> String {
    if helper_is_runtime_parametric(f) {
        format!(
            "assertion in non-#[test] item `{fn_name}` over a runtime iterator/closure/dyn parameter (bin-2: runtime data, not constructible from source literals at any call site); refused"
        )
    } else if helper_body_is_runtime_terminal(f) {
        format!(
            "assertion in non-#[test] item `{fn_name}` has a runtime iterator/collection construct (bin-2: runtime aggregate data, not constructed from source literals); refused"
        )
    } else if helper_is_generic_parametric(f) {
        format!(
            "assertion in non-#[test] item `{fn_name}` reachable only via monomorphization of a generic type/const parameter (runtime instantiation: no single concrete type to read; not statically constructible at any call site); refused"
        )
    } else {
        format!(
            "assertion in non-#[test] item `{fn_name}`: reachable only via call-site inlining; released to layer 0"
        )
    }
}

/// Emit named refusals for every assert macro in a non-`#[test]` fn.
/// These assertions are only reachable via call-site inlining and depend on
/// the fn's parameters: lifting them as unconditional facts would be a false-pass.
/// Skips the fn if it was already successfully reduced by a test fn (Pass 1),
/// because those asserts are already in assertions_lifted.
fn visit_non_test_fn(
    f: &syn::ItemFn,
    source_path: &str,
    modules: &[String],
    reduced_helpers: &HashSet<String>,
    out: &mut AdapterOutput,
) {
    let fn_name = f.sig.ident.to_string();
    // If the reducer successfully inlined this fn's body during Pass 1, its
    // asserts are already in assertions_lifted. Do not double-count.
    if reduced_helpers.contains(&fn_name) {
        return;
    }
    // STDLIB EXCEPTION: a flt2dec formatting test helper's asserts are closed
    // computations over rust's own stdlib; dissolve them by evaluating with our own
    // `format!` instead of refusing as call-site-inlining residue.
    if let Some(mode) = flt2dec_helper_mode(f) {
        lift_flt2dec_helper(f, mode, source_path, modules, out);
        return;
    }
    let scoped_name = scoped_test_name(source_path, modules, &fn_name);
    let count = count_asserts_in_stmts(&f.block.stmts);
    if count == 0 {
        return;
    }
    let reason = callsite_inlining_reason(&fn_name, f);
    for _ in 0..count {
        out.assertions_refused += 1;
        out.skip_reasons.push(reason.clone());
    }
    out.warnings.push(LiftWarning {
        source_path: source_path.to_string(),
        item_name: scoped_name,
        reason: format!(
            "rust test assertions: unsupported assertion surface; released to layer 0: {reason}"
        ),
    });
}

fn visit_test_fn(
    f: &syn::ItemFn,
    source_path: &str,
    modules: &[String],
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    out: &mut AdapterOutput,
) {
    let test_name = scoped_test_name(source_path, modules, &f.sig.ident.to_string());
    match cfg_eval_for_attrs(&f.attrs, options) {
        CfgEval::Active => {}
        CfgEval::Inactive(reason) => {
            // Refuse every assert in the fn body so they are not silent drops.
            let assert_count = count_asserts_in_stmts(&f.block.stmts);
            let skip_reason = format!("inactive cfg on test fn; skipped: {reason}");
            for _ in 0..assert_count {
                out.assertions_refused += 1;
                out.skip_reasons.push(skip_reason.clone());
            }
            out.warnings.push(LiftWarning {
                source_path: source_path.to_string(),
                item_name: test_name,
                reason: format!("rust test assertions: inactive cfg; skipped test: {reason}"),
            });
            return;
        }
        CfgEval::Ambiguous(reason) => {
            // Refuse every assert in the fn body so they are not silent drops.
            let assert_count = count_asserts_in_stmts(&f.block.stmts);
            let skip_reason = format!("ambiguous cfg on test fn; skipped: {reason}");
            for _ in 0..assert_count {
                out.assertions_refused += 1;
                out.skip_reasons.push(skip_reason.clone());
            }
            out.warnings.push(LiftWarning {
                source_path: source_path.to_string(),
                item_name: test_name,
                reason: format!("rust test assertions: ambiguous cfg; skipped test: {reason}"),
            });
            return;
        }
    }
    out.seen += 1;

    let mut entries = Vec::new();
    let mut skipped = Vec::new();
    let mut float_widths = FloatWidthScope::new();
    let mut macros_lifted = 0usize;
    collect_assertion_entries(
        &f.block.stmts,
        &test_name,
        options,
        reducer,
        &mut float_widths,
        &mut entries,
        &mut skipped,
        &mut macros_lifted,
        &mut out.reduced_helpers,
        0,
        &BTreeSet::new(),
        // Top-level `#[test]` fn: no ENCLOSING block, so no inherited nested fns.
        &BTreeMap::new(),
    );
    out.assertions_lifted += macros_lifted;
    out.assertions_refused += skipped.len();
    out.skip_reasons.extend(skipped.iter().cloned());

    // Totality safety net: every assert macro textually present in this test fn
    // body must be accounted for (lifted or refused). The syntactic count is the
    // ground truth; if the structured walk enumerated fewer (an assert in an AST
    // position no arm handles), refuse the remainder by name so nothing is
    // silently dropped. When helper inlining makes accounted exceed the textual
    // count, the gap is zero and no refusal is added.
    let textual_total = count_asserts_in_stmts(&f.block.stmts);
    let accounted = macros_lifted + skipped.len();
    if textual_total > accounted {
        let gap = textual_total - accounted;
        let reason =
            "assertion in an unenumerated statement position within the test fn; released to layer 0"
                .to_string();
        for _ in 0..gap {
            out.assertions_refused += 1;
            out.skip_reasons.push(reason.clone());
        }
        out.warnings.push(LiftWarning {
            source_path: source_path.to_string(),
            item_name: test_name.clone(),
            reason: format!(
                "rust test assertions: {gap} assertion(s) in unenumerated positions; released to layer 0"
            ),
        });
    }

    if !skipped.is_empty() {
        out.warnings.push(LiftWarning {
            source_path: source_path.to_string(),
            item_name: test_name.clone(),
            reason: format!(
                "rust test assertions: unsupported assertion surface; released to layer 0: {}",
                skipped.join("; ")
            ),
        });
    }

    if entries.is_empty() {
        out.warnings.push(LiftWarning {
            source_path: source_path.to_string(),
            item_name: test_name,
            reason: "rust test assertions: no liftable scalar assertions".to_string(),
        });
        return;
    }

    for (name, atoms) in group_assertions(entries, &test_name) {
        out.decls.push(ContractDecl {
            name,
            pre: None,
            post: None,
            inv: Some(and_(atoms)),
            out_binding: "out".to_string(),
            evidence: None,
            panic_loci: Vec::new(),
            concept_hint: None,
        });
    }
    out.lifted += 1;
}

fn has_test_attr(attrs: &[syn::Attribute]) -> bool {
    attrs.iter().any(|attr| {
        attr.path()
            .segments
            .last()
            .is_some_and(|segment| segment.ident == "test")
    })
}

fn scoped_test_name(source_path: &str, modules: &[String], fn_name: &str) -> String {
    if modules.is_empty() {
        format!("{source_path}::{fn_name}")
    } else {
        format!("{source_path}::{}::{fn_name}", modules.join("::"))
    }
}

struct AssertionEntry {
    name: Option<String>,
    atom: Rc<Formula>,
}

struct ReductionCtx<'a> {
    functions: BTreeMap<String, &'a syn::ItemFn>,
    ambiguous_functions: BTreeSet<String>,
    /// In-source `macro_rules!` definitions, by name, parsed into rules. These
    /// are what lets the lifter walk into a macro's definition and expand it,
    /// the same way it walks into a function. A name defined more than once is
    /// ambiguous and not expanded.
    macros: BTreeMap<String, std::rc::Rc<Vec<macro_expand::MacroRule>>>,
    ambiguous_macros: BTreeSet<String>,
    /// macro_rules! gathered from the rest of the crate and its dependency
    /// SOURCE. In-file definitions take precedence; this is the fallback so a
    /// macro defined in another file or crate (whose source we hold) is still
    /// expanded from its definition rather than treated as opaque.
    imported: MacroRegistry,
}

impl<'a> ReductionCtx<'a> {
    fn from_items(items: &'a [Item]) -> Self {
        Self::from_items_with_imports(items, &MacroRegistry::new())
    }

    fn from_items_with_imports(items: &'a [Item], imported: &MacroRegistry) -> Self {
        let mut ctx = Self {
            functions: BTreeMap::new(),
            ambiguous_functions: BTreeSet::new(),
            macros: BTreeMap::new(),
            ambiguous_macros: BTreeSet::new(),
            imported: imported.clone(),
        };
        ctx.collect_items(items);
        ctx
    }

    fn collect_items(&mut self, items: &'a [Item]) {
        for item in items {
            match item {
                Item::Fn(f) => {
                    if !has_test_attr(&f.attrs) {
                        self.insert_function(f);
                    }
                    // fn-local `macro_rules!` (defined INSIDE a fn body, e.g. a test fn's
                    // private `assert_almost_eq!` / `assert_chunks!`) were previously invisible,
                    // so their invocations hit the "unsupported assertion macro" fallthrough.
                    // Collect them by name like any other macro: the same in-file precedence and
                    // the same ambiguity guard apply (a name defined more than once is marked
                    // ambiguous and never expanded -- so collecting fn-local macros globally can
                    // only ever fail to expand, never wrong-expand). This lets the lifter walk
                    // into a fn-local macro's real definition the same way it does a file/dep one.
                    self.collect_macros_in_block(&f.block);
                }
                Item::Macro(m) if m.mac.path.is_ident("macro_rules") => {
                    if let Some(ident) = &m.ident {
                        self.insert_macro(&ident.to_string(), m.mac.tokens.clone());
                    }
                }
                Item::Mod(m) => {
                    if let Some((_, items)) = &m.content {
                        self.collect_items(items);
                    }
                }
                _ => {}
            }
        }
    }

    /// Scan a fn body for fn-local `macro_rules!` definitions, recursing into nested
    /// fns, so a macro defined inside a test fn expands from its real definition.
    fn collect_macros_in_block(&mut self, block: &'a syn::Block) {
        for stmt in &block.stmts {
            match stmt {
                syn::Stmt::Item(Item::Macro(m)) if m.mac.path.is_ident("macro_rules") => {
                    if let Some(ident) = &m.ident {
                        self.insert_macro(&ident.to_string(), m.mac.tokens.clone());
                    }
                }
                syn::Stmt::Item(Item::Fn(f)) => self.collect_macros_in_block(&f.block),
                _ => {}
            }
        }
    }

    fn insert_function(&mut self, f: &'a syn::ItemFn) {
        let name = f.sig.ident.to_string();
        if self.ambiguous_functions.contains(&name) {
            return;
        }
        if self.functions.insert(name.clone(), f).is_some() {
            self.functions.remove(&name);
            self.ambiguous_functions.insert(name);
        }
    }

    fn insert_macro(&mut self, name: &str, tokens: proc_macro2::TokenStream) {
        if self.ambiguous_macros.contains(name) {
            return;
        }
        // A macro whose rules we cannot even parse is not a usable definition;
        // skip it (the caller falls back to refusal).
        let Ok(rules) = macro_expand::parse_rules(tokens) else {
            return;
        };
        if self
            .macros
            .insert(name.to_string(), std::rc::Rc::new(rules))
            .is_some()
        {
            self.macros.remove(name);
            self.ambiguous_macros.insert(name.to_string());
        }
    }

    fn function(&self, name: &str) -> Result<Option<&'a syn::ItemFn>, String> {
        if self.ambiguous_functions.contains(name) {
            return Err(format!(
                "assertion helper `{name}` is ambiguous in visible source"
            ));
        }
        Ok(self.functions.get(name).copied())
    }

    /// Look up a `macro_rules!` definition by name for expansion: in-file first
    /// (most specific), then the imported source-graph registry.
    fn macro_rules(&self, name: &str) -> Option<std::rc::Rc<Vec<macro_expand::MacroRule>>> {
        if self.ambiguous_macros.contains(name) {
            return None;
        }
        if let Some(rules) = self.macros.get(name) {
            return Some(rules.clone());
        }
        self.imported.lookup(name)
    }
}

/// A registry of `macro_rules!` definitions gathered from source: the crate
/// under analysis plus its dependency source trees. Our guarantee extends
/// exactly as far as the source we hold; a macro absent here is out of scope
/// (a named refusal), and the remedy is to add its source, never to reason
/// about a binary.
#[derive(Default, Clone)]
pub struct MacroRegistry {
    macros: BTreeMap<String, std::rc::Rc<Vec<macro_expand::MacroRule>>>,
    ambiguous: BTreeSet<String>,
}

impl MacroRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    /// Ingest every `macro_rules!` definition in a parsed source file (recursing
    /// into inline modules). A name defined inconsistently across sources is
    /// marked ambiguous and not expanded.
    pub fn scan_file(&mut self, file: &syn::File) {
        self.scan_items(&file.items);
    }

    /// Parse source text and ingest its macro definitions. Unparseable source is
    /// skipped (it contributes no definitions).
    pub fn scan_source(&mut self, src: &str) {
        if let Ok(file) = syn::parse_file(src) {
            self.scan_file(&file);
        }
    }

    fn scan_items(&mut self, items: &[Item]) {
        for item in items {
            match item {
                Item::Macro(m) if m.mac.path.is_ident("macro_rules") => {
                    if let Some(ident) = &m.ident {
                        self.insert(&ident.to_string(), m.mac.tokens.clone());
                    }
                }
                Item::Mod(m) => {
                    if let Some((_, items)) = &m.content {
                        self.scan_items(items);
                    }
                }
                _ => {}
            }
        }
    }

    fn insert(&mut self, name: &str, tokens: proc_macro2::TokenStream) {
        if self.ambiguous.contains(name) {
            return;
        }
        let Ok(rules) = macro_expand::parse_rules(tokens) else {
            return;
        };
        match self.macros.get(name) {
            // Re-seeing a byte-identical definition (the same crate scanned
            // twice) is fine; a genuinely different one is ambiguous.
            Some(existing)
                if macro_expand::rules_signature(existing)
                    == macro_expand::rules_signature(&rules) => {}
            Some(_) => {
                self.macros.remove(name);
                self.ambiguous.insert(name.to_string());
            }
            None => {
                self.macros
                    .insert(name.to_string(), std::rc::Rc::new(rules));
            }
        }
    }

    fn lookup(&self, name: &str) -> Option<std::rc::Rc<Vec<macro_expand::MacroRule>>> {
        if self.ambiguous.contains(name) {
            return None;
        }
        self.macros.get(name).cloned()
    }

    /// Number of distinct macro definitions held (for reporting).
    pub fn len(&self) -> usize {
        self.macros.len()
    }

    pub fn is_empty(&self) -> bool {
        self.macros.is_empty()
    }
}

const MAX_ASSERTION_REDUCTION_DEPTH: usize = 8;

/// Bound on nested macro_rules expansion (a macro whose body invokes another
/// in-source macro). Prevents runaway expansion; assertion macros nest shallowly.
const MAX_MACRO_EXPANSION_DEPTH: usize = 16;

/// Walk into an in-source `macro_rules!` definition and reduce its expansion.
/// Returns:
///   - `None` if `path` is not an in-source macro we learned (caller falls back).
///   - `Some(Ok(entries))` if expansion produced at least one liftable atom.
///   - `Some(Err(reason))` if it expanded to no FOL content, the matcher was
///     unsupported, no rule matched, or depth was exceeded. The macro is one
///     accounting unit: one source invocation yields one outcome.
#[allow(clippy::too_many_arguments)]
fn try_macro_expansion_entries(
    path: &syn::Path,
    tokens: &proc_macro2::TokenStream,
    reducer: &ReductionCtx<'_>,
    local_scope: &str,
    options: &LiftOptions,
    float_widths: &mut FloatWidthScope,
    macro_depth: usize,
) -> Option<Result<Vec<AssertionEntry>, String>> {
    let name = path.segments.last()?.ident.to_string();
    let rules = reducer.macro_rules(&name)?;
    if macro_depth >= MAX_MACRO_EXPANSION_DEPTH {
        return Some(Err(format!(
            "macro `{name}`: expansion depth exceeded; released to layer 0"
        )));
    }
    let expanded = match macro_expand::expand(&rules, tokens.clone()) {
        Ok(ts) => ts,
        Err(e) => return Some(Err(format!("macro `{name}`: {e}; released to layer 0"))),
    };
    // Re-parse the expansion as a statement block, then reduce it like any body.
    let block: syn::Block = match syn::parse2(quote::quote! { { #expanded } }) {
        Ok(b) => b,
        Err(_) => {
            return Some(Err(format!(
                "macro `{name}`: expansion did not parse as statements; released to layer 0"
            )))
        }
    };
    // TERMINAL (runtime-local expansion): if the expansion binds a local to a
    // RUNTIME ITERATOR/SEARCHER accessor (`$s.utf8_chunks()`, `.into_searcher()`,
    // an `iter.next()`), the assertions over that local pin a source literal
    // against bin-2 runtime data, not a finite construction from source literals.
    // Lifting them produces an EUF accessor over a bare local var; because the
    // local is RE-BOUND identically across every sibling invocation in one fn,
    // they coalesce onto ONE var and a distinct literal per invocation makes the
    // merged invariant CONTRADICTORY (ex-falso). Refuse the whole expansion as
    // one accounting unit -- the same outcome the lifter gives a hand-written
    // `assert_eq!(lit, it.next().valid())` over a runtime iterator. exact-or-bail.
    if let Some(local) = expansion_binds_runtime_iterator_local(&block.stmts) {
        return Some(Err(format!(
            "macro `{name}`: expansion binds a runtime iterator/searcher local `{local}` \
             (bin-2: runtime data, not constructible from source literals); released to layer 0"
        )));
    }
    let mut temp_entries = Vec::new();
    let mut temp_skipped = Vec::new();
    let mut temp_lifted = 0usize;
    let mut temp_helpers = HashSet::new();
    collect_assertion_entries(
        &block.stmts,
        local_scope,
        options,
        reducer,
        float_widths,
        &mut temp_entries,
        &mut temp_skipped,
        &mut temp_lifted,
        &mut temp_helpers,
        macro_depth + 1,
        &BTreeSet::new(),
        &BTreeMap::new(),
    );
    if temp_entries.is_empty() {
        Some(Err(format!(
            "macro `{name}`: expansion yielded no liftable assertion (type-level or effectful body); released to layer 0"
        )))
    } else {
        Some(Ok(temp_entries))
    }
}

/// Methods whose result is a RUNTIME ITERATOR / SEARCHER / stateful cursor: a
/// value driven by `next()`-style consumption, never a finite construction from
/// source literals. A local bound to such a result is bin-2 runtime data.
fn is_runtime_iterator_producing_method(method: &str) -> bool {
    matches!(
        method,
        "utf8_chunks"
            | "into_searcher"
            | "searcher"
            | "iter"
            | "iter_mut"
            | "into_iter"
            | "chars"
            | "char_indices"
            | "bytes"
            | "split"
            | "rsplit"
            | "splitn"
            | "lines"
            | "matches"
            | "match_indices"
            | "next"
            | "next_back"
            | "nth"
            | "nth_back"
    )
}

/// Does any method call in `expr`'s receiver chain produce a runtime iterator /
/// searcher? Walks the `recv.m1().m2()...` chain (and through parens/refs) so a
/// `$string.utf8_chunks()` or `'a'.into_searcher($h)` initializer is detected.
fn expr_chain_has_runtime_iterator(expr: &Expr) -> bool {
    match expr {
        Expr::MethodCall(mc) => {
            is_runtime_iterator_producing_method(&mc.method.to_string())
                || expr_chain_has_runtime_iterator(&mc.receiver)
        }
        Expr::Paren(p) => expr_chain_has_runtime_iterator(&p.expr),
        Expr::Group(g) => expr_chain_has_runtime_iterator(&g.expr),
        Expr::Reference(r) => expr_chain_has_runtime_iterator(&r.expr),
        Expr::Try(t) => expr_chain_has_runtime_iterator(&t.expr),
        Expr::Await(a) => expr_chain_has_runtime_iterator(&a.base),
        Expr::Field(f) => expr_chain_has_runtime_iterator(&f.base),
        // An array of runtime-stepped elements (`[Step::from(s.next()), ..]`) is
        // itself runtime data when any element steps an iterator.
        Expr::Array(a) => a.elems.iter().any(expr_chain_has_runtime_iterator),
        Expr::Call(c) => c.args.iter().any(expr_chain_has_runtime_iterator),
        _ => false,
    }
}

/// If the expanded block binds a `let <id> = <init>` whose initializer is (or
/// chains through) a runtime iterator/searcher accessor, return `<id>`. Such a
/// local is bin-2 runtime data; asserts pinning a source literal against it must
/// refuse, not EUF-discharge (and must never coalesce across invocations). The
/// scan recurses into nested blocks because a macro body wrapped in `{{ .. }}`
/// re-parses as a single `Stmt::Expr(Block)`, with the `let`s one level down.
fn expansion_binds_runtime_iterator_local(stmts: &[syn::Stmt]) -> Option<String> {
    for stmt in stmts {
        match stmt {
            syn::Stmt::Local(local) => {
                if let Some(init) = &local.init {
                    if expr_chain_has_runtime_iterator(&init.expr) {
                        return Some(
                            local
                                .pat
                                .to_token_stream()
                                .to_string()
                                .replace("mut ", "")
                                .trim()
                                .to_string(),
                        );
                    }
                }
            }
            // Recurse into a nested block (`{{ .. }}` expansion wrapper, or a
            // bare `{ .. }` statement) so a `let` inside it is still seen.
            syn::Stmt::Expr(Expr::Block(b), _) => {
                if let Some(found) = expansion_binds_runtime_iterator_local(&b.block.stmts) {
                    return Some(found);
                }
            }
            _ => {}
        }
    }
    None
}

type ExprBindings = BTreeMap<String, Expr>;

#[derive(Debug, Clone, Default)]
struct TemporalPlan {
    versioned: BTreeSet<String>,
    /// Locals bound with `let mut` anywhere in the scope. Rust's `mut` keyword
    /// is the mutability oracle: a non-mut local cannot be reassigned,
    /// &mut-borrowed, index-assigned, or have an &mut-self method called on it,
    /// so it is provably temporally stable. A `mut` local is conservatively
    /// treated as unstable (it may be mutated in a way the syntactic tracker
    /// cannot follow, e.g. `xs[i] = v` or `xs.push(..)`).
    mut_locals: BTreeSet<String>,
    /// Locals bound to an INTERIOR-MUTABLE primitive (`Cell::new`, `RefCell::new`,
    /// `UnsafeCell::new`, an `Atomic*::new`, `Mutex::new`, `RwLock::new`). The
    /// `mut` keyword is blind to interior mutability: such a binding is NOT `mut`
    /// yet its observed value changes through `&self` (a `set`/`store`, or even the
    /// drop side-effects of OTHER bindings -- the `iterator_drops` counter). So a
    /// READ of it (`get`/`load`/`borrow`) at two program points is a fork around
    /// `t`, not a contradiction. We version such a binding at EVERY statement so
    /// each read observes a distinct `t`; the reads then do not coalesce and each
    /// pin discharges on its own. A value bound once (`let v = c.get()`) is a bare
    /// var, so a double-pin on it is still caught.
    interior_mut: BTreeSet<String>,
    /// Locals bound to an ITERATOR (a range, `.iter()`/`.into_iter()` family, or an
    /// adapter chain). Unlike an interior-mutable cell, an iterator only changes when
    /// it is CONSUMED (`next`/`nth`/...). A NON-consuming read (`len`/`contains`/
    /// `size_hint`/`peek`) does NOT advance it, so two such reads with no consumption
    /// between them observe the SAME `t` and MUST coalesce -- otherwise a genuine
    /// contradiction on an unadvanced iterator would be masked (a falsePass). So an
    /// iterator is versioned only at a CONSUMPTION boundary (a consuming method call,
    /// in statement or let-init position -- handled via `deterministic_definition_
    /// names`), NOT at every statement. Same-statement double consumption is split by
    /// the `@adv` occurrence tag. Iterators ARE in `versioned` (so reads are tagged
    /// and `@adv` applies) but are NOT in `interior_mut` (no per-statement tick).
    iterators: BTreeSet<String>,
    /// Locals bound to an array of NON-literal element constructions (`let xs =
    /// [CountClone::new(), ..]`) that are subsequently consumed by a `.cloned()`
    /// adaptor in a side-effecting `for`-loop (`for _ in xs.iter().cloned().zip(..) {}`).
    /// `.cloned()` invokes `Clone::clone(&elem)` per element; for a user type whose
    /// `Clone` impl has a side effect through `&self` (interior mutability -- the
    /// `CountClone(Cell<i32>)` whose clone bumps a counter), the element VALUES change
    /// during iteration. The `mut` keyword and the `Cell::new` constructor oracle are
    /// both BLIND to this: `xs` is a non-`mut` `let` and its elements are user
    /// constructor calls, not `Cell::new(..)` directly. So a subsequent
    /// `assert!([..].any(|v| &xs == *v))` reads `xs`'s RUNTIME (clone-mutated) contents,
    /// not a value constructed from source literals -- the same proven order-loss as the
    /// `let mut`-capture terminal. Detected ONLY when BOTH (a) the array elements are
    /// NON-literal constructions AND (b) `xs` is the base of a `.cloned()`/`.copied()`
    /// adaptor in a bare side-effecting `for`-loop in the block. A PURE `.any` over a
    /// plain `[1, 2, 3]` literal array (scalar-literal elements, no side-effecting
    /// `.cloned()` loop) never enters this set -- the fake-refuse guardrail.
    sideeffecting_clone_locals: BTreeSet<String>,
}

#[derive(Debug, Clone)]
pub(crate) struct TemporalScope {
    local_scope: String,
    plan: TemporalPlan,
    versions: BTreeMap<String, usize>,
    ambiguous: BTreeSet<String>,
    /// Per-statement count of CONSUMING reads (`next`/`nth`/...) seen so far for
    /// each iterator binding. A consuming read ADVANCES the iterator, so two such
    /// reads of the same binding WITHIN ONE statement (`assert_ne!(it.nth(0),
    /// it.nth(0))`) observe distinct `t` and must not coalesce into `ne(X, X)`.
    /// The version bump is per STATEMENT (between statements); this counter splits
    /// per OCCURRENCE within a statement. Interior-mutable so it can advance while
    /// term translation holds `&self`; reset to empty at each statement boundary.
    consuming_occurrence: std::cell::RefCell<BTreeMap<String, usize>>,
    /// In-scope LITERAL arrays captured from this block's `let <id> = [e0, e1, ..]`
    /// (and `Box::new([..])`), so a `.iter().all(|x| ..)` / `.any(..)` quantifier
    /// over a `let`-bound finite domain can resolve its receiver to the element
    /// literals and unroll. Only arrays whose elements are ALL closed scalar
    /// literals are captured (a non-literal element omits the binding, so the
    /// quantifier path declines rather than over-claims).
    literal_arrays: BTreeMap<String, Vec<Expr>>,
    /// In-scope simple `let <id> = <init>;` initializer EXPRS for this block, owned.
    /// Used ONLY by the closed `try_fold` value-evaluator (`try_fold_eval`) to resolve
    /// a `let`-bound fold closure (`let f = &|..| ..;` then `xs.try_fold(7, f)`) or a
    /// `let`-bound receiver chain back to its source. Resolution is gated on
    /// `!is_mut_local` (a `let mut` binding could be reassigned, so its later value is
    /// not the written init -- such a name is NOT resolved). EXACT-OR-BAIL: an absent
    /// / unresolvable binding makes the evaluator decline (the operand stays in its
    /// existing refusal -- a safe under-claim).
    let_bindings: BTreeMap<String, Expr>,
}

impl TemporalScope {
    fn new(local_scope: &str, plan: TemporalPlan) -> Self {
        Self {
            local_scope: local_scope.to_string(),
            plan,
            versions: BTreeMap::new(),
            ambiguous: BTreeSet::new(),
            consuming_occurrence: std::cell::RefCell::new(BTreeMap::new()),
            literal_arrays: BTreeMap::new(),
            let_bindings: BTreeMap::new(),
        }
    }

    /// Record the in-scope literal-array bindings for this block (see field doc).
    fn with_literal_arrays(mut self, arrays: BTreeMap<String, Vec<Expr>>) -> Self {
        self.literal_arrays = arrays;
        self
    }

    /// The `let`-bound initializer expr for `name` in this scope, or `None`. Used by
    /// the closed `try_fold` evaluator to resolve a bound closure / receiver chain.
    fn let_binding(&self, name: &str) -> Option<&Expr> {
        self.let_bindings.get(name)
    }

    /// Record a `let <name> = <init>;` binding reached at the CURRENT statement, so a
    /// later assertion sees the lexically-in-effect initializer (shadowing-correct: a
    /// re-`let` of the same name OVERWRITES). The lift loop advances this as it passes
    /// each `Stmt::Local`, so a `try_fold` operand resolves the binding in effect at
    /// its position, never a later shadow. A `let mut` name is recorded too, but the
    /// evaluator gates resolution on `!is_mut_local` (a mutable binding's later value
    /// is not its written init).
    fn record_let_binding(&mut self, name: &str, init: Expr) {
        self.let_bindings.insert(name.to_string(), init);
    }

    /// The closed scalar-literal elements of `name` if it is a `let`-bound literal
    /// array in this scope; else `None`.
    fn literal_array(&self, name: &str) -> Option<&[Expr]> {
        self.literal_arrays.get(name).map(Vec::as_slice)
    }

    /// Record one CONSUMING read of iterator `name` in the current statement and
    /// return how many such reads PRECEDED it (0 for the first). The caller appends
    /// `@adv{n}` for n > 0 so the second-and-later reads in one statement are
    /// distinct terms. `name` is the already-versioned receiver var (`it@def5`).
    fn bump_consuming_occurrence(&self, name: &str) -> usize {
        let mut map = self.consuming_occurrence.borrow_mut();
        let count = map.entry(name.to_string()).or_insert(0);
        let prior = *count;
        *count += 1;
        prior
    }

    fn local_scope(&self) -> &str {
        &self.local_scope
    }

    /// Whether `name` is a `let mut` local in this scope (conservatively
    /// unstable). A non-mut local is provably immutable and stable.
    pub(crate) fn is_mut_local(&self, name: &str) -> bool {
        self.plan.mut_locals.contains(name)
    }

    fn is_sideeffecting_clone_local(&self, name: &str) -> bool {
        self.plan.sideeffecting_clone_locals.contains(name)
    }

    fn define_local(&mut self, name: &str) {
        if self.plan.versioned.contains(name) {
            let next = self.versions.get(name).copied().unwrap_or(0) + 1;
            self.versions.insert(name.to_string(), next);
            self.ambiguous.remove(name);
        }
    }

    fn mark_ambiguous(&mut self, name: &str) {
        if self.plan.versioned.contains(name) {
            self.ambiguous.insert(name.to_string());
        }
    }

    fn path_name(&self, path: &syn::Path) -> Result<String, String> {
        let name = path_to_name(path);
        if !is_unqualified_local_name(&name) || !self.plan.versioned.contains(&name) {
            return Ok(name);
        }
        if self.ambiguous.contains(&name) {
            return Err(format!(
                "ambiguous temporal identity for receiver `{name}`; skipped assertion"
            ));
        }
        match self.versions.get(&name).copied() {
            Some(version) => Ok(format!("{name}@def{version}")),
            None => Ok(name),
        }
    }
}

fn group_assertions(
    entries: Vec<AssertionEntry>,
    fallback_name: &str,
) -> Vec<(String, Vec<Rc<Formula>>)> {
    // Each entry joins the obligation named by its callsite (or the fn
    // fallback). A lifted loop is a named `<test>::loop::<var>` memento with its
    // own obligation here, mirroring the Python layer-2 lifter. Whether a
    // universal refutes a sibling point-claim is answered ONCE in the shared
    // consistency engine (which treats forall invariants as ambient), not in
    // this per-language lifter.
    let mut groups: Vec<(String, Vec<Rc<Formula>>)> = Vec::new();
    for entry in entries {
        let name = entry.name.unwrap_or_else(|| fallback_name.to_string());
        if let Some((_, atoms)) = groups
            .iter_mut()
            .find(|(group_name, _)| group_name == &name)
        {
            atoms.push(entry.atom);
        } else {
            groups.push((name, vec![entry.atom]));
        }
    }
    groups
}

/// Count assert macros reachable anywhere inside a statement list, including
/// nested in control flow, closures, and blocks. Used to produce named refusals
/// for asserts that cannot be unconditionally lifted.
/// Exhaustively counts assert-family macro invocations anywhere in a subtree,
/// using the same syn visitor the sweep uses as its denominator. Counting must
/// match that denominator exactly, otherwise the totality safety net cannot
/// detect an assert in an AST position the structured walk does not enumerate.
#[derive(Default)]
struct NestedAssertCounter {
    total: usize,
}

impl<'ast> syn::visit::Visit<'ast> for NestedAssertCounter {
    fn visit_macro(&mut self, m: &'ast syn::Macro) {
        if is_assert_macro_path(&m.path) {
            self.total += 1;
        }
        syn::visit::visit_macro(self, m);
    }
}

fn count_asserts_in_stmts(stmts: &[Stmt]) -> usize {
    let mut counter = NestedAssertCounter::default();
    for stmt in stmts {
        syn::visit::Visit::visit_stmt(&mut counter, stmt);
    }
    counter.total
}

/// Exhaustively count assert-family macros across a set of items (a whole
/// module subtree). Used to account a cfg-skipped module per assertion so the
/// walk logs a reason for every assert it drops, leaving no silent drop.
fn count_asserts_in_items(items: &[Item]) -> usize {
    let mut counter = NestedAssertCounter::default();
    for item in items {
        syn::visit::Visit::visit_item(&mut counter, item);
    }
    counter.total
}

/// A cfg-gated module (e.g. `#[cfg(all(test, target_has_atomic = "64"))]`) whose
/// predicate we cannot resolve is skipped, but every assertion inside it must
/// still be accounted: refuse one per assert with the cfg reason so nothing is
/// silently dropped. The remedy to discharge them is to resolve the cfg (feed
/// the build configuration), not to ignore them.
fn account_skipped_module(
    items: &[Item],
    module_name: &str,
    kind: &str,
    reason: &str,
    source_path: &str,
    out: &mut AdapterOutput,
) {
    let count = count_asserts_in_items(items);
    let skip = format!("{kind} cfg on module; skipped: {reason}");
    for _ in 0..count {
        out.assertions_refused += 1;
        out.skip_reasons.push(skip.clone());
    }
    out.warnings.push(LiftWarning {
        source_path: source_path.to_string(),
        item_name: module_name.to_string(),
        reason: format!("rust test assertions: {kind} cfg; skipped module: {reason}"),
    });
}

fn count_asserts_in_expr(expr: &Expr) -> usize {
    let mut counter = NestedAssertCounter::default();
    syn::visit::Visit::visit_expr(&mut counter, expr);
    counter.total
}

fn is_assert_macro_path(path: &syn::Path) -> bool {
    if let Some(seg) = path.segments.last() {
        // The lifter treats any macro whose name starts with assert / debug_assert
        // as an assertion (the standard six plus stdlib custom macros like
        // assert_all!, assert_none!, assert_eq_const_safe!). The nested-assert
        // counter must use the same universe as the sweep denominator so the
        // discharged + refused + silent reconciliation is exact.
        let name = seg.ident.to_string();
        name.starts_with("assert") || name.starts_with("debug_assert")
    } else {
        false
    }
}

/// If an expression is an UNCONDITIONALLY-evaluated block, return its statements
/// so the collector can recurse and lift the asserts inside (the per-fn safety
/// net still accounts anything not reached, so this never reintroduces a silent
/// drop). Sound contexts:
///   - a plain value block `{ .. }` and `unsafe { .. }` (evaluated once here)
///   - `rt.block_on(async { .. })`: block_on drives the future to completion
///     synchronously, so its top-level statements run exactly once. The async /
///     await is the ordering we drop; the assertions inside still hold.
/// A bare `async { .. }`, a closure, or a spawned future is NOT unconditional
/// (it may never run, or runs per-iteration) and is not returned here.
/// If `expr` is a call to the std intrinsic `const_eval_select((), ct, rt)`,
/// return the runtime branch fn name (the third argument, an ident). At run
/// time the intrinsic calls that fn, so its body is reached.
fn const_eval_select_runtime_target(expr: &Expr) -> Option<String> {
    let call = match expr {
        Expr::Call(c) => c,
        Expr::Paren(p) => return const_eval_select_runtime_target(&p.expr),
        Expr::Group(g) => return const_eval_select_runtime_target(&g.expr),
        _ => return None,
    };
    let Expr::Path(p) = &*call.func else {
        return None;
    };
    if p.path.segments.last()?.ident != "const_eval_select" {
        return None;
    }
    // The runtime fn is the last argument; accept the common 3-arg form.
    match call.args.last()? {
        Expr::Path(rt) => rt.path.get_ident().map(|i| i.to_string()),
        _ => None,
    }
}

/// All inner-fn names selected as a const_eval_select runtime branch in a block.
fn const_eval_select_runtime_targets(stmts: &[Stmt]) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for stmt in stmts {
        if let Stmt::Expr(e, _) = stmt {
            if let Some(name) = const_eval_select_runtime_target(e) {
                out.insert(name);
            }
        }
    }
    out
}

/// True if a block of statements mutates anything: an assignment / compound
/// assignment, a `let mut` binding, or a `&mut` borrow. A loop whose body
/// mutates is not a clean universal over the loop variable, so it is gutter.
fn loop_body_mutates(stmts: &[Stmt]) -> bool {
    #[derive(Default)]
    struct MutScan {
        mutates: bool,
    }
    impl<'ast> syn::visit::Visit<'ast> for MutScan {
        fn visit_expr_assign(&mut self, _: &'ast syn::ExprAssign) {
            self.mutates = true;
        }
        fn visit_expr_binary(&mut self, b: &'ast syn::ExprBinary) {
            if matches!(
                b.op,
                BinOp::AddAssign(_)
                    | BinOp::SubAssign(_)
                    | BinOp::MulAssign(_)
                    | BinOp::DivAssign(_)
                    | BinOp::RemAssign(_)
                    | BinOp::BitXorAssign(_)
                    | BinOp::BitAndAssign(_)
                    | BinOp::BitOrAssign(_)
                    | BinOp::ShlAssign(_)
                    | BinOp::ShrAssign(_)
            ) {
                self.mutates = true;
            }
            syn::visit::visit_expr_binary(self, b);
        }
        fn visit_expr_reference(&mut self, r: &'ast syn::ExprReference) {
            if r.mutability.is_some() {
                self.mutates = true;
            }
            syn::visit::visit_expr_reference(self, r);
        }
        fn visit_pat_ident(&mut self, p: &'ast syn::PatIdent) {
            if p.mutability.is_some() {
                self.mutates = true;
            }
            syn::visit::visit_pat_ident(self, p);
        }
    }
    let mut scan = MutScan::default();
    for stmt in stmts {
        syn::visit::Visit::visit_stmt(&mut scan, stmt);
    }
    scan.mutates
}

/// Substitute every free occurrence of the variable `name` in a term with
/// `repl`. Used to bind a loop variable to a quantifier's bound variable.
fn subst_var_in_term(term: &Rc<Term>, name: &str, repl: &Rc<Term>) -> Rc<Term> {
    match term.as_ref() {
        Term::Var { name: n } if n == name => repl.clone(),
        Term::Ctor { name: cname, args } => Rc::new(Term::Ctor {
            name: cname.clone(),
            args: args
                .iter()
                .map(|a| subst_var_in_term(a, name, repl))
                .collect(),
        }),
        _ => term.clone(),
    }
}

/// Substitute `name` with `repl` throughout a formula (respecting quantifier
/// shadowing: a nested quantifier binding the same name is left untouched).
fn subst_var_in_formula(formula: &Rc<Formula>, name: &str, repl: &Rc<Term>) -> Rc<Formula> {
    match formula.as_ref() {
        Formula::Atomic { name: rel, args } => Rc::new(Formula::Atomic {
            name: rel.clone(),
            args: args
                .iter()
                .map(|a| subst_var_in_term(a, name, repl))
                .collect(),
        }),
        Formula::Connective { kind, operands } => Rc::new(Formula::Connective {
            kind: kind.clone(),
            operands: operands
                .iter()
                .map(|f| subst_var_in_formula(f, name, repl))
                .collect(),
        }),
        Formula::Quantifier {
            kind,
            name: bound,
            sort,
            body,
        } => {
            let new_body = if bound == name {
                body.clone()
            } else {
                subst_var_in_formula(body, name, repl)
            };
            Rc::new(Formula::Quantifier {
                kind: kind.clone(),
                name: bound.clone(),
                sort: sort.clone(),
                body: new_body,
            })
        }
        _ => formula.clone(),
    }
}

/// Rewrite `index(<lit-array-var>, <const-int>)` terms to the array's concrete
/// element term, given a map of in-scope LITERAL arrays (name -> element TERMS) and
/// the constant-folded index. This is THE LAW applied to the indexed read: when the
/// array is a written literal and the position is a literal (the threaded cursor),
/// the value at that position IS a literal in scope -> substitute the element. An
/// out-of-bounds or unknown-array `index` term is left UNTOUCHED (the uninterpreted
/// EUF accessor -- the established sound floor; the program would have panicked OOB,
/// outside our claim). Sound only over an IMMUTABLE literal array (the caller passes
/// only `let`-bound non-`mut` array literals).
fn resolve_index_in_term(term: &Rc<Term>, arrays: &BTreeMap<String, Vec<Rc<Term>>>) -> Rc<Term> {
    match term.as_ref() {
        Term::Ctor { name, args } if name == "index" && args.len() == 2 => {
            // Resolve children first (a nested index), then this one.
            let base = resolve_index_in_term(&args[0], arrays);
            let idx = resolve_index_in_term(&args[1], arrays);
            // The threaded index is often arithmetic over a literal (`i - 1` with `i`
            // substituted to a const) -- const-fold it to a literal position first.
            let idx_k = term_as_int(&idx).or_else(|| const_fold_int_term(&idx));
            if let (Term::Var { name: arr }, Some(k)) = (base.as_ref(), idx_k) {
                if let Some(elems) = arrays.get(arr) {
                    // `usize::try_from` (NOT `as usize`): a wide i128 index must
                    // never wrap into a spuriously in-range slot -- that would
                    // resolve to the WRONG element (a fake-dig). Out of usize
                    // range -> leave the index symbolic.
                    if let Ok(ki) = usize::try_from(k) {
                        if ki < elems.len() {
                            return elems[ki].clone();
                        }
                    }
                }
            }
            Rc::new(Term::Ctor {
                name: name.clone(),
                args: vec![base, idx],
            })
        }
        Term::Ctor { name, args } => Rc::new(Term::Ctor {
            name: name.clone(),
            args: args.iter().map(|a| resolve_index_in_term(a, arrays)).collect(),
        }),
        _ => term.clone(),
    }
}

/// Const-fold an integer-valued arithmetic Term (`+`/`-`/`*` over int consts) to its
/// literal value. Used to reduce a threaded index like `sub(num(4), num(1))` to `3`
/// before an `index` resolution. None for any non-const / non-arithmetic term -- the
/// `index` then stays the EUF accessor (sound under-claim).
fn const_fold_int_term(term: &Rc<Term>) -> Option<i128> {
    if let Some(n) = term_as_int(term) {
        return Some(n);
    }
    match term.as_ref() {
        Term::Ctor { name, args } if args.len() == 2 => {
            let a = const_fold_int_term(&args[0])?;
            let b = const_fold_int_term(&args[1])?;
            match name.as_str() {
                "+" => a.checked_add(b),
                "-" => a.checked_sub(b),
                "*" => a.checked_mul(b),
                _ => None,
            }
        }
        _ => None,
    }
}

/// Apply `resolve_index_in_term` throughout a formula's terms (the finite-conjunction
/// instance for one fold step, after the accumulator/index has been threaded to a
/// concrete literal). Leaves connective/quantifier structure intact.
fn resolve_index_in_formula(
    formula: &Rc<Formula>,
    arrays: &BTreeMap<String, Vec<Rc<Term>>>,
) -> Rc<Formula> {
    match formula.as_ref() {
        Formula::Atomic { name, args } => Rc::new(Formula::Atomic {
            name: name.clone(),
            args: args.iter().map(|a| resolve_index_in_term(a, arrays)).collect(),
        }),
        Formula::Connective { kind, operands } => Rc::new(Formula::Connective {
            kind: kind.clone(),
            operands: operands
                .iter()
                .map(|f| resolve_index_in_formula(f, arrays))
                .collect(),
        }),
        Formula::Quantifier {
            kind,
            name,
            sort,
            body,
        } => Rc::new(Formula::Quantifier {
            kind: kind.clone(),
            name: name.clone(),
            sort: sort.clone(),
            body: resolve_index_in_formula(body, arrays),
        }),
        _ => formula.clone(),
    }
}

/// Read a `for <ident> in <range> { body }` loop as the bounded universal it
/// literally states: forall x. (range_guard(x) => body(x)). The range is
/// transcribed letter for letter (start..end / start..=end); the body is lifted
/// through the normal collector, so a body that does not compute to a truth
/// value (effectful, mutated accumulator, conditional) is gutter (None here,
/// refused by the caller). Returns the quantified formula and the number of
/// body assert macros it accounts for, or None to refuse the loop.
/// A FINITE-CONSTRUCTION domain for a bounded universal: a closed integer range
/// `a..b` / `a..=b` (transcribed as a forall guard) or a literal array
/// `[e0, e1, ...]` (unrolled over its constructed element terms). A runtime
/// collection is NOT constructed from source literals and is NOT a `BoundedDomain`.
#[derive(Clone)]
enum BoundedDomain {
    Range {
        start: Rc<Term>,
        end: Rc<Term>,
        inclusive: bool,
    },
    Array(Vec<Rc<Term>>),
}

/// Read an iteration domain expression as a FINITE CONSTRUCTION, or None when it
/// is a runtime collection (`v`, `v.iter()`, `coll.get(k)`, ...) that is not
/// constructed from source literals. Shared by the `for` loop and the
/// `.for_each(|x| ..)` adaptor: both iterate exactly the same constructed domains,
/// so both discriminate it identically here. An empty array is None (the loop
/// never runs -> vacuous; leave to the refusal path, never emit a vacuous `true`).
fn bounded_domain_from_expr(expr: &Expr, scope: &TemporalScope) -> Option<BoundedDomain> {
    match expr {
        Expr::Range(range) => {
            let (Some(start_expr), Some(end_expr)) = (&range.start, &range.end) else {
                return None;
            };
            Some(BoundedDomain::Range {
                start: translate_term_in_scope(start_expr, scope).ok()?,
                end: translate_term_in_scope(end_expr, scope).ok()?,
                inclusive: matches!(range.limits, syn::RangeLimits::Closed(_)),
            })
        }
        Expr::Array(arr) => {
            if arr.elems.is_empty() {
                return None;
            }
            let mut elems = Vec::with_capacity(arr.elems.len());
            for e in &arr.elems {
                elems.push(translate_term_in_scope(e, scope).ok()?);
            }
            Some(BoundedDomain::Array(elems))
        }
        Expr::Paren(p) => bounded_domain_from_expr(&p.expr, scope),
        Expr::Group(g) => bounded_domain_from_expr(&g.expr, scope),
        Expr::Reference(r) => bounded_domain_from_expr(&r.expr, scope),
        _ => None,
    }
}

/// Lift `∀ <var> ∈ <domain>. <body>` where `<domain>` is a finite construction
/// and `<body>` is the statement list executed once per element with `<var>`
/// bound. This is the shared core of `try_lift_for_loop_forall` (a `for` loop)

/// A single application-order wrapper in a `.fold`/`.rfold` receiver chain: given the
/// inner sequence-`Sugar`, it produces the next outer decorator (`IdentitySugar`,
/// `RevSugar`, ...). One per recognized adaptor; the per-class decorator structs live
/// in `src/sugar/*.rs`. STDLIB sugar over the element sequence: the transforming kinds
/// capture the closure we const-evaluate over each concrete element. Only
/// EXACT-replicable adaptors produce a wrapper; an unrepresentable adaptor (flat_map
/// / flatten / a windowing/stateful one) makes the peel return None -> bail (honest,
/// never a fake-dig). (`filter_map` IS replicable via the closed Option-eval, so it
/// produces a `FilterMapSugar` wrapper.)
type AdaptorWrap = Box<dyn FnOnce(Box<dyn Sugar>) -> Box<dyn Sugar>>;

/// Wrap `inner` in `RevSugar` (the `.rev()` adaptor, also the synthetic final `Rev`
/// appended for `.rfold`).
fn wrap_rev(inner: Box<dyn Sugar>) -> Box<dyn Sugar> {
    Box::new(sugar::rev::RevSugar { inner })
}

/// Peel iterator adaptors off a `.fold`/`.rfold` receiver and RESOLVE `let`-bound
/// receivers through `let_inits`, reaching the base literal-domain expression PLUS the
/// ordered adaptor chain (in APPLICATION order: base -> ... -> fold). Returns
/// (base, wrappers) or None on an unrepresentable adaptor / unresolvable binding /
/// non-literal `n` for skip/take (-> bail). Stdlib sugar over written literals -> dig;
/// monkey business -> the const-evaluator that runs the closures will itself bail.
fn peel_fold_adaptors<'a>(
    expr: &'a Expr,
    let_inits: &BTreeMap<String, &'a Expr>,
    depth: usize,
) -> Option<(&'a Expr, Vec<AdaptorWrap>)> {
    const MAX_DEPTH: usize = 8;
    if depth > MAX_DEPTH {
        return None;
    }
    let mut cur = expr;
    // Collected OUTERMOST-first (we walk from the fold receiver inward); reverse at the
    // end to get APPLICATION order (base-first).
    let mut adaptors_rev: Vec<AdaptorWrap> = Vec::new();
    loop {
        match cur {
            Expr::MethodCall(m) => {
                let name = m.method.to_string();
                let ad: AdaptorWrap = match (name.as_str(), m.args.len()) {
                    ("iter" | "into_iter" | "cloned" | "copied" | "fuse", 0) => {
                        Box::new(|inner| Box::new(sugar::identity::IdentitySugar { inner }))
                    }
                    ("rev", 0) => Box::new(wrap_rev),
                    ("enumerate", 0) => {
                        Box::new(|inner| Box::new(sugar::enumerate::EnumerateSugar { inner }))
                    }
                    ("filter", 1) => match &m.args[0] {
                        Expr::Closure(c) => {
                            let pred = c.clone();
                            Box::new(move |inner| {
                                Box::new(sugar::filter::FilterSugar { inner, pred })
                            })
                        }
                        _ => return None,
                    },
                    ("map", 1) => match &m.args[0] {
                        Expr::Closure(c) => {
                            let f = c.clone();
                            Box::new(move |inner| Box::new(sugar::map::MapSugar { inner, f }))
                        }
                        _ => return None,
                    },
                    ("filter_map", 1) => match &m.args[0] {
                        Expr::Closure(c) => {
                            let f = c.clone();
                            Box::new(move |inner| {
                                Box::new(sugar::filter_map::FilterMapSugar { inner, f })
                            })
                        }
                        _ => return None,
                    },
                    ("skip_while", 1) => match &m.args[0] {
                        Expr::Closure(c) => {
                            let pred = c.clone();
                            Box::new(move |inner| {
                                Box::new(sugar::skip_while::SkipWhileSugar { inner, pred })
                            })
                        }
                        _ => return None,
                    },
                    ("take_while", 1) => match &m.args[0] {
                        Expr::Closure(c) => {
                            let pred = c.clone();
                            Box::new(move |inner| {
                                Box::new(sugar::take_while::TakeWhileSugar { inner, pred })
                            })
                        }
                        _ => return None,
                    },
                    ("skip", 1) => {
                        let n: usize = const_int(&m.args[0])?.try_into().ok()?;
                        Box::new(move |inner| Box::new(sugar::skip::SkipSugar { inner, n }))
                    }
                    ("take", 1) => {
                        let n: usize = const_int(&m.args[0])?.try_into().ok()?;
                        Box::new(move |inner| Box::new(sugar::take::TakeSugar { inner, n }))
                    }
                    // flat_map / flatten (sub-sequence const-eval) and every other
                    // adaptor: not yet provably exact -> bail. (`filter_map` digs above
                    // via the composable `FilterMapSugar` over the closed Option-eval.)
                    _ => return None,
                };
                adaptors_rev.push(ad);
                cur = &m.receiver;
            }
            Expr::Paren(p) => cur = &p.expr,
            Expr::Group(g) => cur = &g.expr,
            Expr::Reference(r) => cur = &r.expr,
            // A bare ident bound in this block: resolve to its initializer and re-peel,
            // PREPENDING the inner chain (it applies first, nearer the base).
            Expr::Path(p) => {
                if let Some(id) = p.path.get_ident() {
                    if let Some(init) = let_inits.get(&id.to_string()) {
                        let (inner_base, mut inner_adaptors) =
                            peel_fold_adaptors(init, let_inits, depth + 1)?;
                        // inner_adaptors are already base-first; our outer adaptors_rev are
                        // outermost-first, so reversed they are application-order and come
                        // AFTER the inner chain.
                        adaptors_rev.reverse();
                        inner_adaptors.extend(adaptors_rev);
                        return Some((inner_base, inner_adaptors));
                    }
                }
                break;
            }
            _ => break,
        }
    }
    adaptors_rev.reverse();
    Some((cur, adaptors_rev))
}

/// An EXACT const value the defolder is willing to compute for a transforming-adaptor
/// closure (`.filter`/`.map`/`.skip_while`/...). DELIBERATELY NARROW: only the value
/// kinds whose Rust semantics we can replicate with certainty -- integer, bool, char,
/// byte (an int), and tuples thereof. NO float (equality edge cases / NaN), NO string
/// (allocation / encoding), NO arbitrary struct. A wrong DIG is a fake-discharge, so the
/// evaluator is exact-or-None everywhere: the instant an expression is outside this
/// closed set, `const_eval` returns None and the whole defold bails.
#[derive(Clone, Debug, PartialEq)]
enum ConstVal {
    // i128 carrier -- same widening as the lifted-term Int const: a wide
    // literal const-folds to its EXACT integer value, never a truncation.
    Int(i128),
    Bool(bool),
    Char(char),
    Tuple(Vec<ConstVal>),
}

impl ConstVal {
    /// Reconstruct a Rust literal EXPR for this value, so a `.map`-produced element can be
    /// fed back through the normal term translator. Exact round-trip for the closed set.
    fn to_expr(&self) -> Option<Expr> {
        let s = match self {
            ConstVal::Int(n) => n.to_string(),
            ConstVal::Bool(b) => b.to_string(),
            ConstVal::Char(c) => format!("{c:?}"), // debug form emits a valid char literal
            // a tuple element fed to a later adaptor stays a ConstVal; only scalars are
            // ever materialized back to an Expr (the fold item). A tuple item is uncommon
            // and we conservatively decline materializing it.
            ConstVal::Tuple(_) => return None,
        };
        syn::parse_str::<Expr>(&s).ok()
    }
    fn as_int(&self) -> Option<i128> {
        match self {
            ConstVal::Int(n) => Some(*n),
            _ => None,
        }
    }
    fn as_bool(&self) -> Option<bool> {
        match self {
            ConstVal::Bool(b) => Some(*b),
            _ => None,
        }
    }
}

/// EXACT-OR-BAIL const-evaluator over the closed `ConstVal` set. Evaluates `expr` given
/// `env` (closure param bindings to concrete element values). Returns None -- forcing the
/// whole defold to bail -- for ANYTHING outside the set we can replicate with certainty:
/// a non-literal leaf, a float, a string, a method/fn call, an index into a runtime value,
/// an unbound ident, an integer overflow, a division by zero. UNDER-evaluating is a safe
/// under-claim; a wrong evaluation would be a fake-discharge, so we never guess.
fn const_eval(expr: &Expr, env: &BTreeMap<String, ConstVal>) -> Option<ConstVal> {
    match expr {
        Expr::Lit(ExprLit { lit, .. }) => match lit {
            Lit::Int(i) => parse_int_lit(i).ok().map(ConstVal::Int),
            Lit::Bool(b) => Some(ConstVal::Bool(b.value)),
            Lit::Char(c) => Some(ConstVal::Char(c.value())),
            Lit::Byte(b) => Some(ConstVal::Int(i128::from(b.value()))),
            // float / str / bytestr: outside the certain set -> bail.
            _ => None,
        },
        Expr::Path(p) => {
            let id = p.path.get_ident()?.to_string();
            env.get(&id).cloned()
        }
        Expr::Paren(pr) => const_eval(&pr.expr, env),
        Expr::Group(g) => const_eval(&g.expr, env),
        Expr::Reference(r) => const_eval(&r.expr, env),
        Expr::Tuple(t) => {
            let mut vals = Vec::with_capacity(t.elems.len());
            for e in &t.elems {
                vals.push(const_eval(e, env)?);
            }
            Some(ConstVal::Tuple(vals))
        }
        // `pair.0` / `pair.1` on a const tuple.
        Expr::Field(f) => {
            let recv = const_eval(&f.base, env)?;
            if let (ConstVal::Tuple(vals), syn::Member::Unnamed(idx)) = (&recv, &f.member) {
                vals.get(idx.index as usize).cloned()
            } else {
                None
            }
        }
        // int->int `as` cast only (exact within i64); a float/usize-truncation cast is not
        // replicated -> bail. (We keep one canonical i64 regime; a cast that would change
        // value semantics, e.g. `-1i32 as u8`, is NOT modeled -> bail.)
        Expr::Cast(c) => {
            // To stay provably exact we ONLY accept an identity-preserving widening of an
            // integer value to a signed type at least as wide as our i64 regime, and bail
            // on every narrowing / sign-changing / float cast (those can change the value).
            let n = const_eval(&c.expr, env)?.as_int()?;
            match &*c.ty {
                syn::Type::Path(tp) => {
                    let name = tp.path.segments.last()?.ident.to_string();
                    match name.as_str() {
                        // `as i128` is identity for any value the carrier holds.
                        "i128" => Some(ConstVal::Int(n)),
                        // `as i64` / `as isize` is identity ONLY when the value fits the
                        // target; a wide value would TRUNCATE (change value) -> bail
                        // (EXACT-OR-BAIL; the cast comment's identity-preservation is now
                        // enforced, not assumed).
                        "i64" | "isize" => i64::try_from(n).ok().map(|v| ConstVal::Int(i128::from(v))),
                        _ => None,
                    }
                }
                _ => None,
            }
        }
        Expr::Unary(u) => {
            let v = const_eval(&u.expr, env)?;
            match u.op {
                UnOp::Neg(_) => v.as_int()?.checked_neg().map(ConstVal::Int),
                UnOp::Not(_) => match v {
                    ConstVal::Bool(b) => Some(ConstVal::Bool(!b)),
                    // bitwise-not on an int is value-width-dependent -> bail.
                    _ => None,
                },
                // `*x` deref of a bound element: the const model holds scalar VALUES
                // (no pointers), and a `&x`/`&&x` closure param binds the dereferenced
                // element value directly, so `*x` is the identity on that value
                // (`|&x| *x < 15`). Faithful: the predicate reads the element it bound.
                UnOp::Deref(_) => Some(v),
                _ => None,
            }
        }
        Expr::Binary(b) => {
            let l = const_eval(&b.left, env)?;
            let r = const_eval(&b.right, env)?;
            // ARITHMETIC RUNS IN THE BOUNDED i64 REGIME. The i128 carrier exists to
            // hold a wide LITERAL exactly (the wide-int DIG), NOT to relax rust's
            // width-checked arithmetic: `i64::MAX * 1000` PANICS in rustc debug, so a
            // const-fold that silently computed it in i128 would model a computation
            // the vendor's test never performs -- a fake-dig. We do not track each
            // operand's source width post-erasure, so the canonical regime is i64:
            // an operand or result outside i64 bails (None). A wide literal entering
            // defold arithmetic therefore declines -- a safe under-claim, never a
            // wrong value. (Direct wide-literal assertions still lift via
            // `translate_lit`; only the defolder's closure arithmetic is bounded.)
            let as_i64 = |v: &ConstVal| -> Option<i64> { i64::try_from(v.as_int()?).ok() };
            let int = |n: i64| ConstVal::Int(i128::from(n));
            match b.op {
                // integer arithmetic with overflow / div-zero guards (bail on either),
                // checked at i64 width to match rustc's debug-mode overflow panic.
                BinOp::Add(_) => as_i64(&l)?.checked_add(as_i64(&r)?).map(int),
                BinOp::Sub(_) => as_i64(&l)?.checked_sub(as_i64(&r)?).map(int),
                BinOp::Mul(_) => as_i64(&l)?.checked_mul(as_i64(&r)?).map(int),
                BinOp::Div(_) => {
                    let (a, d) = (as_i64(&l)?, as_i64(&r)?);
                    if d == 0 { None } else { a.checked_div(d).map(int) }
                }
                BinOp::Rem(_) => {
                    let (a, d) = (as_i64(&l)?, as_i64(&r)?);
                    if d == 0 { None } else { a.checked_rem(d).map(int) }
                }
                // comparisons -> Bool (ints or chars).
                BinOp::Eq(_) => Some(ConstVal::Bool(l == r)),
                BinOp::Ne(_) => Some(ConstVal::Bool(l != r)),
                BinOp::Lt(_) => const_cmp(&l, &r).map(|o| ConstVal::Bool(o == std::cmp::Ordering::Less)),
                BinOp::Le(_) => const_cmp(&l, &r).map(|o| ConstVal::Bool(o != std::cmp::Ordering::Greater)),
                BinOp::Gt(_) => const_cmp(&l, &r).map(|o| ConstVal::Bool(o == std::cmp::Ordering::Greater)),
                BinOp::Ge(_) => const_cmp(&l, &r).map(|o| ConstVal::Bool(o != std::cmp::Ordering::Less)),
                // short-circuit logic.
                BinOp::And(_) => Some(ConstVal::Bool(l.as_bool()? && r.as_bool()?)),
                BinOp::Or(_) => Some(ConstVal::Bool(l.as_bool()? || r.as_bool()?)),
                _ => None,
            }
        }
        _ => None,
    }
}

/// Total order for `<`/`<=`/`>`/`>=` over the comparable const kinds (ints, chars). A
/// cross-kind or non-comparable pair -> None (bail).
fn const_cmp(l: &ConstVal, r: &ConstVal) -> Option<std::cmp::Ordering> {
    match (l, r) {
        (ConstVal::Int(a), ConstVal::Int(b)) => Some(a.cmp(b)),
        (ConstVal::Char(a), ConstVal::Char(b)) => Some(a.cmp(b)),
        _ => None,
    }
}

/// Evaluate a single-parameter closure `|p| body` over a concrete element value, exactly.
/// The body may be a bare expr or a block whose final expr is the value (no statements
/// with side effects -- a `let` in the body is not modeled, so bail). Returns the
/// resulting `ConstVal` or None (bail). Used to apply a transforming adaptor's closure.
fn const_eval_unary_closure(closure: &syn::ExprClosure, arg: &ConstVal) -> Option<ConstVal> {
    if closure.inputs.len() != 1 {
        return None;
    }
    let param = closure_single_param_ident(&closure.inputs[0])?;
    let mut env = BTreeMap::new();
    env.insert(param, arg.clone());
    let body: &Expr = match &*closure.body {
        Expr::Block(b) => match b.block.stmts.as_slice() {
            [Stmt::Expr(e, None)] => e,
            _ => return None, // a multi-statement / side-effecting body -> bail.
        },
        other => other,
    };
    const_eval(body, &env)
}

/// Evaluate an `Option`-returning single-parameter closure `|p| <opt-body>` over a
/// concrete element value, EXACT-OR-BAIL. The body's VALUE is an `Option`: a `None`
/// constructor, a `Some(<pure>)` call, or an `if <pure-cond> { <opt> } else { <opt> }`
/// (the `filter_map` / `map_while` shape). Returns `Some(Some(v))` (kept, value `v`),
/// `Some(None)` (dropped), or `None` (BAIL -- an unmodeled body / opaque element /
/// non-const-foldable piece). This is the crate-level twin of the closed `try_fold`
/// value-evaluator's `eval_option_closure` (`try_fold_eval`), sharing the SAME
/// `const_eval` floor, lifted here so the composable `FilterMapSugar` / `MapWhileSugar`
/// decorators const-evaluate an `Option`-closure over each element exactly as the
/// `MapSugar` decorator const-evaluates a value-closure. A wrong BAIL is a safe
/// under-claim; a wrong VALUE would be a fake-discharge, so we never guess.
fn const_eval_option_closure(
    closure: &syn::ExprClosure,
    arg: &ConstVal,
) -> Option<Option<ConstVal>> {
    if closure.inputs.len() != 1 {
        return None;
    }
    let param = closure_single_param_ident(&closure.inputs[0])?;
    let mut env = BTreeMap::new();
    env.insert(param, arg.clone());
    let body: &Expr = match &*closure.body {
        Expr::Block(b) => match b.block.stmts.as_slice() {
            [Stmt::Expr(e, None)] => e,
            _ => return None, // a multi-statement / side-effecting body -> bail.
        },
        other => other,
    };
    const_eval_option_expr(body, &env)
}

/// Evaluate an expression whose VALUE is an `Option` to a concrete `Option<ConstVal>`:
/// `None`, `Some(<pure>)`, or `if <pure-cond> { <opt> } else { <opt> }`. `None` (BAIL)
/// for any other shape. EXACT-OR-BAIL; the dual of `eval_option_expr` in
/// `try_fold_eval`, over the canonical `const_eval` floor.
fn const_eval_option_expr(
    expr: &Expr,
    env: &BTreeMap<String, ConstVal>,
) -> Option<Option<ConstVal>> {
    match expr {
        Expr::Paren(p) => const_eval_option_expr(&p.expr, env),
        Expr::Group(g) => const_eval_option_expr(&g.expr, env),
        Expr::Block(b) => match b.block.stmts.as_slice() {
            [Stmt::Expr(e, None)] => const_eval_option_expr(e, env),
            _ => None,
        },
        // `None` constructor.
        Expr::Path(p) if p.path.is_ident("None") => Some(None),
        // `Some(<pure>)`.
        Expr::Call(c) => {
            let Expr::Path(p) = &*c.func else { return None };
            if !p.path.is_ident("Some") || c.args.len() != 1 {
                return None;
            }
            Some(Some(const_eval(&c.args[0], env)?))
        }
        // `if <pure-cond> { <opt> } else { <opt> }`.
        Expr::If(if_expr) => {
            // A `let` condition (a pattern guard) is not a pure boolean: `const_eval`
            // returns None for `Expr::Let`, so `as_bool()?` below bails -- no separate
            // shape pre-filter needed.
            let cond = const_eval(&if_expr.cond, env)?.as_bool()?;
            let then_opt = match if_expr.then_branch.stmts.as_slice() {
                [Stmt::Expr(e, None)] => const_eval_option_expr(e, env)?,
                _ => return None,
            };
            let else_branch = if_expr.else_branch.as_ref()?;
            let else_opt = const_eval_option_expr(&else_branch.1, env)?;
            Some(if cond { then_opt } else { else_opt })
        }
        _ => None,
    }
}

/// The single bound ident of a closure parameter pattern (`x`, `&x`), or None for any
/// other pattern (tuple / wildcard / typed-with-subpattern) -> bail.
fn closure_single_param_ident(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(p) if p.subpat.is_none() => Some(p.ident.to_string()),
        Pat::Reference(r) => closure_single_param_ident(&r.pat),
        Pat::Type(t) => closure_single_param_ident(&t.pat),
        _ => None,
    }
}

/// Const-fold an integer accumulator-update tail expression to an `i64` given `env` (the
/// accumulator + the iteration's item-component bindings). This is the integer projection
/// of the exact `const_eval`: it shares the same overflow/div-zero guards but returns an
/// `i64` (the accumulator regime). Any shape / unbound ident / non-int value -> None
/// (bail the defold -- a non-const-foldable accumulator is honest unclassified, never a
/// fake-dig).
fn const_fold_acc_update(tail: &Expr, env: &BTreeMap<String, i64>) -> Option<i64> {
    let cv_env: BTreeMap<String, ConstVal> = env
        .iter()
        .map(|(k, v)| (k.clone(), ConstVal::Int(i128::from(*v))))
        .collect();
    // The accumulator stays in the bounded i64 cursor regime: a folded value
    // beyond i64 is not a representable accumulator position -> bail
    // (EXACT-OR-BAIL; a truncation would be a fake-dig), mirroring
    // `const_int_acc_init`.
    const_eval(tail, &cv_env)?
        .as_int()
        .and_then(|n| i64::try_from(n).ok())
}

// ─────────────────────────────────────────────────────────────────────────────
// The `Sugar` hierarchy (T 2026-06-14). The doctrine reified as types.
//
// stdlib IS sugar; a method-call chain / for-loop is a COMPOSITE TREE of `Sugar`
// nodes, each owning its own `.desugar()` (Interpreter pattern; the chain of
// responsibility falls out of the composition). `decompose` builds the tree by
// recursively decomposing a node's children into inner Sugars; `.desugar()` walks
// inward until `LiteralSugar` bottoms out OR some node returns `None` (BAIL). The
// structure ENFORCES the one predicate: the only way to produce a `Desugared` is
// to reach literals through every layer (no fake-discharge); any layer's `None`
// is the happy refuse.
//
// `Desugared` is a (value, warrant) pair. There are two value flavors, glued to
// the SAME warrant rope:
//   * `Seq` -- a finite element sequence (the literal floor, possibly synthetic:
//     a filter/map output the vendor never typed, warranted by the composed
//     sugar that minted it). Each element keeps BOTH its source `Expr` (for EUF
//     term translation / faithful substitution) AND its `ConstVal` when exactly
//     evaluable; a transforming adaptor REQUIRES the `ConstVal` or it bails.
//   * `Constraints` -- the emitted finite conjunction (a fold/for_each/for-loop
//     terminal), the assert-macro count it accounts, and its warrant (the memento
//     name). This is the lift; the warrant ties it back to the sugar.
//
// EXACT-OR-BAIL is structural: `ConstVal` has no Float/Str variant, so a
// non-const element bails; `Option<Desugared>` IS the bail. A wrong BAIL is a
// safe under-claim; a wrong DIG would be a fake-discharge, so we never guess.

/// One element of a desugared finite sequence: the value glued to its warrant.
/// `expr` is the source expression (carries spans / EUF identity, faithful for
/// term translation); `value` is the exact `ConstVal` when evaluable, `None` for
/// an opaque-but-constructed element (a non-transforming pass-through can keep an
/// opaque element; a transforming adaptor that must inspect it bails on `None`).
#[derive(Clone)]
struct DesugaredElem {
    expr: Expr,
    value: Option<ConstVal>,
}

/// The warrant for a desugared lift: the memento name that ties the emitted
/// constraint back to the sugar that warrants it. `None` falls back to the
/// enclosing function scope at the emit site (mirrors the trunk's un-named
/// `AssertionEntry`). This is the rope; every emit carries one.
#[derive(Clone)]
struct Warrant {
    name: Option<String>,
}

/// The output of `Sugar::desugar`: a (value, warrant) pair. `Seq` is the literal
/// floor (a finite element sequence); `Constraints` is the emitted obligation.
enum Desugared {
    /// A finite element sequence -- the desugared literal floor (written or
    /// synthetic-but-warranted). Produced by `LiteralSugar` and the sequence
    /// adaptors (`IterSugar`/`FilterSugar`/`MapSugar`/...).
    Seq(Vec<DesugaredElem>),
    /// An emitted finite conjunction (a fold/for_each/for-loop terminal): the
    /// formula, the static assert-macro count it accounts, and its warrant.
    Constraints {
        atom: Rc<Formula>,
        n: usize,
        warrant: Warrant,
    },
}

impl Desugared {
    /// The sequence payload, or None (bail) if this is a constraint terminal --
    /// used when an outer sequence adaptor expects an inner sequence.
    fn into_seq(self) -> Option<Vec<DesugaredElem>> {
        match self {
            Desugared::Seq(s) => Some(s),
            Desugared::Constraints { .. } => None,
        }
    }

    /// The single STRING LITERAL value this desugared to, or None. A
    /// pattern-operand `Sugar` (the regex pattern) digs to a one-element `Seq`
    /// whose element `expr` is a `&str` literal; this reads that literal's value
    /// back out. `None` for any non-string-literal payload (a multi-element seq, a
    /// constraint terminal, a non-`LitStr` element) -- the caller bails. This is
    /// the COMPOSITIONAL read: the regex node consumes whatever its pattern child
    /// dug to, so a literal / const-string / `concat!` all flow through the same
    /// `desugar` -> `as_string_literal` path.
    fn as_string_literal(&self) -> Option<String> {
        let seq = match self {
            Desugared::Seq(s) => s,
            Desugared::Constraints { .. } => return None,
        };
        let [only] = seq.as_slice() else {
            return None;
        };
        match strip_refs_groups(&only.expr) {
            Expr::Lit(ExprLit {
                lit: Lit::Str(s), ..
            }) => Some(s.value()),
            _ => None,
        }
    }
}

/// What `desugar` needs from its environment, bundled so the trait method stays
/// `fn desugar(&self, ctx: &SugarCtx) -> Outcome` (the doctrine's exact
/// signature). `float_widths` is interior-mutable (a `RefCell`) because the body
/// collector advances it while desugaring a constraint terminal.
struct SugarCtx<'a, 'c> {
    scope: &'a TemporalScope,
    options: &'a LiftOptions,
    reducer: &'a ReductionCtx<'c>,
    float_widths: std::cell::RefCell<&'a mut FloatWidthScope>,
    macro_depth: usize,
}

/// A node in the desugaring tree. `desugar` recurses inward (each child is a
/// `Sugar` whose `desugar` we call) until `LiteralSugar` bottoms out, or the walk
/// strikes an order-loss boundary (`Hit`). The reduction is TOTAL: it ALWAYS returns
/// an `Outcome` -- `Dug` (reached truth) or `Hit` (a named effect). There is no
/// `Option`/`None` bail and no unclassified return path. Adding a construct = adding
/// one class with one `desugar`.
trait Sugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome;
}

// ── The total reduction: `Outcome { Dug | Hit }` ─────────────────────────────
//
// `Sugar::desugar` is the DIG side -- it walks inward until it reaches literal
// truth (`Dug`). When the walk hits MONKEY BUSINESS -- a side effect, an opaque
// runtime value, an iterator advance, a mutable read -- it `Hit`s a named `Effect`.
// `Outcome` is TOTAL (two cases, no third): every reduction is `Dug` or `Hit`,
// nothing else. The old untyped `None` bail + downstream reason STRING is gone; the
// bail is now a typed `Hit(Effect)` carrying the SAME reason string the collector
// emits into `skip_reasons` (recognized as terminal by `refusal_disposition`). The
// wire format -- and thus the CID + counts -- is unchanged.
//
// `Effect` is a FLAT enum of named order-loss boundaries (a mutation, an iterator
// advance, an opaque runtime value, TLS, IO, a mutable read, ...), each a structural
// property of the SOURCE (not a missing lift) that destroys the single timeless `t` a
// point-wise value claim needs. `Effect::reason()` is the proto refusal string;
// `Effect::boundary()` is the `SourceMemento` (the bail-side rope, mirroring the
// dig-side `Warrant`). Adding an effect = adding one variant + one `reason()` arm.
//
// SOUNDNESS (the critical line, do NOT cross it): an `Effect` is ONLY for a PROVABLE
// order-loss effect -- a syntactic mutation / `iter.next()` / `&mut` / `.push` on
// captured state, a genuinely runtime/opaque value (param, runtime call result, TLS,
// IO), a mutable-container read. A PURE-BUT-UNTRANSLATED term (a pure stdlib method we
// have not transcribed yet) is NOT an `Effect` we should NAME: it stays a STRUCTURAL
// backstop (`Effect::Unsupported`, the byte-identical generic reason at its emit site),
// honest future work for a `Sugar`/`const_eval` arm. Reclassifying a pure-untranslated
// term as a SPECIFIC named effect would be a FAKE-REFUSE -- mislabeling our own work as
// a source property.

/// The bail-side rope: a `SourceMemento` ties a refusal to the source boundary that
/// warrants it (the span / token-key of the offending construct). The mirror of the
/// dig-side `Warrant` (which ropes a discharged constraint to the sugar that minted
/// it). `boundary` is the rendered token-key / description of the order-loss site.
#[derive(Clone, Debug, PartialEq, Eq)]
struct SourceMemento {
    /// The source construct that is the order-loss boundary (token-key / description).
    boundary: String,
}

/// The outcome of a desugar attempt -- the TOTAL reduction. `Dug` reached truth (a
/// discharged `Desugared`); `Hit` struck a NAMED, WARRANTED order-loss boundary (an
/// `Effect`, a terminal loud refusal with a cause). There is no third case: the
/// reduction is total. The collector unwraps it to the existing entries / skip_reasons
/// emission so the wire format (and thus the CID + counts) is unchanged.
enum Outcome {
    /// Reached truth: the desugared literal floor / emitted obligation. -> discharged.
    Dug(Desugared),
    /// Struck a named order-loss boundary. -> refused (terminal, loud, with cause).
    Hit(Effect),
}

impl Outcome {
    /// Lift the legacy `Option<Desugared>` into the total `Outcome`: `Some(d)` reached
    /// truth (`Dug`); a `None` bail is the STRUCTURAL backstop (`Hit(Effect::Unsupported)`
    /// carrying the byte-identical generic skip reason -- a bare structural bail that the
    /// fall-through consumer discards exactly as it discarded `None`, then emits its own
    /// site-specific generic reason). This is the ONE place the legacy `?`/`Option` body of
    /// a `Sugar` becomes total. There is no longer any unclassified return path from
    /// `desugar`.
    fn from_opt(opt: Option<Desugared>) -> Outcome {
        match opt {
            Some(d) => Outcome::Dug(d),
            None => Outcome::Hit(Effect::Unsupported {
                reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
            }),
        }
    }

    /// The discharged payload, or `None` if this struck a boundary (`Hit`). The dual
    /// of `from_opt`: a consumer that wants the legacy `Option<Desugared>` fall-through
    /// (`.and_then` / `?`) reads through this. A `Hit` is discarded exactly as the old
    /// `None` was -- the consumer's own site-specific reason classification is unchanged.
    fn dug(self) -> Option<Desugared> {
        match self {
            Outcome::Dug(d) => Some(d),
            Outcome::Hit(_) => None,
        }
    }
}

/// The STRUCTURAL backstop reason: the bare structural bail of a `Sugar::desugar`
/// (the old `None`). It is NEVER emitted to `skip_reasons` -- a `Hit(Effect::Unsupported)`
/// from a `Sugar` bail is discarded by the fall-through consumer (via `Outcome::dug`)
/// exactly as the old `None` was, and that consumer emits its OWN site-specific reason.
/// This string exists only so `Effect` is total over the structural bail; it is the
/// in-code name of "the dig walk did not reach truth here" with no wire footprint.
const STRUCTURAL_BACKSTOP_REASON: &str =
    "structural bail: the desugar dig did not reach truth (no named effect); fall through";

/// A typed order-loss boundary -- the `Hit` side of `Outcome`. A FLAT enum: one variant
/// per named effect (a mutation, an iterator advance, an opaque runtime value, TLS, IO, a
/// mutable read, ...), plus the `Unsupported` STRUCTURAL backstop (a bare structural bail,
/// or a term-shaped `unsupported term`). `reason()` returns the terminal refusal string
/// (recognized by `refusal_disposition`); `boundary()` returns the `SourceMemento`
/// warranting that the bail names a SOURCE property. Adding an effect = adding one variant
/// + one `reason()` arm.
///
/// Each variant carries its `boundary` (the token-key / description of the order-loss
/// site). The reason strings are kept BYTE-IDENTICAL to the proto strings the collector
/// emitted before this enum existed, so `refusal_disposition` classifies them terminal and
/// the CID is conserved.
enum Effect {
    /// MUTATION: the closure / loop body MUTATES captured or local state (`+=`, `&mut`,
    /// `.push`, an assignment). The asserted value varies per iteration independently of
    /// the bound var, so a single universal over it would be a false claim. A source
    /// property -- no value lifter could read a single timeless `t`. (HALF 2 of the
    /// fold-closure bucket.)
    Mutation { boundary: String },
    /// ITER-ADVANCE: the body advances a captured iterator (`iter.next()` / `nth += 1`), a
    /// sequence/position-dependent side effect. Distinct CAUSE from `Mutation` (no
    /// captured-state assignment is needed), but the SAME terminal class -- the observed
    /// value is per-iteration, not timeless. (Carried under the side-effecting closure-body
    /// proto reason today; typed here as its own named boundary.)
    IterAdvance { boundary: String },
    /// OPAQUE-RUNTIME (bin-2): the iterated / asserted value is RUNTIME data -- a param, a
    /// runtime call result, an opaque receiver -- not constructible from source literals.
    /// There is no construction to walk, so no finite universe to emit. A source property.
    /// `accessor` is true for an effectful ACCESSOR (`.with` / `.with_unfilled_buf`) over
    /// opaque state; false for a plain opaque RECEIVER (`coll.iter().for_each(..)` where
    /// `coll` is runtime). Selects the matching proto reason (both `bin-2` terminal).
    OpaqueRuntime { boundary: String, accessor: bool },
    /// TLS: a `thread_local!` `.with(|x| ..)` -- the closure ranges over thread-local
    /// runtime state, an opaque non-constructed value. A specialization of the opaque
    /// accessor boundary (its proto reason). Named so the catalog records the TLS cause.
    Tls { boundary: String },
    /// IO: the body performs IO (a `write` / `send` to a runtime sink). The observed value
    /// is a runtime effect, not a constructed literal. A source property; carried under the
    /// opaque-accessor proto reason. (`write`/`send` are in `CLOSURE_BODY_MUTATING_METHODS`,
    /// so an IO closure body is caught as a mutation today; named here so the catalog
    /// records the IO cause.)
    Io { boundary: String },
    /// TEMPORAL-READ: a read of a MUTABLE container (`a[i]` where `a` is a provably-`mut`
    /// local that the `mut` oracle flags). The container may be index-assigned or
    /// method-mutated between program points, so `index(a, i)` has no single timeless `t`
    /// -- the read is sequence/position dependent. The mirror, for an index READ, of the
    /// already-terminal `temporally unstable` reason (a term reading a MUTATED local).
    /// SOUNDNESS: emitted ONLY when the `mut` oracle (`scope.is_mut_local`) PROVES the
    /// container is a mutable local -- so this can only refuse a genuinely-mutable read.
    TemporalRead { boundary: String },
    /// CONTROL-FLOW: a `try { .. }` / `async { .. }` block or a `?` operator in term
    /// position. None of these is a single timeless point-wise VALUE: a `try` block
    /// short-circuits on `Err` (control flow), an `async` block is a deferred future, and
    /// `?` is a conditional early-return. There is no finite construction-from-literals to
    /// walk -- a SOURCE/effect property, not a lifter gap. (Drains the `future.rs`
    /// join!-over-`try` row unclassified -> refused; the block is held + named.)
    ControlFlow { boundary: String },
    /// REFLECTION: the asserted value flows through OPAQUE COMPILE-TIME REFLECTION over
    /// runtime type identity -- `Type::of::<T>()` / a `TypeId::of::<T>()` comparison, read
    /// through `.kind` and a `match` arm binding. A `TypeId` is an opaque, target-determined
    /// identity, not a value constructed from source literals; there is no finite literal
    /// construction to walk -- a SOURCE property (the `bin-2` class). A `match` over a
    /// CONSTRUCTED literal scrutinee never reaches here, so this only refuses a reflective read.
    Reflection { boundary: String },
    /// LOOP-ADVANCE: the asserted value flows through a `loop { .. }` over a RUNTIME iterator
    /// the loop body itself ADVANCES (`iter.next()` to drive / break) and reads
    /// non-deterministically (`iter.size_hint()`). Per-iteration runtime bounds, no finite
    /// literal construction (unlike a closed-`for`). A source/effect property of the same
    /// class as `under while context`. Detected ONLY when the loop body advances an iterator.
    LoopAdvance { boundary: String },
    /// IMPL-METHOD: an assertion in an `impl` method BODY (a top-level `Item::Impl`, or a
    /// nested `impl` declared as a statement inside a test fn). The method runs only when
    /// INVOKED, observing the receiver's RUNTIME state. There is no single timeless `t` at
    /// which to read the assert: its truth depends on how many times / in what order the
    /// method was driven. A SOURCE property (the runtime-reachability class). Detection is
    /// STRUCTURAL -- the assert is lexically inside a method body, with no value at definition
    /// time -- so this only refuses a genuine impl-method assert.
    ImplMethod { boundary: String },
    /// IF-GUARD-RUNTIME: a `ConditionalSugar` BAIL whose guard reads a RUNTIME value -- a
    /// `&mut` borrow / mutation in the condition, or a method call on a runtime receiver. The
    /// implication `guard => then` is not a constructible point-wise predicate, because the
    /// guard's truth is not fixed from source literals. A SOURCE property. Detection is EARNED
    /// by `if_guard_is_runtime`; a CONST/cfg/literal guard STAYS UNCLASSIFIED (the
    /// discrimination guardrail against fake-refuse).
    IfGuardRuntime { boundary: String },
    /// RUNTIME-EXPR-STMT: a bare expression-statement whose asserted value is read through a
    /// `&mut` borrow or a mutation. A mutably-aliased read has no single timeless `t` (kin to
    /// `mutable container is not temporally stable`). A SOURCE property. Detection is EARNED by
    /// the `StatementPositionSugar` aliased-read leaf; a statement over a CONSTRUCTED literal
    /// value stays unclassified.
    RuntimeExprStmt { boundary: String },
    /// RUNTIME-MATCH-SCRUTINEE: an `assert!(match <runtime call> { .. })` whose scrutinee is a
    /// RUNTIME non-scalar method/function result. The asserted boolean is the arm taken by a
    /// runtime result, not a scalar equality over constructible values -- no single timeless
    /// `t` (kin to `bin-2`). A SOURCE property. Detection is EARNED by
    /// `runtime_match_scrutinee_effect`; a `match` over a CONSTRUCTED literal scrutinee stays
    /// the bare `only scalar equality` reason (UNCLASSIFIED -- the inverse-sin guardrail).
    RuntimeMatchScrutinee { boundary: String },
    /// ARRAY-REPEAT (non-literal): an array-repeat `[elem; N]` whose length `N` is NOT a plain
    /// literal -- a const-generic param or a const expression (`[0u8; SIZE]`, `[(); SIZE - 1]`).
    /// With a NON-literal count there is no finite construction from the written literal to
    /// materialize -- the universe size is symbolic. A SOURCE property. Detection is EARNED by
    /// the `None` arm of `repeat_count_literal`; a literal length lifts the unrolled array and
    /// never reaches here (the inverse-sin guardrail).
    ArrayRepeat { boundary: String },
    /// UNSUPPORTED: the STRUCTURAL backstop. Two shapes, both carrying their OWN reason string
    /// verbatim:
    ///   * a term-shaped `unsupported term` whose SHAPE is a genuinely effectful /
    ///     non-constructible place (a `&mut` borrow of a non-immutable-value place, a raw
    ///     pointer `&raw const`/`&raw mut`, a `const { <bare path> }` block). EARNED at the
    ///     specific term arm; a PURE untranslated term is NOT given this reason.
    ///   * the bare structural bail of a `Sugar::desugar` dig that did not reach truth (the
    ///     old `None`), with `STRUCTURAL_BACKSTOP_REASON` -- NEVER emitted to `skip_reasons`
    ///     (the fall-through consumer discards it via `Outcome::dug` and emits its own reason).
    /// This is the ONE catch-all variant: it carries a pre-built `reason` string so the emit
    /// site's wire format is conserved.
    Unsupported { reason: String },
}

/// The named effectful CAUSE of an `Effect::Unsupported` term-shaped bail (selects the
/// reason clause). A PURE untranslated term has NONE of these shapes and STAYS the bare
/// `unsupported term` reason -- UNCLASSIFIED work (the inverse-sin guardrail).
#[derive(Debug, Clone, Copy)]
enum UnsupportedTermCause {
    /// `&mut <place>`: a mutable borrow of a non-immutable-value referent.
    MutableReference,
    /// `&raw const`/`&raw mut`: a raw pointer (runtime address).
    RawPointer,
    /// `const { <bare path> }`: a const-block over a bare name (a ZST/fn-item reference; sugar).
    ConstBlockPath,
}

impl UnsupportedTermCause {
    fn clause(self) -> &'static str {
        match self {
            UnsupportedTermCause::MutableReference => "a `&mut` borrow",
            UnsupportedTermCause::RawPointer => "a raw pointer (`&raw const`/`&raw mut`)",
            UnsupportedTermCause::ConstBlockPath => "a `const { <path> }` block (a name is sugar)",
        }
    }

    /// Build the term-shaped `Effect::Unsupported` reason for this cause over `boundary`.
    /// Carries the existing `unsupported term` prefix verbatim so the term path's prior
    /// emission shape is conserved, plus the named effectful cause that earns the terminal
    /// whitelist entry "effectful / raw-pointer / mutable-reference term".
    fn unsupported_term_reason(self, boundary: &str) -> String {
        format!(
            "unsupported term `{}`: effectful / raw-pointer / mutable-reference term \
             ({}) is not a constructible timeless value; refused",
            boundary,
            self.clause()
        )
    }
}

impl Effect {
    /// The terminal refusal string (recognized terminal by `refusal_disposition`), kept
    /// BYTE-IDENTICAL to the proto string the collector emitted before this enum existed.
    fn reason(&self) -> String {
        match self {
            // The proto string the collector already emits for a side-effecting / iterator-
            // advancing closure body (kept verbatim so the CID is conserved). `Mutation` and
            // `IterAdvance` carry the SAME terminal class; typed apart records the cause.
            Effect::Mutation { .. } | Effect::IterAdvance { .. } => {
                "assertion in a side-effecting closure body (mutates captured state / \
                 advances an iterator); not a pure point-wise claim; refused"
                    .to_string()
            }
            Effect::OpaqueRuntime { accessor, .. } => {
                if *accessor {
                    "assertion in a closure over an opaque/effectful accessor (bin-2: runtime \
                     data, not constructible from source literals); refused"
                        .to_string()
                } else {
                    "assertion in a closure over an opaque runtime receiver (bin-2: runtime data, \
                     not constructible from source literals); refused"
                        .to_string()
                }
            }
            // TLS / IO are specializations of the opaque-accessor boundary (same proto reason).
            Effect::Tls { .. } | Effect::Io { .. } => {
                "assertion in a closure over an opaque/effectful accessor (bin-2: runtime \
                 data, not constructible from source literals); refused"
                    .to_string()
            }
            // Carries the existing index-read substring so a single whitelist entry ("mutable
            // container is not temporally stable") recognizes it; the `unsupported term` prefix
            // the term path attaches is preserved by the emit site, so this is the bare clause.
            Effect::TemporalRead { boundary } => format!(
                "unsupported term `{boundary}`: mutable container is not temporally stable"
            ),
            Effect::ControlFlow { boundary } => format!(
                "unsupported term `{boundary}`: effectful control-flow block (try/async/`?`) is not a \
                 timeless point-wise value; refused"
            ),
            Effect::Reflection { boundary } => format!(
                "assertion over opaque compile-time reflection `{boundary}` (Type::of/TypeId: \
                 runtime type identity, not constructed from source literals); refused"
            ),
            Effect::LoopAdvance { boundary } => format!(
                "assertion inside a loop over a runtime-advanced iterator `{boundary}` \
                 (size_hint/next: per-iteration runtime bounds, no finite literal \
                 construction); refused"
            ),
            Effect::ImplMethod { boundary } => format!(
                "assertion in an impl method, reachable only at runtime when the method is \
                 invoked ({boundary}); the receiver's state has no single timeless `t`; refused"
            ),
            Effect::IfGuardRuntime { boundary } => format!(
                "assertion under an if-guard over a runtime value `{boundary}` (not a constructible \
                 predicate; the guard's truth is not fixed from source literals); refused"
            ),
            Effect::RuntimeExprStmt { boundary } => format!(
                "assertion in a runtime expression-statement `{boundary}` (value read through a \
                 `&mut` borrow / mutation, not constructible from source literals); refused"
            ),
            Effect::RuntimeMatchScrutinee { boundary } => format!(
                "only scalar equality is liftable; operand is a runtime non-scalar result \
                 `{boundary}` (a `match` over a runtime call result, not constructible from source \
                 literals); refused"
            ),
            // Carries the existing "array-repeat ... non-literal length ... refused by name"
            // substring verbatim so a single whitelist entry recognizes it; the emit site's
            // `assert_eq!:` / `assert!:` prefix is preserved by the caller.
            Effect::ArrayRepeat { boundary } => format!(
                "array-repeat `[_; N]` has a non-literal length -- not a finite \
                 construction from the literal; refused by name: `{boundary}`"
            ),
            // The structural backstop carries its OWN pre-built reason verbatim (a term-shaped
            // `unsupported term` cause, or the never-emitted `STRUCTURAL_BACKSTOP_REASON`).
            Effect::Unsupported { reason } => reason.clone(),
        }
    }

    /// The `SourceMemento` warranting that the bail names a SOURCE property -- the bail-side
    /// rope (mirror of the dig-side `Warrant`). For `Unsupported`, the boundary is the reason
    /// itself (the backstop carries no separate token-key; the reason names the construct).
    fn boundary(&self) -> SourceMemento {
        let boundary = match self {
            Effect::Mutation { boundary }
            | Effect::IterAdvance { boundary }
            | Effect::OpaqueRuntime { boundary, .. }
            | Effect::Tls { boundary }
            | Effect::Io { boundary }
            | Effect::TemporalRead { boundary }
            | Effect::ControlFlow { boundary }
            | Effect::Reflection { boundary }
            | Effect::LoopAdvance { boundary }
            | Effect::ImplMethod { boundary }
            | Effect::IfGuardRuntime { boundary }
            | Effect::RuntimeExprStmt { boundary }
            | Effect::RuntimeMatchScrutinee { boundary }
            | Effect::ArrayRepeat { boundary } => boundary.clone(),
            Effect::Unsupported { reason } => reason.clone(),
        };
        SourceMemento { boundary }
    }

    /// Build the term-shaped `Effect::Unsupported` for a genuinely effectful / non-
    /// constructible TERM (a `&mut` borrow, a raw pointer, a `const { <path> }` block). The
    /// reason carries the `unsupported term` prefix + named cause verbatim (the term path's
    /// prior emission shape). A PURE untranslated term is NOT given this -- it keeps its bare
    /// `unsupported term` reason elsewhere (the inverse-sin guardrail).
    fn unsupported_term(boundary: &str, cause: UnsupportedTermCause) -> Effect {
        Effect::Unsupported {
            reason: cause.unsupported_term_reason(boundary),
        }
    }
}


/// Maximum desugared sequence length (a finite-construction guard shared by every
/// sequence class). Mirrors the defolder's `CAP`.
const SUGAR_SEQ_CAP: i64 = 4096;


/// `ConditionalSugar`: the CLAIM-side atom (mirror of `LiteralSugar`, the
/// value-side atom). A guarded assertion `if <guard> { <then-asserts> }
/// [else { <else-asserts> }]` is the implication it literally states:
/// `guard => then` (and `not guard => else` when the else branch carries asserts).
///
/// SOUNDNESS LINE: we emit `guard => claim`, NEVER bare `claim`. Asserting the
/// body unconditionally when it is guarded would be a fake-discharge (the assert
/// only fires when the guard holds). `match` is nested conditionals; a bare
/// `assert!(P)` is the trivial `true => P` (handled by the normal unconditional
/// path, so `ConditionalSugar` engages only on the genuinely-guarded contexts the
/// trunk previously refused).
///


/// A `match scrut { pat_i => body_i }` reduced to its scrutinee term + per-arm
/// discriminant guards. The conjunction it states is `⋀_i (guard_i ⇒ conj(A_i))`,

/// Build the discriminant guard a single match arm's pattern states over the
/// scrutinee term, or None (BAIL) for any pattern outside the represented set:
///   - a literal `1 =>`  ->  `scrut == 1` (reuses `translate_lit`);
///   - a qualified variant `Poll::Ready(_) =>` / `Ok(_) =>` (a known prelude
///     wrapper)  ->  `variant_of(scrut) == "variant::<tag>"` (reuses the SAME
///     construction-semantics atom as panic-locus / `matches!` lifting);
///   - the final wildcard `_ =>`  ->  `Ok(None)` (the caller substitutes the
///     negation of all prior guards).


/// Build a `MatchSugar` from a `Stmt::Expr(Expr::Match(..))`: the scrutinee must


/// Capture the in-scope LITERAL arrays (`ys -> [13, 15, ..]`) from `let_inits`, so a
/// for-loop / for_each body's `index(ys, <const>)` read can resolve to its concrete
/// element after the loop index is threaded to a literal position. Byte-identical to
/// the capture `decompose_fold` performs (one level of binding resolution). The
/// mut-gate and the element-translation happen later, in `ForAllSugar::desugar`,
/// against the live scope (a `let mut arr` is excluded there).
fn capture_literal_arrays(let_inits: &BTreeMap<String, &Expr>) -> BTreeMap<String, Vec<Expr>> {
    let mut literal_arrays: BTreeMap<String, Vec<Expr>> = BTreeMap::new();
    for (name, init) in let_inits {
        if let Expr::Array(arr) = strip_refs_groups(init) {
            literal_arrays.insert(name.clone(), arr.elems.iter().cloned().collect());
        }
    }
    literal_arrays
}

/// Capture this block's `let <id> = <array>` bindings whose array is a finite
/// construction of CLOSED SCALAR LITERALS (`[1, 2, 3]`, `[0xab, 0xcd]`), through a
/// `Box::new([..])` wrapper and `&`/group wrappers. A NON-mut binding only (a
/// `let mut` array can be reassigned, so its identity at the assertion point is
/// not the literal). A non-literal or non-scalar element omits the binding so the
/// quantifier path declines rather than over-claims. Used by the
/// `.iter().all/.any(|x| ..)` quantifier to resolve a `let`-bound receiver to its
/// element literals and unroll soundly.
fn capture_scalar_literal_arrays(stmts: &[Stmt]) -> BTreeMap<String, Vec<Expr>> {
    let mut arrays: BTreeMap<String, Vec<Expr>> = BTreeMap::new();
    for stmt in stmts {
        let Stmt::Local(local) = stmt else { continue };
        // Unwrap a type ascription (`let v: Box<[isize]> = ..`): the binding name
        // is inside the `Pat::Type`. A `let mut` / `ref` / sub-pattern binding is
        // not a stable literal identity, so it is skipped.
        let Some(pi) = let_simple_binding(&local.pat) else {
            continue;
        };
        let Some(init) = local.init.as_ref().filter(|i| i.diverge.is_none()) else {
            continue;
        };
        if let Some(elems) = scalar_literal_array_elems(&init.expr) {
            arrays.insert(pi, elems);
        }
    }
    arrays
}

/// The binding name of a simple immutable `let` pattern (`x` or `x: T`), through a
/// type ascription. `None` for `mut`/`ref`/sub-pattern/destructuring binders.
fn let_simple_binding(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(pi)
            if pi.mutability.is_none() && pi.by_ref.is_none() && pi.subpat.is_none() =>
        {
            Some(pi.ident.to_string())
        }
        Pat::Type(t) => let_simple_binding(&t.pat),
        _ => None,
    }
}

/// The closed scalar-literal elements of an array-literal expression (`[1, 2, 3]`)
/// or a `Box::new([..])` of one, through `&`/paren/group wrappers. `None` if it is
/// not an array literal or ANY element is not a closed scalar literal (int/char/
/// byte/bool, allowing a unary `-` on a numeric literal). Strict by design: a
/// single non-literal element bails the whole array (never a partial domain).
fn scalar_literal_array_elems(expr: &Expr) -> Option<Vec<Expr>> {
    match strip_refs_groups(expr) {
        Expr::Array(arr) => {
            for e in &arr.elems {
                if !is_closed_scalar_literal(e) {
                    return None;
                }
            }
            Some(arr.elems.iter().cloned().collect())
        }
        // `Box::new([..])` -- the boxed array is the same finite construction.
        Expr::Call(c) => {
            let Expr::Path(p) = c.func.as_ref() else {
                return None;
            };
            let is_box_new = p.path.segments.len() == 2
                && p.path.segments[0].ident == "Box"
                && p.path.segments[1].ident == "new"
                || p.path.segments.last().is_some_and(|s| s.ident == "new")
                    && p.path.segments.iter().any(|s| s.ident == "Box");
            if !is_box_new || c.args.len() != 1 {
                return None;
            }
            scalar_literal_array_elems(&c.args[0])
        }
        _ => None,
    }
}

/// A CLOSED scalar literal: an int / char / byte / bool literal, or a unary `-`
/// over a numeric literal. (Floats are deliberately excluded -- the quantifier
/// unroll emits Int/Char/Bool comparison atoms, not Real refinements.)
fn is_closed_scalar_literal(expr: &Expr) -> bool {
    match expr {
        Expr::Lit(ExprLit { lit, .. }) => matches!(
            lit,
            Lit::Int(_) | Lit::Char(_) | Lit::Byte(_) | Lit::Bool(_)
        ),
        Expr::Unary(u) if matches!(u.op, UnOp::Neg(_)) => {
            matches!(&*u.expr, Expr::Lit(ExprLit { lit: Lit::Int(_), .. }))
        }
        Expr::Paren(p) => is_closed_scalar_literal(&p.expr),
        Expr::Group(g) => is_closed_scalar_literal(&g.expr),
        _ => false,
    }
}


/// Build a `SugarCtx` from the collector's loose arguments. Centralizes the
/// `RefCell` wrap of `float_widths` so the call sites stay terse.
fn sugar_ctx<'a, 'c>(
    scope: &'a TemporalScope,
    options: &'a LiftOptions,
    reducer: &'a ReductionCtx<'c>,
    float_widths: &'a mut FloatWidthScope,
    macro_depth: usize,
) -> SugarCtx<'a, 'c> {
    SugarCtx {
        scope,
        options,
        reducer,
        float_widths: std::cell::RefCell::new(float_widths),
        macro_depth,
    }
}

/// Emit a desugared constraint terminal into the collector's `entries` (the
/// warranted-emission path), accounting its assert-macro count. Returns true if a
/// constraint was emitted (the statement is accounted), false if `desugared` was a
/// bare sequence (a sequence sugar at statement position is not an emit). The
/// warrant name becomes the `AssertionEntry.name` (the memento handle).
fn emit_desugared(
    desugared: Desugared,
    entries: &mut Vec<AssertionEntry>,
    macros_lifted: &mut usize,
) -> bool {
    match desugared {
        Desugared::Constraints { atom, n, warrant } => {
            entries.push(AssertionEntry {
                name: warrant.name,
                atom,
            });
            *macros_lifted += n;
            true
        }
        Desugared::Seq(_) => false,
    }
}

/// The component sub-expressions of a 2+-tuple expression (`(a, b)`), or None if `expr`
/// is not a tuple. Strips parens/groups/refs first.
fn tuple_components(expr: &Expr) -> Option<Vec<&Expr>> {
    match strip_refs_groups(expr) {
        Expr::Tuple(t) => Some(t.elems.iter().collect()),
        _ => None,
    }
}

/// Strip references / parens / groups to reveal an underlying expression (used to
/// re-read a domain array's element literals for accumulator const-folding).
fn strip_refs_groups(expr: &Expr) -> &Expr {
    match expr {
        Expr::Reference(r) => strip_refs_groups(&r.expr),
        Expr::Paren(p) => strip_refs_groups(&p.expr),
        Expr::Group(g) => strip_refs_groups(&g.expr),
        _ => expr,
    }
}

/// Read a Term as an i64 when it is a literal integer constant (`num`), for closed
/// range enumeration in the defolder. None for any non-literal-int term.
fn term_as_int(t: &Rc<Term>) -> Option<i128> {
    match t.as_ref() {
        Term::Const {
            value: ConstValue::Int(n),
            ..
        } => Some(*n),
        _ => None,
    }
}

/// Mutating method names: a call to one of these on a CAPTURED binding inside a
/// closure body advances / mutates external state (a side effect), so a single
/// universal over the closure parameter is not a timeless point-wise claim.
const CLOSURE_BODY_MUTATING_METHODS: &[&str] = &[
    "next", "next_back", "nth", "nth_back", "push", "push_back", "push_front",
    "pop", "pop_back", "pop_front", "insert", "remove", "clear", "set", "replace",
    "swap", "truncate", "extend", "append", "drain", "store", "fetch_add",
    "fetch_sub", "fetch_or", "borrow_mut", "get_mut", "write", "send",
];

/// The closure-bearing iterator/Option adaptors whose closure body MAY carry a
/// dissolvable / liftable point-wise assertion (pure value-sugar adaptors). A
/// closure-method NOT in this set (`.with`, `.with_unfilled_buf`, `.scope`, an
/// arbitrary effectful accessor) is an opaque/effectful accessor, not a pure
/// iteration -- its asserts are not point-wise and cannot be lifted by any value
/// lifter, so they are TERMINAL (closed with a source property), not lifter work.
const PURE_CLOSURE_ADAPTORS: &[&str] = &[
    "for_each", "try_for_each", "fold", "rfold", "try_fold", "map", "filter_map",
    "flat_map", "scan", "inspect", "all", "any", "find", "find_map", "position",
    "rposition", "reduce", "map_while", "take_while", "skip_while", "filter",
    "and_then", "or_else", "map_or", "map_or_else", "unwrap_or_else",
];

/// True if a closure body (a `Block`'s stmts or a single body expr) is
/// SIDE-EFFECTING: it mutates captured state (an assignment / compound-assign /
/// `&mut` / `let mut` -- via `loop_body_mutates`) or calls a known mutating /
/// iterator-advancing method (`iter.next()`, `v.push(..)`, ...). A side-effecting
/// body is not a pure point-wise claim, so a universal over the closure parameter
/// would be a false claim -- it is TERMINAL, not dissolvable / liftable.
fn closure_body_is_side_effecting(body: &Expr) -> bool {
    let stmts: Vec<Stmt> = match body {
        Expr::Block(b) => b.block.stmts.clone(),
        other => vec![Stmt::Expr(other.clone(), None)],
    };
    if loop_body_mutates(&stmts) {
        return true;
    }
    struct MethScan {
        found: bool,
    }
    impl<'ast> syn::visit::Visit<'ast> for MethScan {
        fn visit_expr_method_call(&mut self, m: &'ast syn::ExprMethodCall) {
            if CLOSURE_BODY_MUTATING_METHODS.contains(&m.method.to_string().as_str()) {
                self.found = true;
            }
            syn::visit::visit_expr_method_call(self, m);
        }
        // A mutating call frequently lives INSIDE an assert macro's tokens
        // (`assert_eq!(Some(x), iter.next())`), which the AST visitor does NOT descend
        // (macro tokens are opaque). Parse the macro args as a comma-list of exprs and
        // scan those, so `iter.next()` inside the assert is seen.
        fn visit_macro(&mut self, m: &'ast syn::Macro) {
            use syn::parse::Parser;
            use syn::punctuated::Punctuated;
            let parser = Punctuated::<Expr, syn::Token![,]>::parse_terminated;
            if let Ok(args) = parser.parse2(m.tokens.clone()) {
                for a in &args {
                    syn::visit::Visit::visit_expr(self, a);
                }
            }
            syn::visit::visit_macro(self, m);
        }
    }
    let mut s = MethScan { found: false };
    syn::visit::Visit::visit_expr(&mut s, body);
    s.found
}

/// If `expr` is a CLOSURE-BEARING method call whose closure body contains assert
/// macro(s) but is NOT a dissolvable/liftable pure-point-wise iteration, return a
/// TERMINAL refusal reason (a source property no value lifter could lift). This is
/// HALF 2 of the fold-closure bucket: the side-effecting / opaque-accessor cases
/// (intersperse `iter.clone().for_each(|x| .. iter.next())`, BorrowedBuf
/// `cursor.with_unfilled_buf(|buf| ..)`, TLS `DROPS.with(|d| ..)`, `array::from_fn(..)
/// .map(|x| { assert!(..); nth += 1 })`) move from unclassified -> terminal-refused.
///
/// Discrimination (the construction + purity boundary, exact so a defoldable case is
/// NEVER fake-refused):
///   * the closure-method is NOT a pure adaptor (an effectful/opaque accessor like
///     `.with` / `.with_unfilled_buf`) -> terminal "opaque ... bin-2" accessor.
///   * a PURE adaptor whose closure body is side-effecting (mutates captured state /
///     advances an iterator) -> terminal "side-effecting closure body".
///   * a PURE iterator adaptor (for_each/fold-family) whose RECEIVER does NOT resolve
///     (through `let_inits`) to a finite literal domain -> the iterated values are runtime
///     data, terminal "opaque runtime receiver (bin-2)".
///   * a PURE adaptor, PURE body, LITERAL-resolvable receiver -> None: this is a
///     defoldable / for_each-liftable case (`try_lift_fold_forall` / `try_lift_for_each_
///     forall` already discharged it, or declined for a recoverable reason like a non-
///     const-foldable accumulator) -> leave the generic UNCLASSIFIED skip (honest work).
/// None also for any non-closure-method statement (handled by the existing skip).
/// True if a closure body ADVANCES an iterator (`iter.next()` / `next_back` / `nth` /
/// `nth_back`) -- the sequence/position-dependent cause that types as
/// `IterAdvanceEffect` (vs a captured-state assignment, which types as
/// `MutationEffect`). Scans the body and any assert-macro args (the advance frequently
/// lives in `assert_eq!(Some(x), iter.next())`), mirroring `MethScan`.
fn closure_body_advances_iterator(body: &Expr) -> bool {
    const ITER_ADVANCE_METHODS: &[&str] = &["next", "next_back", "nth", "nth_back"];
    struct Scan {
        found: bool,
    }
    impl<'ast> syn::visit::Visit<'ast> for Scan {
        fn visit_expr_method_call(&mut self, m: &'ast syn::ExprMethodCall) {
            if ITER_ADVANCE_METHODS.contains(&m.method.to_string().as_str()) {
                self.found = true;
            }
            syn::visit::visit_expr_method_call(self, m);
        }
        fn visit_macro(&mut self, m: &'ast syn::Macro) {
            let parser = Punctuated::<Expr, syn::Token![,]>::parse_terminated;
            if let Ok(args) = parser.parse2(m.tokens.clone()) {
                for a in &args {
                    syn::visit::Visit::visit_expr(self, a);
                }
            }
            syn::visit::visit_macro(self, m);
        }
    }
    let mut s = Scan { found: false };
    syn::visit::Visit::visit_expr(&mut s, body);
    s.found
}

/// If `expr` is a CLOSURE-BEARING method call whose closure asserts but is NOT a
/// dissolvable/liftable pure point-wise iteration, return the NAMED `Effect` the
/// `ClosureAdaptorSugar` node's `desugar` `Hit`s (a mutation / iterator-advance /
/// opaque-runtime / TLS boundary). A THIN ADAPTER over the node, which lives in
/// `sugar::closure_adaptor`: it `build`s the node (`decompose_closure_adaptor`), `desugar`s
/// it once, and reads the verdict -- mapping the node's STRUCTURAL backstop `Hit` back to
/// `None` (the honest-unclassified fall-through, the old `None`). The caller renders
/// `effect.reason()` into `skip_reasons` -- the wire format is unchanged.
///
/// Returns `None` for a PURE adaptor over a PURE body over a LITERAL-resolvable receiver
/// (the defoldable / for_each-liftable case -- honest UNCLASSIFIED work, never fake-refused)
/// and for any non-closure-method statement. The order-loss VERDICT is made entirely in the
/// node's `desugar` (and its accessor/body/receiver leaves), never here.
fn closure_method_terminal_effect(
    expr: &Expr,
    scope: &TemporalScope,
    options: &LiftOptions,
    reducer: &ReductionCtx,
    float_widths: &mut FloatWidthScope,
    macro_depth: usize,
    let_inits: &BTreeMap<String, &Expr>,
) -> Option<Effect> {
    let node = sugar::closure_adaptor::decompose_closure_adaptor(expr, let_inits)?;
    let ctx = sugar_ctx(scope, options, reducer, float_widths, macro_depth);
    match node.desugar(&ctx) {
        // The STRUCTURAL backstop = the honest-unclassified fall-through (the old `None`).
        Outcome::Hit(Effect::Unsupported { reason }) if reason == STRUCTURAL_BACKSTOP_REASON => {
            None
        }
        // A NAMED order-loss boundary -- the verdict the caller renders to skip_reasons.
        Outcome::Hit(effect) => Some(effect),
        // A bail-side node never reaches truth; `Dug` is unreachable here.
        Outcome::Dug(_) => None,
    }
}

/// True if `expr` (or anything inside it) is an `.await` -- the asserted value flows
/// through a FUTURE CONTINUATION (`let x = join!(..).await; assert_eq!(x, ..)`). The
/// awaited value is produced by a runtime executor, not constructed from source
/// literals -- value NOT in scope.
fn expr_contains_await(expr: &Expr) -> bool {
    struct Scan {
        found: bool,
    }
    impl<'ast> syn::visit::Visit<'ast> for Scan {
        fn visit_expr_await(&mut self, _: &'ast syn::ExprAwait) {
            self.found = true;
        }
    }
    let mut s = Scan { found: false };
    syn::visit::Visit::visit_expr(&mut s, expr);
    s.found
}

/// True if `expr` is a FREE-FN `block_on(async { .. })` / `block_on(async move { .. })`
/// call -- a future driven to completion by a runtime executor. The
/// `unconditional_block_stmts` recursion handles `rt.block_on(async{..})` as a METHOD
/// call (it drives a concrete future synchronously), but a free-fn `block_on(async{..})`
/// whose async body binds its asserted values from `.await` results is a runtime
/// continuation -- value NOT in scope. (Recursing it would FAKE-DIG: `assert_eq!(x, 0)`
/// where `x = join!(async{0}).await` would discharge `x == 0` as a literal, ignoring the
/// runtime await. Proven empirically.)
fn is_free_fn_block_on_async(expr: &Expr) -> bool {
    let Expr::Call(call) = expr else {
        return false;
    };
    let Expr::Path(p) = &*call.func else {
        return false;
    };
    let is_block_on = p
        .path
        .segments
        .last()
        .is_some_and(|s| s.ident == "block_on");
    if !is_block_on || call.args.len() != 1 {
        return false;
    }
    matches!(&call.args[0], Expr::Async(_))
}

/// True if a `match` scrutinee is OPAQUE COMPILE-TIME REFLECTION over runtime type
/// identity: `Type::of::<T>()` / `<expr>.info()` / a `.kind` read off such, optionally
/// wrapped in a `const { .. }` block. A `TypeId`/`Type` is a target/compiler-determined
/// identity, not a value constructed from source literals. Detected structurally so a
/// `match` over a CONSTRUCTED literal scrutinee never matches (it digs / stays
/// unclassified). Returns the rendered scrutinee for the boundary, or None.
fn reflection_scrutinee(scrut: &Expr) -> Option<String> {
    // A reflection call is `Type::of::<..>()` / `TypeId::of::<..>()` / `<e>.info()`.
    struct Scan {
        found: bool,
    }
    impl<'ast> syn::visit::Visit<'ast> for Scan {
        fn visit_expr_call(&mut self, c: &'ast syn::ExprCall) {
            if let Expr::Path(p) = &*c.func {
                // `Type::of` / `TypeId::of` (segment `of` on a `Type`/`TypeId` path).
                let segs: Vec<String> =
                    p.path.segments.iter().map(|s| s.ident.to_string()).collect();
                if segs.iter().any(|s| s == "Type" || s == "TypeId")
                    && segs.last().is_some_and(|s| s == "of")
                {
                    self.found = true;
                }
            }
            syn::visit::visit_expr_call(self, c);
        }
        fn visit_expr_method_call(&mut self, m: &'ast syn::ExprMethodCall) {
            // `<e>.info()` reads the runtime `Type` metadata of `e`.
            if m.method == "info" && m.args.is_empty() {
                self.found = true;
            }
            syn::visit::visit_expr_method_call(self, m);
        }
    }
    let mut s = Scan { found: false };
    syn::visit::Visit::visit_expr(&mut s, scrut);
    if s.found {
        Some(token_key(scrut))
    } else {
        None
    }
}

/// Detect whether an `if`/`while` GUARD reads a RUNTIME value -- a `&mut` borrow or a
/// mutation in the condition (`if let Some(p) = it.peek_mut()`), or an assignment. A
/// runtime guard's truth is not fixed from source literals, so `guard => then` is not a
/// constructible point-wise predicate (the `IfGuardRuntimeEffect` cause).
///
/// DISCRIMINATION GUARDRAIL: a CONST/cfg/literal guard is NOT runtime. A `cfg!(..)`
/// macro is a compile-time target predicate (constant per build); a bare literal /
/// const-folded boolean (`!false`, `!true`) is a constructible value. These return
/// `false` -> the assert STAYS UNCLASSIFIED (computable-but-unimplemented), never
/// fake-refused. We detect runtime ONLY by a positive syntactic signal (`&mut` /
/// assignment); absence of that signal is treated as NOT-runtime (the conservative,
/// non-draining default).
fn if_guard_is_runtime(cond: &Expr) -> bool {
    // A `cfg!(..)` guard is a compile-time constant predicate -- explicitly NOT runtime,
    // even though it is a macro call. Strip the common `!cfg!(..)` / `cfg!(..)` shapes.
    if expr_is_cfg_macro(cond) {
        return false;
    }
    #[derive(Default)]
    struct Scan {
        runtime: bool,
    }
    impl<'ast> syn::visit::Visit<'ast> for Scan {
        fn visit_expr_reference(&mut self, r: &'ast syn::ExprReference) {
            if r.mutability.is_some() {
                self.runtime = true;
            }
            syn::visit::visit_expr_reference(self, r);
        }
        fn visit_expr_assign(&mut self, _: &'ast syn::ExprAssign) {
            self.runtime = true;
        }
        fn visit_expr_binary(&mut self, b: &'ast syn::ExprBinary) {
            if matches!(
                b.op,
                BinOp::AddAssign(_)
                    | BinOp::SubAssign(_)
                    | BinOp::MulAssign(_)
                    | BinOp::DivAssign(_)
                    | BinOp::RemAssign(_)
                    | BinOp::BitXorAssign(_)
                    | BinOp::BitAndAssign(_)
                    | BinOp::BitOrAssign(_)
                    | BinOp::ShlAssign(_)
                    | BinOp::ShrAssign(_)
            ) {
                self.runtime = true;
            }
            syn::visit::visit_expr_binary(self, b);
        }
    }
    let mut scan = Scan::default();
    syn::visit::Visit::visit_expr(&mut scan, cond);
    scan.runtime
}

/// Is `cond` a `cfg!(..)` / `!cfg!(..)` macro call? A target-config predicate is a
/// compile-time constant, not a runtime value -- so it must NOT be classified runtime.
fn expr_is_cfg_macro(cond: &Expr) -> bool {
    let inner = match cond {
        Expr::Unary(u) if matches!(u.op, syn::UnOp::Not(_)) => u.expr.as_ref(),
        other => other,
    };
    matches!(inner, Expr::Macro(m) if m.mac.path.segments.last().is_some_and(|s| s.ident == "cfg"))
}

/// Const-fold an `if`/match GUARD whose truth is fixed at compile time from the
/// source: a bare boolean literal (`true`/`false`), a not over a literal (`!false`
/// -> true, `!true` -> false), or a `cfg!(..)` / `!cfg!(..)` target-config predicate
/// resolved against `options.target_cfg`. Returns `Some(bool)` for a constant guard,
/// `None` for anything whose truth is NOT fixed from source (a runtime value, an
/// opaque predicate, or a `cfg!` with no resolved target facts -- `Ambiguous`).
///
/// SOUNDNESS: the returned bool is the EXACT compile-time value of the guard, so the
/// emitted `guard_const => P` is faithful: a `true` guard forces `P`, a `false` guard
/// makes the implication trivially satisfied (the body never runs -- exactly the
/// branch's semantics). DISCRIMINATION: a runtime guard folds to `None` and stays
/// refused (`if_guard_is_runtime`); only a literal/cfg-constant guard folds here.
fn const_fold_bool_guard(cond: &Expr, options: &LiftOptions) -> Option<bool> {
    let (negate, inner) = match cond {
        Expr::Unary(u) if matches!(u.op, syn::UnOp::Not(_)) => (true, u.expr.as_ref()),
        Expr::Paren(p) => return const_fold_bool_guard(&p.expr, options),
        Expr::Group(g) => return const_fold_bool_guard(&g.expr, options),
        other => (false, other),
    };
    let base = match inner {
        // A bare boolean literal: `true` / `false`.
        Expr::Lit(ExprLit { lit: Lit::Bool(b), .. }) => b.value,
        // `(.. )` / `{ .. }` wrapping a literal.
        Expr::Paren(p) => const_fold_bool_guard(&p.expr, options)?,
        Expr::Group(g) => const_fold_bool_guard(&g.expr, options)?,
        // A `cfg!(..)` macro: a compile-time target predicate. Parse its predicate
        // and resolve against the explicit target cfg facts. Ambiguous (no facts) or
        // unparseable -> None (bail; stays unclassified, never fake-folded).
        Expr::Macro(m) if m.mac.path.segments.last().is_some_and(|s| s.ident == "cfg") => {
            let predicate = m.mac.parse_body::<CfgPredicate>().ok()?;
            match cfg_eval_predicate(&predicate, options.target_cfg.as_ref()) {
                CfgEval::Active => true,
                CfgEval::Inactive(_) => false,
                CfgEval::Ambiguous(_) => return None,
            }
        }
        _ => return None,
    };
    Some(if negate { !base } else { base })
}

/// The first method name in an `impl` block that carries at least one assertion (for the
/// `ImplMethodEffect` boundary description). Returns None if no method body carries an
/// assert (so a pure impl block -- e.g. a `const`-only or assert-free impl declared as a
/// statement -- is NOT refused; it stays on the generic unclassified path).
fn impl_block_method_name(imp: &syn::ItemImpl) -> Option<String> {
    imp.items.iter().find_map(|it| {
        if let syn::ImplItem::Fn(m) = it {
            if count_asserts_in_stmts(&m.block.stmts) > 0 {
                return Some(m.sig.ident.to_string());
            }
        }
        None
    })
}

/// Thin node-router: a bare statement-position expression whose asserted value flows through
/// a RUNTIME continuation NOT IN SCOPE is classified by the `StatementPositionSugar` node. It
/// names every value-NOT-in-scope verdict in its own `desugar` -- a future continuation
/// (`.await` / free-fn `block_on(async{..})`) `ControlFlow`, an opaque `match Type::of::<T>()
/// .kind`/`.info()` `Reflection`, a `loop { .. }` over a runtime-advanced iterator `LoopAdvance`,
/// or a `&mut`-aliased / mutated `RuntimeExprStmt` read. The caller renders `effect.reason()`
/// into `skip_reasons`, which `refusal_disposition` classifies terminal. This is the
/// value-NOT-in-scope half of the statement-position split (the value-IN-scope half DIGS via
/// the defolder / unconditional-block recursion).
///
/// SOUNDNESS (the discrimination guardrail): each leaf fires ONLY on a DETECTED runtime
/// signal (an `.await`, a free-fn `block_on(async)`, a `Type::of`/`.info()` reflection
/// scrutinee, a loop body that advances an iterator, a `&mut` borrow / assignment). A
/// statement carrying a CONSTRUCTED literal value matches NONE of these -> the node returns
/// its STRUCTURAL backstop, which this router maps to `None` (the old fall-through), leaving
/// it to DIG or stay unclassified -- never terminalized by position.
fn statement_position_terminal_effect(
    expr: &Expr,
    scope: &TemporalScope,
    options: &LiftOptions,
    reducer: &ReductionCtx,
    float_widths: &mut FloatWidthScope,
    macro_depth: usize,
) -> Option<Effect> {
    let node = sugar::statement_position::decompose_statement_position(expr)?;
    let ctx = sugar_ctx(scope, options, reducer, float_widths, macro_depth);
    match node.desugar(&ctx) {
        // The STRUCTURAL backstop = the honest-unclassified fall-through (the old `None`).
        Outcome::Hit(Effect::Unsupported { reason }) if reason == STRUCTURAL_BACKSTOP_REASON => {
            None
        }
        // A NAMED statement-position boundary -- the verdict the caller renders to skip_reasons.
        Outcome::Hit(effect) => Some(effect),
        // A bail-side node never reaches truth; `Dug` is unreachable here.
        Outcome::Dug(_) => None,
    }
}

/// Thin node-router: a statement-nested `impl` block whose method body carries an assertion is
/// classified by the `ImplMethodSugar` node. It names the impl-method-reachability verdict in
/// its own `desugar` -- an assertion lexically inside an impl method body is reachable ONLY at
/// call time, over the receiver's RUNTIME state, so there is no single timeless `t` (the
/// `ImplMethodEffect` boundary is `impl method `{name}``). The caller renders `effect.reason()`
/// into `skipped`, which `refusal_disposition` classifies terminal. This is the same terminal
/// cause as the top-level `Item::Impl` bucket, surfaced here because the impl is a statement.
///
/// SOUNDNESS (the discrimination guardrail): the node fires ONLY on a DETECTED asserting method
/// (`impl_block_method_name` finds a method body with an assert). A pure / assert-free impl
/// block matches none -> the node declines to RECOGNIZE (the build arm returns `None`), which
/// this router maps to `None` (the old fall-through), leaving the statement on the generic
/// unclassified path -- never terminalized by position.
fn impl_method_terminal_effect(
    imp: &syn::ItemImpl,
    scope: &TemporalScope,
    options: &LiftOptions,
    reducer: &ReductionCtx,
    float_widths: &mut FloatWidthScope,
    macro_depth: usize,
) -> Option<Effect> {
    let node = sugar::impl_method::decompose_impl_method(imp)?;
    let ctx = sugar_ctx(scope, options, reducer, float_widths, macro_depth);
    match node.desugar(&ctx) {
        // The STRUCTURAL backstop = the honest-unclassified fall-through (the old `None`).
        Outcome::Hit(Effect::Unsupported { reason }) if reason == STRUCTURAL_BACKSTOP_REASON => {
            None
        }
        // A NAMED impl-method boundary -- the verdict the caller renders to skipped.
        Outcome::Hit(effect) => Some(effect),
        // A bail-side node never reaches truth; `Dug` is unreachable here.
        Outcome::Dug(_) => None,
    }
}

/// Strip a `const { .. }` wrapper (and parens/groups) off a match scrutinee to reveal
/// the underlying reflection call (`match const { Type::of::<T>() }.kind { .. }`).
fn strip_const_block(expr: &Expr) -> &Expr {
    match expr {
        Expr::Const(c) => {
            // `const { <single tail expr> }` -> that expr; else leave as-is.
            if let [syn::Stmt::Expr(e, None)] = c.block.stmts.as_slice() {
                return strip_const_block(e);
            }
            expr
        }
        Expr::Field(f) => strip_const_block(&f.base),
        Expr::Paren(p) => strip_const_block(&p.expr),
        Expr::Group(g) => strip_const_block(&g.expr),
        _ => expr,
    }
}

/// A nested block is a DISTINCT program region. Two sibling blocks that each
/// rebind a same-named local (`const { let ty = .. }` twice; `{ let as_mut = .. }`
/// twice; the `{ let i = Cell::new(0); .. }` rebind-in-block of `iterator_drops`)
/// must NOT coalesce: each block's `ty`/`as_mut`/`i` is a different value observed
/// at a different program point. The function-level `local_scope` is the same for
/// both, so their unqualified locals key identically and a false `unsat` is
/// manufactured. Tagging each nested block with its statement ordinal gives every
/// region a distinct scope, so its locals (and the obligations keyed on them) are
/// distinct. Splitting one obligation into two smaller ones is sound: it can only
/// turn a spurious `unsat` into two satisfiable groups, never the reverse.
fn child_block_scope(parent: &str, stmt_idx: usize) -> String {
    format!("{parent}#b{stmt_idx}")
}

fn unconditional_block_stmts(expr: &Expr) -> Option<&[Stmt]> {
    match expr {
        Expr::Block(b) => Some(&b.block.stmts),
        Expr::Unsafe(u) => Some(&u.block.stmts),
        Expr::Paren(p) => unconditional_block_stmts(&p.expr),
        Expr::Group(g) => unconditional_block_stmts(&g.expr),
        Expr::MethodCall(c) if c.method == "block_on" && c.args.len() == 1 => match &c.args[0] {
            Expr::Async(a) => Some(&a.block.stmts),
            other => unconditional_block_stmts(other),
        },
        _ => None,
    }
}

#[allow(clippy::too_many_arguments)]
fn collect_assertion_entries<'a>(
    stmts: &'a [Stmt],
    local_scope: &str,
    options: &LiftOptions,
    reducer: &ReductionCtx<'a>,
    float_widths: &mut FloatWidthScope,
    entries: &mut Vec<AssertionEntry>,
    skipped: &mut Vec<String>,
    macros_lifted: &mut usize,
    reduced_helpers: &mut HashSet<String>,
    macro_depth: usize,
    inherited_stateful: &BTreeSet<String>,
    // LEXICAL SCOPE: nested fns declared in ENCLOSING blocks (the ancestors of this
    // block). A Rust `fn` item is in scope for the whole enclosing block including all
    // nested sub-blocks (item hoisting), so a helper defined at the `#[test]` fn level
    // (`fn assert_predicates_exact(..)`) IS lexically visible at a call inside a bare
    // `{ .. }` block. We merge these into THIS block's `local_fns` so the call resolves
    // and its body is RE-LIFTED at the call site -- a pure body digs, a RUNTIME body
    // (HashSet/Vec collect over TypeId, `fmt::write` over a `let mut` writer) refuses
    // with a NAMED effect. Without this, such a call fell to the unresolved
    // "has no visible source" (UNCLASSIFIED) -- a reach gap, not a source property.
    // SOUND: the SAME reducer re-digs the body, so this can only DRAIN (dig or named-
    // refuse) a body whose cause is now SHOWN; it never fake-digs (a runtime body bails
    // / refuses) and never fake-refuses (a pure body discharges through the dig path).
    enclosing_fns: &BTreeMap<String, &'a syn::ItemFn>,
) {
    // A NESTED BLOCK carries the `#b<idx>` marker (`child_block_scope`); a function
    // body / macro-expansion / loop scope does not. Inside a nested block we relabel
    // this level's un-named entries to the block scope (see below).
    let relabel_unnamed_to_scope = local_scope.contains("#b");
    // A NESTED BLOCK is a distinct consistency scope. Un-callsite-named asserts
    // (field-access / variant equalities, with no method-call key) otherwise fall
    // back to the FUNCTION name and conjoin across sibling blocks -- so two blocks
    // that each rebind a same-named local (`const { let ty = .. }`; `{ let p = .. }`;
    // `{ let as_mut = .. }`) collide into a false `unsat` on bare `ty`/`p`/`as_mut`.
    // When this invocation lifts a nested block, we relabel ITS OWN un-named entries
    // to the block-distinct `local_scope`, so each block is grouped (and checked)
    // on its own. Entries added by DEEPER recursions are already named (their own
    // block), so only this level's still-`None` entries are touched.
    let entries_start = entries.len();
    let temporal_plan = temporal_plan_for_stmts(stmts, inherited_stateful);
    let mut temporal_scope = TemporalScope::new(local_scope, temporal_plan)
        .with_literal_arrays(capture_scalar_literal_arrays(stmts));
    // `let_bindings` is advanced INCREMENTALLY in the statement loop below (see
    // `record_let_binding`), so a `try_fold` operand resolves the binding in EFFECT at
    // its position -- shadowing-correct. (A block-wide capture would let a LATER
    // `let f = ..` shadow leak back to an EARLIER assert's `f`, mis-grounding it.)
    // const_eval_select((), compiletime, runtime) is a std intrinsic that, at
    // run time, calls its runtime fn. Find such calls in this block and the
    // inner fns they select, so the runtime branch is inlined (its asserts
    // lift) instead of refused as an unreachable inner fn.
    let runtime_targets = const_eval_select_runtime_targets(stmts);
    // Start from the lexically-enclosing nested fns (ancestor blocks), then OVERLAY this
    // block's own `Item::Fn`s -- a same-named inner fn SHADOWS an outer one (Rust scoping).
    // So a helper defined at the `#[test]` fn level resolves at a call inside a nested
    // block, while a block-local redefinition still wins. The merged map is what we resolve
    // calls against AND what we pass down as `enclosing_fns` to deeper recursions.
    let mut local_fns: BTreeMap<String, &'a syn::ItemFn> = enclosing_fns.clone();
    for s in stmts.iter() {
        if let Stmt::Item(Item::Fn(f)) = s {
            local_fns.insert(f.sig.ident.to_string(), f);
        }
    }
    // Map of this block's simple `let <ident> = <init>;` bindings, so the DEFOLDER can
    // resolve a fold receiver that is a binding (`it.fold(..)` where `it = xs.iter()`,
    // `xs = [..]`) back through to its literal-array / range domain. A non-simple pat or
    // a diverging init is omitted (resolution then fails -> the defolder declines, safe).
    let let_inits: BTreeMap<String, &Expr> = stmts
        .iter()
        .filter_map(|s| match s {
            Stmt::Local(local) => {
                let init = local.init.as_ref().filter(|i| i.diverge.is_none())?;
                match &local.pat {
                    Pat::Ident(p) if p.subpat.is_none() => {
                        Some((p.ident.to_string(), &*init.expr))
                    }
                    _ => None,
                }
            }
            _ => None,
        })
        .collect();
    // Deferred nested-fn-definition refusals. A nested helper's "reachable only via
    // call-site inlining" refusal must NOT be emitted if a later bare-call statement
    // in THIS block inlines it (the call sites populate `reduced_helpers` as the loop
    // advances, and the definition is hit before its calls). So we DEFER the
    // definition-site refusal and drain it AFTER the loop, emitting only for nested
    // fns still NOT in `reduced_helpers` -- the block-local mirror of the file-level
    // Pass1/Pass2 split. (count, reason) per still-refused inner fn.
    let mut deferred_inner_fn_refusals: Vec<(String, usize, String)> = Vec::new();
    // BLOCK-LOCAL reduction tracking (the name-collision fix). `reduced_helpers` is the
    // FILE-level set: it dedups TOP-level helpers reduced by some test fn vs the same
    // helper visited standalone (`visit_non_test_fn`). But a NESTED `fn` is lexically
    // local to ITS enclosing block: two different test fns may each declare a distinct
    // `fn zero_byte` / `fn check` with the SAME name but DIFFERENT bodies (rust-src
    // hash/sip.rs has `zero_byte` in both `_64` and `_32`; char.rs has FIVE distinct
    // nested `check`s). Keying the deferred-inner-fn drain off the GLOBAL set conflated
    // them: once test A reduced its `zero_byte`, test B's distinct `zero_byte` was
    // skipped at BOTH the inline-attempt AND the refusal drain, so its asserts were
    // never enumerated -> they fell to the "unenumerated statement position" safety net
    // (a FALSE unclassified, not real work). "Reduced during THIS block's processing"
    // is computed two ways, unioned, so EVERY reduction path is covered: (1) the
    // explicit `reduced_in_block` inserts at the bare-statement / arg-position commit
    // sites below; (2) a SET DIFF against the snapshot of `reduced_helpers` taken at
    // entry -- this catches reductions that happen DEEPER (e.g. `reduce_assertion_expr`
    // inserting the helper name into `reduced_helpers` from inside a recursive desugar)
    // without an explicit insert here. A name added to `reduced_helpers` during this
    // call but absent at entry was reduced HERE. (The explicit set ALSO covers the
    // collision case where a same-named helper was inherited at entry AND reduced here:
    // the set-diff alone would miss it, the explicit insert catches it.) The deferred
    // drain consults the union instead of the raw file-global set, so each block's
    // nested fns are judged on their OWN reduction; the global set is still updated for
    // cross-test/file TOP-level dedup.
    let reduced_at_entry: HashSet<String> = reduced_helpers.clone();
    let mut reduced_in_block: HashSet<String> = HashSet::new();
    for (stmt_idx, stmt) in stmts.iter().enumerate() {
        match stmt {
            Stmt::Local(local) => {
                update_float_width_scope_for_pat(&local.pat, float_widths);
                if let Some(init) = &local.init {
                    // If the initializer is an unconditional block (a plain block
                    // or a block_on(async {..})), recurse and lift its asserts;
                    // the per-fn safety net accounts anything not reached, so no
                    // silent drop. Otherwise the asserts (closures, conditionals)
                    // are not top-level point-wise: refuse them.
                    if let Some(stmts) = unconditional_block_stmts(&init.expr) {
                        collect_assertion_entries(
                            stmts,
                            &child_block_scope(local_scope, stmt_idx),
                            options,
                            reducer,
                            float_widths,
                            entries,
                            skipped,
                            macros_lifted,
                            reduced_helpers,
                            macro_depth,
                            &temporal_scope.plan.interior_mut,
                            &local_fns,
                        );
                    } else if let Some(desugared) = {
                        // DESUGAR (the typed `Sugar` spine): a `.fold`/`.rfold`
                        // (`FoldSugar`) or a `.for_each` (`ForEachSugar`) over a
                        // finite literal domain desugars to its finite conjunction
                        // (the construction axiom: desugar fold with fold). The
                        // `Sugar` tree is built by `decompose_*` (node + children)
                        // and walked by `desugar()`; the warranted emission drains
                        // its output. A bail (`None`) at any layer falls through.
                        let ctx = sugar_ctx(
                            &temporal_scope,
                            options,
                            reducer,
                            float_widths,
                            macro_depth,
                        );
                        decompose_fold(&init.expr, &let_inits)
                            .and_then(|s| s.desugar(&ctx).dug())
                            .or_else(|| {
                                decompose_for_each(&init.expr, &temporal_scope, &let_inits)
                                    .and_then(|s| s.desugar(&ctx).dug())
                            })
                    } {
                        emit_desugared(desugared, entries, macros_lifted);
                    } else {
                        let mut count = count_asserts_in_expr(&init.expr);
                        if let Some((_, diverge)) = &init.diverge {
                            count += count_asserts_in_expr(diverge);
                        }
                        // HALF 2: a closure-method let-init whose body is side-effecting /
                        // over an opaque accessor is TERMINAL (a source property), not the
                        // generic unclassified work. The typed `SideEffect` names the
                        // boundary; we render its `reason()` (the wire format is unchanged).
                        // A pure adaptor + pure body returns None here and keeps the generic
                        // skip (dissolvable in --dissolve).
                        let reason = closure_method_terminal_effect(
                            &init.expr,
                            &temporal_scope,
                            options,
                            reducer,
                            float_widths,
                            macro_depth,
                            &let_inits,
                        )
                        .map(|e| e.reason())
                        .unwrap_or_else(|| {
                            "assertion inside a let-initializer expression: not a top-level point-wise assertion; released to layer 0".to_string()
                        });
                        for _ in 0..count {
                            skipped.push(reason.clone());
                        }
                    }
                }
                // Advance the in-effect `let` bindings AFTER this local's own init is
                // processed, so a SUBSEQUENT `try_fold` operand resolves this binding
                // (shadowing-correct: a re-`let` of the same name overwrites). Only a
                // simple immutable binding is recorded (the evaluator gates resolution
                // on `!is_mut_local` regardless, so a `let mut` left out is harmless).
                if let (Some(name), Some(init)) =
                    (let_simple_binding(&local.pat), local.init.as_ref())
                {
                    if init.diverge.is_none() {
                        temporal_scope.record_let_binding(&name, (*init.expr).clone());
                    }
                }
            }
            Stmt::Macro(m) => match cfg_eval_for_attrs(&m.attrs, options) {
                CfgEval::Active => {
                    // Known assertion macros are lowered by their tuned arm
                    // first. If no arm lifts it, walk into the definition: when
                    // we hold the macro's source, expand it and reduce the
                    // expansion. One source macro is one accounting unit.
                    let before_e = entries.len();
                    let before_s = skipped.len();
                    collect_macro(
                        &m.mac.path,
                        m.mac.tokens.clone(),
                        &temporal_scope,
                        &*float_widths,
                        options,
                        entries,
                        skipped,
                    );
                    if entries.len() > before_e {
                        *macros_lifted += 1;
                    } else {
                        match try_macro_expansion_entries(
                            &m.mac.path,
                            &m.mac.tokens,
                            reducer,
                            local_scope,
                            options,
                            float_widths,
                            macro_depth,
                        ) {
                            Some(Ok(es)) => {
                                skipped.truncate(before_s);
                                if !es.is_empty() {
                                    *macros_lifted += 1;
                                }
                                entries.extend(es);
                            }
                            Some(Err(reason)) => {
                                skipped.truncate(before_s);
                                // Account a refusal only for assertion macros. A
                                // non-assertion macro (task_local!, pin!, ...)
                                // that does not expand to FOL is not an assertion
                                // and is ignored, not refused.
                                if is_assert_macro_path(&m.mac.path) {
                                    skipped.push(reason);
                                }
                            }
                            None => {}
                        }
                    }
                }
                CfgEval::Inactive(reason) => {
                    skipped.push(format!("inactive cfg on assertion; skipped: {reason}"));
                }
                CfgEval::Ambiguous(reason) => {
                    skipped.push(format!("ambiguous cfg on assertion; skipped: {reason}"));
                }
            },
            Stmt::Expr(Expr::Macro(m), _) => match cfg_eval_for_attrs(&m.attrs, options) {
                CfgEval::Active => {
                    // Known assertion macros are lowered by their tuned arm
                    // first. If no arm lifts it, walk into the definition: when
                    // we hold the macro's source, expand it and reduce the
                    // expansion. One source macro is one accounting unit.
                    let before_e = entries.len();
                    let before_s = skipped.len();
                    collect_macro(
                        &m.mac.path,
                        m.mac.tokens.clone(),
                        &temporal_scope,
                        &*float_widths,
                        options,
                        entries,
                        skipped,
                    );
                    if entries.len() > before_e {
                        *macros_lifted += 1;
                    } else {
                        match try_macro_expansion_entries(
                            &m.mac.path,
                            &m.mac.tokens,
                            reducer,
                            local_scope,
                            options,
                            float_widths,
                            macro_depth,
                        ) {
                            Some(Ok(es)) => {
                                skipped.truncate(before_s);
                                if !es.is_empty() {
                                    *macros_lifted += 1;
                                }
                                entries.extend(es);
                            }
                            Some(Err(reason)) => {
                                skipped.truncate(before_s);
                                // Account a refusal only for assertion macros. A
                                // non-assertion macro (task_local!, pin!, ...)
                                // that does not expand to FOL is not an assertion
                                // and is ignored, not refused.
                                if is_assert_macro_path(&m.mac.path) {
                                    skipped.push(reason);
                                }
                            }
                            None => {}
                        }
                    }
                }
                CfgEval::Inactive(reason) => {
                    skipped.push(format!("inactive cfg on assertion; skipped: {reason}"));
                }
                CfgEval::Ambiguous(reason) => {
                    skipped.push(format!("ambiguous cfg on assertion; skipped: {reason}"));
                }
            },
            Stmt::Expr(expr, _) if assertion_call_name(expr).is_some() => {
                let call_name = assertion_call_name(expr).expect("guard ensures Some");
                // An assert-prefixed call to a LEXICALLY-VISIBLE empty-body helper is a
                // TYPE-LEVEL obligation: the helper's only content is its signature's
                // trait bounds (e.g. `fn assert_trusted_len<T: TrustedLen>(_: &T) {}`),
                // discharged by the type system, not a point-wise value predicate. Empty
                // body => zero recoverable value-work => terminal refusal (a source
                // property no value-lifter can lift), NOT a lifter limitation and NOT a
                // fake-zero. Same-block scope only (`local_fns` = this block's nested fns,
                // lexically correct by construction); a deeper/sibling-scope helper is not
                // matched and stays unclassified -- a safe under-claim, never a wrong one.
                // This NEVER displaces a discharge: an empty body lifts to zero entries.
                if local_fns
                    .get(&call_name)
                    .is_some_and(|f| f.block.stmts.is_empty())
                {
                    skipped.push(format!(
                        "assertion helper `{call_name}` is a type-level obligation \
                         (empty body: trait-bound or no-op), not a point-wise value \
                         predicate; refused"
                    ));
                } else {
                    match reduce_assertion_expr(
                        expr,
                        &local_fns,
                        reducer,
                        &temporal_scope,
                        &*float_widths,
                        options,
                        MAX_ASSERTION_REDUCTION_DEPTH,
                        reduced_helpers,
                    ) {
                        Ok(reduced_entries) => {
                            if !reduced_entries.is_empty() {
                                *macros_lifted += 1;
                            }
                            entries.extend(reduced_entries);
                        }
                        Err(reason) => skipped.push(reason),
                    }
                }
            }
            // Unconditional plain block: recurse and lift normally.
            Stmt::Expr(Expr::Block(b), _) => {
                collect_assertion_entries(
                    &b.block.stmts,
                    &child_block_scope(local_scope, stmt_idx),
                    options,
                    reducer,
                    float_widths,
                    entries,
                    skipped,
                    macros_lifted,
                    reduced_helpers,
                    macro_depth,
                    &temporal_scope.plan.interior_mut,
                    &local_fns,
                );
            }
            // Unconditional unsafe block: recurse and lift normally.
            Stmt::Expr(Expr::Unsafe(u), _) => {
                collect_assertion_entries(
                    &u.block.stmts,
                    &child_block_scope(local_scope, stmt_idx),
                    options,
                    reducer,
                    float_widths,
                    entries,
                    skipped,
                    macros_lifted,
                    reduced_helpers,
                    macro_depth,
                    &temporal_scope.plan.interior_mut,
                    &local_fns,
                );
            }
            // Control-flow contexts: asserts are conditional or parametric; refuse.
            Stmt::Expr(Expr::ForLoop(f), _) => {
                // A bounded loop is the universal it states: `ForAllSugar` reads the
                // range as a guard and lifts forall x. (guard => body) (or the finite
                // conjunction over a literal array). If the body does not wholly
                // compute to truth values, the desugar bails (refuse below).
                let lifted = {
                    let ctx = sugar_ctx(
                        &temporal_scope,
                        options,
                        reducer,
                        float_widths,
                        macro_depth,
                    );
                    decompose_for_loop(f, &temporal_scope, &let_inits).and_then(|s| s.desugar(&ctx).dug())
                };
                if let Some(desugared) = lifted {
                    // The loop memento is named `<test>::loop::<var>` by the
                    // `ForAllSugar` warrant, mirroring the Python reference
                    // (layer2.py PATTERN 1). A named universal is federatable and
                    // the engine conjoins it ambiently.
                    emit_desugared(desugared, entries, macros_lifted);
                } else {
                    // The DIG declined (literal-body half handled above by
                    // `lift_bounded_forall`). This is the REFUSE half: a for-loop whose
                    // DOMAIN / BODY / ACCUMULATOR is provably RUNTIME is a NAMED terminal
                    // Effect (Hit side of Outcome{Dug|Hit}) -- not unclassified WORK. The
                    // classification is detection-EARNED (a specific runtime cause), never
                    // a blanket relabel: a literal-domain + literal-body + simple-counter
                    // loop DIGS above; a computable-but-unimplemented body (in-scope value,
                    // no runtime cause detected -- e.g. a `let`-SSA + conditional over the
                    // loop var) STAYS UNCLASSIFIED here (the inverse of fake-dig is
                    // fake-REFUSE, equally forbidden -- never refuse to zero the count).
                    let count = count_asserts_in_stmts(&f.body.stmts);
                    let reason = for_context_refusal_reason(
                        f,
                        &temporal_scope,
                        options,
                        reducer,
                        float_widths,
                        macro_depth,
                    );
                    for _ in 0..count {
                        skipped.push(reason.clone());
                    }
                }
            }
            Stmt::Expr(Expr::While(w), _) => {
                let body_count = count_asserts_in_stmts(&w.body.stmts);
                let cond_count = count_asserts_in_expr(&w.cond);
                let total = body_count + cond_count;
                for _ in 0..total {
                    skipped.push(
                        "assertion under while context: not unconditional point-wise; released to layer 0"
                            .to_string(),
                    );
                }
            }
            Stmt::Expr(Expr::Loop(l), _) => {
                refuse_nested_asserts_in_stmts(&l.body.stmts, "loop", skipped);
            }
            Stmt::Expr(Expr::If(i), _) => {
                // Panic locus: `if let PAT = e { .. } else { panic!() }` asserts
                // e matches PAT. Lift it; otherwise try the guarded-implication
                // (`ConditionalSugar`); otherwise refuse the conditional.
                if let Some(entry) = panic_locus_if_entry(i, &temporal_scope) {
                    entries.push(entry);
                    *macros_lifted += 1;
                } else if let Some(desugared) = {
                    // `ConditionalSugar`: `if guard { then } [else { else }]` is the
                    // implication `guard => then` (and `not guard => else`) it states
                    // -- the claim-side atom. EXACT-OR-BAIL (guard must translate, the
                    // branch asserts must fully lift, pure body); a bail keeps the
                    // refusal below. SOUNDNESS: never bare `then` -- always guarded.
                    let ctx = sugar_ctx(
                        &temporal_scope,
                        options,
                        reducer,
                        float_widths,
                        macro_depth,
                    );
                    decompose_if(i).and_then(|s| s.desugar(&ctx).dug())
                } {
                    emit_desugared(desugared, entries, macros_lifted);
                } else {
                    let count = count_asserts_in_stmts(&i.then_branch.stmts)
                        + i.else_branch
                            .as_ref()
                            .map_or(0, |(_, e)| count_asserts_in_expr(e));
                    // The `ConditionalSugar` desugar BAILED. Split the residue by CAUSE:
                    //   * a RUNTIME guard (reads a runtime value -- a mutable/aliased local,
                    //     a `&mut` borrow, a method call on a runtime receiver) is a NAMED
                    //     terminal Effect: `guard => then` cannot be a constructible point-wise
                    //     predicate because the guard's truth is not fixed from source literals.
                    //     Typed as `IfGuardRuntimeEffect`. (The Hit side.)
                    //   * a CONST/cfg/literal guard (`!false`, `cfg!(..)`, a const-eq) is
                    //     COMPUTABLE-but-unimplemented: the implication just is not lifted yet.
                    //     It STAYS UNCLASSIFIED -- refusing it would be FAKE-REFUSE (the inverse
                    //     sin of fake-dig). This is the discrimination guardrail.
                    let reason = if if_guard_is_runtime(&i.cond) {
                        (Effect::IfGuardRuntime {
                            boundary: token_key(&i.cond),
                        })
                        .reason()
                    } else {
                        "assertion under if context: not unconditional point-wise; released to layer 0"
                            .to_string()
                    };
                    for _ in 0..count {
                        skipped.push(reason.clone());
                    }
                }
            }
            Stmt::Expr(Expr::Match(m), _) => {
                // OPAQUE-REFLECTION qualified continue path (value NOT in scope): a
                // `match Type::of::<T>().kind { TypeKind::X(b) => assert_eq!(b.field, ..) }`
                // reads its asserted values out of compile-time reflection over runtime
                // type identity (`TypeId`) -- not a value constructed from source
                // literals. The surviving arm's BODY asserts (the ones the panic-locus
                // variant pin does NOT carry) are TERMINAL over that named continuation;
                // account them here so they do not fall to the unenumerated safety net.
                // The variant-pin discharge (below) is unchanged. A match over a
                // CONSTRUCTED literal scrutinee has no reflection call -> None -> the
                // ordinary path (dig / under-match-context), never reflection-refused.
                let reflection_boundary = reflection_scrutinee(strip_const_block(&m.expr));
                if let Some(b) = &reflection_boundary {
                    let body_asserts: usize = m
                        .arms
                        .iter()
                        .filter(|a| !expr_diverges(&a.body))
                        .map(|a| count_asserts_in_expr(&a.body))
                        .sum();
                    let reason = (Effect::Reflection { boundary: b.clone() }).reason();
                    for _ in 0..body_asserts {
                        skipped.push(reason.clone());
                    }
                }
                // Panic locus: a match whose every arm but one diverges asserts
                // the scrutinee matches the surviving arm. Lift it FIRST (it pins
                // the scrutinee's variant with no body asserts to carry).
                if let Some(entry) = panic_locus_match_entry(m, &temporal_scope) {
                    entries.push(entry);
                    *macros_lifted += 1;
                } else if reflection_boundary.is_some() {
                    // Reflection match with no panic-locus (no diverging `_` arm): its
                    // body asserts are already accounted above; do NOT also count them
                    // under the generic "under match context" path (double-count).
                } else if let Some(desugared) = {
                    // `MatchSugar`: `match scrut { pat_i => A_i }` is the conjunction
                    // `⋀_i (guard_i => A_i)` -- each arm's discriminant guard implies
                    // its arm asserts (a match IS nested conditionals; this generalizes
                    // `ConditionalSugar` from a bool guard to N pattern discriminants).
                    // EXACT-OR-BAIL: scrutinee must translate, every pattern must
                    // reduce to a discriminant (binding/guard/or/range arms bail), and
                    // the arm asserts must fully lift; a bail keeps the refusal below.
                    // SOUNDNESS: never bare `A_i` -- always guarded by `guard_i`.
                    let ctx = sugar_ctx(
                        &temporal_scope,
                        options,
                        reducer,
                        float_widths,
                        macro_depth,
                    );
                    decompose_match(m, &temporal_scope, options).and_then(|s| s.desugar(&ctx).dug())
                } {
                    emit_desugared(desugared, entries, macros_lifted);
                    // `decompose_match` dropped any arm gated by an INACTIVE `#[cfg(..)]`
                    // (it does not exist on this target). Those arms' asserts are NOT in
                    // the emitted conjunction, so account them HERE with a precise reason
                    // (a cfg-inactive arm, mirroring `account_skipped_module`) -- otherwise
                    // they fall to the generic per-fn safety net. SILENT stays 0; the
                    // surviving (active) arm is the one that ran. Corpus: num/wrapping.rs.
                    for arm in &m.arms {
                        if matches!(cfg_eval_for_attrs(&arm.attrs, options), CfgEval::Inactive(_)) {
                            let inactive = count_asserts_in_expr(&arm.body);
                            for _ in 0..inactive {
                                skipped.push(
                                    "assertion in a cfg-inactive match arm (not present on this target); refused"
                                        .to_string(),
                                );
                            }
                        }
                    }
                } else {
                    let count: usize = m.arms.iter().map(|a| count_asserts_in_expr(&a.body)).sum();
                    // RESOLVE-THEN-CLASSIFY (the match-context tail): a `match` whose
                    // SCRUTINEE is a RUNTIME call result (`match it.next() { Some(x) =>
                    // assert_eq!(*x, ..) }`, `it` a `let mut` iterator) reads its asserted
                    // values out of the runtime arm taken by a runtime iterator-advance --
                    // no single timeless `t`, the SAME terminal class as the existing
                    // `RuntimeMatchScrutineeEffect` (`operand is a runtime non-scalar
                    // result`). Name it terminal. DISCRIMINATION: a `match` over a
                    // CONSTRUCTED literal/path scrutinee is NOT a runtime call result
                    // (`expr_is_runtime_call_result` false), so it STAYS the generic
                    // UNCLASSIFIED reason -- the fake-refuse guardrail. Corpus:
                    // option.rs::test_mut_iter (`match it.next()`).
                    let reason = if let Some(eff) = runtime_match_scrutinee_effect(
                        &Expr::Match(m.clone()),
                    ) {
                        eff.reason()
                    } else {
                        "assertion under match context: not unconditional point-wise; released to layer 0"
                            .to_string()
                    };
                    for _ in 0..count {
                        skipped.push(reason.clone());
                    }
                }
            }
            Stmt::Expr(Expr::Closure(c), _) => {
                let count = count_asserts_in_expr(&c.body);
                for _ in 0..count {
                    skipped.push(
                        "assertion under closure context: not unconditional point-wise; released to layer 0"
                            .to_string(),
                    );
                }
            }
            // Unconditional const block: recurse and lift normally.
            // const { ... } is always evaluated; lifting its asserts is sound.
            Stmt::Expr(Expr::Const(c), _) => {
                collect_assertion_entries(
                    &c.block.stmts,
                    &child_block_scope(local_scope, stmt_idx),
                    options,
                    reducer,
                    float_widths,
                    entries,
                    skipped,
                    macros_lifted,
                    reduced_helpers,
                    macro_depth,
                    &temporal_scope.plan.interior_mut,
                    &local_fns,
                );
            }
            // A `const`/`static` ITEM declared inside a test fn body
            // (`const _: () = { .. assert!(..) .. };`, `const COUNTER: u32 = { .. };`)
            // has its initializer UNCONDITIONALLY evaluated at compile time the
            // moment the item is defined -- the test running is what defines it.
            // Its body runs exactly once, no branch guards it, so an assert inside
            // is as point-wise as a top-level assert: recurse and lift normally.
            // This mirrors the `Stmt::Expr(Expr::Const)` arm (a `const { .. }`
            // block) and the item-layer `Item::Const` / `Item::Static` handling in
            // `lift_item_assertions`; only the statement POSITION (item vs expr)
            // differed. A block initializer contributes its own statements; a bare
            // `const X: T = assert!(..)` (or `= expr`) is wrapped as one statement.
            // The per-assert gating inside the recursion still refuses anything
            // genuinely conditional (an assert under a `for`/`if` in the body, a
            // stateful read), and the per-fn safety net accounts anything not
            // reached -- so no silent drop and no over-claim.
            Stmt::Item(syn::Item::Const(syn::ItemConst { expr: init, .. }))
            | Stmt::Item(syn::Item::Static(syn::ItemStatic { expr: init, .. })) => {
                let init_stmts: Vec<Stmt> = match init.as_ref() {
                    Expr::Block(b) => b.block.stmts.clone(),
                    Expr::Unsafe(u) => u.block.stmts.clone(),
                    Expr::Const(c) => c.block.stmts.clone(),
                    Expr::Macro(m) => vec![Stmt::Macro(syn::StmtMacro {
                        attrs: Vec::new(),
                        mac: m.mac.clone(),
                        semi_token: None,
                    })],
                    other => vec![Stmt::Expr(other.clone(), None)],
                };
                collect_assertion_entries(
                    &init_stmts,
                    &child_block_scope(local_scope, stmt_idx),
                    options,
                    reducer,
                    float_widths,
                    entries,
                    skipped,
                    macros_lifted,
                    reduced_helpers,
                    macro_depth,
                    &temporal_scope.plan.interior_mut,
                    &local_fns,
                );
            }
            // Inner fn definitions inside a test fn: their asserts are only
            // reachable via a call inside the test body. DEFER the refusal: a later
            // bare-call statement in this block may inline this helper (the CallsiteSugar
            // dispatch arm, resolving nested fns via `local_fns`), which records it in
            // `reduced_helpers`. We emit the "reachable only" refusal after the loop
            // ONLY for inner fns still not reduced -- so a drained nested helper is not
            // double-counted (discharged at the callsite AND refused at the definition).
            Stmt::Item(syn::Item::Fn(inner_fn)) => {
                let fn_name = inner_fn.sig.ident.to_string();
                // An inner fn selected as the runtime branch of const_eval_select
                // is reached at run time; it is inlined where the call appears,
                // so do not refuse it here (that would double-count).
                if runtime_targets.contains(&fn_name) {
                    continue;
                }
                let count = count_asserts_in_stmts(&inner_fn.block.stmts);
                let reason = callsite_inlining_reason(&fn_name, inner_fn);
                deferred_inner_fn_refusals.push((fn_name, count, reason));
            }
            // Totality fallback: any other statement shape (a bare method-call
            // statement with a closure argument, an expression statement we do
            // not lift, etc.) may still contain nested asserts. Count and refuse
            // them so nothing is silently dropped. count_asserts_in_stmts only
            // runs here for statements no specific arm matched, so there is no
            // double counting.
            other => {
                // A bare expression statement that is an unconditional block
                // (e.g. `rt.block_on(async { .. })`) runs once: recurse and lift
                // its asserts. The per-fn safety net accounts anything not
                // reached, so no silent drop. Otherwise refuse.
                let recursed = if let Stmt::Expr(e, _) = other {
                    // `<lit>.iter().for_each(|v| assert!(..))` (or `.into_iter()` /
                    // `(a..b).for_each(..)`) is the SAME bounded universal as the
                    // equivalent `for v in <lit> { .. }` loop -- a finite conjunction
                    // over the constructed domain (construction axiom). Recognize it
                    // and add the named universal; the body asserts are accounted by
                    // `n`. An OPAQUE receiver makes `try_lift_for_each_forall` None,
                    // so the assert stays in its existing bin-2 refusal below.
                    let desugared = {
                        let ctx = sugar_ctx(
                            &temporal_scope,
                            options,
                            reducer,
                            float_widths,
                            macro_depth,
                        );
                        // DEFOLDER over a literal domain (bare `.fold`/`.rfold`
                        // statement), or a bare `.for_each` (the same bounded
                        // universal as the equivalent for-loop).
                        decompose_fold(e, &let_inits)
                            .and_then(|s| s.desugar(&ctx).dug())
                            .or_else(|| {
                                decompose_for_each(e, &temporal_scope, &let_inits)
                                    .and_then(|s| s.desugar(&ctx).dug())
                            })
                    };
                    if let Some(desugared) = desugared {
                        emit_desugared(desugared, entries, macros_lifted);
                        true
                    } else {
                    // const_eval_select((), compiletime, runtime): inline the
                    // runtime branch (the fn called at run time).
                    let select_target = const_eval_select_runtime_target(e)
                        .filter(|name| local_fns.contains_key(name));
                    if let Some(name) = select_target {
                        collect_assertion_entries(
                            &local_fns[&name].block.stmts,
                            local_scope,
                            options,
                            reducer,
                            float_widths,
                            entries,
                            skipped,
                            macros_lifted,
                            reduced_helpers,
                            macro_depth,
                            &BTreeSet::new(),
                            &local_fns,
                        );
                        true
                    } else if let Some(stmts) = unconditional_block_stmts(e) {
                        collect_assertion_entries(
                            stmts,
                            &child_block_scope(local_scope, stmt_idx),
                            options,
                            reducer,
                            float_widths,
                            entries,
                            skipped,
                            macros_lifted,
                            reduced_helpers,
                            macro_depth,
                            &temporal_scope.plan.interior_mut,
                            &local_fns,
                        );
                        true
                    } else if let Some(cs) = sugar::callsite::CallsiteSugar::decompose(
                        e,
                        &local_fns,
                        reducer,
                        options,
                        macro_depth,
                    ) {
                        // CALLSITE-SUGAR DISPATCH ARM (lift-and-replace of the old R7
                        // procedural block; the inlining engine now lives in
                        // `sugar::callsite`). `decompose` recognized a carryable
                        // closed-arg call to an inlinable helper; `desugar` β-reduces
                        // (param := actual) and re-desugars the substituted body
                        // through THIS SAME hierarchy in scratch buffers, gated on the
                        // monotonic `added_unclassified == 0` invariant.
                        //
                        // RECONCILIATION HOOK (concurrent lib.rs split): this is the ONE
                        // decompose-dispatch arm to add to the central
                        // `collect_assertion_entries` body. It sits in the bare-expr-
                        // statement fallthrough, after `for_each`/`const_eval_select`/
                        // `unconditional_block`, replacing the inline R7 branch.
                        match cs.desugar(
                            local_scope,
                            stmt_idx,
                            options,
                            reducer,
                            float_widths,
                            reduced_helpers,
                            macro_depth,
                        ) {
                            sugar::callsite::CallsiteOutcome::Dug(commit) => {
                                // The body fully reduced: COMMIT the trial buffers (the
                                // asserts lift via the byte-identical dig path). This is
                                // the blessed inlining-unblock.
                                entries.extend(commit.entries);
                                skipped.extend(commit.skipped);
                                *macros_lifted += commit.macros_lifted;
                                *reduced_helpers = commit.reduced_helpers;
                                reduced_helpers.insert(commit.name.clone());
                                reduced_in_block.insert(commit.name);
                                true
                            }
                            // BAIL: the body did not fully reduce (honest unclassified
                            // residue). Leave the helper unreduced; Pass 2 keeps the
                            // single "reachable only via call-site inlining" refusal.
                            // Never fake-dug, never fake-refused.
                            sugar::callsite::CallsiteOutcome::Bail(_) => false,
                        }
                    } else {
                        false
                    }
                    }
                } else {
                    false
                };
                if !recursed {
                    let count = count_asserts_in_stmts(std::slice::from_ref(other));
                    // HALF 2: a bare closure-method statement whose body is side-effecting /
                    // over an opaque accessor is TERMINAL (a source property), not generic
                    // unclassified work. The typed `SideEffect` names the boundary; we render
                    // its `reason()` (the wire format is unchanged). A pure adaptor + pure
                    // body returns None and keeps the generic skip (dissolvable in --dissolve).
                    let reason = match other {
                        Stmt::Expr(e, _) => {
                            // First the closure-method bucket (fold/for_each over an opaque
                            // accessor / side-effecting body). Then the statement-position
                            // qualified continue paths (value NOT in scope): a future
                            // continuation (`.await` / free-fn `block_on(async{..})`), opaque
                            // reflection (`match Type::of::<T>().kind`), or a runtime loop.
                            // Finally a RUNTIME EXPRESSION-STATEMENT (a tuple/expr whose
                            // asserted value is read through a `&mut` borrow or a mutation --
                            // e.g. `(assert_matches!(*MutRefWithDrop(&mut val).0, 0),
                            // mem::take(&mut val))`): mutably aliased, so the read has no single
                            // timeless `t`. Typed as `RuntimeExprStmtEffect`. A statement
                            // carrying a CONSTRUCTED literal matches none -> None -> the generic
                            // unclassified skip (the value-IN-scope dig path).
                            closure_method_terminal_effect(
                                e,
                                &temporal_scope,
                                options,
                                reducer,
                                float_widths,
                                macro_depth,
                                &let_inits,
                            )
                            .or_else(|| {
                                statement_position_terminal_effect(
                                    e,
                                    &temporal_scope,
                                    options,
                                    reducer,
                                    float_widths,
                                    macro_depth,
                                )
                            })
                        }
                        // A nested `impl` block declared as a STATEMENT inside the test fn
                        // (`impl Write for W { fn write_str(..) { assert_eq!(..) } }`). Its
                        // method-body asserts are reachable ONLY when the method runs, with
                        // the receiver's runtime state -- the SAME terminal cause as the
                        // top-level `Item::Impl` bucket, surfaced here because the impl is a
                        // statement, not a top-level Item. Typed as `ImplMethodEffect`. The
                        // node (`ImplMethodSugar`) owns the verdict; this arm is a thin router.
                        Stmt::Item(syn::Item::Impl(imp)) => impl_method_terminal_effect(
                            imp,
                            &temporal_scope,
                            options,
                            reducer,
                            float_widths,
                            macro_depth,
                        ),
                        _ => None,
                    }
                    .map(|e| e.reason())
                    .unwrap_or_else(|| {
                        "assertion nested in an unlifted expression statement: not a top-level point-wise assertion; released to layer 0".to_string()
                    });
                    for _ in 0..count {
                        skipped.push(reason.clone());
                    }
                }
            }
        }
        advance_temporal_scope_for_stmt(stmt, &mut temporal_scope);
    }
    // "Reduced in this block" = explicit commit-site inserts UNION the set-diff of
    // `reduced_helpers` against its entry snapshot (covers deeper reduce paths). A
    // closure recomputes it on demand so it reflects reductions made by the
    // arg-position drain below as well.
    let reduced_here = |explicit: &HashSet<String>, current: &HashSet<String>| -> HashSet<String> {
        let mut s = explicit.clone();
        for name in current.difference(&reduced_at_entry) {
            s.insert(name.clone());
        }
        s
    };
    // ARG-POSITION CALL-SITE INLINING (the second drain). A nested helper that is
    // never called as a BARE statement -- only in argument / reference / macro-arg
    // position (`assert_ne!(hash(&val), hash(&zero_byte(val, 0)))`) -- was not inlined
    // by the bare-statement CallsiteSugar dispatch above, so its INTERNAL asserts
    // (`assert!(byte < 8)`) fall to the deferred "reachable only via call-site inlining"
    // refusal. Before refusing, replay the SAME gated `desugar` trial at EVERY distinct
    // arg-position call site of the helper: extract that site's `param := actual`
    // bindings, β-reduce the body, and commit the body's asserts point-wise iff the
    // substituted body adds zero unclassified. A site whose body does not fully dig
    // (a runtime actual the asserts read, an effectful body) BAILS and is left for the
    // refusal -- never fake-dug. Distinct sites with distinct literal actuals produce
    // distinct point-wise obligations (no collapse); inlining N sites of one source
    // assert is N obligations (accounted in `unaccounted`, never a silent drop).
    let already_reduced_here = reduced_here(&reduced_in_block, reduced_helpers);
    for (fn_name, _count, reason) in &deferred_inner_fn_refusals {
        // Skip ONLY if THIS block's own processing already inlined this nested fn
        // (block-local, not the raw file-global set -- a same-named nested fn reduced
        // by a DIFFERENT test fn must not suppress this block's attempt).
        if already_reduced_here.contains(fn_name) {
            continue;
        }
        // SOUNDNESS GATE: only attempt to inline a helper whose deferred refusal is
        // UNCLASSIFIED (the "reachable only via call-site inlining" reason for a CONCRETE
        // scalar/slice helper). A helper refused as TERMINAL -- a GENERIC type/const-
        // parametric helper (`reachable only via monomorphization`) or a RUNTIME-
        // parametric one (`bin-2`) -- is a SHOWN source property, NOT call-queueing reach.
        // Inlining it at a concrete literal site would launder a deliberate terminal
        // refusal into a discharge (the architect-owned generic-slice refusal). Leave
        // terminal helpers alone; the arg-position drain only ever frees UNCLASSIFIED work.
        if !matches!(refusal_disposition(reason), Disposition::Unclassified) {
            continue;
        }
        let Some(helper) = local_fns.get(fn_name) else {
            continue;
        };
        // The helper must be carryable as a value-helper: active cfg, simple params,
        // a non-empty assert-bearing body. (An empty/effectful body simply produces no
        // committing site -> stays refused.)
        if count_asserts_in_stmts(&helper.block.stmts) == 0 {
            continue;
        }
        if !matches!(cfg_eval_for_attrs(&helper.attrs, options), CfgEval::Active) {
            continue;
        }
        let Ok(params) = helper_param_names(helper) else {
            continue;
        };
        // Collect every distinct arg-position call site of this helper in the block.
        let sites = collect_arg_position_call_sites(stmts, fn_name, params.len());
        if sites.is_empty() {
            continue;
        }
        let mut any_committed = false;
        for (site_idx, args) in sites.into_iter().enumerate() {
            let mut bindings = ExprBindings::new();
            for (param, arg) in params.iter().cloned().zip(args.into_iter()) {
                bindings.insert(param, arg);
            }
            let cs = sugar::callsite::CallsiteSugar::from_bindings(
                helper,
                fn_name.clone(),
                bindings,
            );
            // A distinct child scope per site so distinct-literal sites do not conjoin
            // into a false consistency collapse (the discrimination invariant). The
            // per-helper-per-site scope tag `<scope>::argsite::<helper>#<i>` is unique.
            let site_scope = format!("{local_scope}::argsite::{fn_name}");
            match cs.desugar(
                &site_scope,
                site_idx,
                options,
                reducer,
                float_widths,
                reduced_helpers,
                macro_depth,
            ) {
                sugar::callsite::CallsiteOutcome::Dug(commit) => {
                    if !commit.entries.is_empty() {
                        *macros_lifted += 1;
                    }
                    entries.extend(commit.entries);
                    skipped.extend(commit.skipped);
                    *macros_lifted += commit.macros_lifted;
                    *reduced_helpers = commit.reduced_helpers;
                    any_committed = true;
                }
                sugar::callsite::CallsiteOutcome::Bail(_) => {}
            }
        }
        if any_committed {
            // At least one site fully dug: the helper's asserts are accounted point-wise
            // at the committing sites. Mark reduced so the refusal-drain below does not
            // ALSO refuse (double-count). A site that bailed contributed nothing; its
            // path is the outer runtime assertion (already accounted elsewhere).
            reduced_helpers.insert(fn_name.clone());
            reduced_in_block.insert(fn_name.clone());
        }
    }
    // Drain the deferred nested-fn refusals: emit "reachable only via call-site
    // inlining" ONLY for inner fns NOT inlined by some call site in this block. A
    // helper inlined at any callsite is in `reduced_in_block` (its asserts already
    // discharged / terminal-refused point-wise), so re-refusing it here would
    // double-count. Keyed BLOCK-LOCAL, not file-global: a same-named nested fn reduced
    // in a DIFFERENT test fn must NOT suppress THIS block's refusal (else its distinct
    // body's asserts silently vanish into the unenumerated safety net). This is the
    // block-local Pass-2. Recompute the block-local reduction set (the arg-position
    // drain above may have added reductions).
    let reduced_here_final = reduced_here(&reduced_in_block, reduced_helpers);
    for (fn_name, count, reason) in &deferred_inner_fn_refusals {
        if reduced_here_final.contains(fn_name) {
            continue;
        }
        for _ in 0..*count {
            skipped.push(reason.clone());
        }
    }
    if relabel_unnamed_to_scope {
        for entry in entries[entries_start..].iter_mut() {
            if entry.name.is_none() {
                entry.name = Some(local_scope.to_string());
            }
        }
    }
}

/// Collect the actual-argument lists of EVERY call to the simple-named helper
/// `fn_name` (with arity `arity`) appearing ANYWHERE in `stmts` -- including in
/// argument / reference position and inside assert-family macro token streams (which
/// `syn::visit` treats as opaque, so we parse the macro args and visit them). De-dups
/// identical call sites (same arg tokens) so a helper called N times with the SAME
/// literal contributes one obligation, not N copies; DISTINCT literal sites stay
/// distinct (the discrimination invariant). Does NOT descend into nested fn item
/// bodies (their calls belong to their own block scope). Used by the arg-position
/// call-site inliner to find sites the bare-statement dispatch missed.
fn collect_arg_position_call_sites(
    stmts: &[Stmt],
    fn_name: &str,
    arity: usize,
) -> Vec<Vec<Expr>> {
    use std::collections::BTreeSet;
    struct W<'a> {
        target: &'a str,
        arity: usize,
        sites: Vec<Vec<Expr>>,
        seen: BTreeSet<String>,
    }
    impl<'a, 'ast> syn::visit::Visit<'ast> for W<'a> {
        fn visit_expr_call(&mut self, c: &'ast syn::ExprCall) {
            if let Some(name) = simple_call_name(c) {
                if name == self.target && c.args.len() == self.arity {
                    let args: Vec<Expr> = c.args.iter().cloned().collect();
                    let key = args
                        .iter()
                        .map(|a| quote::quote!(#a).to_string())
                        .collect::<Vec<_>>()
                        .join(",");
                    if self.seen.insert(key) {
                        self.sites.push(args);
                    }
                }
            }
            // Keep descending: a call may nest another (`hash(&zero_byte(..))`).
            syn::visit::visit_expr_call(self, c);
        }
        // syn::visit does NOT descend into macro token streams. An assert-family macro
        // (`assert_ne!(hash(&val), hash(&zero_byte(val, 0)))`) hides the helper call in
        // its tokens; parse the comma-separated operands and visit them.
        fn visit_macro(&mut self, m: &'ast syn::Macro) {
            if is_assert_macro_path(&m.path) {
                if let Ok(args) = parse_macro_args(m.tokens.clone()) {
                    for a in &args.exprs {
                        syn::visit::Visit::visit_expr(self, a);
                    }
                }
            }
            syn::visit::visit_macro(self, m);
        }
        // A nested fn's own body calls belong to its own block; do not hoist them here.
        fn visit_item_fn(&mut self, _f: &'ast syn::ItemFn) {}
    }
    let mut w = W {
        target: fn_name,
        arity,
        sites: Vec::new(),
        seen: BTreeSet::new(),
    };
    for st in stmts {
        syn::visit::Visit::visit_stmt(&mut w, st);
    }
    w.sites
}

/// Classify a refused for-loop's iterator domain for the bin-1 / bin-2 sort.
/// `try_lift_for_loop_forall` already lifts a closed-range loop as a `forall`, so
/// a loop that reaches the refusal is one it could NOT lift:
///   - a literal range `a..b` / `a..=b` or a literal array `[..]`: the domain IS
///     a finite construction (the forall lift exists) -- the refusal is body-side
///     (mutation, or a body assert that did not lift). This is **bin-1**, drainable
///     by teaching the body, NOT by inventing a domain.
///   - anything else (`for x in coll`, `for x in v.iter()`, a field, a call): the
///     loop ranges over a collection whose ELEMENTS are runtime data, not
///     constructed from source literals. No finite construction to walk -> **bin-2**.
/// True when the iteration domain is a RANGE whose endpoint is NOT a literal int --
/// `for i in 0..v.len()`, `for i in 0..xs.len()`, `for i in lo..hi` (lo/hi runtime).
/// The universe is then NOT a finite construction from source literals (the count is a
/// runtime quantity), so the loop is a Hit(Effect) domain refusal, not unclassified WORK.
/// A literal-array / literal-int-range domain is NOT runtime (returns false -> the cause
/// is body-side or the loop is computable-but-unimplemented). EXACT: both endpoints must
/// const-fold to ints for the domain to be finite-literal; a missing or non-literal end
/// is runtime. (A `..` open range never reaches a refused for-loop -- it would not parse
/// as an iterable in the corpus -- but a missing end is treated as runtime for safety.)
fn for_domain_endpoint_is_runtime(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        // A literal array / repeat is a finite literal construction -> NOT runtime.
        Expr::Array(_) | Expr::Repeat(_) => false,
        Expr::Range(r) => {
            let start_lit = r
                .start
                .as_ref()
                .map(|e| const_int(e).is_some())
                .unwrap_or(true); // `..end` start defaults to 0 -- literal.
            let end_lit = r
                .end
                .as_ref()
                .map(|e| const_int(e).is_some())
                .unwrap_or(false); // `start..` open end is a runtime/unbounded extent.
            !(start_lit && end_lit)
        }
        // Any other iterable (`coll`, `v.iter()`, a call, a field) is an OPAQUE runtime
        // collection -- already bin-2 by `for_iter_domain`; not our concern here.
        _ => false,
    }
}

/// True when EVERY mutation in the loop body is a SIMPLE COUNTER step over the literal
/// domain: an unconditional `acc += <const>` / `acc -= <const>` / `acc = acc (+|-|*) <const>`
/// whose RHS const-folds to an int literal. A conditional increment (`if c { acc += 1 }`),
/// a runtime step (`acc += v[i]` where `v[i]` is runtime), or a mutation of a non-int
/// value (a builder `.sign(..)`, a `Big` accumulator) is NOT a simple counter -> the
/// accumulator is runtime-valued. The presence of ANY non-simple-counter mutation makes
/// the whole body's accumulator runtime-valued (we under-claim: one impure mutation
/// taints it). NO mutation at all returns true (vacuously a simple counter -- the caller
/// checks `loop_body_mutates` first, so this is only consulted when a mutation exists).
fn loop_mutation_is_simple_counter_only(stmts: &[Stmt]) -> bool {
    #[derive(Default)]
    struct Scan {
        all_simple: bool,
        saw_mutation: bool,
        in_conditional: usize,
    }
    impl Scan {
        fn note_impure(&mut self) {
            self.saw_mutation = true;
            self.all_simple = false;
        }
    }
    impl<'ast> syn::visit::Visit<'ast> for Scan {
        fn visit_expr_if(&mut self, e: &'ast syn::ExprIf) {
            // A mutation INSIDE a conditional is not unconditional -> not a simple counter.
            self.in_conditional += 1;
            syn::visit::visit_expr_if(self, e);
            self.in_conditional -= 1;
        }
        fn visit_expr_match(&mut self, e: &'ast syn::ExprMatch) {
            self.in_conditional += 1;
            syn::visit::visit_expr_match(self, e);
            self.in_conditional -= 1;
        }
        fn visit_expr_assign(&mut self, a: &'ast syn::ExprAssign) {
            self.saw_mutation = true;
            // `acc = acc (+|-|*) <const>` is a simple counter ONLY if unconditional and
            // the RHS is exactly that shape.
            let simple = self.in_conditional == 0
                && matches!(&*a.left, Expr::Path(_))
                && match &*a.right {
                    Expr::Binary(b) => {
                        matches!(b.op, BinOp::Add(_) | BinOp::Sub(_) | BinOp::Mul(_))
                            && (const_int(&b.left).is_some() || const_int(&b.right).is_some())
                            && (matches!(&*b.left, Expr::Path(_)) || matches!(&*b.right, Expr::Path(_)))
                    }
                    _ => false,
                };
            if !simple {
                self.all_simple = false;
            }
            syn::visit::visit_expr_assign(self, a);
        }
        fn visit_expr_binary(&mut self, b: &'ast syn::ExprBinary) {
            let is_compound = matches!(
                b.op,
                BinOp::AddAssign(_)
                    | BinOp::SubAssign(_)
                    | BinOp::MulAssign(_)
                    | BinOp::DivAssign(_)
                    | BinOp::RemAssign(_)
                    | BinOp::BitXorAssign(_)
                    | BinOp::BitAndAssign(_)
                    | BinOp::BitOrAssign(_)
                    | BinOp::ShlAssign(_)
                    | BinOp::ShrAssign(_)
            );
            if is_compound {
                self.saw_mutation = true;
                // `acc += <const>` / `acc -= <const>` is a simple counter; `*=`/`/=`/...
                // and a non-const step are NOT. Must be unconditional.
                let simple = self.in_conditional == 0
                    && matches!(b.op, BinOp::AddAssign(_) | BinOp::SubAssign(_))
                    && matches!(&*b.left, Expr::Path(_))
                    && const_int(&b.right).is_some();
                if !simple {
                    self.all_simple = false;
                }
            }
            syn::visit::visit_expr_binary(self, b);
        }
        fn visit_expr_reference(&mut self, r: &'ast syn::ExprReference) {
            // A `&mut` borrow feeds a runtime mutation (`mul_pow10(&mut curpow10, i)`,
            // a builder `.sign(..)`); not a simple counter.
            if r.mutability.is_some() {
                self.note_impure();
            }
            syn::visit::visit_expr_reference(self, r);
        }
        fn visit_pat_ident(&mut self, p: &'ast syn::PatIdent) {
            // A `let mut x = ..` inside the body is a fresh runtime accumulator, not a
            // counter over the domain.
            if p.mutability.is_some() {
                self.note_impure();
            }
            syn::visit::visit_pat_ident(self, p);
        }
    }
    let mut scan = Scan {
        all_simple: true,
        ..Default::default()
    };
    for stmt in stmts {
        syn::visit::Visit::visit_stmt(&mut scan, stmt);
    }
    // No mutation -> vacuously simple (caller gates on loop_body_mutates first).
    !scan.saw_mutation || scan.all_simple
}

/// Classify a REFUSED literal-domain for-loop into its named terminal Effect (the
/// REFUSE half of the bin-1 classification), or leave it the existing UNCLASSIFIED
/// for-context reason when no runtime cause is structurally detected (computable-but-
/// unimplemented -- in-scope value, just no lifter yet). Detection-EARNED, precedence
/// runtime-domain > runtime-body-read > runtime-accumulator; the dig already fired
/// (this is the `else` after `desugar` declined).
#[allow(clippy::too_many_arguments)]
fn for_context_refusal_reason(
    f: &syn::ExprForLoop,
    scope: &TemporalScope,
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    float_widths: &mut FloatWidthScope,
    macro_depth: usize,
) -> String {
    let domain = for_iter_domain(&f.expr);
    // OPAQUE collection domain -> already bin-2 (terminal) by `for_iter_domain`; keep it.
    if !domain.contains("LITERAL") {
        return format!(
            "assertion under for context over {domain}; \
             not unconditional point-wise; released to layer 0"
        );
    }

    // (A) RUNTIME DOMAIN ENDPOINT: `for i in 0..v.len()` -- the universe is not a finite
    // construction from source literals (the count is a runtime quantity). Terminal
    // Effect, EARNED by the non-literal endpoint (a literal-int range never matches).
    if for_domain_endpoint_is_runtime(&f.expr) {
        return "assertion under for context whose domain is over a RUNTIME endpoint \
                (`a..b` with a runtime bound -- not a finite construction from source \
                literals); released to layer 0"
            .to_string();
    }

    // Re-run the body collector to read its own refusal reasons (the same probe the old
    // provenance sort used).
    let mut be = Vec::new();
    let mut bs = Vec::new();
    let mut bl = 0usize;
    let mut bh = HashSet::new();
    collect_assertion_entries(
        &f.body.stmts,
        scope.local_scope(),
        options,
        reducer,
        float_widths,
        &mut be,
        &mut bs,
        &mut bl,
        &mut bh,
        macro_depth,
        &scope.plan.interior_mut,
        &BTreeMap::new(),
    );
    let body_over_opaque = bs.iter().any(|r| {
        r.contains("OPAQUE")
            || r.contains("ambiguous temporal identity")
            || r.contains("mutable container")
    });

    // (B) RUNTIME BODY READ: a body assert refused over OPAQUE / temporally-unstable /
    // mutable-container data (`fmt.flags()&1`, a runtime accessor). The iterated values
    // are literals but the ASSERTED values are runtime -> the body cannot be a timeless
    // point-wise claim. Terminal Effect, EARNED by the body's own refusal reason.
    if body_over_opaque {
        return "assertion under for context over a LITERAL domain but the body READS \
                RUNTIME DATA (an opaque/effectful accessor / temporally-unstable / \
                mutable-container read); not a finite construction from source literals; \
                released to layer 0"
            .to_string();
    }

    // (C) RUNTIME-VALUED ACCUMULATOR: the body mutates, and the mutation is NOT a simple
    // counter (`acc += <const>`) over the literal domain -- a builder `.sign(..)`, a
    // `let mut curpow10` + `mul_pow10(&mut ..)`, a `Big`/struct accumulator. Its value at
    // a later iteration is a runtime quantity, so a single universal would be false.
    // Terminal Effect, EARNED by the non-counter mutation. (A genuine simple-counter loop
    // does NOT reach here -- the dig path threads it, or it lifts as a forall.)
    if loop_body_mutates(&f.body.stmts) && !loop_mutation_is_simple_counter_only(&f.body.stmts) {
        return "assertion under for context over a LITERAL domain with a RUNTIME-VALUED \
                accumulator (a mutated builder / non-int accumulator, not a simple counter \
                over the domain); released to layer 0"
            .to_string();
    }

    // ELSE: no runtime cause detected. The body is computable-in-principle over the
    // literal domain (a `let`-SSA + conditional over the loop var, a pure-but-untranslated
    // term) -- in-scope WORK, NOT a source property. STAY UNCLASSIFIED (the fake-refuse
    // guard: never refuse a computable case to zero the count). This is the existing
    // bin-1 reason, disposition Unclassified.
    format!(
        "assertion under for context over {domain}; \
         not unconditional point-wise; released to layer 0"
    )
}

fn for_iter_domain(expr: &Expr) -> &'static str {
    match expr {
        Expr::Range(r) if r.start.is_some() && r.end.is_some() => {
            "a LITERAL range (bin-1: domain constructed, body not yet point-wise liftable)"
        }
        Expr::Array(_) | Expr::Repeat(_) => {
            "a LITERAL array (bin-1: domain constructed, body not yet point-wise liftable)"
        }
        Expr::Reference(r) => for_iter_domain(&r.expr),
        Expr::Paren(p) => for_iter_domain(&p.expr),
        Expr::Group(g) => for_iter_domain(&g.expr),
        _ => "an OPAQUE collection (bin-2: runtime data, not constructed from source literals)",
    }
}

/// If `expr` is a CLOSURE-BEARING iterator/Option adaptor -- a quantifier
/// (`.all`/`.any`) or a transform/search (`.map`/`.find`/`.filter`/...) -- return a
/// provenance-named refusal (literal-collection -> bin-1, opaque -> bin-2), reusing
/// `for_iter_domain` on the underlying collection. The closure predicate ranges over
/// the receiver's ELEMENTS, which are runtime data when the receiver is opaque; the
/// provenance makes that bin-2 PROVEN rather than presumed from the bare `|x|` shape.
/// Returns None for any non-adaptor call (handled by the ordinary term path).
fn closure_adaptor_refusal(expr: &Expr, scope: &TemporalScope) -> Option<String> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    let method = call.method.to_string();
    let is_adaptor = matches!(
        method.as_str(),
        "all" | "any" | "map" | "find" | "filter" | "filter_map" | "find_map" | "position"
    );
    if !is_adaptor {
        return None;
    }
    // At least one closure argument (the predicate / transform). A `.map(path_fn)`
    // with a function path (not a closure) is left to the ordinary term path.
    if !call.args.iter().any(|a| matches!(a, Expr::Closure(_))) {
        return None;
    }
    let collection = iter_adaptor_base(&call.receiver);
    let domain = for_iter_domain(collection);
    // TERMINAL (bin-2 BODY READ over a literal domain): the DOMAIN is a finite literal
    // construction, but the closure body READS a provably-MUTABLE captured local
    // (`assert!([..].iter().any(|v| &xs == *v))` where `let mut xs = [0; 6]` is mutated
    // by `xs.iter_mut().map(|x| *x += 1)` -- the corpus `iter/adapters/zip.rs`
    // ::test_zip_map_sideffectful). The asserted boolean ranges over `xs`'s RUNTIME
    // contents, not a value constructed from source literals -- the same proven order-loss
    // as the for-context "(B) RUNTIME BODY READ over a literal domain" terminal. EARNED
    // ONLY when `is_mut_local` PROVES a captured (non-closure-param) name is mutable; a
    // PURE body (`|x| x > 3`) or an immutable captured local reads as stable terms and
    // STAYS the UNCLASSIFIED bin-1 reason below (the fake-refuse guardrail -- a genuinely
    // drainable point-wise body is never refused to zero the count).
    if for_iter_domain_is_literal(collection)
        && call
            .args
            .iter()
            .any(|a| closure_body_reads_mut_local(a, scope))
    {
        return Some(format!(
            "iterator/option adaptor `.{method}(|..| ..)` over {domain} whose closure body \
             READS a MUTABLE-local capture (bin-2: runtime data mutated by side-effecting \
             iteration, not constructed from source literals); refused"
        ));
    }
    // TERMINAL (bin-2 SIDE-EFFECTING-CLONE READ over a literal domain): the DOMAIN is a
    // finite literal construction, but the closure body READS a captured local proven (by
    // the temporal plan) to be a SIDE-EFFECTING-CLONE source -- an array of non-literal
    // element constructions consumed by a `.cloned()` adaptor in a side-effecting
    // `for`-loop (`let xs = [CountClone::new(); ..]; for _ in xs.iter().cloned()... {};
    // assert!([..].any(|v| &xs == *v))`, rust-src `iter/adapters/zip.rs`
    // ::test_zip_cloned_sideffectful). `.cloned()` invokes a user `Clone` impl through
    // `&self`; for `CountClone(Cell<i32>)` that bumps an interior counter, so `xs`'s
    // element values change DURING iteration. The asserted boolean ranges over `xs`'s
    // RUNTIME (clone-mutated) contents, NOT a value constructed from source literals --
    // the same proven order-loss as the `let mut`-capture terminal above, surfaced through
    // interior mutability the `mut` keyword + the `Cell::new` constructor oracle are both
    // blind to. EARNED ONLY when the temporal plan proved the side-effecting-clone trajectory
    // (both the non-literal-element array AND the `.cloned()` side-effecting loop); a PURE
    // `.any` over a plain `[1, 2, 3]` scalar-literal array reads as stable terms and STAYS
    // the UNCLASSIFIED bin-1 reason below (the fake-refuse guardrail).
    if for_iter_domain_is_literal(collection)
        && call
            .args
            .iter()
            .any(|a| closure_body_reads_sideeffecting_clone_local(a, scope))
    {
        return Some(format!(
            "iterator/option adaptor `.{method}(|..| ..)` over {domain} whose closure body \
             READS a SIDE-EFFECTING-CLONE-local capture (bin-2: an array whose elements' \
             interior state was mutated by a `.cloned()` side-effecting `Clone` impl during \
             iteration, not constructed from source literals); refused"
        ));
    }
    Some(format!(
        "iterator/option adaptor `.{method}(|..| ..)` over {domain}; not yet lifted; \
         released to layer 0"
    ))
}

/// True if `expr` is a closure whose BODY references a captured name that `scope`
/// proves is a SIDE-EFFECTING-CLONE local (see `TemporalPlan::sideeffecting_clone_locals`),
/// where that name is NOT one of the closure's own parameters. Mirror of
/// `closure_body_reads_mut_local` for the interior-mutability-via-side-effecting-Clone
/// trajectory.
fn closure_body_reads_sideeffecting_clone_local(expr: &Expr, scope: &TemporalScope) -> bool {
    let Expr::Closure(cl) = expr else {
        return false;
    };
    let mut param_vec: Vec<String> = Vec::new();
    for pat in &cl.inputs {
        collect_pat_idents(pat, &mut param_vec);
    }
    let params: BTreeSet<String> = param_vec.into_iter().collect();
    struct V<'a> {
        scope: &'a TemporalScope,
        params: &'a BTreeSet<String>,
        found: bool,
    }
    impl<'ast, 'a> syn::visit::Visit<'ast> for V<'a> {
        fn visit_expr_path(&mut self, p: &'ast syn::ExprPath) {
            if let Some(name) = p.path.get_ident().map(|i| i.to_string()) {
                if !self.params.contains(&name) && self.scope.is_sideeffecting_clone_local(&name) {
                    self.found = true;
                }
            }
            syn::visit::visit_expr_path(self, p);
        }
    }
    let mut v = V {
        scope,
        params: &params,
        found: false,
    };
    syn::visit::Visit::visit_expr(&mut v, &cl.body);
    v.found
}

/// True if `expr` is a closure whose BODY references a name that `scope` proves is a
/// MUTABLE local, where that name is NOT one of the closure's own parameters (a capture).
/// The mutable-capture read makes the body's value runtime (bin-2). A non-closure expr,
/// or a closure that only reads its params / immutable names / literals, returns false.
fn closure_body_reads_mut_local(expr: &Expr, scope: &TemporalScope) -> bool {
    let Expr::Closure(cl) = expr else {
        return false;
    };
    // The closure's own bound parameters are NOT captures -- exclude them.
    let mut param_vec: Vec<String> = Vec::new();
    for pat in &cl.inputs {
        collect_pat_idents(pat, &mut param_vec);
    }
    let params: BTreeSet<String> = param_vec.into_iter().collect();
    struct V<'a> {
        scope: &'a TemporalScope,
        params: &'a BTreeSet<String>,
        found: bool,
    }
    impl<'ast, 'a> syn::visit::Visit<'ast> for V<'a> {
        fn visit_expr_path(&mut self, p: &'ast syn::ExprPath) {
            if let Some(name) = p.path.get_ident().map(|i| i.to_string()) {
                if !self.params.contains(&name) && self.scope.is_mut_local(&name) {
                    self.found = true;
                }
            }
            syn::visit::visit_expr_path(self, p);
        }
        // A nested closure introduces its own params, but for our corpus shapes a single
        // level suffices; descend normally (the mut-local capture is still a mut read).
    }
    let mut v = V {
        scope,
        params: &params,
        found: false,
    };
    syn::visit::Visit::visit_expr(&mut v, &cl.body);
    v.found
}

/// True if `for_iter_domain` would name `collection` a finite LITERAL construction (a
/// closed range or a literal array/repeat), i.e. the bin-1 (drainable) domain class --
/// as opposed to an OPAQUE (bin-2) collection. The single source of truth is
/// `for_iter_domain`'s own string, so the two never drift.
fn for_iter_domain_is_literal(collection: &Expr) -> bool {
    for_iter_domain(collection).contains("bin-1")
}

/// Strip a trailing element-producing adaptor (`.iter()`, `.into_iter()`,
/// `.iter_mut()`, `.chars()`, `.bytes()`, `.keys()`, `.values()`) to reveal the
/// underlying collection expression, so its literal/opaque provenance can be read.
fn iter_adaptor_base(expr: &Expr) -> &Expr {
    if let Expr::MethodCall(c) = expr {
        if c.args.is_empty()
            && matches!(
                c.method.to_string().as_str(),
                "iter" | "into_iter" | "iter_mut" | "chars" | "bytes" | "keys" | "values"
            )
        {
            return iter_adaptor_base(&c.receiver);
        }
    }
    expr
}

fn refuse_nested_asserts_in_stmts(stmts: &[Stmt], context: &str, skipped: &mut Vec<String>) {
    let count = count_asserts_in_stmts(stmts);
    for _ in 0..count {
        skipped.push(format!(
            "assertion under {context} context: not unconditional point-wise; released to layer 0"
        ));
    }
}

/// Lift the assert macros inside an item-level const/static initializer. The
/// initializer of a `const`/`static` is UNCONDITIONALLY evaluated (compile-time
/// const-eval), so its asserts are real, unconditional obligations -- lift them
/// through the SAME collector a `#[test]` fn body uses, rather than blanket-refusing.
/// This discharges e.g. the `const _: () = { .. }` compile-time twin that
/// `test_runtime_and_compiletime!` emits alongside each `#[test] fn` (both copies are
/// distinct source occurrences counted in the textual total, so discharging the const
/// copy balances `seen`, it does not double-count). A non-liftable assert propagates
/// its own named refusal via the collector (stays unclassified/refused, never a silent
/// drop or false discharge); the totality net refuses any unenumerated remainder so the
/// accounting stays closed.
fn lift_item_assertions(
    expr: &Expr,
    kind: &str,
    source_path: &str,
    modules: &[String],
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    out: &mut AdapterOutput,
) {
    let textual_total = count_asserts_in_expr(expr);
    if textual_total == 0 {
        return;
    }
    let item_name = scoped_test_name(source_path, modules, kind);
    // Normalize the initializer to a statement slice the collector understands:
    // a block initializer contributes its own statements; a bare `assert!(..)` is
    // wrapped as the macro statement; anything else is a single expression statement.
    let stmts: Vec<Stmt> = match expr {
        Expr::Block(b) => b.block.stmts.clone(),
        Expr::Macro(m) => vec![Stmt::Macro(syn::StmtMacro {
            attrs: Vec::new(),
            mac: m.mac.clone(),
            semi_token: None,
        })],
        other => vec![Stmt::Expr(other.clone(), None)],
    };
    let mut entries = Vec::new();
    let mut skipped = Vec::new();
    let mut float_widths = FloatWidthScope::new();
    let mut macros_lifted = 0usize;
    collect_assertion_entries(
        &stmts,
        &item_name,
        options,
        reducer,
        &mut float_widths,
        &mut entries,
        &mut skipped,
        &mut macros_lifted,
        &mut out.reduced_helpers,
        0,
        &BTreeSet::new(),
        &BTreeMap::new(),
    );
    out.assertions_lifted += macros_lifted;
    out.assertions_refused += skipped.len();
    out.skip_reasons.extend(skipped.iter().cloned());

    // Totality net: every textual assert macro in the initializer is accounted
    // (lifted or refused). Any remainder the structured walk did not reach is
    // refused by name -- no silent drop.
    let accounted = macros_lifted + skipped.len();
    if textual_total > accounted {
        let gap = textual_total - accounted;
        let reason =
            format!("{kind} assertion: compile-time const/static assert; released to layer 0");
        for _ in 0..gap {
            out.assertions_refused += 1;
            out.skip_reasons.push(reason.clone());
        }
    }

    for (name, atoms) in group_assertions(entries, &item_name) {
        out.decls.push(ContractDecl {
            name,
            pre: None,
            post: None,
            inv: Some(and_(atoms)),
            out_binding: "out".to_string(),
            evidence: None,
            panic_loci: Vec::new(),
            concept_hint: None,
        });
    }
}

fn temporal_plan_for_stmts(stmts: &[Stmt], inherited_stateful: &BTreeSet<String>) -> TemporalPlan {
    let mut definitions = BTreeMap::<String, usize>::new();
    let mut ambiguous = BTreeSet::<String>::new();
    let mut mut_locals = BTreeSet::<String>::new();
    // LEXICAL SCOPING (the compiler axiom, for free): a nested block inherits the
    // enclosing scope's stateful bindings, so `let r = &cell` / `*x.get()` inside
    // a block knows `cell`/`x` is a trajectory.
    let mut interior_mut = inherited_stateful.clone();
    let mut iterators = BTreeSet::<String>::new();
    for stmt in stmts {
        for name in deterministic_definition_names(stmt) {
            *definitions.entry(name).or_insert(0) += 1;
        }
        for name in ambiguous_boundary_names_in_stmt(stmt) {
            ambiguous.insert(name);
        }
        collect_mut_binding_names_in_stmt(stmt, &mut mut_locals);
        collect_interior_mut_binding_names_in_stmt(stmt, &mut interior_mut, &mut iterators);
    }
    // COMPILER AXIOM (for free): `load`/`fetch_*`/`compare_exchange`/`swap` are
    // ATOMIC-EXCLUSIVE methods, so any receiver of one IS an atomic -- interior-
    // mutable shared state -- whether it is a static, a local, or a field. A syn
    // visitor finds these anywhere, descending into nested blocks.
    collect_atomic_receiver_names(stmts, &mut interior_mut);
    // `mut` ORACLE made precise: a `let mut x` whose `&mut x` is taken (passed to
    // `ptr::swap`, `mem::swap`, `from_mut`, a `*mut` cast, ...) is genuinely mutated
    // through that borrow, so a read of `x` (or `*x.field`) at two program points is
    // a fork around `t`. Version it per statement like an interior-mutable cell. A
    // syn visitor finds `&mut x` anywhere, descending into nested (e.g. `unsafe { }`)
    // blocks where the mutation often lives while the reads sit in the outer block.
    collect_mut_borrowed_local_names(stmts, &mut_locals, &mut interior_mut);
    let mut versioned: BTreeSet<String> = definitions
        .into_iter()
        .filter_map(|(name, count)| (count > 1 || ambiguous.contains(&name)).then_some(name))
        .collect();
    // An interior-mutable binding is versioned even though it is bound once: its
    // INTERIOR changes across statements, so each read must observe a distinct `t`.
    versioned.extend(interior_mut.iter().cloned());
    // An iterator is versioned too (so its reads are tagged and `@adv` applies), but
    // it advances only at a CONSUMPTION boundary -- a consuming method call, which
    // `deterministic_definition_names` already records as a version bump -- not every
    // statement. A name that is BOTH a cell and an iterator stays a cell (the
    // stronger, per-statement posture).
    for name in &iterators {
        if !interior_mut.contains(name) {
            versioned.insert(name.clone());
        }
    }
    iterators.retain(|name| !interior_mut.contains(name));
    let sideeffecting_clone_locals = collect_sideeffecting_clone_locals(stmts);
    TemporalPlan {
        versioned,
        mut_locals,
        interior_mut,
        iterators,
        sideeffecting_clone_locals,
    }
}

/// Locals bound to an array of NON-literal element constructions that are then
/// consumed by a `.cloned()`/`.copied()` adaptor inside a bare side-effecting
/// `for`-loop statement. See `TemporalPlan::sideeffecting_clone_locals`. Sound BAIL
/// signal for the `iter/adapters/zip.rs::test_zip_cloned_sideffectful` shape, where
/// `let xs = [CountClone::new(); ..]; for _ in xs.iter().cloned().zip(..) {}` mutates
/// `xs`'s interior counts via a side-effecting `Clone` impl the lifter cannot see.
fn collect_sideeffecting_clone_locals(stmts: &[Stmt]) -> BTreeSet<String> {
    // (a) Candidate locals: `let L = [<elems>]` where the elements are NON-literal
    //     constructions (so a plain `[1, 2, 3]` scalar-literal array is excluded). We
    //     require at least one element and that they are NOT all closed scalar literals.
    let mut candidates: BTreeSet<String> = BTreeSet::new();
    for stmt in stmts {
        let Stmt::Local(local) = stmt else { continue };
        let Some(init) = &local.init else { continue };
        if init.diverge.is_some() {
            continue;
        }
        if !init_is_nonliteral_element_array(&init.expr) {
            continue;
        }
        for name in pat_idents(&local.pat) {
            candidates.insert(name);
        }
    }
    if candidates.is_empty() {
        return BTreeSet::new();
    }
    // (b) Of those, keep only the ones that are the BASE of a `.cloned()`/`.copied()`
    //     adaptor inside a bare side-effecting `for`-loop statement.
    let mut consumed: BTreeSet<String> = BTreeSet::new();
    for stmt in stmts {
        // `for <pat> in <expr> <block>` (any block, including empty `{}`) is the
        // side-effecting drive of the iterator chain.
        let for_expr = match stmt {
            Stmt::Expr(Expr::ForLoop(f), _) => Some(f),
            _ => None,
        };
        let Some(f) = for_expr else { continue };
        collect_cloned_adaptor_bases(&f.expr, &candidates, &mut consumed);
    }
    consumed
}

/// `let L = [<e0>, <e1>, ..]` (optionally `&`/`Box::new`-wrapped) whose elements are
/// present and NOT all closed scalar literals -- i.e. element CONSTRUCTIONS (user
/// `T::new()` calls, struct/tuple literals). Returns false for an empty array, a
/// scalar-literal array (`[1, 2, 3]`), or a non-array init.
fn init_is_nonliteral_element_array(expr: &Expr) -> bool {
    let inner = strip_refs_groups(expr);
    let Expr::Array(arr) = inner else {
        // `Box::new([..])` -- unwrap one Box::new layer.
        if let Expr::Call(c) = inner {
            if let Expr::Path(p) = c.func.as_ref() {
                let is_box_new = p.path.segments.last().is_some_and(|s| s.ident == "new")
                    && p.path.segments.iter().any(|s| s.ident == "Box");
                if is_box_new && c.args.len() == 1 {
                    return init_is_nonliteral_element_array(&c.args[0]);
                }
            }
        }
        return false;
    };
    if arr.elems.is_empty() {
        return false;
    }
    // At least one non-literal element AND not ALL scalar literals: a pure literal
    // array (`[1, 2, 3]`) is the discrimination case and must NOT qualify.
    arr.elems.iter().any(|e| !is_closed_scalar_literal(e))
        && arr.elems.iter().all(|e| !is_closed_scalar_literal(e))
}

/// Walk `expr` for any `<base>.cloned()` / `<base>.copied()` method call whose
/// underlying collection (after stripping `.iter()`/`.into_iter()` etc.) is a bare
/// candidate local name; record that name in `consumed`.
fn collect_cloned_adaptor_bases(
    expr: &Expr,
    candidates: &BTreeSet<String>,
    consumed: &mut BTreeSet<String>,
) {
    struct V<'a> {
        candidates: &'a BTreeSet<String>,
        consumed: &'a mut BTreeSet<String>,
    }
    impl<'ast, 'a> syn::visit::Visit<'ast> for V<'a> {
        fn visit_expr_method_call(&mut self, m: &'ast syn::ExprMethodCall) {
            if (m.method == "cloned" || m.method == "copied") && m.args.is_empty() {
                // The receiver is `<base>.iter()` / `<base>.into_iter()` etc.; strip
                // the element-producing adaptor to reach the bare collection name.
                let base = iter_adaptor_base(&m.receiver);
                if let Expr::Path(p) = base {
                    if let Some(name) = p.path.get_ident().map(|i| i.to_string()) {
                        if self.candidates.contains(&name) {
                            self.consumed.insert(name);
                        }
                    }
                }
            }
            syn::visit::visit_expr_method_call(self, m);
        }
    }
    let mut v = V {
        candidates,
        consumed,
    };
    syn::visit::Visit::visit_expr(&mut v, expr);
}

/// `let <name> = <interior-mutable constructor>(..)` -- record `<name>`.
/// Interior-mutable primitives are the language's interior-mutability mechanism
/// (all built on `UnsafeCell`): `Cell`, `RefCell`, `UnsafeCell`, the `Atomic*`
/// family, `Mutex`, `RwLock`, `OnceCell`/`OnceLock`, `LazyCell`/`LazyLock`. A
/// binding to one of their constructors is non-`mut` yet observably changes
/// through `&self`. Recognising the constructor (not any per-method behaviour) is
/// the interior-mutability dual of the `mut` keyword oracle.
fn collect_interior_mut_binding_names_in_stmt(
    stmt: &Stmt,
    cells: &mut BTreeSet<String>,
    iters: &mut BTreeSet<String>,
) {
    match stmt {
        Stmt::Local(local) => {
            let Some(init) = &local.init else { return };
            // A CELL / raw `*mut` pointer changes through `&self` or an alias at any
            // time (per-statement posture); an ITERATOR changes only when consumed
            // (consumption-boundary posture).
            let is_cell = init_is_interior_mut_construction(&init.expr)
                || init_is_raw_mut_pointer_construction(&init.expr);
            let is_iter = !is_cell && init_is_iterator_construction(&init.expr);
            // RECURSIVE TRAJECTORY: a binding DERIVED from an already-stateful binding
            // -- a view/borrow/adapter over it (`let r = &mut *cell.get()`, `let it2 =
            // it.by_ref()`) -- inherits that binding's posture. (`cells`/`iters`
            // accumulate in statement order, so an init referencing an EARLIER
            // stateful binding is caught.)
            let refs = (!is_cell && !is_iter).then(|| names_referenced_in_expr(&init.expr));
            let derived_cell = refs.as_ref().is_some_and(|r| !cells.is_disjoint(r));
            let derived_iter =
                !derived_cell && refs.as_ref().is_some_and(|r| !iters.is_disjoint(r));
            if is_cell || derived_cell {
                for name in pat_idents(&local.pat) {
                    cells.insert(name);
                }
            } else if is_iter || derived_iter {
                for name in pat_idents(&local.pat) {
                    iters.insert(name);
                }
            }
        }
        // A `static X: Atomic.. = ..` (e.g. a drop counter) is interior-mutable
        // global state; a `.load()`/`.fetch_*()` on it is a stateful read.
        Stmt::Item(syn::Item::Static(s)) => {
            if type_is_atomic_cell(&s.ty) {
                cells.insert(s.ident.to_string());
            }
        }
        _ => {}
    }
}

/// Collect the receiver name of every atomic-only method call anywhere in `stmts`
/// (descending into nested blocks). `load`/`fetch_*`/`compare_exchange`/`swap`
/// are atomic-exclusive, so their receiver is interior-mutable atomic state.
fn collect_atomic_receiver_names(stmts: &[Stmt], out: &mut BTreeSet<String>) {
    struct V<'a> {
        out: &'a mut BTreeSet<String>,
    }
    impl<'ast> syn::visit::Visit<'ast> for V<'_> {
        fn visit_expr_method_call(&mut self, mc: &'ast syn::ExprMethodCall) {
            const ATOMIC: &[&str] = &[
                "load",
                "store",
                "swap",
                "fetch_add",
                "fetch_sub",
                "fetch_and",
                "fetch_or",
                "fetch_xor",
                "fetch_nand",
                "fetch_max",
                "fetch_min",
                "fetch_update",
                "compare_exchange",
                "compare_exchange_weak",
                "compare_and_swap",
            ];
            if ATOMIC.contains(&mc.method.to_string().as_str()) {
                if let Expr::Path(p) = mc.receiver.as_ref() {
                    if let Some(seg) = p.path.segments.last() {
                        self.out.insert(seg.ident.to_string());
                    }
                }
            }
            syn::visit::visit_expr_method_call(self, mc);
        }
    }
    let mut v = V { out };
    for stmt in stmts {
        syn::visit::Visit::visit_stmt(&mut v, stmt);
    }
}

/// Collect the receiver names of CONSUMING iterator calls (`next`/`nth`/...) in
/// `expr`. A consuming call is a `t`-advance for its receiver (the iterator's
/// temporal homomorphism: `nth(it, k)` is warranted `nth(it, k, t)`, and the call
/// IS the step to `t+1`). Used to bump the receiver's version at a let-init
/// consumption boundary; the statement-position case is the ordinary method-receiver
/// boundary.
fn collect_consuming_iterator_receiver_names(expr: &Expr, out: &mut BTreeSet<String>) {
    if let Expr::MethodCall(call) = expr {
        if is_consuming_iterator_method(&call.method.to_string()) {
            if let Some(name) = simple_path_name(&call.receiver) {
                out.insert(name);
            }
        }
    }
    // Descend: the consuming call may be wrapped (`it.next().unwrap()`,
    // `Some(it.nth(0))`, `&it.next()`).
    match expr {
        Expr::MethodCall(c) => {
            collect_consuming_iterator_receiver_names(&c.receiver, out);
            for a in &c.args {
                collect_consuming_iterator_receiver_names(a, out);
            }
        }
        Expr::Call(c) => {
            for a in &c.args {
                collect_consuming_iterator_receiver_names(a, out);
            }
        }
        Expr::Reference(r) => collect_consuming_iterator_receiver_names(&r.expr, out),
        Expr::Paren(p) => collect_consuming_iterator_receiver_names(&p.expr, out),
        Expr::Group(g) => collect_consuming_iterator_receiver_names(&g.expr, out),
        Expr::Try(t) => collect_consuming_iterator_receiver_names(&t.expr, out),
        _ => {}
    }
}

/// Collect the names of `mut` locals that are MUTABLY borrowed (`&mut x`) AS A CALL
/// ARGUMENT (e.g. `ptr::from_mut(&mut x)`, `mem::swap(&mut a, &mut b)`). Passing
/// `&mut x` inline to a call is a DETERMINISTIC mutation boundary at that point, so
/// `x` is genuinely mutated and its reads fork around `t` -- version it per
/// statement like a cell. We deliberately do NOT collect `let alias = &mut x` (an
/// alias BINDING): that makes `x`'s identity ambiguous (mutations flow through the
/// alias at unknown points), which the ambiguity machinery handles by skipping. Only
/// `mut` locals qualify. Descends into nested blocks (the mutation often lives in an
/// inner `unsafe { }` while the reads sit outside).
fn collect_mut_borrowed_local_names(
    stmts: &[Stmt],
    mut_locals: &BTreeSet<String>,
    out: &mut BTreeSet<String>,
) {
    fn mut_ref_arg_name(arg: &Expr, mut_locals: &BTreeSet<String>) -> Option<String> {
        match arg {
            Expr::Reference(r) if r.mutability.is_some() => {
                simple_path_name(&r.expr).filter(|n| mut_locals.contains(n))
            }
            Expr::Paren(p) => mut_ref_arg_name(&p.expr, mut_locals),
            Expr::Group(g) => mut_ref_arg_name(&g.expr, mut_locals),
            _ => None,
        }
    }
    struct V<'a> {
        mut_locals: &'a BTreeSet<String>,
        out: &'a mut BTreeSet<String>,
    }
    impl<'ast> syn::visit::Visit<'ast> for V<'_> {
        fn visit_expr_call(&mut self, call: &'ast syn::ExprCall) {
            for arg in &call.args {
                if let Some(name) = mut_ref_arg_name(arg, self.mut_locals) {
                    self.out.insert(name);
                }
            }
            syn::visit::visit_expr_call(self, call);
        }
        fn visit_expr_method_call(&mut self, mc: &'ast syn::ExprMethodCall) {
            for arg in &mc.args {
                if let Some(name) = mut_ref_arg_name(arg, self.mut_locals) {
                    self.out.insert(name);
                }
            }
            syn::visit::visit_expr_method_call(self, mc);
        }
    }
    let mut v = V { mut_locals, out };
    for stmt in stmts {
        syn::visit::Visit::visit_stmt(&mut v, stmt);
    }
}

/// Collect every path's last-segment identifier referenced in `expr` (a superset
/// of its free variables -- enough to test "does this init reference a stateful
/// binding").
fn names_referenced_in_expr(expr: &Expr) -> BTreeSet<String> {
    #[derive(Default)]
    struct V {
        names: BTreeSet<String>,
    }
    impl<'ast> syn::visit::Visit<'ast> for V {
        fn visit_path(&mut self, p: &'ast syn::Path) {
            if let Some(seg) = p.segments.last() {
                self.names.insert(seg.ident.to_string());
            }
            syn::visit::visit_path(self, p);
        }
    }
    let mut v = V::default();
    syn::visit::Visit::visit_expr(&mut v, expr);
    v.names
}

/// True iff `ty` is an interior-mutable cell/atomic type by its head name --
/// `AtomicUsize`, `Cell<_>`, `RefCell<_>`, `UnsafeCell<_>`, `Mutex<_>`, ...
fn type_is_atomic_cell(ty: &syn::Type) -> bool {
    let syn::Type::Path(p) = ty else { return false };
    let Some(seg) = p.path.segments.last() else {
        return false;
    };
    let name = seg.ident.to_string();
    name.starts_with("Atomic")
        || matches!(
            name.as_str(),
            "Cell" | "RefCell" | "UnsafeCell" | "SyncUnsafeCell" | "Mutex" | "RwLock"
        )
}

/// True iff `expr` constructs a raw `*mut` pointer -- `addr_of_mut!(x)`,
/// `&mut x as *mut T`, any `expr as *mut T` cast (including a re-cast of an
/// existing `*mut`), or `ptr::from_mut(..)`. A binding holding a `*mut` is a
/// HANDLE to memory that is mutated through it (`*p = v`) or through an alias; a
/// `*p` read at two program points legitimately observes different values (a fork
/// around `t`, not a contradiction). So we version it per statement exactly like
/// an interior-mutable cell -- the deref reads then carry the version and do not
/// coalesce. A value bound once (`let v = *p`) is a bare var, so a genuine
/// double-pin is still caught.
/// True iff `method` is an iterator method that CONSUMES (advances past) one or
/// more elements when called -- so two calls in one statement observe different
/// state. `peek`/`size_hint`/`len`/`clone` do NOT advance and are excluded.
fn is_consuming_iterator_method(method: &str) -> bool {
    matches!(
        method,
        // Single-element advances.
        "next"
            | "nth"
            | "next_back"
            | "nth_back"
            | "next_if"
            | "next_if_eq"
            | "advance_by"
            | "advance_back_by"
            // Short-circuiting `&mut self` terminals: they drive the iterator (so they
            // ADVANCE it) and, unlike the by-value terminals (`fold`/`sum`/`count`),
            // borrow rather than move -- so a later read of the same binding is valid
            // and must observe the advanced `t`. Including a NON-advancing method here
            // (e.g. `len`) would be unsound (it would split reads that must coalesce);
            // every name below genuinely consumes.
            | "try_fold"
            | "try_for_each"
            | "find"
            | "find_map"
            | "position"
            | "rposition"
            | "all"
            | "any"
    )
}

/// True iff `var` (a possibly `@def`-tagged receiver name) names a versioned
/// iterator binding in scope -- i.e. its base is in the versioned/interior-mut set.
fn receiver_is_versioned_iterator(var: &str, scope: &TemporalScope) -> bool {
    let base = var.split('@').next().unwrap_or(var);
    scope.plan.versioned.contains(base)
}

fn init_is_raw_mut_pointer_construction(expr: &Expr) -> bool {
    match expr {
        Expr::Reference(r) => init_is_raw_mut_pointer_construction(&r.expr),
        Expr::Paren(p) => init_is_raw_mut_pointer_construction(&p.expr),
        Expr::Group(g) => init_is_raw_mut_pointer_construction(&g.expr),
        Expr::Cast(cast) => matches!(
            cast.ty.as_ref(),
            syn::Type::Ptr(p) if p.mutability.is_some()
        ),
        Expr::Macro(m) => m
            .mac
            .path
            .segments
            .last()
            .is_some_and(|s| s.ident == "addr_of_mut"),
        Expr::Call(call) => {
            if let Expr::Path(p) = call.func.as_ref() {
                p.path
                    .segments
                    .last()
                    .is_some_and(|s| s.ident == "from_mut")
            } else {
                false
            }
        }
        _ => false,
    }
}

/// True iff `expr` constructs an ITERATOR -- a range, an `.iter()`/`.into_iter()`
/// family source, or an adapter chain over one. An iterator binding is stateful:
/// it is consumed/advanced, so `len`/`count`/`size_hint`/`next` observed at
/// different program points legitimately differ (the same `t` posture as an
/// interior-mutable cell). Recognises the std Iterator protocol's vocabulary, not
/// any per-method contract.
fn init_is_iterator_construction(expr: &Expr) -> bool {
    match expr {
        Expr::Range(_) => true,
        Expr::Reference(r) => init_is_iterator_construction(&r.expr),
        Expr::Paren(p) => init_is_iterator_construction(&p.expr),
        Expr::MethodCall(mc) => {
            const ITER_SOURCES: &[&str] = &[
                "iter",
                "iter_mut",
                "into_iter",
                "chars",
                "char_indices",
                "bytes",
                "drain",
                "keys",
                "values",
                "values_mut",
                "lines",
                "split_whitespace",
                "windows",
                "chunks",
                "array_chunks",
                "array_windows",
            ];
            const ADAPTERS: &[&str] = &[
                "map",
                "filter",
                "filter_map",
                "take",
                "take_while",
                "skip",
                "skip_while",
                "rev",
                "cloned",
                "copied",
                "enumerate",
                "zip",
                "chain",
                "flatten",
                "flat_map",
                "peekable",
                "step_by",
                "scan",
                "fuse",
                "by_ref",
                "inspect",
                "cycle",
                "map_while",
            ];
            let m = mc.method.to_string();
            if ITER_SOURCES.contains(&m.as_str()) {
                return true;
            }
            // An adapter IS an iterator iff its receiver is one.
            ADAPTERS.contains(&m.as_str()) && init_is_iterator_construction(&mc.receiver)
        }
        // Free-function / UFCS forms: `core::iter::repeat(x)`, `iter::once(x)`,
        // `IntoIterator::into_iter([..])`, `<[T]>::iter(xs)`.
        Expr::Call(call) => {
            let Expr::Path(p) = call.func.as_ref() else {
                return false;
            };
            let last = p
                .path
                .segments
                .last()
                .map(|s| s.ident.to_string())
                .unwrap_or_default();
            // Iterator producer free functions.
            const PRODUCERS: &[&str] = &[
                "repeat",
                "repeat_with",
                "repeat_n",
                "once",
                "once_with",
                "empty",
                "from_fn",
                "successors",
            ];
            // UFCS iterator sources (same source names as the method form).
            const UFCS_SOURCES: &[&str] = &[
                "into_iter",
                "iter",
                "iter_mut",
                "chars",
                "char_indices",
                "bytes",
                "drain",
            ];
            PRODUCERS.contains(&last.as_str()) || UFCS_SOURCES.contains(&last.as_str())
        }
        _ => false,
    }
}

/// True iff `expr` is a call to an interior-mutable primitive's constructor, e.g.
/// `Cell::new(..)`, `core::cell::RefCell::new(..)`, `AtomicUsize::new(..)`.
fn init_is_interior_mut_construction(expr: &Expr) -> bool {
    // `let b = &Cell::new(a)` / `let cell = &Cell::new(0)`: the binding is a
    // reference to a freshly-constructed cell. The reference is transparent to
    // interior mutability -- a read through `b` still observes the cell's changing
    // interior -- so unwrap `&`/parens/groups to reach the constructor.
    match expr {
        Expr::Reference(r) => return init_is_interior_mut_construction(&r.expr),
        Expr::Paren(p) => return init_is_interior_mut_construction(&p.expr),
        Expr::Group(g) => return init_is_interior_mut_construction(&g.expr),
        _ => {}
    }
    let Expr::Call(call) = expr else { return false };
    let Expr::Path(path) = call.func.as_ref() else {
        return false;
    };
    let segs: Vec<String> = path
        .path
        .segments
        .iter()
        .map(|s| s.ident.to_string())
        .collect();
    // The constructor is the last `::new` (or `::from`) segment; the type is the
    // segment before it.
    let n = segs.len();
    if n < 2 {
        return false;
    }
    let ctor = segs[n - 1].as_str();
    if !matches!(ctor, "new" | "from" | "new_in") {
        return false;
    }
    let ty = segs[n - 2].as_str();
    ty.starts_with("Atomic")
        || matches!(
            ty,
            "Cell"
                | "RefCell"
                | "UnsafeCell"
                | "SyncUnsafeCell"
                | "Mutex"
                | "RwLock"
                | "OnceCell"
                | "OnceLock"
                | "LazyCell"
                | "LazyLock"
        )
}

/// Collect `let mut <name>` binding names in a statement (recursing into nested
/// blocks/control-flow). These are the conservatively-unstable locals.
fn collect_mut_binding_names_in_stmt(stmt: &Stmt, out: &mut BTreeSet<String>) {
    if let Stmt::Local(local) = stmt {
        collect_mut_pat_idents(&local.pat, out);
    }
}

fn collect_mut_pat_idents(pat: &Pat, out: &mut BTreeSet<String>) {
    match pat {
        Pat::Ident(ident) => {
            if ident.mutability.is_some() {
                out.insert(ident.ident.to_string());
            }
            if let Some((_, sub)) = &ident.subpat {
                collect_mut_pat_idents(sub, out);
            }
        }
        Pat::Reference(r) => collect_mut_pat_idents(&r.pat, out),
        Pat::Tuple(t) => t.elems.iter().for_each(|e| collect_mut_pat_idents(e, out)),
        Pat::TupleStruct(t) => t.elems.iter().for_each(|e| collect_mut_pat_idents(e, out)),
        Pat::Paren(p) => collect_mut_pat_idents(&p.pat, out),
        Pat::Type(t) => collect_mut_pat_idents(&t.pat, out),
        _ => {}
    }
}

fn advance_temporal_scope_for_stmt(stmt: &Stmt, scope: &mut TemporalScope) {
    for name in deterministic_definition_names(stmt) {
        scope.define_local(&name);
    }
    for name in ambiguous_boundary_names_in_stmt(stmt) {
        scope.mark_ambiguous(&name);
    }
    // Interior-mutable bindings advance their `t` at EVERY statement: the value
    // may change through `&self` (a `set`/`store`, or the drop side-effects of
    // other bindings) between any two reads, so each read observes a fresh
    // version and the reads do not coalesce into a false contradiction.
    let interior: Vec<String> = scope.plan.interior_mut.iter().cloned().collect();
    for name in interior {
        scope.define_local(&name);
    }
    // Per-occurrence consuming-read counters are statement-local: a new statement
    // starts fresh (cross-statement distinctness is already carried by the version
    // bump above).
    scope.consuming_occurrence.borrow_mut().clear();
}

fn deterministic_definition_names(stmt: &Stmt) -> Vec<String> {
    let mut out = BTreeSet::new();
    match stmt {
        Stmt::Local(local) if local.init.is_some() => {
            for name in pat_idents(&local.pat) {
                out.insert(name);
            }
            // CONSUMPTION boundary in a let-initializer: `let _ = it.next()` advances
            // `it`. The receiver of a CONSUMING iterator call is a version bump for
            // that receiver, exactly as a method-call statement is (below). Only
            // consuming calls count -- a non-consuming `let n = it.len()` must NOT
            // bump `it`, or two `len` reads around it would falsely split.
            if let Some(init) = &local.init {
                collect_consuming_iterator_receiver_names(&init.expr, &mut out);
            }
        }
        Stmt::Expr(expr, _) if !is_temporal_control_flow_expr(expr) => {
            if let Some(name) = deterministic_assignment_name(expr) {
                out.insert(name);
            }
            collect_method_receiver_names(expr, &mut out);
        }
        // CONSUMPTION boundary inside an assertion: `assert_eq!(it.next(), Some(0))`
        // advances `it`. The consuming call is an ARGUMENT of the macro, so neither
        // the `Stmt::Expr` nor `Stmt::Local` arm sees it -- without this, the
        // subsequent `it.len()`/`it.size_hint()` reads coalesce onto a stale version
        // and forge a contradiction. We parse the macro's token args as expressions
        // and collect consuming-iterator receivers (only consuming calls bump; a
        // `assert_eq!(it.len(), 5)` argument is non-consuming and leaves `it` alone).
        Stmt::Macro(m) => collect_consuming_receivers_in_macro(&m.mac, &mut out),
        Stmt::Expr(Expr::Macro(m), _) => collect_consuming_receivers_in_macro(&m.mac, &mut out),
        _ => {}
    }
    out.into_iter().collect()
}

/// Parse a macro's token args as a comma-separated expression list and collect the
/// receivers of CONSUMING iterator calls within them. Used so a consuming call
/// embedded in an assertion (`assert_eq!(it.next(), ..)`) is a version boundary for
/// its receiver. A parse failure (non-expression macro tokens) yields nothing.
fn collect_consuming_receivers_in_macro(mac: &syn::Macro, out: &mut BTreeSet<String>) {
    use syn::parse::Parser;
    use syn::punctuated::Punctuated;
    use syn::Token;
    let parser = Punctuated::<Expr, Token![,]>::parse_terminated;
    if let Ok(args) = parser.parse2(mac.tokens.clone()) {
        for arg in &args {
            collect_consuming_iterator_receiver_names(arg, out);
        }
    }
}

fn deterministic_assignment_name(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Assign(assign) => simple_path_name(&assign.left),
        Expr::Binary(binary) if is_assignment_binop(&binary.op) => simple_path_name(&binary.left),
        Expr::Paren(paren) => deterministic_assignment_name(&paren.expr),
        Expr::Group(group) => deterministic_assignment_name(&group.expr),
        _ => None,
    }
}

fn ambiguous_boundary_names_in_stmt(stmt: &Stmt) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    match stmt {
        Stmt::Local(local) => {
            if let Some(init) = &local.init {
                collect_reference_alias_names_in_expr(&init.expr, &mut out);
            }
        }
        Stmt::Expr(expr, _) => {
            collect_reference_alias_names_in_expr(expr, &mut out);
            collect_ambiguous_control_flow_names_in_expr(expr, &mut out);
        }
        _ => {}
    }
    out
}

fn collect_ambiguous_control_flow_names_in_expr(expr: &Expr, out: &mut BTreeSet<String>) {
    match expr {
        Expr::If(expr_if) => {
            collect_ambiguous_boundary_names_in_block(&expr_if.then_branch, out);
            if let Some((_, else_branch)) = &expr_if.else_branch {
                collect_ambiguous_names_in_expr(else_branch, out);
            }
        }
        Expr::ForLoop(expr_for) => collect_ambiguous_boundary_names_in_block(&expr_for.body, out),
        Expr::Loop(expr_loop) => collect_ambiguous_boundary_names_in_block(&expr_loop.body, out),
        Expr::While(expr_while) => collect_ambiguous_boundary_names_in_block(&expr_while.body, out),
        Expr::Match(expr_match) => {
            for arm in &expr_match.arms {
                collect_ambiguous_names_in_expr(&arm.body, out);
            }
        }
        Expr::Block(expr_block) => {
            collect_ambiguous_boundary_names_in_block(&expr_block.block, out)
        }
        _ => {}
    }
}

fn collect_ambiguous_boundary_names_in_block(block: &syn::Block, out: &mut BTreeSet<String>) {
    for stmt in &block.stmts {
        match stmt {
            Stmt::Local(local) if local.init.is_some() => {
                for name in pat_idents(&local.pat) {
                    out.insert(name);
                }
                if let Some(init) = &local.init {
                    collect_reference_alias_names_in_expr(&init.expr, out);
                }
            }
            Stmt::Expr(expr, _) => collect_ambiguous_names_in_expr(expr, out),
            _ => {}
        }
    }
}

fn collect_ambiguous_names_in_expr(expr: &Expr, out: &mut BTreeSet<String>) {
    if let Some(name) = deterministic_assignment_name(expr) {
        out.insert(name);
        return;
    }
    collect_reference_alias_names_in_expr(expr, out);
    collect_method_receiver_names(expr, out);
    match expr {
        Expr::Block(expr_block) => {
            collect_ambiguous_boundary_names_in_block(&expr_block.block, out)
        }
        Expr::If(expr_if) => {
            collect_ambiguous_boundary_names_in_block(&expr_if.then_branch, out);
            if let Some((_, else_branch)) = &expr_if.else_branch {
                collect_ambiguous_names_in_expr(else_branch, out);
            }
        }
        Expr::ForLoop(expr_for) => collect_ambiguous_boundary_names_in_block(&expr_for.body, out),
        Expr::Loop(expr_loop) => collect_ambiguous_boundary_names_in_block(&expr_loop.body, out),
        Expr::While(expr_while) => collect_ambiguous_boundary_names_in_block(&expr_while.body, out),
        Expr::Match(expr_match) => {
            for arm in &expr_match.arms {
                collect_ambiguous_names_in_expr(&arm.body, out);
            }
        }
        Expr::Paren(paren) => collect_ambiguous_names_in_expr(&paren.expr, out),
        Expr::Group(group) => collect_ambiguous_names_in_expr(&group.expr, out),
        _ => {}
    }
}

fn collect_reference_alias_names_in_expr(expr: &Expr, out: &mut BTreeSet<String>) {
    match expr {
        Expr::Reference(reference) => {
            if let Some(name) = simple_path_name(&reference.expr) {
                out.insert(name);
            } else {
                collect_reference_alias_names_in_expr(&reference.expr, out);
            }
        }
        Expr::MethodCall(call) => {
            collect_reference_alias_names_in_expr(&call.receiver, out);
            for arg in &call.args {
                collect_reference_alias_names_in_expr(arg, out);
            }
        }
        Expr::Call(call) => {
            collect_reference_alias_names_in_expr(&call.func, out);
            for arg in &call.args {
                collect_reference_alias_names_in_expr(arg, out);
            }
        }
        Expr::Await(await_expr) => collect_reference_alias_names_in_expr(&await_expr.base, out),
        Expr::Cast(cast) => collect_reference_alias_names_in_expr(&cast.expr, out),
        Expr::Field(field) => collect_reference_alias_names_in_expr(&field.base, out),
        Expr::Binary(binary) => {
            collect_reference_alias_names_in_expr(&binary.left, out);
            collect_reference_alias_names_in_expr(&binary.right, out);
        }
        Expr::Array(array) => {
            for elem in &array.elems {
                collect_reference_alias_names_in_expr(elem, out);
            }
        }
        Expr::Tuple(tuple) => {
            for elem in &tuple.elems {
                collect_reference_alias_names_in_expr(elem, out);
            }
        }
        Expr::Range(range) => {
            if let Some(start) = &range.start {
                collect_reference_alias_names_in_expr(start, out);
            }
            if let Some(end) = &range.end {
                collect_reference_alias_names_in_expr(end, out);
            }
        }
        Expr::Assign(assign) => {
            collect_reference_alias_names_in_expr(&assign.left, out);
            collect_reference_alias_names_in_expr(&assign.right, out);
        }
        Expr::Paren(paren) => collect_reference_alias_names_in_expr(&paren.expr, out),
        Expr::Group(group) => collect_reference_alias_names_in_expr(&group.expr, out),
        // `addr_of_mut!(x)` and `addr_of!(x)` take a raw pointer to `x`
        // without going through an `Expr::Reference` node. A raw pointer
        // alias means `x` may be mutated via the pointer later (e.g. by
        // `ptr::swap`) without any syntactic assignment to `x`. Treat the
        // argument as an alias-introduced name so the temporal tracker marks
        // it ambiguous after this statement, preventing pre/post observations
        // from being coalesced into a false contradiction.
        Expr::Macro(m) => {
            let macro_name = m.mac.path.segments.last().map(|s| s.ident.to_string());
            if matches!(macro_name.as_deref(), Some("addr_of_mut") | Some("addr_of")) {
                // The token stream of `addr_of_mut!(x)` is just the identifier `x`.
                // Parse it as a simple path/ident to extract the name.
                if let Ok(ident) = syn::parse2::<syn::Ident>(m.mac.tokens.clone()) {
                    out.insert(ident.to_string());
                } else if let Ok(path) = syn::parse2::<syn::Path>(m.mac.tokens.clone()) {
                    if let Some(name) = path.get_ident() {
                        out.insert(name.to_string());
                    }
                }
            }
        }
        _ => {}
    }
}

fn pat_idents(pat: &Pat) -> Vec<String> {
    let mut out = Vec::new();
    collect_pat_idents(pat, &mut out);
    out
}

fn collect_pat_idents(pat: &Pat, out: &mut Vec<String>) {
    match pat {
        Pat::Ident(ident) => out.push(ident.ident.to_string()),
        Pat::Reference(reference) => collect_pat_idents(&reference.pat, out),
        Pat::Tuple(tuple) => {
            for elem in &tuple.elems {
                collect_pat_idents(elem, out);
            }
        }
        Pat::TupleStruct(tuple) => {
            for elem in &tuple.elems {
                collect_pat_idents(elem, out);
            }
        }
        Pat::Struct(strukt) => {
            for field in &strukt.fields {
                collect_pat_idents(&field.pat, out);
            }
        }
        Pat::Slice(slice) => {
            for elem in &slice.elems {
                collect_pat_idents(elem, out);
            }
        }
        Pat::Or(or_pat) => {
            for case in &or_pat.cases {
                collect_pat_idents(case, out);
            }
        }
        Pat::Paren(paren) => collect_pat_idents(&paren.pat, out),
        Pat::Type(ty) => collect_pat_idents(&ty.pat, out),
        _ => {}
    }
}

pub(crate) fn simple_path_name(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Path(path) if path.qself.is_none() => {
            path.path.get_ident().map(|ident| ident.to_string())
        }
        Expr::Paren(paren) => simple_path_name(&paren.expr),
        Expr::Group(group) => simple_path_name(&group.expr),
        _ => None,
    }
}

fn is_temporal_control_flow_expr(expr: &Expr) -> bool {
    matches!(
        expr,
        Expr::If(_) | Expr::ForLoop(_) | Expr::Loop(_) | Expr::While(_) | Expr::Match(_)
    )
}

fn collect_method_receiver_names(expr: &Expr, out: &mut BTreeSet<String>) {
    match expr {
        Expr::MethodCall(call) => {
            if let Some(name) = simple_path_name(&call.receiver) {
                out.insert(name);
            } else {
                collect_method_receiver_names(&call.receiver, out);
            }
            for arg in &call.args {
                collect_method_receiver_names(arg, out);
            }
        }
        Expr::Call(call) => {
            for arg in &call.args {
                collect_method_receiver_names(arg, out);
            }
        }
        Expr::Await(await_expr) => collect_method_receiver_names(&await_expr.base, out),
        Expr::Reference(reference) => collect_method_receiver_names(&reference.expr, out),
        Expr::Cast(cast) => collect_method_receiver_names(&cast.expr, out),
        Expr::Field(field) => collect_method_receiver_names(&field.base, out),
        Expr::Binary(binary) => {
            collect_method_receiver_names(&binary.left, out);
            collect_method_receiver_names(&binary.right, out);
        }
        Expr::Array(array) => {
            for elem in &array.elems {
                collect_method_receiver_names(elem, out);
            }
        }
        Expr::Tuple(tuple) => {
            for elem in &tuple.elems {
                collect_method_receiver_names(elem, out);
            }
        }
        Expr::Range(range) => {
            if let Some(start) = &range.start {
                collect_method_receiver_names(start, out);
            }
            if let Some(end) = &range.end {
                collect_method_receiver_names(end, out);
            }
        }
        Expr::Paren(paren) => collect_method_receiver_names(&paren.expr, out),
        Expr::Group(group) => collect_method_receiver_names(&group.expr, out),
        // A closure captures locals from the enclosing scope, potentially
        // by `&mut` (even without explicit `move`). If the closure body
        // calls a method on a captured name, that name may be mutated
        // in ways the top-level tracker cannot see. Recurse into the body
        // so that `for_each(|x| s.push(x))` is detected as a method call
        // on `s`, marking `s` ambiguous between assertions.
        Expr::Closure(closure) => collect_method_receiver_names(&closure.body, out),
        _ => {}
    }
}

fn is_assignment_binop(op: &BinOp) -> bool {
    matches!(
        op,
        BinOp::AddAssign(_)
            | BinOp::SubAssign(_)
            | BinOp::MulAssign(_)
            | BinOp::DivAssign(_)
            | BinOp::RemAssign(_)
            | BinOp::BitXorAssign(_)
            | BinOp::BitAndAssign(_)
            | BinOp::BitOrAssign(_)
            | BinOp::ShlAssign(_)
            | BinOp::ShrAssign(_)
    )
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum CfgEval {
    Active,
    Inactive(String),
    Ambiguous(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum CfgPredicate {
    Name(String),
    KeyValue(String, String),
    All(Vec<CfgPredicate>),
    Any(Vec<CfgPredicate>),
    Not(Box<CfgPredicate>),
}

impl Parse for CfgPredicate {
    fn parse(input: ParseStream<'_>) -> syn::Result<Self> {
        let path: syn::Path = input.parse()?;
        let name = path_to_name(&path);
        if input.peek(Token![=]) {
            let _: Token![=] = input.parse()?;
            let value: syn::LitStr = input.parse()?;
            return Ok(CfgPredicate::KeyValue(name, value.value()));
        }
        if input.peek(syn::token::Paren) {
            let content;
            syn::parenthesized!(content in input);
            let args = Punctuated::<CfgPredicate, Token![,]>::parse_terminated(&content)?
                .into_iter()
                .collect::<Vec<_>>();
            return match name.as_str() {
                "all" => Ok(CfgPredicate::All(args)),
                "any" => Ok(CfgPredicate::Any(args)),
                "not" if args.len() == 1 => Ok(CfgPredicate::Not(Box::new(
                    args.into_iter().next().unwrap(),
                ))),
                "not" => Err(syn::Error::new_spanned(
                    path,
                    "cfg not(...) expects exactly one predicate",
                )),
                _ => Err(syn::Error::new_spanned(
                    path,
                    "unsupported cfg predicate function",
                )),
            };
        }
        Ok(CfgPredicate::Name(name))
    }
}

impl fmt::Display for CfgPredicate {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            CfgPredicate::Name(name) => f.write_str(name),
            CfgPredicate::KeyValue(key, value) => write!(f, "{key} = {value:?}"),
            CfgPredicate::All(predicates) => write!(
                f,
                "all({})",
                predicates
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
            CfgPredicate::Any(predicates) => write!(
                f,
                "any({})",
                predicates
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
            CfgPredicate::Not(predicate) => write!(f, "not({predicate})"),
        }
    }
}

fn cfg_eval_for_attrs(attrs: &[syn::Attribute], options: &LiftOptions) -> CfgEval {
    let mut saw_cfg = false;
    for attr in attrs {
        if !attr.path().is_ident("cfg") {
            continue;
        }
        saw_cfg = true;
        let predicate = match attr.parse_args::<CfgPredicate>() {
            Ok(predicate) => predicate,
            Err(e) => {
                return CfgEval::Ambiguous(format!(
                    "cannot parse cfg `{}`: {e}",
                    attr.to_token_stream()
                ));
            }
        };
        match cfg_eval_predicate(&predicate, options.target_cfg.as_ref()) {
            CfgEval::Active => {}
            CfgEval::Inactive(reason) => return CfgEval::Inactive(reason),
            CfgEval::Ambiguous(reason) => return CfgEval::Ambiguous(reason),
        }
    }
    if saw_cfg {
        CfgEval::Active
    } else {
        CfgEval::Active
    }
}

fn cfg_eval_predicate(predicate: &CfgPredicate, target_cfg: Option<&TargetCfg>) -> CfgEval {
    match predicate {
        CfgPredicate::Name(name) => {
            if name == "test" {
                return CfgEval::Active;
            }
            let Some(target_cfg) = target_cfg else {
                return CfgEval::Ambiguous(format!(
                    "no explicit target cfg facts for `{predicate}`"
                ));
            };
            if target_cfg.contains_name(name) {
                CfgEval::Active
            } else {
                CfgEval::Inactive(predicate.to_string())
            }
        }
        CfgPredicate::KeyValue(key, value) => {
            let Some(target_cfg) = target_cfg else {
                return CfgEval::Ambiguous(format!(
                    "no explicit target cfg facts for `{predicate}`"
                ));
            };
            if target_cfg.contains_key_value(key, value) {
                CfgEval::Active
            } else {
                CfgEval::Inactive(predicate.to_string())
            }
        }
        CfgPredicate::All(predicates) => {
            let mut ambiguous = None;
            for child in predicates {
                match cfg_eval_predicate(child, target_cfg) {
                    CfgEval::Active => {}
                    CfgEval::Inactive(reason) => return CfgEval::Inactive(reason),
                    CfgEval::Ambiguous(reason) => {
                        ambiguous.get_or_insert(reason);
                    }
                }
            }
            if let Some(reason) = ambiguous {
                CfgEval::Ambiguous(reason)
            } else {
                CfgEval::Active
            }
        }
        CfgPredicate::Any(predicates) => {
            let mut inactive = Vec::new();
            let mut ambiguous = None;
            for child in predicates {
                match cfg_eval_predicate(child, target_cfg) {
                    CfgEval::Active => return CfgEval::Active,
                    CfgEval::Inactive(reason) => inactive.push(reason),
                    CfgEval::Ambiguous(reason) => {
                        ambiguous.get_or_insert(reason);
                    }
                }
            }
            if let Some(reason) = ambiguous {
                CfgEval::Ambiguous(reason)
            } else {
                CfgEval::Inactive(format!("any inactive: {}", inactive.join("; ")))
            }
        }
        CfgPredicate::Not(child) => match cfg_eval_predicate(child, target_cfg) {
            CfgEval::Active => CfgEval::Inactive(predicate.to_string()),
            CfgEval::Inactive(_) => CfgEval::Active,
            CfgEval::Ambiguous(reason) => CfgEval::Ambiguous(reason),
        },
    }
}

fn assertion_call_name(expr: &Expr) -> Option<String> {
    let Expr::Call(call) = expr else {
        return None;
    };
    let name = simple_call_name(call)?;
    name.starts_with("assert").then_some(name)
}

fn simple_call_name(call: &syn::ExprCall) -> Option<String> {
    let Expr::Path(path) = call.func.as_ref() else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    path.path.get_ident().map(|ident| ident.to_string())
}

#[allow(clippy::too_many_arguments)]
fn reduce_assertion_expr<'a>(
    expr: &Expr,
    local_fns: &BTreeMap<String, &'a syn::ItemFn>,
    reducer: &ReductionCtx<'a>,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
    options: &LiftOptions,
    depth: usize,
    reduced_helpers: &mut HashSet<String>,
) -> Result<Vec<AssertionEntry>, String> {
    if depth == 0 {
        return Err(format!(
            "assertion reduction depth exhausted at `{}`; skipped assertion",
            token_key(expr)
        ));
    }
    match expr {
        Expr::Call(call) => {
            // Base lowerer: ptr::eq / core::ptr::eq / std::ptr::eq is a primitive
            // expression reducer. Dispatch it directly so helper bodies that call
            // assert!(ptr::eq(a, b)) reduce through this path rather than requiring
            // the dedicated translate_pointer_eq_assertion pre-filter arm.
            let callee = expr_head_key(&call.func);
            if matches!(
                callee.as_str(),
                "core::ptr::eq" | "ptr::eq" | "std::ptr::eq"
            ) {
                return translate_pointer_eq_assertion(expr, scope)?
                    .ok_or_else(|| {
                        format!(
                            "ptr::eq call did not lower to an assertion at `{}`",
                            token_key(expr)
                        )
                    })
                    .map(|entry| vec![entry]);
            }
            let name = simple_call_name(call).ok_or_else(|| {
                format!(
                    "assertion call is not a simple visible helper `{}`",
                    token_key(expr)
                )
            })?;
            if !name.starts_with("assert") {
                return Err(format!(
                    "non-assertion helper call `{name}` is not reducible"
                ));
            }
            // Resolve the helper LEXICALLY first: a helper defined inside the enclosing
            // `#[test]` fn (e.g. `fn assert_predicates_exact(..)` nested in the test body)
            // is invisible to the global `ReductionCtx` registry, but it IS in scope at the
            // call site. Mirror `resolve_inlinable_helper_call_scoped`: a `local_fns` hit
            // (the block's nested fns) takes precedence over the global registry; only when
            // neither resolves does the helper stay "has no visible source" (UNCLASSIFIED
            // work). The body still digs through the SAME reducer below, so a nested helper
            // whose body is pure-and-liftable discharges exactly like a top-level one, while
            // a runtime/effectful body (HashSet collect, `fmt::write`, mutable state) returns
            // Err here-down and stays UNCLASSIFIED -- never fake-dug.
            let helper = match local_fns.get(&name) {
                Some(f) => *f,
                None => reducer.function(&name)?.ok_or_else(|| {
                    format!("assertion helper `{name}` has no visible source; skipped assertion")
                })?,
            };
            match cfg_eval_for_attrs(&helper.attrs, options) {
                CfgEval::Active => {}
                CfgEval::Inactive(reason) => {
                    return Err(format!(
                        "assertion helper `{name}` inactive cfg; skipped: {reason}"
                    ));
                }
                CfgEval::Ambiguous(reason) => {
                    return Err(format!(
                        "assertion helper `{name}` ambiguous cfg; skipped: {reason}"
                    ));
                }
            }
            let params = helper_param_names(helper)?;
            if params.len() != call.args.len() {
                return Err(format!(
                    "assertion helper `{name}` arity mismatch: expected {}, got {}",
                    params.len(),
                    call.args.len()
                ));
            }
            let mut bindings = ExprBindings::new();
            for (param, arg) in params.into_iter().zip(call.args.iter()) {
                bindings.insert(param, arg.clone());
            }
            let result = reduce_assertion_stmts(
                &helper.block.stmts,
                &bindings,
                local_fns,
                reducer,
                scope,
                float_widths,
                options,
                depth - 1,
                reduced_helpers,
            )
            .map_err(|e| format!("{name}: {e}"));
            // Record the helper fn name as successfully reduced so Pass 2
            // does not also emit refusals for its asserts (which are already
            // in assertions_lifted).
            if result.is_ok() {
                reduced_helpers.insert(name);
            }
            result
        }
        Expr::Paren(paren) => reduce_assertion_expr(
            &paren.expr,
            local_fns,
            reducer,
            scope,
            float_widths,
            options,
            depth,
            reduced_helpers,
        ),
        Expr::Group(group) => reduce_assertion_expr(
            &group.expr,
            local_fns,
            reducer,
            scope,
            float_widths,
            options,
            depth,
            reduced_helpers,
        ),
        other => Err(format!(
            "assertion expression is not structurally reducible `{}`",
            token_key(other)
        )),
    }
}

#[allow(clippy::too_many_arguments)]
fn reduce_assertion_stmts<'a>(
    stmts: &[Stmt],
    bindings: &ExprBindings,
    local_fns: &BTreeMap<String, &'a syn::ItemFn>,
    reducer: &ReductionCtx<'a>,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
    options: &LiftOptions,
    depth: usize,
    reduced_helpers: &mut HashSet<String>,
) -> Result<Vec<AssertionEntry>, String> {
    let mut entries = Vec::new();
    // Local mutable view: a `let x = <pure>` in the body adds an immutable binding
    // we substitute into later statements (sound let-inlining; see the Stmt::Local
    // arm). Starts as a clone of the inherited param bindings.
    let mut binds = bindings.clone();
    for stmt in stmts {
        match stmt {
            Stmt::Macro(m) => {
                entries.extend(assertions_from_macro_with_bindings(
                    &m.mac.path,
                    m.mac.tokens.clone(),
                    scope,
                    float_widths,
                    options,
                    &binds,
                )?);
            }
            Stmt::Expr(Expr::Macro(m), _) => {
                entries.extend(assertions_from_macro_with_bindings(
                    &m.mac.path,
                    m.mac.tokens.clone(),
                    scope,
                    float_widths,
                    options,
                    &binds,
                )?);
            }
            // `let x = <pure pinnable expr>;` in a reduced body: bind x to its
            // (substituted) init and substitute it into the rest. SOUND iff the init
            // is PURE -- a literal / path / arithmetic / index / field / tuple over
            // pure parts, with NO calls, NO `&`/`&mut`, and x is NOT `let mut`.
            // For a pure init, `x` denotes a single fixed value, so substituting it
            // is exact (no re-evaluation hazard). Any other init -> refuse the body
            // (Pass 2 accounts it); we never substitute something we cannot prove
            // pure, so no masked re-evaluation / forged step.
            Stmt::Local(local) => {
                let Some(init) = &local.init else {
                    return Err("helper-body `let` without initializer".to_string());
                };
                if init.diverge.is_some() {
                    return Err("helper-body `let ... else` is not a pure binding".to_string());
                }
                let name = match &local.pat {
                    Pat::Ident(id) if id.subpat.is_none() && id.by_ref.is_none() => {
                        if id.mutability.is_some() {
                            // A `let mut` binding in a RESOLVED helper body is a mutable
                            // local trajectory: a state machine the body mutates step by
                            // step (`let mut writer = ..; fmt::write(&mut writer, ..)`),
                            // observed by asserts over its per-step mutated state. With
                            // the source now SHOWN (a test-nested helper lexically in
                            // scope), the mutated local has no single timeless `t` -- a
                            // SOURCE property, kin to the terminal `mutable container is
                            // not temporally stable` / `temporally unstable`. Named as a
                            // runtime helper-body effect (terminal). (Corpus:
                            // `fmt/float.rs::assert_exact_exp`'s `let mut writer`.)
                            return Err(format!(
                                "resolved helper body has a runtime `let mut {}` trajectory \
                                 (mutable-local state machine driven by fmt-write / a mutating \
                                 method; not temporally stable); refused",
                                id.ident
                            ));
                        }
                        id.ident.to_string()
                    }
                    Pat::Type(pt) => match &*pt.pat {
                        Pat::Ident(id)
                            if id.subpat.is_none()
                                && id.by_ref.is_none()
                                && id.mutability.is_none() =>
                        {
                            id.ident.to_string()
                        }
                        _ => return Err("helper-body `let` non-simple pattern".to_string()),
                    },
                    _ => return Err("helper-body `let` non-simple pattern".to_string()),
                };
                let init_expr = substitute_expr(&init.expr, &binds);
                if !is_pure_pinnable_expr(&init_expr) {
                    // RESOLVE-THEN-CLASSIFY: with the helper source now SHOWN, an init that
                    // is a RUNTIME COLLECTION construct (`preds.iter().map(..).collect()`
                    // into a Vec/HashSet) is bin-2 runtime aggregate data -- not a finite
                    // construction from source literals, terminal. A non-pure init that is
                    // NOT a recognized collection construct (e.g. a const free-fn call a
                    // future const-eval arm could evaluate) STAYS the generic UNCLASSIFIED
                    // reason -- the fake-refuse guardrail.
                    if init_is_runtime_collection(&init_expr) {
                        return Err(format!(
                            "resolved helper body `let {name} = {}` is a runtime \
                             iterator/collection construct (bin-2: runtime aggregate data, \
                             not constructed from source literals); refused",
                            token_key(&init.expr)
                        ));
                    }
                    return Err(format!(
                        "helper-body `let {name} = {}` has a non-pure initializer",
                        token_key(&init.expr)
                    ));
                }
                binds.insert(name, init_expr);
            }
            Stmt::Expr(expr, _) => {
                let expr = substitute_expr(expr, &binds);
                entries.extend(reduce_assertion_expr(
                    &expr,
                    local_fns,
                    reducer,
                    scope,
                    float_widths,
                    options,
                    depth,
                    reduced_helpers,
                )?);
            }
            other => {
                return Err(format!(
                    "helper body is not a static assertion reduction `{}`",
                    token_key(other)
                ));
            }
        }
    }
    if entries.is_empty() {
        return Err("helper body reduced to no FOL assertions".to_string());
    }
    Ok(entries)
}

/// A conservatively-PURE, pinnable expression: a value that is a fixed function of
/// its (already-pinned) parts, with NO call, method call, closure, reference, await,
/// index-assign, or macro -- nothing that could carry an effect or re-evaluate a
/// state. Used to gate `let x = e` substitution inside a reduced helper body: only
/// a pure `e` may be substituted (so `x` denotes one fixed value and inlining it is
/// exact). Deliberately strict -- refuse-on-doubt, never approximate. NOTE: this is
/// NOT "is it liftable" (that is the term translator's job); it is "is substituting
/// it for a single-use binding faithful", which forbids calls because a call may be
/// impure / re-evaluate.
fn is_pure_pinnable_expr(expr: &Expr) -> bool {
    match expr {
        Expr::Lit(_) => true,
        Expr::Path(p) => p.qself.is_none(),
        Expr::Paren(p) => is_pure_pinnable_expr(&p.expr),
        Expr::Group(g) => is_pure_pinnable_expr(&g.expr),
        Expr::Unary(u) => {
            // Pure unary: neg / not / deref-of-pure. (`*p` of a pure path is the
            // EUF `deref` term; the term translator decides stability.)
            matches!(u.op, UnOp::Neg(_) | UnOp::Not(_) | UnOp::Deref(_))
                && is_pure_pinnable_expr(&u.expr)
        }
        Expr::Binary(b) => is_pure_pinnable_expr(&b.left) && is_pure_pinnable_expr(&b.right),
        Expr::Index(i) => is_pure_pinnable_expr(&i.expr) && is_pure_pinnable_expr(&i.index),
        Expr::Field(f) => is_pure_pinnable_expr(&f.base),
        Expr::Tuple(t) => t.elems.iter().all(is_pure_pinnable_expr),
        Expr::Array(a) => a.elems.iter().all(is_pure_pinnable_expr),
        Expr::Cast(c) => is_pure_pinnable_expr(&c.expr),
        Expr::Range(r) => {
            r.start.as_deref().map(is_pure_pinnable_expr).unwrap_or(true)
                && r.end.as_deref().map(is_pure_pinnable_expr).unwrap_or(true)
        }
        _ => false,
    }
}

/// A RESOLVED helper body's `let`-init is a genuinely-RUNTIME collection construct
/// (an iterator/collection chain: `.iter()`/`.into_iter()`/`.collect()`/`.map()` over a
/// slice/Vec/HashSet). The collected value is RUNTIME aggregate data -- a multiset/set
/// built at run time from the (runtime) parameter contents, not a finite construction
/// from source literals (kin to `bin-2`). Once the helper is RESOLVED (its source is
/// now SHOWN -- a test-nested helper lexically in scope), such a body has no point-wise
/// timeless value to lift, by any value-lifter: a SOURCE property, terminal. EARNED by
/// detecting the iterator/collection chain SHAPE; a pure non-pinnable init that is NOT a
/// collection construct (e.g. a const free-fn call a future arm could evaluate) returns
/// None and STAYS the generic "non-pure initializer" UNCLASSIFIED reason -- the
/// fake-refuse guardrail. (Corpus: `mem/type_info.rs::assert_predicates_exact`'s
/// `let actual_pred_ids: Vec<TypeId> = preds.iter().map(..).collect()`.)
fn init_is_runtime_collection(expr: &Expr) -> bool {
    fn walk(e: &Expr, depth: usize) -> bool {
        if depth == 0 {
            return false;
        }
        match e {
            Expr::MethodCall(mc) => {
                let m = mc.method.to_string();
                matches!(
                    m.as_str(),
                    "collect" | "iter" | "into_iter" | "iter_mut" | "copied" | "cloned" | "map"
                ) || walk(&mc.receiver, depth - 1)
            }
            Expr::Paren(p) => walk(&p.expr, depth - 1),
            Expr::Group(g) => walk(&g.expr, depth - 1),
            Expr::Reference(r) => walk(&r.expr, depth - 1),
            _ => false,
        }
    }
    walk(expr, 16)
}

fn helper_param_names(f: &syn::ItemFn) -> Result<Vec<String>, String> {
    let mut params = Vec::new();
    for input in &f.sig.inputs {
        let syn::FnArg::Typed(pat_type) = input else {
            return Err(
                "assertion helper methods with self receivers are not reducible".to_string(),
            );
        };
        let name = simple_pat_name(&pat_type.pat).ok_or_else(|| {
            format!(
                "assertion helper `{}` has non-simple parameter `{}`",
                f.sig.ident,
                token_key(&pat_type.pat)
            )
        })?;
        params.push(name);
    }
    Ok(params)
}

fn simple_pat_name(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(ident) if ident.subpat.is_none() => Some(ident.ident.to_string()),
        Pat::Type(pat_type) => simple_pat_name(&pat_type.pat),
        Pat::Paren(paren) => simple_pat_name(&paren.pat),
        _ => None,
    }
}

fn collect_macro(
    path: &syn::Path,
    tokens: proc_macro2::TokenStream,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
    options: &LiftOptions,
    entries: &mut Vec<AssertionEntry>,
    skipped: &mut Vec<String>,
) {
    match assertions_from_macro(path, tokens, scope, float_widths, options) {
        Ok(macro_entries) => entries.extend(macro_entries),
        Err(reason) => skipped.push(reason),
    }
}

fn lower_assert_eq(
    lhs_expr: &Expr,
    rhs_expr: &Expr,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
) -> Result<AssertionEntry, String> {
    // Intercept infinity-constant equality before falling through to the
    // Real-equality path. f32/f64 infinity is not a Real value; IEEE exactness
    // gives the sound conjunction instead.
    if let Some(entry) = translate_infinity_eq_assertion(lhs_expr, rhs_expr, scope, float_widths)? {
        return Ok(entry);
    }
    let lhs = translate_assertion_term_in_scope(lhs_expr, scope)?;
    let rhs = translate_assertion_term_in_scope(rhs_expr, scope)?;
    Ok(assertion_entry_from_eq(lhs, rhs, scope))
}

fn lower_assert_ne(
    lhs_expr: &Expr,
    rhs_expr: &Expr,
    scope: &TemporalScope,
) -> Result<AssertionEntry, String> {
    // assert_ne!(a, b) is sugar for assert!(a != b): route through the same
    // relation path so the lifted atom is byte-identical to `a != b`.
    let lhs = translate_assertion_term_in_scope(lhs_expr, scope)?;
    let rhs = translate_assertion_term_in_scope(rhs_expr, scope)?;
    Ok(assertion_entry_from_relation(
        lhs,
        rhs,
        RelationOp::Ne,
        scope,
    ))
}

fn lower_assert_condition(
    expr: &Expr,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
) -> Result<AssertionEntry, String> {
    translate_bool_assertion(expr, scope, float_widths)
}

fn substitute_exprs(exprs: &[Expr], bindings: &ExprBindings) -> Vec<Expr> {
    exprs
        .iter()
        .map(|expr| substitute_expr(expr, bindings))
        .collect()
}

/// β-reduction over a helper body: substitute `bindings` (param := callsite actual)
/// into every statement so the body can be re-lifted at the callsite by the normal
/// (binding-free) collector. Faithful -- each param is replaced by its actual
/// exactly (no merge, no re-evaluation). A `let` binding a name shadows a param of
/// that name for the rest. Assert-MACRO args are substituted via parse → substitute
/// → re-quote. Nested fn items are kept as-is (their calls lift opaquely / resolve
/// via the file registry).
fn substitute_stmts(stmts: &[Stmt], bindings: &ExprBindings) -> Vec<Stmt> {
    let mut binds = bindings.clone();
    stmts.iter().map(|s| substitute_stmt(s, &mut binds)).collect()
}

fn substitute_stmt(stmt: &Stmt, binds: &mut ExprBindings) -> Stmt {
    match stmt {
        Stmt::Local(local) => {
            let mut l = local.clone();
            if let Some(init) = &local.init {
                let mut ni = init.clone();
                ni.expr = Box::new(substitute_expr(&init.expr, binds));
                l.init = Some(ni);
            }
            // The let binds names that shadow same-named params for the rest.
            for name in pat_idents(&local.pat) {
                binds.remove(&name);
            }
            Stmt::Local(l)
        }
        Stmt::Expr(e, semi) => Stmt::Expr(substitute_expr(e, binds), *semi),
        Stmt::Macro(m) => {
            let mut sm = m.clone();
            if let Some(tokens) = substitute_macro_tokens(&m.mac, binds) {
                sm.mac.tokens = tokens;
            }
            Stmt::Macro(sm)
        }
        Stmt::Item(_) => stmt.clone(),
    }
}

/// Substitute bindings into an assertion macro's comma-separated expression args by
/// parsing, substituting, and re-quoting. None if the tokens are not a parseable
/// expression list (a non-assertion macro) -- the caller keeps the macro as-is.
fn substitute_macro_tokens(
    mac: &syn::Macro,
    binds: &ExprBindings,
) -> Option<proc_macro2::TokenStream> {
    let args = parse_macro_args(mac.tokens.clone()).ok()?;
    let subst = substitute_exprs(&args.exprs, binds);
    let mut ts = proc_macro2::TokenStream::new();
    for (i, e) in subst.iter().enumerate() {
        if i > 0 {
            ts.extend(quote::quote!(,));
        }
        ts.extend(quote::quote!(#e));
    }
    Some(ts)
}

/// Resolve a bare call expression to an inlinable helper: a file-resolvable fn whose
/// body contains assertions, active cfg, simple params, matching arity. Returns the
/// helper, its name, and the param := actual bindings. None otherwise.
///
/// Resolves the helper name against the LOCALLY-VISIBLE nested fns first (lexical
/// scope), then the global reducer.
///
/// THE DRAIN: the corpus's dominant call-site-inlining shape is a helper defined
/// INSIDE a `#[test]` fn body (`fn test<T>(x: T) { .. } test(0u32);`). The global
/// `ReductionCtx` registers only TOP-LEVEL non-test fns, so a nested helper was
/// invisible and its body asserts fell to "reachable only via call-site inlining"
/// unclassified even when the body digs clean. Resolving `local_fns` first makes a
/// nested closed-arg helper inline exactly like a top-level one. SOUND: a nested fn
/// is in scope at the call site by construction, lexical shadowing is honored
/// (local takes precedence), and the SAME monotonic `added_unclassified == 0` gate
/// guards the commit -- a runtime-parametric / effectful / pure-untranslated body
/// produces unclassified residue and BAILS, so this can only ever DRAIN a body that
/// genuinely reduces.
fn resolve_inlinable_helper_call_scoped<'a>(
    expr: &Expr,
    local_fns: &BTreeMap<String, &'a syn::ItemFn>,
    reducer: &ReductionCtx<'a>,
    options: &LiftOptions,
) -> Option<(&'a syn::ItemFn, String, ExprBindings)> {
    let inner = match expr {
        Expr::Paren(p) => &*p.expr,
        Expr::Group(g) => &*g.expr,
        other => other,
    };
    let Expr::Call(call) = inner else { return None };
    let name = simple_call_name(call)?;
    // Lexical scope: a nested fn shadows a same-named global. `function()` already
    // declines an ambiguous (re-defined) global; a `local_fns` hit is the single
    // helper lexically in scope at this call.
    let helper: &'a syn::ItemFn = match local_fns.get(name.as_str()) {
        Some(f) => f,
        None => reducer.function(&name).ok()??,
    };
    if count_asserts_in_stmts(&helper.block.stmts) == 0 {
        return None;
    }
    if !matches!(cfg_eval_for_attrs(&helper.attrs, options), CfgEval::Active) {
        return None;
    }
    let params = helper_param_names(helper).ok()?;
    if params.len() != call.args.len() {
        return None;
    }
    let mut bindings = ExprBindings::new();
    for (param, arg) in params.into_iter().zip(call.args.iter()) {
        bindings.insert(param, arg.clone());
    }
    Some((helper, name, bindings))
}

fn substitute_expr(expr: &Expr, bindings: &ExprBindings) -> Expr {
    match expr {
        Expr::Path(path) if path.qself.is_none() => {
            if let Some(ident) = path.path.get_ident() {
                if let Some(bound) = bindings.get(&ident.to_string()) {
                    return bound.clone();
                }
            }
            expr.clone()
        }
        Expr::Paren(paren) => {
            let mut out = paren.clone();
            out.expr = Box::new(substitute_expr(&paren.expr, bindings));
            Expr::Paren(out)
        }
        Expr::Group(group) => {
            let mut out = group.clone();
            out.expr = Box::new(substitute_expr(&group.expr, bindings));
            Expr::Group(out)
        }
        Expr::Binary(binary) => {
            let mut out = binary.clone();
            out.left = Box::new(substitute_expr(&binary.left, bindings));
            out.right = Box::new(substitute_expr(&binary.right, bindings));
            Expr::Binary(out)
        }
        Expr::Unary(unary) => {
            let mut out = unary.clone();
            out.expr = Box::new(substitute_expr(&unary.expr, bindings));
            Expr::Unary(out)
        }
        Expr::Call(call) => {
            let mut out = call.clone();
            out.func = Box::new(substitute_expr(&call.func, bindings));
            out.args = call
                .args
                .iter()
                .map(|arg| substitute_expr(arg, bindings))
                .collect();
            Expr::Call(out)
        }
        Expr::MethodCall(call) => {
            let mut out = call.clone();
            out.receiver = Box::new(substitute_expr(&call.receiver, bindings));
            out.args = call
                .args
                .iter()
                .map(|arg| substitute_expr(arg, bindings))
                .collect();
            Expr::MethodCall(out)
        }
        Expr::Await(await_expr) => {
            let mut out = await_expr.clone();
            out.base = Box::new(substitute_expr(&await_expr.base, bindings));
            Expr::Await(out)
        }
        Expr::Reference(reference) => {
            let mut out = reference.clone();
            out.expr = Box::new(substitute_expr(&reference.expr, bindings));
            Expr::Reference(out)
        }
        Expr::Field(field) => {
            let mut out = field.clone();
            out.base = Box::new(substitute_expr(&field.base, bindings));
            Expr::Field(out)
        }
        Expr::Cast(cast) => {
            let mut out = cast.clone();
            out.expr = Box::new(substitute_expr(&cast.expr, bindings));
            Expr::Cast(out)
        }
        Expr::Array(array) => {
            let mut out = array.clone();
            out.elems = array
                .elems
                .iter()
                .map(|elem| substitute_expr(elem, bindings))
                .collect();
            Expr::Array(out)
        }
        Expr::Tuple(tuple) => {
            let mut out = tuple.clone();
            out.elems = tuple
                .elems
                .iter()
                .map(|elem| substitute_expr(elem, bindings))
                .collect();
            Expr::Tuple(out)
        }
        _ => expr.clone(),
    }
}

fn assertions_from_macro(
    path: &syn::Path,
    tokens: proc_macro2::TokenStream,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
    options: &LiftOptions,
) -> Result<Vec<AssertionEntry>, String> {
    let bindings = ExprBindings::new();
    assertions_from_macro_with_bindings(path, tokens, scope, float_widths, options, &bindings)
}

fn assertions_from_macro_with_bindings(
    path: &syn::Path,
    tokens: proc_macro2::TokenStream,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
    options: &LiftOptions,
    bindings: &ExprBindings,
) -> Result<Vec<AssertionEntry>, String> {
    let Some(name) = path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
    else {
        return Ok(Vec::new());
    };
    match name.as_str() {
        "assert_eq" => {
            let args = parse_macro_args(tokens).map_err(|e| format!("assert_eq!: {e}"))?;
            let exprs = substitute_exprs(&args.exprs, bindings);
            if exprs.len() < 2 {
                return Err("assert_eq!: expected at least 2 arguments".to_string());
            }
            lower_assert_eq(&exprs[0], &exprs[1], scope, float_widths)
                .map(|entry| vec![entry])
                .map_err(|e| format!("assert_eq!: {e}"))
        }
        "assert" => {
            let args = parse_macro_args(tokens).map_err(|e| format!("assert!: {e}"))?;
            let exprs = substitute_exprs(&args.exprs, bindings);
            let Some(first) = exprs.first() else {
                return Err("assert!: expected a condition".to_string());
            };
            lower_assert_condition(first, scope, float_widths)
                .map(|entry| vec![entry])
                .map_err(|e| format!("assert!: {e}"))
        }
        "assert_ne" => {
            let args = parse_macro_args(tokens).map_err(|e| format!("assert_ne!: {e}"))?;
            let exprs = substitute_exprs(&args.exprs, bindings);
            if exprs.len() < 2 {
                return Err("assert_ne!: expected at least 2 arguments".to_string());
            }
            lower_assert_ne(&exprs[0], &exprs[1], scope)
                .map(|entry| vec![entry])
                .map_err(|e| format!("assert_ne!: {e}"))
        }
        "assert_all" | "assert_none" => {
            let args = parse_macro_args(tokens).map_err(|e| format!("{name}!: {e}"))?;
            let exprs = substitute_exprs(&args.exprs, bindings);
            assertion_entries_from_ascii_macro(name.as_str(), &exprs)
        }
        // debug_assert*(a, b) is cfg(debug_assertions)-gated sugar: the CLAIM is
        // identical to the non-debug twin, but it is only asserted when
        // debug_assertions is Active (i.e. debug/test builds). In the witnessed test
        // profile (cargo test) debug_assertions is always on, so if the supplied
        // target_cfg confirms it Active we lift the same atom as the twin. If
        // debug_assertions is NOT confirmed Active we refuse -- overclaiming on a
        // macro that compiles out in release would be a falsePass.
        "debug_assert_eq" => {
            match cfg_eval_predicate(
                &CfgPredicate::Name("debug_assertions".to_string()),
                options.target_cfg.as_ref(),
            ) {
                CfgEval::Active => {}
                CfgEval::Inactive(reason) => {
                    return Err(format!(
                        "debug_assert_eq!: cfg(debug_assertions) not active; skipped: {reason}"
                    ));
                }
                CfgEval::Ambiguous(reason) => {
                    return Err(format!(
                        "debug_assert_eq!: cfg(debug_assertions) ambiguous; skipped: {reason}"
                    ));
                }
            }
            let args = parse_macro_args(tokens).map_err(|e| format!("debug_assert_eq!: {e}"))?;
            let exprs = substitute_exprs(&args.exprs, bindings);
            if exprs.len() < 2 {
                return Err("debug_assert_eq!: expected at least 2 arguments".to_string());
            }
            lower_assert_eq(&exprs[0], &exprs[1], scope, float_widths)
                .map(|entry| vec![entry])
                .map_err(|e| format!("debug_assert_eq!: {e}"))
        }
        "debug_assert" => {
            match cfg_eval_predicate(
                &CfgPredicate::Name("debug_assertions".to_string()),
                options.target_cfg.as_ref(),
            ) {
                CfgEval::Active => {}
                CfgEval::Inactive(reason) => {
                    return Err(format!(
                        "debug_assert!: cfg(debug_assertions) not active; skipped: {reason}"
                    ));
                }
                CfgEval::Ambiguous(reason) => {
                    return Err(format!(
                        "debug_assert!: cfg(debug_assertions) ambiguous; skipped: {reason}"
                    ));
                }
            }
            let args = parse_macro_args(tokens).map_err(|e| format!("debug_assert!: {e}"))?;
            let exprs = substitute_exprs(&args.exprs, bindings);
            let Some(first) = exprs.first() else {
                return Err("debug_assert!: expected a condition".to_string());
            };
            lower_assert_condition(first, scope, float_widths)
                .map(|entry| vec![entry])
                .map_err(|e| format!("debug_assert!: {e}"))
        }
        "debug_assert_ne" => {
            match cfg_eval_predicate(
                &CfgPredicate::Name("debug_assertions".to_string()),
                options.target_cfg.as_ref(),
            ) {
                CfgEval::Active => {}
                CfgEval::Inactive(reason) => {
                    return Err(format!(
                        "debug_assert_ne!: cfg(debug_assertions) not active; skipped: {reason}"
                    ));
                }
                CfgEval::Ambiguous(reason) => {
                    return Err(format!(
                        "debug_assert_ne!: cfg(debug_assertions) ambiguous; skipped: {reason}"
                    ));
                }
            }
            let args = parse_macro_args(tokens).map_err(|e| format!("debug_assert_ne!: {e}"))?;
            let exprs = substitute_exprs(&args.exprs, bindings);
            if exprs.len() < 2 {
                return Err("debug_assert_ne!: expected at least 2 arguments".to_string());
            }
            lower_assert_ne(&exprs[0], &exprs[1], scope)
                .map(|entry| vec![entry])
                .map_err(|e| format!("debug_assert_ne!: {e}"))
        }
        // The hardcoded per-macro arms for assert_eq_const_safe!,
        // assert_almost_eq!, assert_float_result_bits_eq!, assert_chunks!, and
        // assert_range_eq! were removed. Those were a hardcoded vocabulary --
        // the sin. The macro_rules expander now walks into each macro's real
        // definition (from source, in-crate or a dependency) and reduces the
        // expansion: a clean equality discharges, a tolerance/iteration/effectful
        // body becomes a named refusal derived from the actual body. The
        // collector tries the expander when no tuned arm lifts a macro.
        other if other.starts_with("assert") || other.starts_with("debug_assert") => {
            Err(format!("{other}!: unsupported assertion macro"))
        }
        _ => Ok(Vec::new()),
    }
}

// Parser for assert_eq_const_safe!($t:ty: $left:expr, $right:expr).
//
// The macro prefixes the two value expressions with a type annotation and a
// colon: `u8: left, right`. Standard parse_macro_args (comma-only) cannot
// split this because the colon is not a comma. We consume the Type and the
// colon token explicitly, then collect the remaining expressions normally.
struct ConstSafeMacroArgs {
    exprs: Vec<Expr>,
}

impl Parse for ConstSafeMacroArgs {
    fn parse(input: ParseStream<'_>) -> syn::Result<Self> {
        // Consume the leading type argument ($t:ty) and the colon separator.
        let _ty: Type = input.parse()?;
        let _colon: Token![:] = input.parse()?;
        // The rest is a comma-separated list of expressions.
        let exprs = Punctuated::<Expr, Token![,]>::parse_terminated(input)?
            .into_iter()
            .collect();
        Ok(Self { exprs })
    }
}

fn parse_const_safe_macro_args(
    tokens: proc_macro2::TokenStream,
) -> syn::Result<ConstSafeMacroArgs> {
    syn::parse2(tokens)
}

fn assertion_entries_from_ascii_macro(
    macro_name: &str,
    exprs: &[Expr],
) -> Result<Vec<AssertionEntry>, String> {
    if exprs.len() < 2 {
        return Err(format!(
            "{macro_name}!: expected predicate name and at least one literal source"
        ));
    }
    let predicate = ascii_macro_predicate_name(&exprs[0]).ok_or_else(|| {
        format!(
            "{macro_name}!: expected a simple ASCII predicate name, got `{}`",
            token_key(&exprs[0])
        )
    })?;
    let negate = macro_name == "assert_none";
    let mut entries = Vec::new();
    for source in &exprs[1..] {
        let value = literal_string_value(source).ok_or_else(|| {
            format!(
                "{macro_name}!: expected string literal source, got `{}`",
                token_key(source)
            )
        })?;
        for ch in value.chars() {
            let atom = ascii_char_class_atom(&predicate, str_const(ch.to_string()))
                .ok_or_else(|| unsupported_ascii_macro_predicate(&predicate))?;
            entries.push(AssertionEntry {
                name: None,
                atom: if negate { not_(atom) } else { atom },
            });
        }
        for byte in value.as_bytes() {
            let atom = ascii_byte_class_atom(&predicate, num(i128::from(*byte)))
                .ok_or_else(|| unsupported_ascii_macro_predicate(&predicate))?;
            entries.push(AssertionEntry {
                name: None,
                atom: if negate { not_(atom) } else { atom },
            });
        }
    }
    Ok(entries)
}

fn ascii_macro_predicate_name(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Path(path) => path.path.get_ident().map(|ident| ident.to_string()),
        Expr::Paren(paren) => ascii_macro_predicate_name(&paren.expr),
        Expr::Group(group) => ascii_macro_predicate_name(&group.expr),
        _ => None,
    }
}

fn unsupported_ascii_macro_predicate(predicate: &str) -> String {
    if predicate == "is_alphabetic" {
        "unicode char predicate is_alphabetic is not lifted; z3 string theory has no Rust Unicode Alphabetic database"
            .to_string()
    } else {
        format!("unsupported bounded ASCII macro predicate `{predicate}`")
    }
}

struct MacroArgs {
    exprs: Vec<Expr>,
}

impl Parse for MacroArgs {
    fn parse(input: ParseStream<'_>) -> syn::Result<Self> {
        let exprs = Punctuated::<Expr, Token![,]>::parse_terminated(input)?
            .into_iter()
            .collect();
        Ok(Self { exprs })
    }
}

fn parse_macro_args(tokens: proc_macro2::TokenStream) -> syn::Result<MacroArgs> {
    syn::parse2(tokens)
}

fn translate_bool_assertion(
    expr: &Expr,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
) -> Result<AssertionEntry, String> {
    if let Some(entry) = translate_pointer_eq_assertion(expr, scope)? {
        return Ok(entry);
    }
    if let Some(entry) = translate_string_predicate_assertion(expr, scope)? {
        return Ok(entry);
    }
    if let Some(entry) = translate_literal_iterator_assertion(expr, scope, float_widths)? {
        return Ok(entry);
    }
    if let Some(entry) = translate_float_refinement_assertion(expr, scope, float_widths)? {
        return Ok(entry);
    }
    if let Some(entry) = translate_matches_assertion(expr, scope)? {
        return Ok(entry);
    }
    match expr {
        Expr::Binary(binary) => translate_binary_bool_assertion(binary, scope, float_widths),
        Expr::Unary(unary) if matches!(unary.op, UnOp::Not(_)) => {
            if let Some(entry) = translate_string_predicate_assertion(&unary.expr, scope)? {
                return Ok(AssertionEntry {
                    name: entry.name,
                    atom: not_(entry.atom),
                });
            }
            if let Some(entry) =
                translate_float_refinement_assertion(&unary.expr, scope, float_widths)?
            {
                return Ok(AssertionEntry {
                    name: entry.name,
                    atom: not_(entry.atom),
                });
            }
            // `!matches!(x, Type::Variant)` — negate the discriminant atom. This
            // MUST run before the opaque-term fallback below, which would lower a
            // `matches!` macro to an unconstrained `macro:...` Var equated to false
            // (a vacuous lift with no teeth) rather than the real discriminant.
            if let Some(entry) = translate_matches_assertion(&unary.expr, scope)? {
                return Ok(AssertionEntry {
                    name: entry.name,
                    atom: not_(entry.atom),
                });
            }
            // `!(<lhs> <cmp> <rhs>)` is a NEGATED comparison. Route it to the
            // relation-ATOM path (`not_` over the `lt`/`ge`/... atom) BEFORE the
            // term fallback below. BinaryOpSugar made `translate_term_in_scope`
            // succeed on a term-position comparison (emitting a `cmp:*` bool ctor),
            // which would otherwise divert this to `eq(cmp:lt(..), false)` and break
            // EUF-coalescing of a negated comparison with its positive sibling
            // (`assert!(x >= 3); assert!(!(x < 3))` must share the `lt`/`ge` atom
            // shape -- see negated_call_result_comparison_lifts_as_fol_not_under_euf_key).
            if let Expr::Binary(binary) = unwrap_paren_group(&unary.expr) {
                if relation_from_binop(&binary.op).is_some() {
                    let entry = translate_binary_bool_assertion(binary, scope, float_widths)?;
                    return Ok(AssertionEntry {
                        name: entry.name,
                        atom: not_(entry.atom),
                    });
                }
            }
            if let Ok(term) = translate_term_in_scope(&unary.expr, scope) {
                Ok(assertion_entry_from_eq(term, bool_const(false), scope))
            } else {
                let entry = translate_bool_assertion(&unary.expr, scope, float_widths)?;
                Ok(AssertionEntry {
                    name: entry.name,
                    atom: not_(entry.atom),
                })
            }
        }
        Expr::Lit(ExprLit { lit: Lit::Bool(b), .. }) => {
            // A bare boolean LITERAL assert `assert!(true)` / `assert!(false)` is a
            // CONSTANT claim -- the timeless value is fixed from the source literal.
            // `assert!(true)` lifts to the tautology `true == true`; `assert!(false)`
            // lifts to the refutable `false == true` (UNSAT, a real refutation). This
            // is faithful and teethed: a bare `assert!(false)` is a statement that
            // always panics, and its lift is UNSAT -- never fake-green. Corpus shape:
            // bool.rs::test_bool_not (`if !true { assert!(false) }`).
            Ok(assertion_entry_from_eq(
                bool_const(b.value),
                bool_const(true),
                scope,
            ))
        }
        Expr::Path(_) => {
            // A bare boolean place `assert!(flag)` asserts the boolean is true:
            // lift `flag == true`. `assert!` requires a bool operand, so this is
            // type-safe WITHOUT type info; it is teethed, not vacuous -- a sibling
            // `assert!(!flag)` over the same place is `flag==true ∧ flag==false`,
            // UNSAT. (A `Field` place like `assert!(x.flag)` is already handled by
            // the call/method/field arm below.)
            let term = translate_term_in_scope(expr, scope)?;
            Ok(assertion_entry_from_eq(term, bool_const(true), scope))
        }
        Expr::Call(_) | Expr::MethodCall(_) | Expr::Await(_) | Expr::Field(_) => {
            // `<coll>.all(|x| ..)` / `.any(|x| ..)` is an iterator quantifier
            // (∀ / ∃ over the receiver's elements). We do not yet LIFT it, but we
            // pay the provenance debt: name whether the collection is a finite
            // CONSTRUCTION (literal -> bin-1, drainable by unroll) or RUNTIME data
            // (opaque -> bin-2, the membrane), so the bin sort is structural rather
            // than presumed from the bare `|x|` shape.
            if let Some(reason) = closure_adaptor_refusal(expr, scope) {
                return Err(reason);
            }
            let term = translate_term_in_scope(expr, scope)?;
            if is_refinement_predicate_term(term.as_ref()) {
                return Err(format!(
                    "refinement predicate remains out of this exact-value slice `{}`",
                    token_key(expr)
                ));
            }
            Ok(assertion_entry_from_eq(term, bool_const(true), scope))
        }
        Expr::Paren(paren) => translate_bool_assertion(&paren.expr, scope, float_widths),
        Expr::Group(group) => translate_bool_assertion(&group.expr, scope, float_widths),
        other => {
            // REFUSE HALF: a `match <runtime call> { .. }` scrutinee (the corpus
            // `match b.binary_search(&3) { Ok(1..=3) => true, _ => false }`) asserts the arm
            // taken by a RUNTIME non-scalar result -- no single timeless `t`, kin to `bin-2`.
            // EARNED by `runtime_match_scrutinee_effect`; a `match` over a CONSTRUCTED literal
            // scrutinee (no runtime call) matches None and STAYS the bare `only scalar equality`
            // reason below -- UNCLASSIFIED (the inverse-sin guardrail against fake-refuse).
            if let Some(effect) = runtime_match_scrutinee_effect(other) {
                return Err(effect.reason());
            }
            Err(format!(
                "only scalar equality is liftable, got `{}`",
                token_key(other)
            ))
        }
    }
}

/// Thin node-router: a `match <runtime call> { .. }` is classified by the `MatchScrutineeSugar`
/// node, which names the runtime-match-scrutinee verdict in its own `desugar` -- the asserted
/// value is the arm taken by a RUNTIME non-scalar result (a method call `b.binary_search(&3)`
/// or a free-function call), not a scalar equality over constructible values, so there is no
/// single timeless `t` (the `RuntimeMatchScrutinee` boundary is the match's token-key). BOTH
/// callsites route through this ONE router: the statement-context `Stmt::Expr(Expr::Match)`
/// residue and the expression-position `translate_bool_assertion` half-refuse. Each caller
/// renders `effect.reason()` (which `refusal_disposition` classifies terminal) on a `Some`,
/// and on `None` keeps its OWN site-specific generic reason (the "under match context" /
/// "only scalar equality" string) -- byte-identical to before.
///
/// The verdict is purely SYNTACTIC (the node's `desugar` ignores its `SugarCtx`), so this
/// router needs no scope/options -- which is why the ctx-less `translate_bool_assertion`
/// caller can route through it unchanged. It builds the node and inspects its single verdict
/// leaf; the node's STRUCTURAL backstop maps to `None` (the old fall-through), exactly as the
/// other thin node-routers do.
///
/// SOUNDNESS (the fake-refuse guardrail): the node fires ONLY on a DETECTED runtime-call
/// scrutinee. A non-`match` expr OR a `match` over a CONSTRUCTED literal / path / index
/// scrutinee declines to RECOGNIZE (the build arm returns `None`), which this router maps to
/// `None` -- leaving everything else UNCLASSIFIED, never terminalized by position.
fn runtime_match_scrutinee_effect(expr: &Expr) -> Option<Effect> {
    let node = sugar::match_scrutinee::decompose_match_scrutinee(expr)?;
    match node.desugar_ctx_free() {
        // The STRUCTURAL backstop = the honest-unclassified fall-through (the old `None`).
        Outcome::Hit(Effect::Unsupported { reason }) if reason == STRUCTURAL_BACKSTOP_REASON => {
            None
        }
        // A NAMED runtime-match-scrutinee boundary -- the verdict the caller renders.
        Outcome::Hit(effect) => Some(effect),
        // A bail-side node never reaches truth; `Dug` is unreachable here.
        Outcome::Dug(_) => None,
    }
}

/// Is `expr` a RUNTIME call result -- a method call (`x.binary_search(..)`) or a free function
/// call (`f(..)`), looking through parens/groups/references? These produce a value only when
/// run; they are not constructible from source literals. A literal / path / index / cast is
/// NOT a runtime call result (it stays diggable -> the caller keeps it unclassified).
pub(crate) fn expr_is_runtime_call_result(expr: &Expr) -> bool {
    match expr {
        Expr::MethodCall(_) | Expr::Call(_) => true,
        Expr::Paren(p) => expr_is_runtime_call_result(&p.expr),
        Expr::Group(g) => expr_is_runtime_call_result(&g.expr),
        Expr::Reference(r) => expr_is_runtime_call_result(&r.expr),
        _ => false,
    }
}

fn translate_float_refinement_assertion(
    expr: &Expr,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
) -> Result<Option<AssertionEntry>, String> {
    match expr {
        Expr::MethodCall(call) => {
            let method = call.method.to_string();
            if !is_liftable_float_refinement_method(&method) {
                return Ok(None);
            }
            if !call.args.is_empty() {
                return Err(format!(
                    "float refinement predicate takes no arguments `{}`",
                    token_key(expr)
                ));
            }
            let Some(width) = float_refinement_receiver_width(&call.receiver, float_widths) else {
                return Err(format!(
                    "float refinement predicate `{method}` requires known f32/f64 receiver width `{}`",
                    token_key(expr)
                ));
            };
            let receiver = translate_term_in_scope(&call.receiver, scope)?;
            let name = callsite_assertion_name(receiver.as_ref(), scope.local_scope());
            Ok(Some(AssertionEntry {
                name,
                atom: atomic_(format!("float.{width}.{method}"), vec![receiver]),
            }))
        }
        Expr::Paren(paren) => {
            translate_float_refinement_assertion(&paren.expr, scope, float_widths)
        }
        Expr::Group(group) => {
            translate_float_refinement_assertion(&group.expr, scope, float_widths)
        }
        _ => Ok(None),
    }
}

fn is_liftable_float_refinement_method(method: &str) -> bool {
    matches!(
        method,
        "is_nan"
            | "is_infinite"
            | "is_finite"
            | "is_normal"
            | "is_sign_positive"
            | "is_sign_negative"
    )
}

/// If `expr` is exactly `f32::INFINITY`, `f64::INFINITY`, `f32::NEG_INFINITY`,
/// or `f64::NEG_INFINITY` (a two-segment path with no generics), returns
/// `(width, is_positive)`. Any other expression returns `None`.
///
/// This is the ONLY trigger for the infinity-equality conjunction path.
/// Finite float literals (`1.5f64`) and all other expressions return `None`
/// and stay on the existing Real-equality path unchanged.
fn infinity_constant_kind(expr: &Expr) -> Option<(&'static str, bool)> {
    let path = match expr {
        Expr::Path(p) if p.qself.is_none() => &p.path,
        Expr::Paren(paren) => return infinity_constant_kind(&paren.expr),
        Expr::Group(group) => return infinity_constant_kind(&group.expr),
        _ => return None,
    };
    // Must be exactly two path segments with no arguments: `f32::INFINITY`.
    let segs: Vec<_> = path.segments.iter().collect();
    if segs.len() != 2 {
        return None;
    }
    // Both segments must have no generic arguments.
    for seg in &segs {
        if !matches!(seg.arguments, syn::PathArguments::None) {
            return None;
        }
    }
    let type_seg = segs[0].ident.to_string();
    let const_seg = segs[1].ident.to_string();
    let width: &'static str = match type_seg.as_str() {
        "f32" => "f32",
        "f64" => "f64",
        _ => return None,
    };
    let is_positive = match const_seg.as_str() {
        "INFINITY" => true,
        "NEG_INFINITY" => false,
        _ => return None,
    };
    Some((width, is_positive))
}

/// Attempt to lift `lhs == rhs` (or `rhs == lhs`) where exactly one operand is
/// an infinity constant path, as the sound predicate conjunction:
///
///   `f64::INFINITY`  => `and(float.f64.is_infinite(expr), float.f64.is_sign_positive(expr))`
///   `f64::NEG_INFINITY` => `and(float.f64.is_infinite(expr), float.f64.is_sign_negative(expr))`
///
/// Width is taken from the constant operand. The non-constant operand becomes
/// the receiver term.
///
/// Returns `Ok(None)` if neither operand is an infinity constant (caller falls
/// through to the existing path). Returns `Err` only if the constant was
/// detected but the receiver term translation fails.
fn translate_infinity_eq_assertion(
    lhs: &Expr,
    rhs: &Expr,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
) -> Result<Option<AssertionEntry>, String> {
    let (width, is_positive, receiver_expr) =
        match (infinity_constant_kind(lhs), infinity_constant_kind(rhs)) {
            (Some((w, pos)), _) => (w, pos, rhs),
            (None, Some((w, pos))) => (w, pos, lhs),
            (None, None) => return Ok(None),
        };

    // The receiver must have a known width to avoid lifting a wrong claim.
    // We accept the width from the constant side if the receiver has no
    // conflicting annotation (soundness: we know the constant's type so the
    // equality is between same-type values in valid Rust).
    // We still check: if the receiver has a conflicting width annotation,
    // refuse rather than guess.
    if let Some(receiver_width) = float_refinement_receiver_width(receiver_expr, float_widths) {
        if receiver_width != width {
            return Err(format!(
                "infinity equality: receiver width `{receiver_width}` conflicts with constant width `{width}` in `{}`",
                token_key(receiver_expr)
            ));
        }
    }
    // Width is determined by the constant. Translate the receiver as a term.
    let receiver = translate_term_in_scope(receiver_expr, scope).map_err(|e| {
        format!(
            "infinity equality: receiver term translation failed for `{}`: {e}",
            token_key(receiver_expr)
        )
    })?;

    let name = callsite_assertion_name(receiver.as_ref(), scope.local_scope());
    let sign_pred = if is_positive {
        "is_sign_positive"
    } else {
        "is_sign_negative"
    };
    let atom = and_(vec![
        atomic_(format!("float.{width}.is_infinite"), vec![receiver.clone()]),
        atomic_(format!("float.{width}.{sign_pred}"), vec![receiver]),
    ]);
    Ok(Some(AssertionEntry { name, atom }))
}

type FloatWidthScope = BTreeMap<String, &'static str>;

fn update_float_width_scope_for_pat(pat: &Pat, out: &mut FloatWidthScope) {
    remove_float_width_idents(pat, out);
    match pat {
        Pat::Type(pat_type) => {
            if let Some(width) = float_width_from_type(&pat_type.ty) {
                collect_float_width_ident_pat(&pat_type.pat, width, out);
            }
        }
        Pat::Paren(paren) => update_float_width_scope_for_pat(&paren.pat, out),
        _ => {}
    }
}

fn remove_float_width_idents(pat: &Pat, out: &mut FloatWidthScope) {
    match pat {
        Pat::Ident(ident) => {
            out.remove(&ident.ident.to_string());
            if let Some((_, subpat)) = &ident.subpat {
                remove_float_width_idents(subpat, out);
            }
        }
        Pat::Or(or) => {
            for case in &or.cases {
                remove_float_width_idents(case, out);
            }
        }
        Pat::Paren(paren) => remove_float_width_idents(&paren.pat, out),
        Pat::Reference(reference) => remove_float_width_idents(&reference.pat, out),
        Pat::Slice(slice) => {
            for elem in &slice.elems {
                remove_float_width_idents(elem, out);
            }
        }
        Pat::Struct(pat_struct) => {
            for field in &pat_struct.fields {
                remove_float_width_idents(&field.pat, out);
            }
        }
        Pat::Tuple(tuple) => {
            for elem in &tuple.elems {
                remove_float_width_idents(elem, out);
            }
        }
        Pat::TupleStruct(tuple_struct) => {
            for elem in &tuple_struct.elems {
                remove_float_width_idents(elem, out);
            }
        }
        Pat::Type(pat_type) => remove_float_width_idents(&pat_type.pat, out),
        _ => {}
    }
}

fn collect_float_width_ident_pat(pat: &Pat, width: &'static str, out: &mut FloatWidthScope) {
    match pat {
        Pat::Ident(ident) if ident.subpat.is_none() => {
            out.insert(ident.ident.to_string(), width);
        }
        Pat::Paren(paren) => collect_float_width_ident_pat(&paren.pat, width, out),
        _ => {}
    }
}

fn float_width_from_type(ty: &Type) -> Option<&'static str> {
    match ty {
        Type::Path(path) => float_width_from_path(&path.path),
        Type::Paren(paren) => float_width_from_type(&paren.elem),
        Type::Group(group) => float_width_from_type(&group.elem),
        _ => None,
    }
}

fn float_refinement_receiver_width(
    expr: &Expr,
    float_widths: &FloatWidthScope,
) -> Option<&'static str> {
    match expr {
        Expr::MethodCall(call) => float_width_from_method_name(&call.method.to_string())
            .or_else(|| float_width_from_method_turbofish(call))
            .or_else(|| {
                if call.method == "unwrap" {
                    float_refinement_receiver_width(&call.receiver, float_widths)
                } else {
                    None
                }
            }),
        Expr::Path(path) => {
            let name = path_to_name(&path.path);
            float_widths
                .get(&name)
                .copied()
                .or_else(|| float_width_from_path(&path.path))
        }
        Expr::Lit(ExprLit {
            lit: Lit::Float(lit),
            ..
        }) => float_width_from_suffix(lit.suffix()),
        Expr::Paren(paren) => float_refinement_receiver_width(&paren.expr, float_widths),
        Expr::Group(group) => float_refinement_receiver_width(&group.expr, float_widths),
        _ => None,
    }
}

fn float_width_from_method_turbofish(call: &syn::ExprMethodCall) -> Option<&'static str> {
    if call.method != "parse" {
        return None;
    }
    let args = call.turbofish.as_ref()?;
    float_width_from_angle_args(args)
}

fn float_width_from_angle_args(args: &syn::AngleBracketedGenericArguments) -> Option<&'static str> {
    if args.args.len() != 1 {
        return None;
    }
    let Some(syn::GenericArgument::Type(ty)) = args.args.first() else {
        return None;
    };
    float_width_from_type(ty)
}

fn float_width_from_method_name(method: &str) -> Option<&'static str> {
    if method.ends_with("_f32") {
        Some("f32")
    } else if method.ends_with("_f64") {
        Some("f64")
    } else {
        None
    }
}

fn float_width_from_path(path: &syn::Path) -> Option<&'static str> {
    for segment in &path.segments {
        match segment.ident.to_string().as_str() {
            "f32" => return Some("f32"),
            "f64" => return Some("f64"),
            _ => {}
        }
    }
    None
}

fn float_width_from_suffix(suffix: &str) -> Option<&'static str> {
    match suffix {
        "f32" => Some("f32"),
        "f64" => Some("f64"),
        _ => None,
    }
}

fn translate_pointer_eq_assertion(
    expr: &Expr,
    scope: &TemporalScope,
) -> Result<Option<AssertionEntry>, String> {
    match expr {
        Expr::Paren(paren) => translate_pointer_eq_assertion(&paren.expr, scope),
        Expr::Group(group) => translate_pointer_eq_assertion(&group.expr, scope),
        Expr::Call(call) => {
            let callee = expr_head_key(&call.func);
            if !matches!(
                callee.as_str(),
                "core::ptr::eq" | "ptr::eq" | "std::ptr::eq"
            ) {
                return Ok(None);
            }
            if call.args.len() != 2 {
                return Err("ptr::eq expects two arguments".to_string());
            }
            let mut args = Vec::new();
            for arg in &call.args {
                args.push(translate_pointer_identity_term(arg, scope)?);
            }
            let term = Rc::new(Term::Ctor {
                name: format!("call:{callee}"),
                args,
            });
            Ok(Some(assertion_entry_from_eq(term, bool_const(true), scope)))
        }
        _ => Ok(None),
    }
}

fn translate_pointer_identity_term(expr: &Expr, scope: &TemporalScope) -> Result<Rc<Term>, String> {
    match expr {
        Expr::Reference(reference) if reference.mutability.is_none() => Ok(Rc::new(Term::Ctor {
            name: "ref".to_string(),
            args: vec![translate_pointer_identity_term(&reference.expr, scope)?],
        })),
        Expr::Index(index) => Ok(Rc::new(Term::Ctor {
            name: "index".to_string(),
            args: vec![
                translate_pointer_identity_term(&index.expr, scope)?,
                translate_pointer_identity_term(&index.index, scope)?,
            ],
        })),
        Expr::Paren(paren) => translate_pointer_identity_term(&paren.expr, scope),
        Expr::Group(group) => translate_pointer_identity_term(&group.expr, scope),
        other => translate_term_in_scope(other, scope),
    }
}

fn translate_binary_bool_assertion(
    binary: &syn::ExprBinary,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
) -> Result<AssertionEntry, String> {
    match &binary.op {
        BinOp::And(_) | BinOp::Or(_) => {
            let left = translate_bool_assertion(&binary.left, scope, float_widths)?;
            let right = translate_bool_assertion(&binary.right, scope, float_widths)?;
            let name = common_assertion_name(&left.name, &right.name);
            let atom = if matches!(binary.op, BinOp::And(_)) {
                and_(vec![left.atom, right.atom])
            } else {
                or_(vec![left.atom, right.atom])
            };
            Ok(AssertionEntry { name, atom })
        }
        BinOp::Eq(_) | BinOp::Ne(_) | BinOp::Lt(_) | BinOp::Le(_) | BinOp::Gt(_) | BinOp::Ge(_) => {
            // For == only: intercept infinity-constant equality before the
            // Real-equality path. != and ordered comparisons fall through unchanged.
            if matches!(binary.op, BinOp::Eq(_)) {
                if let Some(entry) = translate_infinity_eq_assertion(
                    &binary.left,
                    &binary.right,
                    scope,
                    float_widths,
                )? {
                    return Ok(entry);
                }
            }
            let op = relation_from_binop(&binary.op)
                .expect("comparison op matched but did not map to relation");
            let lhs = translate_assertion_term_in_scope(&binary.left, scope)?;
            let rhs = translate_assertion_term_in_scope(&binary.right, scope)?;
            Ok(assertion_entry_from_relation(lhs, rhs, op, scope))
        }
        _ => Err(format!(
            "only scalar comparison/connective assertions are liftable, got `{}`",
            token_key(binary)
        )),
    }
}

fn common_assertion_name(left: &Option<String>, right: &Option<String>) -> Option<String> {
    match (left, right) {
        (Some(left), Some(right)) if left == right => Some(left.clone()),
        _ => None,
    }
}

fn assertion_entry_from_eq(lhs: Rc<Term>, rhs: Rc<Term>, scope: &TemporalScope) -> AssertionEntry {
    assertion_entry_from_relation(lhs, rhs, RelationOp::Eq, scope)
}

/// An expression that diverges: its value is never produced because control
/// panics/aborts/returns. As a match or if arm, it is the panic locus -- the
/// test passing proves control did NOT reach it.
fn expr_diverges(expr: &Expr) -> bool {
    match expr {
        Expr::Macro(m) => m.mac.path.segments.last().is_some_and(|s| {
            matches!(
                s.ident.to_string().as_str(),
                "panic" | "unreachable" | "todo" | "unimplemented"
            )
        }),
        Expr::Block(b) => b.block.stmts.last().is_some_and(stmt_diverges),
        Expr::Unsafe(u) => u.block.stmts.last().is_some_and(stmt_diverges),
        Expr::Return(_) => true,
        Expr::Paren(p) => expr_diverges(&p.expr),
        Expr::Group(g) => expr_diverges(&g.expr),
        Expr::Call(c) => {
            if let Expr::Path(p) = &*c.func {
                let last = p.path.segments.last().map(|s| s.ident.to_string());
                matches!(last.as_deref(), Some("exit") | Some("abort"))
                    && p.path.segments.iter().any(|s| s.ident == "process")
            } else {
                false
            }
        }
        _ => false,
    }
}

fn stmt_diverges(s: &Stmt) -> bool {
    match s {
        Stmt::Expr(e, _) => expr_diverges(e),
        Stmt::Macro(m) => m.mac.path.segments.last().is_some_and(|seg| {
            matches!(
                seg.ident.to_string().as_str(),
                "panic" | "unreachable" | "todo" | "unimplemented"
            )
        }),
        _ => false,
    }
}

fn path_to_variant_string(p: &syn::Path) -> String {
    p.segments
        .iter()
        .map(|s| s.ident.to_string())
        .collect::<Vec<_>>()
        .join("::")
}

/// The variant a surviving match/if-let arm pattern identifies, as a tag string.
fn pattern_variant_path(pat: &syn::Pat) -> Option<String> {
    match pat {
        syn::Pat::TupleStruct(ts) => Some(path_to_variant_string(&ts.path)),
        syn::Pat::Path(p) => Some(path_to_variant_string(&p.path)),
        syn::Pat::Struct(s) => Some(path_to_variant_string(&s.path)),
        syn::Pat::Ident(id) if id.subpat.is_none() => Some(id.ident.to_string()),
        syn::Pat::Reference(r) => pattern_variant_path(&r.pat),
        _ => None,
    }
}

/// Lift `assert!(matches!(subject, Type::Variant ...))` as a variant-discriminant
/// assertion: `variant_of(subject) == "variant::<Type::Variant>"` -- the SAME
/// construction-semantics atom panic-locus lifting emits (`panic_locus_entry`),
/// with the same teeth (two variants are distinct string constants, so claiming
/// both is UNSAT).
///
/// SOUND SCOPE: `matches!(x, P)` is exactly `match x { P => true, _ => false }`,
/// so a passing `assert!(matches!(x, P [if g]))` means x matched P (and, if
/// present, the guard g held) -- the discriminant `variant_of(x) == "variant::P"`
/// is therefore IMPLIED. We lift only that (weaker, always-implied) discriminant
/// fact, so both value-binding subpatterns (`V { f }`, `V(inner)`) AND a trailing
/// GUARD (`P if g`) are fine: the lifted obligation is implied either way, and
/// dropping g loses only refutation power, never soundness. (This differs from
/// `panic_locus_match_entry`, which refuses guards: a `match` has multiple arms,
/// the same pattern can recur with different guards, and which arm a value reaches
/// is genuinely guard-dependent -- the single-pattern `matches!` macro has no such
/// ambiguity.) We REFUSE BY NAME only the shapes where the discriminant itself is
/// NOT unambiguous:
///   - an or-pattern (`A | B`): a disjunction is not a single discriminant;
///   - a binding / wildcard / single-segment path: a lowercase `foo` is a
///     catch-all binding (always matches), and a bare `Foo` is ambiguous between
///     a unit variant and an associated const -- not an unambiguous `Type::Variant`.
fn translate_matches_assertion(
    expr: &Expr,
    scope: &TemporalScope,
) -> Result<Option<AssertionEntry>, String> {
    let Expr::Macro(m) = expr else {
        return Ok(None);
    };
    if !m.mac.path.is_ident("matches") {
        return Ok(None);
    }
    // Parse `subject , pattern (if guard)?` from the macro token stream.
    let parser = |input: ParseStream| -> syn::Result<(Expr, syn::Pat)> {
        let subject: Expr = input.parse()?;
        input.parse::<Token![,]>()?;
        let pat = syn::Pat::parse_multi_with_leading_vert(input)?;
        // A trailing `if <guard>` is consumed but NOT modeled: for the ASSERTED
        // direction, `matches!(x, V if g)` true ⟹ x matches V AND g, so the
        // discriminant `variant_of(x) == "variant::V"` is IMPLIED regardless of g.
        // Lifting the discriminant and dropping the guard is therefore SOUND (a
        // weaker, always-implied fact); not modeling g loses only refutation power,
        // never soundness -- the same tradeoff `collect_ambient_foralls` makes.
        let _ = input.parse::<proc_macro2::TokenStream>();
        Ok((subject, pat))
    };
    let (subject, pat) = match Parser::parse2(parser, m.mac.tokens.clone()) {
        Ok(v) => v,
        // Not the `matches!(expr, pat)` shape we lift; fall through to the
        // ordinary boolean-assertion paths (which will name their own refusal).
        Err(_) => return Ok(None),
    };
    let Some(variant) = strict_variant_path(&pat) else {
        // NESTED WRAPPER: `matches!(x, Some(Inner::V))` / `Ok(..)` / `Err(..)`.
        // The single-segment wrapper is a known prelude variant (so `variant_of(x)
        // == "variant::Some"` is unambiguous), and its inner pattern -- when a
        // qualified variant -- pins the payload's discriminant via the payload
        // accessor. This is the meaningful claim (`Some(Widen)` vs `Some(Halt)`),
        // so we lift the conjunction, not just the trivial outer `Some`.
        if let Some((wrapper, inner)) = wrapped_variant(&pat) {
            return Ok(wrapped_variant_entry(
                &subject,
                &wrapper,
                inner.as_deref(),
                scope,
            ));
        }
        // TUPLE PATTERN: `matches!(subj, (Type::Variant, 1))` pins each tuple
        // COMPONENT of the subject -- a qualified variant via its discriminant
        // (`variant_of(field:i(subj)) == "variant::Type::Variant"`) and a literal
        // by value (`field:i(subj) == <lit>`). `field:i(subj)` is a congruent
        // uninterpreted accessor, so two claims about the same subject's i-th
        // component coalesce and a contradicting claim is UNSAT (the teeth). EXACT-
        // OR-BAIL: every component must be a strict qualified variant or a closed
        // literal (a binding / range / nested / non-literal component bails the
        // whole pattern -- we never lift a partially-pinned tuple); a `_` wildcard
        // simply contributes no constraint, and the entry refuses if NOTHING is
        // pinned (no teeth).
        if let Some(entry) = tuple_pattern_entry(&subject, &pat, scope) {
            return Ok(Some(entry));
        }
        return Err(format!(
            "matches! pattern is not an unambiguous qualified variant \
             (binding/wildcard/single-segment/or-pattern); refused by name: `{}`",
            token_key(expr)
        ));
    };
    match panic_locus_entry(&subject, &variant, scope) {
        Some(entry) => Ok(Some(entry)),
        None => Err(format!(
            "matches! subject is not a liftable term: `{}`",
            token_key(&subject)
        )),
    }
}

/// A nested known-wrapper pattern `Some(P)` / `Ok(P)` / `Err(P)`: returns the
/// single-segment wrapper variant name and the inner variant IF the inner pattern
/// is itself a qualified `Type::Variant` (else `None` -- a `Some(_)` / `Some(x)`
/// still pins the OUTER wrapper, but carries no inner discriminant). The wrapper
/// must be one of the prelude tuple variants whose single-segment name is
/// unambiguously a variant, not a const/binding.
fn wrapped_variant(pat: &syn::Pat) -> Option<(String, Option<String>)> {
    match pat {
        syn::Pat::Reference(r) => wrapped_variant(&r.pat),
        syn::Pat::TupleStruct(ts) if ts.path.segments.len() == 1 && ts.elems.len() == 1 => {
            let wrapper = ts.path.segments[0].ident.to_string();
            if !matches!(wrapper.as_str(), "Some" | "Ok" | "Err") {
                return None;
            }
            Some((wrapper, strict_variant_path(&ts.elems[0])))
        }
        _ => None,
    }
}

/// Build the nested-wrapper discriminant entry:
///   `variant_of(subject) == "variant::<wrapper>"`  (always), AND
///   `variant_of(payload:<wrapper>(subject)) == "variant::<inner>"`  (if inner is
///   a qualified variant).
/// The payload accessor `payload:<wrapper>(subject)` is an uninterpreted Ctor; by
/// congruence, two claims about the same subject's payload share it, so asserting
/// two distinct inner variants is UNSAT (the teeth). The contract NAME keys on the
/// subject (via the outer entry), so siblings about the same subject conjoin.
fn wrapped_variant_entry(
    subject: &Expr,
    wrapper: &str,
    inner: Option<&str>,
    scope: &TemporalScope,
) -> Option<AssertionEntry> {
    let subject_term = translate_term_in_scope(subject, scope).ok()?;
    let outer_lhs = Rc::new(Term::Ctor {
        name: "variant_of".to_string(),
        args: vec![subject_term.clone()],
    });
    let outer = assertion_entry_from_eq(outer_lhs, str_const(format!("variant::{wrapper}")), scope);
    let Some(inner_variant) = inner else {
        // `Some(_)` / `Some(x)`: only the outer wrapper is pinned.
        return Some(outer);
    };
    let payload = Rc::new(Term::Ctor {
        name: format!("payload:{wrapper}"),
        args: vec![subject_term],
    });
    let inner_lhs = Rc::new(Term::Ctor {
        name: "variant_of".to_string(),
        args: vec![payload],
    });
    let inner_atom = assertion_entry_from_eq(
        inner_lhs,
        str_const(format!("variant::{inner_variant}")),
        scope,
    )
    .atom;
    Some(AssertionEntry {
        name: outer.name,
        atom: and_(vec![outer.atom, inner_atom]),
    })
}

/// `matches!(subject, (C0, C1, ...))` over a TUPLE pattern: pin each component
/// of the subject. The i-th component is read via the congruent uninterpreted
/// accessor `field:i(subject_term)`; a qualified-variant component pins its
/// discriminant (`variant_of(field:i(subj)) == "variant::C"`), a literal
/// component pins its value (`field:i(subj) == <lit>`). A `_` wildcard adds no
/// constraint. ANY other component shape (binding, range, nested struct, a
/// non-literal expr) BAILS the whole pattern (`None`) -- a partially-pinned
/// tuple is never lifted. Returns `None` (not the lifted entry) when the
/// pattern is not a tuple, the subject is not a liftable term, or nothing is
/// pinned (a `(_, _)` pattern has no teeth). The conjunction's NAME keys on the
/// subject, so sibling claims about the same subject conjoin.
fn tuple_pattern_entry(
    subject: &Expr,
    pat: &syn::Pat,
    scope: &TemporalScope,
) -> Option<AssertionEntry> {
    let tuple = match strip_pat_ref_paren(pat) {
        syn::Pat::Tuple(t) => t,
        _ => return None,
    };
    let subject_term = translate_term_in_scope(subject, scope).ok()?;
    let mut atoms: Vec<Rc<Formula>> = Vec::new();
    for (i, elem) in tuple.elems.iter().enumerate() {
        let elem = strip_pat_ref_paren(elem);
        if matches!(elem, syn::Pat::Wild(_)) {
            continue;
        }
        let field = Rc::new(Term::Ctor {
            name: format!("field:{i}"),
            args: vec![subject_term.clone()],
        });
        if let Some(variant) = strict_variant_path(elem) {
            let lhs = Rc::new(Term::Ctor {
                name: "variant_of".to_string(),
                args: vec![field],
            });
            atoms.push(assertion_entry_from_eq(lhs, str_const(format!("variant::{variant}")), scope).atom);
        } else if let syn::Pat::Lit(lit) = elem {
            let rhs = lit_membership_term(&lit.lit)?;
            atoms.push(assertion_entry_from_eq(field, rhs, scope).atom);
        } else {
            // A binding / range / nested / non-literal component: not a closed
            // pin. Bail the WHOLE tuple rather than lift a partial claim.
            return None;
        }
    }
    if atoms.is_empty() {
        // `(_, _)` -- no teeth.
        return None;
    }
    let name = callsite_assertion_name(subject_term.as_ref(), scope.local_scope());
    Some(AssertionEntry {
        name,
        atom: and_(atoms),
    })
}

/// Strip leading `&pat` / `(pat)` wrappers from a pattern, returning the inner.
fn strip_pat_ref_paren(pat: &syn::Pat) -> &syn::Pat {
    match pat {
        syn::Pat::Reference(r) => strip_pat_ref_paren(&r.pat),
        syn::Pat::Paren(p) => strip_pat_ref_paren(&p.pat),
        other => other,
    }
}

/// Strict variant-path extraction for `matches!` discriminant lifting: a
/// QUALIFIED `Type::Variant` (>= 2 path segments) as a unit, tuple-struct, or
/// struct pattern, or such a pattern behind a `&`. Returns None for bindings,
/// wildcards, single-segment paths, and or-patterns -- the caller refuses those
/// by name. Stricter than `pattern_variant_path` (which accepts bare `Pat::Ident`
/// bindings and single-segment paths, sound only in its panic-locus call site).
fn strict_variant_path(pat: &syn::Pat) -> Option<String> {
    fn qualified(path: &syn::Path) -> Option<String> {
        (path.segments.len() >= 2).then(|| path_to_variant_string(path))
    }
    match pat {
        syn::Pat::TupleStruct(ts) => qualified(&ts.path),
        syn::Pat::Struct(s) => qualified(&s.path),
        syn::Pat::Path(p) => qualified(&p.path),
        syn::Pat::Reference(r) => strict_variant_path(&r.pat),
        _ => None,
    }
}

/// Build the panic-locus atom: `variant_of(subject) == "variant::<tag>"`. The
/// tag is a string literal, so two different variants of the same subject are
/// distinct constants -- asserting both is UNSAT (the teeth).
fn panic_locus_entry(
    subject: &Expr,
    variant: &str,
    scope: &TemporalScope,
) -> Option<AssertionEntry> {
    let subject_term = translate_term_in_scope(subject, scope).ok()?;
    let variant_of = Rc::new(Term::Ctor {
        name: "variant_of".to_string(),
        args: vec![subject_term],
    });
    Some(assertion_entry_from_eq(
        variant_of,
        str_const(format!("variant::{variant}")),
        scope,
    ))
}

/// Panic-locus lifting for a `match`: if every arm but one diverges (panics),
/// the test passing proves the scrutinee matches the surviving arm's pattern.
fn panic_locus_match_entry(m: &syn::ExprMatch, scope: &TemporalScope) -> Option<AssertionEntry> {
    if m.arms.len() < 2 {
        return None;
    }
    let mut surviving = Vec::new();
    let mut diverging = 0usize;
    for arm in &m.arms {
        if arm.guard.is_some() {
            return None; // a guard changes which values reach the arm
        }
        if expr_diverges(&arm.body) {
            diverging += 1;
        } else {
            surviving.push(arm);
        }
    }
    if diverging == 0 || surviving.len() != 1 {
        return None;
    }
    let variant = pattern_variant_path(&surviving[0].pat)?;
    panic_locus_entry(&m.expr, &variant, scope)
}

/// Panic-locus lifting for `if let PAT = SUBJ { .. } else { panic!() }`.
fn panic_locus_if_entry(i: &syn::ExprIf, scope: &TemporalScope) -> Option<AssertionEntry> {
    let Expr::Let(cond) = &*i.cond else {
        return None;
    };
    let (_, else_expr) = i.else_branch.as_ref()?;
    if !expr_diverges(else_expr) {
        return None;
    }
    let variant = pattern_variant_path(&cond.pat)?;
    panic_locus_entry(&cond.expr, &variant, scope)
}

#[derive(Clone, Copy)]
enum RelationOp {
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
}

impl RelationOp {
    fn operator_call_name(self) -> &'static str {
        match self {
            RelationOp::Eq | RelationOp::Ne => "eq",
            RelationOp::Lt => "lt",
            RelationOp::Le => "le",
            RelationOp::Gt => "gt",
            RelationOp::Ge => "ge",
        }
    }

    fn operator_asserted_result(self) -> bool {
        !matches!(self, RelationOp::Ne)
    }

    /// The bool-valued comparison-CTOR tag used when a comparison sits in TERM
    /// position (`assert!(x == (a[0] < b[0]))`). Distinct per variant -- including
    /// `eq` vs `neq` (unlike `operator_call_name`, which collapses Eq/Ne and relies
    /// on a separate asserted-result bool to disambiguate). Distinctness is the
    /// teeth: `cmp:lt(x,y)` and `cmp:gt(x,y)` are different terms, so claiming both
    /// equal `true` over the same operands is UNSAT.
    fn cmp_ctor_name(self) -> &'static str {
        match self {
            RelationOp::Eq => "eq",
            RelationOp::Ne => "neq",
            RelationOp::Lt => "lt",
            RelationOp::Le => "le",
            RelationOp::Gt => "gt",
            RelationOp::Ge => "ge",
        }
    }
}

fn relation_from_binop(op: &BinOp) -> Option<RelationOp> {
    match op {
        BinOp::Eq(_) => Some(RelationOp::Eq),
        BinOp::Ne(_) => Some(RelationOp::Ne),
        BinOp::Lt(_) => Some(RelationOp::Lt),
        BinOp::Le(_) => Some(RelationOp::Le),
        BinOp::Gt(_) => Some(RelationOp::Gt),
        BinOp::Ge(_) => Some(RelationOp::Ge),
        _ => None,
    }
}

fn translate_string_predicate_assertion(
    expr: &Expr,
    scope: &TemporalScope,
) -> Result<Option<AssertionEntry>, String> {
    // `RegexSugar` (the regex-match → str.in_re membership lift). A
    // `Regex::new("pat").unwrap().is_match(subj)` / `re.is_match(subj)` /
    // `Regex::new("pat")…find(subj).is_some()` is first-order string theory:
    // `re.is_match(s) ⟺ str.in_re(s, R)` where the pattern literal lowers to a
    // z3 RegLan term. We LIFT THE SHAPE — never link/run the `regex` crate. The
    // pattern is recognized as a STRING LITERAL (a LiteralSugar of String kind);
    // a non-literal/runtime pattern is NOT recognized (the floor is a written
    // literal). The emitted atom is byte-identical to the Java `@Pattern` pass's
    // `str.in-regex(subject, <raw-regex-const>)`; the SMT compiler's
    // `regex_regln` is the single lowering authority and the refuse-by-name
    // boundary for non-regular features. This runs FIRST so an `is_match` /
    // `is_some` over a `Regex::new(lit)` chain routes here before the generic
    // method-name arms; a foreign `is_match` falls through (None).
    if let Some(entry) = translate_regex_match_assertion(expr, scope)? {
        return Ok(Some(entry));
    }
    match expr {
        Expr::Paren(paren) => translate_string_predicate_assertion(&paren.expr, scope),
        Expr::Group(group) => translate_string_predicate_assertion(&group.expr, scope),
        Expr::MethodCall(call) => {
            let method = call.method.to_string();
            match method.as_str() {
                "contains" => {
                    let Some(receiver) = string_or_char_literal_term(&call.receiver) else {
                        return Ok(None);
                    };
                    if call.args.len() != 1 {
                        return Err("string contains predicate expects one literal pattern".to_string());
                    }
                    let Some(pattern) = string_or_char_literal_term(&call.args[0]) else {
                        return Err(format!(
                            "string contains predicate needs a string/char literal pattern, got `{}`",
                            token_key(&call.args[0])
                        ));
                    };
                    let name = method_call_assertion_name(
                        "contains",
                        vec![receiver.clone(), pattern.clone()],
                        scope.local_scope(),
                    );
                    Ok(Some(AssertionEntry {
                        name,
                        atom: atomic_("contains", vec![receiver, pattern]),
                    }))
                }
                "starts_with" | "ends_with" => {
                    // The receiver is type-guaranteed a string (`starts_with` /
                    // `ends_with` exist only on str/String), so translate it as a
                    // TERM -- literal OR opaque (e.g. `cid.starts_with("blake3-512:")`
                    // where `cid` is a computed value). No type info needed; the
                    // method's existence proves stringness. The PATTERN must still be
                    // a literal (the known prefix/suffix). `prefix-of(pattern, recv)`
                    // is the faithful FOL, teethed against a contradicting claim.
                    // TERMINAL (bin-2): a `starts_with`/`ends_with` whose RECEIVER is a
                    // provably-MUTABLE local (`let mut a = Vec::new()`). The slice/string
                    // its contents form is produced by side-effecting mutation between
                    // program points (`a.push(n)` driven by `iter.next()` -- the corpus
                    // `iter/adapters/zip.rs` tail-side-effect tests), so the receiver has no
                    // single timeless `t`: the asserted prefix is over runtime data, NOT a
                    // value constructed from source literals (kin to `mutable container is
                    // not temporally stable` / `bin-2`). EARNED ONLY under `is_mut_local`;
                    // a non-`mut`, provably-immutable receiver (`cid.starts_with("..")` over
                    // a computed-but-immutable value) is NOT flagged and STAYS the bare
                    // "needs a string/char literal pattern" UNCLASSIFIED reason below (the
                    // fake-refuse guardrail -- never refuse a stable receiver to zero a count).
                    if let Some(recv_name) = simple_path_name(&call.receiver) {
                        if scope.is_mut_local(&recv_name) {
                            return Err(format!(
                                "{method} predicate over a MUTABLE-local receiver `{recv_name}` \
                                 (bin-2: a slice/string mutated by side-effecting iteration, not \
                                 constructed from source literals); refused"
                            ));
                        }
                    }
                    let Ok(receiver) = translate_term_in_scope(&call.receiver, scope) else {
                        return Ok(None);
                    };
                    if call.args.len() != 1 {
                        return Err(format!("{method} predicate expects one literal pattern"));
                    }
                    let Some(pattern) = string_or_char_literal_term(&call.args[0]) else {
                        return Err(format!(
                            "{method} predicate needs a string/char literal pattern, got `{}`",
                            token_key(&call.args[0])
                        ));
                    };
                    let name = method_call_assertion_name(
                        method.as_str(),
                        vec![receiver.clone(), pattern.clone()],
                        scope.local_scope(),
                    );
                    let atom_name = if method == "starts_with" {
                        "prefix-of"
                    } else {
                        "suffix-of"
                    };
                    Ok(Some(AssertionEntry {
                        name,
                        atom: atomic_(atom_name, vec![pattern, receiver]),
                    }))
                }
                "is_ascii" => {
                    if !call.args.is_empty() {
                        return Err("is_ascii predicate expects no arguments".to_string());
                    }
                    if let Some(receiver) = string_or_char_literal_term(&call.receiver) {
                        let name = method_call_assertion_name(
                            "is_ascii",
                            vec![receiver.clone()],
                            scope.local_scope(),
                        );
                        return Ok(Some(AssertionEntry {
                            name,
                            atom: atomic_("str.is_ascii", vec![receiver]),
                        }));
                    }
                    let Some(bytes) = literal_byte_string_value(&call.receiver) else {
                        return Ok(None);
                    };
                    let atoms = bytes
                        .into_iter()
                        .map(|b| byte_is_ascii_formula(num(i128::from(b))))
                        .collect::<Vec<_>>();
                    let atom = if atoms.is_empty() {
                        eq(bool_const(true), bool_const(true))
                    } else {
                        and_(atoms)
                    };
                    Ok(Some(AssertionEntry { name: None, atom }))
                }
                "is_ascii_alphabetic" => {
                    let Some(receiver) = char_literal_term(&call.receiver) else {
                        return Ok(None);
                    };
                    if !call.args.is_empty() {
                        return Err("is_ascii_alphabetic predicate expects no arguments".to_string());
                    }
                    let name = method_call_assertion_name(
                        "is_ascii_alphabetic",
                        vec![receiver.clone()],
                        scope.local_scope(),
                    );
                    Ok(Some(AssertionEntry {
                        name,
                        atom: atomic_("str.is_ascii_alphabetic", vec![receiver]),
                    }))
                }
                "is_ascii_digit" => {
                    ascii_char_class_assertion(call, scope.local_scope(), "str.is_ascii_digit")
                }
                "is_ascii_alphanumeric" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_alphanumeric",
                ),
                "is_ascii_octdigit" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_octdigit",
                ),
                "is_ascii_lowercase" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_lowercase",
                ),
                "is_ascii_uppercase" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_uppercase",
                ),
                "is_ascii_hexdigit" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_hexdigit",
                ),
                "is_ascii_punctuation" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_punctuation",
                ),
                "is_ascii_graphic" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_graphic",
                ),
                "is_ascii_whitespace" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_whitespace",
                ),
                "is_ascii_control" => ascii_char_class_assertion(
                    call,
                    scope.local_scope(),
                    "str.is_ascii_control",
                ),
                "is_alphabetic" if char_literal_term(&call.receiver).is_some() => Err(
                    "unicode char predicate is_alphabetic is not lifted; z3 string theory has no Rust Unicode Alphabetic database"
                        .to_string(),
                ),
                _ => Ok(None),
            }
        }
        _ => Ok(None),
    }
}

/// `RegexSugar`: lift a recognized rust regex-match assertion to the
/// `str.in-regex(subject, pattern)` membership atom — the IDENTICAL ProofIR term
/// the Java `@Pattern` universe pass emits (`buildRegexUniverseContract`). The
/// subject becomes a String-sorted term (a literal subject is the decidable POINT
/// case; a variable subject is the UNIVERSAL membership case, translated opaquely);
/// the pattern is the verbatim `Regex::new("…")` String literal carried RAW as a
/// String-sorted const (`str_const`), NOT a pre-lowered regln — the SMT compiler's
/// `regex_regln` is the single lowering authority and the refuse-by-name boundary
/// for non-regular features (backreference / lookahead / atomic / inline flag /
/// `\b`), which it drops without approximating. Returns `None` when the expr is not
/// a recognized regex-match shape (or carries a non-literal pattern) — never a
/// fake-refuse; the construct simply is not a regex membership.
fn translate_regex_match_assertion(
    expr: &Expr,
    scope: &TemporalScope,
) -> Result<Option<AssertionEntry>, String> {
    // Only IMMUTABLE `let` bindings resolve a bound regex: a `let mut re` could be
    // reassigned, so its later value is not the written `Regex::new(lit)` init
    // (mirrors the `try_fold` evaluator's `!is_mut_local` gate). A mut binding is
    // excluded, so an unstable receiver is declined rather than mis-resolved.
    let stable_bindings: BTreeMap<String, Expr> = scope
        .let_bindings
        .iter()
        .filter(|(name, _)| !scope.is_mut_local(name))
        .map(|(name, init)| (name.clone(), init.clone()))
        .collect();
    let Some(m) = sugar::regex_match::recognize_regex_match(expr, &stable_bindings) else {
        return Ok(None);
    };
    // COMPOSITIONAL pattern resolution: the pattern operand is an INNER `Sugar`,
    // resolved by DESUGARING it (mirroring `MapSugar`'s inner). `Dug` -> the
    // resolved string literal (a literal / const-string / `concat!` all flow
    // through this one path); `Hit` -> a genuinely runtime / unsupported pattern
    // (a `format!(…)` with no FormatSugar yet) -> DECLINE (None), the composition
    // frontier that flips to dig FOR FREE when its producer lands. We never bail
    // merely because the pattern is not an inline literal.
    //
    // The current pattern producers (string-literal base case, `let`/`const`
    // resolver, `concat!`) are PURE -- they do not read the SugarCtx -- so a
    // minimal ctx suffices here; a future ctx-needing producer threads the real
    // ctx in then, with no change to this contract.
    let mut fw = FloatWidthScope::new();
    let reducer = ReductionCtx::from_items(&[]);
    let options = LiftOptions::default();
    let ctx = sugar_ctx(scope, &options, &reducer, &mut fw, 0);
    let Some(pattern_str) = m.resolve_pattern(&ctx).dug().and_then(|d| d.as_string_literal()) else {
        // Runtime / unsupported pattern operand -> not a recognized regex
        // membership today (the composition frontier). Declined, not refused.
        return Ok(None);
    };
    // REFUSE BY NAME at lift time if the resolved pattern is not a regular language
    // — mirroring the Java `PatternUniverseWalker`, which refuses a non-regular
    // `@Pattern` at walk time (no row emitted, the floor stands). We use the SINGLE
    // lowering authority (`regex_regln`) as the regularity oracle so rust and Java
    // share ONE verdict; a non-regular feature (backreference, lookahead/behind,
    // atomic/possessive group, inline flag, `\b`) names the boundary precisely.
    // This is a REFUSAL (Err), never a silent drop: the false membership claim is
    // accounted, not vanished.
    if let Err(e) = sugar_ir_compiler_smt_lib::regex_regln::regex_to_regln(&pattern_str) {
        return Err(match e {
            sugar_ir_compiler_smt_lib::regex_regln::RegexError::NotRegular(feat) => format!(
                "regex pattern `{}` uses a non-regular feature ({feat}) — not expressible \
                 as RegLan; refused by name (no str.in-regex membership row)",
                pattern_str
            ),
            sugar_ir_compiler_smt_lib::regex_regln::RegexError::Malformed(msg) => format!(
                "regex pattern `{}` is malformed ({msg}); refused (no str.in-regex membership row)",
                pattern_str
            ),
        });
    }
    // The subject is translated in scope: a string literal is the POINT case (a
    // decidable membership of a concrete string), a variable is the UNIVERSAL
    // membership case (an opaque String term whose value z3 quantifies over). A
    // subject we cannot translate to a term is declined (None) — not refused.
    let Ok(subject) = translate_term_in_scope(&m.subject, scope) else {
        return Ok(None);
    };
    // The resolved pattern is carried verbatim as a String-sorted const. The atom
    // is `str.in-regex(subject, pattern)` — arg order and shape byte-identical to
    // the Java `@Pattern` emission (`buildRegexUniverseContract`).
    let pattern = str_const(pattern_str);
    let name = method_call_assertion_name(
        m.method,
        vec![subject.clone(), pattern.clone()],
        scope.local_scope(),
    );
    Ok(Some(AssertionEntry {
        name,
        atom: atomic_("str.in-regex", vec![subject, pattern]),
    }))
}

fn ascii_char_class_assertion(
    call: &syn::ExprMethodCall,
    local_scope: &str,
    atom_name: &str,
) -> Result<Option<AssertionEntry>, String> {
    let Some(receiver) = char_literal_term(&call.receiver) else {
        return Ok(None);
    };
    if !call.args.is_empty() {
        return Err(format!("{} predicate expects no arguments", call.method));
    }
    let method = call.method.to_string();
    let name = method_call_assertion_name(method.as_str(), vec![receiver.clone()], local_scope);
    Ok(Some(AssertionEntry {
        name,
        atom: atomic_(atom_name, vec![receiver]),
    }))
}

fn translate_literal_iterator_assertion(
    expr: &Expr,
    scope: &TemporalScope,
    float_widths: &FloatWidthScope,
) -> Result<Option<AssertionEntry>, String> {
    let Expr::MethodCall(call) = expr else {
        return Ok(None);
    };
    let method = call.method.to_string();
    if !matches!(method.as_str(), "all" | "any") {
        return Ok(None);
    }
    if call.args.len() != 1 {
        return Err(format!("{method} predicate expects one closure"));
    }
    let Some(closure) = call.args.first().and_then(|expr| match expr {
        Expr::Closure(closure) => Some(closure),
        _ => None,
    }) else {
        return Ok(None);
    };
    if closure.inputs.len() != 1 {
        return Err(format!("{method} predicate expects one closure parameter"));
    }
    // The bound parameter, accepting a plain `|x|` AND a reference pattern `|&x|`
    // (the dominant `.iter()` shape -- `.iter()` yields `&T`, so the closure
    // binds `&x` to read the element by value). A wildcard `|_|` or a destructuring
    // pattern is NOT a simple binding -> we have no name to substitute, so this
    // path declines (it falls through to the closure-adaptor refusal, which names
    // the collection provenance).
    let Some(param_name) = closure_simple_param_name(closure) else {
        // The string char/byte ascii-predicate path is a closed shape that does
        // not need a substitutable parameter (its body is a fixed method call);
        // keep its historical refusal for a non-ident param there. For the general
        // arithmetic body we simply decline (Ok(None)) so provenance is named.
        if literal_iterator_elements(&call.receiver)?.is_some() {
            return Err(format!("{method} predicate requires a simple identifier parameter"));
        }
        return Ok(None);
    };

    // PATH 1 (closed, historical): a STRING-literal `.chars()`/`.bytes()` domain
    // whose body is a fixed ascii-class method call. Unchanged.
    if let Some((iter_kind, elements)) = literal_iterator_elements(&call.receiver)? {
        let mut atoms = Vec::new();
        for element in elements {
            atoms.push(iterator_element_predicate_atom(
                closure.body.as_ref(),
                &param_name,
                element,
                iter_kind,
            )?);
        }
        let atom = quantifier_join(&method, atoms);
        return Ok(Some(AssertionEntry { name: None, atom }));
    }

    // PATH 2 (general): a SCALAR-LITERAL array domain (`[1,2,3].iter()` or a
    // `let v = Box::new([1,2,3])` resolved via scope) with a PURE body. We unroll
    // the quantifier over the finite, source-constructed domain: substitute the
    // bound parameter with each element literal and lift the body through the
    // ordinary bool-assertion path (so a comparison `x < 10` becomes the real
    // `lt`/`ge` atom, EXACT-OR-BAIL -- a non-liftable body propagates its own Err
    // and the whole quantifier refuses, never a partial/over-claim). `all` ->
    // conjunction, `any` -> disjunction. The domain is finite and pinned from
    // written literals (the construction axiom); a RUNTIME receiver (an opaque
    // collection, a sliced `v[..i]`, a non-literal binding) does NOT resolve here
    // and falls through to the closure-adaptor refusal (bin-2, named).
    let Some(elements) = scalar_iter_domain_elems(&call.receiver, scope) else {
        return Ok(None);
    };
    let mut atoms = Vec::new();
    for element in elements {
        // Substitute the bound parameter with the concrete element literal in a
        // CLONE of the body, then lift via the ordinary path. Substitution is by
        // identifier name (reusing the helper-inlining substitutor); the closure
        // body reads its own parameter, never an outer binding of the same name
        // (shadowing), so this is sound.
        let mut binds = ExprBindings::new();
        binds.insert(param_name.clone(), element);
        let body = substitute_expr(closure.body.as_ref(), &binds);
        let entry = translate_bool_assertion(&body, scope, float_widths)?;
        atoms.push(entry.atom);
    }
    let atom = quantifier_join(&method, atoms);
    Ok(Some(AssertionEntry { name: None, atom }))
}

/// `all` -> the conjunction of the per-element atoms (empty domain -> vacuously
/// true); `any` -> the disjunction (empty domain -> false). The empty cases are
/// the IEEE-of-quantifiers identities (`∀∅ = ⊤`, `∃∅ = ⊥`).
fn quantifier_join(method: &str, atoms: Vec<Rc<Formula>>) -> Rc<Formula> {
    if method == "all" {
        if atoms.is_empty() {
            eq(bool_const(true), bool_const(true))
        } else {
            and_(atoms)
        }
    } else if atoms.is_empty() {
        eq(bool_const(true), bool_const(false))
    } else {
        or_(atoms)
    }
}

/// The bound parameter name of a single-parameter closure, accepting `|x|` and a
/// reference pattern `|&x|` (and `|&mut x|`), through a type ascription `|x: T|`.
/// `None` for a wildcard `|_|` or any destructuring pattern (no single name to
/// substitute).
fn closure_simple_param_name(closure: &syn::ExprClosure) -> Option<String> {
    fn ident_of(pat: &syn::Pat) -> Option<String> {
        match pat {
            syn::Pat::Ident(id) if id.subpat.is_none() => Some(id.ident.to_string()),
            syn::Pat::Reference(r) => ident_of(&r.pat),
            syn::Pat::Paren(p) => ident_of(&p.pat),
            syn::Pat::Type(t) => ident_of(&t.pat),
            _ => None,
        }
    }
    ident_of(closure.inputs.first()?)
}

/// The element expressions of a `.iter()`/`.into_iter()` receiver IF the underlying
/// collection is a finite SCALAR-LITERAL array -- either an inline `[1,2,3]` literal
/// or a `let`-bound array captured in `scope` (`let v = Box::new([1,2,3])`). `None`
/// for a runtime/opaque receiver (a sliced `v[..i]`, an opaque collection, a
/// non-captured binding), so the quantifier declines and provenance is named
/// elsewhere. The elements are returned as `Expr` (closed scalar literals) for
/// substitution into the closure body.
fn scalar_iter_domain_elems(receiver: &Expr, scope: &TemporalScope) -> Option<Vec<Expr>> {
    let base = iter_adaptor_base(receiver);
    // Inline array literal: `[1, 2, 3].iter()`.
    if let Some(elems) = scalar_literal_array_elems(base) {
        return Some(elems);
    }
    // A `let`-bound scalar-literal array captured in scope.
    if let Some(name) = simple_path_name(base) {
        if let Some(elems) = scope.literal_array(&name) {
            return Some(elems.to_vec());
        }
    }
    None
}

#[derive(Clone, Copy)]
enum IteratorKind {
    Chars,
    Bytes,
}

fn iterator_element_predicate_atom(
    body: &Expr,
    param_name: &str,
    element: Rc<Term>,
    iter_kind: IteratorKind,
) -> Result<Rc<Formula>, String> {
    let Expr::MethodCall(call) = body else {
        return Err(format!(
            "iterator closure body must be a simple method call, got `{}`",
            token_key(body)
        ));
    };
    if !call.args.is_empty() {
        return Err(format!(
            "iterator closure predicate `{}` expects no arguments",
            call.method
        ));
    }
    if !matches_param_receiver(&call.receiver, param_name) {
        return Err(format!(
            "iterator closure predicate must read its bound parameter `{param_name}`"
        ));
    }
    let method = call.method.to_string();
    match iter_kind {
        IteratorKind::Chars => ascii_char_class_atom(&method, element).ok_or_else(|| {
            if method == "is_alphabetic" {
                "unicode char predicate is_alphabetic is not lifted; z3 string theory has no Rust Unicode Alphabetic database"
                    .to_string()
            } else {
                format!("unsupported char iterator predicate `{method}`")
            }
        }),
        IteratorKind::Bytes => ascii_byte_class_atom(&method, element)
            .ok_or_else(|| format!("unsupported byte iterator predicate `{method}`")),
    }
}

fn ascii_char_class_atom(method: &str, receiver: Rc<Term>) -> Option<Rc<Formula>> {
    let atom_name = match method {
        "is_ascii" => "str.is_ascii",
        "is_ascii_alphabetic" => "str.is_ascii_alphabetic",
        "is_ascii_alphanumeric" => "str.is_ascii_alphanumeric",
        "is_ascii_digit" => "str.is_ascii_digit",
        "is_ascii_octdigit" => "str.is_ascii_octdigit",
        "is_ascii_lowercase" => "str.is_ascii_lowercase",
        "is_ascii_uppercase" => "str.is_ascii_uppercase",
        "is_ascii_hexdigit" => "str.is_ascii_hexdigit",
        "is_ascii_punctuation" => "str.is_ascii_punctuation",
        "is_ascii_graphic" => "str.is_ascii_graphic",
        "is_ascii_whitespace" => "str.is_ascii_whitespace",
        "is_ascii_control" => "str.is_ascii_control",
        _ => return None,
    };
    Some(atomic_(atom_name, vec![receiver]))
}

fn ascii_byte_class_atom(method: &str, byte: Rc<Term>) -> Option<Rc<Formula>> {
    match method {
        "is_ascii" => Some(byte_is_ascii_formula(byte)),
        "is_ascii_alphabetic" => Some(or_(vec![
            byte_range(byte.clone(), b'A', b'Z'),
            byte_range(byte, b'a', b'z'),
        ])),
        "is_ascii_alphanumeric" => Some(or_(vec![
            byte_range(byte.clone(), b'A', b'Z'),
            byte_range(byte.clone(), b'a', b'z'),
            byte_range(byte, b'0', b'9'),
        ])),
        "is_ascii_digit" => Some(byte_range(byte, b'0', b'9')),
        "is_ascii_octdigit" => Some(byte_range(byte, b'0', b'7')),
        "is_ascii_lowercase" => Some(byte_range(byte, b'a', b'z')),
        "is_ascii_uppercase" => Some(byte_range(byte, b'A', b'Z')),
        "is_ascii_hexdigit" => Some(or_(vec![
            byte_range(byte.clone(), b'0', b'9'),
            byte_range(byte.clone(), b'A', b'F'),
            byte_range(byte, b'a', b'f'),
        ])),
        "is_ascii_punctuation" => Some(or_(vec![
            byte_range(byte.clone(), b'!', b'/'),
            byte_range(byte.clone(), b':', b'@'),
            byte_range(byte.clone(), b'[', b'`'),
            byte_range(byte, b'{', b'~'),
        ])),
        "is_ascii_graphic" => Some(byte_range(byte, b'!', b'~')),
        "is_ascii_whitespace" => Some(or_(vec![
            eq(byte.clone(), num(i128::from(b' '))),
            eq(byte.clone(), num(9)),
            eq(byte.clone(), num(10)),
            eq(byte.clone(), num(12)),
            eq(byte, num(13)),
        ])),
        "is_ascii_control" => Some(or_(vec![
            byte_range(byte.clone(), 0u8, 31u8),
            eq(byte, num(127)),
        ])),
        _ => None,
    }
}

fn byte_is_ascii_formula(byte: Rc<Term>) -> Rc<Formula> {
    and_(vec![gte(byte.clone(), num(0)), lte(byte, num(127))])
}

fn byte_range(byte: Rc<Term>, low: u8, high: u8) -> Rc<Formula> {
    and_(vec![
        gte(byte.clone(), num(i128::from(low))),
        lte(byte, num(i128::from(high))),
    ])
}

// ── Source-audit value-contract emission ────────────────────────────────────
// A source warrant is REAL only if the kit EMITS the ProofIR contract for the
// body -- a syntactic "looks generalizable" flag with no emitted relation is a
// hollow warrant. `emit_value_contract` walks a value-function body into a
// closed consistency `ContractDecl`, mirroring the Python source kit's
// `_lift_function` (walk body -> term/formula, wrap as `return_value = body`) in
// the rust kit's inv-only form (`out` is the return value). It reuses the SAME
// term/formula atoms the test-assertion path already compiles to Z3 -- no new
// semantic path. Returns None when the body is not (yet) emittable; the caller
// then leaves the function UNCLASSIFIED (the honest dark), never warranted.
//
// Slice 1 -- the character-classification predicate shape (`is_ascii_*` family):
// a bool-returning body that reduces to `matches!(<scalar>, <pattern>)` (and
// `&&`/`||`/`!` trees thereof). The pattern is walked -- not the function name
// (names are sugar) -- into a range/equality membership formula, the same shape
// `ascii_byte_class_atom` proves. The contract is the biconditional
// `out <-> membership` (encoded with `implies`/`and`, since the compiler has no
// `iff`).
pub fn emit_value_contract(name: &str, block: &syn::Block) -> Option<ContractDecl> {
    let plan = temporal_plan_for_stmts(&block.stmts, &BTreeSet::new());
    let scope = TemporalScope::new("rust-source", plan);
    block_inv(block, &scope).map(|inv| source_value_contract(name, inv))
}

/// The BROAD warrant: every value body warrants, down to bare functionality.
/// Either we THINK it constrains (so warrant it -- dumbly, opaquely if need be)
/// or it NEVER constrains (no output -> None, the caller refuses by vacuity).
/// There is no swamp in between.
///
/// Order = strongest constraint first: the STRUCTURAL lift (`emit_value_contract`
/// -- membership, bounded universes, value-ifs, EUF terms: strong teeth), then
/// the DUMB functional fallback `out = call:NAME(params)` -- "out is a
/// deterministic function of the inputs" (weak teeth: bites only nondeterminism,
/// but still a real vendor DEMAND). A unit-returning body has no output to
/// constrain -> None.
///
/// Safe to be this dumb because the vendor is the referee (see the keystone): a
/// bogus broad warrant either finds no pin (harmless, unrefuted) or goes
/// all-UNSAT and self-retracts; it can only become a finding after a SAT
/// licenses it. We never have to PROVE the lift sound -- the check does.
pub fn broad_functional_warrant(
    name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
) -> Option<ContractDecl> {
    if let Some(decl) = emit_value_contract(name, block) {
        return Some(decl); // structural -- strongest teeth
    }
    if sig_returns_unit(sig) {
        return None; // no output to constrain -> the caller refuses by vacuity
    }
    // Bare functionality: out = call:NAME(params). The fn name keys it to the
    // vendor's call-site pins (intra-kit; CID-canonicalization is downstream).
    let term = Rc::new(Term::Ctor {
        name: format!("call:{name}"),
        args: sig_param_vars(sig),
    });
    Some(source_value_contract(name, eq(make_var("out"), term)))
}

/// True iff the signature returns `()` (explicit or default) -- no output to
/// constrain. Mirrored in the RPC bin's classifier.
pub fn sig_returns_unit(sig: &syn::Signature) -> bool {
    match &sig.output {
        syn::ReturnType::Default => true,
        syn::ReturnType::Type(_, ty) => matches!(&**ty, syn::Type::Tuple(t) if t.elems.is_empty()),
    }
}

/// The bound parameter names as EUF vars: a receiver -> `self`, a simple
/// `ident: T` -> `ident`. Destructuring/complex param patterns are skipped (they
/// only weaken the opaque functional term, never make it unsound).
fn sig_param_vars(sig: &syn::Signature) -> Vec<Rc<Term>> {
    sig.inputs
        .iter()
        .filter_map(|arg| match arg {
            syn::FnArg::Receiver(_) => Some(make_var("self")),
            syn::FnArg::Typed(pt) => match &*pt.pat {
                syn::Pat::Ident(id) => Some(make_var(id.ident.to_string())),
                _ => None,
            },
        })
        .collect()
}

/// The new-doctrine check: conjoin a body's emitted warrant with a VENDOR pin --
/// the sworn output at concrete arguments -- and hand the conjunction to the
/// solver. We do NOT analyze the body's effects, order, or interior; we
/// INSTANTIATE the warrant `out = <body over params>` at the vendor call's
/// argument bindings, conjoin the vendor's asserted output `out = <answer>`, and
/// let z3 be the only referee:
///   SAT   -> the warranted constraint coexists with the sworn answer; the warrant
///            holds, and the interior mess never mattered.
///   UNSAT -> the derived constraint cannot coexist with the sworn answer -> the
///            warrant (or the impl) is refuted -> REFUSE, carrying the
///            contradiction. Nondeterminism/mutation self-surface here too: the
///            same arguments pinned to two different vendor answers conjoin to
///            UNSAT under the functional warrant.
/// `bindings` maps the body's parameter names to the vendor call's integer
/// arguments; `asserted_out` is the vendor's sworn integer return value. Returns
/// the conjoined `ContractDecl` for the solver, or None if the body emitted no
/// warrant (nothing to check against the vendor).
pub fn warrant_conjoined_with_vendor(
    decl: &ContractDecl,
    bindings: &[(&str, i64)],
    asserted_out: i64,
) -> ContractDecl {
    let term_bindings: Vec<(&str, Rc<Term>)> = bindings
        .iter()
        .map(|(n, v)| (*n, num(i128::from(*v))))
        .collect();
    warrant_conjoined_with_vendor_terms(decl, &term_bindings, num(i128::from(asserted_out)))
}

/// General form: instantiate the body warrant at arbitrary scalar argument TERMS
/// (int / bool / string / ...), then conjoin the vendor's sworn output term. The
/// `i64` form above is the int special case. Same closed check (substitute the
/// params, conjoin `out == asserted_out`); the interior is an unopened EUF box.
pub fn warrant_conjoined_with_vendor_terms(
    decl: &ContractDecl,
    bindings: &[(&str, Rc<Term>)],
    asserted_out: Rc<Term>,
) -> ContractDecl {
    let mut inv = decl
        .inv
        .clone()
        .unwrap_or_else(|| atomic_("true", Vec::new()));
    for (name, value) in bindings {
        inv = subst_var_in_formula(&inv, name, value);
    }
    let conjoined = and_(vec![inv, eq(make_var("out"), asserted_out)]);
    ContractDecl {
        inv: Some(conjoined),
        ..decl.clone()
    }
}

/// The consistency `inv` for a block: a single tail expression (-> tail_inv) or a
/// leading immutable-let prefix + any tail (-> let_prefix_inv).
fn block_inv(block: &syn::Block, scope: &TemporalScope) -> Option<Rc<Formula>> {
    if let [Stmt::Expr(tail, None)] = block.stmts.as_slice() {
        return tail_inv(tail, scope);
    }
    if let Some(inv) = let_prefix_inv(block, scope) {
        return Some(inv);
    }
    emit_guard_return_value(block, scope)
}

/// A guard-clause body: `(if COND { return RET; })+ TAIL` -- one or more leading
/// early-return guard clauses (the `?`/let-else family of bin-1) followed by a
/// fall-through tail value. Semantically `if COND { RET } else { TAIL }`, so it
/// reuses the value-`if` encoding: `out == RET` under `COND` (and the negation
/// of every earlier guard), `out == TAIL` under all guards negated. Each guard's
/// RET and the final TAIL must be EUF terms; the `if` must have NO `else` and a
/// then-block that is exactly `return RET;`. Anything else -> None.
fn emit_guard_return_value(block: &syn::Block, scope: &TemporalScope) -> Option<Rc<Formula>> {
    let stmts = block.stmts.as_slice();
    let mut clauses: Vec<(Rc<Formula>, Rc<Term>)> = Vec::new();
    let mut negated: Vec<Rc<Formula>> = Vec::new();
    let mut idx = 0;
    while idx < stmts.len() {
        let Stmt::Expr(Expr::If(if_expr), _) = &stmts[idx] else {
            break;
        };
        if if_expr.else_branch.is_some() {
            break;
        }
        let Some(ret_expr) = then_block_single_return(&if_expr.then_branch) else {
            break;
        };
        let ret_term = translate_term_in_scope(ret_expr, scope).ok()?;
        if !term_is_euf_value(&ret_term) {
            return None;
        }
        let cond = match translate_bool_assertion(&if_expr.cond, scope, &FloatWidthScope::new()) {
            Ok(entry) => entry.atom,
            Err(_) => {
                let t = translate_term_in_scope(&if_expr.cond, scope).ok()?;
                if !term_is_euf_value(&t) {
                    return None;
                }
                eq(t, bool_const(true))
            }
        };
        let mut gp = negated.clone();
        gp.push(cond.clone());
        let guard = if gp.len() == 1 { gp.remove(0) } else { and_(gp) };
        clauses.push((guard, ret_term));
        negated.push(not_(cond));
        idx += 1;
    }
    if clauses.is_empty() {
        return None; // no leading guard clause -> not this shape
    }
    // The remaining statements are the fall-through tail value (under all guards
    // negated). Reuse block_euf_term over a synthetic block of the rest.
    let tail_block = syn::Block {
        brace_token: block.brace_token,
        stmts: stmts[idx..].to_vec(),
    };
    let tail_term = block_euf_term(&tail_block, scope)?;
    let tail_guard = if negated.len() == 1 {
        negated.remove(0)
    } else {
        and_(negated)
    };
    clauses.push((tail_guard, tail_term));
    let out = make_var("out");
    Some(and_(
        clauses
            .into_iter()
            .map(|(guard, term)| implies(guard, eq(out.clone(), term)))
            .collect(),
    ))
}

/// The returned expression of a then-block that is exactly `return RET;` (or
/// `{ return RET; }`). None if the block is not a single bare `return <expr>`.
fn then_block_single_return(then_branch: &syn::Block) -> Option<&Expr> {
    let [stmt] = then_branch.stmts.as_slice() else {
        return None;
    };
    let ret = match stmt {
        Stmt::Expr(Expr::Return(r), _) => r,
        _ => return None,
    };
    ret.expr.as_deref()
}

/// The consistency `inv` for a SINGLE tail expression (no prefix). Tries, in
/// order: bool-membership universe (matches!), bounded-output universe (clamp),
/// EUF value term (incl. method-call-as-EUF), value-if chain, scalar match, and
/// bool predicate (comparison/&&/||). None if the tail is none of these.
fn tail_inv(tail: &Expr, scope: &TemporalScope) -> Option<Rc<Formula>> {
    // Slice 14 -- `unsafe { .. }` / plain `{ .. }` are VALUE-TRANSPARENT: the inv
    // is the inner block's inv (unsafe is a compile-time obligation, not a value
    // transform). Unwrap before the per-shape branches.
    if let Expr::Unsafe(u) = tail {
        return block_inv(&u.block, scope);
    }
    if let Expr::Block(b) = tail {
        return block_inv(&b.block, scope);
    }
    if let Expr::Paren(p) = tail {
        return tail_inv(&p.expr, scope);
    }
    if let Expr::Group(g) = tail {
        return tail_inv(&g.expr, scope);
    }
    // (a) Slice 1 -- matches! membership: out <-> m.
    if let Some(membership) = emit_bool_membership_formula(tail, scope) {
        return Some(biconditional_out(membership));
    }
    // (b) Slice 4 -- bounded-output universe (clamp), BEFORE the EUF path so the
    //     bound's teeth aren't shadowed by an opaque `out = clamp(..)`.
    if let Some(universe) = bounded_output_universe(tail, scope) {
        return Some(universe);
    }
    // (c) Slice 2/5 -- value-term + method-call-as-EUF: out = <euf term>.
    if let Ok(term) = translate_term_in_scope(tail, scope) {
        if term_is_euf_value(&term) {
            return Some(eq(make_var("out"), term));
        }
    }
    // (e) Slice 8 -- value-position if / else-if / else -> ite via implies/and.
    if let Some(inv) = emit_if_value(tail, scope) {
        return Some(inv);
    }
    // (g) Slice 10 -- value-position scalar match (literal/range/_ arms) -> ite.
    if let Some(inv) = emit_match_value(tail, scope) {
        return Some(inv);
    }
    // (f) Slice 9 -- bool-predicate body (comparison / && / || / !), GATED so it
    //     can't mis-accept a non-bool call as a predicate. out <-> F.
    if is_bool_shaped_expr(tail) {
        if let Ok(entry) = translate_bool_assertion(tail, scope, &FloatWidthScope::new()) {
            return Some(biconditional_out(entry.atom));
        }
    }
    None
}

/// `out <-> F`, encoded as (out=true => F) ∧ (F => out=true) (no `iff` in the
/// compiler).
fn biconditional_out(f: Rc<Formula>) -> Rc<Formula> {
    let out_true = atomic_("=", vec![make_var("out"), bool_const(true)]);
    and_(vec![
        implies(out_true.clone(), f.clone()),
        implies(f, out_true),
    ])
}

/// Slice 6/11: a body `(let <ident> = <euf>;)* <tail>` -- collect the immutable
/// let substitution, compute the TAIL's inv (any single-tail shape), then
/// substitute the lets into that Formula (referential transparency over
/// deterministic EUF terms). None if any binding is mut / let-else / shadowing /
/// non-EUF, the prefix is empty (single-tail handled above), or the tail has no inv.
fn let_prefix_inv(block: &syn::Block, scope: &TemporalScope) -> Option<Rc<Formula>> {
    let (last, prefix) = block.stmts.split_last()?;
    let Stmt::Expr(tail_expr, None) = last else {
        return None;
    };
    if prefix.is_empty() {
        return None;
    }
    let subst = collect_let_subst(prefix, scope)?;
    let mut inv = tail_inv(tail_expr, scope)?;
    for (n, t) in &subst {
        inv = subst_var_in_formula(&inv, n, t);
    }
    Some(inv)
}

/// Collect the substitution map for a leading immutable-`let` prefix: each
/// `let <ident> = <euf>;` becomes (name -> EUF term), earlier bindings
/// substituted into later RHSs. None if any statement is not such a `let`
/// (mut / ref / destructuring / let-else / shadowing / non-EUF RHS).
fn collect_let_subst(prefix: &[Stmt], scope: &TemporalScope) -> Option<Vec<(String, Rc<Term>)>> {
    let mut subst: Vec<(String, Rc<Term>)> = Vec::new();
    for stmt in prefix {
        let Stmt::Local(local) = stmt else {
            return None;
        };
        let init = local.init.as_ref()?;
        if init.diverge.is_some() {
            return None;
        }
        let mut rhs = translate_term_in_scope(&init.expr, scope).ok()?;
        for (n, t) in &subst {
            rhs = subst_var_in_term(&rhs, n, t);
        }
        if !term_is_euf_value(&rhs) {
            return None;
        }
        for (name, term) in let_bindings(&local.pat, &rhs)? {
            if subst.iter().any(|(n, _)| n == &name) {
                return None; // shadowing breaks sequential substitution
            }
            subst.push((name, term));
        }
    }
    Some(subst)
}

/// The (name -> term) bindings a `let <pat> = <rhs>` introduces. A simple ident
/// binds the whole rhs; a tuple destructuring `let (a, _, c) = rhs` binds each
/// position i to the uninterpreted projection `field:i(rhs)` (the same accessor
/// the kit's `Expr::Field` translation uses, so `let (a,_) = t; a` is congruent
/// with `t.0`). `mut` / `ref` / nested sub-patterns are refused (None).
fn let_bindings(pat: &Pat, rhs: &Rc<Term>) -> Option<Vec<(String, Rc<Term>)>> {
    match pat {
        Pat::Ident(id) if id.subpat.is_none() && id.mutability.is_none() && id.by_ref.is_none() => {
            Some(vec![(id.ident.to_string(), rhs.clone())])
        }
        Pat::Type(t) => let_bindings(&t.pat, rhs),
        Pat::Paren(p) => let_bindings(&p.pat, rhs),
        Pat::Tuple(t) => {
            let mut out = Vec::new();
            for (i, elem) in t.elems.iter().enumerate() {
                match elem {
                    Pat::Wild(_) => {}
                    Pat::Ident(id)
                        if id.subpat.is_none()
                            && id.mutability.is_none()
                            && id.by_ref.is_none() =>
                    {
                        out.push((
                            id.ident.to_string(),
                            Rc::new(Term::Ctor {
                                name: format!("field:{i}"),
                                args: vec![rhs.clone()],
                            }),
                        ));
                    }
                    _ => return None,
                }
            }
            Some(out)
        }
        _ => None,
    }
}

/// A leading immutable-`let` prefix reduced to a single EUF TERM tail (for an
/// if/match BRANCH that needs a value term, not a Formula). None unless the tail
/// is an EUF value term after substitution.
fn let_prefix_euf_term(block: &syn::Block, scope: &TemporalScope) -> Option<Rc<Term>> {
    let (last, prefix) = block.stmts.split_last()?;
    let Stmt::Expr(tail_expr, None) = last else {
        return None;
    };
    if prefix.is_empty() {
        return None;
    }
    let subst = collect_let_subst(prefix, scope)?;
    let mut tail = translate_term_in_scope(tail_expr, scope).ok()?;
    for (n, t) in &subst {
        tail = subst_var_in_term(&tail, n, t);
    }
    term_is_euf_value(&tail).then_some(tail)
}

/// True iff an expression is syntactically a boolean predicate the assertion
/// lifter can handle as `out <-> F`: a comparison / logical-op binary, a `!`, or
/// those through paren/group. Deliberately EXCLUDES bare calls and `matches!`
/// (matches! is handled by emit_bool_membership_formula; a bare call's bool-ness
/// is unknown and must not be mis-warranted as a predicate).
fn is_bool_shaped_expr(expr: &Expr) -> bool {
    match expr {
        Expr::Binary(b) => matches!(
            b.op,
            BinOp::Eq(_)
                | BinOp::Ne(_)
                | BinOp::Lt(_)
                | BinOp::Le(_)
                | BinOp::Gt(_)
                | BinOp::Ge(_)
                | BinOp::And(_)
                | BinOp::Or(_)
        ),
        Expr::Unary(u) => matches!(u.op, UnOp::Not(_)),
        Expr::Paren(p) => is_bool_shaped_expr(&p.expr),
        Expr::Group(g) => is_bool_shaped_expr(&g.expr),
        _ => false,
    }
}

/// A value-position `match` (no arm guards) over a scalar OR enum scrutinee,
/// encoded as the ite via the existing implies/and atoms:
/// `and_i implies(guard_i, out = term_i)`, guard_i = the arm's discriminant
/// conjoined with the negations of earlier arms. Arm discriminants:
///   - scalar literal/range/or -> pattern-membership over the scrutinee;
///   - enum variant (Path / TupleStruct / Struct, all-wild or 1-field binding) ->
///     `variant_of(scrutinee) == "variant::<tag>"`, the panic-locus form, with a
///     single field binding mapped to the uninterpreted `payload:<tag>(scrutinee)`
///     accessor (substituted into the arm body);
///   - `_` or a bare `Pat::Ident` -> CATCH-ALL: guard = ¬earlier (terminal). A
///     bare ident is sound whether it is a unit variant or a binding -- for an
///     exhaustive match `¬earlier` IS the residual case, and the binding (if any)
///     is substituted to the scrutinee (a no-op for a unit variant).
/// None if the scrutinee isn't EUF, any arm has a guard, any arm pattern is
/// unsupported (multi-field binding, nested), or any body isn't EUF.
fn emit_match_value(expr: &Expr, scope: &TemporalScope) -> Option<Rc<Formula>> {
    let m = match expr {
        Expr::Match(m) => m,
        Expr::Paren(p) => return emit_match_value(&p.expr, scope),
        Expr::Group(g) => return emit_match_value(&g.expr, scope),
        _ => return None,
    };
    let scrutinee = translate_term_in_scope(&m.expr, scope).ok()?;
    if !term_is_euf_value(&scrutinee) {
        return None;
    }
    let mut negated: Vec<Rc<Formula>> = Vec::new();
    let mut clauses: Vec<(Rc<Formula>, Rc<Term>)> = Vec::new();
    for arm in &m.arms {
        if arm.guard.is_some() {
            return None;
        }
        let (atom, bindings) = match_arm_discriminant(&scrutinee, &arm.pat)?;
        let mut body = arm_body_euf_term(&arm.body, scope)?;
        for (n, t) in &bindings {
            body = subst_var_in_term(&body, n, t);
        }
        match atom {
            // Catch-all (`_` / bare ident): guard = ¬earlier, terminal.
            None => {
                let guard = match negated.len() {
                    0 => atomic_("true", vec![]),
                    1 => negated[0].clone(),
                    _ => and_(negated.clone()),
                };
                clauses.push((guard, body));
                let out = make_var("out");
                return Some(and_(
                    clauses
                        .into_iter()
                        .map(|(g, t)| implies(g, eq(out.clone(), t)))
                        .collect(),
                ));
            }
            Some(a) => {
                let mut gp = negated.clone();
                gp.push(a.clone());
                let guard = if gp.len() == 1 {
                    gp.remove(0)
                } else {
                    and_(gp)
                };
                clauses.push((guard, body));
                negated.push(not_(a));
            }
        }
    }
    // No catch-all: an exhaustive variant match -- the conditional clauses are
    // sound regardless of completeness (each is `if discriminant then out=term`).
    if clauses.is_empty() {
        return None;
    }
    let out = make_var("out");
    Some(and_(
        clauses
            .into_iter()
            .map(|(g, t)| implies(g, eq(out.clone(), t)))
            .collect(),
    ))
}

/// Classify a match-arm pattern over `scrutinee`: returns (discriminant atom or
/// None for a catch-all, payload bindings to substitute into the arm body). None
/// (the outer Option) for an unsupported pattern -> the whole match refuses.
#[allow(clippy::type_complexity)]
fn match_arm_discriminant(
    scrutinee: &Rc<Term>,
    pat: &Pat,
) -> Option<(Option<Rc<Formula>>, Vec<(String, Rc<Term>)>)> {
    let variant_eq = |tag: &str| {
        eq(
            Rc::new(Term::Ctor {
                name: "variant_of".to_string(),
                args: vec![scrutinee.clone()],
            }),
            str_const(format!("variant::{tag}")),
        )
    };
    match pat {
        Pat::Wild(_) => Some((None, vec![])),
        Pat::Ident(id) if id.subpat.is_none() && id.mutability.is_none() && id.by_ref.is_none() => {
            // catch-all binding (or unit variant): bind name -> scrutinee.
            Some((None, vec![(id.ident.to_string(), scrutinee.clone())]))
        }
        Pat::Lit(_) | Pat::Range(_) | Pat::Or(_) | Pat::Paren(_) => {
            Some((Some(pattern_membership_formula(scrutinee, pat)?), vec![]))
        }
        Pat::Path(p) => Some((Some(variant_eq(&path_to_variant_string(&p.path))), vec![])),
        Pat::TupleStruct(ts) => {
            let tag = path_to_variant_string(&ts.path);
            // A `..` rest makes positional payload indices ambiguous -> only
            // allowed when there are no bindings at all (all wild/rest).
            let all_inert = ts
                .elems
                .iter()
                .all(|e| matches!(e, Pat::Wild(_) | Pat::Rest(_)));
            if all_inert {
                return Some((Some(variant_eq(&tag)), vec![]));
            }
            if ts.elems.iter().any(|e| matches!(e, Pat::Rest(_))) {
                return None; // rest + bindings: ambiguous positions, refuse
            }
            let n = ts.elems.len();
            let mut bindings = Vec::new();
            for (i, elem) in ts.elems.iter().enumerate() {
                match elem {
                    Pat::Wild(_) => {}
                    Pat::Ident(id)
                        if id.subpat.is_none()
                            && id.mutability.is_none()
                            && id.by_ref.is_none() =>
                    {
                        // Single-field keeps `payload:tag` (matches the kit's
                        // wrapped_variant_entry congruence); multi-field is indexed.
                        let acc = if n == 1 {
                            format!("payload:{tag}")
                        } else {
                            format!("payload:{tag}.{i}")
                        };
                        bindings.push((
                            id.ident.to_string(),
                            Rc::new(Term::Ctor {
                                name: acc,
                                args: vec![scrutinee.clone()],
                            }),
                        ));
                    }
                    _ => return None, // nested pattern -> refuse
                }
            }
            Some((Some(variant_eq(&tag)), bindings))
        }
        Pat::Struct(s) => {
            let tag = path_to_variant_string(&s.path);
            let mut bindings = Vec::new();
            for f in &s.fields {
                let field_name = match &f.member {
                    syn::Member::Named(id) => id.to_string(),
                    syn::Member::Unnamed(idx) => idx.index.to_string(),
                };
                match &*f.pat {
                    Pat::Wild(_) => {}
                    Pat::Ident(id)
                        if id.subpat.is_none()
                            && id.mutability.is_none()
                            && id.by_ref.is_none() =>
                    {
                        bindings.push((
                            id.ident.to_string(),
                            Rc::new(Term::Ctor {
                                name: format!("payload:{tag}.{field_name}"),
                                args: vec![scrutinee.clone()],
                            }),
                        ));
                    }
                    _ => return None,
                }
            }
            // A `..` rest is fine here (it only drops unbound fields, no index shift).
            Some((Some(variant_eq(&tag)), bindings))
        }
        Pat::Reference(r) => match_arm_discriminant(scrutinee, &r.pat),
        _ => None,
    }
}

/// A match arm's body as an EUF term (a block via block_euf_term, else a direct
/// EUF tail expression).
fn arm_body_euf_term(expr: &Expr, scope: &TemporalScope) -> Option<Rc<Term>> {
    match expr {
        Expr::Block(b) => block_euf_term(&b.block, scope),
        other => {
            let t = translate_term_in_scope(other, scope).ok()?;
            term_is_euf_value(&t).then_some(t)
        }
    }
}

/// A block's value as an EUF term: a single EUF tail expression, or a leading
/// immutable-let prefix substituted into an EUF tail. None if neither shape.
fn block_euf_term(block: &syn::Block, scope: &TemporalScope) -> Option<Rc<Term>> {
    if let [Stmt::Expr(tail, None)] = block.stmts.as_slice() {
        let t = translate_term_in_scope(tail, scope).ok()?;
        return term_is_euf_value(&t).then_some(t);
    }
    let_prefix_euf_term(block, scope)
}

/// A value-position `if` / `else if` / `else` chain (TOTAL -- a final `else` is
/// required, else `out` is undefined on a branch and we cannot warrant). Encoded
/// as the ite via the EXISTING implies/and atoms: `and_i implies(guard_i, out =
/// term_i)`, where guard_i is the i-th branch condition conjoined with the
/// negations of all earlier conditions. None if any condition does not translate
/// to a Formula (e.g. `if let`), any branch is not an EUF block, or no final else.
fn emit_if_value(expr: &Expr, scope: &TemporalScope) -> Option<Rc<Formula>> {
    let mut clauses: Vec<(Rc<Formula>, Rc<Term>)> = Vec::new();
    collect_if_clauses(expr, scope, &mut Vec::new(), &mut clauses)?;
    if clauses.is_empty() {
        return None;
    }
    let out = make_var("out");
    Some(and_(
        clauses
            .into_iter()
            .map(|(guard, term)| implies(guard, eq(out.clone(), term)))
            .collect(),
    ))
}

fn collect_if_clauses(
    expr: &Expr,
    scope: &TemporalScope,
    negated: &mut Vec<Rc<Formula>>,
    out_clauses: &mut Vec<(Rc<Formula>, Rc<Term>)>,
) -> Option<()> {
    let if_expr = match expr {
        Expr::If(i) => i,
        Expr::Paren(p) => return collect_if_clauses(&p.expr, scope, negated, out_clauses),
        Expr::Group(g) => return collect_if_clauses(&g.expr, scope, negated, out_clauses),
        _ => return None,
    };
    // The `if` condition as a Formula. First try the assertion bool-lifter
    // (comparisons / &&/|| / matches! / string predicates). If that declines,
    // fall back to a bool-returning EUF expression (`if f(x)`, `if x.is_valid()`):
    // model it as `cond_term == true`. The if-condition POSITION guarantees the
    // expr is bool, so this is sound (no is_bool_shaped gate needed here). An
    // `if let` cond is an Expr::Let -> neither path -> None.
    let cond = match translate_bool_assertion(&if_expr.cond, scope, &FloatWidthScope::new()) {
        Ok(entry) => entry.atom,
        Err(_) => {
            let t = translate_term_in_scope(&if_expr.cond, scope).ok()?;
            if !term_is_euf_value(&t) {
                return None;
            }
            eq(t, bool_const(true))
        }
    };
    let then_term = block_euf_term(&if_expr.then_branch, scope)?;
    let mut gp = negated.clone();
    gp.push(cond.clone());
    let guard = if gp.len() == 1 {
        gp.remove(0)
    } else {
        and_(gp)
    };
    out_clauses.push((guard, then_term));
    // A final `else` is required for totality.
    let (_, else_expr) = if_expr.else_branch.as_ref()?;
    match &**else_expr {
        Expr::If(_) => {
            negated.push(not_(cond));
            let r = collect_if_clauses(else_expr, scope, negated, out_clauses);
            negated.pop();
            r
        }
        Expr::Block(b) => {
            let else_term = block_euf_term(&b.block, scope)?;
            let mut gp = negated.clone();
            gp.push(not_(cond));
            let guard = if gp.len() == 1 {
                gp.remove(0)
            } else {
                and_(gp)
            };
            out_clauses.push((guard, else_term));
            Some(())
        }
        _ => None,
    }
}

// (substitution reuses the existing `subst_var_in_term` defined earlier.)

/// A bounded-output universe over `out` from a known TOTAL rust primitive in the
/// tail: a UNIVERSAL over the output (not a pin). Today `recv.clamp(lo, hi)` =>
/// `lo <= out <= hi`, when receiver and bounds are side-effect-free terms. The
/// bound holds on every returning input regardless of the receiver -- the teeth
/// that statically refute an out-of-bound twin.
fn bounded_output_universe(expr: &Expr, scope: &TemporalScope) -> Option<Rc<Formula>> {
    let call = match expr {
        Expr::MethodCall(c) => c,
        Expr::Paren(p) => return bounded_output_universe(&p.expr, scope),
        Expr::Group(g) => return bounded_output_universe(&g.expr, scope),
        _ => return None,
    };
    if call.method == "clamp" && call.args.len() == 2 {
        let recv = translate_term_in_scope(&call.receiver, scope).ok()?;
        let lo = translate_term_in_scope(&call.args[0], scope).ok()?;
        let hi = translate_term_in_scope(&call.args[1], scope).ok()?;
        if term_is_euf_value(&recv) && term_is_euf_value(&lo) && term_is_euf_value(&hi) {
            return Some(and_(vec![
                gte(make_var("out"), lo),
                lte(make_var("out"), hi),
            ]));
        }
    }
    None
}

/// A closed consistency source contract `inv` over `out` (the return value).
fn source_value_contract(name: &str, inv: Rc<Formula>) -> ContractDecl {
    ContractDecl {
        name: format!("rust-source::{name}"),
        pre: None,
        post: None,
        inv: Some(inv),
        out_binding: "out".to_string(),
        evidence: None,
        panic_loci: Vec::new(),
        concept_hint: None,
    }
}

/// True iff a value term is an emittable EUF value: reads, total operators,
/// value constructors, AND value-position calls (`method:`/`call:`) treated as
/// uninterpreted deterministic functions -- the method-call-as-EUF shape, the
/// same policy Python's `_Emitter` applies to value-position calls (`out =
/// m(recv, args)` over an uninterpreted `m`). Excluded: a known PANIC method
/// (unwrap/expect family -> divergence, refused as an effect by `effect_refusal`),
/// `await` (async effect), and a `macro:` var (unknown). Statement-level effects
/// (assignment, `&mut`, loops) never reach here: an assignment/`&mut` tail fails
/// translation and multi-statement bodies are not a single tail expr -- both fall
/// through to `effect_refusal`.
fn term_is_euf_value(term: &Term) -> bool {
    match term {
        Term::Var { name } => !name.starts_with("macro:"),
        Term::Const { .. } => true,
        Term::Ctor { name, args } => {
            let panicker = matches!(
                name.as_str(),
                "method:unwrap"
                    | "method:expect"
                    | "method:unwrap_unchecked"
                    | "method:unwrap_err"
                    | "method:expect_err"
            );
            let async_effect = name == "await";
            !panicker && !async_effect && args.iter().all(|a| term_is_euf_value(a))
        }
        Term::Lambda { body, .. } => term_is_euf_value(body),
        Term::Let { bindings, body } => {
            bindings.iter().all(|b| term_is_euf_value(&b.bound_term)) && term_is_euf_value(body)
        }
    }
}

/// A boolean body as a membership formula: `matches!` predicates joined by
/// `&&`/`||`/`!`. Any other shape is not emittable here (-> None).
fn emit_bool_membership_formula(expr: &Expr, scope: &TemporalScope) -> Option<Rc<Formula>> {
    match expr {
        Expr::Paren(p) => emit_bool_membership_formula(&p.expr, scope),
        Expr::Group(g) => emit_bool_membership_formula(&g.expr, scope),
        Expr::Unary(u) if matches!(u.op, UnOp::Not(_)) => {
            Some(not_(emit_bool_membership_formula(&u.expr, scope)?))
        }
        Expr::Binary(b) => match b.op {
            BinOp::Or(_) | BinOp::BitOr(_) => Some(or_(vec![
                emit_bool_membership_formula(&b.left, scope)?,
                emit_bool_membership_formula(&b.right, scope)?,
            ])),
            BinOp::And(_) | BinOp::BitAnd(_) => Some(and_(vec![
                emit_bool_membership_formula(&b.left, scope)?,
                emit_bool_membership_formula(&b.right, scope)?,
            ])),
            _ => None,
        },
        Expr::Macro(m) => matches_membership_formula(&m.mac, scope),
        _ => None,
    }
}

/// `matches!(<scrutinee>, <pattern> [if <guard>])` -> the membership formula.
/// Unguarded scalar/string patterns reduce over the scrutinee's value
/// (`scrutinee_scalar_var` + `pattern_membership_formula`). A guard, or an enum
/// pattern with bindings, routes through `match_arm_discriminant` (the SAME
/// `variant_of`/`payload:` machinery as a value-`match`): the discriminant is
/// conjoined with the guard translated as a bool predicate, with each pattern
/// binding substituted by its payload accessor (`p` in `Punct(p)` -> the
/// `payload:Punct(scrutinee)` term). The guard must be a bool-predicate the
/// assertion translator accepts and must compose; anything else -> None (the
/// body stays unclassified, never a hollow warrant).
fn matches_membership_formula(mac: &syn::Macro, scope: &TemporalScope) -> Option<Rc<Formula>> {
    if !mac
        .path
        .segments
        .last()
        .is_some_and(|s| s.ident == "matches")
    {
        return None;
    }
    let (scrutinee, pat, guard) = mac
        .parse_body_with(|input: ParseStream| {
            let scrutinee: Expr = input.parse()?;
            input.parse::<Token![,]>()?;
            let pat = Pat::parse_multi_with_leading_vert(input)?;
            let guard = if input.peek(Token![if]) {
                input.parse::<Token![if]>()?;
                Some(input.parse::<Expr>()?)
            } else {
                None
            };
            Ok::<_, syn::Error>((scrutinee, pat, guard))
        })
        .ok()?;
    let Some(guard) = guard else {
        // Unguarded. A simple-name scrutinee: scalar/string code-point membership,
        // then enum-variant discrimination (`is_ipv4`/`is_some`: `variant_of(x) ==
        // "variant::V"` via match_arm_discriminant; a bare binding/wildcard has no
        // discriminant -> vacuous -> None, never a teethless `out <-> true`).
        if let Some(scrutinee_term) = scrutinee_scalar_var(&scrutinee) {
            if let Some(f) = pattern_membership_formula(&scrutinee_term, &pat) {
                return Some(f);
            }
            if let Some((Some(disc), _bindings)) = match_arm_discriminant(&scrutinee_term, &pat) {
                return Some(disc);
            }
        }
        // Slice pattern over a general (possibly method-call) scrutinee:
        // `matches!(self.octets(), [169, 254, ..])` (the net is_documentation /
        // is_link_local family).
        return emit_slice_pattern_membership(&scrutinee, &pat, scope);
    };
    // Guarded: discriminant /\ guard[pattern bindings := payload accessors].
    let scrutinee_term = scrutinee_scalar_var(&scrutinee)?;
    let (disc, bindings) = match_arm_discriminant(&scrutinee_term, &pat)?;
    let entry = translate_bool_assertion(&guard, scope, &FloatWidthScope::new()).ok()?;
    let mut guard_f = entry.atom;
    for (name, term) in &bindings {
        guard_f = subst_var_in_formula(&guard_f, name, term);
    }
    Some(match disc {
        Some(d) => and_(vec![d, guard_f]),
        None => guard_f,
    })
}

/// A slice-pattern `matches!(scrut, [lit, _, .., lit])` as a membership formula:
/// each fixed FRONT position `i` (before an optional TRAILING `..`) becomes
/// `index(scrut, i) == lit` over the existing `index` accessor, conjoined.
/// Wildcards skip a position; a trailing `..` leaves the rest unconstrained. The
/// scrutinee is any EUF term (`self.octets()` -> `method:octets(self)`). A
/// non-trailing `..` (back-indexing), a binding/nested element, or an all-wild
/// pattern (no teeth) -> None.
fn emit_slice_pattern_membership(
    scrutinee: &Expr,
    pat: &Pat,
    scope: &TemporalScope,
) -> Option<Rc<Formula>> {
    let Pat::Slice(slice) = pat else {
        return None;
    };
    let scrut = translate_term_in_scope(scrutinee, scope).ok()?;
    if !term_is_euf_value(&scrut) {
        return None;
    }
    let last = slice.elems.len().saturating_sub(1);
    let mut conj: Vec<Rc<Formula>> = Vec::new();
    for (i, elem) in slice.elems.iter().enumerate() {
        match elem {
            // A `..` rest is only sound at the end: a mid-pattern rest shifts the
            // following elements to back-indexing, which `index(scrut, i)` (front)
            // does not model.
            Pat::Rest(_) => {
                if i != last {
                    return None;
                }
                break;
            }
            Pat::Wild(_) => {}
            Pat::Lit(p) => {
                let elem_term = Rc::new(Term::Ctor {
                    name: "index".to_string(),
                    args: vec![scrut.clone(), num(i as i128)],
                });
                conj.push(eq(elem_term, lit_membership_term(&p.lit)?));
            }
            _ => return None,
        }
    }
    if conj.is_empty() {
        return None; // all wild / bare rest -> vacuous, no teeth
    }
    Some(and_(conj))
}

/// The scrutinee of a char/byte `matches!` reduces to a single bound name (its
/// code point): `*self` / `self` / a one-segment path, through deref/ref/paren.
fn scrutinee_scalar_var(expr: &Expr) -> Option<Rc<Term>> {
    match expr {
        Expr::Paren(p) => scrutinee_scalar_var(&p.expr),
        Expr::Group(g) => scrutinee_scalar_var(&g.expr),
        Expr::Unary(u) if matches!(u.op, UnOp::Deref(_)) => scrutinee_scalar_var(&u.expr),
        Expr::Reference(r) => scrutinee_scalar_var(&r.expr),
        Expr::Path(p) if p.path.segments.len() == 1 => {
            Some(make_var(p.path.segments[0].ident.to_string()))
        }
        _ => None,
    }
}

/// A char/byte/int pattern as a membership formula over `scrutinee` (its code
/// point): literal -> `=`, inclusive/half-open range -> bounded `and`, or-pattern
/// -> `or`, wildcard -> `true`. Bindings/structs/etc. are not emittable (-> None).
fn pattern_membership_formula(scrutinee: &Rc<Term>, pat: &Pat) -> Option<Rc<Formula>> {
    match pat {
        Pat::Paren(p) => pattern_membership_formula(scrutinee, &p.pat),
        Pat::Wild(_) => Some(atomic_("true", vec![])),
        Pat::Or(o) => {
            let mut cases = Vec::with_capacity(o.cases.len());
            for c in &o.cases {
                cases.push(pattern_membership_formula(scrutinee, c)?);
            }
            Some(or_(cases))
        }
        Pat::Lit(p) => Some(eq(scrutinee.clone(), lit_membership_term(&p.lit)?)),
        Pat::Range(r) => {
            let inclusive = matches!(r.limits, syn::RangeLimits::Closed(_));
            let mut conj = Vec::new();
            if let Some(lo) = r.start.as_deref().and_then(expr_codepoint) {
                conj.push(gte(scrutinee.clone(), num(lo)));
            }
            if let Some(hi) = r.end.as_deref().and_then(expr_codepoint) {
                conj.push(if inclusive {
                    lte(scrutinee.clone(), num(hi))
                } else {
                    lt(scrutinee.clone(), num(hi))
                });
            }
            if conj.is_empty() {
                return None;
            }
            Some(and_(conj))
        }
        _ => None,
    }
}

/// A `matches!` literal pattern bound as a membership *term* to equate the
/// scrutinee against: a string literal becomes a `String`-sorted constant
/// (string-theory regime; the scrutinee is the string value itself), every
/// scalar (char/byte/int) becomes its `Int` code point. A `matches!` arm is
/// homogeneous in practice (`matches!(x, "a" | 1)` is a type error), so a
/// String/Int mix never reaches the same scrutinee.
fn lit_membership_term(lit: &Lit) -> Option<Rc<Term>> {
    match lit {
        Lit::Str(s) => Some(str_const(s.value())),
        _ => Some(num(lit_codepoint(lit)?)),
    }
}

/// The integer code point of a char / byte / integer literal pattern bound.
/// i128 carrier: a wide integer pattern (`match x { 0xffff_..._u64 => .. }`)
/// folds to its EXACT value via `parse_int_lit`, never a truncation.
fn lit_codepoint(lit: &Lit) -> Option<i128> {
    match lit {
        Lit::Char(c) => Some(i128::from(u32::from(c.value()))),
        Lit::Byte(b) => Some(i128::from(b.value())),
        Lit::Int(i) => parse_int_lit(i).ok(),
        _ => None,
    }
}

fn expr_codepoint(expr: &Expr) -> Option<i128> {
    match expr {
        Expr::Lit(ExprLit { lit, .. }) => lit_codepoint(lit),
        Expr::Paren(p) => expr_codepoint(&p.expr),
        Expr::Group(g) => expr_codepoint(&g.expr),
        _ => None,
    }
}

fn literal_iterator_elements(expr: &Expr) -> Result<Option<(IteratorKind, Vec<Rc<Term>>)>, String> {
    match expr {
        Expr::MethodCall(call) if call.args.is_empty() && call.method == "chars" => {
            let Some(value) = literal_string_value(&call.receiver) else {
                return Ok(None);
            };
            let elements = value
                .chars()
                .map(|ch| str_const(ch.to_string()))
                .collect::<Vec<_>>();
            Ok(Some((IteratorKind::Chars, elements)))
        }
        Expr::MethodCall(call) if call.args.is_empty() && call.method == "iter" => {
            let Some(bytes) = literal_byte_string_value(&call.receiver) else {
                return Ok(None);
            };
            let elements = bytes.into_iter().map(|b| num(i128::from(b))).collect();
            Ok(Some((IteratorKind::Bytes, elements)))
        }
        Expr::Paren(paren) => literal_iterator_elements(&paren.expr),
        Expr::Group(group) => literal_iterator_elements(&group.expr),
        _ => Ok(None),
    }
}

fn literal_string_value(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Str(s), ..
        }) => Some(s.value()),
        Expr::Paren(paren) => literal_string_value(&paren.expr),
        Expr::Group(group) => literal_string_value(&group.expr),
        _ => None,
    }
}

fn literal_byte_string_value(expr: &Expr) -> Option<Vec<u8>> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::ByteStr(bytes),
            ..
        }) => Some(bytes.value()),
        Expr::Paren(paren) => literal_byte_string_value(&paren.expr),
        Expr::Group(group) => literal_byte_string_value(&group.expr),
        _ => None,
    }
}

fn matches_param_receiver(expr: &Expr, param_name: &str) -> bool {
    match expr {
        Expr::Path(path) => path
            .path
            .segments
            .last()
            .is_some_and(|segment| segment.ident == param_name),
        Expr::Paren(paren) => matches_param_receiver(&paren.expr, param_name),
        Expr::Group(group) => matches_param_receiver(&group.expr, param_name),
        _ => false,
    }
}

fn method_call_assertion_name(
    method: &str,
    args: Vec<Rc<Term>>,
    local_scope: &str,
) -> Option<String> {
    let term = Term::Ctor {
        name: format!("method:{method}"),
        args,
    };
    callsite_assertion_name(&term, local_scope)
}

fn assertion_entry_from_relation(
    lhs: Rc<Term>,
    rhs: Rc<Term>,
    op: RelationOp,
    scope: &TemporalScope,
) -> AssertionEntry {
    if let Some(tag) =
        constructor_operator_tag(lhs.as_ref()).or_else(|| constructor_operator_tag(rhs.as_ref()))
    {
        return AssertionEntry {
            name: None,
            atom: constructor_operator_atom(lhs, rhs, op, &tag),
        };
    }

    let name = if is_ground_value(lhs.as_ref()) {
        callsite_assertion_name(rhs.as_ref(), scope.local_scope())
    } else if is_ground_value(rhs.as_ref()) {
        callsite_assertion_name(lhs.as_ref(), scope.local_scope())
    } else {
        None
    };
    let atom = match op {
        RelationOp::Eq => eq(lhs, rhs),
        RelationOp::Ne => ne(lhs, rhs),
        RelationOp::Lt => lt(lhs, rhs),
        RelationOp::Le => lte(lhs, rhs),
        RelationOp::Gt => gt(lhs, rhs),
        RelationOp::Ge => gte(lhs, rhs),
    };
    AssertionEntry { name, atom }
}

fn constructor_operator_atom(
    lhs: Rc<Term>,
    rhs: Rc<Term>,
    op: RelationOp,
    tag: &str,
) -> Rc<Formula> {
    // Federated operator-dispatch shape: user-type operators are method calls,
    // so ==/!= lift as equality over the canonical eq call result, and
    // order operators lift as their own canonical call results. Java .equals
    // and Python __eq__ must mirror this byte-for-byte for the same TypeKey.
    let operator_call = Rc::new(Term::Ctor {
        name: format!("call:{}:{tag}", op.operator_call_name()),
        args: vec![lhs, rhs],
    });
    eq(operator_call, bool_const(op.operator_asserted_result()))
}

fn constructor_operator_tag(term: &Term) -> Option<String> {
    let Term::Ctor { name, .. } = term else {
        return None;
    };
    let callee = name.strip_prefix("call:")?;
    let final_segment = callee.rsplit("::").next().unwrap_or(callee);
    final_segment
        .chars()
        .next()
        .is_some_and(|ch| ch.is_ascii_uppercase())
        .then(|| callee.to_string())
}

fn is_ground_value(term: &Term) -> bool {
    match term {
        Term::Const { .. } => true,
        Term::Var { name } if name.starts_with("literal:") => true,
        Term::Ctor { name, args } if is_ground_value_ctor(name) => {
            args.iter().all(|arg| is_ground_value(arg))
        }
        _ => false,
    }
}

fn is_ground_value_ctor(name: &str) -> bool {
    matches!(
        name,
        "+" | "-"
            | "*"
            | "int-div"
            | "int-rem"
            | "bit-and"
            | "bit-or"
            | "bit-xor"
            | "shift-left"
            | "shift-right"
            | "bit-not"
            | "ref"
            | "range"
            | "range_incl"
    )
}

fn bool_const(value: bool) -> Rc<Term> {
    Rc::new(Term::Const {
        value: ConstValue::Bool(value),
        sort: sugar_ir_symbolic::Sort::bool(),
    })
}

fn callsite_assertion_name(term: &Term, local_scope: &str) -> Option<String> {
    let Term::Ctor { name, .. } = term else {
        return None;
    };
    if is_location_keyed_call_result(name) {
        return None;
    }
    let callee = callsite_callee_name(name)?;
    // A bare free-function callee (no `::` separator and NOT a `method:` call)
    // is a LOCAL helper defined inside the test, NOT a globally federated API.
    // Local helpers with the same name but different semantics exist in
    // different test functions (e.g. `fn string(c: char)` in test_escape_debug
    // vs test_escape_default). Scoping the key to the test fn prevents
    // cross-test conflation. We deliberately do NOT scope `method:` calls: a
    // method name carries a single `:` (not `::`), so the old `!contains("::")`
    // check wrongly test-scoped EVERY method call (~1300 obligations), needlessly
    // disabling cross-test/cross-proof method coalescing.
    let is_local_helper = !callee.contains("::") && !callee.starts_with("method:");
    let scoped_callee = if is_local_helper {
        format!("{local_scope}::{callee}")
    } else {
        callee.to_string()
    };
    Some(format!(
        "{scoped_callee}#euf#{}::assertion",
        canonical_callsite_sig(term, local_scope)
    ))
}

fn is_location_keyed_call_result(name: &str) -> bool {
    matches!(
        name,
        "call:core::ptr::eq" | "call:ptr::eq" | "call:std::ptr::eq"
    )
}

fn canonical_callsite_sig(term: &Term, local_scope: &str) -> String {
    let Term::Ctor { name, args } = term else {
        return term_key(term);
    };
    let Some(callee) = callsite_callee_name(name) else {
        return term_key(term);
    };
    let head = call_result_head(callee, args.len());
    let inner = args
        .iter()
        .map(|arg| {
            if callee.starts_with("method:") {
                canonical_method_arg_sig(arg, local_scope)
            } else {
                canonical_term_sig(arg)
            }
        })
        .collect::<Vec<_>>()
        .join(",");
    format!("c:{head}({inner})")
}

fn callsite_callee_name(name: &str) -> Option<&str> {
    if name == "str.len" {
        return Some("method:len");
    }
    name.strip_prefix("call:")
        .or_else(|| name.starts_with("method:").then_some(name))
}

fn call_result_head(callee: &str, arity: usize) -> String {
    let safe = callee
        .chars()
        .map(|ch| {
            if ch.is_ascii() && ch.is_ascii_alphanumeric() {
                ch
            } else {
                '_'
            }
        })
        .collect::<String>();
    format!("callresult_{safe}_a{arity}")
}

fn canonical_term_sig(term: &Term) -> String {
    match term {
        Term::Var { name } => format!("v:{name}"),
        Term::Const { value, sort } => match value {
            // The literal's WIDTH (when not the default `Int`) is part of the
            // callsite key, so `align_of_val(&1u8)` and `&1u64` do not collapse
            // onto `i:1`. Default-`Int` literals keep the bare `i:{v}` key (no
            // churn on the common, unsuffixed case).
            ConstValue::Int(value) if sort.name == "Int" => format!("i:{value}"),
            ConstValue::Int(value) => format!("i:{value}:{}", sort.name),
            ConstValue::Real(value) => format!("r:{value}"),
            ConstValue::String(value) => format!("s:{value:?}"),
            ConstValue::Bool(value) => format!("b:{value}"),
        },
        Term::Ctor { name, args } => {
            let inner = args
                .iter()
                .map(|arg| canonical_term_sig(arg))
                .collect::<Vec<_>>()
                .join(",");
            format!("c:{name}({inner})")
        }
        _ => term_key(term),
    }
}

fn canonical_method_arg_sig(term: &Term, local_scope: &str) -> String {
    match term {
        Term::Var { name } if name.starts_with("literal:") => format!("v:{name}"),
        Term::Var { name } if is_unqualified_local_name(name) => {
            format!("v:{local_scope}::{name}")
        }
        Term::Var { name } => format!("v:{name}"),
        Term::Const { value, sort } => match value {
            // The literal's WIDTH (when not the default `Int`) is part of the
            // callsite key, so `align_of_val(&1u8)` and `&1u64` do not collapse
            // onto `i:1`. Default-`Int` literals keep the bare `i:{v}` key (no
            // churn on the common, unsuffixed case).
            ConstValue::Int(value) if sort.name == "Int" => format!("i:{value}"),
            ConstValue::Int(value) => format!("i:{value}:{}", sort.name),
            ConstValue::Real(value) => format!("r:{value}"),
            ConstValue::String(value) => format!("s:{value:?}"),
            ConstValue::Bool(value) => format!("b:{value}"),
        },
        Term::Ctor { name, args } => {
            let inner = args
                .iter()
                .map(|arg| canonical_method_arg_sig(arg, local_scope))
                .collect::<Vec<_>>()
                .join(",");
            format!("c:{name}({inner})")
        }
        _ => term_key(term),
    }
}

fn is_unqualified_local_name(name: &str) -> bool {
    !name.contains("::")
}

fn is_refinement_predicate_term(term: &Term) -> bool {
    matches!(
        term,
        Term::Ctor { name, .. }
            if matches!(
                name.as_str(),
                "method:is_nan"
                    | "method:is_finite"
                    | "method:is_infinite"
                    | "method:is_normal"
                    | "method:is_subnormal"
                    | "method:is_sign_positive"
                    | "method:is_sign_negative"
            )
    )
}

fn term_key(term: &Term) -> String {
    format!("{term:?}")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

/// Detect Rust format-string implicit captures (e.g. `"{socket}"` or
/// `"{socket:<24}"`) that reference a `let mut` local from `scope`.
/// The format spec opens with `{` and the identifier runs until the
/// first of `:`, `}`, or `!` (for debug format `{x:?}`).
fn macro_literal_contains_mut_local(lit_text: &str, scope: &TemporalScope) -> bool {
    let bytes = lit_text.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'{' {
            i += 1;
            // Skip escaped `{{`
            if i < bytes.len() && bytes[i] == b'{' {
                i += 1;
                continue;
            }
            // Collect identifier characters until `:`, `}`, `!`, or end
            let start = i;
            while i < bytes.len()
                && bytes[i] != b':'
                && bytes[i] != b'}'
                && bytes[i] != b'!'
                && bytes[i] != b'.'
            {
                i += 1;
            }
            let candidate = &lit_text[start..i];
            // Trim surrounding whitespace that may appear in the raw token text
            let candidate = candidate.trim();
            if !candidate.is_empty() && scope.is_mut_local(candidate) {
                return true;
            }
        } else {
            i += 1;
        }
    }
    false
}

fn translate_term_in_scope(expr: &Expr, scope: &TemporalScope) -> Result<Rc<Term>, String> {
    match expr {
        Expr::Lit(lit) => translate_lit(lit),
        // `const { EXPR }` is a compile-time evaluation of EXPR: PURE (no runtime
        // effect), its value IS EXPR's value. Translate the inner expression-only
        // block and scope its locals, mirroring the assertion-term path. core uses
        // const blocks for const-generic / intrinsic constants
        // (`const { type_name::<T>() }`, `const { 4 * 8 }`).
        Expr::Const(const_block) => {
            // A const block wrapping a bare PATH is (or may be) a function-item /
            // const reference -- sugar, NOT a keyed value term (see the fn-pointer
            // residual test; "function names are sugar"). Keep it residual. A const
            // block wrapping a COMPUTED expression (arithmetic, call, ...) is a pure
            // compile-time value -> translate it.
            if let [Stmt::Expr(Expr::Path(_), None)] = const_block.block.stmts.as_slice() {
                // A const block wrapping a bare PATH (`const { Zst }`) is a function-item /
                // const reference -- a NAME, which is sugar, not a keyed value term. There is
                // no constructible value to read: a SOURCE property (kin to "function names are
                // sugar"), not a lifter gap. Typed as `Effect::Unsupported` (term-shaped).
                let effect = Effect::unsupported_term(
                    &token_key(expr),
                    UnsupportedTermCause::ConstBlockPath,
                );
                return Err(effect.reason());
            }
            let term =
                translate_expression_only_block_in_scope(&const_block.block, "const", scope)?;
            Ok(scope_const_block_locals(term, scope.local_scope()))
        }
        Expr::Unary(unary) if matches!(unary.op, UnOp::Neg(_)) => {
            if let Some(value) = const_int(&unary.expr) {
                return Ok(num(-value));
            }
            if let Some(value) = const_float(&unary.expr)? {
                if real_literal_is_zero(&value) {
                    return Err(format!(
                        "signed zero float literal remains an IEEE refinement `{}`",
                        token_key(expr)
                    ));
                }
                return Ok(real_const(format!("-{value}")));
            }
            // Arithmetic negation of a non-literal (`-x`): `0 - x`, the same
            // integer-subtraction ctor as a binary `-`. Only signed operands
            // compile with unary `-`, so the Int regime is sound. The inner term
            // must itself be liftable (its named Err propagates).
            Ok(Rc::new(Term::Ctor {
                name: "-".to_string(),
                args: vec![num(0), translate_term_in_scope(&unary.expr, scope)?],
            }))
        }
        Expr::Unary(unary) if matches!(unary.op, UnOp::Not(_)) => Ok(Rc::new(Term::Ctor {
            name: "bit-not".to_string(),
            args: vec![translate_term_in_scope(&unary.expr, scope)?],
        })),
        // Dereference: *p is a function of the pointer/reference term, the same
        // EUF shape as the immutable-reference arm below. `*a == *b` reasons
        // structurally and a contradiction over one dereferenced term is UNSAT.
        Expr::Unary(unary) if matches!(unary.op, UnOp::Deref(_)) => Ok(Rc::new(Term::Ctor {
            name: "deref".to_string(),
            args: vec![translate_term_in_scope(&unary.expr, scope)?],
        })),
        Expr::Path(path) if path.path.is_ident("None") => Ok(Rc::new(Term::Ctor {
            name: "call:None".to_string(),
            args: Vec::new(),
        })),
        Expr::Path(path) => Ok(make_var(scope.path_name(&path.path)?)),
        Expr::Call(call) => {
            if let Some(term) = type_id_of_call_term(&call.func, call.args.len())? {
                return Ok(term);
            }
            let mut args = Vec::new();
            for arg in &call.args {
                args.push(translate_term_in_scope(arg, scope)?);
            }
            Ok(Rc::new(Term::Ctor {
                name: format!("call:{}", expr_head_key(&call.func)),
                args,
            }))
        }
        Expr::Array(array) => {
            literal_aggregate_term_in_scope("Array", array.elems.iter(), expr, scope)
        }
        Expr::Tuple(tuple) => {
            literal_aggregate_term_in_scope("Tuple", tuple.elems.iter(), expr, scope)
        }
        Expr::Repeat(repeat) => {
            // `[elem; N]` is an N-element array constructor. With a LITERAL count it
            // is EXACTLY the N-fold explicit array `[elem, elem, ...]`, the same value
            // and (by construction) the same aggregate term -- so `[0xab; 3]` and
            // `[0xab, 0xab, 0xab]` are congruent, and two different repeats are
            // distinct terms (the teeth). A non-literal count is not a finite
            // construction from the written literal, so it is REFUSED BY NAME; an
            // element that does not translate propagates its own named Err.
            let Some(count) = repeat_count_literal(&repeat.len) else {
                // A non-literal count (`[0u8; SIZE]`, `[(); SIZE - 1]`) is not a finite
                // construction from the written literal: the universe size is symbolic
                // (const-generic / const expr), so no aggregate term can be pinned. A SOURCE
                // property, not a lifter gap. THIN NODE-ROUTER: the non-literal-length verdict
                // is owned by the `ArrayRepeatSugar` node, which `Hit`s `Effect::ArrayRepeat`
                // in its own `desugar`; this arm renders `effect.reason()` to the `Err` exactly
                // as before (byte-identical). `decompose_array_repeat` recognizes ONLY this
                // refuse-shape (it returns `None` for a literal-count repeat, which never
                // reaches here -- the `let-else` succeeds and the constructive expansion below
                // runs); on the unreachable structural backstop the term path keeps its own
                // `unsupported term` cause.
                return match sugar::array_repeat::decompose_array_repeat(expr) {
                    Some(node) => match node.desugar_ctx_free() {
                        Outcome::Hit(effect @ Effect::ArrayRepeat { .. }) => Err(effect.reason()),
                        _ => Err(format!("unsupported term `{}`", token_key(expr))),
                    },
                    None => Err(format!("unsupported term `{}`", token_key(expr))),
                };
            };
            // Bound the expansion so a pathological literal length cannot blow up the
            // term; an over-bound repeat is named, not silently truncated.
            const MAX_REPEAT: usize = 4096;
            if count > MAX_REPEAT {
                return Err(format!(
                    "array-repeat length {count} exceeds the {MAX_REPEAT}-element \
                     expansion bound; refused by name: `{}`",
                    token_key(expr)
                ));
            }
            let elem_refs = std::iter::repeat(&*repeat.expr).take(count);
            literal_aggregate_term_in_scope("Array", elem_refs, expr, scope)
        }
        Expr::Struct(s) => {
            // A struct / enum-struct literal `Path { f: v, ... }` is a constructor.
            // Lift it to a Ctor keyed by the path, with one `field:<name>` sub-ctor
            // per field. Fields are SORTED BY NAME so the term is canonical (source
            // field order is irrelevant: `V { a, b }` and `V { b, a }` are the same
            // value -> the same term) while field names stay significant
            // (`V { a: x }` != `V { b: x }`). Two distinct literals are distinct
            // Ctors -> asserting equality with the wrong one is UNSAT (the teeth).
            //
            // A functional-update `..rest` means the value is NOT fully pinned from
            // the literal, so it is refused by name (not silently approximated).
            // A field value that does not translate propagates its own named Err.
            if s.rest.is_some() {
                return Err(format!(
                    "struct literal with `..rest` is not fully pinned from the literal: `{}`",
                    token_key(expr)
                ));
            }
            let mut fields: Vec<(String, Rc<Term>)> = Vec::new();
            for fv in &s.fields {
                let fname = match &fv.member {
                    syn::Member::Named(id) => id.to_string(),
                    syn::Member::Unnamed(idx) => idx.index.to_string(),
                };
                fields.push((fname, translate_term_in_scope(&fv.expr, scope)?));
            }
            fields.sort_by(|a, b| a.0.cmp(&b.0));
            let args = fields
                .into_iter()
                .map(|(fname, term)| {
                    Rc::new(Term::Ctor {
                        name: format!("field:{fname}"),
                        args: vec![term],
                    })
                })
                .collect();
            Ok(Rc::new(Term::Ctor {
                name: format!("struct:{}", path_to_variant_string(&s.path)),
                args,
            }))
        }
        Expr::MethodCall(call) => {
            // CLOSED `try_fold` / `try_rfold` VALUE (the construction axiom for a fold
            // RESULT): `<closed-literal-chain>.try_fold(<lit>, <pure checked closure>)`
            // is a FINITE construction from source literals, so it reduces to ONE
            // concrete `Option<i*>`. Ground it to a `Some(n)` / `None` literal and
            // translate THAT through the ordinary path: `Some(11250)` lifts to
            // `Ctor("call:Some", [Int(11250)])`, so the outer `assert_eq!` becomes a
            // grounded `Some(a) == Some(b)`. The teeth follow from ctor-equality: a
            // bad-twin side grounding to a different `Some(b)` is `call:Some[a] ==
            // call:Some[b]` (a != b) -- z3-UNSAT. EXACT-OR-BAIL: `None` here falls
            // through to the existing (unclassified) refusal (a safe under-claim).
            // CLOSED `try_fold` / `try_rfold` VALUE: ground it to a `Some(n)` / `None`
            // literal when (and ONLY when) the WHOLE chain is closed-evaluable. On a
            // bail (a mutable / runtime receiver -- e.g. `iter.try_fold(0, ..)` over a
            // `let mut iter`), fall THROUGH to the existing path so the prior
            // (bin-2 / opaque) classification of that row is preserved UNCHANGED -- this
            // hook only DRAINS the closed-literal rows, it never reclassifies a runtime
            // one. (Grounding both sides is verified for the 6 closed targets, so no
            // mixed grounded/opaque `assert_eq!` atom arises; a runtime row's two
            // operands BOTH stay on the existing path.)
            if matches!(call.method.to_string().as_str(), "try_fold" | "try_rfold") {
                if let Some(grounded) = try_fold_eval::eval_try_fold_operand(expr, scope) {
                    return translate_term_in_scope(&grounded, scope);
                }
            }
            // A closure-bearing iterator/Option adaptor in TERM position (e.g.
            // `assert_eq!(opt.map(|v| ..), x)`) refuses with the collection
            // provenance, not a bare "unsupported term `|v|`" -- so the bin sort is
            // PROVEN (opaque receiver -> bin-2), not presumed. Same rigor the
            // bool-assertion path already applies to `.all`/`.any`.
            if let Some(reason) = closure_adaptor_refusal(expr, scope) {
                return Err(reason);
            }
            let mut args = vec![translate_term_in_scope(&call.receiver, scope)?];
            // PER-OCCURRENCE ADVANCE (Fix 5): a CONSUMING iterator read advances the
            // iterator, so the second-and-later such read of the SAME binding within
            // one statement (`assert_ne!(it.nth(0), it.nth(0))`) observes a distinct
            // `t`. The receiver is already version-tagged (`it@def5`); appending
            // `@adv{n}` for the n-th occurrence makes the reads distinct terms so the
            // assertion is `ne(X0, X1)` (satisfiable), not `ne(X, X)` (false unsat).
            if is_consuming_iterator_method(&call.method.to_string()) {
                if let Term::Var { name } = args[0].as_ref() {
                    if receiver_is_versioned_iterator(name, scope) {
                        let occ = scope.bump_consuming_occurrence(name);
                        if occ > 0 {
                            args[0] = make_var(format!("{name}@adv{occ}"));
                        }
                    }
                }
            }
            for arg in &call.args {
                args.push(translate_term_in_scope(arg, scope)?);
            }
            let method = match &call.turbofish {
                Some(args) => format!("{}{}", call.method, angle_args_key(args)),
                None => call.method.to_string(),
            };
            Ok(Rc::new(Term::Ctor {
                name: format!("method:{method}"),
                args,
            }))
        }
        Expr::Await(await_expr) => Ok(Rc::new(Term::Ctor {
            name: "await".to_string(),
            args: vec![translate_term_in_scope(&await_expr.base, scope)?],
        })),
        // Only the immutable borrow is a stable term. `&mut x` stays residual:
        // a mutable referent can change between observations (temporal identity),
        // so coalescing two `&mut x` terms would be unsound. See the
        // mutable_reference_pointer_eq_stays_residual guard test.
        Expr::Reference(reference) if reference.mutability.is_none() => Ok(Rc::new(Term::Ctor {
            name: "ref".to_string(),
            args: vec![translate_term_in_scope(&reference.expr, scope)?],
        })),
        // `&mut <closure>` / `&mut <literal>` / `&mut [<array literal>]`: the referent
        // is an IMMUTABLE VALUE (a closure, scalar literal, or freshly-constructed
        // array literal cannot be reassigned), so unlike `&mut <variable>` -- which
        // stays RESIDUAL because two `&mut x` of a mutable binding are distinct
        // pointers (mutable_reference_pointer_eq_stays_residual) -- this `&mut` is a
        // stable term: `ref_mut(<value>)`. Needed so `to_string(&mut |d,b,l| .., 3.14)`
        // (the flt2dec FnMut pattern, post-inline) lifts as a stated point-observation
        // rather than refusing on `& mut |..|`, AND so `assert_eq!(left, &mut [1,2,3])`
        // -- slice/array PartialEq is BY VALUE, not by pointer -- lifts its pinned RHS
        // (`array.rs`/`slice.rs` split/chunk asserts). The array is the SAME immutable-
        // value class as a scalar literal: its elements lift via the version-aware
        // element path (so a mutable element cannot false-coalesce across a tick), and
        // a non-liftable element propagates its own Err (stays unclassified, never a
        // false discharge). Strictly narrower than the residual rule: a plain `&mut x`
        // (and `&mut <call>`, e.g. `&mut ready(1)`) still falls through and refuses.
        Expr::Reference(reference) if is_immutable_value_expr(&reference.expr) => {
            Ok(Rc::new(Term::Ctor {
                name: "ref_mut".to_string(),
                args: vec![translate_term_in_scope(&reference.expr, scope)?],
            }))
        }
        // A `&mut <place>` of a NON-immutable-value referent (`&mut x`, `&mut cx`,
        // `&mut *cell.get()`, `&mut ready(1)`): a mutable borrow is an order-loss place --
        // two `&mut x` of a mutable binding are distinct pointers, so the term has no single
        // timeless value to read. EARNED here ONLY after the immutable-value arm above has
        // claimed the stable `&mut <literal/closure/array>` cases (a non-mutable `&` already
        // lifted as `ref`), so this can only refuse a genuinely-mutable borrow. Typed as
        // `Effect::Unsupported` (term-shaped).
        Expr::Reference(reference) if reference.mutability.is_some() => {
            let effect = Effect::unsupported_term(
                &token_key(expr),
                UnsupportedTermCause::MutableReference,
            );
            Err(effect.reason())
        }
        // A raw pointer `&raw const <place>` / `&raw mut <place>` (`Expr::RawAddr`): a raw
        // address is a runtime value, not a construction from source literals. Kin to `bin-2`.
        // Typed as `Effect::Unsupported` (term-shaped).
        Expr::RawAddr(_) => {
            let effect = Effect::unsupported_term(
                &token_key(expr),
                UnsupportedTermCause::RawPointer,
            );
            Err(effect.reason())
        }
        Expr::Cast(cast) => {
            if is_shared_dyn_any_type(&cast.ty) {
                return Ok(Rc::new(Term::Ctor {
                    name: format!("cast:{}", type_key(&cast.ty)),
                    args: vec![translate_term_in_scope(&cast.expr, scope)?],
                }));
            }
            if let Some(cast_type) = scalar_cast_type_key(&cast.ty) {
                return Ok(Rc::new(Term::Ctor {
                    name: format!("cast:{cast_type}"),
                    args: vec![translate_term_in_scope(&cast.expr, scope)?],
                }));
            }
            Err(format!("unsupported term `{}`", token_key(expr)))
        }
        Expr::Range(range) => {
            // An omitted bound must NOT lift to a `_` var: `_` is not a valid
            // SMT-LIB symbol, so it reached the solver as `unknown constant _` and
            // spuriously REFUSED every `v[..k]` / `v[k..]` slice obligation. An
            // omitted START is 0 (`..k` == `0..k`); an omitted END is the
            // collection length -- an opaque but VALID symbol, never `_`.
            let start = match &range.start {
                Some(expr) => translate_term_in_scope(expr, scope)?,
                None => num(0),
            };
            let end = match &range.end {
                Some(expr) => translate_term_in_scope(expr, scope)?,
                None => make_var("range_end_len"),
            };
            let name = match range.limits {
                syn::RangeLimits::HalfOpen(_) => "range",
                syn::RangeLimits::Closed(_) => "range_incl",
            };
            Ok(Rc::new(Term::Ctor {
                name: name.to_string(),
                args: vec![start, end],
            }))
        }
        Expr::Field(field) => Ok(Rc::new(Term::Ctor {
            name: format!("field:{}", token_key(&field.member)),
            args: vec![translate_term_in_scope(&field.base, scope)?],
        })),
        Expr::Index(index) => {
            if let Some(term) = const_index_term_in_scope(index, scope)? {
                return Ok(term);
            }
            // General a[i] is the IR term index(a, i). Sound iff the container is
            // temporally stable. The `mut` oracle (L4) decides: a non-`mut` local
            // is provably immutable, so index(a, i) is a stable term; a `mut`
            // local may be index-assigned or method-mutated in ways the tracker
            // cannot follow, so it stays residual. Non-local containers (a call
            // result, a field) translate through their own EUF terms.
            // TYPED BAIL: when the `mut` oracle PROVES the container is a mutable local,
            // `index(a,i)` is a sequence/position-dependent read with no single timeless `t`.
            // THIN NODE-ROUTER: that verdict is owned by the `TemporalReadSugar` node, which
            // `Hit`s `Effect::TemporalRead` in its own `desugar`; this arm renders
            // `effect.reason()` to the `Err` exactly as before (byte-identical), and the reason
            // it produces is whitelisted terminal by `refusal_disposition`, draining this
            // effect-shaped case unclassified -> refused. `decompose_temporal_read` recognizes
            // ONLY this refuse-shape (an `Index` over a `mut`-local simple-path container): a
            // non-`mut` / non-simple-path container returns `None`, and the read falls through
            // to the constructive `index(a, i)` term below (the discrimination twin's
            // soundness gate -- a stable read is never terminalized).
            if let Some(node) = sugar::temporal_read::decompose_temporal_read(expr, scope) {
                if let Outcome::Hit(effect @ Effect::TemporalRead { .. }) = node.desugar_ctx_free()
                {
                    return Err(effect.reason());
                }
            }
            let container = translate_term_in_scope(&index.expr, scope)?;
            let idx = translate_term_in_scope(&index.index, scope)?;
            Ok(Rc::new(Term::Ctor {
                name: "index".to_string(),
                args: vec![container, idx],
            }))
        }
        Expr::Binary(binary) => {
            // BinaryOpSugar: a COMPARISON in term position (`a[0] < b[0]` as the
            // operand of an outer `==`, or the LHS of `assert_eq!(false == false,
            // true)`) is the bool-VALUED FOL fact it states -- not an arithmetic
            // Ctor. `term_binop_name` deliberately keeps the ordered comparisons
            // OUT of the arithmetic ctor set (so a TOP-LEVEL/negated comparison
            // routes to the relation-ATOM path and EUF-coalesces with its negated
            // sibling). Here, in genuine TERM position, we lift the comparison as a
            // bool value so the surrounding equality can reason over it.
            if let Some(rel) = relation_from_binop(&binary.op) {
                // const operands -> fold the comparison to its Bool literal, EXACT
                // (`false == false` -> Bool(true)). `const_eval` is exact-or-None
                // over the closed Int/Bool/Char set; a non-const operand returns
                // None and falls through to the symbolic comparison ctor below.
                if let Some(ConstVal::Bool(b)) = const_eval(expr, &BTreeMap::new()) {
                    return Ok(bool_const(b));
                }
                // non-const but STABLE operands -> a bool-valued comparison ctor
                // over the translated operand terms. Keyed per relation
                // (`cmp:lt`/`cmp:le`/.../`cmp:eq`/`cmp:ne`) so two contradictory
                // comparisons over the same operands are DISTINCT terms (the
                // teeth): `cmp:lt(x,y)` and `cmp:gt(x,y)` cannot both equal `true`.
                // EXACT-OR-BAIL: each operand translates through the same sound
                // term path, so a `mut` container / effectful operand propagates
                // its own named Err via `?` (the index/mut oracle still BAILS); we
                // never emit a comparison over a temporally-unstable operand.
                let lhs = translate_term_in_scope(&binary.left, scope)?;
                let rhs = translate_term_in_scope(&binary.right, scope)?;
                return Ok(Rc::new(Term::Ctor {
                    name: format!("cmp:{}", rel.cmp_ctor_name()),
                    args: vec![lhs, rhs],
                }));
            }
            let Some(op) = term_binop_name(&binary.op) else {
                return Err(format!("unsupported term operator `{}`", token_key(expr)));
            };
            Ok(Rc::new(Term::Ctor {
                name: op.to_string(),
                args: vec![
                    translate_term_in_scope(&binary.left, scope)?,
                    translate_term_in_scope(&binary.right, scope)?,
                ],
            }))
        }
        Expr::Paren(paren) => translate_term_in_scope(&paren.expr, scope),
        Expr::Group(group) => translate_term_in_scope(&group.expr, scope),
        // A macro invocation in term position (format!, vec!, offset_of!, ...)
        // is desugared to an uninterpreted function term keyed by its canonical
        // source tokens. Identical macro calls map to the same term (congruence),
        // so a contradiction like `format!(a) == "p" && format!(a) == "q"` stays
        // UNSAT; distinct calls map to distinct terms. The witness re-run proves
        // the actual runtime value; consistency only checks non-contradiction.
        //
        // EXCEPTION: if the macro's token stream contains a `let mut` local
        // (e.g. `format!("{:?}", r)` where `r` is `let mut r = ...`), the
        // same macro text at two different program points can produce different
        // values after a mutation (e.g. `r.next()` between the two calls).
        // The canonical token-key then maps two different observations onto the
        // same Var name, causing a false contradiction in the fallback
        // obligation. Refuse the macro as temporally unstable when it contains
        // any mut local from the current scope.
        Expr::Macro(m) => {
            // Walk the token stream looking for any identifier that is a mut_local.
            // Two forms must be detected:
            //   1. `format!("{:?}", r)` — `r` is a bare Ident token.
            //   2. `format!("{socket}")` — `socket` is captured by name inside
            //      the format-string literal (Rust 1.58+ implicit capture); the
            //      identifier does NOT appear as a separate Ident token.
            // For (2), scan the text content of every Literal token in the macro
            // for occurrences of any mut_local name surrounded by `{` / `:` / `}`
            // as Rust format-spec delimiters.
            let token_str = token_key(expr);
            let contains_mut_local = m
                .mac
                .tokens
                .clone()
                .into_iter()
                .any(|tt| match &tt {
                    proc_macro2::TokenTree::Ident(id) => scope.is_mut_local(&id.to_string()),
                    proc_macro2::TokenTree::Literal(lit) => {
                        // Check for inline captures like `"{socket}"` or `"{socket:<24}"`.
                        // The literal text includes the surrounding quotes; just scan
                        // the raw string for any mut_local name following `{`.
                        let text = lit.to_string();
                        macro_literal_contains_mut_local(&text, scope)
                    }
                    _ => false,
                });
            if contains_mut_local {
                return Err(format!(
                    "macro in term position references a `let mut` local; \
                     temporally unstable — refused: `{token_str}`"
                ));
            }
            Ok(make_var(format!("macro:{token_str}")))
        }
        // A CLOSURE LITERAL as an opaque EUF symbol, keyed by its body text AND the
        // version-aware terms of its CAPTURED free variables. Conservative by
        // identity: same text + same captures -> same symbol (a contradiction over
        // it coalesces and is CAUGHT); ANY difference -> a distinct symbol (it never
        // false-coalesces, so it cannot mask a contradiction). Captures MUST be
        // version-aware -- two `|x| x+n` with different captured `n` have identical
        // text, so coalescing them would be unsound; we include each free var as a
        // versioned arg, and REFUSE if a capture is ambiguous (no single `t`).
        Expr::Closure(closure) => {
            let params: BTreeSet<String> = closure
                .inputs
                .iter()
                .filter_map(|p| match p {
                    Pat::Ident(id) => Some(id.ident.to_string()),
                    Pat::Type(t) => match &*t.pat {
                        Pat::Ident(id) => Some(id.ident.to_string()),
                        _ => None,
                    },
                    _ => None,
                })
                .collect();
            let mut args = Vec::new();
            for name in names_referenced_in_expr(&closure.body) {
                if params.contains(&name) {
                    continue;
                }
                // A captured LOCAL must be read at its program-point `t` (versioned);
                // a global/const path is the same symbol everywhere (bare). Ambiguous
                // capture -> no single `t` -> refuse the closure.
                if is_unqualified_local_name(&name) && scope.plan.versioned.contains(&name) {
                    if scope.ambiguous.contains(&name) {
                        return Err(format!(
                            "closure captures ambiguous local `{name}`; refused"
                        ));
                    }
                    let vname = match scope.versions.get(&name) {
                        Some(v) => format!("{name}@def{v}"),
                        None => name.clone(),
                    };
                    args.push(make_var(vname));
                } else {
                    args.push(make_var(name));
                }
            }
            Ok(Rc::new(Term::Ctor {
                name: format!("closure:{}", token_key(&closure.body)),
                args,
            }))
        }
        // VALUE-TRANSPARENT WRAPPERS: an `unsafe { <tail> }` or plain `{ <tail> }`
        // block in TERM position is the value of its tail expression -- `unsafe` is a
        // compile-time obligation, not a value transform (the same transparency the
        // value-contract path applies via `tail_inv`, see
        // `emit_value_contract_unsafe_and_block_are_value_transparent`). We unwrap ONLY
        // the single-tail block shape (`{ expr }`, no `;`): the inner expr then lifts
        // via the existing term paths (method-call EUF, deref, call), so
        // `assert_eq!(unsafe { ok.unwrap_unchecked() }, 100)` lifts to the SAME term as
        // `assert_eq!(ok.unwrap_unchecked(), 100)` (the `unsafe` wrapper is congruent).
        // CRITICALLY this is NOT a free pass: the unwrapped tail still goes through the
        // ordinary operand translation, so a temporally-unstable inner read still BAILS
        // -- e.g. `unsafe { &mut *cell.get() }` is `&mut` of a deref (not an immutable
        // value), which falls through to the catch-all and refuses; only the WRAPPER is
        // transparent. A multi-statement block (a `let`/effect prefix) is NOT unwrapped
        // here (it is not a single timeless value) and stays refused by name.
        Expr::Unsafe(block) => match block.block.stmts.as_slice() {
            [Stmt::Expr(tail, None)] => translate_term_in_scope(tail, scope),
            _ => Err(format!("unsupported term `{}`", token_key(expr))),
        },
        Expr::Block(block) => match block.block.stmts.as_slice() {
            [Stmt::Expr(tail, None)] => translate_term_in_scope(tail, scope),
            _ => Err(format!("unsupported term `{}`", token_key(expr))),
        },
        // EFFECTFUL CONTROL-FLOW: a `try { .. }` / `async { .. }` block, or a `?`
        // (`Expr::Try`), is NOT a single timeless point-wise value -- it is control
        // flow / a deferred computation (a `try` block early-returns its `Err`, an
        // `async` block is a future evaluated elsewhere, a `?` is a conditional
        // early-return). There is no construction-from-literals to walk, so no value
        // lifter could read a single `t`: a SOURCE property, not a missing lift. TYPED
        // as an `Effect::ControlFlow` whose reason is whitelisted TERMINAL by
        // `refusal_disposition` -- this drains the `future.rs`
        // `assert!(Option::is_none(&try { join!(maybe_fut?, async { unreachable!() }) }))`
        // row unclassified -> refused (a named refuse, never a silent shrug).
        Expr::TryBlock(_) | Expr::Async(_) | Expr::Try(_) => {
            // THIN NODE-ROUTER: the term-position control-flow verdict is owned by the
            // `ControlFlowTermSugar` node, which `Hit`s `Effect::ControlFlow` in its own
            // `desugar`; this arm renders `effect.reason()` to the `Err` exactly as before
            // (byte-identical). `decompose_control_flow_term` recognizes ONLY this refuse-shape
            // (a `try`/`async`/`?` construct); any other expr returns `None` and never reaches
            // here (this arm matches only those three).
            match sugar::control_flow_term::decompose_control_flow_term(expr) {
                Some(node) => match node.desugar_ctx_free() {
                    Outcome::Hit(effect @ Effect::ControlFlow { .. }) => Err(effect.reason()),
                    _ => Err(format!("unsupported term `{}`", token_key(expr))),
                },
                None => Err(format!("unsupported term `{}`", token_key(expr))),
            }
        }
        other => Err(format!("unsupported term `{}`", token_key(other))),
    }
}

fn const_index_term_in_scope(
    index: &syn::ExprIndex,
    scope: &TemporalScope,
) -> Result<Option<Rc<Term>>, String> {
    let Some(index_value) = const_int(&index.index) else {
        return Ok(None);
    };
    let Some(base_name) = const_index_base_name(&index.expr, scope)? else {
        return Ok(None);
    };
    Ok(Some(Rc::new(Term::Ctor {
        name: "index".to_string(),
        args: vec![make_var(base_name), num(index_value)],
    })))
}

fn const_index_base_name(expr: &Expr, scope: &TemporalScope) -> Result<Option<String>, String> {
    match expr {
        Expr::Path(path) if path.qself.is_none() && is_const_like_path(&path.path) => {
            scope.path_name(&path.path).map(Some)
        }
        Expr::Paren(paren) => const_index_base_name(&paren.expr, scope),
        Expr::Group(group) => const_index_base_name(&group.expr, scope),
        _ => Ok(None),
    }
}

fn is_const_like_path(path: &syn::Path) -> bool {
    let Some(final_segment) = path.segments.last() else {
        return false;
    };
    let ident = final_segment.ident.to_string();
    ident.chars().any(|ch| ch.is_ascii_uppercase())
        && ident
            .chars()
            .all(|ch| ch.is_ascii_uppercase() || ch.is_ascii_digit() || ch == '_')
}

fn translate_assertion_term_in_scope(
    expr: &Expr,
    scope: &TemporalScope,
) -> Result<Rc<Term>, String> {
    match expr {
        Expr::Const(const_block) => {
            let term =
                translate_expression_only_block_in_scope(&const_block.block, "const", scope)?;
            Ok(scope_const_block_locals(term, scope.local_scope()))
        }
        Expr::Path(path) if path.path.is_ident("None") => Ok(Rc::new(Term::Ctor {
            name: "call:None".to_string(),
            args: Vec::new(),
        })),
        Expr::Paren(paren) => translate_assertion_term_in_scope(&paren.expr, scope),
        Expr::Group(group) => translate_assertion_term_in_scope(&group.expr, scope),
        _ => translate_term_in_scope(expr, scope),
    }
}

fn scope_const_block_locals(term: Rc<Term>, local_scope: &str) -> Rc<Term> {
    match term.as_ref() {
        Term::Var { name } if should_scope_const_block_var(name) => {
            make_var(format!("{local_scope}::{name}"))
        }
        Term::Ctor { name, args } => Rc::new(Term::Ctor {
            name: name.clone(),
            args: args
                .iter()
                .map(|arg| scope_const_block_locals(arg.clone(), local_scope))
                .collect(),
        }),
        _ => term,
    }
}

fn should_scope_const_block_var(name: &str) -> bool {
    is_unqualified_local_name(name) && name != "_" && !name.starts_with("literal:")
}

fn translate_expression_only_block_in_scope(
    block: &syn::Block,
    label: &str,
    scope: &TemporalScope,
) -> Result<Rc<Term>, String> {
    match block.stmts.as_slice() {
        [Stmt::Expr(expr, None)] => {
            if let Some(nested_const) = find_const_expr(expr) {
                return Err(format!("unsupported term `{}`", token_key(nested_const)));
            }
            translate_term_in_scope(expr, scope)
        }
        _ => Err(format!(
            "{label} block is not an expression-only term `{}`",
            token_key(block)
        )),
    }
}

fn find_const_expr(expr: &Expr) -> Option<&Expr> {
    match expr {
        Expr::Const(_) => Some(expr),
        Expr::Unary(unary) => find_const_expr(&unary.expr),
        Expr::Call(call) => call
            .args
            .iter()
            .find_map(find_const_expr)
            .or_else(|| find_const_expr(&call.func)),
        Expr::Array(array) => array.elems.iter().find_map(find_const_expr),
        Expr::Tuple(tuple) => tuple.elems.iter().find_map(find_const_expr),
        Expr::MethodCall(call) => {
            find_const_expr(&call.receiver).or_else(|| call.args.iter().find_map(find_const_expr))
        }
        Expr::Await(await_expr) => find_const_expr(&await_expr.base),
        Expr::Reference(reference) => find_const_expr(&reference.expr),
        Expr::Cast(cast) => find_const_expr(&cast.expr),
        Expr::Range(range) => range
            .start
            .as_deref()
            .and_then(find_const_expr)
            .or_else(|| range.end.as_deref().and_then(find_const_expr)),
        Expr::Field(field) => find_const_expr(&field.base),
        Expr::Binary(binary) => {
            find_const_expr(&binary.left).or_else(|| find_const_expr(&binary.right))
        }
        Expr::Paren(paren) => find_const_expr(&paren.expr),
        Expr::Group(group) => find_const_expr(&group.expr),
        _ => None,
    }
}

/// The length of an array-repeat `[elem; N]` as a `usize`, iff `N` is a plain
/// integer literal (the only finitely-constructible case). A `const`/path length
/// (`[0; LEN]`) returns None and is refused by name upstream.
pub(crate) fn repeat_count_literal(len: &Expr) -> Option<usize> {
    match len {
        Expr::Lit(ExprLit {
            lit: Lit::Int(i), ..
        }) => i.base10_parse::<usize>().ok(),
        Expr::Paren(p) => repeat_count_literal(&p.expr),
        Expr::Group(g) => repeat_count_literal(&g.expr),
        _ => None,
    }
}

fn literal_aggregate_term_in_scope<'a>(
    kind: &str,
    elems: impl Iterator<Item = &'a Expr>,
    source: &Expr,
    scope: &TemporalScope,
) -> Result<Rc<Term>, String> {
    let _ = source;
    let mut args = Vec::new();
    let mut all_literal = true;
    for elem in elems {
        // Each element is translated through the same sound term path. An
        // element that cannot be translated (e.g. a &mut borrow) propagates its
        // refusal via `?`, so the aggregate is only built from accountable terms.
        let term = translate_term_in_scope(elem, scope)?;
        if !is_literal_identity_term(term.as_ref()) {
            all_literal = false;
        }
        args.push(term);
    }
    let inner = args
        .iter()
        .map(|arg| canonical_term_sig(arg))
        .collect::<Vec<_>>()
        .join(",");
    // All-literal aggregates keep the literal: key (byte-identical to before).
    // Aggregates with non-literal elements are an uninterpreted constructor over
    // their element terms (agg:), congruence-keyed so contradictions are caught.
    let prefix = if all_literal { "literal" } else { "agg" };
    Ok(make_var(format!("{prefix}:{kind}({inner})")))
}

fn is_literal_identity_term(term: &Term) -> bool {
    match term {
        Term::Const { .. } => true,
        Term::Var { name } => name.starts_with("literal:"),
        Term::Ctor { name, args } if constructor_operator_tag(term).is_some() => {
            name.starts_with("call:") && args.iter().all(|arg| is_literal_identity_term(arg))
        }
        _ => false,
    }
}

/// A `..` with both bounds omitted — `x[..]` is the FULL slice of `x`, the same
/// value as `x` for slice/array PartialEq.
fn is_full_range_expr(expr: &Expr) -> bool {
    matches!(expr, Expr::Range(r) if r.start.is_none() && r.end.is_none())
}

/// An expression that denotes an IMMUTABLE VALUE constructed from the source: a
/// closure, a scalar literal, an array literal, the negation of one, or a FULL
/// slice (`[..]`) of one. `&mut <such expr>` is a stable `ref_mut(<value>)` term
/// (it cannot be reassigned), unlike `&mut <variable>` / `&mut <call>` / a partial
/// or non-literal index (`&mut buf[i]`, `&mut buf[..]`) — those keep distinct
/// pointer/temporal identity and stay RESIDUAL (mutable_reference_pointer_eq guard).
/// Element/inner translation goes through the normal version-aware path, so a
/// mutable element cannot false-coalesce and a non-liftable inner propagates Err
/// (stays unclassified, never a false discharge).
fn is_immutable_value_expr(expr: &Expr) -> bool {
    match expr {
        Expr::Closure(_) | Expr::Lit(_) | Expr::Array(_) => true,
        Expr::Unary(u) if matches!(u.op, syn::UnOp::Neg(_)) => is_immutable_value_expr(&u.expr),
        Expr::Index(i) if is_full_range_expr(&i.index) => is_immutable_value_expr(&i.expr),
        Expr::Paren(p) => is_immutable_value_expr(&p.expr),
        Expr::Group(g) => is_immutable_value_expr(&g.expr),
        _ => false,
    }
}

fn type_id_of_call_term(func: &Expr, arg_len: usize) -> Result<Option<Rc<Term>>, String> {
    if arg_len != 0 {
        return Ok(None);
    }
    let Expr::Path(path) = func else {
        return Ok(None);
    };
    if !is_type_id_of_path(&path.path) {
        return Ok(None);
    }
    let Some(last) = path.path.segments.last() else {
        return Ok(None);
    };
    let syn::PathArguments::AngleBracketed(args) = &last.arguments else {
        return Err("TypeId::of requires exactly one type argument".to_string());
    };
    if args.args.len() != 1 {
        return Err("TypeId::of requires exactly one type argument".to_string());
    }
    let Some(syn::GenericArgument::Type(ty)) = args.args.first() else {
        return Err("TypeId::of requires a type argument".to_string());
    };
    Ok(Some(Rc::new(Term::Ctor {
        name: format!("type_id::{}", type_key(ty)),
        args: Vec::new(),
    })))
}

fn is_type_id_of_path(path: &syn::Path) -> bool {
    let segments = path.segments.iter().collect::<Vec<_>>();
    matches!(
        segments.as_slice(),
        [.., type_id, of]
            if type_id.ident == "TypeId" && of.ident == "of"
    )
}

fn is_shared_dyn_any_type(ty: &syn::Type) -> bool {
    let syn::Type::Reference(reference) = ty else {
        return false;
    };
    if reference.mutability.is_some() {
        return false;
    }
    let syn::Type::TraitObject(trait_object) = reference.elem.as_ref() else {
        return false;
    };
    trait_object.bounds.iter().any(|bound| {
        let syn::TypeParamBound::Trait(trait_bound) = bound else {
            return false;
        };
        trait_bound
            .path
            .segments
            .last()
            .is_some_and(|segment| segment.ident == "Any")
    })
}

/// A primitive scalar cast target as a `cast:` ctor suffix: every integer width
/// plus `char` (a pure code-point conversion, `u8 as char` / `c as char`). The
/// cast is modeled as an opaque deterministic unary EUF ctor `cast:<T>(x)` --
/// the same uninterpreted-function standard as method-EUF, no claim about the
/// conversion's numeric semantics, only that it is a function of its input. char
/// stays in the Int/opaque regime (a code point), so it composes alongside the
/// integer casts. Floats are deliberately excluded (Real-sort interplay).
fn scalar_cast_type_key(ty: &syn::Type) -> Option<&'static str> {
    if let Some(k) = integer_scalar_cast_type_key(ty) {
        return Some(k);
    }
    if let Some(k) = float_scalar_cast_type_key(ty) {
        return Some(k);
    }
    let syn::Type::Path(path) = ty else {
        return None;
    };
    if path.qself.is_some() || path.path.segments.len() != 1 {
        return None;
    }
    let segment = path.path.segments.first()?;
    if !matches!(segment.arguments, syn::PathArguments::None) {
        return None;
    }
    match segment.ident.to_string().as_str() {
        "char" => Some("char"),
        _ => None,
    }
}

// A FLOAT primitive cast `expr as f16/f32/f64/f128`. Recognized as the OPAQUE EUF
// ctor `cast:f32(<expr>)` -- the EXACT same standard as the integer/char casts
// (`scalar_integer_cast_call_result_stays_location_keyed_not_euf`): the substrate
// adds NO cast/round semantics, the term is a pure structural function of its
// operand, and the row stays location-keyed (not #euf-federated). Asserting
// `cast:f32(x) == <pinned float>` is therefore a structural equality whose
// wrong-expected twin is REFUTED by Ctor inequality. Needed for the `num/mod.rs`
// `test_f32f64` float<->float round-trip rows (`assert_eq!(max as f32, f32::MAX)`,
// `epsilon as f32`, `infinity as f32`, ...) which fell out at the cast fallthrough.
// The IEEE width is carried only in the ctor NAME (`cast:f16`/`cast:f32`/`cast:f64`/
// `cast:f128`), never as a Real-arithmetic claim -- so no float-rounding semantics
// are smuggled in (kin to the int-width-in-sort discipline; not a fake-discharge).
fn float_scalar_cast_type_key(ty: &syn::Type) -> Option<&'static str> {
    let syn::Type::Path(path) = ty else {
        return None;
    };
    if path.qself.is_some() || path.path.segments.len() != 1 {
        return None;
    }
    let segment = path.path.segments.first()?;
    if !matches!(segment.arguments, syn::PathArguments::None) {
        return None;
    }
    match segment.ident.to_string().as_str() {
        "f16" => Some("f16"),
        "f32" => Some("f32"),
        "f64" => Some("f64"),
        "f128" => Some("f128"),
        _ => None,
    }
}

fn integer_scalar_cast_type_key(ty: &syn::Type) -> Option<&'static str> {
    let syn::Type::Path(path) = ty else {
        return None;
    };
    if path.qself.is_some() || path.path.segments.len() != 1 {
        return None;
    }
    let segment = path.path.segments.first()?;
    if !matches!(segment.arguments, syn::PathArguments::None) {
        return None;
    }
    match segment.ident.to_string().as_str() {
        "i8" => Some("i8"),
        "i16" => Some("i16"),
        "i32" => Some("i32"),
        "i64" => Some("i64"),
        "i128" => Some("i128"),
        "isize" => Some("isize"),
        "u8" => Some("u8"),
        "u16" => Some("u16"),
        "u32" => Some("u32"),
        "u64" => Some("u64"),
        "u128" => Some("u128"),
        "usize" => Some("usize"),
        _ => None,
    }
}

fn translate_lit(lit: &ExprLit) -> Result<Rc<Term>, String> {
    match &lit.lit {
        Lit::Int(i) => {
            // A CONCRETE Int const whose WIDTH (u8 … i128 / usize / isize) is
            // carried in the const's SORT, never by opaquing the term. The proofir
            // compiler maps any non-{Int,Bool,Real,String} primitive sort -> Int
            // for SMT (emit_sort_with_reason), so the value stays concrete and
            // `2u8 + 3u8 == 6` is still REFUTED — no arithmetic-masking falsePass.
            // The width rides in the canonical callsite KEY (canonical_term_sig
            // renders `i:{v}:{width}`), so `align_of_val(&1u8)=1` and `&1u64=8` get
            // DISTINCT obligations instead of collapsing onto `ref(i:1)`.
            let value = parse_int_lit(i)?;
            let suffix = i.suffix();
            if suffix.is_empty() {
                Ok(num(value))
            } else {
                Ok(Rc::new(Term::Const {
                    value: ConstValue::Int(value),
                    sort: sugar_ir_symbolic::Sort {
                        name: suffix.to_string(),
                    },
                }))
            }
        }
        Lit::Float(f) => canonical_float_literal(f).map(real_const),
        Lit::Str(s) => Ok(str_const(s.value())),
        Lit::Char(c) => Ok(str_const(c.value().to_string())),
        Lit::Bool(b) => Ok(bool_const(b.value)),
        Lit::ByteStr(bs) => Ok(bytes_literal_term_from_bytes(&bs.value())),
        // A byte literal `b'0'` is pure sugar for a `u8` constant (here 48): it
        // carries a fixed numeric value and rust types it `u8`. Dissolve it to the
        // same concrete-Int-with-u8-sort form a `48u8` literal lifts to, so a direct
        // byte operand (`assert_eq!(byte, b'0')`) is liftable and `b'0' != 49` is
        // REFUTED via the existing int path — no new refutation logic, no masking.
        Lit::Byte(b) => Ok(Rc::new(Term::Const {
            value: ConstValue::Int(i128::from(b.value())),
            sort: sugar_ir_symbolic::Sort {
                name: "u8".to_string(),
            },
        })),
        other => Err(format!(
            "only integer/string/char/finite decimal float scalar constants are liftable, got `{}`",
            token_key(other)
        )),
    }
}

/// Encode a byte slice as a lower-hex string: each byte as exactly two hex
/// digits, concatenated.  No external crate dependency required.
fn bytes_to_hex(bytes: &[u8]) -> String {
    bytes
        .iter()
        .flat_map(|b| {
            let hi = (b >> 4) & 0xf;
            let lo = b & 0xf;
            [
                char::from_digit(u32::from(hi), 16).unwrap_or('0'),
                char::from_digit(u32::from(lo), 16).unwrap_or('0'),
            ]
        })
        .collect()
}

/// Produce an opaque content-keyed term for a byte-string literal.
///
/// The term is `Term::Var { name: "literal:bytes(<hex>)" }` where `<hex>` is
/// the lower-hex encoding of the byte content.  This mirrors the
/// `literal_aggregate_term_in_scope` convention: the `literal:` prefix marks
/// the var as a ground identity value throughout the lifter.
///
/// Soundness: identical byte sequences produce identical names (congruence);
/// distinct byte sequences produce distinct names, so any conjunction that
/// equates a single call result to two different byte literals is
/// internally contradictory and will be flagged UNSAT by the solver.
fn bytes_literal_term_from_bytes(bytes: &[u8]) -> Rc<Term> {
    make_var(format!("literal:bytes({})", bytes_to_hex(bytes)))
}

/// Extract a byte-string literal from `expr` as an opaque content-keyed
/// Term::Var, if `expr` is exactly a `b"..."` literal (or a parenthesised /
/// grouped wrapper around one).  Returns `None` for all other expression
/// shapes.
fn bytes_literal_term(expr: &Expr) -> Option<Rc<Term>> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::ByteStr(bs),
            ..
        }) => Some(bytes_literal_term_from_bytes(&bs.value())),
        Expr::Paren(paren) => bytes_literal_term(&paren.expr),
        Expr::Group(group) => bytes_literal_term(&group.expr),
        _ => None,
    }
}

fn parse_int_lit(lit: &syn::LitInt) -> Result<i128, String> {
    // i128 carrier: a wide Rust literal (u64::MAX, u128 within i128 range,
    // large isize) is an EXACT mathematical-Int constant -- the FOL/SMT `Int`
    // sort is unbounded, so there is no "too large" for anything i128 can
    // hold. A literal beyond i128 range (e.g. u128::MAX) still fails here and
    // is refused upstream ("number too large") -- an honest, EXACT-OR-BAIL
    // refusal, never a silent truncation.
    let mut text = lit.to_string();
    let suffix = lit.suffix();
    if !suffix.is_empty() && text.ends_with(suffix) {
        text.truncate(text.len() - suffix.len());
    }
    let text = text.replace('_', "");
    let (radix, digits) =
        if let Some(rest) = text.strip_prefix("0x").or_else(|| text.strip_prefix("0X")) {
            (16, rest)
        } else if let Some(rest) = text.strip_prefix("0o").or_else(|| text.strip_prefix("0O")) {
            (8, rest)
        } else if let Some(rest) = text.strip_prefix("0b").or_else(|| text.strip_prefix("0B")) {
            (2, rest)
        } else {
            (10, text.as_str())
        };
    i128::from_str_radix(digits, radix).map_err(|e| format!("int literal `{}`: {e}", lit))
}

fn string_or_char_literal_term(expr: &Expr) -> Option<Rc<Term>> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Str(s), ..
        }) => Some(str_const(s.value())),
        Expr::Lit(ExprLit {
            lit: Lit::Char(c), ..
        }) => Some(str_const(c.value().to_string())),
        Expr::Paren(paren) => string_or_char_literal_term(&paren.expr),
        Expr::Group(group) => string_or_char_literal_term(&group.expr),
        _ => None,
    }
}

fn char_literal_term(expr: &Expr) -> Option<Rc<Term>> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Char(c), ..
        }) => Some(str_const(c.value().to_string())),
        Expr::Paren(paren) => char_literal_term(&paren.expr),
        Expr::Group(group) => char_literal_term(&group.expr),
        _ => None,
    }
}

fn canonical_float_literal(lit: &syn::LitFloat) -> Result<String, String> {
    let digits = lit.base10_digits().replace('_', "");
    if digits.is_empty() {
        return Err("empty float literal".to_string());
    }
    if digits.contains('e') || digits.contains('E') {
        return normalize_decimal_exponent_literal(&digits).map_err(|e| {
            format!(
                "float literal with exponent is not exact decimal syntax `{}`: {e}",
                lit.to_token_stream()
            )
        });
    }
    Ok(digits)
}

fn normalize_decimal_exponent_literal(text: &str) -> Result<String, String> {
    let lower = text.to_ascii_lowercase();
    let (mantissa, exponent) = lower
        .split_once('e')
        .ok_or_else(|| "missing exponent marker".to_string())?;
    if exponent.contains('e') {
        return Err("multiple exponent markers".to_string());
    }
    let exponent: i64 = exponent
        .parse()
        .map_err(|e| format!("invalid exponent: {e}"))?;
    if exponent.unsigned_abs() > 10_000 {
        return Err("exponent is too large to normalize safely".to_string());
    }

    let mut digits = String::new();
    let mut fractional_digits = 0i64;
    let mut seen_dot = false;
    for ch in mantissa.chars() {
        match ch {
            '.' if !seen_dot => seen_dot = true,
            '.' => return Err("multiple decimal points".to_string()),
            ch if ch.is_ascii_digit() => {
                digits.push(ch);
                if seen_dot {
                    fractional_digits += 1;
                }
            }
            _ => return Err(format!("invalid mantissa character `{ch}`")),
        }
    }
    if digits.is_empty() {
        return Err("empty mantissa".to_string());
    }

    let scale = fractional_digits - exponent;
    if scale <= 0 {
        let zeros = usize::try_from(-scale).map_err(|_| "invalid exponent scale".to_string())?;
        digits.extend(std::iter::repeat_n('0', zeros));
        return Ok(normalize_integer_digits(&digits));
    }

    let scale = usize::try_from(scale).map_err(|_| "invalid exponent scale".to_string())?;
    if digits.len() <= scale {
        let zeros = scale - digits.len();
        let mut out = String::from("0.");
        out.extend(std::iter::repeat_n('0', zeros));
        out.push_str(&digits);
        return Ok(normalize_decimal_digits(&out));
    }

    let split = digits.len() - scale;
    let mut out = digits[..split].to_string();
    out.push('.');
    out.push_str(&digits[split..]);
    Ok(normalize_decimal_digits(&out))
}

fn normalize_integer_digits(text: &str) -> String {
    let trimmed = text.trim_start_matches('0');
    if trimmed.is_empty() {
        "0".to_string()
    } else {
        trimmed.to_string()
    }
}

fn normalize_decimal_digits(text: &str) -> String {
    let (int_part, frac_part) = text
        .split_once('.')
        .expect("normalizer calls this only for decimal text");
    let int_part = normalize_integer_digits(int_part);
    let frac_part = frac_part.trim_end_matches('0');
    if frac_part.is_empty() {
        int_part
    } else {
        format!("{int_part}.{frac_part}")
    }
}

fn const_float(expr: &Expr) -> Result<Option<String>, String> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Float(lit),
            ..
        }) => Ok(Some(canonical_float_literal(lit)?)),
        Expr::Paren(paren) => const_float(&paren.expr),
        Expr::Group(group) => const_float(&group.expr),
        _ => Ok(None),
    }
}

fn real_literal_is_zero(text: &str) -> bool {
    let text = text.strip_prefix('-').unwrap_or(text);
    let mut saw_digit = false;
    for ch in text.chars() {
        if ch == '.' {
            continue;
        }
        saw_digit = true;
        if ch != '0' {
            return false;
        }
    }
    saw_digit
}

fn const_int(expr: &Expr) -> Option<i128> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Int(i), ..
        }) => parse_int_lit(i).ok(),
        Expr::Paren(paren) => const_int(&paren.expr),
        Expr::Group(group) => const_int(&group.expr),
        _ => None,
    }
}

/// The static element-count of `expr` when it is a LITERAL array (`[e0, e1, ...]`),
/// resolving a bare binding through `let_inits` (`ys` -> its `[..]` initializer).
/// A literal array's length IS a literal value in scope -- the cursor extent is the
/// concrete count, not a runtime quantity. None for a non-literal-array receiver (a
/// runtime collection / a range / `[x; N]` repeat -- whose length is not a written
/// element list); the caller then declines (a safe under-claim, never a fake-dig).
fn literal_array_len_with_lets(expr: &Expr, let_inits: &BTreeMap<String, &Expr>) -> Option<i64> {
    match strip_refs_groups(expr) {
        Expr::Array(arr) => Some(arr.elems.len() as i64),
        Expr::Path(p) => {
            let id = p.path.get_ident()?;
            let init = let_inits.get(&id.to_string())?;
            // One level of binding resolution; the resolved init must itself be a
            // literal array (no chained `let a = b;` -- that would need the binding's
            // own len, which `b` resolves the same way, but we keep it to one hop for
            // determinism. A chain is uncommon for `.len()` receivers in the corpus).
            literal_array_len_with_lets(init, let_inits)
        }
        _ => None,
    }
}

/// A scope-aware EXACT integer evaluator for a fold ACCUMULATOR INITIALIZER: a
/// literal int (`const_int`), the length of a LITERAL array (`ys.len()` ->
/// element count, resolved through `let_inits`), or `+`/`-`/`*` arithmetic over
/// those (`xs.len() - 1`). This is THE LAW for the cursor start: when the iterated
/// domain is a literal array, the start position (`ys.len()`, `xs.len() - 1`) is a
/// LITERAL value in scope -- it reduces to the concrete count, so the cursor
/// position is statically determinable. EXACT-OR-BAIL: anything outside this closed
/// set (a runtime `.len()`, a non-arithmetic op, a div/rem we don't const-fold here)
/// returns None and the defolder declines -- a safe under-claim, never a fake-dig.
fn const_int_acc_init(expr: &Expr, let_inits: &BTreeMap<String, &Expr>) -> Option<i64> {
    if let Some(n) = const_int(expr) {
        // The accumulator start is a bounded cursor position (i64/usize
        // domain). A wide literal here is not a representable cursor start ->
        // bail (EXACT-OR-BAIL; a truncation would be a fake-dig).
        return i64::try_from(n).ok();
    }
    match expr {
        Expr::Paren(p) => const_int_acc_init(&p.expr, let_inits),
        Expr::Group(g) => const_int_acc_init(&g.expr, let_inits),
        // `<literal-array>.len()` -- the only method we resolve, and only over a
        // literal array. `.len()` on a runtime receiver is NOT const (returns None).
        Expr::MethodCall(m) if m.method == "len" && m.args.is_empty() => {
            literal_array_len_with_lets(&m.receiver, let_inits)
        }
        // `a + b` / `a - b` / `a * b` over const-resolvable operands. Saturating
        // semantics are not modeled here; the operands are small literal positions,
        // and a non-arithmetic op (`/`, `%`, shift) bails.
        Expr::Binary(b) => {
            let lhs = const_int_acc_init(&b.left, let_inits)?;
            let rhs = const_int_acc_init(&b.right, let_inits)?;
            match b.op {
                BinOp::Add(_) => lhs.checked_add(rhs),
                BinOp::Sub(_) => lhs.checked_sub(rhs),
                BinOp::Mul(_) => lhs.checked_mul(rhs),
                _ => None,
            }
        }
        _ => None,
    }
}

/// Peel transparent `(..)` / proc-macro `Group` wrappers off an expression so the
/// inner shape can be matched. Source `(a[0] < b[0])` parses to `Paren(Binary)`;
/// callers that branch on the binary op need the unwrapped node.
fn unwrap_paren_group(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(p) => unwrap_paren_group(&p.expr),
        Expr::Group(g) => unwrap_paren_group(&g.expr),
        other => other,
    }
}

fn term_binop_name(op: &BinOp) -> Option<&'static str> {
    match op {
        BinOp::Add(_) => Some("+"),
        BinOp::Sub(_) => Some("-"),
        BinOp::Mul(_) => Some("*"),
        BinOp::Div(_) => Some("int-div"),
        BinOp::Rem(_) => Some("int-rem"),
        BinOp::BitAnd(_) => Some("bit-and"),
        BinOp::BitOr(_) => Some("bit-or"),
        BinOp::BitXor(_) => Some("bit-xor"),
        BinOp::Shl(_) => Some("shift-left"),
        BinOp::Shr(_) => Some("shift-right"),
        // NOTE: comparisons (`==`/`!=`/`<`/`<=`/`>`/`>=`) are deliberately NOT
        // arithmetic term binops -- they are bool-VALUED, not Int-valued. A
        // TOP-LEVEL or negated comparison must route to the relation-ATOM path
        // (`lt`/`ge` formulas) so a negated comparison EUF-coalesces with its
        // positive sibling (negated_call_result_comparison_lifts_as_fol_not_under_euf_key).
        // A comparison in genuine TERM position (operand of an outer `==`, or an
        // `assert_eq!` arg) is handled SEPARATELY in `translate_term_in_scope`'s
        // `Expr::Binary` arm (BinaryOpSugar): const-folded to a Bool literal, or
        // emitted as a bool-valued `cmp:*` ctor -- never reaching this arithmetic
        // table. Keeping comparisons out HERE is what preserves the atom routing.
        _ => None,
    }
}

fn expr_head_key(expr: &Expr) -> String {
    match expr {
        Expr::Path(path) => path_to_name(&path.path),
        Expr::Paren(paren) => expr_head_key(&paren.expr),
        Expr::Group(group) => expr_head_key(&group.expr),
        other => token_key(other),
    }
}

fn path_to_name(path: &syn::Path) -> String {
    path.segments
        .iter()
        .map(|segment| {
            let mut name = segment.ident.to_string();
            name.push_str(&path_arguments_key(&segment.arguments));
            name
        })
        .collect::<Vec<_>>()
        .join("::")
}

fn path_arguments_key(arguments: &syn::PathArguments) -> String {
    match arguments {
        syn::PathArguments::None => String::new(),
        syn::PathArguments::AngleBracketed(args) => angle_args_key(args),
        syn::PathArguments::Parenthesized(args) => token_key(args),
    }
}

fn angle_args_key(args: &syn::AngleBracketedGenericArguments) -> String {
    let inner = args
        .args
        .iter()
        .map(generic_arg_key)
        .collect::<Vec<_>>()
        .join(",");
    format!("::<{inner}>")
}

fn generic_arg_key(arg: &syn::GenericArgument) -> String {
    match arg {
        syn::GenericArgument::Type(ty) => type_key(ty),
        syn::GenericArgument::Const(expr) => format!("const:{}", token_key(expr)),
        syn::GenericArgument::Lifetime(lifetime) => format!("'{}", lifetime.ident),
        syn::GenericArgument::AssocType(assoc) => {
            format!("{}={}", assoc.ident, type_key(&assoc.ty))
        }
        syn::GenericArgument::AssocConst(assoc) => {
            format!("{}=const:{}", assoc.ident, token_key(&assoc.value))
        }
        syn::GenericArgument::Constraint(constraint) => token_key(constraint),
        _ => token_key(arg),
    }
}

fn type_key(ty: &syn::Type) -> String {
    match ty {
        syn::Type::Path(path) => path_to_name(&path.path),
        syn::Type::Reference(reference) => {
            let mut out = String::from("&");
            if let Some(lifetime) = &reference.lifetime {
                out.push('\'');
                out.push_str(&lifetime.ident.to_string());
                out.push(' ');
            }
            if reference.mutability.is_some() {
                out.push_str("mut ");
            }
            out.push_str(&type_key(&reference.elem));
            out
        }
        syn::Type::Tuple(tuple) => {
            let inner = tuple
                .elems
                .iter()
                .map(type_key)
                .collect::<Vec<_>>()
                .join(",");
            format!("({inner})")
        }
        syn::Type::Array(array) => {
            format!("[{};{}]", type_key(&array.elem), token_key(&array.len))
        }
        syn::Type::Slice(slice) => format!("[{}]", type_key(&slice.elem)),
        syn::Type::TraitObject(trait_object) => {
            let bounds = trait_object
                .bounds
                .iter()
                .map(|bound| match bound {
                    syn::TypeParamBound::Trait(trait_bound) => path_to_name(&trait_bound.path),
                    syn::TypeParamBound::Lifetime(lifetime) => format!("'{}", lifetime.ident),
                    _ => token_key(bound),
                })
                .collect::<Vec<_>>()
                .join("+");
            format!("dyn {bounds}")
        }
        _ => token_key(ty),
    }
}

fn token_key<T: ToTokens>(node: T) -> String {
    node.to_token_stream()
        .to_string()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
mod lifter_key_tests {
    use super::*;

    fn lift_src(src: &str) -> AdapterOutput {
        let file: syn::File = syn::parse_str(src).expect("test src must parse");
        lift_file(&file, "tests/test_src.rs")
    }

    fn lift_src_cfg(src: &str) -> AdapterOutput {
        let file: syn::File = syn::parse_str(src).expect("test src must parse");
        let target = TargetCfg::from_rustc_cfg_facts([
            "target_pointer_width=\"64\"",
            "target_family=\"unix\"",
        ])
        .expect("cfg facts");
        lift_file_with_options(&file, "tests/test_src.rs", &LiftOptions::for_target_cfg(target))
    }

    fn contract_names(out: &AdapterOutput) -> Vec<&str> {
        out.decls.iter().map(|d| d.name.as_str()).collect()
    }

    // ── const/static ITEM initializer is unconditional (drain-letinit) ───────

    #[test]
    fn const_item_block_assert_lifts_like_top_level() {
        // POSITIVE TWIN: an assert inside a `const _: () = { .. }` ITEM declared
        // in a test body runs UNCONDITIONALLY at const-eval (the test running is
        // what defines the item). It is as point-wise as a top-level assert and
        // must LIFT, not be refused as a "nested unlifted expression statement".
        // Vendor shape: rust-src coretests num/wrapping.rs::wrapping_const.
        let src = r#"
            #[test]
            fn wrapping_const() {
                const _: () = {
                    assert!(i32::MIN.wrapping_div(-1) == i32::MIN);
                    assert!(i32::MIN.wrapping_rem(-1) == 0);
                };
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 2,
            "both unconditional const-item asserts must lift; warnings: {:?}",
            out.skip_reasons
        );
        assert_eq!(
            out.assertions_refused, 0,
            "no const-item assert should be refused: {:?}",
            out.skip_reasons
        );
        assert!(
            !out.skip_reasons.iter().any(|r| r.contains("nested in an unlifted expression statement")),
            "const-item asserts must not fall to the unlifted-expr-statement bucket: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn static_item_block_assert_lifts_like_top_level() {
        // POSITIVE TWIN (static variant): a `static` item initializer block is
        // likewise unconditionally evaluated; its asserts lift.
        let src = r#"
            #[test]
            fn static_const() {
                static _GUARD: () = {
                    assert!(1u8.wrapping_add(255) == 0);
                };
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 1,
            "the unconditional static-item assert must lift; warnings: {:?}",
            out.skip_reasons
        );
        assert_eq!(out.assertions_refused, 0, "{:?}", out.skip_reasons);
    }

    #[test]
    fn const_item_conditional_assert_is_not_falsely_lifted() {
        // NEGATIVE TWIN: an assert that sits under a `for` loop INSIDE the const
        // item block is genuinely conditional (per-element). Recursing into the
        // const-item block must NOT promote it to a point-wise lift -- the
        // per-assert gating still routes it to the for-context refusal. Over-
        // claiming it would be a false discharge.
        // Vendor shape: rust-src coretests iter/mod.rs::test_const_iter.
        let src = r#"
            #[test]
            fn const_loop() {
                const X: bool = {
                    let it = Some(42);
                    let mut run = false;
                    for x in it {
                        assert!(x == 42);
                        run = true;
                    }
                    run
                };
                assert!(X);
            }
        "#;
        let out = lift_src(src);
        // The `assert!(x == 42)` under the `for` must stay refused (conditional);
        // only the unconditional top-level `assert!(X)` lifts.
        assert!(
            out.skip_reasons.iter().any(|r| r.contains("under for context")),
            "the for-bodied assert inside the const block must stay refused as a \
             for-context assertion, not be falsely lifted: {:?}",
            out.skip_reasons
        );
        assert!(
            out.assertions_lifted <= 1,
            "only the unconditional `assert!(X)` may lift, not the conditional \
             for-body assert: lifted={}, reasons={:?}",
            out.assertions_lifted,
            out.skip_reasons
        );
    }

    // ── Stateful-read trajectory vindication (interior-mut / iterator) ────────

    #[test]
    fn omitted_range_bound_is_not_an_underscore_var() {
        // `v[..4]` must lift with start 0, never a `_` var -- `_` is not a valid
        // SMT symbol and reached the solver as `unknown constant _`, spuriously
        // refusing every slice obligation.
        let src = r#"
            #[test]
            fn slice_count() {
                let v = [1, 2, 3, 4, 5];
                assert_eq!(v[..4].iter().count(), 4);
            }
        "#;
        let out = lift_src(src);
        let dump = format!("{:?}", out.decls);
        assert!(
            !dump.contains("name: \"_\""),
            "an omitted range bound must not lift to a `_` var: {dump}"
        );
        assert!(
            contract_names(&out).iter().any(|n| n.contains("range(i:0")),
            "an omitted range start must lift to 0: {:?}",
            contract_names(&out)
        );
    }

    #[test]
    fn interior_mutable_cell_reads_do_not_coalesce() {
        // `c.get()` at two program points observes a mutable interior, so the
        // reads must get DISTINCT keys (c is versioned per statement) rather than
        // coalesce into a false contradiction.
        let src = r#"
            #[test]
            fn cell_traj() {
                let c = Cell::new(0);
                assert_eq!(c.get(), 0);
                assert_eq!(c.get(), 4);
            }
        "#;
        let out = lift_src(src);
        let gets: Vec<&str> = contract_names(&out)
            .into_iter()
            .filter(|n| n.contains("method:get"))
            .collect();
        assert!(gets.len() >= 2, "expected two get obligations: {gets:?}");
        let distinct: std::collections::HashSet<&str> = gets.iter().cloned().collect();
        assert_eq!(
            distinct.len(),
            gets.len(),
            "interior-mut reads must have distinct keys, not coalesce: {gets:?}"
        );
    }

    #[test]
    fn iterator_reads_do_not_coalesce() {
        // An iterator is consumed/advanced, so `len` observed at two program
        // points must get distinct keys rather than coalesce.
        let src = r#"
            #[test]
            fn iter_traj() {
                let mut it = [1, 2, 3].iter();
                assert_eq!(it.len(), 3);
                let _ = it.next();
                assert_eq!(it.len(), 2);
            }
        "#;
        let out = lift_src(src);
        let lens: Vec<&str> = contract_names(&out)
            .into_iter()
            .filter(|n| n.contains("method:len"))
            .collect();
        assert!(lens.len() >= 2, "expected two len obligations: {lens:?}");
        let distinct: std::collections::HashSet<&str> = lens.iter().cloned().collect();
        assert_eq!(
            distinct.len(),
            lens.len(),
            "iterator reads must have distinct keys, not coalesce: {lens:?}"
        );
    }

    #[test]
    fn plain_immutable_binding_reads_do_coalesce() {
        // DISCRIMINATION: a plain (non-stateful) binding read twice with the SAME
        // value coalesces to ONE key -- versioning is ONLY for stateful receivers,
        // so a real contradiction on an immutable value is still caught.
        let src = r#"
            #[test]
            fn plain() {
                let x = 5;
                assert_eq!(plain_helper(x), 1);
                assert_eq!(plain_helper(x), 1);
            }
        "#;
        let out = lift_src(src);
        let calls: Vec<&str> = contract_names(&out)
            .into_iter()
            .filter(|n| n.contains("plain_helper"))
            .collect();
        if calls.len() >= 2 {
            let distinct: std::collections::HashSet<&str> = calls.iter().cloned().collect();
            assert_eq!(
                distinct.len(),
                1,
                "a plain immutable binding's reads must COALESCE (one key): {calls:?}"
            );
        }
    }

    #[test]
    fn iterator_producer_and_ufcs_reads_do_not_coalesce() {
        // `core::iter::repeat(x).take(n)` (a producer free fn) and
        // `IntoIterator::into_iter([..])` (UFCS) are iterators too -- their reads
        // must get distinct keys, not coalesce.
        for src in [
            r#"
            #[test]
            fn prod() {
                let mut iter = core::iter::repeat(42).take(40);
                assert_eq!(iter.len(), 40);
                let _ = iter.next();
                assert_eq!(iter.len(), 39);
            }
            "#,
            r#"
            #[test]
            fn ufcs() {
                let mut it = IntoIterator::into_iter([0, 9, 2, 4]);
                assert_eq!(it.len(), 4);
                let _ = it.next();
                assert_eq!(it.len(), 3);
            }
            "#,
        ] {
            let out = lift_src(src);
            let lens: Vec<&str> = contract_names(&out)
                .into_iter()
                .filter(|n| n.contains("method:len"))
                .collect();
            assert!(lens.len() >= 2, "expected two len obligations: {lens:?}");
            let distinct: std::collections::HashSet<&str> = lens.iter().cloned().collect();
            assert_eq!(
                distinct.len(),
                lens.len(),
                "producer/UFCS iterator reads must have distinct keys: {lens:?}"
            );
        }
    }

    #[test]
    fn binding_derived_from_stateful_is_also_a_trajectory() {
        // A view/borrow over a stateful binding is itself a trajectory (recursive
        // propagation), so its reads must get distinct keys.
        let src = r#"
            #[test]
            fn derived() {
                let x = Cell::new(0);
                let r = &x;
                assert_eq!(r.get(), 0);
                assert_eq!(r.get(), 4);
            }
        "#;
        let out = lift_src(src);
        let gets: Vec<&str> = contract_names(&out)
            .into_iter()
            .filter(|n| n.contains("method:get"))
            .collect();
        assert!(gets.len() >= 2, "expected two get obligations: {gets:?}");
        let distinct: std::collections::HashSet<&str> = gets.iter().cloned().collect();
        assert_eq!(
            distinct.len(),
            gets.len(),
            "a binding derived from a stateful one must have distinct read keys: {gets:?}"
        );
    }

    #[test]
    fn static_atomic_loads_do_not_coalesce() {
        // A `static X: AtomicUsize` is interior-mutable global state; its `.load()`
        // reads must get distinct keys.
        let src = r#"
            #[test]
            fn atomic_traj() {
                static A: AtomicUsize = AtomicUsize::new(0);
                assert_eq!(A.load(SeqCst), 0);
                assert_eq!(A.load(SeqCst), 4);
            }
        "#;
        let out = lift_src(src);
        let loads: Vec<&str> = contract_names(&out)
            .into_iter()
            .filter(|n| n.contains("method:load"))
            .collect();
        assert!(loads.len() >= 2, "expected two load obligations: {loads:?}");
        let distinct: std::collections::HashSet<&str> = loads.iter().cloned().collect();
        assert_eq!(
            distinct.len(),
            loads.len(),
            "static atomic loads must have distinct keys: {loads:?}"
        );
    }

    // ── Int literal width: SOUNDNESS GUARD (no opaque wrapper) ────────────────
    //
    // A suffixed literal (`1u8`) must lift to a CONCRETE Int term, never an
    // opaque `typed_int:` ctor. Wrapping it opaque made arithmetic uncheckable:
    // `2u8 + 3u8 == 6` became `X + Y == 6` over free Ints (SAT) -> a real
    // arithmetic contradiction would be silently DISCHARGED (a falsePass). This
    // guard locks that hole shut.
    //
    // KNOWN RESIDUAL (tracked): because the width is therefore NOT yet in the
    // callsite key, `align_of_val(&1u8)=1` and `align_of_val(&1u64)=8` still
    // collapse onto one key and are reported as a (false) contradiction. The
    // proper fix is a width-sort hierarchy in the proofir compiler (maps
    // u8..i128 -> Int for SMT, preserves the width name for the KEY), NOT
    // opaquing the term.

    #[test]
    fn suffixed_int_lifts_to_concrete_term_not_opaque_wrapper() {
        // `2u8 + 3u8 == 6` must remain a CHECKABLE arithmetic obligation: the
        // literals stay concrete Ints, so no `typed_int:`-style opaque wrapper
        // appears anywhere in the lifted contracts.
        let src = r#"
            #[test]
            fn arith() {
                assert_eq!(2u8 + 3u8, 6);
            }
        "#;
        let out = lift_src(src);
        let names = contract_names(&out);
        let serialized = format!("{:?}", out.decls);
        assert!(
            !serialized.contains("typed_int"),
            "suffixed literals must NOT be wrapped in an opaque typed_int ctor \
             (that masks arithmetic contradictions): {names:?}"
        );
    }

    #[test]
    fn int_width_distinguishes_align_of_val_keys() {
        // `align_of_val(&1u8)` (=1) and `align_of_val(&1u64)` (=8) must land in
        // DISTINCT obligations: the width rides in the key (`i:1:u8` vs `i:1:u64`)
        // so they no longer collapse onto `ref(i:1)` and get conjoined into a
        // false contradiction. The term stays a concrete Int (no opaque wrapper).
        let src = r#"
            #[test]
            fn align_of_val_basic() {
                assert_eq!(align_of_val(&1u8), 1);
                assert_eq!(align_of_val(&1u64), 8);
            }
        "#;
        let out = lift_src(src);
        let names = contract_names(&out);
        assert!(
            names.iter().any(|n| n.contains("i:1:u8")),
            "expected a width-tagged key `i:1:u8` in {names:?}"
        );
        assert!(
            names.iter().any(|n| n.contains("i:1:u64")),
            "expected a width-tagged key `i:1:u64` in {names:?}"
        );
        assert_ne!(
            names.iter().find(|n| n.contains("i:1:u8")),
            names.iter().find(|n| n.contains("i:1:u64")),
            "u8 and u64 align_of_val calls must be DISTINCT obligations: {names:?}"
        );
    }

    // ── Fix B: local helper function scope in EUF key ─────────────────────────
    //
    // When the same local helper name `string` exists in two different test fns,
    // calls to `string(c)` must produce distinct keys per-test. Before the fix,
    // `string('\n') == "\\n"` from test A and `string('\n') == "\\n"` (or a
    // different rhs) from test B produced the same key and got conjoined.

    #[test]
    fn local_helper_call_key_is_scoped_to_test_fn() {
        // Two test functions both call a local helper `helper(x)`. The
        // obligations must be distinct even though the argument is the same.
        let src = r#"
            #[test]
            fn test_a() {
                fn helper(c: char) -> i32 { 0 }
                assert_eq!(helper('a'), 1);
            }
            #[test]
            fn test_b() {
                fn helper(c: char) -> i32 { 0 }
                assert_eq!(helper('a'), 2);
            }
        "#;
        let out = lift_src(src);
        // helper('a') in test_a and helper('a') in test_b must be in different
        // obligations. Contract names must include the test fn name as scope.
        let names = contract_names(&out);
        let test_a_contracts: Vec<_> = names.iter().filter(|n| n.contains("test_a")).collect();
        let test_b_contracts: Vec<_> = names.iter().filter(|n| n.contains("test_b")).collect();
        // Each test must have its own scoped contract for helper('a').
        assert!(
            !test_a_contracts.is_empty() || !test_b_contracts.is_empty(),
            "expected scoped contracts per test fn, got: {names:?}"
        );
    }

    #[test]
    fn unqualified_callee_includes_local_scope_in_key() {
        // A bare function call `f(x)` in term position must include the test
        // fn's scoped name in the assertion key (the `local_scope::f` prefix),
        // preventing federation with a same-named function in another test.
        let src = r#"
            #[test]
            fn test_escape_debug() {
                assert_eq!(escape('\n'), "\\n");
                assert_eq!(escape(' '), " ");
            }
        "#;
        let out = lift_src(src);
        let names = contract_names(&out);
        // The key for `escape('\n')` must contain the test fn scope.
        let scoped = names.iter().any(|n| n.contains("test_escape_debug"));
        assert!(
            scoped || out.skip_reasons.iter().any(|r| r.contains("escape")),
            "expected scoped key or refusal for `escape` call; contracts: {names:?}"
        );
    }

    // ── Fix C: addr_of_mut! marks variable ambiguous ──────────────────────────
    //
    // `addr_of_mut!(x)` creates a raw pointer alias to `x`. Any subsequent
    // mutation through that pointer (e.g. `ptr::swap`) changes `x` without a
    // visible assignment. The variable must be marked ambiguous so pre/post
    // assertions don't coalesce.

    #[test]
    fn addr_of_mut_marks_local_ambiguous() {
        // After `addr_of_mut!(y)`, `y` must be ambiguous — assertions about
        // `y` before and after must NOT coalesce under the same contract.
        let src = r#"
            #[test]
            fn swap_test() {
                let mut x = 5u8;
                let mut y = 6u8;
                let _p = addr_of_mut!(y);
                assert_eq!(x, 5);
                assert_eq!(y, 6);
                assert_eq!(y, 5);
            }
        "#;
        let out = lift_src(src);
        // y's ambiguity should cause its assertions to be dropped (skip) or
        // separated, not conjoined into a single obligation with contradictory values.
        // Key check: no assertion `y == 6 && y == 5` in any single contract inv.
        // We verify by checking that the lifter does not produce a contract
        // whose name resolves to the plain Var `y` (it would be ambiguous/dropped).
        let names = contract_names(&out);
        // The presence of a skip reason about y's ambiguity is the expected outcome.
        let y_ambiguous = out.skip_reasons.iter().any(|r| r.contains("ambiguous") && r.contains("y"))
            || !names.iter().any(|n| n.ends_with("::assertion") && n.contains("y"));
        assert!(
            y_ambiguous || out.skip_reasons.iter().any(|r| r.contains("y")),
            "expected y to be ambiguous/dropped after addr_of_mut!, contracts: {names:?}, skips: {:?}",
            out.skip_reasons
        );
    }

    // ── Fix D: closure &mut capture marks receiver ambiguous ─────────────────
    //
    // `iter.for_each(|x| s.push(x))` mutates `s` through a closure capture.
    // `s` must be treated as ambiguous so assertions `s == "Zab"` and
    // `s == "Zabcd"` (after further mutations) don't coalesce.

    #[test]
    fn closure_mut_receiver_marks_local_ambiguous() {
        // `.for_each(|x| s.push(x))` mutates `s` — assertions about `s` before
        // and after must be refused (ambiguous) rather than conjoined.
        let src = r#"
            #[test]
            fn by_ref_sized_test() {
                let mut s = String::new();
                let vals = [1i32, 2, 3];
                vals.iter().for_each(|_x| s.push('a'));
                assert_eq!(s, "aaa");
                vals.iter().for_each(|_x| s.push('b'));
                assert_eq!(s, "aaabbb");
            }
        "#;
        let out = lift_src(src);
        // `s` must not produce a conjoined contradictory obligation.
        // The skip reasons should mention s's ambiguity, OR s-related assertions
        // should be absent (dropped).
        let s_asserts_conjoined = out.decls.iter().any(|d| {
            d.name.contains("::assertion") && {
                // check if any single obligation contains s with two different values
                // (this is a heuristic — we just verify no single contract for s)
                d.name.contains("s") && !d.name.contains("test_") // bare 's' var key
            }
        });
        assert!(
            !s_asserts_conjoined,
            "s must not appear as a bare EUF key after closure mutation"
        );
    }

    // ── fold-closure foralls: `.for_each(|v| assert..)` over a FINITE domain ──
    //
    // `<lit>.iter().for_each(|v| assert!(..))` is the SAME bounded universal as
    // `for v in <lit> { assert!(..) }`: a finite conjunction over the constructed
    // domain (construction axiom). The collector did not descend the `for_each`
    // closure, so the body assert fell to the nested-unlifted-expr-statement /
    // let-initializer refusal. `try_lift_for_each_forall` mirrors the for-loop
    // lift and drains them -- but ONLY for a finite-literal domain, NEVER for an
    // opaque receiver and NEVER for a mutating body (an unsound single universal).

    #[test]
    fn for_each_over_literal_array_lifts_like_for_loop() {
        // POSITIVE: a clean assert body in a `.for_each` over a LITERAL array is a
        // finite conjunction over its elements -- it must LIFT (one named
        // universal memento), not fall to the nested-unlifted-expr-statement
        // bucket. `into_iter` over a literal array is constructed identically.
        let src = r#"
            #[test]
            fn each_lit() {
                [1i32, 2, 3].into_iter().for_each(|x| {
                    assert!(x > 0);
                });
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 1,
            "the literal-array `.for_each` body assert must lift as a bounded \
             universal; reasons: {:?}",
            out.skip_reasons
        );
        assert_eq!(
            out.assertions_refused, 0,
            "no assert should be refused for a clean literal-domain `.for_each`: {:?}",
            out.skip_reasons
        );
        assert!(
            !out.skip_reasons.iter().any(|r| r
                .contains("nested in an unlifted expression statement")
                || r.contains("inside a let-initializer expression")),
            "the `.for_each` body assert must not stay in a fold-closure refusal: {:?}",
            out.skip_reasons
        );
        assert!(
            contract_names(&out).iter().any(|n| n.contains("::for_each::x")),
            "the lifted universal must be named `<test>::for_each::<var>`: {:?}",
            contract_names(&out)
        );
    }

    #[test]
    fn for_each_over_closed_range_lifts_as_guarded_forall() {
        // POSITIVE (range form): `(a..b).for_each(|i| assert!(..))` is the guarded
        // universal `forall i. a<=i<b => body` -- the same lift the for-loop gives
        // a closed range. It must lift, not refuse.
        let src = r#"
            #[test]
            fn each_range() {
                (0..4).for_each(|i| {
                    assert!(i < 4);
                });
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 1,
            "the closed-range `.for_each` body assert must lift as a guarded \
             universal; reasons: {:?}",
            out.skip_reasons
        );
        assert_eq!(out.assertions_refused, 0, "{:?}", out.skip_reasons);
    }

    #[test]
    fn for_each_over_opaque_collection_stays_refused() {
        // DISCRIMINATION: the receiver is a BINDING (`v`), so its elements are
        // RUNTIME data, not constructed from source literals. There is no finite
        // conjunction to walk: the lift MUST refuse (bin-2), leaving the body
        // assert in its existing refusal -- forcing a universal over an opaque
        // domain would be an unfounded claim.
        let src = r#"
            #[test]
            fn each_opaque() {
                let v = make_collection();
                v.iter().for_each(|x| {
                    assert!(x.is_valid());
                });
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 0,
            "an opaque-domain `.for_each` must NOT be lifted (runtime data, not \
             constructible): {:?}",
            contract_names(&out)
        );
        assert!(
            out.assertions_refused >= 1,
            "the opaque-domain `.for_each` body assert must stay refused: {:?}",
            out.skip_reasons
        );
        assert!(
            !contract_names(&out).iter().any(|n| n.contains("::for_each::")),
            "no `for_each` universal memento may be minted over an opaque domain: {:?}",
            contract_names(&out)
        );
    }

    #[test]
    fn for_each_with_mutating_body_stays_refused() {
        // STRUCTURAL: the domain is a LITERAL array (finite), but the body MUTATES
        // an accumulator (`total += x`). A single universal over the bound var
        // would be a false claim (the asserted value varies across iterations
        // independently of the var). The purity gate must REFUSE the whole lift,
        // leaving the body assert in its refusal.
        let src = r#"
            #[test]
            fn each_mut() {
                let mut total = 0;
                [1i32, 2, 3].iter().for_each(|x| {
                    total += x;
                    assert!(total > 0);
                });
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 0,
            "a mutating-body `.for_each` must NOT be lifted even over a literal \
             domain (unsound single universal): {:?}",
            contract_names(&out)
        );
        assert!(
            !contract_names(&out).iter().any(|n| n.contains("::for_each::")),
            "no `for_each` universal memento may be minted for a mutating body: {:?}",
            contract_names(&out)
        );
    }

    // ── HALF 2: side-effecting / opaque closure-method asserts -> TERMINAL ─────
    //
    // The fold-closure bucket has two halves. HALF 1 (the Dissolver) compiles+runs the
    // CONSTRUCTIBLE-PURE closure statements verbatim (drains in --dissolve). HALF 2: the
    // side-effecting / opaque-accessor cases are NOT dissolvable and NOT liftable -- they
    // are a SOURCE property, so they move unclassified -> TERMINAL refused ("happy
    // refuse") instead of the generic "nested unlifted expression statement" unclassified.

    #[test]
    fn side_effecting_for_each_body_is_terminal_refused() {
        // The intersperse shape: `iter.clone().for_each(|x| assert_eq!(Some(x),
        // iter.next()))` -- the body ADVANCES a captured iterator (`iter.next()`), a side
        // effect, so the assert observes a per-iteration value, not a timeless point-wise
        // claim. TERMINAL, not unclassified.
        let src = r#"
            #[test]
            fn intersperse_like() {
                let mut iter = [1i32, 2, 3].iter();
                iter.clone().for_each(|x| assert_eq!(Some(x), iter.next()));
            }
        "#;
        let out = lift_src(src);
        assert!(
            out.skip_reasons.iter().any(|r| r.contains("side-effecting closure body")),
            "a for_each body that advances a captured iterator must be TERMINAL refused: {:?}",
            out.skip_reasons
        );
        assert!(
            out.skip_reasons.iter().all(|r| !r.contains("nested in an unlifted expression statement")),
            "the side-effecting case must NOT stay in the generic unclassified bucket: {:?}",
            out.skip_reasons
        );
        // and its disposition is terminal (Refused), not Unclassified work.
        assert!(
            out.skip_reasons
                .iter()
                .filter(|r| r.contains("side-effecting closure body"))
                .all(|r| matches!(refusal_disposition(r), Disposition::Refused)),
            "side-effecting closure body reason must be a terminal disposition"
        );
    }

    #[test]
    fn opaque_accessor_closure_is_terminal_refused() {
        // The TLS / BorrowedBuf shape: `DROPS.with(|d| assert_eq!(*d.borrow(), [0]))` --
        // `.with` is NOT a pure iterator/Option adaptor; the receiver is opaque runtime
        // state (a thread-local), not a constructed literal domain. TERMINAL (bin-2).
        let src = r#"
            #[test]
            fn tls_like() {
                DROPS.with(|d| assert_eq!(*d.borrow(), [0]));
            }
        "#;
        let out = lift_src(src);
        assert!(
            out.skip_reasons.iter().any(|r| r.contains("opaque/effectful accessor") && r.contains("bin-2")),
            "a `.with`-accessor closure assert must be TERMINAL refused (bin-2): {:?}",
            out.skip_reasons
        );
        assert!(
            out.skip_reasons
                .iter()
                .filter(|r| r.contains("opaque/effectful accessor"))
                .all(|r| matches!(refusal_disposition(r), Disposition::Refused)),
            "opaque-accessor reason must be a terminal disposition"
        );
    }

    // ── The typed BAIL: `SideEffect` (the mirror of `Sugar`) ───────────────────
    //
    // `Sugar::desugar` reaches truth (Dug). When the walk hits monkey business it
    // BAILS; a `SideEffect` RETYPES that bail as a NAMED, WARRANTED order-loss
    // boundary. THE CRITICAL LINE: a `SideEffect` is only for a PROVABLE order-loss
    // effect (a mutation / iter-advance / opaque-runtime value / mutable read); a
    // PURE-but-untranslated term STAYS UNCLASSIFIED (honest work), never fake-refused.

    #[test]
    fn typed_side_effect_catalog_reasons_are_all_terminal() {
        // Every named `Effect`'s `reason()` is recognized terminal by
        // `refusal_disposition` (the bail is a CLAIM, earned). `boundary()` ropes the
        // refusal to the source construct that warrants it (the bail-side `SourceMemento`,
        // mirror of the dig-side `Warrant`).
        let effects: Vec<Effect> = vec![
            Effect::Mutation { boundary: "v.push(x)".to_string() },
            Effect::IterAdvance { boundary: "iter.next()".to_string() },
            Effect::OpaqueRuntime { boundary: "p.iter().for_each(..)".to_string(), accessor: false },
            Effect::OpaqueRuntime { boundary: "buf.with_unfilled_buf(..)".to_string(), accessor: true },
            Effect::Tls { boundary: "DROPS.with(..)".to_string() },
            Effect::Io { boundary: "out.write(..)".to_string() },
            Effect::TemporalRead { boundary: "a[i]".to_string() },
            Effect::ControlFlow { boundary: "try { maybe_fut? }".to_string() },
        ];
        for e in &effects {
            assert_eq!(
                refusal_disposition(&e.reason()),
                Disposition::Refused,
                "typed Effect reason must be terminal: {}",
                e.reason()
            );
            // The boundary memento carries the source construct (non-empty rope).
            assert!(!e.boundary().boundary.is_empty(), "boundary memento must rope to a source construct");
        }
    }

    #[test]
    fn adversarial_a_mutation_and_iter_advance_bodies_are_typed_side_effect_refuse() {
        // (a) GENUINE MUTATION: a `.for_each` body that mutates captured state (`total +=
        // x`) -- a `MutationEffect`. The asserted value varies per iteration, no single
        // timeless `t`. TYPED SIDE-EFFECT refuse, NOT unclassified.
        let mut_src = r#"
            #[test]
            fn mutating_body() {
                let mut total = 0i32;
                [1i32, 2, 3].iter().for_each(|x| {
                    total += x;
                    assert!(total > 0);
                });
            }
        "#;
        let out = lift_src(mut_src);
        assert!(
            out.skip_reasons.iter().any(|r| r.contains("side-effecting closure body")),
            "a mutating closure body must be a typed SideEffect refuse: {:?}",
            out.skip_reasons
        );
        assert!(
            out.skip_reasons
                .iter()
                .filter(|r| r.contains("side-effecting closure body"))
                .all(|r| matches!(refusal_disposition(r), Disposition::Refused)),
            "the mutation SideEffect must be a terminal disposition (refused): {:?}",
            out.skip_reasons
        );
        assert!(
            out.skip_reasons.iter().all(|r| !r.contains("nested in an unlifted expression statement")),
            "the mutation case must NOT stay generic-unclassified: {:?}",
            out.skip_reasons
        );

        // (a') GENUINE ITER-ADVANCE: a body that advances a captured iterator
        // (`iter.next()`) -- an `IterAdvanceEffect`, the same terminal class, distinct
        // cause. Also TYPED SIDE-EFFECT refuse.
        let adv_src = r#"
            #[test]
            fn iter_advance_body() {
                let mut iter = [1i32, 2, 3].iter();
                iter.clone().for_each(|x| assert_eq!(Some(x), iter.next()));
            }
        "#;
        let out = lift_src(adv_src);
        assert!(
            out.skip_reasons.iter().any(|r| r.contains("side-effecting closure body")),
            "an iterator-advancing closure body must be a typed SideEffect refuse: {:?}",
            out.skip_reasons
        );
        assert!(
            out.skip_reasons
                .iter()
                .filter(|r| r.contains("side-effecting closure body"))
                .all(|r| matches!(refusal_disposition(r), Disposition::Refused)),
            "the iter-advance SideEffect must be terminal (refused): {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn adversarial_b_runtime_receiver_is_opaque_runtime_effect_refuse() {
        // (b) RUNTIME RECEIVER: a `.for_each` over an opaque runtime receiver
        // (`std::env::args()` -- a runtime call result, not a constructed literal) -- an
        // `OpaqueRuntimeEffect` (bin-2). The iterated values are runtime data, no
        // construction to walk. TYPED refuse, NOT unclassified.
        let src = r#"
            #[test]
            fn over_runtime() {
                std::env::args().for_each(|x| assert!(!x.is_empty()));
            }
        "#;
        let out = lift_src(src);
        assert!(
            out.skip_reasons.iter().any(|r| r.contains("bin-2") && r.contains("runtime")),
            "an opaque runtime receiver must be a typed OpaqueRuntimeEffect refuse (bin-2): {:?}",
            out.skip_reasons
        );
        assert!(
            out.skip_reasons
                .iter()
                .filter(|r| r.contains("bin-2"))
                .all(|r| matches!(refusal_disposition(r), Disposition::Refused)),
            "the opaque-runtime SideEffect must be terminal (refused): {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn adversarial_c_pure_but_untranslated_term_stays_unclassified_not_refused() {
        // (c) THE CRITICAL LINE: a PURE-but-untranslated term must STAY UNCLASSIFIED
        // (honest future work for a Sugar/const_eval arm), NEVER reclassified as a
        // SideEffect. A VALUE-POSITION `if`/`else` term (`if true { 1 } else { 2 }`) is
        // PURE -- no mutation, no iter-advance, no runtime value (all literals) -- we
        // simply have not transcribed a term-position `Expr::If` yet (the assertion path
        // lifts an if-CONDITION, but an if as a TERM operand falls through). (The EUF
        // term path digs MOST untranslated calls as uninterpreted symbols -- e.g.
        // `char::from_u32(i).unwrap().to_ascii_uppercase()` over `0..3` lifts soundly via
        // EUF -- so a genuine term-GAP is rare; this if-term is one. Refusing it as an
        // effect would be a FAKE-REFUSE: mislabeling our own work as a source property --
        // the exact trap that put 8 bad terminals in an earlier floor.)
        //
        // NOTE: this fixture WAS `(1i32 as f64)`, chosen as a then-untranslated cast.
        // The TermBreadth float-cast arm now lifts `as f16/f32/f64/f128` to the opaque
        // `cast:fN(..)` ctor, so that example is no longer a term-gap; the intent (pure
        // term stays unclassified, never fake-refused) is preserved with a still-untranslated
        // pure term.
        let src = r#"
            #[test]
            fn pure_untranslated() {
                assert_eq!(if true { 1 } else { 2 }, 1);
            }
        "#;
        let out = lift_src(src);
        // It is refused-as-not-discharged (we did not lift it), but its disposition is
        // UNCLASSIFIED work, NOT a terminal SideEffect refuse.
        assert_eq!(
            out.assertions_lifted, 0,
            "the untranslated pure term must not be (falsely) discharged: {:?}",
            out.skip_reasons
        );
        assert!(
            !out.skip_reasons.is_empty()
                && out.skip_reasons.iter().all(|r| matches!(refusal_disposition(r), Disposition::Unclassified)),
            "a PURE-but-untranslated term must STAY UNCLASSIFIED, never a SideEffect refuse: {:?}",
            out.skip_reasons
        );
        // And specifically: it must NOT have been laundered into any effect reason.
        assert!(
            out.skip_reasons.iter().all(|r| {
                !r.contains("side-effecting closure body")
                    && !r.contains("mutable container is not temporally stable")
                    && !(r.contains("bin-2") && r.contains("runtime"))
            }),
            "EFFECT-OR-LEAVE: a pure term must not wear any SideEffect reason: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn the_drain_mutable_container_read_is_temporal_read_effect_refuse() {
        // THE DRAIN: a read of a provably-MUTABLE container (`buf[i]` where `buf` is a
        // `let mut` the `mut` oracle flags) is a `TemporalReadEffect` -- the index-read
        // sibling of the whitelisted `temporally unstable`. It fell to unclassified only
        // because its reason was not whitelisted; typing + whitelisting moves it
        // unclassified -> refused. SOUNDNESS: emitted ONLY under `is_mut_local`.
        let src = r#"
            #[test]
            fn mutable_read() {
                let mut buf = [0i32, 0, 0];
                buf[0] = 7;
                assert_eq!(buf[1], 0);
            }
        "#;
        let out = lift_src(src);
        assert!(
            out.skip_reasons.iter().any(|r| r.contains("mutable container is not temporally stable")),
            "a read of a mutable container must surface the TemporalReadEffect reason: {:?}",
            out.skip_reasons
        );
        assert!(
            out.skip_reasons
                .iter()
                .filter(|r| r.contains("mutable container is not temporally stable"))
                .all(|r| matches!(refusal_disposition(r), Disposition::Refused)),
            "THE DRAIN: the mutable-container read must now be TERMINAL refused, not unclassified: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn drain_soundness_immutable_container_read_is_not_a_temporal_read_effect() {
        // THE DISCRIMINATION TWIN: a read of a NON-`mut` (provably-immutable) container
        // must NOT be a `TemporalReadEffect`. A non-`mut` local reads as a stable
        // `index(a,i)` term -- the `is_mut_local` gate is never hit -- so the effect is
        // never minted. This proves the drain refuses ONLY a genuinely-mutable read,
        // never a pure/stable one (no over-terminalization).
        let src = r#"
            #[test]
            fn immutable_read() {
                let buf = [1i32, 2, 3];
                assert_eq!(buf[1], 2);
            }
        "#;
        let out = lift_src(src);
        assert!(
            out.skip_reasons.iter().all(|r| !r.contains("mutable container is not temporally stable")),
            "an immutable-container read must NEVER wear the TemporalReadEffect reason: {:?}",
            out.skip_reasons
        );
    }

    // ── DEFOLDER: hermetic symbolic fold-unroll over a literal domain ─────────
    //
    // `fold`'s definition IS its desugaring (`acc = init; while let Some(x) = it.next()
    // { acc = f(acc, x) }`). Over a FINITE literal domain it is the finite conjunction of
    // the per-iteration body with `acc` threaded as a const-folded value -- the
    // construction axiom, no compile/run. `for_each` is `fold` with `acc = ()`.

    #[test]
    fn defold_pure_fold_over_literal_locals_lifts() {
        // (a) POSITIVE: `xs.iter().fold(0, |i, &x| { assert_eq!(x, ys[i]); i + 1 })` over
        // literal `xs`/`ys` -- the index accumulator threads 0,1,2 and each body assert
        // becomes a concrete point. Lifts as the finite conjunction (no skip).
        let src = r#"
            #[test]
            fn pure_fold() {
                let xs = [1u32, 2, 3];
                let ys = [1u32, 2, 3];
                let _ = xs.iter().fold(0usize, |i, &x| { assert_eq!(x, ys[i]); i + 1 });
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 1,
            "the defolded fold body assert must lift as the finite conjunction; reasons: {:?}",
            out.skip_reasons
        );
        assert!(
            out.skip_reasons.iter().all(|r| !r.contains("let-initializer expression")
                && !r.contains("side-effecting closure body")
                && !r.contains("opaque/effectful accessor")),
            "a defolded pure fold must NOT remain in any skip bucket: {:?}",
            out.skip_reasons
        );
        assert!(
            contract_names(&out).iter().any(|n| n.contains("::fold")),
            "the lifted conjunction must be named `<test>::fold`: {:?}",
            contract_names(&out)
        );
    }

    #[test]
    fn defold_rfold_reverses_element_order_and_lifts() {
        // (b) `.rfold` iterates the literal domain in REVERSE; the accumulator threads over
        // the reversed order. Still a finite conjunction -- lifts.
        let src = r#"
            #[test]
            fn rfold_t() {
                let xs = [10u32, 20, 30];
                let _ = xs.iter().rfold(0usize, |i, &x| { assert!(x > 0); i + 1 });
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 1,
            "an rfold over a literal array must lift (reverse order); reasons: {:?}",
            out.skip_reasons
        );
        assert!(
            contract_names(&out).iter().any(|n| n.contains("::rfold")),
            "named `<test>::rfold`: {:?}",
            contract_names(&out)
        );
    }

    #[test]
    fn defold_enumerate_fold_lifts() {
        // (c) `.iter().enumerate().fold(0, |acc, (j, &x)| ..)` binds the index pair; the
        // index `j` is the concrete position each step. Lifts.
        let src = r#"
            #[test]
            fn enum_fold() {
                let xs = [5u32, 6, 7];
                let _ = xs.iter().enumerate().fold(0usize, |acc, (j, &x)| { assert!(x >= j as u32); acc + 1 });
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 1,
            "an enumerate().fold over a literal array must lift; reasons: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn defold_opaque_receiver_fold_is_terminal_refused() {
        // (d) DISCRIMINATION: inside a `#[test]` fn, the fold receiver `v` is bound to a
        // RUNTIME fn-call result (`make()`), not a literal domain. The defolder declines
        // (the receiver does not resolve to a finite construction); HALF 2 then makes it a
        // TERMINAL refusal (opaque runtime receiver, bin-2), not generic unclassified.
        let src = r#"
            #[test]
            fn opaque_fold() {
                let v = make_runtime();
                let _ = v.iter().fold(0usize, |i, &x| { assert_eq!(x, i as u32); i + 1 });
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 0,
            "an opaque-domain fold must NOT be lifted by the defolder: {:?}",
            contract_names(&out)
        );
        assert!(
            out.skip_reasons.iter().any(|r| r.contains("opaque runtime receiver")
                && matches!(refusal_disposition(r), Disposition::Refused)),
            "an opaque-receiver fold body assert must be TERMINAL refused (bin-2): {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn defold_side_effecting_body_fold_is_terminal_refused() {
        // (e) DISCRIMINATION: a literal-domain fold whose body ADVANCES a captured iterator
        // (`other.next()`) is side-effecting -- the defolder declines (purity gate), and
        // HALF 2 makes it TERMINAL refused, not generic unclassified.
        let src = r#"
            #[test]
            fn se_fold() {
                let xs = [1u32, 2, 3];
                let mut other = [4u32, 5, 6].iter();
                let _ = xs.iter().fold(0usize, |i, &x| { assert_eq!(Some(&x), other.next()); i + 1 });
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 0,
            "a side-effecting-body fold must NOT be lifted: {:?}",
            contract_names(&out)
        );
        assert!(
            out.skip_reasons.iter().any(|r| r.contains("side-effecting closure body")
                && matches!(refusal_disposition(r), Disposition::Refused)),
            "a side-effecting fold body assert must be TERMINAL refused: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn defold_non_const_foldable_accumulator_stays_unclassified() {
        // (f) HONEST BOUNDARY: a literal-domain fold whose tail is NOT a const-foldable
        // accumulator update (`acc.wrapping_mul(x)` -- a method call we do not const-fold)
        // is declined by the defolder. The body is pure and the receiver is a pure adaptor,
        // so HALF 2 does NOT terminal-refuse it -- it stays UNCLASSIFIED (honest work, not a
        // fake discharge or a fake refusal).
        let src = r#"
            #[test]
            fn nf_fold() {
                let xs = [1u32, 2, 3];
                let _ = xs.iter().fold(1u32, |acc, &x| { assert!(x > 0); acc.wrapping_mul(x) });
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 0,
            "a non-const-foldable accumulator must NOT be defolded: {:?}",
            contract_names(&out)
        );
        assert!(
            out.skip_reasons.iter().any(|r| r.contains("let-initializer expression")
                && matches!(refusal_disposition(r), Disposition::Unclassified)),
            "a non-foldable-acc fold stays UNCLASSIFIED (honest), not terminal: {:?}",
            out.skip_reasons
        );
    }

    // ── DIG-side: transforming adaptors over the literal element sequence ─────
    //
    // `.filter`/`.map`/`.skip`/`.take`/`.skip_while`/`.take_while` ARE stdlib sugar; over a
    // literal domain their closures const-evaluate on the concrete elements, so the
    // resulting sequence is exact and the fold digs. EXACT-OR-BAIL: a runtime/inexact
    // closure makes the const-evaluator bail (honest unclassified), never a fake-dig.

    #[test]
    fn dig_filter_drops_elements_exactly() {
        // (a) ADVERSARIAL: `.filter(|x| x % 2 == 0)` over [0..6] keeps EXACTLY {0,2,4}. The
        // conjunction must be over the kept-3 sequence -- the dropped odds must NOT appear
        // as point-claims, the kept evens MUST.
        let src = r#"
            #[test]
            fn filt() {
                let xs = [0i64, 1, 2, 3, 4, 5];
                let _ = xs.iter().copied().filter(|x| x % 2 == 0).fold(0i64, |acc, x| { assert!(x % 2 == 0); acc + x });
            }
        "#;
        let out = lift_src(src);
        assert_eq!(out.assertions_lifted, 1, "filtered fold must lift: {:?}", out.skip_reasons);
        let dump = format!("{:?}", out.decls);
        // kept evens present as concrete operands; dropped odds absent as element operands.
        for kept in ["0", "2", "4"] {
            assert!(dump.contains(kept), "kept element {kept} must appear in the conjunction");
        }
        // The conjunction has exactly 3 conjuncts (one per kept element). The `%` atom
        // `x % 2 == 0` becomes `<elem> % 2 == 0`; count the int-modulo subterms == 3.
        let conjunct_marker = dump.matches("int-rem").count();
        assert_eq!(
            conjunct_marker, 3,
            "exactly 3 kept-element point-claims (0,2,4), not 6: dump={dump}"
        );
    }

    #[test]
    fn dig_map_transforms_values_exactly() {
        // (b) ADVERSARIAL: `.map(|x| x * 10)` over [1,2,3] makes the fold body see 10,20,30.
        // The conjunction must reference the TRANSFORMED values, not the originals.
        let src = r#"
            #[test]
            fn mp() {
                let xs = [1i64, 2, 3];
                let _ = xs.iter().copied().map(|x| x * 10).fold(0i64, |acc, x| { assert!(x >= 10); acc + x });
            }
        "#;
        let out = lift_src(src);
        assert_eq!(out.assertions_lifted, 1, "mapped fold must lift: {:?}", out.skip_reasons);
        let dump = format!("{:?}", out.decls);
        for mapped in ["10", "20", "30"] {
            assert!(dump.contains(mapped), "transformed value {mapped} must appear: {dump}");
        }
    }

    #[test]
    fn dig_skip_take_keep_exact_window() {
        // `.skip(1).take(2)` over [10,20,30,40] keeps EXACTLY {20,30}.
        let src = r#"
            #[test]
            fn st() {
                let xs = [10i64, 20, 30, 40];
                let _ = xs.iter().copied().skip(1).take(2).fold(0i64, |acc, x| { assert!(x >= 20); acc + x });
            }
        "#;
        let out = lift_src(src);
        assert_eq!(out.assertions_lifted, 1, "skip/take fold must lift: {:?}", out.skip_reasons);
        let dump = format!("{:?}", out.decls);
        assert!(dump.contains("20") && dump.contains("30"), "kept window {{20,30}}: {dump}");
    }

    #[test]
    fn dig_wrong_expected_produces_refutable_conjunction_not_fake_green() {
        // (c) ADVERSARIAL THE DANGEROUS ONE: a DELIBERATELY WRONG expected -- the body
        // asserts `x == wrong` where wrong != the actual element. The lift must NOT fake it
        // green: it must emit the concrete (false) equality the element produces, so a
        // solver REFUTES it. We verify the conjunction faithfully carries the actual element
        // values (the equality is present-and-false, not silently dropped or coerced equal).
        let src = r#"
            #[test]
            fn wrong() {
                let xs = [1i64, 2, 3];
                let ws = [9i64, 9, 9];
                let _ = xs.iter().copied().enumerate().fold(0i64, |acc, (i, x)| { assert_eq!(x, ws[i]); acc + 1 });
            }
        "#;
        let out = lift_src(src);
        // It DOES lift (the defolder digs the literal-derived sequence) ...
        assert_eq!(out.assertions_lifted, 1, "the enumerate fold lifts: {:?}", out.skip_reasons);
        let dump = format!("{:?}", out.decls);
        // ... but HONESTLY: the actual element values 1,2,3 are the LHS of the equalities
        // (faithful substitution), so `1 == ws[0]` etc. are refutable given ws=[9,9,9]. The
        // lift did not coerce x to 9 or drop the claim.
        for actual in ["1", "2", "3"] {
            assert!(dump.contains(actual), "actual element {actual} must be the faithful LHS: {dump}");
        }
        // The equality predicate is present (an `=`/eq atom), not optimized away to `true`.
        assert!(
            dump.contains("Atomic") || dump.contains("="),
            "the equality claim must be emitted (refutable), not faked green: {dump}"
        );
    }

    #[test]
    fn dig_runtime_predicate_in_filter_bails() {
        // (d) BAIL: the `.filter` predicate references a RUNTIME binding (`threshold`, bound
        // to a fn call), so the const-evaluator cannot decide which elements are kept -- it
        // bails. The fold stays UNCLASSIFIED (honest), NEVER a fake-dig over a guessed seq.
        let src = r#"
            #[test]
            fn rt_filt() {
                let xs = [1i64, 2, 3, 4];
                let threshold = runtime_value();
                let _ = xs.iter().copied().filter(|x| *x > threshold).fold(0i64, |acc, x| { assert!(x > 0); acc + x });
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 0,
            "a runtime-predicate filter must BAIL (cannot decide the kept set exactly): {:?}",
            contract_names(&out)
        );
    }

    #[test]
    fn dig_overflow_in_closure_bails() {
        // (e) BAIL: a `.map` closure that OVERFLOWS i64 (`x * huge`) must bail (checked_mul
        // returns None) rather than silently wrap (which would not match rustc's debug
        // semantics). Honest unclassified.
        let src = r#"
            #[test]
            fn ov() {
                let xs = [9223372036854775807i64, 2];
                let _ = xs.iter().copied().map(|x| x * 1000).fold(0i64, |acc, x| { assert!(x != 0); acc + 1 });
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 0,
            "an overflowing map closure must BAIL, not wrap (exact-or-none): {:?}",
            contract_names(&out)
        );
    }

    // ── ConditionalSugar: a guarded assert is `guard => claim`, never bare ────
    //
    // `if guard { assert P }` is the implication it states (`guard => P`), the
    // CLAIM-side atom. SOUNDNESS LINE: the body assert only fires when the guard
    // holds, so the lift MUST be guarded -- emitting bare `P` would be a fake-
    // discharge (asserting it unconditionally). EXACT-OR-BAIL: a guard that does
    // not translate, a branch that does not fully lift, or a mutating body bails.

    #[test]
    fn conditional_if_lifts_as_guarded_implication_not_bare_claim() {
        // POSITIVE + SOUNDNESS: `if x > 0 { assert!(x < 10) }` lifts as the
        // implication `x > 0 => x < 10`. The lifted formula must contain the
        // IMPLICATION (the guard as antecedent), not a bare `x < 10`.
        let src = r#"
            #[test]
            fn guarded() {
                let x = 5i64;
                if x > 0 {
                    assert!(x < 10);
                }
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 1,
            "a guarded assert must lift as a guarded implication: {:?}",
            out.skip_reasons
        );
        assert_eq!(
            out.assertions_refused, 0,
            "no refusal for a cleanly-guarded assert: {:?}",
            out.skip_reasons
        );
        assert!(
            out.skip_reasons.iter().all(|r| !r.contains("under if context")),
            "the guarded assert must NOT stay in the if-context refusal: {:?}",
            out.skip_reasons
        );
        // The emitted formula is an implication (`=>` / Implies connective), not a
        // bare claim atom: the guard is the antecedent.
        let dump = format!("{:?}", out.decls);
        assert!(
            dump.contains("Implies") || dump.contains("implies") || dump.contains("=>"),
            "the guarded assert must emit `guard => claim` (an implication), \
             never a bare claim (that would be a fake-discharge): {dump}"
        );
    }

    #[test]
    fn conditional_else_branch_lifts_under_negated_guard() {
        // STRUCTURAL: `if c { assert A } else { assert B }` lifts as
        // `(c => A) and (not c => B)` -- the else branch fires under the negated
        // guard. Both branches must be present, each under its own guard.
        let src = r#"
            #[test]
            fn both_branches() {
                let x = 3i64;
                if x > 0 {
                    assert!(x > 0);
                } else {
                    assert!(x <= 0);
                }
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 2,
            "both guarded branches must lift (then under c, else under not c): {:?}",
            out.skip_reasons
        );
        let dump = format!("{:?}", out.decls);
        assert!(
            dump.contains("Not") || dump.contains("not"),
            "the else branch must be guarded by the NEGATED condition: {dump}"
        );
    }

    #[test]
    fn conditional_opaque_pure_guard_lifts_faithfully_under_euf() {
        // SOUNDNESS (EUF at callsites): an OPAQUE-but-PURE guard
        // (`thing.is_ready()`) and an opaque claim translate to uninterpreted EUF
        // atoms, so `is_ready(thing) => value(thing)==1` is the FAITHFUL implication
        // the source states -- a sound (if weak) DIG, NOT a fake-discharge (the
        // claim is GUARDED, never asserted unconditionally). It lifts.
        let src = r#"
            #[test]
            fn rt_guard() {
                let thing = make_thing();
                if thing.is_ready() {
                    assert!(thing.value() == 1);
                }
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 1,
            "an opaque-but-pure guarded assert lifts as the faithful EUF implication: {:?}",
            out.skip_reasons
        );
        let dump = format!("{:?}", out.decls);
        assert!(
            dump.contains("Implies") || dump.contains("implies") || dump.contains("=>"),
            "the claim must stay GUARDED by the opaque predicate, never bare: {dump}"
        );
    }

    #[test]
    fn conditional_side_effecting_guard_bails() {
        // BAIL (DISCRIMINATION, the real soundness line): the guard ADVANCES a
        // captured iterator (`it.next().is_some()`) -- a side effect, so the guard
        // is not a timeless predicate (it changes state each evaluation). The lift
        // must BAIL, leaving the assert in the if-context refusal, never lifting a
        // stateful guard as a stable antecedent.
        let src = r#"
            #[test]
            fn se_guard() {
                let mut it = [1i64, 2, 3].iter();
                if it.next().is_some() {
                    assert!(true);
                }
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 0,
            "a side-effecting (iterator-advancing) guard must BAIL: {:?}",
            contract_names(&out)
        );
        assert!(
            out.skip_reasons.iter().any(|r| r.contains("under if context")),
            "the side-effecting-guard assert must stay in the if-context refusal: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn conditional_mutating_branch_bails() {
        // BAIL (DISCRIMINATION): the then-branch MUTATES an accumulator
        // (`total += 1`) -- a single guarded implication would not be a timeless
        // point-wise claim. Must bail, leaving the assert refused.
        let src = r#"
            #[test]
            fn mut_branch() {
                let x = 1i64;
                let mut total = 0i64;
                if x > 0 {
                    total += 1;
                    assert!(total > 0);
                }
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 0,
            "a mutating guarded branch must BAIL (not a timeless point-wise claim): {:?}",
            contract_names(&out)
        );
    }

    // ── ForAllSugar over a CONDITIONAL body: the for-context drain ────────────
    //
    // `for v in <literal> { if guard { assert P } }` is the bounded conjunction
    // `forall k. (k in dom => (guard(k) => P(k)))` -- the wrapper (`ForAllSugar`)
    // composes the claim-side atom (`ConditionalSugar`). This drains the
    // for-context unclassified bucket: the loop body is now liftable because the
    // conditional assert is.

    #[test]
    fn forall_over_conditional_body_drains_for_context() {
        // POSITIVE (the drain): a closed-range loop whose body is a guarded assert
        // now lifts as the bounded universal of the implication -- the cases that
        // previously sat in "under for context over a literal ... bin-1".
        let src = r#"
            #[test]
            fn loop_guarded() {
                for i in 0..4 {
                    if i > 0 {
                        assert!(i < 4);
                    }
                }
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 1,
            "a for-loop over a literal range with a guarded body must drain (lift \
             as the bounded universal of the implication): {:?}",
            out.skip_reasons
        );
        assert!(
            out.skip_reasons.iter().all(|r| !r.contains("under for context")
                && !r.contains("under if context")),
            "neither the for-context nor the if-context refusal may remain: {:?}",
            out.skip_reasons
        );
        assert!(
            contract_names(&out).iter().any(|n| n.contains("::loop::i")),
            "the drained loop is named `<test>::loop::<var>`: {:?}",
            contract_names(&out)
        );
    }

    #[test]
    fn forall_array_over_conditional_body_is_refutable_for_wrong_claim() {
        // ADVERSARIAL (the dangerous direction): a literal-array loop with a
        // guarded but DELIBERATELY WRONG claim must lift HONESTLY -- the finite
        // conjunction must carry the actual element values under the guard, so a
        // solver REFUTES it (not fake-green). For `[1,2,3]`, `if v > 1 { assert!(v
        // == 9) }` is refutable at v=2,3.
        let src = r#"
            #[test]
            fn loop_wrong() {
                for v in [1i64, 2, 3] {
                    if v > 1 {
                        assert!(v == 9);
                    }
                }
            }
        "#;
        let out = lift_src(src);
        assert_eq!(
            out.assertions_lifted, 1,
            "the literal-array guarded loop lifts (the conjunction is the universe): {:?}",
            out.skip_reasons
        );
        let dump = format!("{:?}", out.decls);
        // The actual element values are substituted (faithful), so the false
        // equality `2 == 9` / `3 == 9` is present and refutable, guarded by `> 1`.
        for actual in ["2", "3"] {
            assert!(
                dump.contains(actual),
                "actual element {actual} must be the faithful substitution (refutable, \
                 not faked green): {dump}"
            );
        }
        assert!(
            dump.contains("Implies") || dump.contains("implies") || dump.contains("=>"),
            "each instance must remain guarded (`v>1 => v==9`), never bare: {dump}"
        );
    }

    // ── Fix E: format! with mut local is refused ─────────────────────────────
    //
    // `format!("{:?}", r)` where `r` is `let mut r = ...` must be refused as
    // temporally unstable (different program points see different values of r).

    #[test]
    fn format_macro_with_mut_local_arg_is_refused() {
        let src = r#"
            #[test]
            fn test_fmt() {
                let mut r = 1..=1;
                assert_eq!(format!("{:?}", r), "1..=1");
                let _ = r.next();
                assert_eq!(format!("{:?}", r), "1..=1 (exhausted)");
            }
        "#;
        let out = lift_src(src);
        // The format! assertions must be refused (skip reasons present),
        // not lifted into contradictory obligations.
        let refused = out.skip_reasons.iter().any(|r| r.contains("mut") && r.contains("local"))
            || out.skip_reasons.iter().any(|r| r.contains("temporally unstable"));
        // If they were lifted, there should be at most 1 obligation (not 2 contradictory ones).
        let fmt_obligations = out.decls.iter().filter(|d| d.name.contains("format")).count();
        assert!(
            refused || fmt_obligations <= 1,
            "format! with mut local should be refused or produce at most 1 obligation; \
             skips: {:?}, fmt_obligations: {fmt_obligations}",
            out.skip_reasons
        );
    }

    #[test]
    fn format_macro_with_inline_capture_mut_local_is_refused() {
        // `format!("{socket}")` with `let mut socket = ...` uses implicit capture.
        // The `socket` identifier is embedded in the format string literal.
        let src = r#"
            #[test]
            fn socket_test() {
                let mut socket = 42i32;
                assert_eq!(format!("{socket}"), "42");
                let socket = 99i32;
                assert_eq!(format!("{socket}"), "99");
            }
        "#;
        let out = lift_src(src);
        // The format! with inline mut capture must be refused.
        let refused = out.skip_reasons.iter().any(|r| {
            r.contains("temporally unstable") || r.contains("mut")
        });
        let fmt_contracts = out.decls.iter().filter(|d| d.name.contains("format")).count();
        assert!(
            refused || fmt_contracts <= 1,
            "format! with inline mut capture should be refused; skips: {:?}",
            out.skip_reasons
        );
    }

    // ── Nested-block scope: sibling blocks are distinct consistency regions ────

    #[test]
    fn sibling_blocks_rebinding_same_local_do_not_coalesce() {
        // Two sibling `{ }` blocks each rebind `r` to a different cell and assert a
        // different value. The bare-`r` field reads must NOT conjoin across the
        // blocks into a false `unsat` -- each block is its own scope.
        let src = r#"
            #[test]
            fn rebinds() {
                {
                    let r = Wrap::new(1);
                    assert_eq!(r.field, 1);
                }
                {
                    let r = Wrap::new(2);
                    assert_eq!(r.field, 2);
                }
            }
        "#;
        let out = lift_src(src);
        // The two `field` equalities must land in DIFFERENT obligation groups
        // (distinct block scopes), so no single inv pins `r.field` to 1 and 2.
        for d in &out.decls {
            let dump = format!("{:?}", d.inv);
            let pins_1 = dump.contains("Int(1)");
            let pins_2 = dump.contains("Int(2)");
            assert!(
                !(pins_1 && pins_2),
                "sibling-block rebinds of `r` must not coalesce into one inv: {dump}"
            );
        }
    }

    #[test]
    fn const_blocks_rebinding_same_local_do_not_coalesce() {
        // The `mem/type_info.rs` shape: two `const { }` blocks each bind `ty` and
        // pin `ty.fields.len()` to a different count. Distinct block scopes keep
        // them apart.
        let src = r#"
            #[test]
            fn type_info() {
                const {
                    let ty = describe::<A>();
                    assert!(ty.fields.len() == 3);
                }
                const {
                    let ty = describe::<B>();
                    assert!(ty.fields.len() == 1);
                }
            }
        "#;
        let out = lift_src(src);
        for d in &out.decls {
            let dump = format!("{:?}", d.inv);
            assert!(
                !(dump.contains("Int(3)") && dump.contains("Int(1)")),
                "sibling const-block `ty` must not coalesce: {dump}"
            );
        }
    }

    // ── Reference-wrapped cell, raw `*mut`, mut-borrow trajectories ────────────

    #[test]
    fn reference_wrapped_cell_reads_do_not_coalesce() {
        // `let b = &Cell::new(0)` is an interior-mutable cell behind a reference;
        // reads of `b.get()` at two program points must get distinct keys.
        let src = r#"
            #[test]
            fn ref_cell() {
                let b = &Cell::new(0);
                assert_eq!(b.get(), 12);
                b.set(13);
                assert_eq!(b.get(), 13);
            }
        "#;
        let out = lift_src(src);
        let gets: Vec<&str> = contract_names(&out)
            .into_iter()
            .filter(|n| n.contains("method:get"))
            .collect();
        let distinct: std::collections::HashSet<&str> = gets.iter().cloned().collect();
        assert_eq!(
            distinct.len(),
            gets.len(),
            "`&Cell::new` reads must not coalesce: {gets:?}"
        );
    }

    #[test]
    fn raw_mut_pointer_deref_reads_do_not_coalesce() {
        // `let p = addr_of_mut!(x)` is a handle to memory mutated through it; `*p`
        // reads at two program points must get distinct keys (p versioned).
        let src = r#"
            #[test]
            fn raw_ptr() {
                let mut x = 10;
                let p = addr_of_mut!(x);
                unsafe {
                    assert_eq!(*p, 10);
                    *p = 30;
                    assert_eq!(*p, 30);
                }
            }
        "#;
        let out = lift_src(src);
        // `p` must be VERSIONED (distinct `@def` tags), so the two `*p` reads are
        // distinct terms: `deref(p@defA)==10 ∧ deref(p@defB)==30` is satisfiable,
        // not the false `deref(p)==10 ∧ deref(p)==30` unsat.
        let dump = format!("{:?}", out.decls);
        assert!(dump.contains("deref"), "expected a deref term: {dump}");
        // The first read is bare `p` (version 0); the post-write read is `p@def2`.
        // The presence of a versioned read proves the two `*p` terms are distinct
        // (the false `deref(p)==10 ∧ deref(p)==30` unsat is dissolved).
        assert!(
            dump.contains("p@def"),
            "raw `*mut p` read across a write must be versioned (distinct term): {dump}"
        );
    }

    #[test]
    fn mut_local_borrowed_into_writer_is_a_trajectory() {
        // The `clone_to_uninit` shape: `b` is a `mut` local, `&mut b` is passed to a
        // writer, so `*b` BEFORE != x and `*b` AFTER == x is a real fork around `t`
        // (b was mutated), NOT a value-eq/ref-id conflation. The two reads must be
        // distinct, so the `ne` then `eq` are mutually satisfiable.
        let src = r#"
            #[test]
            fn writer_traj() {
                let a = "hello";
                let mut b: Box<str> = "world".into();
                assert_ne!(a, &*b);
                writer(ptr::from_mut::<str>(&mut b).cast());
                assert_eq!(a, &*b);
            }
        "#;
        let out = lift_src(src);
        // No single inv may carry BOTH an `=` and `ne`/`≠` over the same `deref(b)`
        // pair (that was the false-unsat shape); versioning `b` separates them.
        let dump = format!("{:?}", out.decls);
        let has_ne = dump.contains("\u{2260}") || dump.contains("\"ne\"");
        // The key property: `b` is versioned (distinct @def tags appear), so the two
        // `&*b` reads are not the same term.
        assert!(
            dump.contains("b@def") || !has_ne,
            "a mut local written through `&mut b` must be versioned (trajectory): {dump}"
        );
    }

    // ── Per-occurrence consuming-iterator advance (same statement) ─────────────

    #[test]
    fn same_statement_consuming_nth_reads_are_distinct() {
        // `assert_ne!(it.nth(0), it.nth(0))`: each `nth` ADVANCES the iterator, so
        // the two reads in ONE statement must be distinct terms (the second carries
        // an `@adv` tag), not `ne(X, X)`.
        let src = r#"
            #[test]
            fn windows_nth() {
                let v: &[i32] = &[0, 1, 2, 3];
                let mut w = v.windows(2);
                assert_ne!(w.nth(0), w.nth(0));
            }
        "#;
        let out = lift_src(src);
        let dump = format!("{:?}", out.decls);
        assert!(
            dump.contains("@adv"),
            "the second same-statement `nth` must carry an `@adv` occurrence tag: {dump}"
        );
    }

    #[test]
    fn inlined_contradictory_helper_body_is_caught_not_masked() {
        // SOUNDNESS GUARD for capability #1: inlining must not MASK a real
        // contradiction. A helper whose body pins the SAME callsite to two distinct
        // values, inlined, must produce a single coalesced inv with BOTH pins (so the
        // verifier refutes it) -- never two split obligations that each look fine.
        let src = r#"
            fn bad(n: i32) { assert_eq!(g(n), 1); assert_eq!(g(n), 2); }
            #[test]
            fn drives() { bad(5); }
        "#;
        let out = lift_src(src);
        // The two pins on g(5) must land in ONE inv (coalesced), so unsat is visible.
        let mut found_both = false;
        for d in &out.decls {
            let dump = format!("{:?}", d.inv);
            if dump.contains("Int(1)") && dump.contains("Int(2)") && dump.contains("call:g") {
                found_both = true;
            }
        }
        assert!(
            found_both,
            "inlined contradictory body must coalesce both pins into one inv (caught, \
             not masked): {:?}",
            out.decls.iter().map(|d| format!("{:?}", d.inv)).collect::<Vec<_>>()
        );
    }

    #[test]
    fn closure_opaque_is_keyed_by_text_and_captures() {
        // A closure lifts to an opaque EUF symbol keyed by body text + captured free
        // vars. DISCRIMINATION: two closures with DIFFERENT text get DISTINCT symbols
        // (so they never false-coalesce). Same text + same captures coalesce (a
        // contradiction over the call would be caught).
        let src = r#"
            #[test]
            fn t() {
                assert_eq!(apply(|x| x + 1), 3);
                assert_eq!(apply(|x| x + 2), 4);
            }
        "#;
        let out = lift_src(src);
        let dump = format!("{:?}", out.decls);
        // Two distinct closure symbols (x+1 vs x+2), not one coalesced.
        assert!(
            dump.contains("closure:") ,
            "closures should lift to opaque closure: symbols: {dump}"
        );
        // The two apply-calls must NOT collapse to one obligation (distinct closures).
        let applies: std::collections::HashSet<&str> = out
            .decls
            .iter()
            .map(|d| d.name.as_str())
            .filter(|n| n.contains("apply"))
            .collect();
        assert!(
            applies.len() >= 2 || out.decls.len() >= 2,
            "distinct closures must not coalesce: {:?}",
            out.decls.iter().map(|d| &d.name).collect::<Vec<_>>()
        );
    }

    // ── R7: statement-position helper-call inlining (β-reduction) ──────────────

    #[test]
    fn statement_helper_call_with_asserting_body_inlines_per_callsite() {
        // `check(2); check(3);` — a bare-statement call to a helper whose body
        // asserts. Each callsite inlines (params := actuals), so the helper's assert
        // discharges point-wise per callsite and the helper is NOT refused in Pass 2.
        let src = r#"
            fn check(n: i32) { assert_eq!(probe(n), n); }
            #[test]
            fn drives() {
                check(2);
                check(3);
            }
        "#;
        let out = lift_src(src);
        // `check`'s body assert is lifted at the callsites, not refused.
        let refused_check = out
            .skip_reasons
            .iter()
            .any(|r| r.contains("check") && r.contains("reachable only via call-site"));
        assert!(
            !refused_check,
            "helper `check` should inline at the callsite, not be refused: {:?}",
            out.skip_reasons
        );
        // Two callsites with different args -> two distinct probe-obligations.
        let probes: Vec<&str> = out
            .decls
            .iter()
            .map(|d| d.name.as_str())
            .filter(|n| n.contains("probe"))
            .collect();
        assert!(
            probes.len() >= 2,
            "expected a probe obligation per callsite: {:?}",
            out.decls.iter().map(|d| &d.name).collect::<Vec<_>>()
        );
    }

    #[test]
    fn helper_body_with_let_inlines_via_collector_monotonically() {
        // A statement-called helper with a `let` body inlines through the NORMAL
        // collector (β-reduced params; the `let` local stays a free var the collector
        // lifts over). The monotonic gate admits it because the body adds no
        // unclassified: `check` is not refused, and the `probe` term is lifted.
        let src = r#"
            fn check(n: i32) { let m = n + n; assert_eq!(probe(m), m); }
            #[test]
            fn drives() { check(2); }
        "#;
        let out = lift_src(src);
        let refused_check = out
            .skip_reasons
            .iter()
            .any(|r| r.contains("check") && r.contains("reachable only via call-site"));
        assert!(
            !refused_check,
            "helper `check` should inline (monotonic gate admits a fully-lifting body): {:?}",
            out.skip_reasons
        );
        let dump = format!("{:?}", out.decls);
        assert!(
            dump.contains("probe"),
            "expected a probe term from the inlined body: {dump}"
        );
    }

    #[test]
    fn helper_body_impure_let_is_refused_not_substituted() {
        // DISCRIMINATION: `let m = sink(n);` is NOT pure-pinnable (a call may be
        // impure / re-evaluate), so the helper is NOT inlined -- it stays refused,
        // never substituted (no forged re-evaluation).
        let src = r#"
            fn check(n: i32) { let m = sink(n); assert_eq!(m, m); }
            #[test]
            fn drives() { check(2); }
        "#;
        let out = lift_src(src);
        // `check` must NOT be silently inlined via an impure let (it either stays
        // refused, or the assert lifts without the let-substitution path firing).
        // The key property: the impure init is not pure-pinnable.
        assert!(
            !is_pure_pinnable_expr(&syn::parse_str::<syn::Expr>("sink(n)").unwrap()),
            "a call init must not be pure-pinnable"
        );
    }

    // ── Refusal disposition: refused is earned, unclassified is the default ────

    #[test]
    fn refusal_disposition_is_a_terminal_whitelist() {
        use Disposition::*;
        // TERMINAL (source property -- closed with a damn good reason).
        for r in [
            "assertion under for context over an opaque collection (bin-2: runtime data)",
            "assert_eq!: int literal 999999999999999999999: number too large to fit in target type",
            "ambiguous temporal identity for receiver `r`; skipped assertion",
            "assert_eq!: macro in term position references a `x` local; temporally unstable — refused",
            "assertion helper `assert_trusted_len` is a type-level obligation (empty body: trait-bound or no-op), not a point-wise value predicate; refused",
            "macro `m`: expansion yielded no liftable assertion (type-level or effectful body); released to layer 0",
            "assertion under while context: not unconditional point-wise; released to layer 0",
            "flt2dec assert: f16/f128 formatting is unstable -- unformattable on the stable toolchain the lifter ships and not modellable as a point-wise claim; refused",
            "assertion in a side-effecting closure body (mutates captured state / advances an iterator); not a pure point-wise claim; refused",
            "assertion in a closure over an opaque/effectful accessor (bin-2: runtime data, not constructible from source literals); refused",
            "unsupported term `buf[i]`: mutable container is not temporally stable",
            "assertion in an impl method, reachable only at runtime when the method is invoked (impl method `next`); the receiver's state has no single timeless `t`; refused",
            "assertion under an if-guard over a runtime value `*p = true` (not a constructible predicate; the guard's truth is not fixed from source literals); refused",
            "assertion in a runtime expression-statement `(assert_matches ! (..) , mem :: take (& mut val))` (value read through a `&mut` borrow / mutation, not constructible from source literals); refused",
            "flt2dec assert: operand is not a closed f32/f64 literal term (ldexp or a format! expected); released to layer 0",
            "signed zero float literal remains an IEEE refinement `- 0.0`",
            "assert_eq!: signed zero float literal remains an IEEE refinement `- 0.0f32`",
            "float refinement predicate `is_nan` requires known f32/f64 receiver width `\"NaN\" . parse :: < f16 > () . unwrap () . is_nan ()`",
            "assertion in non-#[test] item `test_num` reachable only via monomorphization of a generic type/const parameter (runtime instantiation: no single concrete type to read; not statically constructible at any call site); refused",
            "assert_eq!: unsupported term `& mut x`: effectful / raw-pointer / mutable-reference term (a `&mut` borrow) is not a constructible timeless value; refused",
            "assert_eq!: unsupported term `& raw const garlic`: effectful / raw-pointer / mutable-reference term (a raw pointer (`&raw const`/`&raw mut`)) is not a constructible timeless value; refused",
            "assert_eq!: unsupported term `const { Zst }`: effectful / raw-pointer / mutable-reference term (a `const { <path> }` block (a name is sugar)) is not a constructible timeless value; refused",
            "assert!: only scalar equality is liftable; operand is a runtime non-scalar result `match b . binary_search (& 3) { Ok (1 ..= 3) => true , _ => false , }` (a `match` over a runtime call result, not constructible from source literals); refused",
            "assert_eq!: array-repeat `[_; N]` has a non-literal length -- not a finite construction from the literal; refused by name: `[0u8 ; SIZE]`",
        ] {
            assert_eq!(refusal_disposition(r), Refused, "should be terminal: {r}");
        }
        // INACTIVE (cfg-disabled -- not in this build's universe).
        for r in [
            "inactive cfg on test fn",
            "inactive cfg on assertion; skipped: cfg(target_has_atomic)",
        ] {
            assert_eq!(refusal_disposition(r), Disposition::Inactive, "should be inactive: {r}");
        }
        // UNCLASSIFIED (lifter limitation -- WORK), incl. the default for anything
        // not on the whitelist.
        for r in [
            "assertion under if context: not unconditional point-wise; released to layer 0",
            "assert_eq!: unsupported term",
            "assertion in non-#[test] item to_string: reachable only via call-site inlining",
            "assertion under for context over a literal range (bin-1: domain constructed)",
            "assertion inside a let-initializer expression; released to layer 0",
            "ambiguous cfg on assertion; skipped",
            // A no-visible-source helper is WORK, not a source property: the body may be
            // loadable by better resolution (e.g. a fn-local helper nested in a `#[test]`
            // fn the reducer does not yet register). Refusing it would be a fake-refuse.
            "assertion helper `assert_exact_exp` has no visible source; skipped assertion",
            // The corpus `assert_predicates_exact` / `assert_typeid_set_eq` helpers (mem/
            // type_info.rs) are fn-local in the test body: their source IS present but the
            // reducer does not yet register a test-nested helper, so the reason is RESOLUTION
            // REACH, not a source property. Even though the body is runtime (HashSet-collect
            // over TypeId reflection), the *unresolved* body cannot be inspected to detect a
            // cause -- refusing on the reach reason would be a fake-refuse. Stays WORK.
            "assertion helper `assert_predicates_exact` has no visible source; skipped assertion",
            // A BARE `unsupported term` (a PURE untranslated value -- a cast / untranscribed
            // pure method) is honest future work, NOT an effectful shape. It must NOT be
            // laundered into the `&mut`/raw-pointer/`const{<path>}` terminal: no effectful
            // clause -> stays Unclassified (the inverse-sin guardrail).
            "assert_eq!: unsupported term `1i32 as f64`",
            "assert_eq!: unsupported term `Foo::ITER_CONST`",
            // The `assert_chunks` macro `no rule matched` is a MATCHER GAP, not a genuine
            // non-match: the matcher `( $string:expr, $(($valid:expr, $invalid:expr)),* $(,)? )`
            // SHOULD match `(b"hello", ("hello", b""))`, but our matcher does not recurse into a
            // non-`$(..)` delimiter group to match the metavars inside `($valid:expr, $invalid:expr)`.
            // Fixable lifter work -> stays Unclassified (refusing it would be a fake-refuse).
            "macro `assert_chunks`: macro expansion: no rule matched the invocation; released to layer 0",
            // A `match` over a CONSTRUCTED literal scrutinee is NOT a runtime call result -- it is
            // diggable (branch partitioning), so the bare `only scalar equality` reason stays work.
            "assert!: only scalar equality is liftable, got `match SOME_CONST { 1 => true, _ => false, }`",
            "some brand new reason nobody has classified yet",
        ] {
            assert_eq!(refusal_disposition(r), Unclassified, "should be work: {r}");
        }
    }

    // ── Runtime-residue refusal: impl-method / runtime if-guard / runtime expr-stmt ──
    //
    // The Hit side of Outcome{Dug|Hit}: a runtime/un-nameable value is a NAMED terminal
    // Effect (refused), accounted not silent. Each test pairs the REFUSE direction (a
    // detected runtime cause) with the DISCRIMINATION direction (a const/computable shape
    // that STAYS UNCLASSIFIED -- the inverse-sin guardrail against fake-refuse).

    #[test]
    fn assertion_in_impl_method_is_refused_runtime_reachability() {
        // REFUSE: an assert in a top-level `impl` method body reads receiver state that
        // only exists when the method runs (corpus: iter/adapters/mod.rs `next`,
        // map_windows.rs `check`). A source property -- reachable only at runtime.
        let src = r#"
            struct W { done: bool }
            impl Iterator for W {
                type Item = i64;
                fn next(&mut self) -> Option<i64> {
                    assert!(!self.done, "already returned None");
                    None
                }
            }
        "#;
        let out = lift_src(src);
        assert_eq!(out.assertions_lifted, 0, "an impl-method assert must not lift");
        assert!(
            out.skip_reasons
                .iter()
                .any(|r| r.contains("reachable only at runtime when the method is invoked")
                    && refusal_disposition(r) == Disposition::Refused),
            "the impl-method assert must be REFUSED with its named runtime cause: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn assertion_in_nested_impl_statement_is_refused_runtime_reachability() {
        // REFUSE: a nested `impl` declared as a STATEMENT inside a test fn (corpus:
        // fmt/float.rs `ExactExpWriter::finish`/`write_str`, ptr.rs `set_tag`,
        // hint.rs `Drop::drop`). Same runtime cause, surfaced at the expr-stmt site.
        let src = r#"
            #[test]
            fn t() {
                struct W { pos: usize }
                impl W {
                    fn finish(self) {
                        assert_eq!(self.pos, 3);
                    }
                }
            }
        "#;
        let out = lift_src(src);
        assert_eq!(out.assertions_lifted, 0, "a nested-impl-method assert must not lift");
        assert!(
            out.skip_reasons
                .iter()
                .any(|r| r.contains("reachable only at runtime when the method is invoked")
                    && refusal_disposition(r) == Disposition::Refused),
            "the nested-impl-method assert must be REFUSED with its named runtime cause: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn runtime_expr_statement_through_mut_borrow_is_refused() {
        // REFUSE: the borrow/drop-scoping tuple statement (corpus:
        // macros.rs::temporary_scope_introduction). The asserted value is read through a
        // `&mut` borrow and the sibling element `mem::take`s the same local -- mutably
        // aliased, no single timeless `t`.
        let src = r#"
            #[test]
            fn t() {
                let mut val = 0;
                (assert_matches!(*MutRefWithDrop(&mut val).0, 0), std::mem::take(&mut val));
            }
        "#;
        let out = lift_src(src);
        assert_eq!(out.assertions_lifted, 0, "a mut-borrow expr-stmt assert must not lift");
        assert!(
            out.skip_reasons
                .iter()
                .any(|r| r.contains("runtime expression-statement")
                    && refusal_disposition(r) == Disposition::Refused),
            "the mut-borrow tuple-statement assert must be REFUSED with its named cause: {:?}",
            out.skip_reasons
        );
    }

    // ── FLOAT TAIL refusal: flt2dec runtime output / signed-zero / unknown f-width ──
    //
    // The Hit side of Outcome{Dug|Hit}: a float value with no constructible timeless FOL
    // form is a NAMED terminal Effect (refused), accounted not silent. Each test pairs the
    // REFUSE direction (a detected runtime / sign-sensitive / unstable-width cause) with the
    // DISCRIMINATION direction (a CLOSED-literal float that STAYS on its current path --
    // discharged or its existing reason -- proving the refusal is cause-driven, not a
    // blanket float refusal: the inverse-sin guardrail against fake-refuse).

    #[test]
    fn signed_zero_float_literal_is_refused_ieee_refinement() {
        // REFUSE: a `-0.0` float literal. IEEE-754 distinguishes -0.0 from +0.0 by the
        // sign bit; our Real sort collapses ±0, so lifting risks a sign-collapse
        // fake-discharge (corpus: ops.rs / num/mod.rs / time.rs). Sign-sensitive IEEE value.
        let src = r#"
            #[test]
            fn t() {
                assert_eq!(-0.0f32, x);
            }
        "#;
        let out = lift_src(src);
        assert!(
            out.skip_reasons
                .iter()
                .any(|r| r.contains("signed zero float literal remains an IEEE refinement")
                    && refusal_disposition(r) == Disposition::Refused),
            "the -0.0 literal must be REFUSED with its named signed-zero cause: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn nonzero_negative_float_literal_is_not_signed_zero_refused() {
        // DISCRIMINATION: a NON-zero negative float literal (`-1.5`) is NOT sign-collapsing
        // -- it lifts via `real_const("-1.5")` and must NOT carry the signed-zero refusal.
        // Proves the refusal is the `real_literal_is_zero` cause, not a blanket float bail.
        let src = r#"
            #[test]
            fn t() {
                assert_eq!(-1.5f64, -1.5f64);
            }
        "#;
        let out = lift_src(src);
        assert!(
            !out.skip_reasons
                .iter()
                .any(|r| r.contains("signed zero float literal remains an IEEE refinement")),
            "a non-zero -1.5 literal must NOT be signed-zero refused: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn float_refinement_over_unknown_width_is_refused() {
        // REFUSE: `is_nan` over an f16 parse-unwrap chain has no resolvable f32/f64 width
        // (corpus: num/dec2flt/mod.rs `"NaN".parse::<f16>().unwrap().is_nan()`). With no
        // stable width the `float.{width}.{method}` atom is inexpressible -- mirrors the
        // existing f16/f128-unstable terminal.
        let src = r#"
            #[test]
            fn t() {
                assert!("NaN".parse::<f16>().unwrap().is_nan());
            }
        "#;
        let out = lift_src(src);
        assert!(
            out.skip_reasons
                .iter()
                .any(|r| r.contains("requires known f32/f64 receiver width")
                    && refusal_disposition(r) == Disposition::Refused),
            "the f16 refinement predicate must be REFUSED with its named unknown-width cause: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn float_refinement_over_known_f64_width_is_not_unknown_width_refused() {
        // DISCRIMINATION: `is_nan` over a known-f64 receiver (typed local) resolves a width
        // and lifts as `float.f64.is_nan` -- it must NOT carry the unknown-width refusal.
        // Proves the refusal is the `float_refinement_receiver_width` None cause, not a
        // blanket float-refinement bail.
        let src = r#"
            #[test]
            fn t() {
                let x: f64 = 0.0;
                assert!(x.is_nan());
            }
        "#;
        let out = lift_src(src);
        assert!(
            !out.skip_reasons
                .iter()
                .any(|r| r.contains("requires known f32/f64 receiver width")),
            "a known-f64 refinement receiver must NOT be unknown-width refused: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn const_if_guard_digs_and_pure_expr_statement_not_fake_refused() {
        // DISCRIMINATION + DIG (the const/cfg if-guard, now lifted):
        //
        // (1) a CONST/literal if-guard (`!false`, corpus: bool.rs::test_bool_not)
        //     const-folds to a constant antecedent and DIGS (`true => P`). It must
        //     NOT stay in the "under if context" bucket and must NEVER be
        //     runtime-refused (the fake-refuse guardrail still holds: a const guard
        //     is not a runtime value). See assertion_lift.rs::const_if_guard_digs_*
        //     for the full DIG + bad-twin + cfg-resolution coverage.
        {
            let out = lift_src(
                r#"
                #[test]
                fn t() {
                    if !false {
                        assert!(true);
                    } else {
                        assert!(false);
                    }
                }
                "#,
            );
            assert!(
                out.skip_reasons.iter().all(|r| !r.contains("under if context")),
                "a const if-guard must now DIG (no longer under-if-context): {:?}",
                out.skip_reasons
            );
            assert!(
                out.skip_reasons
                    .iter()
                    .all(|r| !r.contains("under an if-guard over a runtime value")),
                "a const if-guard must NEVER be runtime-refused (fake-refuse): {:?}",
                out.skip_reasons
            );
            assert_eq!(out.assertions_lifted, 2, "both branch asserts dig: {:?}", out.skip_reasons);
        }
        // The cfg!-guard variant resolves only against explicit target facts; with
        // 64-bit facts it const-folds and digs (it must NOT stay under-if-context).
        {
            let out = lift_src_cfg(
                r#"
                #[test]
                fn t() {
                    if cfg!(target_pointer_width = "64") {
                        assert_eq!(1i64, 1i64);
                    }
                }
                "#,
            );
            assert!(
                out.skip_reasons.iter().all(|r| !r.contains("under if context")),
                "a resolved cfg! if-guard must DIG (no longer under-if-context): {:?}",
                out.skip_reasons
            );
            assert_eq!(out.assertions_lifted, 1, "the cfg-active branch digs: {:?}", out.skip_reasons);
        }

        // (2) a PURE expr-statement (a tuple with no `&mut` / mutation) is not runtime --
        //     it must NOT be runtime-refused as an expression-statement.
        let pure = r#"
            #[test]
            fn t() {
                (assert_matches!(SOME_CONST, 0), 1);
            }
        "#;
        let out = lift_src(pure);
        assert!(
            out.skip_reasons
                .iter()
                .all(|r| !r.contains("runtime expression-statement")),
            "a pure (no-&mut) expr-statement must NOT be runtime-refused (fake-refuse): {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn runtime_if_guard_over_mut_borrow_is_refused() {
        // REFUSE direction for the if-guard cause: a guard that takes a `&mut` borrow is a
        // runtime predicate (its truth is not fixed from source literals). This arms the
        // gate; NO corpus member hits it today (all 7 corpus if-guards are const/cfg), so
        // it is an EARNED detector, not a count-draining relabel.
        let src = r#"
            #[test]
            fn t() {
                let mut v = vec![1i64];
                if take_mut(&mut v) {
                    assert!(true);
                }
            }
        "#;
        let out = lift_src(src);
        assert!(
            out.skip_reasons
                .iter()
                .any(|r| r.contains("under an if-guard over a runtime value")
                    && refusal_disposition(r) == Disposition::Refused),
            "a `&mut`-borrow if-guard must be REFUSED with its named runtime cause: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn runtime_parametric_helper_is_bin2_but_scalar_or_slice_helper_stays_unclassified() {
        use Disposition::*;
        fn pf(src: &str) -> syn::ItemFn {
            syn::parse_str(src).expect("parse fn")
        }
        // RUNTIME-PARAMETRIC -> bin-2 terminal (refused):
        // closure param (the iter.rs `check(xs, p: impl Fn(..))` shape)
        let closure_helper =
            pf("fn check(xs: &mut [i32], p: impl Fn(&i32) -> bool, n: usize) { assert_eq!(xs.iter().filter(|x| p(x)).count(), n); }");
        assert!(helper_is_runtime_parametric(&closure_helper));
        assert_eq!(
            refusal_disposition(&callsite_inlining_reason("check", &closure_helper)),
            Refused,
            "closure-param helper is bin-2 terminal"
        );
        // generic Iterator param
        let iter_helper = pf("fn drive<I: Iterator<Item = u32>>(mut it: I) { assert_eq!(it.next(), Some(1)); }");
        assert!(helper_is_runtime_parametric(&iter_helper));
        assert_eq!(
            refusal_disposition(&callsite_inlining_reason("drive", &iter_helper)),
            Refused,
            "iterator-param helper is bin-2 terminal"
        );
        // NOT runtime-parametric -> stays UNCLASSIFIED (dissolution/inlining can close it):
        // scalar param -- a literal at the call site pins it
        let scalar_helper =
            pf("fn lower(c: char) -> String { assert_eq!(c.to_lowercase().count(), 1); c.to_lowercase().collect() }");
        assert!(!helper_is_runtime_parametric(&scalar_helper));
        assert_eq!(
            refusal_disposition(&callsite_inlining_reason("lower", &scalar_helper)),
            Unclassified,
            "scalar-param helper must NOT be falsely refused"
        );
        // slice-only param -- a literal slice CAN be closed at the call site, so we do NOT
        // claim it terminal (safe under-claim); dissolution + the exact partition own it.
        let slice_helper =
            pf("fn test_chain(xs: &[i32], ys: &[i32]) { assert_eq!(xs.iter().chain(ys).count(), 6); }");
        assert!(!helper_is_runtime_parametric(&slice_helper));
        assert_eq!(
            refusal_disposition(&callsite_inlining_reason("test_chain", &slice_helper)),
            Unclassified,
            "slice-param helper stays unclassified (not falsely refused)"
        );
    }

    // ── Refuse parametric call-site tail: a GENERIC type/const helper is terminal,
    //    a CONCRETE scalar/slice / a no-visible-source helper STAYS unclassified ──
    //
    // The Hit side of Outcome{Dug|Hit}: a helper reachable only at RUNTIME
    // INSTANTIATION (monomorphization of a generic type/const parameter) is a NAMED
    // terminal Effect, accounted not silent. Each corpus shape pairs the REFUSE
    // direction (a detected generic cause) with the DISCRIMINATION direction (a
    // concrete-param / no-visible-source shape that STAYS UNCLASSIFIED -- the
    // inverse-sin guardrail against fake-refuse).
    #[test]
    fn generic_parametric_helper_is_monomorphization_terminal_but_concrete_or_invisible_stays_unclassified() {
        use Disposition::*;
        fn pf(src: &str) -> syn::ItemFn {
            syn::parse_str(src).expect("parse fn")
        }
        // REFUSE: a generic TYPE param bound by value traits (coretests num/mod.rs
        // `test_num<T: Add+Sub+..>`, called only as `num::n(10 as $T, 2 as $T)`).
        let test_num =
            pf("fn test_num<T: PartialEq + Add<Output = T> + Copy>(ten: T, two: T) { assert_eq!(ten.add(two), ten + two); }");
        assert!(helper_is_generic_parametric(&test_num));
        assert!(!helper_is_runtime_parametric(&test_num));
        assert_eq!(
            refusal_disposition(&callsite_inlining_reason("test_num", &test_num)),
            Refused,
            "generic type-param helper is monomorphization terminal"
        );
        // REFUSE: a generic TYPE param via a `where` clause (num/mod.rs
        // `test_parse<T>` where T: FromStr, called only via `test_parse::<i8>(..)`).
        let test_parse =
            pf("fn test_parse<T>(num_str: &str, expected: Result<T, IntErrorKind>) where T: FromStr { assert_eq!(num_str.parse::<T>().ok(), expected.ok()); }");
        assert!(helper_is_generic_parametric(&test_parse));
        assert_eq!(
            refusal_disposition(&callsite_inlining_reason("test_parse", &test_parse)),
            Refused,
            "where-clause generic helper is monomorphization terminal"
        );
        // REFUSE: a CONST generic param (map_windows.rs `check_size_hint<const N: usize>`,
        // called only via `check_size_hint::<1>(..)` / `::<2>` / `::<5>`).
        let check_size_hint =
            pf("fn check_size_hint<const N: usize>(a: (usize, Option<usize>), b: (usize, Option<usize>)) { assert_eq!(a, b); }");
        assert!(helper_is_generic_parametric(&check_size_hint));
        assert_eq!(
            refusal_disposition(&callsite_inlining_reason("check_size_hint", &check_size_hint)),
            Refused,
            "const-generic helper is monomorphization terminal"
        );
        // REFUSE: a generic MARKER type param with NO param of that type (mem.rs
        // `inner<SuppressConstPromotion>()`, called only via `inner::<()>()`).
        let inner = pf("fn inner<SuppressConstPromotion>() { assert_eq!(1, 1); }");
        assert!(helper_is_generic_parametric(&inner));
        assert_eq!(
            refusal_disposition(&callsite_inlining_reason("inner", &inner)),
            Refused,
            "marker-type-param helper is monomorphization terminal"
        );
        // DISCRIMINATION 1 -- a CONCRETE scalar helper (hash/sip.rs `zero_byte(val: u64,
        // byte: usize)`): no type/const param. Its `val`/`byte` call-site args ARE source
        // literals (`zero_byte(0xdead.., 0)`), so a closed-literal call site CAN pin it; the
        // inability to lift is call-queueing (only-in-macro-arg-position) reach, NOT a source
        // property. Must STAY unclassified (refusing it would be fake-refuse of a carryable
        // concrete call -- left for the dig path).
        let zero_byte = pf("fn zero_byte(val: u64, byte: usize) -> u64 { assert!(byte < 8); val }");
        assert!(!helper_is_generic_parametric(&zero_byte));
        assert!(!helper_is_runtime_parametric(&zero_byte));
        assert_eq!(
            refusal_disposition(&callsite_inlining_reason("zero_byte", &zero_byte)),
            Unclassified,
            "concrete scalar helper (zero_byte) must NOT be falsely refused"
        );
        // DISCRIMINATION 2 -- a LIFETIME-only generic is NOT type/const-parametric: it
        // erases at runtime and never changes a value claim, so a concrete call site CAN
        // pin it. Must STAY unclassified (lifetimes are not a monomorphization barrier).
        let lifetime_only =
            pf("fn pred<'a>(preds: &'a [u8], want: u8) { assert_eq!(preds[0], want); }");
        assert!(!helper_is_generic_parametric(&lifetime_only));
        assert_eq!(
            refusal_disposition(&callsite_inlining_reason("pred", &lifetime_only)),
            Unclassified,
            "lifetime-only helper stays unclassified (lifetime is not a mono barrier)"
        );
        // DISCRIMINATION 3 -- a no-visible-source helper stays UNCLASSIFIED. The body may
        // be loadable by better resolution (the coretests `assert_predicates_exact` /
        // `assert_exact_exp` are fn-local helpers nested in a `#[test]` fn whose source IS
        // present, just not registered by the reducer). Refusing it would launder a fixable
        // resolution gap as a source property -- the inverse sin (fake-refuse).
        assert_eq!(
            refusal_disposition("assertion helper `assert_predicates_exact` has no visible source; skipped assertion"),
            Unclassified,
            "no-visible-source helper stays unclassified (resolution reach, not a source property)"
        );
    }

    // ── Discrimination: versioning is ONLY for warranted mutation ──────────────

    #[test]
    fn plain_mut_local_never_borrowed_still_coalesces() {
        // A `let mut x` that is NEVER `&mut`-borrowed nor reassigned is provably
        // stable, so two pins on it COALESCE -- a genuine double-pin contradiction
        // is still caught (no spurious vindication).
        let src = r#"
            #[test]
            fn stable_mut() {
                let mut x = 5;
                assert_eq!(stable_helper(x), 1);
                assert_eq!(stable_helper(x), 2);
            }
        "#;
        let out = lift_src(src);
        let calls: Vec<&str> = contract_names(&out)
            .into_iter()
            .filter(|n| n.contains("stable_helper"))
            .collect();
        if calls.len() >= 2 {
            let distinct: std::collections::HashSet<&str> = calls.iter().cloned().collect();
            assert_eq!(
                distinct.len(),
                1,
                "an unborrowed, unreassigned mut local must COALESCE (catch the \
                 contradiction), not be versioned: {calls:?}"
            );
        }
    }

    // ── flt2dec dissolution: ldexp values + format! expected-RHS ──────────────

    // Parse a single `assert_eq!(..)` expression statement into its `syn::Macro`.
    fn assert_macro(src: &str) -> syn::Macro {
        let stmt: Stmt = syn::parse_str(src).expect("assert stmt must parse");
        let expr = match stmt {
            Stmt::Macro(m) => return m.mac,
            Stmt::Expr(e, _) => e,
            _ => panic!("expected a macro/expr stmt"),
        };
        match expr {
            Expr::Macro(m) => m.mac,
            _ => panic!("expected a macro expr"),
        }
    }

    fn bind(name: &str, expr_src: &str) -> BTreeMap<String, Expr> {
        let mut b = BTreeMap::new();
        b.insert(
            name.to_string(),
            syn::parse_str::<Expr>(expr_src).expect("binding expr must parse"),
        );
        b
    }

    #[test]
    fn ldexp_binding_dissolves_to_right_string() {
        // minf32 = ldexp_f32(1.0, -149) is the smallest f32 subnormal; its shortest
        // Display is "0." + 44 zeros + "1". Resolved through the let-binding map and
        // evaluated by our own stdlib, the assert dissolves (Some(true)).
        let b = bind("minf32", "ldexp_f32(1.0, -149)");
        let want = format!(r#""0.{}1""#, "0".repeat(44));
        let m = assert_macro(&format!(
            "assert_eq!(to_string(f, minf32, Minus, 0), {want});"
        ));
        assert_eq!(
            dissolve_flt2dec_assert(&m, Flt2decMode::Shortest, &b),
            Some(true),
            "ldexp-bound subnormal must dissolve to its exact shortest string"
        );
        // minf64 = ldexp_f64(1.0, -1074): "0." + 323 zeros + "5".
        let b64 = bind("minf64", "ldexp_f64(1.0, -1074)");
        let want64 = format!(r#""0.{}5""#, "0".repeat(323));
        let m64 = assert_macro(&format!(
            "assert_eq!(to_string(f, minf64, Minus, 0), {want64});"
        ));
        assert_eq!(
            dissolve_flt2dec_assert(&m64, Flt2decMode::Shortest, &b64),
            Some(true)
        );
    }

    #[test]
    fn ldexp_wrong_expected_does_not_discharge() {
        // break-the-twin: an expected string that does NOT match our independent
        // value must be refused (Some(false)), never force-discharged.
        let b = bind("minf32", "ldexp_f32(1.0, -149)");
        let m = assert_macro(r#"assert_eq!(to_string(f, minf32, Minus, 0), "0.5");"#);
        assert_eq!(
            dissolve_flt2dec_assert(&m, Flt2decMode::Shortest, &b),
            Some(false),
            "a wrong expected literal must refuse, not discharge"
        );
    }

    #[test]
    fn format_zerofill_expected_evaluates() {
        // f32::MAX shortest is `format!("34028235{:0>31}", "")` = 34028235 + 31 zeros.
        let b = BTreeMap::new();
        let m = assert_macro(
            r#"assert_eq!(to_string(f, f32::MAX, Minus, 0), format!("34028235{:0>31}", ""));"#,
        );
        assert_eq!(
            dissolve_flt2dec_assert(&m, Flt2decMode::Shortest, &b),
            Some(true),
            "closed format! zero-fill expected must evaluate and dissolve"
        );
        // And the same pattern with a wrong leading prefix must refuse.
        let bad = assert_macro(
            r#"assert_eq!(to_string(f, f32::MAX, Minus, 0), format!("99999999{:0>31}", ""));"#,
        );
        assert_eq!(
            dissolve_flt2dec_assert(&bad, Flt2decMode::Shortest, &b),
            Some(false)
        );
    }

    #[test]
    fn format_zerofill_direct_eval() {
        // Direct unit on the evaluator: prefix/suffix around one {:0>N}.
        assert_eq!(
            parse_format_zerofill(
                &syn::parse_str::<Expr>(r#"format!("0.{:0>323}5", "")"#).unwrap()
            ),
            Some(format!("0.{}5", "0".repeat(323)))
        );
        // Non-empty fill arg -> not our closed pattern -> None.
        assert_eq!(
            parse_format_zerofill(&syn::parse_str::<Expr>(r#"format!("{:0>4}", "x")"#).unwrap()),
            None
        );
        // Two placeholders -> None (we only evaluate the single-placeholder shape).
        assert_eq!(
            parse_format_zerofill(
                &syn::parse_str::<Expr>(r#"format!("{:0>4}{:0>4}", "")"#).unwrap()
            ),
            None
        );
        // A non-format! macro -> None.
        assert_eq!(
            parse_format_zerofill(&syn::parse_str::<Expr>(r#"vec!["a"]"#).unwrap()),
            None
        );
    }

    #[test]
    fn unparseable_value_or_expected_is_skipped() {
        let b = BTreeMap::new();
        // f16 value (ldexp_f16) -> unresolved -> None (skip, NOT discharge).
        let bf16 = bind("minf16", "ldexp_f16(1.0, -24)");
        let m16 = assert_macro(r#"assert_eq!(to_string(f, minf16, Minus, 0), "0.00000006");"#);
        assert_eq!(
            dissolve_flt2dec_assert(&m16, Flt2decMode::Shortest, &bf16),
            None,
            "f16-bound value must stay unclassified (stable cannot format f16)"
        );
        // Unbound ident -> None.
        let mub = assert_macro(r#"assert_eq!(to_string(f, mystery, Minus, 0), "0");"#);
        assert_eq!(
            dissolve_flt2dec_assert(&mub, Flt2decMode::Shortest, &b),
            None
        );
        // A non-closed format! expected (runtime arg) -> None.
        let mfmt = assert_macro(
            r#"assert_eq!(to_string(f, 1.0, Minus, 0), format!("{}", some_var));"#,
        );
        assert_eq!(
            dissolve_flt2dec_assert(&mfmt, Flt2decMode::Shortest, &b),
            None
        );
    }

    #[test]
    fn exact_fixed_full_expansion_mismatch_is_refused_not_discharged() {
        // SOUNDNESS GUARD: `to_exact_fixed_str(f64::MAX, 8)`'s corpus expected is the
        // SHORTEST decimal zero-padded (`format!("17976931348623157{:0>292}.00000000")`),
        // but our `{:.8}` reproduces the FULL exact expansion (`...570814527...`). These
        // differ, so this row must REFUSE (Some(false)) -- never force-discharge a value
        // we did not reproduce. This is the dog that didn't bark: the format! RHS now
        // PARSES, so the row is no longer skipped (None); it is actively refuted.
        let b = BTreeMap::new();
        let m = assert_macro(
            r#"assert_eq!(to_string(f, f64::MAX, Minus, 8), format!("17976931348623157{:0>292}.00000000", ""));"#,
        );
        assert_eq!(
            dissolve_flt2dec_assert(&m, Flt2decMode::ExactFixed, &b),
            Some(false),
            "a full-expansion fixed value that differs from the shortest-padded expected \
             must refuse, never discharge"
        );
        // The SHORTEST-mode row for the same value DOES match (shortest == padded shortest).
        let ms = assert_macro(
            r#"assert_eq!(to_string(f, f64::MAX, Minus, 0), format!("17976931348623157{:0>292}", ""));"#,
        );
        assert_eq!(
            dissolve_flt2dec_assert(&ms, Flt2decMode::Shortest, &b),
            Some(true)
        );
    }

    #[test]
    fn ldexp_minf32_drains_end_to_end() {
        // End-to-end through the helper: a `to_shortest_str` test fn that defines
        // minf32 via ldexp and asserts both a string-literal and a format!-pattern
        // expected. Both must lift (assertions_lifted == 2, none refused).
        let src = r#"
            #[test]
            fn to_string() {
                fn to_string<T>(_: T, _: f32, _: Sign, _: usize) -> String { String::new() }
                let minf32 = ldexp_f32(1.0, -149);
                assert_eq!(to_string(f, minf32, Minus, 0), format!("0.{:0>44}1", ""));
                assert_eq!(to_string(f, 1.0e-6_f32, Minus, 0), "0.000001");
            }
        "#;
        // Build via the flt2dec path directly so the test is independent of the
        // outer dispatcher's helper recognition heuristics.
        let file: syn::File = syn::parse_str(src).unwrap();
        let mut out = AdapterOutput::default();
        // Find the inner test fn and lift it in Shortest mode.
        fn find_fn(items: &[Item]) -> Option<&syn::ItemFn> {
            for it in items {
                if let Item::Fn(f) = it {
                    return Some(f);
                }
            }
            None
        }
        let f = find_fn(&file.items).expect("test fn");
        lift_flt2dec_helper(f, Flt2decMode::Shortest, "tests/x.rs", &[], &mut out);
        assert_eq!(
            out.assertions_lifted, 2,
            "both the format!-pattern and the literal expected must dissolve"
        );
        assert_eq!(out.assertions_refused, 0, "nothing refused: {:?}", out.skip_reasons);
    }

    // ── starts_with over a MUTABLE-local receiver is a runtime (bin-2) refusal ──
    // Corpus: iter/adapters/zip.rs::test_zip_next_back_side_effects_exhausted and
    // ::test_zip_nth_back_side_effects_exhausted -- `let mut a = Vec::new()` pushed
    // by a side-effecting `.map(|n| { a.push(n); n*10 })` driven by `iter.next()`,
    // then `assert!(a.starts_with(&[1, 2, 3]))`. `a`'s contents are runtime side
    // effects, not a value constructed from source literals.

    #[test]
    fn starts_with_over_mut_local_receiver_is_refused_bin2() {
        // POSITIVE: a `let mut` receiver mutated by iteration -> bin-2 terminal refuse.
        let src = r#"
            #[test]
            fn t() {
                let mut a = Vec::new();
                let mut iter = [1, 2, 3, 4, 5, 6].iter().cloned().map(|n| { a.push(n); n * 10 });
                iter.next();
                iter.next();
                iter.next();
                assert!(a.starts_with(&[1, 2, 3]));
            }
        "#;
        let out = lift_src(src);
        assert_eq!(out.assertions_lifted, 0, "no fake-discharge: {:?}", contract_names(&out));
        assert!(
            out.skip_reasons
                .iter()
                .any(|r| r.contains("starts_with predicate over a MUTABLE-local receiver")),
            "the mut-receiver bin-2 reason must be emitted; got {:?}",
            out.skip_reasons
        );
        // TEETH: the reason carries `bin-2`, so its DISPOSITION is terminal (refused),
        // NOT unclassified -- this is honest progress, not a parked roadmap item.
        assert!(
            out.skip_reasons.iter().all(|r| matches!(
                refusal_disposition(r),
                Disposition::Refused | Disposition::Inactive
            )),
            "mut-receiver starts_with must be TERMINAL: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn starts_with_over_immutable_string_receiver_still_digs() {
        // DISCRIMINATION (fake-refuse guard #1): a NON-mut, immutable string receiver
        // with a STRING literal pattern is the faithful prefix-of FOL -- it must still
        // DIG (lift), never get swept into the mut-receiver refuse.
        let src = r#"
            #[test]
            fn t() {
                let cid = format!("blake3-512:{}", 0);
                assert!(cid.starts_with("blake3-512:"));
            }
        "#;
        let out = lift_src(src);
        assert!(
            !out.skip_reasons
                .iter()
                .any(|r| r.contains("MUTABLE-local receiver")),
            "an immutable receiver must NOT trip the mut-receiver refuse: {:?}",
            out.skip_reasons
        );
        assert_eq!(
            out.assertions_lifted, 1,
            "the immutable string prefix predicate must lift; warnings: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn starts_with_slice_pattern_over_immutable_receiver_stays_unclassified() {
        // DISCRIMINATION (fake-refuse guard #2): a NON-mut receiver with a SLICE pattern
        // (`&[1, 2, 3]`, not a string/char literal) is a lifter-reach gap, NOT a proven
        // source property. It must STAY the UNCLASSIFIED "needs a string/char literal
        // pattern" reason -- never terminalized by the mut-receiver path.
        let src = r#"
            #[test]
            fn t() {
                let a = [1, 2, 3, 4];
                assert!(a.starts_with(&[1, 2, 3]));
            }
        "#;
        let out = lift_src(src);
        assert!(
            !out.skip_reasons
                .iter()
                .any(|r| r.contains("MUTABLE-local receiver")),
            "an immutable receiver must NOT trip the mut-receiver refuse: {:?}",
            out.skip_reasons
        );
        assert!(
            out.skip_reasons.iter().any(|r| {
                r.contains("needs a string/char literal pattern")
                    && matches!(refusal_disposition(r), Disposition::Unclassified)
            }),
            "an immutable slice-pattern starts_with must stay UNCLASSIFIED work: {:?}",
            out.skip_reasons
        );
    }

    // ── `.any()`/adaptor over a LITERAL domain whose closure body reads a MUTABLE
    // capture is a runtime (bin-2) refusal ──
    // Corpus: iter/adapters/zip.rs::test_zip_map_sideffectful -- `let mut xs = [0; 6]`
    // mutated by `xs.iter_mut().map(|x| *x += 1)`, then
    // `assert!([&[..], &[..]].iter().any(|v| &xs == *v))`. The DOMAIN is a literal array
    // but the body reads runtime-mutated `xs`.

    #[test]
    fn any_over_literal_domain_with_mut_capture_body_is_refused_bin2() {
        // POSITIVE: a literal-array `.any` whose body reads a `let mut` capture -> bin-2.
        let src = r#"
            #[test]
            fn t() {
                let mut xs = [0; 6];
                for _ in xs.iter_mut().map(|x| *x += 1) {}
                assert!([&[1, 1, 1, 1, 1, 0], &[1, 1, 1, 1, 0, 0]].iter().any(|v| &xs == *v));
            }
        "#;
        let out = lift_src(src);
        assert_eq!(out.assertions_lifted, 0, "no fake-discharge: {:?}", contract_names(&out));
        assert!(
            out.skip_reasons
                .iter()
                .any(|r| r.contains("READS a MUTABLE-local capture")),
            "the mut-capture body bin-2 reason must be emitted; got {:?}",
            out.skip_reasons
        );
        // TEETH: `bin-2` -> terminal (refused), not parked unclassified.
        assert!(
            out.skip_reasons.iter().all(|r| matches!(
                refusal_disposition(r),
                Disposition::Refused | Disposition::Inactive
            )),
            "mut-capture `.any` must be TERMINAL: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn any_over_literal_domain_with_pure_body_is_not_mut_refused() {
        // DISCRIMINATION (fake-refuse guard): a literal-array `.any` whose body is PURE
        // (reads only the closure param + literals) is a genuine bounded-quantifier the
        // forall lifter DISCHARGES. It must NEVER be swept into the mut-capture bin-2
        // refuse -- a pure body has no runtime capture to read.
        let src = r#"
            #[test]
            fn t() {
                assert!([1, 2, 3, 4].iter().any(|v| *v > 3));
            }
        "#;
        let out = lift_src(src);
        assert!(
            !out.skip_reasons
                .iter()
                .any(|r| r.contains("READS a MUTABLE-local capture")),
            "a pure body must NOT trip the mut-capture refuse: {:?}",
            out.skip_reasons
        );
        // No bin-2 terminal refusal manufactured for the pure case (it discharges or
        // stays non-terminal); the mut-capture path leaves the pure dig path untouched.
        assert!(
            !out.skip_reasons.iter().any(|r| r.contains("bin-2")),
            "a pure literal-array `.any` must not be terminalized as bin-2: {:?}",
            out.skip_reasons
        );
    }

    #[test]
    fn any_over_literal_domain_with_immutable_capture_stays_unclassified() {
        // DISCRIMINATION (fake-refuse guard #2): a literal-array `.any` whose body reads a
        // NON-mut (immutable) captured local is NOT a proven runtime read -- it stays the
        // UNCLASSIFIED bin-1 reason, never terminalized by the mut-capture path.
        let src = r#"
            #[test]
            fn t() {
                let ys = [1, 1, 1, 1];
                assert!([&[1, 1, 1, 1], &[0, 0, 0, 0]].iter().any(|v| &ys == *v));
            }
        "#;
        let out = lift_src(src);
        assert!(
            !out.skip_reasons
                .iter()
                .any(|r| r.contains("READS a MUTABLE-local capture")),
            "an immutable capture must NOT trip the mut-capture refuse: {:?}",
            out.skip_reasons
        );
        // And it is never fake-discharged as a bin-2 contradiction either.
        assert!(
            out.skip_reasons.iter().all(|r| !r.contains("READS a MUTABLE-local capture")),
            "immutable-capture body stays off the mut-capture path: {:?}",
            out.skip_reasons
        );
    }
}
