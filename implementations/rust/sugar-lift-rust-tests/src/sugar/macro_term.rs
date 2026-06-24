// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Macro`: the mut-local temporal-instability refusal, then -- for a
// `macro_rules!` we HOLD THE DEFINITION FOR -- an EXPANSION complete walk that feeds the macro's
// own body back to the factory (`my_macro!(2,3)` -> `2 + 3` -> `+(2,3)`, which grounds).
// If it cannot expand to a term we know how to reduce, construction records a panic
// reason; there is no runtime "unsupported" outcome for "we did not write the sugar".
//
// The expansion lives at DESUGAR time, not recognize time: the macro_rules registry
// hangs off `ReductionCtx`, which is in the DESUGAR-time `SugarCtx` (`ctx.reducer`), NOT
use syn::Expr;

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::term_leaf::reasoned_incomplete;
use crate::{
    macro_literal_contains_mut_local, token_key, Outcome, Sugar, SugarCtx,
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
    Some(Box::new(MacroSugar {
        body: build_macro_body(m, fcx),
    }))
}

/// A term-position macro invocation constructed with its expanded term body. If the
/// source registry does not hold a usable `macro_rules!` definition, the node panics at
/// desugar: that is a construction gap, not an honorable runtime effect.
pub(crate) struct MacroSugar {
    body: MacroTermBody,
}

enum MacroTermBody {
    Expanded(SugarBody<TermFloor>),
    Unconstructible(String),
}

fn build_macro_body(mac: &syn::ExprMacro, fcx: &SugarBuildCtx) -> MacroTermBody {
    let Some(name) = mac
        .mac
        .path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
    else {
        return MacroTermBody::Unconstructible(
            "term macro has no callable path; write more Sugar for this AST".to_string(),
        );
    };
    if fcx.macro_depth() >= MAX_MACRO_EXPANSION_DEPTH {
        return MacroTermBody::Unconstructible(format!(
            "macro `{name}` expansion depth exceeded; write more Sugar for this AST"
        ));
    }
    let Some(rules) = fcx.scope().macro_registry().lookup(&name) else {
        return MacroTermBody::Unconstructible(format!(
            "macro `{name}` has no visible macro_rules source; write more Sugar for this AST"
        ));
    };
    let expanded = match crate::macro_expand::expand(&rules, mac.mac.tokens.clone()) {
        Ok(expanded) => expanded,
        Err(error) => {
            return MacroTermBody::Unconstructible(format!(
                "macro `{name}` expansion failed: {error}; write more Sugar for this AST"
            ));
        }
    };
    // Expand to a TERM: the expansion must be a single expression. A `$a + $b` body
    // parses straight as `Expr::Binary`; a `{ tail }` body parses as `Expr::Block`,
    // which `block_term` recursing through `build_term` handles transparently. A
    // multi-statement / non-expr expansion does NOT parse as an `Expr` here, so this is
    // a construction gap, not a runtime effect.
    let parsed: Expr = match syn::parse2(expanded) {
        Ok(parsed) => parsed,
        Err(error) => {
            return MacroTermBody::Unconstructible(format!(
                "macro `{name}` expansion did not parse as a term expression: {error}; write more Sugar for this AST"
            ));
        }
    };
    let child_fcx = fcx.with_macro_depth(fcx.macro_depth() + 1);
    MacroTermBody::Expanded(SugarBody::term(&parsed, &child_fcx))
}

impl Sugar for MacroSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match &self.body {
            MacroTermBody::Expanded(body) => body.reduce(ctx),
            MacroTermBody::Unconstructible(reason) => {
                panic!("{reason}");
            }
        }
    }
}
