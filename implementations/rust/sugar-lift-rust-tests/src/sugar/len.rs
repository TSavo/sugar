// SPDX-License-Identifier: Apache-2.0
//
// `LenSugar`: std literal-sequence length in term position. For written literal arrays,
// slices, ranges, and identity iterator chains over them, `.len()` is a compiler/std
// axiom over the source construction: the value is the concrete element count. Runtime
// receivers decline to `MethodSugar`.

use sugar_ir_symbolic::num;
use syn::Expr;
use tracing::debug;

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::method_family;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("len", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "len" || !call.args.is_empty() {
        return None;
    }
    let len = method_family::literal_sequence_static_len_in_scope(
        &call.receiver,
        fcx.let_inits(),
        fcx.scope(),
    )?;
    Some(Box::new(LenSugar { len }))
}

struct LenSugar {
    len: usize,
}

impl Sugar for LenSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        debug!(
            target: "sugar_lift_rust_tests::sugar::len",
            len = self.len,
            "reducing literal sequence len"
        );
        Outcome::Dug(Desugared::Term(num(self.len as i128)))
    }
}
