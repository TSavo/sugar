// SPDX-License-Identifier: Apache-2.0
//
// `MonadicSugar`: the CONSTRUCTIVE term node for the std `Option`/`Result`
// CONSTRUCTORS over values -- `Some(x)`, `Ok(x)`, `Err(x)`, and the nullary
// `None`. They are CONSTRUCTORS OVER LITERALS, the same family as the
// `array_term`/`tuple_term`/`struct_term` aggregate nodes: `Some(1)` is sugar
// for a constructed value, all the way down to its inner literal. We do NOT
// leave them as a federated-opaque `call:eq:Some` EUF var (the old behaviour);
// we GROUND them to a constructed value term that z3 reasons about
// STRUCTURALLY.
//
// THE EMITTED TERM. Each ctor lowers to a `Term::Ctor` keyed by a RESERVED
// monadic name -- `opt:some`/`opt:none`/`res:ok`/`res:err` -- distinct from the
// generic `call:<head>` ctor that `call.rs`/`path.rs` build (`call:Some`,
// `call:None`). The reserved names matter twice:
//
//   1. They do NOT carry the `call:<Uppercase>` shape, so
//      `constructor_operator_tag` does NOT route the equality through the
//      FEDERATED user-`PartialEq` path (`eq(call:eq:Some(..), true)`, an opaque
//      EUF call with NO teeth). The plain `eq(lhs, rhs)` atom is emitted, and
//      the two monadic ctor terms meet structurally.
//   2. The IR->SMT compiler recognizes them as the two algebraic datatypes it
//      declares (`SugarOption`/`SugarResult`), so z3 enforces constructor
//      INJECTIVITY (`Some a = Some b <=> a = b`) and DISTINCTNESS
//      (`Some _ != None`, `Ok _ != Err _`). THAT is the teeth: `Some(1) ==
//      Some(2)` is z3-UNSAT, `Some(1) == None` is z3-UNSAT, `Ok(a) == Err(b)`
//      is z3-false. A bare uninterpreted `Some` ctor would let z3 model
//      `Some(1) = Some(2)` (no injectivity) -> SAT -> a FAKE-DIG; the ADT is
//      the principled model, because they ARE algebraic datatypes.
//
// THE SOUNDNESS LINE. Structural unwrap is sound only where `==` is STRUCTURAL:
// std `Option`/`Result` ALWAYS are (their `PartialEq` is the derived structural
// one). This node recognizes ONLY the std unit/tuple constructors by name
// (`Some`/`Ok`/`Err`/`None`); a user enum/struct with a HAND-WRITTEN `PartialEq`
// is a METHOD CALL, not a structural unwrap, and is NOT recognized here -- it
// stays on the existing call machinery. (A user type's *constructor* named
// `Some`/`Ok`/`Err`/`None` is pathological and not in scope.)
//
// THE INNER IS BUILT BY THE FACTORY AT CONSTRUCTION TIME. `Some(x)`'s inner `x`
// is a `SugarBody<TermFloor>` handed to this node by the recognizer, so desugar
// only reduces the already-constructed body and wraps the monadic floor. A child
// `Incomplete` propagates verbatim (the effect/runtime boundary holds:
// `Some(some_io())` blows up, never grounds); a child that completes to a
// non-term is a construction-law bug and panics.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::Expr;

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::{strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before("monadic", &["call", "path"], recognize);

/// The reserved monadic ctor names. Distinct from the generic `call:<head>`
/// ctor (`call:Some`/`call:None`) so the equality routes through the plain
/// `eq(lhs, rhs)` atom (NOT the federated `call:eq:Some` EUF), and so the
/// IR->SMT compiler recognizes them as its `SugarOption`/`SugarResult` ADTs.
//
// The IR->SMT compiler (`sugar-ir-compiler-smt-lib/src/generated.rs`) holds the
// SAME four reserved names and recognizes them as its `SugarOption`/
// `SugarResult` ADT constructors. The two name sets MUST stay in lockstep; they
// are kept byte-identical by convention (a divergence would silently strip the
// ADT teeth -- an unrecognized monadic ctor would fall back to an uninterpreted
// function).
pub(crate) const OPT_SOME: &str = "opt:some";
pub(crate) const OPT_NONE: &str = "opt:none";
pub(crate) const RES_OK: &str = "res:ok";
pub(crate) const RES_ERR: &str = "res:err";

/// Which monadic constructor this node builds.
enum Kind {
    /// `Some(x)` -- one inner child.
    Some(SugarBody<TermFloor>),
    /// `Ok(x)` -- one inner child.
    Ok(SugarBody<TermFloor>),
    /// `Err(x)` -- one inner child.
    Err(SugarBody<TermFloor>),
    /// `None` -- nullary.
    None,
}

/// TERM recognizer for the std `Option`/`Result` constructors. `Some(x)` /
/// `Ok(x)` / `Err(x)` match a single-argument `Expr::Call` whose head is the
/// bare ident; `None` matches an `Expr::Path` ident. Anything else returns
/// `None` so the walk falls through to the generic `call`/`path` recognizers.
///
/// Registered BEFORE `path::recognize` (for `None`) and BEFORE `call::recognize`
/// (for `Some`/`Ok`/`Err`), so a recognized monadic constructor grounds to its
/// ADT-backed constructed value instead of the generic `call:` / `call:None`
/// ctor.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        // Nullary `None` -- a path whose final segment is `None` (`None`,
        // `None::<isize>` with a turbofish, `Option::None`). `is_ident` is too
        // strict (it rejects a turbofish / a qualified path), and `None::<T>` is
        // the common form in vendor code, so match the FINAL SEGMENT ident.
        Expr::Path(path) if path_ends_with(path, "None") => {
            Some(Box::new(MonadicSugar { kind: Kind::None }))
        }
        // `Some(x)` / `Ok(x)` / `Err(x)`: a single-argument call whose head path's
        // final segment is the constructor ident (also allowing a turbofish /
        // qualified path like `Some::<i32>(x)` / `Option::Some(x)`).
        Expr::Call(call) if call.args.len() == 1 => {
            let Expr::Path(path) = &*call.func else {
                return None;
            };
            let inner = SugarBody::term(strip_refs_groups(&call.args[0]), fcx);
            let kind = if path_ends_with(path, "Some") {
                Kind::Some(inner)
            } else if path_ends_with(path, "Ok") {
                Kind::Ok(inner)
            } else if path_ends_with(path, "Err") {
                Kind::Err(inner)
            } else {
                return None;
            };
            Some(Box::new(MonadicSugar { kind }))
        }
        _ => None,
    }
}

/// True iff the path's FINAL segment ident is `name`, ignoring a turbofish on
/// that segment (`None::<T>`) and an optional qualifier (`Option::None`). This
/// is the std `Option`/`Result` constructor surface: only the four reserved
/// idents (`Some`/`Ok`/`Err`/`None`) -- a user type's hand-written `PartialEq`
/// is a method call on a DIFFERENT path and is NOT matched here.
fn path_ends_with(path: &syn::ExprPath, name: &str) -> bool {
    path.path
        .segments
        .last()
        .is_some_and(|seg| seg.ident == name)
}

/// Build the grounded `opt:some(inner)` TERM directly, so a value-level reducer
/// (the iterator positional terminals in `iter_terminal`) can wrap an already-
/// computed element term into the same ADT-backed `Some` value the recognizer
/// emits -- byte-identical name, so both meet structurally under the ADT.
pub(crate) fn some_term(inner: Rc<Term>) -> Rc<Term> {
    Rc::new(Term::Ctor {
        name: OPT_SOME.to_string(),
        args: vec![inner],
    })
}

/// Build the grounded nullary `opt:none` TERM directly (the value for a `.next()`
/// on the empty Seq, or a `.nth(k)` past the end).
pub(crate) fn none_term() -> Rc<Term> {
    Rc::new(Term::Ctor {
        name: OPT_NONE.to_string(),
        args: Vec::new(),
    })
}

/// Build the grounded `res:ok(inner)` TERM directly, matching the constructive
/// `Ok(inner)` recognizer byte-for-byte.
pub(crate) fn ok_term(inner: Rc<Term>) -> Rc<Term> {
    Rc::new(Term::Ctor {
        name: RES_OK.to_string(),
        args: vec![inner],
    })
}

/// Build the grounded `res:err(inner)` TERM directly, matching the constructive
/// `Err(inner)` recognizer byte-for-byte.
pub(crate) fn err_term(inner: Rc<Term>) -> Rc<Term> {
    Rc::new(Term::Ctor {
        name: RES_ERR.to_string(),
        args: vec![inner],
    })
}

/// True iff a value is built wholly from scalar literals and structural
/// constructors. Opaque runtime leaves (`call:`/`method:`), unresolved vars, and
/// higher-order terms are not literal payloads for Option/Result method sugar.
pub(crate) fn is_grounded_literal_term(term: &Term) -> bool {
    match term {
        Term::Const { .. } => true,
        Term::Var { name } => name.starts_with("literal:"),
        Term::Lambda { .. } | Term::Let { .. } => false,
        Term::Ctor { name, args } => {
            if name.starts_with("call:") || name.starts_with("method:") {
                return false;
            }
            args.iter()
                .all(|arg| is_grounded_literal_term(arg.as_ref()))
        }
    }
}

/// The constructive `Option`/`Result` constructor node. completes its inner child to
/// a `Term` (for the unary ctors) and emits `Term::Ctor { name, args }` keyed by
/// the reserved monadic name. A child `Incomplete` propagates verbatim; a child that
/// completes to a non-term panics because this node was constructed with a term floor.
struct MonadicSugar {
    kind: Kind,
}

impl MonadicSugar {
    fn build(name: &str, inner: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Outcome {
        let term = match inner.reduce(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(t) => t,
                None => panic!("monadic constructor child completed as non-term for `{name}`"),
            },
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: name.to_string(),
            args: vec![term],
        })))
    }
}

impl Sugar for MonadicSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match &self.kind {
            Kind::Some(inner) => MonadicSugar::build(OPT_SOME, inner, ctx),
            Kind::Ok(inner) => MonadicSugar::build(RES_OK, inner, ctx),
            Kind::Err(inner) => MonadicSugar::build(RES_ERR, inner, ctx),
            Kind::None => Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
                name: OPT_NONE.to_string(),
                args: Vec::new(),
            }))),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Effect;
    use sugar_ir_symbolic::{make_var, num};

    fn body(term: Rc<Term>) -> SugarBody<TermFloor> {
        SugarBody::from_node(crate::sugar::term_leaf::resolved_term(term))
    }

    struct StubIncomplete;

    impl Sugar for StubIncomplete {
        fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
            Outcome::Incomplete(Effect::LiteralPanic {
                boundary: "monadic-child".to_string(),
                reason: "literal child panic; refused".to_string(),
            })
        }
    }

    fn incomplete_body() -> SugarBody<TermFloor> {
        SugarBody::from_node(Box::new(StubIncomplete))
    }

    fn run(node: &dyn Sugar) -> Outcome {
        let scope = crate::TemporalScope::new("test", crate::TemporalPlan::default());
        let options = crate::LiftOptions::default();
        let items: Vec<syn::Item> = Vec::new();
        let reducer = crate::ReductionCtx::from_items(&items);
        let mut float_widths = crate::FloatWidthScope::new();
        let ctx = crate::sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        node.desugar(&ctx)
    }

    fn ctor_of(t: &Term) -> (&str, &[Rc<Term>]) {
        match t {
            Term::Ctor { name, args } => (name.as_str(), args.as_slice()),
            _ => panic!("expected a Ctor term, got {t:?}"),
        }
    }

    fn dug_term(node: &dyn Sugar) -> Rc<Term> {
        match run(node) {
            Outcome::Complete(d) => d.into_term().expect("a Term"),
            Outcome::Incomplete(_) => panic!("expected Complete, got Incomplete"),
        }
    }

    #[test]
    fn some_emits_opt_some_over_inner_term() {
        let node = MonadicSugar {
            kind: Kind::Some(body(num(1))),
        };
        let term = dug_term(&node);
        let (name, args) = ctor_of(&term);
        assert_eq!(name, OPT_SOME);
        assert_eq!(args.len(), 1);
        // The inner is the literal, not an opaque var.
        assert!(matches!(&*args[0], Term::Const { .. }));
    }

    #[test]
    fn none_emits_nullary_opt_none() {
        let node = MonadicSugar { kind: Kind::None };
        let term = dug_term(&node);
        let (name, args) = ctor_of(&term);
        assert_eq!(name, OPT_NONE);
        assert!(args.is_empty());
    }

    #[test]
    fn ok_and_err_are_distinct_reserved_names() {
        let ok = dug_term(&MonadicSugar {
            kind: Kind::Ok(body(make_var("x"))),
        });
        let err = dug_term(&MonadicSugar {
            kind: Kind::Err(body(make_var("x"))),
        });
        assert_eq!(ctor_of(&ok).0, RES_OK);
        assert_eq!(ctor_of(&err).0, RES_ERR);
        assert_ne!(ctor_of(&ok).0, ctor_of(&err).0);
    }

    #[test]
    fn child_hit_propagates_verbatim() {
        // The effect/runtime boundary holds: `Some(<unsupported term>)` blows up,
        // never grounds.
        let node = MonadicSugar {
            kind: Kind::Some(incomplete_body()),
        };
        match run(&node) {
            Outcome::Incomplete(Effect::LiteralPanic { reason, .. }) => {
                assert!(!reason.is_empty())
            }
            Outcome::Incomplete(_) => panic!("expected the child's LiteralPanic Incomplete"),
            Outcome::Complete(_) => panic!("expected the child's Incomplete, got Complete"),
        }
    }

    #[test]
    fn some_term_and_none_term_helpers_build_reserved_names() {
        let s = some_term(num(7));
        let (name, args) = ctor_of(&s);
        assert_eq!(name, OPT_SOME);
        assert_eq!(args.len(), 1);
        let n = none_term();
        assert_eq!(ctor_of(&n).0, OPT_NONE);
        assert!(ctor_of(&n).1.is_empty());
    }
}
