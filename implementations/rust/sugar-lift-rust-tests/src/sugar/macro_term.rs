// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Macro`: the mut-local temporal-instability refusal, then -- for a
// `macro_rules!` we HOLD THE DEFINITION FOR -- an EXPANSION complete walk that feeds the macro's
// own body back to the factory (`my_macro!(2,3)` -> `2 + 3` -> `+(2,3)`, which grounds).
// If it cannot expand to a term we know how to reduce, it takes the factory gap path.
//
// The expansion lives at DESUGAR time, not recognize time: the macro_rules registry
// hangs off `ReductionCtx`, which is in the DESUGAR-time `SugarCtx` (`ctx.reducer`), NOT
// the build-time `SugarBuildCtx`. So a term-position macro we can expand is a deferred
// complete walk: `recognize` news a `MacroSugar` carrying the macro node, and `desugar`
// does the lookup + token expansion + `build_term` recursion when it finally holds the
// reducer. An unexpandable macro (no held definition, opaque/builtin macro, or a non-term
// expansion) is an engine gap, not an opaque Complete.

use std::collections::BTreeMap;

use syn::Expr;

use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::term_leaf::reasoned_incomplete;
use crate::{
    macro_literal_contains_mut_local, sugar_ctx, token_key, Outcome, Sugar, SugarCtx,
    MAX_MACRO_EXPANSION_DEPTH,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::fallback_term("macro_term", recognize);

/// TERM recognizer for `Expr::Macro`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Macro(m) = expr else {
        return None;
    };
    let scope = fcx.scope();
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
        return Some(reasoned_incomplete(format!(
            "macro in term position references a `let mut` local; \
             temporally unstable — refused: `{token_str}`"
        )));
    }
    // A term-position macro we MIGHT be able to expand: defer the decision to
    // `desugar` (which holds the reducer's macro registry).
    Some(Box::new(MacroSugar { mac: m.clone() }))
}

/// A term-position macro invocation whose disposition is decided at DESUGAR time. If
/// `ctx.reducer` holds a `macro_rules!` definition for the macro's name, `desugar`
/// expands the invocation tokens against that definition, parses the expansion as a
/// single `syn::Expr`, and lifts that expression back through `build_term` -- so a macro
/// whose body is `$a + $b` completes to a GROUNDED `+(a, b)` term. Otherwise (no held
/// definition, an unparseable / non-`Expr` expansion, or expansion depth exceeded) it
/// structurally bails to the factory gap path.
pub(crate) struct MacroSugar {
    /// The macro invocation node (e.g. `add2!(2, 3)`), owned so the expansion can run at
    /// desugar time when the reducer is in hand.
    pub(crate) mac: syn::ExprMacro,
}

impl MacroSugar {
    /// Try to expand this macro invocation to a single TERM-position Sugar using the
    /// reducer's `macro_rules!` registry. `Some(sugar)` if the macro is one we hold a
    /// definition for AND its expansion parses as a single `syn::Expr`; `None` if the
    /// macro is opaque/builtin/ambiguous, expansion failed, or the expansion is not a
    /// single expression (e.g. a multi-stmt block). Recursion is bounded by
    /// `ctx.macro_depth`.
    fn try_expand(&self, ctx: &SugarCtx) -> Option<Box<dyn Sugar>> {
        // Recursion guard: a macro whose body invokes another (in-source) macro must not
        // loop. Beyond the cap, gap rather than inventing an opaque complete.
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
        // gap rather than guess (no statement-level re-entry from term position -- that
        // path is the statement collector's, not the term lifter's).
        let parsed: Expr = syn::parse2(expanded).ok()?;
        // Reconstruct the build-time env from the desugar-time env: the macro's expansion
        // is lifted in the SAME scope/options the invocation was seen in. The expansion is
        // a fresh expr tree with no `let` initializers of its own to capture.
        let empty: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &empty);
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
        // expansion / depth exceeded): no Complete, no fake opaque term.
        Outcome::from_opt(None)
    }
}
