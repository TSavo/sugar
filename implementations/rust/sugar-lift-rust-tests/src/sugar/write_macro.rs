// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for std `write!` / `writeln!`.
//
// These are compiler/std formatting builtins, not ordinary source-backed
// `macro_rules!` terms. This sugar owns the receiver-mutation boundary so the
// generic macro fallback is reserved for actual visible macro definitions.

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "write_macro",
    &["macro_term", "method"],
    crate::sugar::claim::SugarWitnesses::reasoned_bucket(
        "formatting/write side effect; no deterministic verdict-bearing output witness",
    ),
    recognize,
);

pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let name = frag.macro_name()?;
    if name != "write" && name != "writeln" {
        return None;
    }
    let arg_count = frag.macro_arg_count()?;
    let min_args = if name == "writeln" { 1 } else { 2 };
    if arg_count < min_args {
        panic!("{name}! has too few arguments; write more Sugar for this AST");
    }
    Some(Box::new(WriteMacroSugar {
        boundary: frag.token_str(),
    }))
}

struct WriteMacroSugar {
    boundary: String,
}

impl Sugar for WriteMacroSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::AmbiguousTemporalIdentity {
            reason: format!(
                "mutable-local state machine driven by fmt-write `{}`: write!/writeln! \
                 mutates its receiver and returns fmt::Result, so the term has no single \
                 timeless value until a receiver-specific floor replays the write; refused",
                self.boundary
            ),
        })
    }
}
