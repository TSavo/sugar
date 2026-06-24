// SPDX-License-Identifier: Apache-2.0
//
// `.into()` over a target-typed primitive literal floor. The factory supplies the
// compiler-owned target type from the surrounding typed binding; this sugar reduces
// the receiver body, dispatches the completed floor through a visitor, and emits the
// target primitive floor.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::Expr;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::int_literal::{
    from_impl_exists, primitive_int_kind, ExactInt, IntKind, NumericFloor,
};
use crate::sugar::term_dispatch::{ScalarFloorAccept, ScalarFloorVisitor};
use crate::{token_key, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("into", &["method"], recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "into" || !call.args.is_empty() {
        return None;
    }
    let Some(target) = fcx.expected_type().map(str::to_string) else {
        panic!(
            "into sugar cannot be constructed without compiler-provided target type for `{}`",
            token_key(expr)
        )
    };
    Some(Box::new(IntoSugar {
        receiver: SugarBody::term(&call.receiver, fcx),
        target,
        site: token_key(expr),
    }))
}

struct IntoSugar {
    receiver: SugarBody<TermFloor>,
    target: String,
    site: String,
}

impl Sugar for IntoSugar {
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        let target = primitive_int_kind(&self.target).unwrap_or_else(|| {
            panic!(
                "into target `{}` has no primitive-floor dispatch owner yet for `{}`",
                self.target, self.site
            )
        });
        let receiver = match self.receiver.reduce(ctx) {
            Outcome::Complete(d) => d.into_term().unwrap_or_else(|| {
                panic!("into receiver completed as non-term for `{}`", self.site)
            }),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        receiver.accept_scalar_floor(IntoPrimitiveVisitor {
            target,
            site: &self.site,
        })
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

struct IntoPrimitiveVisitor<'a> {
    target: IntKind,
    site: &'a str,
}

impl ScalarFloorVisitor for IntoPrimitiveVisitor<'_> {
    type Output = Outcome;

    fn visit_numeric(self, floor: NumericFloor) -> Self::Output {
        let term = match floor {
            NumericFloor::Untyped(value) => ExactInt::Signed(value).term_for_kind(self.target),
            NumericFloor::Typed { value, kind } => {
                if !from_impl_exists(kind, self.target) {
                    panic!(
                        "std Into is not implemented from `{}` to `{}` for `{}`",
                        kind.name, self.target.name, self.site
                    );
                }
                value.term_for_kind(self.target)
            }
        }
        .unwrap_or_else(|| {
            panic!(
                "numeric floor did not fit `.into()` target `{}` for `{}`",
                self.target.name, self.site
            )
        });
        Outcome::Complete(Desugared::Term(term))
    }

    fn visit_bool(self, value: bool) -> Self::Output {
        let term = ExactInt::Unsigned(if value { 1 } else { 0 })
            .term_for_kind(self.target)
            .unwrap_or_else(|| {
                panic!(
                    "bool `.into()` target `{}` has no primitive bool floor for `{}`",
                    self.target.name, self.site
                )
            });
        Outcome::Complete(Desugared::Term(term))
    }

    fn visit_char(self, value: char) -> Self::Output {
        if self.target.name != "u32" {
            panic!(
                "std Into<char> target `{}` is not implemented for `{}`",
                self.target.name, self.site
            );
        }
        let term = ExactInt::Unsigned(u128::from(u32::from(value)))
            .term_for_kind(self.target)
            .unwrap_or_else(|| {
                panic!(
                    "char `.into()` failed to emit u32 floor for `{}`",
                    self.site
                )
            });
        Outcome::Complete(Desugared::Term(term))
    }

    fn visit_runtime(self, _term: &Rc<Term>) -> Self::Output {
        Outcome::Incomplete(Effect::RuntimeNumericOperand {
            boundary: self.site.to_string(),
            operation: "into".to_string(),
            kind: self.target.name.to_string(),
        })
    }
}
