// SPDX-License-Identifier: Apache-2.0
//
// `ComputeFloatSugar`: stdlib dec2flt `compute_float::<f32/f64>(q, w)` is an
// internal Rust axiom. When the call is pinned to literal arguments, ask rustc for
// the exact `BiasedFp { p_biased, m }` pair and emit the same literal tuple the
// source wrapper returns. Non-literal arguments do not get guessed.

use std::collections::BTreeMap;
use std::hash::{Hash, Hasher};
use std::io::Write;
use std::path::Path;
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};

use sugar_ir_symbolic::{make_var, num, Term};
use syn::{
    Expr, ExprCall, ExprField, ExprPath, GenericArgument, ItemFn, Member, Pat, PathArguments, Stmt,
    Type,
};
use tracing::{debug, warn};

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::{
    canonical_term_sig, const_fold_int_term, const_fold_u128_term, strip_refs_groups, Desugared,
    Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "compute_float",
    SugarRole::Term,
    SugarPriority::Primary,
    recognize,
);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Call(call) = expr else {
        return None;
    };
    if call.args.len() != 2 {
        return None;
    }
    let width = direct_compute_float_width(call, fcx)
        .or_else(|| wrapper_compute_float_width(call, fcx))?;
    Some(Box::new(ComputeFloatSugar {
        width,
        q: build_term(call.args.first()?, fcx),
        w: build_term(call.args.iter().nth(1)?, fcx),
    }))
}

struct ComputeFloatSugar {
    width: ComputeFloatWidth,
    q: Box<dyn Sugar>,
    w: Box<dyn Sugar>,
}

impl Sugar for ComputeFloatSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let q = match self.q.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        let w = match self.w.desugar(ctx) {
            Outcome::Dug(d) => match d.into_term() {
                Some(term) => term,
                None => return Outcome::from_opt(None),
            },
            Outcome::Hit(e) => return Outcome::Hit(e),
        };
        let Some(q) = const_fold_int_term(&q).and_then(|value| i64::try_from(value).ok()) else {
            debug!(
                target: "sugar_lift_rust_tests::sugar::compute_float",
                width = self.width.type_name(),
                "compute_float q argument did not bottom out to an i64 literal"
            );
            return Outcome::from_opt(None);
        };
        let Some(w) = const_fold_u128_term(&w)
            .or_else(|| const_fold_int_term(&w).and_then(|value| u128::try_from(value).ok()))
            .and_then(|value| u64::try_from(value).ok())
        else {
            debug!(
                target: "sugar_lift_rust_tests::sugar::compute_float",
                width = self.width.type_name(),
                "compute_float w argument did not bottom out to a u64 literal"
            );
            return Outcome::from_opt(None);
        };
        let Some(fp) = rustc_compute_float(self.width, q, w) else {
            return Outcome::from_opt(None);
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::compute_float",
            width = self.width.type_name(),
            q,
            w,
            p_biased = fp.p_biased,
            mantissa = fp.m,
            "resolved compute_float stdlib axiom to literal tuple"
        );
        Outcome::Dug(Desugared::Term(biased_fp_tuple_term(fp)))
    }
}

fn biased_fp_tuple_term(fp: BiasedFp) -> std::rc::Rc<Term> {
    let p_biased = num(i128::from(fp.p_biased));
    let mantissa = num(i128::from(fp.m));
    make_var(format!(
        "literal:Tuple({},{})",
        canonical_term_sig(&p_biased),
        canonical_term_sig(&mantissa)
    ))
}

fn direct_compute_float_width(call: &ExprCall, fcx: &SugarBuildCtx) -> Option<ComputeFloatWidth> {
    let Expr::Path(ExprPath {
        qself: None, path, ..
    }) = strip_refs_groups(call.func.as_ref())
    else {
        return None;
    };
    let last = path.segments.last()?;
    if last.ident != "compute_float" {
        return None;
    }
    if path.segments.len() == 1 && fcx.scope().has_visible_fn("compute_float") {
        return None;
    }
    compute_float_type_arg_width(&last.arguments)
}

fn wrapper_compute_float_width(call: &ExprCall, fcx: &SugarBuildCtx) -> Option<ComputeFloatWidth> {
    let Expr::Path(ExprPath {
        qself: None, path, ..
    }) = strip_refs_groups(call.func.as_ref())
    else {
        return None;
    };
    if path.segments.len() != 1 {
        return None;
    }
    let helper = fcx
        .scope()
        .fn_registry()
        .lookup(&path.segments.first()?.ident.to_string())?;
    wrapper_body_compute_float_width(&helper)
}

fn wrapper_body_compute_float_width(helper: &ItemFn) -> Option<ComputeFloatWidth> {
    let mut inputs = helper.sig.inputs.iter();
    let q_param = simple_fn_param(inputs.next()?)?;
    let w_param = simple_fn_param(inputs.next()?)?;
    if inputs.next().is_some() {
        return None;
    }
    let [Stmt::Local(local), Stmt::Expr(ret, None)] = helper.block.stmts.as_slice() else {
        return None;
    };
    let fp_name = simple_pat_ident(&local.pat)?;
    let init = local.init.as_ref()?;
    let width = wrapper_init_width(&init.expr, &q_param, &w_param)?;
    if returns_biased_fp_tuple(ret, &fp_name) {
        Some(width)
    } else {
        None
    }
}

fn wrapper_init_width(expr: &Expr, q_param: &str, w_param: &str) -> Option<ComputeFloatWidth> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.args.len() != 2 {
        return None;
    }
    if simple_path_expr_name(call.args.first()?)? != q_param {
        return None;
    }
    if simple_path_expr_name(call.args.iter().nth(1)?)? != w_param {
        return None;
    }
    let Expr::Path(ExprPath {
        qself: None, path, ..
    }) = strip_refs_groups(call.func.as_ref())
    else {
        return None;
    };
    let last = path.segments.last()?;
    if last.ident != "compute_float" {
        return None;
    }
    compute_float_type_arg_width(&last.arguments)
}

fn compute_float_type_arg_width(arguments: &PathArguments) -> Option<ComputeFloatWidth> {
    let PathArguments::AngleBracketed(args) = arguments else {
        return None;
    };
    if args.args.len() != 1 {
        return None;
    }
    let Some(GenericArgument::Type(ty)) = args.args.first() else {
        return None;
    };
    ComputeFloatWidth::from_type(ty)
}

fn returns_biased_fp_tuple(expr: &Expr, fp_name: &str) -> bool {
    let Expr::Tuple(tuple) = strip_refs_groups(expr) else {
        return false;
    };
    if tuple.elems.len() != 2 {
        return false;
    }
    let Some(first) = tuple.elems.first() else {
        return false;
    };
    let Some(second) = tuple.elems.iter().nth(1) else {
        return false;
    };
    field_of_path(first, fp_name, "p_biased") && field_of_path(second, fp_name, "m")
}

fn field_of_path(expr: &Expr, base: &str, field: &str) -> bool {
    let Expr::Field(ExprField { base: expr_base, member, .. }) = strip_refs_groups(expr) else {
        return false;
    };
    matches!(member, Member::Named(ident) if ident == field)
        && simple_path_expr_name(expr_base).is_some_and(|name| name == base)
}

fn simple_fn_param(input: &syn::FnArg) -> Option<String> {
    let syn::FnArg::Typed(pat_type) = input else {
        return None;
    };
    simple_pat_ident(&pat_type.pat)
}

fn simple_pat_ident(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(ident) if ident.by_ref.is_none() && ident.subpat.is_none() => {
            Some(ident.ident.to_string())
        }
        _ => None,
    }
}

fn simple_path_expr_name(expr: &Expr) -> Option<String> {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    path.path.get_ident().map(|ident| ident.to_string())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, PartialOrd, Ord)]
enum ComputeFloatWidth {
    F32,
    F64,
}

impl ComputeFloatWidth {
    fn from_type(ty: &Type) -> Option<Self> {
        let Type::Path(path) = ty else {
            return None;
        };
        if path.qself.is_some() || path.path.segments.len() != 1 {
            return None;
        }
        let segment = path.path.segments.first()?;
        if !matches!(segment.arguments, PathArguments::None) {
            return None;
        }
        match segment.ident.to_string().as_str() {
            "f32" => Some(Self::F32),
            "f64" => Some(Self::F64),
            _ => None,
        }
    }

    fn type_name(self) -> &'static str {
        match self {
            Self::F32 => "f32",
            Self::F64 => "f64",
        }
    }
}

#[derive(Clone, Copy, Debug)]
struct BiasedFp {
    p_biased: i32,
    m: u64,
}

fn rustc_compute_float(width: ComputeFloatWidth, q: i64, w: u64) -> Option<BiasedFp> {
    let cache = COMPUTE_FLOAT_CACHE.get_or_init(|| Mutex::new(BTreeMap::new()));
    let key = (width, q, w);
    if let Some(cached) = cache.lock().expect("compute_float cache poisoned").get(&key) {
        return *cached;
    }
    let result = compile_and_run_compute_float_harness(width, q, w);
    cache
        .lock()
        .expect("compute_float cache poisoned")
        .insert(key, result);
    result
}

static COMPUTE_FLOAT_CACHE: OnceLock<Mutex<BTreeMap<(ComputeFloatWidth, i64, u64), Option<BiasedFp>>>> =
    OnceLock::new();
static COMPUTE_FLOAT_HARNESS_COUNTER: AtomicU64 = AtomicU64::new(0);

fn compile_and_run_compute_float_harness(
    width: ComputeFloatWidth,
    q: i64,
    w: u64,
) -> Option<BiasedFp> {
    let ty = width.type_name();
    let source = format!(
        "#![feature(num_internals, dec2flt)]\n\
         #![allow(internal_features)]\n\
         extern crate core;\n\
         use core::num::imp::dec2flt::lemire::compute_float;\n\
         fn main() {{\n\
             let fp = compute_float::<{ty}>({q}i64, {w}u64);\n\
             println!(\"{{}} {{}}\", fp.p_biased, fp.m);\n\
         }}\n"
    );
    let tag = harness_tag(&source);
    let dir = std::env::temp_dir().join("sugar_compute_float_harness");
    if let Err(e) = std::fs::create_dir_all(&dir) {
        warn!(
            target: "sugar_lift_rust_tests::sugar::compute_float",
            width = ty,
            q,
            w,
            error = %e,
            "could not create rustc compute_float harness directory"
        );
        return None;
    }
    let src_path = dir.join(format!("compute_float_{tag}.rs"));
    let bin_path = dir.join(format!("compute_float_{tag}_bin"));
    let result = run_compute_float_harness(&src_path, &bin_path, &source, width, q, w);
    let _ = std::fs::remove_file(&src_path);
    let _ = std::fs::remove_file(&bin_path);
    result
}

fn harness_tag(source: &str) -> String {
    let mut h = std::collections::hash_map::DefaultHasher::new();
    source.hash(&mut h);
    let digest = h.finish();
    let count = COMPUTE_FLOAT_HARNESS_COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("{digest:016x}_{count:016x}")
}

fn run_compute_float_harness(
    src_path: &Path,
    bin_path: &Path,
    source: &str,
    width: ComputeFloatWidth,
    q: i64,
    w: u64,
) -> Option<BiasedFp> {
    if let Err(e) = std::fs::File::create(src_path).and_then(|mut f| f.write_all(source.as_bytes()))
    {
        warn!(
            target: "sugar_lift_rust_tests::sugar::compute_float",
            width = width.type_name(),
            q,
            w,
            error = %e,
            "could not write rustc compute_float harness"
        );
        return None;
    }
    let compile = Command::new("rustc")
        .env("RUSTC_BOOTSTRAP", "1")
        .arg("--edition")
        .arg("2021")
        .arg("-A")
        .arg("warnings")
        .arg(src_path)
        .arg("-o")
        .arg(bin_path)
        .output();
    match compile {
        Ok(out) if out.status.success() => {}
        Ok(out) => {
            let mut stderr = String::from_utf8_lossy(&out.stderr).to_string();
            stderr.truncate(800);
            debug!(
                target: "sugar_lift_rust_tests::sugar::compute_float",
                width = width.type_name(),
                q,
                w,
                stderr = stderr.as_str(),
                "rustc compute_float harness did not compile"
            );
            return None;
        }
        Err(e) => {
            warn!(
                target: "sugar_lift_rust_tests::sugar::compute_float",
                width = width.type_name(),
                q,
                w,
                error = %e,
                "could not invoke rustc compute_float harness"
            );
            return None;
        }
    }
    let run = Command::new(bin_path).output();
    let out = match run {
        Ok(out) if out.status.success() => out,
        Ok(out) => {
            let mut stderr = String::from_utf8_lossy(&out.stderr).to_string();
            stderr.truncate(800);
            debug!(
                target: "sugar_lift_rust_tests::sugar::compute_float",
                width = width.type_name(),
                q,
                w,
                stderr = stderr.as_str(),
                "rustc compute_float harness binary failed"
            );
            return None;
        }
        Err(e) => {
            warn!(
                target: "sugar_lift_rust_tests::sugar::compute_float",
                width = width.type_name(),
                q,
                w,
                error = %e,
                "could not run rustc compute_float harness binary"
            );
            return None;
        }
    };
    parse_biased_fp_stdout(&out.stdout)
}

fn parse_biased_fp_stdout(stdout: &[u8]) -> Option<BiasedFp> {
    let stdout = String::from_utf8_lossy(stdout);
    let mut parts = stdout.split_whitespace();
    let p_biased = parts.next()?.parse::<i32>().ok()?;
    let m = parts.next()?.parse::<u64>().ok()?;
    if parts.next().is_some() {
        return None;
    }
    Some(BiasedFp { p_biased, m })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rustc_harness_answers_known_scaled_rows() {
        assert_eq!(
            rustc_compute_float(ComputeFloatWidth::F32, -10, (1u64 << 24) * 10u64.pow(10))
                .map(|fp| (fp.p_biased, fp.m)),
            Some((151, 0))
        );
        assert_eq!(
            rustc_compute_float(ComputeFloatWidth::F64, -3, ((1u64 << 53) + 2) * 1000)
                .map(|fp| (fp.p_biased, fp.m)),
            Some((1076, 1))
        );
    }
}
