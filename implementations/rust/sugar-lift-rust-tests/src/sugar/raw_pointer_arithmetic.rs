// SPDX-License-Identifier: Apache-2.0
//
// Raw-pointer arithmetic (`ptr.wrapping_add(n)`, `wrapping_byte_add`, and their
// subtraction siblings) is address / provenance work, not primitive-integer
// wrapping math. Recognize it before `primitive_int` so literal integer wrapping
// stays on the numeric floor while pointer arithmetic stops at its real runtime
// operand boundary.

use syn::{Expr, Type};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    canonical_term_sig, simple_path_name, strip_refs_groups, Effect, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("raw_pointer_arithmetic", &["primitive_int"], recognize);

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.args.len() != 1
        || !matches!(
            call.method.to_string().as_str(),
            "wrapping_add" | "wrapping_sub" | "wrapping_byte_add" | "wrapping_byte_sub"
        )
        || !raw_pointer_value_in_scope(&call.receiver, fcx, 0)
    {
        return None;
    }
    Some(Box::new(RawPointerArithmeticSugar {
        receiver: SugarBody::term(&call.receiver, fcx),
        rhs: SugarBody::term(&call.args[0], fcx),
        method: call.method.to_string(),
    }))
}

struct RawPointerArithmeticSugar {
    receiver: SugarBody<TermFloor>,
    rhs: SugarBody<TermFloor>,
    method: String,
}

impl Sugar for RawPointerArithmeticSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match self.receiver.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_term()
                .unwrap_or_else(|| panic!("raw pointer arithmetic receiver completed as non-term")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        match self.rhs.reduce(ctx) {
            Outcome::Complete(d) => {
                d.into_term()
                    .unwrap_or_else(|| panic!("raw pointer arithmetic rhs completed as non-term"));
            }
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        }
        Outcome::Incomplete(Effect::RuntimeNumericOperand {
            boundary: canonical_term_sig(&receiver),
            operation: self.method.clone(),
            kind: "raw pointer".to_string(),
        })
    }
}

fn raw_pointer_value_in_scope(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Cast(cast) if matches!(cast.ty.as_ref(), Type::Ptr(_)) => true,
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = simple_path_name(expr) else {
                return false;
            };
            if fcx
                .scope()
                .let_binding_expected_type(&name)
                .is_some_and(raw_pointer_type_key)
            {
                return true;
            }
            fcx.scope()
                .stable_let_binding_for_term(&name)
                .is_some_and(|init| raw_pointer_value_in_scope(init, fcx, depth + 1))
        }
        Expr::Paren(paren) => raw_pointer_value_in_scope(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => raw_pointer_value_in_scope(&group.expr, fcx, depth + 1),
        _ => false,
    }
}

fn raw_pointer_type_key(key: &str) -> bool {
    key.trim_start().starts_with('*')
}
