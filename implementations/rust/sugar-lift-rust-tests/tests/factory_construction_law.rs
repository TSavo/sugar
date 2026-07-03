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

const FORBIDDEN_OPTIONAL_BACKSTOP_SYMBOLS: &[&str] = &["backstop::boxed"];

const FORBIDDEN_SUGAR_RUNTIME_ARGUMENT_SYMBOLS: &[&str] =
    &["Effect::RuntimeArgument", "RuntimeArgument {"];

const AGGREGATE_TERM_RECOGNIZERS: &[&str] = &[
    "src/sugar/array_term.rs",
    "src/sugar/repeat_term.rs",
    "src/sugar/tuple_term.rs",
    "src/sugar/vec_macro.rs",
];

const FORBIDDEN_EAGER_AGGREGATE_SYMBOLS: &[&str] =
    &["literal_aggregate_term_in_scope", "reasoned_incomplete"];

const FORBIDDEN_REASON_LEAF_OWNER_FILES: &[&str] = &["src/sugar/closure_term.rs"];

const TARGET_TYPED_METHOD_SPECIALIZATIONS: &[TargetTypedMethodSpecialization] =
    &[TargetTypedMethodSpecialization {
        module: "src/sugar/into.rs",
        claim: "into::EXPR_SUGAR",
        sugar: "IntoSugar",
        fallback_claim: "method::EXPR_SUGAR",
        required_ordering: "ExprSugarClaim::term_before(\n    \"into\",\n    &[\"method\"],\n    crate::sugar::claim::SugarWitnesses::pair(",
        required_decline: "fcx.expected_type()?",
        replacement: "target-typed `.into()` sugar owns only typed primitive conversions; \
                      untyped `.into()` belongs to generic MethodSugar via catalog fallthrough",
    }];

struct TargetTypedMethodSpecialization {
    module: &'static str,
    claim: &'static str,
    sugar: &'static str,
    fallback_claim: &'static str,
    required_ordering: &'static str,
    required_decline: &'static str,
    replacement: &'static str,
}

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
fn names_and_blames_optional_backstop_boxing() {
    let violations = forbidden_symbol_violations(
        &manifest_dir().join("src/sugar"),
        &manifest_dir().join("src"),
        FORBIDDEN_OPTIONAL_BACKSTOP_SYMBOLS,
        "optional backstop boxing",
        "recognizers must decline None instead of constructing a structural backstop sugar",
    );
    assert!(
        violations.is_empty(),
        "construction-law optional-backstop violation: failing to construct a sugar is a factory gap/decline, not a deferred sugar object.\n{}",
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

#[test]
fn names_and_blames_eager_aggregate_term_fallthroughs() {
    let manifest = manifest_dir();
    let mut violations = Vec::new();
    for rel in AGGREGATE_TERM_RECOGNIZERS {
        let path = manifest.join(rel);
        let src = fs::read_to_string(&path)
            .unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
        for symbol in FORBIDDEN_EAGER_AGGREGATE_SYMBOLS {
            if src.contains(symbol) {
                violations.push(format!(
                    "{rel}: eager aggregate recognizer symbol `{symbol}`; construct SugarBody children and compose in desugar"
                ));
            }
        }
    }
    assert!(
        violations.is_empty(),
        "construction-law eager aggregate violation: array/tuple/vec/repeat term sugar must reduce children lazily and propagate child effects.\n{}",
        violations.join("\n")
    );
}

#[test]
fn names_and_blames_typed_effect_owners_using_reason_leaf() {
    let manifest = manifest_dir();
    let mut violations = Vec::new();
    for rel in FORBIDDEN_REASON_LEAF_OWNER_FILES {
        let path = manifest.join(rel);
        let src = fs::read_to_string(&path)
            .unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
        if src.contains("reasoned_incomplete") {
            violations.push(format!(
                "{rel}: typed effect owner still constructs `reasoned_incomplete`; return the named Effect directly"
            ));
        }
    }
    assert!(
        violations.is_empty(),
        "construction-law typed-effect violation: if a sugar owns the semantic stop, it must return its named Effect instead of a legacy reason leaf.\n{}",
        violations.join("\n")
    );
}

#[test]
fn names_and_blames_target_typed_method_specializations_that_block_fallback() {
    let violations = target_typed_method_fallthrough_violations();
    assert!(
        violations.is_empty(),
        "construction-law target-typed method fallthrough violation: \
         a target-typed method specialization may be catalogued before MethodSugar only if \
         it declines when its typed context is absent. Otherwise it steals untyped method calls \
         from the generic method floor.\n{}",
        violations.join("\n")
    );
}

fn manifest_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn target_typed_method_fallthrough_violations() -> Vec<String> {
    let manifest = manifest_dir();
    let src_root = manifest.join("src");
    let catalog = fs::read_to_string(src_root.join("sugar/catalog.rs"))
        .unwrap_or_else(|err| panic!("read src/sugar/catalog.rs: {err}"));
    let claim_catalog = expr_claim_catalog(&catalog);
    let mut violations = Vec::new();

    for spec in TARGET_TYPED_METHOD_SPECIALIZATIONS {
        let module = fs::read_to_string(src_root.join(spec.module.strip_prefix("src/").unwrap()))
            .unwrap_or_else(|err| panic!("read {}: {err}", spec.module));
        if !module.contains(spec.required_ordering) {
            violations.push(format!(
                "{}: {} must declare `{}` so catalog order documents that `{}` is allowed to run before `{}`",
                spec.module, spec.sugar, spec.required_ordering, spec.sugar, spec.fallback_claim
            ));
        }
        if !module.contains(spec.required_decline) {
            violations.push(format!(
                "{}: {} must decline with `{}` before construction; {}",
                spec.module, spec.sugar, spec.required_decline, spec.replacement
            ));
        }
        let claim_marker = format!("&{}", spec.claim);
        let fallback_marker = format!("&{}", spec.fallback_claim);
        match (
            claim_catalog.find(&claim_marker),
            claim_catalog.find(&fallback_marker),
        ) {
            (Some(specialized), Some(fallback)) if specialized < fallback => {}
            (Some(_), Some(_)) => violations.push(format!(
                "src/sugar/catalog.rs: `{}` must appear before `{}` so typed specialization gets first refusal without blocking fallback",
                spec.claim, spec.fallback_claim
            )),
            (None, _) => violations.push(format!(
                "src/sugar/catalog.rs: missing target-typed claim `{}`",
                spec.claim
            )),
            (_, None) => violations.push(format!(
                "src/sugar/catalog.rs: missing generic fallback claim `{}`",
                spec.fallback_claim
            )),
        }
    }

    violations
}

fn expr_claim_catalog(catalog: &str) -> &str {
    let start = catalog
        .find("const EXPR_CLAIMS")
        .expect("catalog defines EXPR_CLAIMS");
    let tail = &catalog[start..];
    let end = tail
        .find("const ITEM_CLAIMS")
        .expect("catalog defines ITEM_CLAIMS after EXPR_CLAIMS");
    &tail[..end]
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
