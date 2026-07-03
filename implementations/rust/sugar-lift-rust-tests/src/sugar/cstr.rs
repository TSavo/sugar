// SPDX-License-Identifier: Apache-2.0
//
// C string literals are compiler-checked byte sequences with an implicit trailing
// NUL. When the receiver bottoms out in a literal `c"..."`, the stdlib CStr
// accessors are compiler axioms over those bytes, not opaque runtime calls.

use std::rc::Rc;

use sugar_ir_symbolic::{make_var, Term};
use syn::{Expr, ExprLit, Lit};
use tracing::debug;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{FloorRead, LiteralCStrFloor, SugarBody, SugarBuildCtx};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    bytes_literal_term_from_bytes, bytes_to_hex, num, Desugared, Outcome, Sugar, SugarCtx,
};

// A stable binding that resolves to compiler-axiom CStr bytes is a concrete
// literal floor before generic bound-path transparency.
pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "cstr",
    &["bound_path"],
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
            #[test]
            fn t_cstr_good() {
                assert_eq!(c"abc".count_bytes(), 3);
            }
        "#,
        r#"
            #[test]
            fn t_cstr_bad() {
                assert_eq!(c"abc".count_bytes(), 4);
            }
        "#,
    ),
    recognize,
);

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    if has_literal_cstr_floor(expr, fcx) {
        debug!(
            target: "sugar_lift_rust_tests::sugar::cstr",
            "cstr literal claimed as compiler-axiom bytes"
        );
        return Some(Box::new(CStrSugar::identity(SugarBody::literal_cstr(
            expr, fcx,
        ))));
    }

    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !call.args.is_empty() {
        return None;
    }
    let receiver = (*call.receiver).clone();
    cstr_receiver_bytes(&receiver, fcx, &mut Vec::new())?;
    match call.method.to_string().as_str() {
        "count_bytes" => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::cstr",
                method = "count_bytes",
                "cstr literal-backed method claimed"
            );
            Some(Box::new(CStrSugar::method(
                SugarBody::literal_cstr(&receiver, fcx),
                CStrKind::CountBytes,
            )))
        }
        "to_bytes" => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::cstr",
                method = "to_bytes",
                "cstr literal-backed method claimed"
            );
            Some(Box::new(CStrSugar::method(
                SugarBody::literal_cstr(&receiver, fcx),
                CStrKind::ToBytes,
            )))
        }
        "to_bytes_with_nul" => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::cstr",
                method = "to_bytes_with_nul",
                "cstr literal-backed method claimed"
            );
            Some(Box::new(CStrSugar::method(
                SugarBody::literal_cstr(&receiver, fcx),
                CStrKind::ToBytesWithNul,
            )))
        }
        _ => None,
    }
}

pub(crate) fn has_literal_cstr_floor(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    cstr_receiver_bytes(expr, fcx, &mut Vec::new()).is_some()
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct CStrBytes {
    without_nul: Vec<u8>,
    with_nul: Vec<u8>,
}

impl CStrBytes {
    fn from_lit(lit: &syn::LitCStr) -> Self {
        let value = lit.value();
        Self {
            without_nul: value.as_bytes().to_vec(),
            with_nul: value.as_bytes_with_nul().to_vec(),
        }
    }

    pub(crate) fn without_nul(&self) -> &[u8] {
        &self.without_nul
    }

    pub(crate) fn with_nul(&self) -> &[u8] {
        &self.with_nul
    }

    pub(crate) fn accept_literal_cstr<V: LiteralCStrVisitor>(&self, visitor: V) -> V::Output {
        visitor.visit_cstr(self)
    }
}

pub(crate) trait LiteralCStrVisitor {
    type Output;

    fn visit_cstr(self, bytes: &CStrBytes) -> Self::Output;
}

struct LiteralCStrSugar {
    bytes: CStrBytes,
}

impl Sugar for LiteralCStrSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Complete(Desugared::LiteralCStr(self.bytes.clone()))
    }
}

#[derive(Clone, Copy)]
enum CStrKind {
    Identity,
    CountBytes,
    ToBytes,
    ToBytesWithNul,
}

pub(crate) struct CStrSugar {
    body: SugarBody<LiteralCStrFloor>,
    kind: CStrKind,
}

impl CStrSugar {
    fn identity(body: SugarBody<LiteralCStrFloor>) -> Self {
        Self {
            body,
            kind: CStrKind::Identity,
        }
    }

    fn method(body: SugarBody<LiteralCStrFloor>, kind: CStrKind) -> Self {
        Self { body, kind }
    }
}

impl Sugar for CStrSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let bytes = match self.body.reduce_literal_cstr(ctx) {
            FloorRead::Complete(bytes) => bytes,
            FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let term = bytes.accept_literal_cstr(CStrTermVisitor { kind: self.kind });
        Outcome::Complete(Desugared::Term(term))
    }
}

struct CStrTermVisitor {
    kind: CStrKind,
}

impl LiteralCStrVisitor for CStrTermVisitor {
    type Output = Rc<Term>;

    fn visit_cstr(self, bytes: &CStrBytes) -> Self::Output {
        match self.kind {
            CStrKind::Identity => cstr_literal_term_from_bytes_with_nul(bytes.with_nul()),
            CStrKind::CountBytes => num(bytes.without_nul().len() as i128),
            CStrKind::ToBytes => bytes_literal_term_from_bytes(bytes.without_nul()),
            CStrKind::ToBytesWithNul => bytes_literal_term_from_bytes(bytes.with_nul()),
        }
    }
}

pub(crate) fn build_literal_cstr_body(expr: &Expr, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    let bytes = cstr_receiver_bytes(expr, fcx, &mut Vec::new()).unwrap_or_else(|| {
        panic!(
            "literal CStr construction failed for `{}`",
            crate::token_key(expr)
        )
    });
    Box::new(LiteralCStrSugar { bytes })
}

pub(crate) fn literal_cstr_floor_from_outcome(reduction: Outcome) -> FloorRead<CStrBytes> {
    match reduction {
        Outcome::Complete(Desugared::LiteralCStr(value)) => FloorRead::Complete(value),
        Outcome::Complete(_) => {
            panic!("literal CStr child completed a non-literal-cstr floor; fix the factory")
        }
        Outcome::Incomplete(effect) => FloorRead::Incomplete(effect),
    }
}

fn cstr_literal_term_from_bytes_with_nul(bytes: &[u8]) -> Rc<Term> {
    make_var(format!("literal:cstr({})", bytes_to_hex(bytes)))
}

fn direct_cstr_bytes(expr: &Expr) -> Option<CStrBytes> {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::CStr(cstr),
            ..
        }) => Some(CStrBytes::from_lit(cstr)),
        Expr::Paren(paren) => direct_cstr_bytes(&paren.expr),
        Expr::Group(group) => direct_cstr_bytes(&group.expr),
        _ => None,
    }
}

fn cstr_receiver_bytes(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    resolving: &mut Vec<String>,
) -> Option<CStrBytes> {
    if let Some(bytes) = direct_cstr_bytes(expr) {
        return Some(bytes);
    }
    match expr {
        Expr::Reference(reference) if reference.mutability.is_none() => {
            cstr_receiver_bytes(&reference.expr, fcx, resolving)
        }
        Expr::Paren(paren) => cstr_receiver_bytes(&paren.expr, fcx, resolving),
        Expr::Group(group) => cstr_receiver_bytes(&group.expr, fcx, resolving),
        Expr::Path(path) if path.qself.is_none() => {
            let Some(ident) = path.path.get_ident() else {
                return None;
            };
            let name = ident.to_string();
            if fcx.resolving_bound_path(&name) || resolving.iter().any(|current| current == &name) {
                return None;
            }
            resolving.push(name.clone());
            if let Some(current) = fcx.scope().temporal_rewrite_expr_for(&name) {
                let child_fcx = fcx.with_bound_path(&name);
                let out = cstr_receiver_bytes(&current, &child_fcx, resolving);
                resolving.pop();
                return out;
            }
            let Some(init) = fcx.scope().stable_let_binding_for_term(&name) else {
                resolving.pop();
                return None;
            };
            let child_fcx = fcx.with_bound_path(&name);
            let out = cstr_receiver_bytes(init, &child_fcx, resolving);
            resolving.pop();
            out
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct CountBytesWithNul;

    impl LiteralCStrVisitor for CountBytesWithNul {
        type Output = usize;

        fn visit_cstr(self, bytes: &CStrBytes) -> Self::Output {
            bytes.with_nul().len()
        }
    }

    #[test]
    fn literal_cstr_floor_exposes_bytes_through_neutral_visitor() {
        let expr: Expr = syn::parse_str(r#"c"hi""#).unwrap();
        let bytes = direct_cstr_bytes(&expr).expect("literal cstr bytes");

        assert_eq!(bytes.accept_literal_cstr(CountBytesWithNul), 3);
    }

    #[test]
    fn literal_cstr_floor_from_outcome_rejects_non_cstr_floors() {
        let bytes = CStrBytes {
            without_nul: b"hi".to_vec(),
            with_nul: b"hi\0".to_vec(),
        };

        match literal_cstr_floor_from_outcome(Outcome::Complete(Desugared::LiteralCStr(bytes))) {
            crate::sugar::factory::FloorRead::Complete(value) => {
                assert_eq!(value.without_nul(), b"hi");
                assert_eq!(value.with_nul(), b"hi\0");
            }
            crate::sugar::factory::FloorRead::Incomplete(_) => {
                panic!("literal cstr floor should complete")
            }
        }
    }

    #[test]
    fn literal_cstr_floor_composes_into_debug_format_value() {
        let bytes = CStrBytes {
            without_nul: b"hi".to_vec(),
            with_nul: b"hi\0".to_vec(),
        };
        let out = crate::sugar::format::render_format_values(
            "{:?}",
            &[crate::sugar::format::FmtValue::CStr(bytes)],
            &Default::default(),
            &Default::default(),
            "literal_cstr_floor_composes_into_debug_format_value",
        );

        match out {
            crate::sugar::factory::FloorRead::Complete(value) => assert_eq!(value, "\"hi\""),
            crate::sugar::factory::FloorRead::Incomplete(effect) => {
                panic!(
                    "literal cstr format should complete, got {}",
                    effect.reason()
                )
            }
        }
    }

    #[test]
    #[should_panic(expected = "rustc would reject")]
    fn literal_cstr_display_format_panics_as_compiler_impossible() {
        let bytes = CStrBytes {
            without_nul: b"hi".to_vec(),
            with_nul: b"hi\0".to_vec(),
        };

        let _ = crate::sugar::format::render_format_values(
            "{}",
            &[crate::sugar::format::FmtValue::CStr(bytes)],
            &Default::default(),
            &Default::default(),
            "literal_cstr_display_format_panics_as_compiler_impossible",
        );
    }
}
