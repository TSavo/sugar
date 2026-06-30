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

use sugar_ir_symbolic::num;
use syn::{Expr, ExprLit, Lit};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::{strip_refs_groups, Desugared, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

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
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if !call.args.is_empty() {
        return None;
    }
    let method = call.method.to_string();
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
    let total = duration_total_nanos(&call.receiver)?;
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

/// Fold a `Duration::<ctor>(int-literals)` receiver to its total nanoseconds.
/// `None` for a non-`Duration` receiver, a float/runtime constructor, or a
/// non-integer-literal argument.
fn duration_total_nanos(expr: &Expr) -> Option<u128> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    let Expr::Path(path) = &*call.func else {
        return None;
    };
    if path.qself.is_some() || path.path.segments.len() < 2 {
        return None;
    }
    let mut segs = path.path.segments.iter().rev();
    let method = segs.next()?.ident.to_string();
    let ty = segs.next()?.ident.to_string();
    if ty != "Duration" {
        return None;
    }
    let args: Vec<u128> = call
        .args
        .iter()
        .map(arg_u128)
        .collect::<Option<Vec<u128>>>()?;
    match (method.as_str(), args.as_slice()) {
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

/// A non-negative integer literal argument (`5`, `5u64`, `500_000_000`), through
/// paren/group/ref wrappers. `None` for a float, a negative, or any non-literal
/// -- Duration's integer constructors take only unsigned literals here.
fn arg_u128(expr: &Expr) -> Option<u128> {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Int(i), ..
        }) => i.base10_parse::<u128>().ok(),
        _ => None,
    }
}

struct DurationAccessorSugar {
    value: i128,
}

impl Sugar for DurationAccessorSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Complete(Desugared::Term(num(self.value)))
    }
}
