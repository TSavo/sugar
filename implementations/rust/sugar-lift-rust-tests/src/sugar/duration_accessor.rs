// SPDX-License-Identifier: Apache-2.0
//
// `DurationAccessorSugar`: an integer field accessor (`as_secs` / `subsec_nanos`
// / `subsec_micros` / `subsec_millis` / `as_millis` / `as_micros` / `as_nanos`)
// over a `Duration` built from INTEGER literals is value sugar. A literal
// `Duration` is a closed value -- (secs, nanos) -- determined entirely by its
// constructor, so we COMPUTE the accessor in the host and lower a ground integer
// const that z3 reasons about directly, replacing the opaque `method:as_secs`
// EUF var (no teeth).
//
// THE MODEL. A `Duration` is exactly `total_nanos: u128` (secs*1e9 + subsec). We
// fold the constructor to `total_nanos`, then each accessor is integer
// division/modulo on it:
//   as_secs       = total / 1e9            subsec_nanos  = total % 1e9
//   as_millis     = total / 1e6            subsec_micros = (total % 1e9) / 1e3
//   as_micros     = total / 1e3            subsec_millis = (total % 1e9) / 1e6
//   as_nanos      = total
//
// Constructors folded (all over integer literal args):
//   Duration::new(secs, nanos)   = secs*1e9 + nanos   (nanos may carry; the
//                                   total model handles it exactly)
//   from_secs / from_millis / from_micros / from_nanos
//   from_mins / from_hours / from_days / from_weeks
//
// EXACT-OR-NONE. We claim ONLY for an accessor whose receiver is one of these
// integer constructors over integer-literal args. The FLOAT surface
// (`from_secs_f32/f64`, `as_secs_f32/f64`, `div_duration_f32/f64`), a runtime /
// let-bound / arithmetic-built `Duration`, or a non-literal arg -> `None`, so
// the existing opaque handling stands (no regression, never a guess). All int
// widths collapse to SMT `Int`, so the lowered `num` meets a typed RHS
// (`as_secs() == 5u64`) and an untyped one alike.
//
// TEETH. `Duration::from_millis(1500).as_secs()` lowers to `1`; a claim of `2`
// is z3-UNSAT (refuted). `.subsec_millis()` lowers to `500`.
//
// MIGRATION (Phase-3 ratchet). Fully migrated leaf: `recognize` uses ONLY
// `SourceFragment` typed accessors -- no `as_expr()`/raw `Expr::` access.
// `DurationAccessorSugar` holds ONLY `value: i128` -- no raw syn fields.

use sugar_ir_symbolic::num;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, Outcome, Sugar, SugarCtx};

const NANOS_PER_SEC: u128 = 1_000_000_000;
const NANOS_PER_MICRO: u128 = 1_000;
const NANOS_PER_MILLI: u128 = 1_000_000;
const SECS_PER_MIN: u128 = 60;
const SECS_PER_HOUR: u128 = 3_600;
const SECS_PER_DAY: u128 = 86_400;
const SECS_PER_WEEK: u128 = 604_800;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("duration_accessor", SugarRole::Term, recognize);

fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // Must be a zero-argument method call.
    if !frag.call_is_method_call() {
        return None;
    }
    if frag.call_arg_count() != 0 {
        return None;
    }
    let method = frag.call_target_name()?;
    // Only the integer accessors; the float surface stays opaque.
    if !matches!(
        method.as_str(),
        "as_secs"
            | "subsec_nanos"
            | "subsec_micros"
            | "subsec_millis"
            | "as_millis"
            | "as_micros"
            | "as_nanos"
    ) {
        return None;
    }
    // Strip refs/groups/parens from the receiver, then try to fold it to
    // total nanoseconds as a Duration constructor over literal int args.
    let receiver = frag.call_receiver()?.strip_refs_groups();
    let total = duration_total_nanos(&receiver)?;
    let value = apply_accessor(&method, total)?;
    // All int widths are SMT `Int`; the result must still fit our i128 const lane.
    let n = i128::try_from(value).ok()?;
    debug!(
        target: "sugar_lift_rust_tests::sugar::duration_accessor",
        method = method.as_str(),
        value = n as i64,
        "resolved Duration integer accessor stdlib axiom to a ground int"
    );
    Some(Box::new(DurationAccessorSugar { value: n }))
}

/// Fold a `Duration::<ctor>(int-literals)` receiver fragment to its total
/// nanoseconds. `None` for a non-`Duration` receiver, a float/runtime
/// constructor, or a non-integer-literal argument. Uses ONLY `SourceFragment`
/// typed accessors -- no raw syn escape.
fn duration_total_nanos(frag: &SourceFragment) -> Option<u128> {
    // Must be a plain function call (e.g. Duration::from_millis(1500)).
    if frag.observed() != "Call" {
        return None;
    }
    // The callee must be an Expr::Path whose last two segments are
    // <Type>::<ctor>, e.g. "Duration::from_millis" or
    // "std::time::Duration::from_millis".
    let func = frag.call_func()?;
    let full_path = func.path_full_name()?;
    let segs: Vec<&str> = full_path.split("::").collect();
    if segs.len() < 2 {
        return None;
    }
    let ty_name = segs[segs.len() - 2];
    let ctor_name = segs[segs.len() - 1];
    if ty_name != "Duration" {
        return None;
    }
    // Fold all constructor arguments to u128 values (decimal int literals only).
    let arg_frags = frag.call_args();
    let args: Vec<u128> = arg_frags
        .iter()
        .map(arg_u128)
        .collect::<Option<Vec<u128>>>()?;
    match (ctor_name, args.as_slice()) {
        ("new", [secs, nanos]) => secs.checked_mul(NANOS_PER_SEC)?.checked_add(*nanos),
        ("from_secs", [s]) => s.checked_mul(NANOS_PER_SEC),
        ("from_millis", [ms]) => ms.checked_mul(NANOS_PER_MILLI),
        ("from_micros", [us]) => us.checked_mul(NANOS_PER_MICRO),
        ("from_nanos", [ns]) => Some(*ns),
        ("from_mins", [m]) => m.checked_mul(SECS_PER_MIN)?.checked_mul(NANOS_PER_SEC),
        ("from_hours", [h]) => h.checked_mul(SECS_PER_HOUR)?.checked_mul(NANOS_PER_SEC),
        ("from_days", [d]) => d.checked_mul(SECS_PER_DAY)?.checked_mul(NANOS_PER_SEC),
        ("from_weeks", [w]) => w.checked_mul(SECS_PER_WEEK)?.checked_mul(NANOS_PER_SEC),
        _ => None,
    }
}

/// Apply an integer accessor to a total-nanoseconds value.
fn apply_accessor(method: &str, total: u128) -> Option<u128> {
    let subsec = total % NANOS_PER_SEC;
    Some(match method {
        "as_secs" => total / NANOS_PER_SEC,
        "subsec_nanos" => subsec,
        "subsec_micros" => subsec / NANOS_PER_MICRO,
        "subsec_millis" => subsec / NANOS_PER_MILLI,
        "as_millis" => total / NANOS_PER_MILLI,
        "as_micros" => total / NANOS_PER_MICRO,
        "as_nanos" => total,
        _ => return None,
    })
}

/// A non-negative integer literal argument (`5`, `5u64`, `500_000_000`),
/// through `Paren`/`Group`/`Reference` wrappers. `None` for a float, a
/// non-literal, or a non-decimal literal -- Duration's integer constructors
/// take only decimal-literal args in practice, matching `base10_parse`.
fn arg_u128(frag: &SourceFragment) -> Option<u128> {
    frag.strip_refs_groups().literal_int_u128()
}

struct DurationAccessorSugar {
    value: i128,
}

impl Sugar for DurationAccessorSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Complete(Desugared::Term(num(self.value)))
    }
}

#[cfg(test)]
mod tests {
    // from_src TDD harness: source string -> SourceFragment -> assert observed
    // -> assert typed-accessor values -> build DurationAccessorSugar from
    // computed data -> assert struct field.
    // No parse_quote!, no StubTerm, no run(). The struct holds ONLY
    // `value: i128` -- zero raw-syn fields -- so these tests prove the
    // migration is clean.
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    /// Navigate from the parsed file down to the tail expression in the first
    /// function's body. Returns the expression-level fragment (e.g., the outer
    /// method call), NOT the wrapping statement fragment.
    fn tail_expr<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let fn_frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = fn_frag.function_body().unwrap();
        let stmts = body.statements();
        let tail = stmts[0]; // Copy (SourceFragment is Copy)
        let terms = tail.terms();
        terms.into_iter().next().expect("expression in tail")
    }

    /// from_src: `Duration::from_millis(1500).as_secs()` -> value 1.
    ///
    /// Proves:
    ///   - observed is "MethodCall"
    ///   - call_is_method_call() is true
    ///   - call_target_name() is "as_secs"
    ///   - call_arg_count() is 0 (no arguments on the accessor call)
    ///   - receiver.strip_refs_groups().observed() is "Call"
    ///   - duration_total_nanos folds 1500 ms to 1_500_000_000 ns
    ///   - apply_accessor("as_secs", total) -> 1
    ///   - DurationAccessorSugar holds value 1i128 -- no raw syn field
    #[test]
    fn from_src_from_millis_1500_as_secs_folds_to_1() {
        let src = "fn f() -> u64 { Duration::from_millis(1500).as_secs() }";
        let file = parse_file(src);
        let frag = tail_expr(&file, "f.rs");

        // Shape check through typed accessors only.
        assert_eq!(frag.observed(), "MethodCall");
        assert!(frag.call_is_method_call());
        assert_eq!(frag.call_target_name().as_deref(), Some("as_secs"));
        assert_eq!(frag.call_arg_count(), 0);

        // Receiver is the Duration::from_millis(1500) Call expression.
        let recv = frag
            .call_receiver()
            .expect("has receiver")
            .strip_refs_groups();
        assert_eq!(recv.observed(), "Call");

        // Fold receiver to total nanoseconds via duration_total_nanos.
        let total = duration_total_nanos(&recv).expect("folds Duration::from_millis(1500)");
        assert_eq!(total, 1_500_000_000_u128, "1500 ms = 1_500_000_000 ns");

        // Apply accessor: as_secs = total / 1e9 = 1.
        let n = apply_accessor("as_secs", total).unwrap();
        assert_eq!(n, 1_u128);

        // Build: struct holds only the computed i128 -- zero raw syn.
        let sugar = DurationAccessorSugar {
            value: i128::try_from(n).unwrap(),
        };
        assert_eq!(sugar.value, 1_i128);
    }

    /// Discrimination: a plain integer literal must NOT trigger this recognizer.
    ///
    /// Proves the `call_is_method_call()` guard correctly rejects non-method
    /// fragments so `duration_total_nanos` is never reached for literals.
    #[test]
    fn discrimination_int_literal_not_a_duration_accessor() {
        let src = "fn f() -> u64 { 42 }";
        let file = parse_file(src);
        let frag = tail_expr(&file, "f.rs");

        assert_eq!(frag.observed(), "PrimitiveLiteral");
        assert!(!frag.call_is_method_call());
        // call_target_name() returns None for a non-call fragment.
        assert!(frag.call_target_name().is_none());
    }

    /// Structural: `DurationAccessorSugar` holds only `value: i128`, no syn.
    ///
    /// Tests `Duration::new(1, 500_000_000)` (1 s + 0.5 s = 1.5 s total)
    /// and verifies `subsec_millis()` = 500 ms and `as_nanos()` = 1_500_000_000.
    #[test]
    fn structural_duration_new_subsec_millis_and_as_nanos() {
        let src = "fn f() -> u32 { Duration::new(1, 500_000_000).subsec_millis() }";
        let file = parse_file(src);
        let frag = tail_expr(&file, "f.rs");

        assert_eq!(frag.call_target_name().as_deref(), Some("subsec_millis"));

        let recv = frag.call_receiver().unwrap().strip_refs_groups();
        let total = duration_total_nanos(&recv).expect("folds Duration::new(1, 500_000_000)");
        // 1 s * 1e9 + 500_000_000 ns = 1_500_000_000 ns
        assert_eq!(total, 1_500_000_000_u128);

        // subsec = total % 1e9 = 500_000_000; subsec_millis = subsec / 1e6 = 500
        let n = apply_accessor("subsec_millis", total).unwrap();
        assert_eq!(n, 500_u128);

        // struct holds only the i128 result
        let sugar = DurationAccessorSugar {
            value: i128::try_from(n).unwrap(),
        };
        assert_eq!(sugar.value, 500_i128);

        // as_nanos = total = 1_500_000_000
        let nanos = apply_accessor("as_nanos", total).unwrap();
        assert_eq!(nanos, 1_500_000_000_u128);
    }
}
