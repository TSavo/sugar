// SPDX-License-Identifier: MIT OR Apache-2.0
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
// `Term` DIRECTLY from the pre-computed `path_key` (the `path_to_name` result
// captured at build time from the `SourceFragment`) and `ctx.scope` -- there is
// no inner expression to recurse into (a path is atomic).
//
// THE REFUSE EDGE. `scope.path_name_str` returns `Result<String, String>`: it
// `Err`s when a versioned receiver has an AMBIGUOUS temporal identity (`ambiguous
// temporal identity for receiver ...; skipped assertion`). The node mirrors that
// EXACTLY: an `Err(reason)` becomes `Outcome::Incomplete(AmbiguousTemporalIdentity)`,
// carrying the SAME reason string the collector emitted into `skip_reasons`
// before -- the wire format (and thus the CID + counts) is conserved. An
// `Ok(name)` completes to `Term::Var { name }` via the shared `make_var` helper,
// byte-identical to the arm's `make_var(..)`.
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
// MIGRATION NOTE (Phase-3 ratchet). `PathSugar` is a FULLY MIGRATED leaf:
//   * `recognize` uses ONLY `SourceFragment` typed accessors (`observed`,
//     `name_id`, `path_full_name`, `path_token_str`, `path_simple_ident`) --
//     no `as_expr()`/`as_stmt()`/`as_item()` shim, no raw `Expr::` match.
//   * `PathSugar` holds NO raw `syn` fields: `path_key: String` (the
//     `path_to_name` result computed at build time) and `boundary: String`
//     (the token-stream representation for diagnostic messages).
//   * `desugar` calls `ctx.scope.path_name_str(&self.path_key)` -- the
//     string-taking sibling of `path_name` that skips the `path_to_name` step.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_leaf::resolved_term;
use crate::{make_var, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::fallback_term(
        "path",
        crate::sugar::claim::SugarWitnesses::reasoned_bucket(
            "owner-mismatch fallback path row; witnesses dispatch to const/bound/term owners",
        ),
        recognize,
    );

/// TERM recognizer for `Expr::Path`. Mirrors the two source-of-truth arms in order:
/// the `is_ident("None")` unit-ctor guard (a `call:None` ctor) FIRST, then the general
/// `make_var(scope.path_name(..))` name read ([`PathSugar`]).
///
/// Uses ONLY `SourceFragment` typed accessors -- no `as_expr()`/raw `Expr::` access.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // Must be an Expr::Path fragment ("Name" in observed())
    if frag.observed() != "Name" {
        return None;
    }

    // None unit-ctor guard: a single ident "None" -> call:None ctor (not a Var).
    // Mirrors `Expr::Path(path) if path.path.is_ident("None")` -- `name_id()` uses
    // `get_ident()`, which matches single-segment bare paths the same way `is_ident` does.
    if frag.name_id().as_deref() == Some("None") {
        return Some(resolved_term(Rc::new(Term::Ctor {
            name: "call:None".to_string(),
            args: Vec::new(),
        })));
    }

    // Unresolved destructure skip: a bare ident with no qself that the temporal plan
    // flagged as an unresolved destructured binding -> None (no Sugar built).
    // `path_simple_ident()` returns Some only when qself is absent AND path is a single
    // ident, matching the original `path.qself.is_none() && path.path.get_ident().is_some_and(..)`
    // guard exactly.
    if let Some(ident) = frag.path_simple_ident() {
        if fcx.scope().is_unresolved_destructured_local(&ident) {
            return None;
        }
    }

    // General path: capture the path key from the fragment so PathSugar holds no raw syn.
    let path_key = frag.path_full_name()?;
    Some(Box::new(PathSugar { path_key }))
}

/// A path read in TERM position (`x`, `Foo::BAR`). LEAF: produces a `Term::Var`
/// directly from the pre-computed `path_key` + `ctx.scope.path_name_str`, with NO
/// child `Sugar` and NO raw `syn` fields. Mirrors the general `Expr::Path` arm of
/// `translate_term_in_scope` byte-identically. The `None` unit-ctor special-case is
/// handled by this Sugar's recognizer before a [`PathSugar`] node is built.
pub(crate) struct PathSugar {
    /// Pre-computed path name (`path_to_name` result captured from the fragment at
    /// build time via `SourceFragment::path_full_name`). For a bare ident `x` this
    /// is `"x"`; for `Foo::BAR` it is `"Foo::BAR"`. `desugar` passes this to
    /// `ctx.scope.path_name_str` for shadowing-correct temporal resolution.
    pub(crate) path_key: String,
}

impl Sugar for PathSugar {
    /// LEAF term reduction: `Term::Var { name: scope.path_name_str(&self.path_key)? }`.
    /// An `Ok(name)` completes to the `make_var` term (byte-identical to the arm); an
    /// `Err(reason)` -- an ambiguous versioned-receiver identity -- returns Incomplete
    /// `AmbiguousTemporalIdentity`, carrying the verbatim reason the `?` propagated
    /// before. No child, no recursion: a path is atomic.
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match ctx.scope.path_name_str(&self.path_key) {
            Ok(name) => Outcome::Complete(Desugared::Term(make_var(name))),
            Err(reason) => Outcome::Incomplete(Effect::AmbiguousTemporalIdentity { reason }),
        }
    }
}

#[cfg(test)]
mod tests {
    // from_src TDD harness: source string -> SourceFragment -> assert observed ->
    // build PathSugar from fragment-derived data -> assert fields.
    // No parse_quote!, no StubTerm, no run(). The struct holds ONLY Strings --
    // zero raw-syn fields -- so these tests prove the migration is clean.
    //
    // Note: `PathSugar::desugar` reads `ctx.scope` (a `TemporalScope`), so the
    // full resolution is exercised end-to-end through the lift in
    // `tests/assertion_lift.rs` once the factory routes `Expr::Path` here.
    // Here we test the recognizer surface and struct-field shapes that are PURE.
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// from_src: source -> fragment -> observed == "Name" -> path_full_name is the ident.
    /// Proves the struct holds `path_key: String` (a bare ident name), not raw syn.
    #[test]
    fn from_src_bare_ident_path_key_is_ident_string() {
        let file = parse_file("fn f(x: u32) -> u32 { x }");
        // Get the tail expression fragment (the path `x`)
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        let tail = &stmts[0];
        let terms = tail.terms();
        let path_frag = &terms[0];

        // observed must be "Name" for Expr::Path
        assert_eq!(path_frag.observed(), "Name");

        // path_full_name gives the path key PathSugar will hold
        let path_key = path_frag
            .path_full_name()
            .expect("path_full_name on a Name frag");
        assert_eq!(path_key, "x");

        // Build: PathSugar holds only Strings -- no raw syn field
        let node = PathSugar {
            path_key: path_key.clone(),
        };
        assert_eq!(node.path_key, "x");
    }

    /// from_src: multi-segment path (`std::u8::MAX` style read via a local alias).
    /// Proves `path_full_name` joins segments with `::`.
    #[test]
    fn from_src_multi_segment_path_key_joins_segments() {
        // Use a const that has a multi-segment path expression as its value.
        // `u8::MAX` in a fn body is an Expr::Path with two segments.
        let file = parse_file("fn f() -> u8 { u8::MAX }");
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        let tail = &stmts[0];
        let terms = tail.terms();
        let path_frag = &terms[0];

        assert_eq!(path_frag.observed(), "Name");

        let path_key = path_frag.path_full_name().expect("path_full_name");
        // `u8::MAX` segments: ["u8", "MAX"]
        assert_eq!(path_key, "u8::MAX");

        let node = PathSugar {
            path_key: path_key.clone(),
        };
        assert_eq!(node.path_key, "u8::MAX");
        // struct holds zero raw-syn fields -- just Strings
    }

    /// Discrimination: a `PrimitiveLiteral` fragment must NOT produce a PathSugar.
    /// Proves the `observed() != "Name"` guard in recognize() filters correctly.
    #[test]
    fn discrimination_literal_is_not_a_path() {
        let file = parse_file("fn f() -> u32 { 42 }");
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        let tail = &stmts[0];
        let terms = tail.terms();
        let lit_frag = &terms[0];

        assert_eq!(lit_frag.observed(), "PrimitiveLiteral");
        // path_full_name is None for a non-path fragment
        assert!(lit_frag.path_full_name().is_none());
    }

    /// Structural: `path_simple_ident` returns None for a multi-segment path.
    /// Proves the unresolved-destructure guard can't fire for qualified paths.
    #[test]
    fn structural_multi_segment_has_no_simple_ident() {
        let file = parse_file("fn f() -> u8 { u8::MAX }");
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        let tail = &stmts[0];
        let terms = tail.terms();
        let path_frag = &terms[0];

        assert_eq!(path_frag.observed(), "Name");
        // multi-segment path: path_simple_ident() must return None (qself absent but
        // get_ident() is None for multi-segment)
        assert!(path_frag.path_simple_ident().is_none());
        // name_id() is also None for multi-segment
        assert!(path_frag.name_id().is_none());
        // path_full_name() IS Some -- it joins segments
        assert_eq!(path_frag.path_full_name().as_deref(), Some("u8::MAX"));
    }
}
