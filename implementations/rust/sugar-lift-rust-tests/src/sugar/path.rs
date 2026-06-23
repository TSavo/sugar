// SPDX-License-Identifier: Apache-2.0
//
// `PathSugar`: the TERM-FLOOR LEAF for a path read in term position -- the
// constructive node mirror of the GENERAL `Expr::Path` arm of
// `translate_term_in_scope`:
//
//     Expr::Path(path) => Ok(make_var(scope.path_name(&path.path)?)),
//
// A path reference (`x`, `self.field` once flattened to a name, an
// associated-const path) is a NAME, and a name resolves to a `Term::Var` keyed
// by its temporal-scope-resolved identity (`scope.path_name` threads the
// shadowing-correct `@def<version>` suffix for a versioned local, or the plain
// path-name otherwise). This is a LEAF: it has NO child `Sugar`. It produces the
// `Term` DIRECTLY from the held source `Expr::Path` + `ctx.scope` -- there is no
// inner expression to recurse into (a path is atomic).
//
// THE REFUSE EDGE. `scope.path_name` returns `Result<String, String>`: it `Err`s
// when a versioned receiver has an AMBIGUOUS temporal identity (`ambiguous
// temporal identity for receiver ...; skipped assertion`). The old arm
// propagated that `Err` verbatim through `?`. The node mirrors that EXACTLY: an
// `Err(reason)` becomes `Outcome::Incomplete(Effect::Unsupported { reason })`, carrying
// the SAME reason string the collector emitted into `skip_reasons` before -- the
// wire format (and thus the CID + counts) is conserved. An `Ok(name)` completes to
// `Term::Var { name }` via the shared `make_var` helper, byte-identical to the
// arm's `make_var(..)`.
//
// THE `None` SPECIAL-CASE BELONGS TO THIS CLAIM'S RECOGNIZER. The arm
// immediately above the general path arm,
//
//     Expr::Path(path) if path.path.is_ident("None") => Ok(Rc::new(Term::Ctor {
//         name: "call:None".to_string(),
//         args: Vec::new(),
//     })),
//
// produces a `Ctor`, NOT a `Var`. That guard is a DISTINCT shape (the `None`
// unit-variant constructor) and is handled by `recognize` BEFORE falling through to
// `PathSugar`. `PathSugar` owns ONLY the general `make_var(scope.path_name(..))` arm;
// it does NOT re-check `is_ident("None")`.
//
// WHY NOT WRAP `BoundSugar`. `BoundSugar` (src/sugar/bound.rs) is a THIN
// pass-through DECORATOR over an ALREADY-`Sugar`-typed operand (`Box<dyn
// Sugar>`): it resolves a `let name = <init>;` reference to whatever the init's
// Sugar resolves to, threading the binding-name provenance. `PathSugar` solves a
// DIFFERENT problem: it resolves a path to its `Term::Var` NAME via the temporal
// scope -- there is no inner `Sugar` to pass through, and `scope.path_name` (not
// a `let`-init lookup) is the resolver. `PathSugar` therefore STANDS ALONE: it is
// a leaf, not a decorator. A future `BoundSugar` operand whose init is a bare
// path would still desugar through whatever Sugar the init builds (potentially a
// `PathSugar`), but `PathSugar` does not itself reach for the binding map -- it is
// the atomic name-resolution floor that `BoundSugar` composes OVER, never the
// reverse.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, ExprPath};

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::term_leaf::resolved_term;
use crate::{make_var, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::fallback_term("path", recognize);

/// TERM recognizer for `Expr::Path`. Mirrors the two source-of-truth arms in order:
/// the `is_ident("None")` unit-ctor guard (a `call:None` ctor) FIRST, then the general
/// `make_var(scope.path_name(..))` name read ([`PathSugar`]).
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Path(path) if path.path.is_ident("None") => {
            Some(resolved_term(Rc::new(Term::Ctor {
                name: "call:None".to_string(),
                args: Vec::new(),
            })))
        }
        Expr::Path(path) if unresolved_destructure_path(path, fcx) => None,
        Expr::Path(path) => Some(Box::new(PathSugar { path: path.clone() })),
        _ => None,
    }
}

fn unresolved_destructure_path(path: &ExprPath, fcx: &SugarBuildCtx) -> bool {
    path.qself.is_none()
        && path.path.get_ident().is_some_and(|ident| {
            fcx.scope()
                .is_unresolved_destructured_local(&ident.to_string())
        })
}

/// A path read in TERM position (`x`, `Foo::BAR`). LEAF: produces a `Term::Var`
/// directly from the held `ExprPath` + `ctx.scope.path_name`, with NO child
/// `Sugar`. Mirrors the general `Expr::Path` arm of `translate_term_in_scope`
/// byte-identically. The `None` unit-ctor special-case is handled by this Sugar's
/// recognizer before a [`PathSugar`] node is built (see the module header).
pub(crate) struct PathSugar {
    /// The source path this reference named. `desugar` resolves it through
    /// `ctx.scope.path_name(&path.path)` -- the shadowing-correct temporal
    /// identity -- exactly as the inline arm did.
    pub(crate) path: ExprPath,
}

impl Sugar for PathSugar {
    /// LEAF term reduction: `Term::Var { name: scope.path_name(&path.path)? }`.
    /// An `Ok(name)` completes to the `make_var` term (byte-identical to the arm); an
    /// `Err(reason)` -- an ambiguous versioned-receiver identity -- returns Incomplete
    /// `Effect::Unsupported { reason }`, carrying the verbatim reason the `?`
    /// propagated before. No child, no recursion: a path is atomic.
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match ctx.scope.path_name(&self.path.path) {
            Ok(name) => Outcome::Complete(Desugared::Term(make_var(name))),
            Err(reason) => Outcome::Incomplete(Effect::Unsupported { reason }),
        }
    }
}

#[cfg(test)]
mod tests {
    // `PathSugar::desugar` reads `ctx.scope` (a `TemporalScope`), so it needs a
    // real `SugarCtx`. Constructing one in isolation is lifetime-heavy
    // (`RefCell<&mut FloatWidthScope>` + `ReductionCtx` + `LiftOptions`), exactly
    // the impracticality `bound.rs` documents for its own ctx-bearing path. The
    // byte-identical term output (`Term::Var { name }`) is exercised END-TO-END
    // through the lift in `tests/assertion_lift.rs` once the factory routes
    // `Expr::Path` here (the wiring slice): a path-operand assertion composes to
    // the SAME `Var` atom as the inline `make_var(scope.path_name(..))` arm. Here
    // we unit-test the parts that are PURE: the node holds the path it was built
    // from, and the constructor shape.
    use super::*;
    use syn::parse_quote;

    #[test]
    fn holds_the_source_path() {
        // The node carries the `ExprPath` it will resolve at `desugar` time; the
        // resolution itself (`scope.path_name`) is the scope's job, exercised in
        // the end-to-end lift sweep.
        let path: ExprPath = parse_quote!(some_local);
        let node = PathSugar { path: path.clone() };
        assert_eq!(
            quote::ToTokens::to_token_stream(&node.path).to_string(),
            quote::ToTokens::to_token_stream(&path).to_string(),
        );
    }

    #[test]
    fn ident_path_is_a_single_segment() {
        // A bare-ident path (`x`) has exactly one segment -- the atomic-name shape
        // `PathSugar` resolves. (A multi-segment path `Foo::BAR` is equally valid;
        // this only pins the held shape, not a resolution verdict.)
        let path: ExprPath = parse_quote!(x);
        let node = PathSugar { path };
        assert_eq!(node.path.path.segments.len(), 1);
        assert!(node.path.path.is_ident("x"));
    }
}
