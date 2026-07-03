// SPDX-License-Identifier: Apache-2.0
//
// Primitive `<IntT>::from(..)` / `IntT::from(..)` sugar.
//
// The call head owns only the destination type. The argument is constructed as a
// typed term body and dispatches as the source floor: bool -> 0/1, char -> codepoint
// for destinations Rust implements, numeric -> checked std `From` conversion.

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::int_literal::{from_impl_exists, ExactInt, IntKind, NumericFloor};
use crate::sugar::ip_addr::{primitive_int_from_literal_ip, LiteralIp};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_dispatch::{ScalarFloorAccept, ScalarFloorVisitor};
use crate::{Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "from_bool",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_from_bool_good() {
                    assert_eq!(1u8, <u8>::from(true));
                }
            "#,
            r#"
                #[test]
                fn t_from_bool_bad() {
                    assert_eq!(1u8, <u8>::from(false));
                }
            "#,
        ),
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if frag.call_arg_count() != 1 {
        return None;
    }
    let func_frag = frag.call_func()?;
    let dst = func_frag.path_primitive_int_from_kind()?;
    let args = frag.call_args();
    Some(Box::new(FromPrimitiveSugar {
        arg: SugarBody::term_frag(&args[0], fcx),
        dst,
        site: frag.token_str(),
    }))
}

struct FromPrimitiveSugar {
    arg: SugarBody<TermFloor>,
    dst: IntKind,
    site: String,
}

impl Sugar for FromPrimitiveSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let arg = match self.arg.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_term()
                .unwrap_or_else(|| panic!("primitive From argument completed as non-term")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        arg.accept_scalar_floor(PrimitiveFromVisitor {
            dst: self.dst,
            site: &self.site,
        })
    }
}

struct PrimitiveFromVisitor<'a> {
    dst: IntKind,
    site: &'a str,
}

impl ScalarFloorVisitor for PrimitiveFromVisitor<'_> {
    type Output = Outcome;

    fn visit_numeric(self, floor: NumericFloor) -> Self::Output {
        let NumericFloor::Typed { value, kind } = floor else {
            panic!(
                "primitive From `{}` received an untyped numeric floor for `{}`",
                self.dst.name, self.site
            );
        };
        if !from_impl_exists(kind, self.dst) {
            panic!(
                "primitive From `{}` received source type `{}` the compiler would reject for `{}`",
                self.dst.name, kind.name, self.site
            );
        }
        let term = value.term_for_kind(self.dst).unwrap_or_else(|| {
            panic!(
                "primitive From `{}` value did not fit destination for `{}`",
                self.dst.name, self.site
            )
        });
        Outcome::Complete(Desugared::Term(term))
    }

    fn visit_bool(self, value: bool) -> Self::Output {
        let term = ExactInt::Unsigned(u128::from(value))
            .term_for_kind(self.dst)
            .unwrap_or_else(|| {
                panic!(
                    "primitive From `{}` could not lower bool for `{}`",
                    self.dst.name, self.site
                )
            });
        Outcome::Complete(Desugared::Term(term))
    }

    fn visit_char(self, value: char) -> Self::Output {
        if !char_from_impl_exists(self.dst) {
            panic!(
                "primitive From `{}` does not implement From<char> for `{}`",
                self.dst.name, self.site
            );
        }
        let term = ExactInt::Unsigned(u128::from(u32::from(value)))
            .term_for_kind(self.dst)
            .unwrap_or_else(|| {
                panic!(
                    "primitive From `{}` could not lower char for `{}`",
                    self.dst.name, self.site
                )
            });
        Outcome::Complete(Desugared::Term(term))
    }

    fn visit_ip(self, _term: &Rc<Term>, ip: LiteralIp) -> Self::Output {
        Outcome::Complete(Desugared::Term(primitive_int_from_literal_ip(
            ip, self.dst, self.site,
        )))
    }

    fn visit_runtime(self, _term: &Rc<Term>) -> Self::Output {
        Outcome::Incomplete(Effect::RuntimeNumericOperand {
            boundary: self.site.to_string(),
            operation: "From".to_string(),
            kind: self.dst.name.to_string(),
        })
    }
}

fn char_from_impl_exists(dst: IntKind) -> bool {
    !dst.signed && dst.bits >= 32
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    fn from_call_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = frag.function_body().expect("fn has a body");
        let stmts = body.statements();
        let terms = stmts[0].terms();
        terms[0]
    }

    /// Positive: `u32::from(x)` observed as `"Call"`, arg count 1, `call_func()`
    /// yields a `"Name"` fragment, `path_primitive_int_from_kind()` returns
    /// `IntKind { name: "u32", signed: false, bits: 32 }`. No as_expr / Expr:: / raw
    /// field access anywhere in this test.
    #[test]
    fn from_src_plain_path_observed_func_and_arg() {
        let file = parse_file("fn f(x: u8) -> u32 { u32::from(x) }");
        let frag = from_call_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "Call");
        assert_eq!(frag.call_arg_count(), 1);

        let func_frag = frag.call_func().expect("func fragment present");
        assert_eq!(func_frag.observed(), "Name");

        let dst = func_frag
            .path_primitive_int_from_kind()
            .expect("u32::from is a primitive int from");
        assert_eq!(dst.name, "u32");
        assert!(!dst.signed);
        assert_eq!(dst.bits, 32);

        let args = frag.call_args();
        assert_eq!(args.len(), 1);
        assert_eq!(args[0].observed(), "Name");
    }

    /// Discrimination: `<u64>::from(x)` (qualified-self form) decodes to
    /// `IntKind { name: "u64", signed: false, bits: 64 }`. Proves
    /// `path_primitive_int_from_kind` handles the qself path distinct from
    /// the two-segment path.
    #[test]
    fn from_src_qself_form_decodes_to_u64_kind() {
        let file = parse_file("fn f(x: u32) -> u64 { <u64>::from(x) }");
        let frag = from_call_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "Call");
        assert_eq!(frag.call_arg_count(), 1);

        let func_frag = frag.call_func().expect("func fragment present");
        let dst = func_frag
            .path_primitive_int_from_kind()
            .expect("<u64>::from is a primitive int from");
        assert_eq!(dst.name, "u64");
        assert!(!dst.signed);
        assert_eq!(dst.bits, 64);
    }

    /// Structural: a `BinOp` is not a `Call`; `call_func()` returns `None` and
    /// `call_arg_count()` returns 0. The accessors are shape-specific and do not
    /// bleed across kinds.
    #[test]
    fn structural_binop_returns_none_from_call_func() {
        let file = parse_file("fn f(a: u32, b: u32) -> u32 { a + b }");
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = frag.function_body().unwrap();
        let stmts = body.statements();
        let terms = stmts[0].terms();
        let binop_frag = &terms[0];

        assert_eq!(binop_frag.observed(), "BinOp");
        assert!(binop_frag.call_func().is_none());
        assert_eq!(binop_frag.call_arg_count(), 0);
        // path_primitive_int_from_kind on a non-path returns None
        assert!(binop_frag.path_primitive_int_from_kind().is_none());
    }
}
