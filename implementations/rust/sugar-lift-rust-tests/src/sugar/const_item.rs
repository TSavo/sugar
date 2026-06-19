// SPDX-License-Identifier: Apache-2.0
//
// `ConstItemSugar`: a local `const`/`static` item with a single-expression
// initializer and no assertion-family macro is inert compiler-axiom support. The
// compiler already checked the initializer for compiling code; at statement
// position it is not a scalar assertion surface to be lowered through
// `ConstraintSugar`.

use syn::{Expr, Item};
use tracing::debug;

use crate::sugar::claim::ItemSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::{count_asserts_in_expr, token_key, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const ITEM_SUGAR: ItemSugarClaim =
    ItemSugarClaim::statement_item("const_item", recognize);

fn recognize(item: &Item, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let (kind, name, initializer) = const_static_parts(item)?;
    if count_asserts_in_expr(initializer) != 0 {
        return None;
    }
    if !is_single_expression_initializer(initializer) {
        return None;
    }
    Some(Box::new(ConstItemSugar {
        kind,
        name,
        initializer: token_key(initializer),
    }))
}

fn const_static_parts(item: &Item) -> Option<(&'static str, String, &Expr)> {
    match item {
        Item::Const(item) => Some(("const", item.ident.to_string(), &item.expr)),
        Item::Static(item) => Some(("static", item.ident.to_string(), &item.expr)),
        _ => None,
    }
}

fn is_single_expression_initializer(expr: &Expr) -> bool {
    !matches!(expr, Expr::Block(_) | Expr::Unsafe(_) | Expr::Const(_))
}

struct ConstItemSugar {
    kind: &'static str,
    name: String,
    initializer: String,
}

impl Sugar for ConstItemSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        debug!(
            target: "sugar_lift_rust_tests::sugar::const_item",
            kind = self.kind,
            name = self.name.as_str(),
            initializer = self.initializer.as_str(),
            "const/static item initializer accounted as inert compiler axiom"
        );
        Outcome::Dug(Desugared::Seq(Vec::new()))
    }
}
