// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::RawAddr` (`&raw const x` / `&raw mut x`): a raw
// pointer capability constructor. Construction itself is inert; consumers own
// any temporal effect when the capability is used or escapes.

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{SugarBody, SugarBuildCtx};
use crate::Sugar;
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("raw_addr_term", recognize);

/// TERM recognizer for `Expr::RawAddr`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::RawAddr(raw) = expr else {
        return None;
    };
    let ctor = match &raw.mutability {
        syn::PointerMutability::Const(_) => "raw_addr_const",
        syn::PointerMutability::Mut(_) => "raw_addr_mut",
    };
    Some(Box::new(CtorSugar::new(
        ctor,
        vec![SugarBody::term(raw.expr.as_ref(), fcx)],
    )))
}

#[cfg(test)]
mod tests {
    use std::rc::Rc;

    use super::*;
    use crate::{
        sugar_ctx, Desugared, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, TemporalPlan,
        TemporalScope,
    };
    use sugar_ir_symbolic::Term;
    use syn::Item;

    fn reduce(src: &str) -> Rc<Term> {
        let expr: Expr = syn::parse_str(src).expect("parse raw address expr");
        let scope = TemporalScope::new("raw-addr-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = recognize(&expr, &fcx).expect("raw_addr_term recognizes");
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        let Outcome::Complete(Desugared::Term(term)) = node.desugar(&ctx) else {
            panic!("raw address sugar should complete as an inert capability term")
        };
        term
    }

    #[test]
    fn raw_const_address_constructs_capability_floor() {
        let term = reduce("&raw const x");
        let Term::Ctor { name, args } = term.as_ref() else {
            panic!("expected raw_addr_const ctor, got {term:?}");
        };
        assert_eq!(name, "raw_addr_const");
        assert_eq!(args.len(), 1);
        assert!(matches!(args[0].as_ref(), Term::Var { name } if name == "x"));
    }

    #[test]
    fn raw_mut_address_constructs_capability_floor() {
        let term = reduce("&raw mut x");
        let Term::Ctor { name, args } = term.as_ref() else {
            panic!("expected raw_addr_mut ctor, got {term:?}");
        };
        assert_eq!(name, "raw_addr_mut");
        assert_eq!(args.len(), 1);
        assert!(matches!(args[0].as_ref(), Term::Var { name } if name == "x"));
    }
}
