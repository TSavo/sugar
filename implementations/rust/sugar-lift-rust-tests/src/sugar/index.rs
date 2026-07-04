// SPDX-License-Identifier: Apache-2.0
//
// `IndexSugar`: the CONSTRUCTIVE term node for a general index read `a[i]` -- the
// constructive tail of the `Expr::Index` arm of `translate_term_in_scope`. It is the
// term-floor sibling of `CallSugar`: a composite term `Sugar` that builds the
// container and the index as child `Sugar`s, reads each child's `Term` back out
// through `Desugared::into_term`, and emits the EXACT `Term::Ctor` the arm's
// constructive tail produces:
//
//   Term::Ctor { name: "index".to_string(), args: vec![container, idx] }
//
// THE CHILDREN ARE LAZY. The container `a` and the index `i` are held as
// `SugarBody<TermFloor>` children. `desugar` builds and completes the container
// FIRST, then the index, mirroring the arm's
// `let container = translate_term_in_scope(&index.expr, scope)?;` /
// `let idx = translate_term_in_scope(&index.index, scope)?;` order, and emits
// `index(container, idx)` -- the args in that exact order. A child that does not
// reduce to a term (`into_term` -> `None`) bails the whole node (the byte-identical
// structural backstop, the old `?`-propagated `Err`); a child that `Incomplete`s a
// named order-loss boundary propagates that `Incomplete` VERBATIM (the old named
// inner `Err`).
//
// THE RECOGNIZER PREAMBLE. The `Expr::Index` shape has TWO
// EARLY-RETURN recognizers BEFORE the constructive tail:
//
//   if let Some(term) = const_index_term_in_scope(index, scope)? {
//       return Ok(term);
//   }
//   ...
//   if let Some(node) = sugar::temporal_read::decompose_temporal_read(expr, scope) {
//       if let Outcome::Incomplete(effect @ Effect::TemporalRead { .. }) = node.desugar_ctx_free()
//       {
//           return Err(effect.reason());
//       }
//   }
//
// The const-index fold (inlined via `scope.path_name_str` + pre-computed
// `container_const_path_name`/`const_index_int`) and the mutable-container
// TEMPORAL-READ refusal (inlined via `scope.is_mut_local` + pre-computed
// `container_simple_path`) run first inside `desugar`: they decide whether the
// constructive `index` ctor is reached at all. `IndexSugar` then emits the
// `index` ctor only after those preambles decline.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{make_var, Term};
use syn::Expr;

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::method_family;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    const_eval, const_fold_int_term, const_val_term, num, path_to_name, ConstVal, Desugared,
    Effect, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "index",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_index_good() {
                    assert_eq!([10_i32, 20, 30][1], 20);
                }
            "#,
            r#"
                #[test]
                fn t_index_bad() {
                    assert_eq!([10_i32, 20, 30][1], 21);
                }
            "#,
        ),
        recognize,
    );

/// TERM recognizer for `Expr::Index`. Gates on `frag.observed() == "Index"`;
/// builds child bodies via `SugarBody::term_frag`. No raw syn in the body.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if frag.observed() != "Index" {
        return None;
    }
    Some(Box::new(IndexSugar::new(frag, fcx)))
}

/// A general index read `a[i]` in term position, composed as a node whose `desugar`
/// emits the `index` ctor over its container and index child terms (the constructive
/// tail of the `Expr::Index` arm). See the module header.
pub(crate) struct IndexSugar {
    /// Token-key for the full `a[i]` expression -- boundary for
    /// `AmbiguousTemporalIdentity` and `TemporalRead` effects.
    boundary_token_str: String,
    /// Pre-computed const integer value of the index expression (paren/group-stripped),
    /// derived at construction time. Used by the inlined `const_index_term_in_scope`
    /// preamble in `desugar`. Mirrors `const_int(&index.index)`.
    const_index_int: Option<i128>,
    /// If the receiver (paren/group-stripped, qself-free) is a const-like ALL_CAPS
    /// path, its `path_to_name` string. Used by the inlined `const_index_term_in_scope`
    /// preamble via `scope.path_name_str`. Mirrors `const_index_base_name`.
    container_const_path_name: Option<String>,
    /// Simple-ident path name of the receiver (after ref/paren/group strip), if any.
    /// Used by `ground_temporal_rewrite_index` and the inlined `decompose_temporal_read`
    /// preamble in `desugar`. Mirrors `simple_path_name(&index.expr)`.
    container_simple_path: Option<String>,
    /// Term-floor child body for the container `a`.
    container: SugarBody<TermFloor>,
    /// Term-floor child body for the index `i`.
    idx: SugarBody<TermFloor>,
    /// Composite-floor child body for `a` when it is a literal sequence. Used by
    /// `ground_literal_index` to const-fold `literal_array[const_k]` to the element.
    literal_container: Option<SugarBody<CompositeFloor>>,
}

impl IndexSugar {
    /// Build an `IndexSugar` from a `&SourceFragment` (must be `observed() == "Index"`).
    /// All raw syn access lives HERE (in `new`, not in `recognize` -- ratchet-excluded)
    /// so the recognize body stays clean. Pre-computes the preamble data that `desugar`
    /// needs without storing raw syn in the struct.
    pub(crate) fn new(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Self {
        let boundary_token_str = frag.token_str();
        let receiver_frag = frag
            .index_receiver()
            .expect("IndexSugar::new: missing receiver");
        let index_frag = frag.index_index().expect("IndexSugar::new: missing index");

        // Pre-compute const int index value. as_expr() lives here (not in recognize body).
        // Mirrors const_int(&index.index): strips Paren/Group only (not Reference).
        let const_index_int = index_frag.as_expr().and_then(const_int_from_expr);

        // Pre-compute const-like path name only when the index is a const int (mirrors the
        // early-return in const_index_term_in_scope: const_int returns None -> skip base).
        // as_expr() lives here (not in recognize body).
        // Mirrors const_index_base_name: qself-free + all-uppercase last segment.
        let container_const_path_name = if const_index_int.is_some() {
            receiver_frag.as_expr().and_then(const_like_path_name)
        } else {
            None
        };

        // Simple-ident path for temporal-rewrite and temporal-read preambles.
        // Mirrors simple_path_name(&index.expr) -- checks via path_simple_ident after
        // stripping ref/paren/group.
        let container_simple_path = receiver_frag.strip_refs_groups().path_simple_ident();

        // Literal container composite (for ground_literal_index).
        // as_expr() lives here (not in recognize body).
        let literal_container = receiver_frag
            .as_expr()
            .and_then(|e| method_family::build_literal_sequence_composite(e, fcx))
            .map(SugarBody::from_node);

        // Build SugarBody children via fragment builders (as_expr inside factory.rs).
        let container = SugarBody::term_frag(&receiver_frag, fcx);
        let idx = SugarBody::term_frag(&index_frag, fcx);

        IndexSugar {
            boundary_token_str,
            const_index_int,
            container_const_path_name,
            container_simple_path,
            container,
            idx,
            literal_container,
        }
    }

    /// Ground `literal_array[const_k]` to the element TERM, or `None` if it does not
    /// cleanly ground (non-literal container, non-const / out-of-bounds index, non-int
    /// element). The caller then emits the symbolic `index` ctor. SOUND: only an
    /// in-bounds const index into a literal int Seq grounds; a non-literal read is never
    /// given a guessed value, and an out-of-bounds index (a rust panic) stays symbolic.
    fn ground_literal_index(&self, ctx: &SugarCtx) -> Result<Option<Rc<Term>>, Outcome> {
        let Some(container) = &self.literal_container else {
            return Ok(None);
        };
        let seq = match container.reduce(ctx) {
            Outcome::Complete(d) => match d.into_seq() {
                Some(seq) => seq,
                None => return Ok(None),
            },
            Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
        };
        let idx = match term_from_body(&self.idx, ctx, "index position") {
            Ok(term) => term,
            Err(outcome) => return Err(outcome),
        };
        let Some(k) = const_fold_int_term(&idx).and_then(|k| usize::try_from(k).ok()) else {
            return Ok(None);
        };
        let Some(elem) = seq.get(k) else {
            return Ok(None);
        };
        let Some(n) = elem.value.as_ref().and_then(ConstVal::as_int) else {
            return Ok(None);
        };
        Ok(Some(num(n)))
    }

    fn ground_temporal_rewrite_index(&self, ctx: &SugarCtx) -> Result<Option<Outcome>, Outcome> {
        // Replaces `simple_path_name(&self.index.expr)` with the pre-computed field.
        let Some(base) = self.container_simple_path.as_deref() else {
            return Ok(None);
        };
        let idx = match term_from_body(&self.idx, ctx, "index temporal position") {
            Ok(term) => term,
            Err(outcome) => return Err(outcome),
        };
        let Some(k) = const_fold_int_term(&idx).and_then(|k| usize::try_from(k).ok()) else {
            return Ok(None);
        };
        let Some(elem) = ctx.scope.temporal_rewrite_index_expr_for(base, k) else {
            return Ok(None);
        };
        let value = const_eval(&elem, &BTreeMap::new())
            .and_then(|value| const_val_term(&value))
            .map(Desugared::Term)
            .map(Outcome::Complete)
            .unwrap_or_else(|| {
                index_gap("temporal index rewrite element is not literal-determined")
            });
        Ok(Some(value))
    }
}

impl Sugar for IndexSugar {
    /// Dig the container child to its `Term`, then the index child, then emit the
    /// `index` ctor over `[container, idx]` -- the constructive tail of the
    /// `Expr::Index` arm, byte-identical (ctor name `"index"`, args in container-then-
    /// index order). A child that `Incomplete`s a named order-loss boundary propagates that
    /// `Incomplete` verbatim (the old named inner `Err`); a child that completes to a non-term
    /// `Desugared` (`into_term` -> `None`) is an impossible floor mismatch and panics
    /// loudly instead of manufacturing a terminal verdict.
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        // Preamble 1: inline const_index_term_in_scope -- no raw syn.
        // Uses pre-computed `const_index_int` (mirrors const_int) and
        // `container_const_path_name` (mirrors const_index_base_name), then
        // `scope.path_name_str` (the string-based twin of scope.path_name).
        if let (Some(index_value), Some(ref path_name)) =
            (self.const_index_int, &self.container_const_path_name)
        {
            match ctx.scope.path_name_str(path_name) {
                Ok(base_name) => {
                    return Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
                        name: "index".to_string(),
                        args: vec![make_var(base_name), num(index_value)],
                    })));
                }
                Err(reason) => {
                    return Outcome::Incomplete(Effect::AmbiguousTemporalIdentity { reason });
                }
            }
        }

        if let Some(outcome) = match self.ground_temporal_rewrite_index(ctx) {
            Ok(outcome) => outcome,
            Err(outcome) => return outcome,
        } {
            return outcome;
        }

        // Preamble 2: inline decompose_temporal_read -- no raw syn.
        // Mirrors: simple_path_name(&index.expr) -> scope.is_mut_local -> TemporalRead.
        if let Some(ref name) = self.container_simple_path {
            if ctx.scope.is_mut_local(name) {
                return Outcome::Incomplete(Effect::TemporalRead {
                    boundary: self.boundary_token_str.clone(),
                });
            }
        }

        // c2: ground `literal_array[const_k]` to the element (`[10,20,99][2]` -> `99`) so
        // the index reaches the floor, instead of an uninterpreted `index(..)` ctor a
        // solver can satisfy with anything (which would over-discharge `a[k] == wrong`).
        // Falls through to the symbolic ctor for a non-literal container.
        if let Some(term) = match self.ground_literal_index(ctx) {
            Ok(term) => term,
            Err(outcome) => return outcome,
        } {
            return Outcome::Complete(Desugared::Term(term));
        }

        let container = match term_from_body(&self.container, ctx, "index container") {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let idx = match term_from_body(&self.idx, ctx, "index position") {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: "index".to_string(),
            args: vec![container, idx],
        })))
    }
}

fn term_from_body(
    body: &SugarBody<TermFloor>,
    ctx: &SugarCtx,
    label: &'static str,
) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_term()
            .ok_or_else(|| index_gap(&format!("{label} reduced to non-term"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn index_gap(reason: &str) -> ! {
    panic!("index completed without a term/composite floor: {reason}")
}

// ---------------------------------------------------------------------------
// Construction helpers (raw syn permitted here; not in recognize body)
// ---------------------------------------------------------------------------

/// Compute the const integer value of an expression, stripping only Paren/Group
/// (not Reference) -- mirrors the private `const_int` in lib.rs exactly, including
/// full-radix parsing (hex, octal, binary) via `int_lit_radix_digits` logic.
fn const_int_from_expr(expr: &Expr) -> Option<i128> {
    match expr {
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Int(i),
            ..
        }) => {
            let mut text = i.to_string();
            let suffix = i.suffix();
            if !suffix.is_empty() && text.ends_with(suffix) {
                text.truncate(text.len() - suffix.len());
            }
            let text = text.replace('_', "");
            let (radix, digits) = if let Some(r) =
                text.strip_prefix("0x").or_else(|| text.strip_prefix("0X"))
            {
                (16u32, r.to_string())
            } else if let Some(r) = text.strip_prefix("0o").or_else(|| text.strip_prefix("0O")) {
                (8u32, r.to_string())
            } else if let Some(r) = text.strip_prefix("0b").or_else(|| text.strip_prefix("0B")) {
                (2u32, r.to_string())
            } else {
                (10u32, text)
            };
            i128::from_str_radix(&digits, radix).ok()
        }
        Expr::Paren(p) => const_int_from_expr(&p.expr),
        Expr::Group(g) => const_int_from_expr(&g.expr),
        _ => None,
    }
}

/// Extract the `path_to_name` string from a receiver expression if it is a
/// qself-free path whose last segment is all-uppercase (const-like). Strips
/// only Paren/Group (not Reference) -- mirrors `const_index_base_name` exactly.
fn const_like_path_name(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Path(p) if p.qself.is_none() => {
            let name = path_to_name(&p.path);
            if is_const_like_name(&name) {
                Some(name)
            } else {
                None
            }
        }
        Expr::Paren(p) => const_like_path_name(&p.expr),
        Expr::Group(g) => const_like_path_name(&g.expr),
        _ => None,
    }
}

/// Whether the last `::` segment of a path name is all-uppercase (const-like).
/// Mirrors `is_const_like_path` from lib.rs, operating on the pre-computed name
/// string instead of a raw `syn::Path`.
fn is_const_like_name(name: &str) -> bool {
    let last = name.rsplit("::").next().unwrap_or(name).trim();
    !last.is_empty()
        && last.chars().any(|c| c.is_ascii_uppercase())
        && last
            .chars()
            .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_')
}

#[cfg(test)]
mod tests {
    // `IndexSugar` is the CONSTRUCTIVE composer for a raw `a[i]` site. Tests
    // assert it emits the exact ctor after child terms are built lazily in `desugar`.
    use super::*;
    use crate::{
        sugar_ctx, Desugared, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, TemporalPlan,
        TemporalScope,
    };
    use sugar_ir_symbolic::Term;
    use syn::Item;

    /// Build an `IndexSugar` from inline source (no parse_quote!).
    /// The expression must be the initializer of `let _ = <expr>;` inside `fn f() { ... }`.
    fn node_from_src(src: &str) -> IndexSugar {
        use crate::sugar::source_fragment::{parse_file, SourceFragment};
        let file = parse_file(&format!("fn f() {{ let _ = {src}; }}"));
        let syn::Item::Fn(ref f) = file.items[0] else {
            panic!("expected fn")
        };
        let syn::Stmt::Local(ref loc) = f.block.stmts[0] else {
            panic!("expected local")
        };
        let index_expr = &*loc.init.as_ref().expect("no init").expr;
        let frag = SourceFragment::expr(index_expr, "<test>");
        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        IndexSugar::new(&frag, &fcx)
    }

    /// Run `node.desugar` against a freshly-built, minimal-but-real `SugarCtx`.
    fn run(node: &IndexSugar) -> Outcome {
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let mut fw = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut fw, 0);
        node.desugar(&ctx)
    }

    // --- from_src test (TDD gate; source -> SourceFragment -> recognize -> floor) ---

    /// from_src: source -> SourceFragment -> observed() -> recognize() -> desugar -> floor.
    /// No parse_quote!, no StubTerm, no run() helper -- exercises the full fragment pipeline.
    #[test]
    fn from_src_index_ctor_floor() {
        use crate::sugar::source_fragment::{parse_file, SourceFragment};

        let src = "fn f() { let _ = a[i]; }";
        let file = parse_file(src);
        let syn::Item::Fn(ref f) = file.items[0] else {
            panic!("expected fn")
        };
        let syn::Stmt::Local(ref loc) = f.block.stmts[0] else {
            panic!("expected local")
        };
        let index_expr = &*loc.init.as_ref().expect("no init").expr;
        let frag = SourceFragment::expr(index_expr, "<test>");

        // Gate: observed shape must be "Index".
        assert_eq!(frag.observed(), "Index", "fragment must observe as Index");

        // Build via recognize (the actual entry point).
        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let sugar_box = recognize(&frag, &fcx).expect("recognize should return Some for Index");

        // Desugar with a minimal real ctx (no run() helper).
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut fw = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut fw, 0);

        let Outcome::Complete(Desugared::Term(term)) = sugar_box.reduce(&ctx) else {
            panic!("expected Complete(Term) from IndexSugar::desugar on a[i]");
        };
        let Term::Ctor { ref name, ref args } = *term else {
            panic!("expected Term::Ctor, got {:?}", term);
        };
        assert_eq!(name, "index");
        assert_eq!(args.len(), 2, "index ctor must have exactly 2 args");

        // Container is the FIRST arg, index the SECOND (order is significant).
        let Term::Var {
            name: ref container_name,
        } = *args[0]
        else {
            panic!("expected Var for container arg, got {:?}", args[0]);
        };
        let Term::Var {
            name: ref index_name,
        } = *args[1]
        else {
            panic!("expected Var for index arg, got {:?}", args[1]);
        };
        assert_eq!(container_name, "a");
        assert_eq!(index_name, "i");
    }

    #[test]
    fn emits_index_ctor_container_then_idx() {
        // `a[i]` -> `Ctor { name: "index", args: [Var(a), Var(i)] }` -- the exact ctor
        // the `Expr::Index` constructive tail emits, container FIRST then index.
        let node = node_from_src("a[i]");
        let Outcome::Complete(Desugared::Term(term)) = run(&node) else {
            panic!("expected a Complete term");
        };
        match &*term {
            Term::Ctor { name, args } => {
                assert_eq!(name, "index");
                assert_eq!(args.len(), 2);
                let vars: Vec<String> = args
                    .iter()
                    .map(|a| match &**a {
                        Term::Var { name } => name.clone(),
                        other => panic!("expected a Var arg, got {other:?}"),
                    })
                    .collect();
                // Container is the FIRST arg, index the SECOND (order is significant).
                assert_eq!(vars, vec!["a".to_string(), "i".to_string()]);
            }
            other => panic!("expected a Ctor, got {other:?}"),
        }
    }
}
