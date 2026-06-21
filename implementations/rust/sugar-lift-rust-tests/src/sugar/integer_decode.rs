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
// EXACT-OR-NONE: f16 (unstable; no exact host decimal->f16), an UNSUFFIXED float (width
// unknown), NAN (std does not pin the decoded mantissa), and any non-literal/non-INFINITY
// receiver (e.g. a runtime `ldexp_f32(..)` call) DECLINE (return None) -> the locus stays
// the opaque `method:integer_decode` fallback.

use syn::{Expr, ExprMethodCall, ExprPath, Lit, UnOp};

/// The `tuple_decomp` producer hook: if `call` is `<f32/f64 literal>.integer_decode()`,
/// return the decoded `(mantissa, exponent, sign)` as three literal component exprs
/// (negatives rendered as unary-neg, matching the corpus tuple syntax). Declines otherwise.
pub(crate) fn decomposed_component_exprs(call: &ExprMethodCall) -> Option<Vec<Expr>> {
    if call.method != "integer_decode" || !call.args.is_empty() {
        return None;
    }
    let (mantissa, exponent, sign) = decode_receiver(&call.receiver, false)?;
    Some(vec![
        syn::parse_str(&mantissa.to_string()).ok()?,
        syn::parse_str(&exponent.to_string()).ok()?,
        syn::parse_str(&sign.to_string()).ok()?,
    ])
}

/// Resolve the receiver to a typed f32/f64 value and compute its `integer_decode`.
/// `negate` accumulates outer unary `-`. Returns `None` (decline) for anything whose
/// exact bits we cannot determine.
fn decode_receiver(expr: &Expr, negate: bool) -> Option<(u64, i16, i8)> {
    match expr {
        Expr::Paren(p) => decode_receiver(&p.expr, negate),
        Expr::Group(g) => decode_receiver(&g.expr, negate),
        Expr::Unary(u) if matches!(u.op, UnOp::Neg(_)) => decode_receiver(&u.expr, !negate),
        Expr::Lit(lit) => decode_float_literal(&lit.lit, negate),
        Expr::Path(path) => decode_assoc_const(path, negate),
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
            let v = if negative { f32::NEG_INFINITY } else { f32::INFINITY };
            Some(integer_decode_f32(v))
        }
        "f64" => {
            let v = if negative { f64::NEG_INFINITY } else { f64::INFINITY };
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
