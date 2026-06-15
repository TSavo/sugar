// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Macro`: the FormatSugar dig (`format!`/`concat!` dissolve
// to a `str_const`), the mut-local temporal-instability refusal, then the opaque
// `macro:<tokens>` EUF var. Byte-identical to the `Expr::Macro` arm of the old fat
// factory.

use sugar_ir_symbolic::make_var;

use crate::sugar::factory::FactoryCtx;
use crate::sugar::format::{stable_let_bindings, try_resolve_format};
use crate::sugar::term_leaf::{reasoned_hit, resolved_term};
use crate::{macro_literal_contains_mut_local, str_const, token_key, Sugar};
use syn::Expr;

/// TERM recognizer for `Expr::Macro`.
pub(crate) fn recognize(expr: &Expr, fcx: &FactoryCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Macro(m) = expr else {
        return None;
    };
    let scope = fcx.scope;
    let seg = m.mac.path.segments.last().map(|s| s.ident.to_string());
    if matches!(seg.as_deref(), Some("format") | Some("concat")) {
        let stable = stable_let_bindings(scope);
        match try_resolve_format(expr, &stable) {
            Ok(Some(s)) => return Some(resolved_term(str_const(s))),
            Err(reason) => return Some(reasoned_hit(reason)),
            Ok(None) => {}
        }
    }
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
        return Some(reasoned_hit(format!(
            "macro in term position references a `let mut` local; \
             temporally unstable — refused: `{token_str}`"
        )));
    }
    Some(resolved_term(make_var(format!("macro:{token_str}"))))
}
