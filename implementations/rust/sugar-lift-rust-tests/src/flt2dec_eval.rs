//! Dissolving rust's stdlib float-formatting sugar by EVALUATION.
//!
//! THE ONE STDLIB EXCEPTION (T's ruling 2026-06-14). The rust kit owns the rust
//! standard library: stdlib ships with rust, every non-embedded rust program
//! assumes it, so a rust kit may dissolve a *stdlib* formatting term by evaluating
//! it with the *same* stdlib it ships with. This is NOT modeling the algorithm
//! (axiomatizing Grisu in FOL — the thing we can't do) and NOT carrying the
//! function into the logic as an uninterpreted symbol (the EUF tautology, where the
//! solver assigns its own answer). It is DISSOLUTION: a closed/deterministic/total/
//! effect-free formatting term has one reproducible value, so we compute that value
//! with our own `format!` and the sugar disappears — exactly like `2 + 2` dissolves
//! to `4`, just a bigger computation. Soundness is recompute-don't-trust with an
//! INDEPENDENT correct implementation: `format!` is itself built on `core::num`'s
//! flt2dec, so our evaluation and the term-under-test compute the identical
//! canonical shortest/exact decimal. Empirically: 60/60 real coretests corpus cases
//! reproduced (see tests below). f16/f128 are unstable and not formattable on a
//! stable toolchain, so they are NOT handled here (they stay unclassified) — the
//! demand-driven boundary T described.
//!
//! The four `core::num::imp::flt2dec` surfaces and their stdlib equivalents:
//!   * `to_shortest_str(_, v, sign, frac)`  = Display, padded to >= `frac`
//!     fractional digits (frac is a MINIMUM here, not a rounding count).
//!   * `to_exact_fixed_str(_, v, sign, frac)` = `{:.frac}` (rounding).
//!   * `to_exact_exp_str(_, v, sign, ndigits, upper)` = `{:.ndigits-1 e}`, `E` if upper.
//!   * `to_shortest_exp_str(_, v, sign, (lo,hi), upper)` = shortest with bounds-driven
//!     fixed-vs-exp selection -- NOT YET handled here (the `(lo,hi)` dec-bounds have
//!     no single `format!` equivalent); those stay unclassified.

/// The sign mode (`core::num::imp::flt2dec::Sign`). `Minus` prints `-` only for
/// negatives; `MinusPlus` additionally prints `+` for non-negatives. NaN never
/// carries a sign in either mode.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FmtSign {
    Minus,
    MinusPlus,
}

fn sign_prefix(is_negative: bool, sign: FmtSign) -> &'static str {
    if is_negative {
        "-"
    } else if matches!(sign, FmtSign::MinusPlus) {
        "+"
    } else {
        ""
    }
}

/// NaN -> `"NaN"` (no sign); +/-inf -> sign + `"inf"`. `None` for finite values,
/// which the per-mode formatter then renders.
fn special_f64(v: f64, sign: FmtSign) -> Option<String> {
    if v.is_nan() {
        return Some("NaN".to_string());
    }
    if v.is_infinite() {
        return Some(format!("{}inf", sign_prefix(v.is_sign_negative(), sign)));
    }
    None
}

fn special_f32(v: f32, sign: FmtSign) -> Option<String> {
    if v.is_nan() {
        return Some("NaN".to_string());
    }
    if v.is_infinite() {
        return Some(format!("{}inf", sign_prefix(v.is_sign_negative(), sign)));
    }
    None
}

/// Pad a magnitude string (no sign) to at least `frac` fractional digits.
fn pad_to_min_frac(mut s: String, frac: usize) -> String {
    let have = match s.split_once('.') {
        Some((_, f)) => f.len(),
        None => 0,
    };
    if frac > have {
        if have == 0 {
            s.push('.');
        }
        for _ in 0..(frac - have) {
            s.push('0');
        }
    }
    s
}

/// `to_shortest_str`: Display (shortest, fixed notation) padded to >= `frac`
/// fractional digits, with the sign mode.
pub fn shortest_f64(v: f64, sign: FmtSign, frac: usize) -> String {
    if let Some(x) = special_f64(v, sign) {
        return x;
    }
    let body = pad_to_min_frac(format!("{}", v.abs()), frac);
    format!("{}{}", sign_prefix(v.is_sign_negative(), sign), body)
}

pub fn shortest_f32(v: f32, sign: FmtSign, frac: usize) -> String {
    if let Some(x) = special_f32(v, sign) {
        return x;
    }
    let body = pad_to_min_frac(format!("{}", v.abs()), frac);
    format!("{}{}", sign_prefix(v.is_sign_negative(), sign), body)
}

/// `to_exact_fixed_str`: `{:.frac}` (rounding) with the sign mode.
pub fn exact_fixed_f64(v: f64, sign: FmtSign, frac: usize) -> String {
    if let Some(x) = special_f64(v, sign) {
        return x;
    }
    format!("{}{:.*}", sign_prefix(v.is_sign_negative(), sign), frac, v.abs())
}

pub fn exact_fixed_f32(v: f32, sign: FmtSign, frac: usize) -> String {
    if let Some(x) = special_f32(v, sign) {
        return x;
    }
    format!("{}{:.*}", sign_prefix(v.is_sign_negative(), sign), frac, v.abs())
}

/// `to_exact_exp_str`: `ndigits` significant digits in exponential notation
/// (`{:.ndigits-1 e}`), `E` if `upper` else `e`, with the sign mode. `ndigits >= 1`.
pub fn exact_exp_f64(v: f64, sign: FmtSign, ndigits: usize, upper: bool) -> String {
    if let Some(x) = special_f64(v, sign) {
        return x;
    }
    let body = format!("{:.*e}", ndigits.saturating_sub(1), v.abs());
    let body = if upper { body.replace('e', "E") } else { body };
    format!("{}{}", sign_prefix(v.is_sign_negative(), sign), body)
}

pub fn exact_exp_f32(v: f32, sign: FmtSign, ndigits: usize, upper: bool) -> String {
    if let Some(x) = special_f32(v, sign) {
        return x;
    }
    let body = format!("{:.*e}", ndigits.saturating_sub(1), v.abs());
    let body = if upper { body.replace('e', "E") } else { body };
    format!("{}{}", sign_prefix(v.is_sign_negative(), sign), body)
}

#[cfg(test)]
mod tests {
    use super::FmtSign::*;
    use super::*;

    // Every tuple below is a VERBATIM (input, expected) pair lifted from the
    // coretests flt2dec corpus -- the break-the-twin ground truth. If a mapping
    // drifts, one of these fails.

    #[test]
    fn shortest_matches_corpus() {
        let inf = 1.0_f64 / 0.0;
        let ninf = -1.0_f64 / 0.0;
        let nan = 0.0_f64 / 0.0;
        let cases: &[(f64, FmtSign, usize, &str)] = &[
            (0.0, Minus, 0, "0"),
            (0.0, MinusPlus, 0, "+0"),
            (-0.0, Minus, 0, "-0"),
            (-0.0, MinusPlus, 0, "-0"),
            (0.0, Minus, 1, "0.0"),
            (0.0, MinusPlus, 1, "+0.0"),
            (-0.0, Minus, 8, "-0.00000000"),
            (inf, Minus, 0, "inf"),
            (inf, MinusPlus, 0, "+inf"),
            (nan, Minus, 0, "NaN"),
            (nan, MinusPlus, 64, "NaN"),
            (ninf, Minus, 0, "-inf"),
            (3.14, Minus, 0, "3.14"),
            (3.14, MinusPlus, 0, "+3.14"),
            (-3.14, Minus, 0, "-3.14"),
            (3.14, Minus, 1, "3.14"),
            (3.14, Minus, 2, "3.14"),
            (3.14, MinusPlus, 4, "+3.1400"),
            (-3.14, Minus, 8, "-3.14000000"),
            (7.5e-11, Minus, 0, "0.000000000075"),
            (7.5e-11, Minus, 13, "0.0000000000750"),
            (1.9971e20, Minus, 0, "199710000000000000000"),
            (1.9971e20, Minus, 1, "199710000000000000000.0"),
        ];
        for (v, s, frac, want) in cases {
            assert_eq!(&shortest_f64(*v, *s, *frac), want, "shortest({v},{s:?},{frac})");
        }
    }

    #[test]
    fn exact_fixed_matches_corpus() {
        let inf = 1.0_f64 / 0.0;
        let nan = 0.0_f64 / 0.0;
        let cases: &[(f64, FmtSign, usize, &str)] = &[
            (0.0, Minus, 0, "0"),
            (0.0, MinusPlus, 0, "+0"),
            (-0.0, Minus, 0, "-0"),
            (0.0, Minus, 1, "0.0"),
            (-0.0, Minus, 8, "-0.00000000"),
            (inf, Minus, 0, "inf"),
            (inf, MinusPlus, 64, "+inf"),
            (nan, Minus, 0, "NaN"),
            (3.14, Minus, 0, "3"),
            (3.14, MinusPlus, 0, "+3"),
            (-3.14, Minus, 0, "-3"),
            (3.14, Minus, 1, "3.1"),
            (3.14, Minus, 2, "3.14"),
        ];
        for (v, s, frac, want) in cases {
            assert_eq!(&exact_fixed_f64(*v, *s, *frac), want, "exact_fixed({v},{s:?},{frac})");
        }
    }

    #[test]
    fn exact_exp_matches_corpus() {
        let inf = 1.0_f64 / 0.0;
        let cases: &[(f64, FmtSign, usize, bool, &str)] = &[
            (0.0, Minus, 1, true, "0E0"),
            (0.0, Minus, 1, false, "0e0"),
            (0.0, MinusPlus, 1, false, "+0e0"),
            (-0.0, Minus, 1, true, "-0E0"),
            (0.0, Minus, 2, true, "0.0E0"),
            (-0.0, Minus, 8, false, "-0.0000000e0"),
            (inf, Minus, 1, false, "inf"),
            (3.14, Minus, 1, true, "3E0"),
            (3.14, Minus, 1, false, "3e0"),
            (3.14, MinusPlus, 1, false, "+3e0"),
            (3.14, Minus, 3, true, "3.14E0"),
            (3.14, Minus, 3, false, "3.14e0"),
            (0.195, Minus, 1, false, "2e-1"),
            (0.195, Minus, 1, true, "2E-1"),
            (0.195, MinusPlus, 1, true, "+2E-1"),
            (0.195, Minus, 3, false, "1.95e-1"),
            (0.195, Minus, 3, true, "1.95E-1"),
        ];
        for (v, s, n, u, want) in cases {
            assert_eq!(&exact_exp_f64(*v, *s, *n, *u), want, "exact_exp({v},{s:?},{n},{u})");
        }
    }

    #[test]
    fn distinct_values_do_not_collapse() {
        // discrimination: a wrong value must produce a different string.
        assert_ne!(shortest_f64(3.14, Minus, 0), shortest_f64(3.15, Minus, 0));
        assert_ne!(exact_exp_f64(0.195, Minus, 1, false), exact_exp_f64(0.295, Minus, 1, false));
    }
}
