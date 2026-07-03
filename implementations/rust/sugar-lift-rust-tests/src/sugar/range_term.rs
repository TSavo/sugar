// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Range` (`a..b` / `a..=b`): `range`/`range_incl` over
// start (or `0`) and end (or `range_end_len`). Byte-identical to the `Expr::Range` arm
// of the old fat factory.

use std::rc::Rc;

use sugar_ir_symbolic::{make_var, num, Term};

use crate::sugar::ctor_term::CtorSugar;
use crate::sugar::factory::{SugarBody, SugarBuildCtx};
use crate::sugar::int_literal::{numeric_floor_from_term, ExactInt, NumericFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_leaf::resolved_term;
use crate::Sugar;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "range_term",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
            #[test]
            fn t_range_term_good() {
                assert_eq!(0..3, 0..3);
            }
        "#,
            r#"
            #[test]
            fn t_range_term_bad() {
                assert_eq!(0..3, 0..4);
            }
        "#,
        ),
        recognize,
    );

/// TERM recognizer for `Expr::Range`.
/// No `as_expr()`, `Expr::`, or raw syn in this function.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let name = frag.range_limits_name()?;
    let start = match frag.range_start_frag() {
        Some(f) => SugarBody::term_frag(&f, fcx),
        None => SugarBody::from_node(resolved_term(num(0))),
    };
    let end = match frag.range_end_frag() {
        Some(f) => SugarBody::term_frag(&f, fcx),
        None => SugarBody::from_node(resolved_term(make_var("range_end_len"))),
    };
    Some(Box::new(CtorSugar::new(name, vec![start, end])))
}

pub(crate) fn literal_range_debug_string(term: &Rc<Term>) -> Option<String> {
    let Term::Ctor { name, args } = term.as_ref() else {
        return None;
    };

    match name.as_str() {
        "range" | "range_incl" if args.len() == 2 => {
            let start = literal_range_endpoint_string(&args[0])?;
            let end = literal_range_endpoint_string(&args[1])?;
            Some(if name == "range_incl" {
                format!("{start}..={end}")
            } else {
                format!("{start}..{end}")
            })
        }
        "method:skip" if args.len() == 2 => literal_skipped_range_debug_string(&args[0], &args[1]),
        _ => None,
    }
}

fn nonnegative_len(start: i128, end: i128, inclusive: bool) -> Option<i128> {
    if end < start {
        return Some(0);
    }
    let len = end.checked_sub(start)?;
    if inclusive {
        len.checked_add(1)
    } else {
        Some(len)
    }
}

fn literal_skipped_range_debug_string(base: &Rc<Term>, skip: &Rc<Term>) -> Option<String> {
    let skip = literal_range_endpoint_i128(skip)?;
    if skip < 0 {
        return None;
    }
    let Term::Ctor { name, args } = base.as_ref() else {
        return None;
    };
    if args.len() != 2 {
        return None;
    }
    let start = literal_range_endpoint_i128(&args[0])?;
    let end = literal_range_endpoint_i128(&args[1])?;
    match name.as_str() {
        "range" => {
            let len = nonnegative_len(start, end, false)?;
            if skip >= len {
                Some(format!("{end}..{end}"))
            } else {
                Some(format!("{}..{end}", start.checked_add(skip)?))
            }
        }
        "range_incl" => {
            let len = nonnegative_len(start, end, true)?;
            if skip >= len {
                Some(format!("{end}..={end} (exhausted)"))
            } else {
                Some(format!("{}..={end}", start.checked_add(skip)?))
            }
        }
        _ => None,
    }
}

fn literal_range_endpoint_string(term: &Rc<Term>) -> Option<String> {
    match numeric_floor_from_term(term)? {
        NumericFloor::Untyped(value) => Some(value.to_string()),
        NumericFloor::Typed {
            value: ExactInt::Signed(value),
            ..
        } => Some(value.to_string()),
        NumericFloor::Typed {
            value: ExactInt::Unsigned(value),
            ..
        } => Some(value.to_string()),
    }
}

fn literal_range_endpoint_i128(term: &Rc<Term>) -> Option<i128> {
    match numeric_floor_from_term(term)? {
        NumericFloor::Untyped(value) => Some(value),
        NumericFloor::Typed {
            value: ExactInt::Signed(value),
            ..
        } => Some(value),
        NumericFloor::Typed {
            value: ExactInt::Unsigned(value),
            ..
        } => i128::try_from(value).ok(),
    }
}
