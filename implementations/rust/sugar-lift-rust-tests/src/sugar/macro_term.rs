// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Macro`: the FormatSugar dig (`format!`/`concat!` dissolve
// to a `str_const`), the mut-local temporal-instability refusal, then -- for a
// `macro_rules!` we HOLD THE DEFINITION FOR -- an EXPANSION dig that feeds the macro's
// own body back to the factory (`my_macro!(2,3)` -> `2 + 3` -> `+(2,3)`, which grounds),
// and only ELSE the opaque `macro:<tokens>` EUF var.
//
// The expansion lives at DESUGAR time, not recognize time: the macro_rules registry
// hangs off `ReductionCtx`, which is in the DESUGAR-time `SugarCtx` (`ctx.reducer`), NOT
// the build-time `FactoryCtx`. So a term-position macro we can expand is a deferred dig:
// `recognize` news a `MacroSugar` carrying the macro node + the opaque fallback term, and
// `desugar` does the lookup + token expansion + `build_term` recursion when it finally
// holds the reducer. An unexpandable macro (no held definition, opaque/builtin macro, or
// a non-term expansion) falls back to the SAME opaque var the old factory emitted -- no
// regression.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{make_var, Term};
use syn::Expr;

use crate::sugar::factory::{build_term, FactoryCtx};
use crate::sugar::format::{stable_let_bindings, try_resolve_format};
use crate::sugar::term_leaf::{reasoned_hit, resolved_term};
use crate::{
    macro_literal_contains_mut_local, sugar_ctx, str_const, token_key, Desugared, Outcome, Sugar,
    SugarCtx, MAX_MACRO_EXPANSION_DEPTH,
};

/// TERM recognizer for `Expr::Macro`.
pub(crate) fn recognize(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Macro(m) = expr else {
        return None;
    };
    let scope = fcx.scope;
    let seg = m.mac.path.segments.last().map(|s| s.ident.to_string());
    if matches!(seg.as_deref(), Some("format") | Some("concat")) {
        let stable = stable_let_bindings(scope);
        match try_resolve_format(expr, &stable) {
            Ok(Some(s)) => return Some(resolved_term(str_const(s))),
            Err(reason) => return Some(reasoned_hit(reason)),
            Ok(None) => {}
        }
    }
    let token_str = token_key(expr);
    let contains_mut_local = m.mac.tokens.clone().into_iter().any(|tt| match &tt {
        proc_macro2::TokenTree::Ident(id) => scope.is_mut_local(&id.to_string()),
        proc_macro2::TokenTree::Literal(lit) => {
            let text = lit.to_string();
            macro_literal_contains_mut_local(&text, scope)
        }
        _ => false,
    });
    if contains_mut_local {
        return Some(reasoned_hit(format!(
            "macro in term position references a `let mut` local; \
             temporally unstable — refused: `{token_str}`"
        )));
    }
    // A term-position macro we MIGHT be able to expand: defer the decision to
    // `desugar` (which holds the reducer's macro registry). The opaque var is the
    // fallback if the macro is not one we hold a definition for, or its expansion is
    // not a liftable single TERM.
    Some(Box::new(MacroSugar {
        mac: m.clone(),
        opaque: make_var(format!("macro:{token_str}")),
    }))
}

/// A term-position macro invocation whose disposition is decided at DESUGAR time. If
/// `ctx.reducer` holds a `macro_rules!` definition for the macro's name, `desugar`
/// expands the invocation tokens against that definition, parses the expansion as a
/// single `syn::Expr`, and lifts that expression back through `build_term` -- so a macro
/// whose body is `$a + $b` digs to a GROUNDED `+(a, b)` term rather than going opaque.
/// Otherwise (no held definition, an unparseable / non-`Expr` expansion, or expansion
/// depth exceeded) it Digs the pre-built `opaque` `macro:<tokens>` EUF var -- the exact
/// coarse-but-valid universe-dig the old factory emitted. No regression for the
/// unexpandable case.
pub(crate) struct MacroSugar {
    /// The macro invocation node (e.g. `add2!(2, 3)`), owned so the expansion can run at
    /// desugar time when the reducer is in hand.
    pub(crate) mac: syn::ExprMacro,
    /// The fallback opaque `macro:<tokens>` EUF var, pre-built at recognize time.
    pub(crate) opaque: Rc<Term>,
}

impl MacroSugar {
    /// Try to expand this macro invocation to a single TERM-position Sugar using the
    /// reducer's `macro_rules!` registry. `Some(sugar)` if the macro is one we hold a
    /// definition for AND its expansion parses as a single `syn::Expr`; `None` (the
    /// caller falls back to the opaque var) if the macro is opaque/builtin/ambiguous,
    /// expansion failed, or the expansion is not a single expression (e.g. a multi-stmt
    /// block). Recursion is bounded by `ctx.macro_depth`.
    fn try_expand(&self, ctx: &SugarCtx) -> Option<Box<dyn Sugar>> {
        // Recursion guard: a macro whose body invokes another (in-source) macro must not
        // loop. Beyond the cap, fall back to opaque -- the coarse but valid dig.
        if ctx.macro_depth >= MAX_MACRO_EXPANSION_DEPTH {
            return None;
        }
        let name = self.mac.mac.path.segments.last()?.ident.to_string();
        let rules = ctx.reducer.macro_rules(&name)?;
        let expanded = crate::macro_expand::expand(&rules, self.mac.mac.tokens.clone()).ok()?;
        // Expand to a TERM: the expansion must be a single expression. A `$a + $b` body
        // parses straight as `Expr::Binary`; a `{ tail }` body parses as `Expr::Block`,
        // which `block_term` recursing through `build_term` handles transparently. A
        // multi-statement / non-expr expansion does NOT parse as an `Expr` here, so we
        // fall back to opaque rather than guess (no statement-level re-entry from term
        // position -- that path is the statement collector's, not the term lifter's).
        let parsed: Expr = syn::parse2(expanded).ok()?;
        // Reconstruct the build-time env from the desugar-time env: the macro's expansion
        // is lifted in the SAME scope/options the invocation was seen in. The expansion is
        // a fresh expr tree with no `let` initializers of its own to capture.
        let empty: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = FactoryCtx {
            scope: ctx.scope,
            options: ctx.options,
            let_inits: &empty,
        };
        Some(build_term(&parsed, &fcx))
    }
}

impl Sugar for MacroSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(node) = self.try_expand(ctx) {
            // Lift the expansion at one deeper macro level so a recursive macro is bounded
            // by the same `MAX_MACRO_EXPANSION_DEPTH` guard the statement path uses. The
            // `RefMut` is bound to a `let` so the re-wrapped `FloatWidthScope` borrow
            // outlives the `bumped` ctx the recursive `desugar` reads from.
            let mut fw = ctx.float_widths.borrow_mut();
            let bumped = sugar_ctx(
                ctx.scope,
                ctx.options,
                ctx.reducer,
                *fw,
                ctx.macro_depth + 1,
            );
            return node.desugar(&bumped);
        }
        // Unexpandable macro (no held definition / opaque / builtin / non-term
        // expansion / depth exceeded): the coarse-but-valid opaque universe-dig, the
        // exact term the old factory emitted.
        Outcome::Dug(Desugared::Term(Rc::clone(&self.opaque)))
    }
}
