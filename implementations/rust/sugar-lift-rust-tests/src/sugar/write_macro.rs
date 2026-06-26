// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for std `write!` / `writeln!`.
//
// These are compiler/std formatting builtins, not ordinary source-backed
// `macro_rules!` terms. This sugar owns the receiver-mutation boundary so the
// generic macro fallback is reserved for actual visible macro definitions.

use syn::Expr;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::format::parse_args;
use crate::{token_key, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("write_macro", &["macro_term", "method"], recognize);

pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Macro(expr_macro) = expr else {
        return None;
    };
    let Some(name) = expr_macro
        .mac
        .path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
    else {
        return None;
    };
    if name != "write" && name != "writeln" {
        return None;
    }

    let args = parse_args(&expr_macro.mac.tokens).unwrap_or_else(|| {
        panic!("{name}! arguments did not parse; write more Sugar for this AST")
    });
    let min_args = if name == "writeln" { 1 } else { 2 };
    if args.len() < min_args {
        panic!("{name}! has too few arguments; write more Sugar for this AST");
    }

    Some(Box::new(WriteMacroSugar {
        boundary: token_key(expr),
    }))
}

struct WriteMacroSugar {
    boundary: String,
}

impl Sugar for WriteMacroSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::AmbiguousTemporalIdentity {
            boundary: self.boundary.clone(),
            reason: format!(
                "mutable-local state machine driven by fmt-write `{}`: write!/writeln! \
                 mutates its receiver and returns fmt::Result, so the term has no single \
                 timeless value until a receiver-specific floor replays the write; refused",
                self.boundary
            ),
        })
    }
}
