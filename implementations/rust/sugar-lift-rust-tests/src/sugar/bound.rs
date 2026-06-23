// SPDX-License-Identifier: Apache-2.0
//
// `BoundSugar`: the binding-resolution node. A `let name = <init>;` reference, when
// it appears as the OPERAND of a consuming `Sugar`, is not an ad-hoc lookup inlined
// into that consumer's resolver -- it is a FIRST-CLASS composed node. `BoundSugar`
// wraps the `Sugar` built from `<init>` and carries the binding's provenance (the
// bound `name`), so a recognized binding collapses to whatever its bound `Sugar`
// collapses to, with the `name was bound to this` rope threaded back to source.
//
// THIN PASS-THROUGH-WITH-PROVENANCE. `desugar` is `self.inner.desugar(ctx)` -- the
// node adds NO new resolution and NO new bail: it resolves to EXACTLY what the bound
// init resolves to (the WHAT is preserved; only the HOW -- through a uniform node
// rather than an inlined `let_bindings.get(name)` recursion -- changes). This is the
// `MapSugar`/`IdentitySugar` shape (a decorator over `inner`), specialized to a
// binding: where `MapSugar` transforms the inner sequence and `IdentitySugar` passes
// it through, `BoundSugar` passes the inner OUTCOME through unchanged and ATTACHES
// the binding name as provenance.
//
// THE PROVENANCE ROPE. `name` is the `let`-bound identifier the reference named. On a
// `Complete`, it records "this discharged value flowed through the binding `name`" (the
// complete-side rope, kin to `Warrant`); on a `Incomplete`, the inner's named `Effect` already
// carries the offending construct's `SourceMemento` (the bail-side rope) -- a
// runtime-bound init `Incomplete`s with ITS boundary, not a generic "binding unresolved".
// Either way the resolved outcome is byte-identical to resolving the init directly:
// the binding reference is transparent to the wire format, exactly as a `let`-inlined
// reference should be (`Regex::new(let p = "a.c"; p)` lifts identically to
// `Regex::new("a.c")`).
//
// SHADOWING. The consumer builds `BoundSugar(name, scope[name])` from the binding in
// effect at the reference's program point (the temporal scope's shadowing-correct
// `let`-binding map: a re-`let` of the same name overwrites, recorded per
// `Stmt::Local`). `BoundSugar` itself holds the ALREADY-RESOLVED inner `Sugar`, so it
// is oblivious to shadowing -- the scope resolved the right version before the node
// was built.
//
// BOUNDARY (the honest stop). Only OPERANDS that are already `Sugar`-typed route
// through `BoundSugar`. The pattern operand of `Regex::new(<pattern>)` is the one
// such site today (a `Box<dyn Sugar>` child). The other in-scope binding resolvers --
// the closed `try_fold` value-evaluator (`resolve_closure` / `eval_seq_chain`), the
// scalar-literal-array quantifier domain (`scalar_iter_domain_elems`), and the
// EUF `let`-prefix substitution (`collect_let_subst` / `let_prefix_euf_term`) --
// resolve a binding to a raw `Expr` / `Rc<Term>` and recurse a NON-`Sugar` evaluator;
// they cannot route through a `Box<dyn Sugar>` node without re-architecting those
// evaluators into `Sugar` producers (the CallsiteSugar knot). They stay as-is; this
// node unifies the binding resolution that is ALREADY at the `Sugar` level.

use crate::sugar::factory::{compat_reduction, FactoryReduction};
use crate::{Outcome, Sugar, SugarCtx};

/// A recognized `let name = <init>;` reference appearing as a consuming node's
/// operand. `inner` is the `Sugar` built from `<init>` (recognized init -> its
/// `Sugar`; unresolved init -> the consumer's existing fallback `Sugar`); `name` is
/// the binding's provenance. `desugar` collapses to whatever `inner` collapses to.
pub(crate) struct BoundSugar {
    /// The `let`-bound identifier this reference named -- the binding provenance rope
    /// (`name was bound to this`), tying the resolved outcome back to its `let` site.
    pub(crate) name: String,
    /// The `Sugar` built from the binding's initializer. `desugar` is delegated to it
    /// verbatim: the binding reference resolves to EXACTLY what its init resolves to.
    pub(crate) inner: Box<dyn Sugar>,
}

impl Sugar for BoundSugar {
    /// Pass through: a recognized binding collapses to whatever its bound `Sugar`
    /// collapses to. The binding `name` is carried (the provenance rope) but does not
    /// alter the outcome -- the resolved `Complete`/`Incomplete` is byte-identical to desugaring
    /// the init directly, so the binding reference is transparent to the wire format.
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        self.inner.reduce(ctx)
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}

impl BoundSugar {
    /// Wrap an init `Sugar` with its binding provenance. The consumer calls this when
    /// it resolves an operand reference to a `let`-bound name: it hands the resulting
    /// `BoundSugar` to the complete instead of inlining a `let_bindings.get(name)` lookup.
    pub(crate) fn new(name: impl Into<String>, inner: Box<dyn Sugar>) -> Box<dyn Sugar> {
        Box::new(BoundSugar {
            name: name.into(),
            inner,
        })
    }

    /// The binding provenance: the `let`-bound name this reference resolved through.
    pub(crate) fn name(&self) -> &str {
        &self.name
    }
}

#[cfg(test)]
mod tests {
    // `BoundSugar::desugar` is a pure delegation to its inner `Sugar`; the
    // pass-through-with-IDENTICAL-outcome contract is exercised END-TO-END through the
    // lift in `tests/assertion_lift.rs` (the `let`-bound regex pattern composes to the
    // same `str.in-regex` atom as the inline literal -- the byte-identical sweep is the
    // proof). Constructing a real `SugarCtx` (lifetime-heavy: `RefCell<&mut
    // FloatWidthScope>` + `ReductionCtx`) in isolation is impractical, so here we unit-
    // test the PROVENANCE rope (the `name` the node carries) and the constructor shape,
    // the parts that are pure.
    use super::*;
    use crate::{Desugared, Outcome, Sugar, SugarCtx};

    /// A test-double `Sugar` whose `desugar` is a fixed sentinel, used to assert that
    /// `BoundSugar` carries the binding provenance WITHOUT mutating the inner node.
    struct Sentinel;
    impl Sugar for Sentinel {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            // Never invoked in these (ctx-free) tests; present so `Sentinel: Sugar`.
            Outcome::Complete(Desugared::Seq(Vec::new()))
        }
    }

    #[test]
    fn carries_binding_provenance() {
        // The node ropes the resolved outcome to the `let`-bound name it resolved
        // through -- the complete-side provenance (`name was bound to this`).
        let node = BoundSugar {
            name: "pat".to_string(),
            inner: Box::new(Sentinel),
        };
        assert_eq!(node.name(), "pat");
    }

    #[test]
    fn new_threads_name_through() {
        // The constructor the consumer calls when it resolves an operand reference: it
        // wraps the init `Sugar` with the binding provenance, returning a boxed `Sugar`.
        let boxed = BoundSugar::new("p", Box::new(Sentinel));
        // Downcast is not available through `dyn Sugar`; the provenance is verified via
        // the concrete-node test above. Here we only assert the constructor yields a
        // usable `Box<dyn Sugar>` (it type-checks as the consumer's operand).
        let _operand: Box<dyn Sugar> = boxed;
    }
}
