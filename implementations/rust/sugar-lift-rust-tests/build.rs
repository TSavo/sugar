// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Factory construction law guard.
//
// Composite Sugar must be constructed from typed SugarBody children, not raw
// syntax that gets decomposed later from a side door. This build script is an
// intentionally loud compile gate: a Sugar struct/enum that stores a raw child
// field such as `receiver: Expr` or `pred: ExprClosure` fails the crate build.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use quote::ToTokens;
use syn::spanned::Spanned;

const RAW_CHILD_FIELD_NAMES: &[&str] = &[
    "arg",
    "args",
    "body",
    "call",
    "closure",
    "container",
    "domain",
    "elems",
    "expr",
    "exponent",
    "f",
    "idx",
    "inner",
    "iter",
    "iterator",
    "left",
    "lhs",
    "mac",
    "operand",
    "operands",
    "pred",
    "receiver",
    "rhs",
    "right",
    "scrutinee",
    "site",
    "source",
    "target",
    "value",
    "values",
];

const RAW_SYNTAX_TYPES: &[&str] = &[
    "Block",
    "Expr",
    "ExprArray",
    "ExprAssign",
    "ExprBinary",
    "ExprBlock",
    "ExprCall",
    "ExprClosure",
    "ExprField",
    "ExprForLoop",
    "ExprIf",
    "ExprLit",
    "ExprLoop",
    "ExprMacro",
    "ExprMatch",
    "ExprMethodCall",
    "ExprPath",
    "ExprRange",
    "ExprReference",
    "ExprRepeat",
    "ExprTuple",
    "ExprUnary",
    "ExprWhile",
    "Stmt",
];

const FORBIDDEN_GAP_SYMBOLS: &[&str] = &[
    "Effect::Unsupported",
    "UnsupportedTermCause",
    "STRUCTURAL_BACKSTOP_REASON",
    "Outcome::from_opt",
    "FactoryGap",
    "FactoryReduction",
    "compat_reduction",
    "structural_bail_to_gap",
];

const FORBIDDEN_SUGAR_RUNTIME_ARGUMENT_SYMBOLS: &[&str] =
    &["Effect::RuntimeArgument", "RuntimeArgument {"];

fn main() {
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let src_dir = manifest_dir.join("src");
    let sugar_dir = manifest_dir.join("src/sugar");
    println!("cargo:rerun-if-changed={}", src_dir.display());
    println!("cargo:rerun-if-changed={}", sugar_dir.display());

    let mut violations = Vec::new();
    for entry in walkdir::WalkDir::new(&sugar_dir)
        .max_depth(1)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|entry| {
            entry.file_type().is_file() && entry.path().extension().is_some_and(|ext| ext == "rs")
        })
    {
        audit_file(entry.path(), &sugar_dir, &mut violations);
    }

    for entry in walkdir::WalkDir::new(&src_dir)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|entry| {
            entry.file_type().is_file() && entry.path().extension().is_some_and(|ext| ext == "rs")
        })
    {
        audit_forbidden_gap_symbols(entry.path(), &src_dir, &mut violations);
    }

    for entry in walkdir::WalkDir::new(&sugar_dir)
        .max_depth(1)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|entry| {
            entry.file_type().is_file() && entry.path().extension().is_some_and(|ext| ext == "rs")
        })
    {
        audit_forbidden_sugar_runtime_argument_symbols(entry.path(), &sugar_dir, &mut violations);
    }

    if violations.is_empty() {
        return;
    }

    violations.sort();
    for violation in &violations {
        println!("cargo:warning=factory construction law violation: {violation}");
    }
    panic!(
        "factory construction law failed: {} violation(s): construct children as SugarBody floors and remove runtime gap symbols",
        violations.len()
    );
}

fn audit_file(path: &Path, sugar_dir: &Path, violations: &mut Vec<String>) {
    let src = fs::read_to_string(path)
        .unwrap_or_else(|err| panic!("cannot read {}: {err}", path.display()));
    let parsed = syn::parse_file(&src)
        .unwrap_or_else(|err| panic!("cannot parse {}: {err}", path.display()));
    let rel = path
        .strip_prefix(sugar_dir.parent().unwrap())
        .unwrap_or(path);
    let file = rel.to_string_lossy().replace('\\', "/");

    for item in parsed.items {
        match item {
            syn::Item::Struct(item) if is_sugar_type(&item.ident.to_string()) => {
                audit_fields(
                    &file,
                    &item.ident.to_string(),
                    None,
                    &item.fields,
                    violations,
                );
            }
            syn::Item::Enum(item) if is_sugar_type(&item.ident.to_string()) => {
                for variant in item.variants {
                    audit_fields(
                        &file,
                        &item.ident.to_string(),
                        Some(&variant.ident.to_string()),
                        &variant.fields,
                        violations,
                    );
                }
            }
            _ => {}
        }
    }
}

fn is_sugar_type(name: &str) -> bool {
    name.ends_with("Sugar")
}

fn audit_fields(
    file: &str,
    owner: &str,
    variant: Option<&str>,
    fields: &syn::Fields,
    violations: &mut Vec<String>,
) {
    for (idx, field) in fields.iter().enumerate() {
        let field_name = field
            .ident
            .as_ref()
            .map(ToString::to_string)
            .unwrap_or_else(|| format!("#{idx}"));
        if !is_raw_child_field(&field_name) {
            continue;
        }
        let Some(raw_kind) = raw_syntax_type(&field.ty) else {
            continue;
        };
        let line = field.span().start().line;
        let ty = field.ty.to_token_stream().to_string();
        let owner = match variant {
            Some(variant) => format!("{owner}::{variant}"),
            None => owner.to_string(),
        };
        violations.push(format!(
            "{file}:{line} {owner}.{field_name}: {ty} stores raw {raw_kind}; construct this child as SugarBody<...> or make construction fail before Outcome"
        ));
    }
}

fn is_raw_child_field(name: &str) -> bool {
    RAW_CHILD_FIELD_NAMES.contains(&name)
}

fn raw_syntax_type(ty: &syn::Type) -> Option<&'static str> {
    match ty {
        syn::Type::Path(path) => {
            for segment in &path.path.segments {
                let ident = segment.ident.to_string();
                if let Some(raw) = RAW_SYNTAX_TYPES.iter().find(|raw| **raw == ident) {
                    return Some(*raw);
                }
                if let syn::PathArguments::AngleBracketed(args) = &segment.arguments {
                    for arg in &args.args {
                        if let syn::GenericArgument::Type(ty) = arg {
                            if let Some(raw) = raw_syntax_type(ty) {
                                return Some(raw);
                            }
                        }
                    }
                }
            }
            None
        }
        syn::Type::Reference(reference) => raw_syntax_type(&reference.elem),
        syn::Type::Ptr(ptr) => raw_syntax_type(&ptr.elem),
        syn::Type::Group(group) => raw_syntax_type(&group.elem),
        syn::Type::Paren(paren) => raw_syntax_type(&paren.elem),
        syn::Type::Array(array) => raw_syntax_type(&array.elem),
        syn::Type::Slice(slice) => raw_syntax_type(&slice.elem),
        syn::Type::Tuple(tuple) => tuple.elems.iter().find_map(raw_syntax_type),
        _ => None,
    }
}

fn audit_forbidden_gap_symbols(path: &Path, src_dir: &Path, violations: &mut Vec<String>) {
    let src = fs::read_to_string(path)
        .unwrap_or_else(|err| panic!("cannot read {}: {err}", path.display()));
    let rel = path.strip_prefix(src_dir.parent().unwrap()).unwrap_or(path);
    let file = rel.to_string_lossy().replace('\\', "/");

    for (idx, line) in src.lines().enumerate() {
        for symbol in FORBIDDEN_GAP_SYMBOLS {
            if line.contains(symbol) {
                violations.push(format!(
                    "{file}:{} forbidden runtime gap symbol `{symbol}`; return a named Effect or a Complete Outcome, never a gap Outcome",
                    idx + 1
                ));
            }
        }
    }
}

fn audit_forbidden_sugar_runtime_argument_symbols(
    path: &Path,
    sugar_dir: &Path,
    violations: &mut Vec<String>,
) {
    let src = fs::read_to_string(path)
        .unwrap_or_else(|err| panic!("cannot read {}: {err}", path.display()));
    let rel = path
        .strip_prefix(sugar_dir.parent().unwrap())
        .unwrap_or(path);
    let file = rel.to_string_lossy().replace('\\', "/");

    for (idx, line) in src.lines().enumerate() {
        for symbol in FORBIDDEN_SUGAR_RUNTIME_ARGUMENT_SYMBOLS {
            if line.contains(symbol) {
                violations.push(format!(
                    "{file}:{} forbidden sugar-owned RuntimeArgument symbol `{symbol}`; RuntimeArgument is owned only by function/input argument boundary sugar",
                    idx + 1
                ));
            }
        }
    }
}
