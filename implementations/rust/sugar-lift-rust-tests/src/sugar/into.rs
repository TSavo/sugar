// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `.into()` over a target-typed primitive literal floor. The factory supplies the
// compiler-owned target type from the surrounding typed binding; this sugar reduces
// the receiver body, dispatches the completed floor through a visitor, and emits the
// target primitive floor.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{IeeeFloatFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::float_floor::{
    runtime_float, stable_width_from_type_key, IeeeFloatAccept, IeeeFloatValue, IeeeFloatVisitor,
    IeeeFloatWidth,
};
use crate::sugar::int_literal::{
    from_impl_exists, primitive_int_kind, ExactInt, IntKind, NumericFloor,
};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_dispatch::{ScalarFloorAccept, ScalarFloorVisitor};
use crate::{Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "into",
    &["method"],
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
            #[test]
            fn t_into_good() {
                let x: u32 = true.into();
                assert_eq!(x, 1u32);
            }
        "#,
        r#"
            #[test]
            fn t_into_bad() {
                let x: u32 = true.into();
                assert_eq!(x, 0u32);
            }
        "#,
    ),
    recognize,
);

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if frag.call_method_key().as_deref() != Some("into") {
        return None;
    }
    if frag.call_arg_count() != 0 {
        return None;
    }
    let target_type = fcx.expected_type()?;
    let target = into_target(target_type)?;
    let receiver_frag = frag.call_receiver()?;
    let receiver = match target {
        IntoTarget::Integer(_) => IntoReceiver::Integer(SugarBody::term_frag(&receiver_frag, fcx)),
        IntoTarget::Float(width) => IntoReceiver::Float(SugarBody::ieee_float_frag(
            &receiver_frag,
            fcx,
            Some(width),
            "into",
        )),
    };
    Some(Box::new(IntoSugar {
        receiver,
        target,
        site: frag.token_str(),
    }))
}

struct IntoSugar {
    receiver: IntoReceiver,
    target: IntoTarget,
    site: String,
}

impl Sugar for IntoSugar {
    fn reduce(&self, ctx: &SugarCtx) -> Outcome {
        match (&self.receiver, self.target) {
            (IntoReceiver::Integer(receiver), IntoTarget::Integer(target)) => {
                let receiver = match receiver.reduce(ctx) {
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
            (IntoReceiver::Float(receiver), IntoTarget::Float(target)) => {
                let receiver = match receiver.reduce(ctx) {
                    Outcome::Complete(d) => d.into_term().unwrap_or_else(|| {
                        panic!("into receiver completed as non-term for `{}`", self.site)
                    }),
                    Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
                };
                receiver.accept_ieee_float(IntoFloatVisitor {
                    target,
                    site: &self.site,
                })
            }
            _ => panic!(
                "into receiver floor diverged from target for `{}`",
                self.site
            ),
        }
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        self.reduce(ctx)
    }
}

enum IntoReceiver {
    Integer(SugarBody<TermFloor>),
    Float(SugarBody<IeeeFloatFloor>),
}

#[derive(Clone, Copy)]
enum IntoTarget {
    Integer(IntKind),
    Float(IeeeFloatWidth),
}

fn into_target(ty: &str) -> Option<IntoTarget> {
    primitive_int_kind(ty)
        .map(IntoTarget::Integer)
        .or_else(|| stable_width_from_type_key(ty).map(IntoTarget::Float))
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
            operation: "into".to_string(),
            kind: self.target.name.to_string(),
        })
    }
}

struct IntoFloatVisitor<'a> {
    target: IeeeFloatWidth,
    site: &'a str,
}

impl IeeeFloatVisitor for IntoFloatVisitor<'_> {
    type Output = Outcome;

    fn visit_float(self, value: IeeeFloatValue) -> Self::Output {
        Outcome::Complete(Desugared::Term(
            value.into_width_term(self.target, self.site),
        ))
    }

    fn visit_non_float(self, _term: &Rc<Term>) -> Self::Output {
        runtime_float(self.site)
    }
}

#[cfg(test)]
mod tests {
    use crate::sugar::source_fragment::{FragNode, SourceFragment};
    use syn::Expr;

    fn e(src: &str) -> Expr {
        syn::parse_str(src).expect("parse expr")
    }

    #[test]
    fn from_src_into_method_key_is_into() {
        // positive: x.into() -> call_method_key == "into", 0 args, has receiver
        let expr = e("x.into()");
        let frag = SourceFragment::from_node(FragNode::Expr(&expr), "<test>");
        assert_eq!(frag.observed(), "MethodCall", "observed must be MethodCall");
        assert_eq!(
            frag.call_method_key().as_deref(),
            Some("into"),
            "method key must be into"
        );
        assert_eq!(frag.call_arg_count(), 0, "into() takes no args");
        assert!(frag.call_receiver().is_some(), "receiver must be present");
    }

    #[test]
    fn discrimination_map_not_into() {
        // discrimination: .map() method key is not "into"
        let expr = e("x.map(f)");
        let frag = SourceFragment::from_node(FragNode::Expr(&expr), "<test>");
        assert_ne!(
            frag.call_method_key().as_deref(),
            Some("into"),
            ".map() must not match into key"
        );
    }

    #[test]
    fn structural_into_receiver_observed_is_name() {
        // structural: receiver of `x.into()` is Expr::Path -> observed "Name"
        let expr = e("x.into()");
        let frag = SourceFragment::from_node(FragNode::Expr(&expr), "<test>");
        let receiver = frag.call_receiver().expect("receiver must be present");
        // Expr::Path maps to "Name" in expr_kind()
        assert_eq!(
            receiver.observed(),
            "Name",
            "receiver of x.into() is Expr::Path -> 'Name'"
        );
    }
}
