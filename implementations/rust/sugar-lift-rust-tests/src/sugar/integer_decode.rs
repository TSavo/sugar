// SPDX-License-Identifier: Apache-2.0
//
// `integer_decode` — a tuple-valued PRODUCER for the shared `tuple_decomp` arm.
// `<float>.integer_decode()` over a grounded f32/f64 literal (or `f32::INFINITY` /
// `NEG_INFINITY`) yields the EXACT std `(mantissa, exponent, sign)` IEEE-754
// decomposition. Per the evaluator doctrine we RUN the real host operation on the
// reconstructed concrete float: `str::parse::<f32>()` reproduces the compiler's dec2flt
// bit-for-bit, then `f32::to_bits()` (the std op) gives the bits we read the IEEE fields
// out of. The decoded triple is returned as three component SOURCE exprs so the shared
// arm can lower a tuple equality COMPONENT-WISE into grounded scalar equalities (which
// have real z3 teeth) -- never as a single uninterpreted `literal:Tuple` constant
// (congruence-only, no teeth).
//
// EXACT-OR-NONE: f16 (unstable; no exact host decimal->f16), an UNSUFFIXED top-level
// float (width unknown), NAN (std does not pin the decoded mantissa), and any
// non-literal/non-INFINITY receiver DECLINE (return None) -> the locus stays the opaque
// `method:integer_decode` fallback. The only closed call we evaluate is the vendored
// coretests `ldexp_f32`/`ldexp_f64` helper shape with literal operands.

use sugar_ir_symbolic::num;
use syn::{
    Expr, ExprCall, ExprPath, FnArg, ForeignItem, Item, ItemFn, Lit, Pat, ReturnType, Stmt, Type,
    UnOp,
};

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::format::{ldexp_f32, ldexp_f64};
use crate::{simple_call_name, strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const TUPLE_PRODUCER_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::tuple_producer(
        "integer_decode_tuple_producer",
        recognize_tuple_producer,
    );

fn recognize_tuple_producer(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "integer_decode" || !call.args.is_empty() {
        return None;
    }
    Some(Box::new(IntegerDecodeTupleProducer {
        receiver: (*call.receiver).clone(),
    }))
}

struct IntegerDecodeTupleProducer {
    receiver: Expr,
}

impl Sugar for IntegerDecodeTupleProducer {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let Some((mantissa, exponent, sign)) = decode_receiver(&self.receiver, false, ctx.scope)
        else {
            return Outcome::from_opt(None);
        };
        Outcome::Complete(Desugared::TupleComponents(vec![
            num(i128::from(mantissa)),
            num(i128::from(exponent)),
            num(i128::from(sign)),
        ]))
    }
}

/// Resolve the receiver to a typed f32/f64 value and compute its `integer_decode`.
/// `negate` accumulates outer unary `-`. Returns `None` (decline) for anything whose
/// exact bits we cannot determine.
fn decode_receiver(
    expr: &Expr,
    negate: bool,
    scope: &crate::TemporalScope,
) -> Option<(u64, i16, i8)> {
    match expr {
        Expr::Paren(p) => decode_receiver(&p.expr, negate, scope),
        Expr::Group(g) => decode_receiver(&g.expr, negate, scope),
        Expr::Unary(u) if matches!(u.op, UnOp::Neg(_)) => decode_receiver(&u.expr, !negate, scope),
        Expr::Lit(lit) => decode_float_literal(&lit.lit, negate),
        Expr::Path(path) => decode_assoc_const(path, negate),
        Expr::Call(call) => decode_ldexp_call(call, negate, scope),
        _ => None,
    }
}

fn decode_float_literal(lit: &Lit, negate: bool) -> Option<(u64, i16, i8)> {
    let (digits, suffix) = match lit {
        Lit::Float(f) => (f.base10_digits().to_string(), f.suffix().to_string()),
        // `0f32` can lex as an integer literal carrying a float suffix.
        Lit::Int(i) => (i.base10_digits().to_string(), i.suffix().to_string()),
        _ => return None,
    };
    match suffix.as_str() {
        "f32" => {
            let v: f32 = digits.parse().ok()?;
            let v = if negate { -v } else { v };
            Some(integer_decode_f32(v))
        }
        "f64" => {
            let v: f64 = digits.parse().ok()?;
            let v = if negate { -v } else { v };
            Some(integer_decode_f64(v))
        }
        // f16 (unstable; no exact host decimal->f16) or unsuffixed (width unknown).
        _ => None,
    }
}

fn decode_ldexp_call(
    call: &ExprCall,
    negate: bool,
    scope: &crate::TemporalScope,
) -> Option<(u64, i16, i8)> {
    let name = simple_call_name(call)?;
    if call.args.len() != 2 || !visible_ldexp_helper_matches(scope, &name) {
        return None;
    }
    let exp = i32::try_from(crate::const_int(call.args.iter().nth(1)?)?).ok()?;
    match name.as_str() {
        "ldexp_f32" => {
            let m = decode_ldexp_arg_f32(call.args.first()?, false)?;
            let v = ldexp_f32(if negate { -m } else { m }, exp);
            Some(integer_decode_f32(v))
        }
        "ldexp_f64" => {
            let m = decode_ldexp_arg_f64(call.args.first()?, false)?;
            let v = ldexp_f64(if negate { -m } else { m }, exp);
            Some(integer_decode_f64(v))
        }
        _ => None,
    }
}

fn decode_ldexp_arg_f32(expr: &Expr, negate: bool) -> Option<f32> {
    match strip_refs_groups(expr) {
        Expr::Unary(u) if matches!(u.op, UnOp::Neg(_)) => decode_ldexp_arg_f32(&u.expr, !negate),
        Expr::Lit(lit) => {
            let (digits, suffix) = float_lit_digits_suffix(&lit.lit)?;
            if !suffix.is_empty() && suffix != "f32" {
                return None;
            }
            let v: f32 = digits.parse().ok()?;
            Some(if negate { -v } else { v })
        }
        _ => None,
    }
}

fn decode_ldexp_arg_f64(expr: &Expr, negate: bool) -> Option<f64> {
    match strip_refs_groups(expr) {
        Expr::Unary(u) if matches!(u.op, UnOp::Neg(_)) => decode_ldexp_arg_f64(&u.expr, !negate),
        Expr::Lit(lit) => {
            let (digits, suffix) = float_lit_digits_suffix(&lit.lit)?;
            if !suffix.is_empty() && suffix != "f64" {
                return None;
            }
            let v: f64 = digits.parse().ok()?;
            Some(if negate { -v } else { v })
        }
        _ => None,
    }
}

fn float_lit_digits_suffix(lit: &Lit) -> Option<(String, String)> {
    match lit {
        Lit::Float(f) => Some((f.base10_digits().to_string(), f.suffix().to_string())),
        // `0f32` can lex as an integer literal carrying a float suffix.
        Lit::Int(i) if matches!(i.suffix(), "f32" | "f64") => {
            Some((i.base10_digits().to_string(), i.suffix().to_string()))
        }
        _ => None,
    }
}

fn visible_ldexp_helper_matches(scope: &crate::TemporalScope, name: &str) -> bool {
    let Some(helper) = scope.fn_registry().lookup(name) else {
        return false;
    };
    match name {
        "ldexp_f32" => ldexp_f32_helper_matches(&helper),
        "ldexp_f64" => ldexp_f64_helper_matches(&helper),
        _ => false,
    }
}

fn ldexp_f32_helper_matches(helper: &ItemFn) -> bool {
    let Some((a, b)) = two_simple_param_names(helper) else {
        return false;
    };
    if !returns_type(helper, "f32") {
        return false;
    }
    let [Stmt::Expr(expr, None)] = helper.block.stmts.as_slice() else {
        return false;
    };
    let Expr::Cast(ret_cast) = strip_refs_groups(expr) else {
        return false;
    };
    if !type_is_ident(&ret_cast.ty, "f32") {
        return false;
    }
    let Expr::Call(call) = strip_refs_groups(&ret_cast.expr) else {
        return false;
    };
    if simple_call_name(call).as_deref() != Some("ldexp_f64") || call.args.len() != 2 {
        return false;
    }
    let Some(first_arg) = call.args.first() else {
        return false;
    };
    let Some(second_arg) = call.args.iter().nth(1) else {
        return false;
    };
    let Expr::Cast(arg_cast) = strip_refs_groups(first_arg) else {
        return false;
    };
    type_is_ident(&arg_cast.ty, "f64")
        && expr_is_path_ident(&arg_cast.expr, &a)
        && expr_is_path_ident(second_arg, &b)
}

fn ldexp_f64_helper_matches(helper: &ItemFn) -> bool {
    let Some((a, b)) = two_simple_param_names(helper) else {
        return false;
    };
    if !returns_type(helper, "f64") {
        return false;
    }
    let mut has_foreign_ldexp = false;
    let mut has_return_call = false;
    for stmt in &helper.block.stmts {
        match stmt {
            Stmt::Item(Item::ForeignMod(foreign)) => {
                has_foreign_ldexp |= foreign
                    .items
                    .iter()
                    .any(|item| matches!(item, ForeignItem::Fn(f) if f.sig.ident == "ldexp"));
            }
            Stmt::Expr(expr, None) => {
                has_return_call |= unsafe_block_returns_ldexp_call(expr, &a, &b);
            }
            _ => {}
        }
    }
    has_foreign_ldexp && has_return_call
}

fn unsafe_block_returns_ldexp_call(expr: &Expr, a: &str, b: &str) -> bool {
    let Expr::Unsafe(unsafe_expr) = strip_refs_groups(expr) else {
        return false;
    };
    let [Stmt::Expr(ret, None)] = unsafe_expr.block.stmts.as_slice() else {
        return false;
    };
    let Expr::Call(call) = strip_refs_groups(ret) else {
        return false;
    };
    simple_call_name(call).as_deref() == Some("ldexp")
        && call.args.len() == 2
        && expr_is_path_ident(call.args.first().unwrap(), a)
        && expr_is_path_ident(call.args.iter().nth(1).unwrap(), b)
}

fn two_simple_param_names(helper: &ItemFn) -> Option<(String, String)> {
    let mut inputs = helper.sig.inputs.iter();
    let a = simple_fn_arg_name(inputs.next()?)?;
    let b = simple_fn_arg_name(inputs.next()?)?;
    if inputs.next().is_some() {
        return None;
    }
    Some((a, b))
}

fn simple_fn_arg_name(arg: &FnArg) -> Option<String> {
    let FnArg::Typed(typed) = arg else {
        return None;
    };
    let Pat::Ident(pat) = typed.pat.as_ref() else {
        return None;
    };
    Some(pat.ident.to_string())
}

fn returns_type(helper: &ItemFn, ty: &str) -> bool {
    matches!(&helper.sig.output, ReturnType::Type(_, ret) if type_is_ident(ret, ty))
}

fn type_is_ident(ty: &Type, ident: &str) -> bool {
    matches!(ty, Type::Path(path) if path.qself.is_none() && path.path.is_ident(ident))
}

fn expr_is_path_ident(expr: &Expr, ident: &str) -> bool {
    matches!(strip_refs_groups(expr), Expr::Path(path) if path.qself.is_none() && path.path.is_ident(ident))
}

fn decode_assoc_const(path: &ExprPath, negate: bool) -> Option<(u64, i16, i8)> {
    if path.qself.is_some() {
        return None;
    }
    let segs = &path.path.segments;
    if segs.len() != 2 {
        return None;
    }
    let ty = segs[0].ident.to_string();
    let neg_const = match segs[1].ident.to_string().as_str() {
        "INFINITY" => false,
        "NEG_INFINITY" => true,
        // NAN's decoded mantissa is not pinned by std; MIN/MAX/EPSILON are not
        // integer_decode corpus sites. Decline rather than risk a wrong tuple.
        _ => return None,
    };
    let negative = negate ^ neg_const;
    match ty.as_str() {
        "f32" => {
            let v = if negative {
                f32::NEG_INFINITY
            } else {
                f32::INFINITY
            };
            Some(integer_decode_f32(v))
        }
        "f64" => {
            let v = if negative {
                f64::NEG_INFINITY
            } else {
                f64::INFINITY
            };
            Some(integer_decode_f64(v))
        }
        _ => None,
    }
}

/// EXACT std `f32::integer_decode` over the real `to_bits()`.
fn integer_decode_f32(f: f32) -> (u64, i16, i8) {
    let bits: u32 = f.to_bits();
    let sign: i8 = if bits >> 31 == 0 { 1 } else { -1 };
    let mut exponent: i16 = ((bits >> 23) & 0xff) as i16;
    let mantissa = if exponent == 0 {
        (bits & 0x7f_ffff) << 1
    } else {
        (bits & 0x7f_ffff) | 0x80_0000
    };
    exponent -= 127 + 23;
    (u64::from(mantissa), exponent, sign)
}

/// EXACT std `f64::integer_decode` over the real `to_bits()`.
fn integer_decode_f64(f: f64) -> (u64, i16, i8) {
    let bits: u64 = f.to_bits();
    let sign: i8 = if bits >> 63 == 0 { 1 } else { -1 };
    let mut exponent: i16 = ((bits >> 52) & 0x7ff) as i16;
    let mantissa = if exponent == 0 {
        (bits & 0xf_ffff_ffff_ffff) << 1
    } else {
        (bits & 0xf_ffff_ffff_ffff) | 0x10_0000_0000_0000
    };
    exponent -= 1023 + 52;
    (mantissa, exponent, sign)
}
