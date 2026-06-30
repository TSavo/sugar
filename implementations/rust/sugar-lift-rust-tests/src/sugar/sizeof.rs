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

use quote::ToTokens;
use sugar_ir_symbolic::num;
use syn::{Expr, ExprCall, ExprPath, GenericArgument, PathArguments, Type};
use tracing::{debug, warn};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::{type_key, Desugared, Effect, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("sizeof", SugarRole::Term, recognize);

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Call(call) = expr else {
        return None;
    };
    let ty = size_of_type_arg(call, fcx)?;
    Some(Box::new(SizeOfSugar {
        ty: ty.clone(),
        ty_key: type_key(ty),
        ty_src: ty.to_token_stream().to_string(),
    }))
}

struct SizeOfSugar {
    ty: Type,
    ty_key: String,
    ty_src: String,
}

impl Sugar for SizeOfSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(size) = primitive_size_of(&self.ty) {
            debug!(
                target: "sugar_lift_rust_tests::sugar::sizeof",
                ty = self.ty_key.as_str(),
                size,
                "resolved primitive size_of compiler axiom to literal"
            );
            return Outcome::Complete(Desugared::Term(num(size)));
        }
        if let Some(size) = core_atomic_size_of(&self.ty) {
            debug!(
                target: "sugar_lift_rust_tests::sugar::sizeof",
                ty = self.ty_key.as_str(),
                size,
                "resolved size_of compiler axiom for a core atomic (layout == underlying)"
            );
            return Outcome::Complete(Desugared::Term(num(size)));
        }
        let prelude = ctx.scope.layout_prelude_for_type(&self.ty);
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

fn size_of_type_arg<'a>(call: &'a ExprCall, fcx: &SugarBuildCtx) -> Option<&'a Type> {
    if !call.args.is_empty() {
        return None;
    }
    let Expr::Path(ExprPath {
        qself: None, path, ..
    }) = call.func.as_ref()
    else {
        return None;
    };
    if !is_compiler_size_of_path(path, fcx) {
        return None;
    }
    let last = path.segments.last()?;
    let PathArguments::AngleBracketed(args) = &last.arguments else {
        return None;
    };
    if args.args.len() != 1 {
        return None;
    }
    let Some(GenericArgument::Type(ty)) = args.args.first() else {
        return None;
    };
    Some(ty)
}

fn is_compiler_size_of_path(path: &syn::Path, fcx: &SugarBuildCtx) -> bool {
    let segments = path.segments.iter().collect::<Vec<_>>();
    match segments.as_slice() {
        [size_of] if size_of.ident == "size_of" => !fcx.scope().has_visible_fn("size_of"),
        [mem, size_of] if mem.ident == "mem" && size_of.ident == "size_of" => true,
        [std_or_core, mem, size_of]
            if matches!(std_or_core.ident.to_string().as_str(), "std" | "core")
                && mem.ident == "mem"
                && size_of.ident == "size_of" =>
        {
            true
        }
        _ => false,
    }
}

fn primitive_size_of(ty: &Type) -> Option<i128> {
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
    let size = match segment.ident.to_string().as_str() {
        "bool" => std::mem::size_of::<bool>(),
        "char" => std::mem::size_of::<char>(),
        "i8" => std::mem::size_of::<i8>(),
        "i16" => std::mem::size_of::<i16>(),
        "i32" => std::mem::size_of::<i32>(),
        "i64" => std::mem::size_of::<i64>(),
        "i128" => std::mem::size_of::<i128>(),
        "isize" => std::mem::size_of::<isize>(),
        "u8" => std::mem::size_of::<u8>(),
        "u16" => std::mem::size_of::<u16>(),
        "u32" => std::mem::size_of::<u32>(),
        "u64" => std::mem::size_of::<u64>(),
        "u128" => std::mem::size_of::<u128>(),
        "usize" => std::mem::size_of::<usize>(),
        "f32" => std::mem::size_of::<f32>(),
        "f64" => std::mem::size_of::<f64>(),
        _ => return None,
    };
    Some(size as i128)
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
