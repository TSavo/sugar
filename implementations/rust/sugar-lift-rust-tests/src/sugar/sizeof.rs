// SPDX-License-Identifier: Apache-2.0
//
// `SizeOfSugar`: `mem::size_of::<T>()` is a compiler axiom, not an opaque
// function call. The Rust compiler has already made `T` meaningful for compiled
// code; the kit reads that axiom and emits a concrete size literal when `T` is
// concrete enough for rustc to answer. If rustc cannot compile the monomorphic
// harness, the type-layout boundary is named as an effect. It never emits a
// symbolic `sizeof:T` pseudo-fact.

use std::collections::BTreeMap;
use std::hash::{Hash, Hasher};
use std::io::Write;
use std::path::Path;
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};

use sugar_ir_symbolic::num;
use syn::{PathArguments, Type};
use tracing::{debug, warn};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("sizeof", SugarRole::Term, recognize);

// No as_expr / Expr:: / raw syn in this body.
fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let parts = frag.call_size_of_type_parts(fcx)?;
    Some(Box::new(SizeOfSugar {
        ty_key: parts.ty_key,
        ty_src: parts.ty_src,
        primitive_size: parts.primitive_size,
        atomic_size: parts.atomic_size,
    }))
}

// No raw syn fields in this struct.
struct SizeOfSugar {
    ty_key: String,
    ty_src: String,
    primitive_size: Option<i128>,
    atomic_size: Option<i128>,
}

impl Sugar for SizeOfSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(size) = self.primitive_size {
            debug!(
                target: "sugar_lift_rust_tests::sugar::sizeof",
                ty = self.ty_key.as_str(),
                size,
                "resolved primitive size_of compiler axiom to literal"
            );
            return Outcome::Complete(Desugared::Term(num(size)));
        }
        if let Some(size) = self.atomic_size {
            debug!(
                target: "sugar_lift_rust_tests::sugar::sizeof",
                ty = self.ty_key.as_str(),
                size,
                "resolved size_of compiler axiom for a core atomic (layout == underlying)"
            );
            return Outcome::Complete(Desugared::Term(num(size)));
        }
        let prelude = ctx.scope.layout_prelude_for_type_src(&self.ty_src);
        if let Some(size) = rustc_size_of_type(&self.ty_key, &self.ty_src, &prelude) {
            debug!(
                target: "sugar_lift_rust_tests::sugar::sizeof",
                ty = self.ty_key.as_str(),
                size,
                local_type_prelude_bytes = prelude.len(),
                "resolved size_of compiler axiom with rustc layout harness"
            );
            return Outcome::Complete(Desugared::Term(num(size)));
        }
        debug!(
            target: "sugar_lift_rust_tests::sugar::sizeof",
            ty = self.ty_key.as_str(),
            local_type_prelude_bytes = prelude.len(),
            "size_of compiler axiom layout is not known to this lift"
        );
        Outcome::Incomplete(Effect::TypeLayout {
            boundary: format!("mem::size_of::<{}>()", self.ty_key),
        })
    }
}

/// The `core::sync::atomic` types have a layout GUARANTEED by the standard library to
/// equal their underlying primitive (e.g. `AtomicU32` "has the same in-memory
/// representation as the underlying integer type, `u32`"; `AtomicPtr<T>` is
/// pointer-sized). That is a COMPILER/std PROMISE, not an opaque fact -- so
/// `size_of::<AtomicU32>()` is `size_of::<u32>()`, read out loud. We seed the table
/// here rather than lean on the rustc harness, which fails when the source names the
/// atomic via a `use` import the monomorphic harness does not carry. Matching the LAST
/// path segment admits both the imported (`AtomicU32`) and fully-qualified
/// (`core::sync::atomic::AtomicU32`) spellings. Sizes are computed from the underlying
/// primitive's host `size_of` (matching the corpus-pinned 64-bit target), exactly as
/// `primitive_size_of` already does for `usize`/`isize`.
fn core_atomic_size_of(ty: &Type) -> Option<i128> {
    let Type::Path(path) = ty else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    let segment = path.path.segments.last()?;
    let ident = segment.ident.to_string();
    // `AtomicPtr<T>` carries a type argument and is pointer-sized regardless of `T`;
    // the integer atomics carry NO argument and equal their underlying primitive.
    let size = match ident.as_str() {
        "AtomicBool" => std::mem::size_of::<bool>(),
        "AtomicU8" | "AtomicI8" => std::mem::size_of::<u8>(),
        "AtomicU16" | "AtomicI16" => std::mem::size_of::<u16>(),
        "AtomicU32" | "AtomicI32" => std::mem::size_of::<u32>(),
        "AtomicU64" | "AtomicI64" => std::mem::size_of::<u64>(),
        "AtomicUsize" => std::mem::size_of::<usize>(),
        "AtomicIsize" => std::mem::size_of::<isize>(),
        "AtomicPtr" => std::mem::size_of::<*const ()>(),
        _ => return None,
    };
    // Only `AtomicPtr` may carry a type argument; an integer atomic with arguments is
    // not the atomic we know (a same-named user type, say) -> decline, let the harness
    // or refuse decide. (finite-or-refuse: never warrant a shape we cannot pin.)
    if ident != "AtomicPtr" && !matches!(segment.arguments, PathArguments::None) {
        return None;
    }
    Some(size as i128)
}

fn rustc_size_of_type(ty_key: &str, ty_src: &str, prelude: &str) -> Option<i128> {
    let cache_key = format!("{prelude}\0{ty_src}");
    let cache = SIZEOF_CACHE.get_or_init(|| Mutex::new(BTreeMap::new()));
    if let Some(cached) = cache.lock().expect("sizeof cache poisoned").get(&cache_key) {
        return *cached;
    }
    let result = compile_and_run_sizeof_harness(ty_key, ty_src, prelude);
    cache
        .lock()
        .expect("sizeof cache poisoned")
        .insert(cache_key, result);
    result
}

static SIZEOF_CACHE: OnceLock<Mutex<BTreeMap<String, Option<i128>>>> = OnceLock::new();
static SIZEOF_HARNESS_COUNTER: AtomicU64 = AtomicU64::new(0);

fn compile_and_run_sizeof_harness(ty_key: &str, ty_src: &str, prelude: &str) -> Option<i128> {
    let source = format!(
        "#![allow(dead_code, non_camel_case_types, non_snake_case, non_upper_case_globals, unused_imports)]\n\
         {prelude}\n\
         fn main() {{ println!(\"{{}}\", ::std::mem::size_of::<{ty_src}>()); }}\n"
    );
    let tag = harness_tag(&source);
    let dir = std::env::temp_dir().join("sugar_sizeof_harness");
    if let Err(e) = std::fs::create_dir_all(&dir) {
        warn!(
            target: "sugar_lift_rust_tests::sugar::sizeof",
            ty = ty_key,
            error = %e,
            "could not create rustc size_of harness directory"
        );
        return None;
    }
    let src_path = dir.join(format!("sizeof_{tag}.rs"));
    let bin_path = dir.join(format!("sizeof_{tag}_bin"));
    let result = run_sizeof_harness(&src_path, &bin_path, &source, ty_key);
    let _ = std::fs::remove_file(&src_path);
    let _ = std::fs::remove_file(&bin_path);
    result
}

fn harness_tag(source: &str) -> String {
    let mut h = std::collections::hash_map::DefaultHasher::new();
    source.hash(&mut h);
    let digest = h.finish();
    let count = SIZEOF_HARNESS_COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("{digest:016x}_{count:016x}")
}

fn run_sizeof_harness(
    src_path: &Path,
    bin_path: &Path,
    source: &str,
    ty_key: &str,
) -> Option<i128> {
    if let Err(e) = std::fs::File::create(src_path).and_then(|mut f| f.write_all(source.as_bytes()))
    {
        warn!(
            target: "sugar_lift_rust_tests::sugar::sizeof",
            ty = ty_key,
            error = %e,
            "could not write rustc size_of harness"
        );
        return None;
    }
    let compile = Command::new("rustc")
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
                target: "sugar_lift_rust_tests::sugar::sizeof",
                ty = ty_key,
                stderr = stderr.as_str(),
                "rustc size_of harness did not compile"
            );
            return None;
        }
        Err(e) => {
            warn!(
                target: "sugar_lift_rust_tests::sugar::sizeof",
                ty = ty_key,
                error = %e,
                "could not invoke rustc size_of harness"
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
                target: "sugar_lift_rust_tests::sugar::sizeof",
                ty = ty_key,
                stderr = stderr.as_str(),
                "rustc size_of harness binary failed"
            );
            return None;
        }
        Err(e) => {
            warn!(
                target: "sugar_lift_rust_tests::sugar::sizeof",
                ty = ty_key,
                error = %e,
                "could not run rustc size_of harness binary"
            );
            return None;
        }
    };
    let stdout = String::from_utf8_lossy(&out.stdout);
    stdout.trim().parse::<i128>().ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rustc_size_of_harness_answers_concrete_type_and_rejects_unbound_t() {
        assert_eq!(rustc_size_of_type("u32", "u32", ""), Some(4));
        assert_eq!(rustc_size_of_type("T", "T", ""), None);
    }

    #[test]
    fn type_layout_effect_names_sizeof_harness_miss() {
        let effect = Effect::TypeLayout {
            boundary: "mem::size_of::<T>()".to_string(),
        };
        let reason = effect.reason();
        assert!(reason.contains("mem::size_of::<T>()"));
        assert!(reason.contains("layout is unknown to this lift"));
        assert!(reason.contains("monomorphic size_of harness"));
    }

    fn ty(src: &str) -> Type {
        syn::parse_str::<Type>(src).expect("parse type")
    }

    // -- Phase-3 from_src test ------------------------------------------------
    // source -> SourceFragment -> observed -> call_size_of_type_parts -> floor.
    // No parse_quote! / StubTerm / run().

    #[test]
    fn from_src_size_of_u32_parts_and_recognize() {
        use crate::sugar::factory::SugarBuildCtx;
        use crate::{LiftOptions, TemporalPlan, TemporalScope};
        use std::collections::BTreeMap;
        use syn::Expr;

        // Positive: mem::size_of::<u32>() is a Call fragment.
        let expr: Expr = syn::parse_str("mem::size_of::<u32>()").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");
        assert_eq!(frag.observed(), "Call", "size_of call observed as Call");

        let scope = TemporalScope::new("sizeof-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        // accessor gate: type parts decoded correctly
        let parts = frag
            .call_size_of_type_parts(&fcx)
            .expect("mem::size_of::<u32>() must yield SizeOfTypeParts");
        assert_eq!(parts.ty_key, "u32", "ty_key");
        assert_eq!(parts.primitive_size, Some(4), "primitive u32 size is 4");
        assert!(parts.atomic_size.is_none(), "u32 is not an atomic");

        // recognize returns Some
        assert!(
            recognize(&frag, &fcx).is_some(),
            "mem::size_of::<u32>() recognized"
        );

        // Discrimination: call with arguments is rejected
        let expr_args: Expr = syn::parse_str("mem::size_of::<u32>(extra)").expect("parse");
        let frag_args = SourceFragment::expr(&expr_args, "<src>");
        assert!(
            frag_args.call_size_of_type_parts(&fcx).is_none(),
            "call with extra arg must return None"
        );
        assert!(
            recognize(&frag_args, &fcx).is_none(),
            "call with extra arg not recognized"
        );

        // Structural: a bare binop is not a size_of call
        let expr_binop: Expr = syn::parse_str("x + 1").expect("parse");
        let frag_binop = SourceFragment::expr(&expr_binop, "<src>");
        assert!(
            frag_binop.call_size_of_type_parts(&fcx).is_none(),
            "binop must return None from call_size_of_type_parts"
        );
        assert!(
            recognize(&frag_binop, &fcx).is_none(),
            "binop not recognized"
        );
    }

    #[test]
    fn from_src_size_of_atomic_parts() {
        use crate::sugar::factory::SugarBuildCtx;
        use crate::{LiftOptions, TemporalPlan, TemporalScope};
        use std::collections::BTreeMap;
        use syn::Expr;

        let expr: Expr = syn::parse_str("core::mem::size_of::<AtomicU32>()").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        let scope = TemporalScope::new("sizeof-atomic-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);

        let parts = frag
            .call_size_of_type_parts(&fcx)
            .expect("core::mem::size_of::<AtomicU32>() must yield SizeOfTypeParts");
        assert_eq!(parts.ty_key, "AtomicU32", "ty_key for AtomicU32");
        assert!(
            parts.primitive_size.is_none(),
            "AtomicU32 is not a primitive"
        );
        assert_eq!(parts.atomic_size, Some(4), "AtomicU32 atomic size is 4");
    }

    #[test]
    fn core_atomic_layout_equals_underlying_primitive() {
        // The std layout guarantee, read out loud: each atomic == its underlying int.
        assert_eq!(core_atomic_size_of(&ty("AtomicBool")), Some(1));
        assert_eq!(core_atomic_size_of(&ty("AtomicU8")), Some(1));
        assert_eq!(core_atomic_size_of(&ty("AtomicI16")), Some(2));
        assert_eq!(core_atomic_size_of(&ty("AtomicU32")), Some(4));
        assert_eq!(core_atomic_size_of(&ty("AtomicU64")), Some(8));
        // Fully-qualified spelling resolves via the LAST segment.
        assert_eq!(
            core_atomic_size_of(&ty("core::sync::atomic::AtomicU32")),
            Some(4)
        );
        // Pointer-width atomics, matching the corpus-pinned 64-bit target.
        assert_eq!(
            core_atomic_size_of(&ty("AtomicUsize")),
            Some(std::mem::size_of::<usize>() as i128)
        );
        assert_eq!(
            core_atomic_size_of(&ty("AtomicPtr<u8>")),
            Some(std::mem::size_of::<*const ()>() as i128)
        );
        // Not an atomic we know -> decline (finite-or-refuse).
        assert_eq!(core_atomic_size_of(&ty("u32")), None);
        assert_eq!(core_atomic_size_of(&ty("AtomicU32<T>")), None);
    }
}
