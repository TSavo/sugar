// SPDX-License-Identifier: Apache-2.0
//
// `OffsetOfSugar`: `mem::offset_of!(T, field...)` is a compiler layout axiom.
// For concrete source-visible layouts, ask rustc for the exact offset and lower
// the macro to an integer literal. If rustc cannot compile the monomorphic
// harness, this sugar stops with a named layout boundary instead of pretending
// the macro is an opaque value.

use std::collections::BTreeMap;
use std::hash::{Hash, Hasher};
use std::io::Write;
use std::path::Path;
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};

use quote::ToTokens;
use sugar_ir_symbolic::num;
use syn::parse::{Parse, ParseStream};
use syn::{Expr, Token, Type};
use tracing::{debug, warn};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::{type_key, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term("offset_of", recognize);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Macro(expr_macro) = expr else {
        return None;
    };
    if !expr_macro
        .mac
        .path
        .segments
        .last()
        .is_some_and(|seg| seg.ident == "offset_of")
    {
        return None;
    }
    let args = syn::parse2::<OffsetOfArgs>(expr_macro.mac.tokens.clone()).ok()?;
    if args.field.is_empty() {
        return None;
    }
    if let Some(rules) = fcx.scope().macro_registry().lookup("offset_of") {
        let Ok(expanded) = crate::macro_expand::expand(&rules, expr_macro.mac.tokens.clone())
        else {
            return None;
        };
        if !expanded.to_string().contains("builtin # offset_of") {
            debug!(
                target: "sugar_lift_rust_tests::sugar::offset_of",
                expansion = expanded.to_string().as_str(),
                "source macro named offset_of is not the compiler-builtin layout form"
            );
            return None;
        }
    }
    Some(Box::new(OffsetOfSugar {
        ty_key: type_key(&args.ty),
        ty_src: args.ty.to_token_stream().to_string(),
        ty: args.ty,
        field_src: args.field.to_string(),
    }))
}

struct OffsetOfArgs {
    ty: Type,
    field: proc_macro2::TokenStream,
}

impl Parse for OffsetOfArgs {
    fn parse(input: ParseStream<'_>) -> syn::Result<Self> {
        let ty = input.parse::<Type>()?;
        input.parse::<Token![,]>()?;
        let field = input.parse::<proc_macro2::TokenStream>()?;
        Ok(Self { ty, field })
    }
}

struct OffsetOfSugar {
    ty: Type,
    ty_key: String,
    ty_src: String,
    field_src: String,
}

impl Sugar for OffsetOfSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let prelude = ctx.scope.offset_prelude_for_type(&self.ty);
        if let Some(offset) =
            rustc_offset_of_field(&self.ty_key, &self.ty_src, &self.field_src, &prelude)
        {
            debug!(
                target: "sugar_lift_rust_tests::sugar::offset_of",
                ty = self.ty_key.as_str(),
                field = self.field_src.as_str(),
                offset,
                local_type_prelude_bytes = prelude.len(),
                "resolved offset_of compiler axiom with rustc layout harness"
            );
            return Outcome::Complete(Desugared::Term(num(offset)));
        }
        debug!(
            target: "sugar_lift_rust_tests::sugar::offset_of",
            ty = self.ty_key.as_str(),
            field = self.field_src.as_str(),
            local_type_prelude_bytes = prelude.len(),
            "offset_of compiler axiom layout is not known to this lift"
        );
        Outcome::Incomplete(Effect::Unsupported {
            reason: format!(
                "unsupported term `offset_of!({}, {})`: layout is unknown to this lift \
                 (rustc could not compile a monomorphic offset_of harness for this type); refused",
                self.ty_key, self.field_src
            ),
        })
    }
}

fn rustc_offset_of_field(
    ty_key: &str,
    ty_src: &str,
    field_src: &str,
    prelude: &str,
) -> Option<i128> {
    let cache_key = format!("{prelude}\0{ty_src}\0{field_src}");
    let cache = OFFSET_CACHE.get_or_init(|| Mutex::new(BTreeMap::new()));
    if let Some(cached) = cache.lock().expect("offset cache poisoned").get(&cache_key) {
        return *cached;
    }
    let result = compile_and_run_offset_harness(ty_key, ty_src, field_src, prelude);
    cache
        .lock()
        .expect("offset cache poisoned")
        .insert(cache_key, result);
    result
}

static OFFSET_CACHE: OnceLock<Mutex<BTreeMap<String, Option<i128>>>> = OnceLock::new();
static OFFSET_HARNESS_COUNTER: AtomicU64 = AtomicU64::new(0);

fn compile_and_run_offset_harness(
    ty_key: &str,
    ty_src: &str,
    field_src: &str,
    prelude: &str,
) -> Option<i128> {
    let source = offset_harness_source("", prelude, ty_src, field_src);
    let tag = harness_tag(&source);
    let dir = std::env::temp_dir().join("sugar_offsetof_harness");
    if let Err(e) = std::fs::create_dir_all(&dir) {
        warn!(
            target: "sugar_lift_rust_tests::sugar::offset_of",
            ty = ty_key,
            field = field_src,
            error = %e,
            "could not create rustc offset_of harness directory"
        );
        return None;
    }
    let src_path = dir.join(format!("offsetof_{tag}.rs"));
    let bin_path = dir.join(format!("offsetof_{tag}_bin"));
    let result = match run_offset_harness(&src_path, &bin_path, &source, ty_key, field_src, false) {
        Ok(offset) => Some(offset),
        Err(stderr) if stderr.contains("extern types are experimental") => {
            debug!(
                target: "sugar_lift_rust_tests::sugar::offset_of",
                ty = ty_key,
                field = field_src,
                "retrying offset_of harness with extern_types feature gate"
            );
            let source =
                offset_harness_source("#![feature(extern_types)]\n", prelude, ty_src, field_src);
            run_offset_harness(&src_path, &bin_path, &source, ty_key, field_src, true).ok()
        }
        Err(_) => None,
    };
    let _ = std::fs::remove_file(&src_path);
    let _ = std::fs::remove_file(&bin_path);
    result
}

fn offset_harness_source(
    feature_prelude: &str,
    prelude: &str,
    ty_src: &str,
    field_src: &str,
) -> String {
    format!(
        "{feature_prelude}\
         #![allow(dead_code, incomplete_features, non_camel_case_types, non_snake_case, non_upper_case_globals, unused_imports)]\n\
         {prelude}\n\
         fn main() {{ println!(\"{{}}\", ::std::mem::offset_of!({ty_src}, {field_src})); }}\n"
    )
}

fn harness_tag(source: &str) -> String {
    let mut h = std::collections::hash_map::DefaultHasher::new();
    source.hash(&mut h);
    let digest = h.finish();
    let count = OFFSET_HARNESS_COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("{digest:016x}_{count:016x}")
}

fn run_offset_harness(
    src_path: &Path,
    bin_path: &Path,
    source: &str,
    ty_key: &str,
    field_src: &str,
    rustc_bootstrap: bool,
) -> Result<i128, String> {
    if let Err(e) = std::fs::File::create(src_path).and_then(|mut f| f.write_all(source.as_bytes()))
    {
        warn!(
            target: "sugar_lift_rust_tests::sugar::offset_of",
            ty = ty_key,
            field = field_src,
            error = %e,
            "could not write rustc offset_of harness"
        );
        return Err(e.to_string());
    }
    let mut compile_cmd = Command::new("rustc");
    compile_cmd
        .arg("--edition")
        .arg("2021")
        .arg("-A")
        .arg("warnings")
        .arg(src_path)
        .arg("-o")
        .arg(bin_path);
    if rustc_bootstrap {
        compile_cmd.env("RUSTC_BOOTSTRAP", "1");
    }
    let compile = compile_cmd.output();
    match compile {
        Ok(out) if out.status.success() => {}
        Ok(out) => {
            let stderr = String::from_utf8_lossy(&out.stderr).to_string();
            let mut truncated = stderr.clone();
            truncated.truncate(800);
            debug!(
                target: "sugar_lift_rust_tests::sugar::offset_of",
                ty = ty_key,
                field = field_src,
                stderr = truncated.as_str(),
                "rustc offset_of harness did not compile"
            );
            return Err(stderr);
        }
        Err(e) => {
            warn!(
                target: "sugar_lift_rust_tests::sugar::offset_of",
                ty = ty_key,
                field = field_src,
                error = %e,
                "could not invoke rustc offset_of harness"
            );
            return Err(e.to_string());
        }
    }
    let run = Command::new(bin_path).output();
    let out = match run {
        Ok(out) if out.status.success() => out,
        Ok(out) => {
            let mut stderr = String::from_utf8_lossy(&out.stderr).to_string();
            stderr.truncate(800);
            debug!(
                target: "sugar_lift_rust_tests::sugar::offset_of",
                ty = ty_key,
                field = field_src,
                stderr = stderr.as_str(),
                "rustc offset_of harness binary failed"
            );
            return Err(stderr);
        }
        Err(e) => {
            warn!(
                target: "sugar_lift_rust_tests::sugar::offset_of",
                ty = ty_key,
                field = field_src,
                error = %e,
                "could not run rustc offset_of harness binary"
            );
            return Err(e.to_string());
        }
    };
    let stdout = String::from_utf8_lossy(&out.stdout);
    stdout.trim().parse::<i128>().map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rustc_offset_harness_answers_concrete_repr_c_type() {
        let prelude = "#[repr(C)] struct Foo { x: u8, y: u16 }";
        assert_eq!(rustc_offset_of_field("Foo", "Foo", "y", prelude), Some(2));
        assert_eq!(rustc_offset_of_field("T", "T", "y", ""), None);
    }

    #[test]
    fn rustc_offset_harness_replays_extern_type_feature_context() {
        let prelude = r#"
            unsafe extern "C" { type Extern; }
            #[repr(C)]
            struct Gamma { x: u8, y: u16, z: Extern }
        "#;
        assert_eq!(
            rustc_offset_of_field("Gamma", "Gamma", "y", prelude),
            Some(2)
        );
    }
}
