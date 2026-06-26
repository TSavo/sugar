// SPDX-License-Identifier: Apache-2.0
//
// `ConstraintRuntimeBoundarySugar`: relation operands that are not missing literal
// reducers, but proven runtime boundaries. The only live owner here is the
// type-inferred parser result refusal used by assert_eq!/assert_ne! lowering.

use crate::{token_key, Effect};
use syn::Expr;

pub(crate) fn type_inferred_parse_result_effect(
    assertion: &str,
    lhs: &Expr,
    rhs: &Expr,
) -> Option<Effect> {
    type_inferred_parse_site(lhs, 0)
        .or_else(|| type_inferred_parse_site(rhs, 0))
        .map(|site| Effect::TypeInferredParseResult {
            assertion: assertion.to_string(),
            boundary: site,
        })
}

pub(crate) fn type_inferred_parse_result_reason(lhs: &Expr, rhs: &Expr) -> Option<String> {
    type_inferred_parse_site(lhs, 0)
        .or_else(|| type_inferred_parse_site(rhs, 0))
        .map(|site| type_inferred_parse_result_site_reason(&site))
}

pub(crate) fn type_inferred_parse_result_site_reason(site: &str) -> String {
    format!(
        "unsupported term `{site}`: type-inferred runtime parser result \
         (parse result type is supplied by assertion context, not by the call syntax; \
         no single constructible timeless value); refused"
    )
}

fn type_inferred_parse_site(expr: &Expr, depth: usize) -> Option<String> {
    if depth > 16 {
        return None;
    }
    match expr {
        Expr::MethodCall(method) => {
            if method.method == "parse" && method.turbofish.is_none() && method.args.is_empty() {
                return Some(token_key(expr));
            }
            type_inferred_parse_site(&method.receiver, depth + 1).or_else(|| {
                method
                    .args
                    .iter()
                    .find_map(|arg| type_inferred_parse_site(arg, depth + 1))
            })
        }
        Expr::Paren(paren) => type_inferred_parse_site(&paren.expr, depth + 1),
        Expr::Group(group) => type_inferred_parse_site(&group.expr, depth + 1),
        Expr::Reference(reference) => type_inferred_parse_site(&reference.expr, depth + 1),
        Expr::Unary(unary) => type_inferred_parse_site(&unary.expr, depth + 1),
        Expr::Field(field) => type_inferred_parse_site(&field.base, depth + 1),
        Expr::Index(index) => type_inferred_parse_site(&index.expr, depth + 1)
            .or_else(|| type_inferred_parse_site(&index.index, depth + 1)),
        Expr::Call(call) => type_inferred_parse_site(&call.func, depth + 1).or_else(|| {
            call.args
                .iter()
                .find_map(|arg| type_inferred_parse_site(arg, depth + 1))
        }),
        Expr::Binary(binary) => type_inferred_parse_site(&binary.left, depth + 1)
            .or_else(|| type_inferred_parse_site(&binary.right, depth + 1)),
        Expr::Cast(cast) => type_inferred_parse_site(&cast.expr, depth + 1),
        Expr::Array(array) => array
            .elems
            .iter()
            .find_map(|elem| type_inferred_parse_site(elem, depth + 1)),
        Expr::Tuple(tuple) => tuple
            .elems
            .iter()
            .find_map(|elem| type_inferred_parse_site(elem, depth + 1)),
        _ => None,
    }
}
