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

#[test]
fn names_and_blames_raw_child_fields_on_sugar_types() {
    let violations = raw_child_field_violations();
    assert!(
        violations.is_empty(),
        "construction-law raw-child violation: Sugar must be constructed with typed SugarBody children, not raw AST children.\n{}",
        violations.join("\n")
    );
}

#[test]
fn names_and_blames_fake_gap_symbols() {
    let violations = forbidden_symbol_violations(
        &manifest_dir().join("src"),
        &manifest_dir(),
        FORBIDDEN_GAP_SYMBOLS,
        "fake gap symbol",
        "use Complete or a named Effect; no third Outcome",
    );
    assert!(
        violations.is_empty(),
        "construction-law fake-gap violation: panic is the convention-failure path; Incomplete is only a named effect.\n{}",
        violations.join("\n")
    );
}

#[test]
fn names_and_blames_sugar_owned_runtime_argument() {
    let violations = forbidden_symbol_violations(
        &manifest_dir().join("src/sugar"),
        &manifest_dir().join("src"),
        FORBIDDEN_SUGAR_RUNTIME_ARGUMENT_SYMBOLS,
        "sugar-owned RuntimeArgument",
        "RuntimeArgument belongs only to function/input argument boundary sugar",
    );
    assert!(
        violations.is_empty(),
        "construction-law RuntimeArgument violation: ordinary sugar must propagate child effects or panic/gap; it must not invent RuntimeArgument.\n{}",
        violations.join("\n")
    );
}

fn manifest_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn raw_child_field_violations() -> Vec<String> {
    let manifest = manifest_dir();
    let sugar_dir = manifest.join("src/sugar");
    let mut violations = Vec::new();
    for path in rust_files(&sugar_dir) {
        let src = fs::read_to_string(&path)
            .unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
        let parsed =
            syn::parse_file(&src).unwrap_or_else(|err| panic!("parse {}: {err}", path.display()));
        let file = relative_file(&path, &manifest.join("src"));
        for item in parsed.items {
            match item {
                syn::Item::Struct(item) if is_sugar_type(&item.ident.to_string()) => {
                    audit_fields(
                        &file,
                        &item.ident.to_string(),
                        None,
                        &item.fields,
                        &mut violations,
                    );
                }
                syn::Item::Enum(item) if is_sugar_type(&item.ident.to_string()) => {
                    for variant in item.variants {
                        audit_fields(
                            &file,
                            &item.ident.to_string(),
                            Some(&variant.ident.to_string()),
                            &variant.fields,
                            &mut violations,
                        );
                    }
                }
                _ => {}
            }
        }
    }
    violations.sort();
    violations
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
        if !RAW_CHILD_FIELD_NAMES.contains(&field_name.as_str()) {
            continue;
        }
        let Some(raw_kind) = raw_syntax_type(&field.ty) else {
            continue;
        };
        let owner = match variant {
            Some(variant) => format!("{owner}::{variant}"),
            None => owner.to_string(),
        };
        violations.push(format!(
            "{file}:{} {owner}.{field_name}: {} stores raw {raw_kind}; construct this child as SugarBody<...>",
            field.span().start().line,
            field.ty.to_token_stream()
        ));
    }
}

fn forbidden_symbol_violations(
    root: &Path,
    relative_root: &Path,
    symbols: &[&str],
    category: &str,
    instruction: &str,
) -> Vec<String> {
    let mut violations = Vec::new();
    for path in rust_files(root) {
        let src = fs::read_to_string(&path)
            .unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
        let file = relative_file(&path, relative_root);
        for (idx, line) in src.lines().enumerate() {
            for symbol in symbols {
                if line.contains(symbol) {
                    violations.push(format!(
                        "{file}:{} {category} `{symbol}`; {instruction}",
                        idx + 1
                    ));
                }
            }
        }
    }
    violations.sort();
    violations
}

fn rust_files(root: &Path) -> Vec<PathBuf> {
    let mut files = walkdir::WalkDir::new(root)
        .max_depth(1)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|entry| {
            entry.file_type().is_file() && entry.path().extension().is_some_and(|ext| ext == "rs")
        })
        .map(|entry| entry.into_path())
        .collect::<Vec<_>>();
    files.sort();
    files
}

fn relative_file(path: &Path, root: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/")
}

fn is_sugar_type(name: &str) -> bool {
    name.ends_with("Sugar")
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
