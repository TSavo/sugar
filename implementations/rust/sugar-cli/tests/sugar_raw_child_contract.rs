use std::fs;
use std::path::{Path, PathBuf};

use syn::spanned::Spanned;
use syn::{Fields, GenericArgument, Item, PathArguments, Type};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("sugar-cli lives under implementations/rust/sugar-cli")
        .to_path_buf()
}

#[derive(Clone, Copy)]
struct PinnedField {
    item: &'static str,
    field: &'static str,
    replacement_plan: &'static str,
}

const PINNED_FIELDS: &[PinnedField] = &[
    PinnedField {
        item: "IntersperseSeparator",
        field: "expr",
        replacement_plan: "split into explicit separator domains: intersperse(sep) owns a constructed SugarBody<TermFloor> separator value, while intersperse_with(f) owns a named generator/callback wrapper",
    },
    PinnedField {
        item: "ResultInspectSugar",
        field: "callback",
        replacement_plan: "rename/wrap as ResultInspectCallback or callback_source so the field is an effect witness, not a reducible child body",
    },
    PinnedField {
        item: "IterTerminalReceiver",
        field: "source",
        replacement_plan: "rename to source_expr/receiver_source and keep the paired SugarBody<CompositeFloor> as the actual child body",
    },
    PinnedField {
        item: "PeekableLiteralAssertionSugar",
        field: "receiver",
        replacement_plan: "replace any raw receiver with a sequence SugarBody<CompositeFloor>; provenance must be named source_expr if it exists",
    },
];

#[test]
fn sugar_raw_expr_storage_names_the_child_or_the_provenance() {
    let root = repo_root();
    let sugar_dir = root
        .join("implementations")
        .join("rust")
        .join("sugar-lift-rust-tests")
        .join("src")
        .join("sugar");

    let mut offenders = Vec::new();
    for pinned in PINNED_FIELDS {
        let Some(found) = find_field(&sugar_dir, pinned.item, pinned.field) else {
            continue;
        };
        if raw_expr_type(&found.ty) {
            offenders.push(format!(
                "{}:{}: {}.{} stores raw `{}`\n  replacement_plan: {}",
                found.rel_path.display(),
                found.line,
                pinned.item,
                pinned.field,
                found.ty_src.trim(),
                pinned.replacement_plan
            ));
        }
    }

    assert!(
        offenders.is_empty(),
        "Sugar construction must hold typed child bodies. Raw `Expr` may remain only when \
         the field name/type says provenance, source, token/site, or effect witness. \
         R.sugar_raw_child_storage.current = {}\n{}",
        offenders.len(),
        offenders.join("\n")
    );
}

#[derive(Clone, Copy)]
struct LateFunctionInlineSite {
    path: &'static str,
    owner: &'static str,
    required_patterns: &'static [&'static str],
    replacement_plan: &'static str,
}

const LATE_FUNCTION_INLINE_SITES: &[LateFunctionInlineSite] = &[
    LateFunctionInlineSite {
        path: "implementations/rust/sugar-lift-rust-tests/src/sugar/bool_predicate.rs",
        owner: "BoolPredicateFunction",
        required_patterns: &[
            "func: Expr",
            ".value\n            .as_ref()",
            "value.to_expr()",
            "ctx.try_inline_value_call(&self.func",
        ],
        replacement_plan: "construct a typed BoolPredicateFunctionBody at build time: resolve the visible function, bind its parameter to a curry term, build the returned expression as SugarBody<BoolFloor>, and curry sequence floor terms through that body in desugar",
    },
    LateFunctionInlineSite {
        path: "implementations/rust/sugar-lift-rust-tests/src/sugar/try_from_fn.rs",
        owner: "TryFromFnSugar",
        required_patterns: &[
            "func: Expr",
            "ConstVal::Int(i128::try_from(index).ok()?).to_expr()",
            "resolve_value_call_inline(func, &[arg]",
        ],
        replacement_plan: "construct a typed TryFromFnBody at recognition: resolve the visible function, bind its index parameter to a curry term, build the returned Option expression as SugarBody<TermFloor>, then curry index terms and read opt:some/opt:none floors",
    },
];

#[test]
fn path_function_callbacks_construct_typed_bodies_before_desugar() {
    let root = repo_root();
    let mut offenders = Vec::new();
    for site in LATE_FUNCTION_INLINE_SITES {
        let path = root.join(site.path);
        let source = fs::read_to_string(&path).expect("read path-function callback sugar source");
        if site
            .required_patterns
            .iter()
            .all(|pattern| source.contains(pattern))
        {
            offenders.push(format!(
                "{}: {} stores a raw path function and rematerializes element source syntax during desugar\n  replacement_plan: {}",
                site.path, site.owner, site.replacement_plan
            ));
        }
    }

    assert!(
        offenders.is_empty(),
        "Path-function callback sugars must construct typed function bodies before desugar. \
         Literal const-eval may be a fast path, but the hard path must ask for each child \
         element's floor term and curry it through the typed function body; it must not \
         rebuild source syntax from sequence elements and late-inline the function. \
         R.path_function_callback_late_inline.current = {}\n{}",
        offenders.len(),
        offenders.join("\n")
    );
}

struct FoundField {
    rel_path: PathBuf,
    line: usize,
    ty: Type,
    ty_src: String,
}

fn find_field(dir: &Path, item_name: &str, field_name: &str) -> Option<FoundField> {
    let root = repo_root();
    let entries = fs::read_dir(dir).expect("read sugar dir");
    for entry in entries {
        let path = entry.expect("sugar dir entry").path();
        if path.extension().and_then(|ext| ext.to_str()) != Some("rs") {
            continue;
        }
        let source = fs::read_to_string(&path).expect("read sugar source");
        let file = syn::parse_file(&source).expect("parse sugar source");
        for item in file.items {
            let Item::Struct(item_struct) = item else {
                continue;
            };
            if item_struct.ident != item_name {
                continue;
            }
            let Fields::Named(fields) = item_struct.fields else {
                continue;
            };
            for field in fields.named {
                let Some(ident) = field.ident else {
                    continue;
                };
                if ident != field_name {
                    continue;
                }
                let ty_src = source_slice(&source, field.ty.span());
                let line = line_for_span(&source, field.ty.span());
                return Some(FoundField {
                    rel_path: path.strip_prefix(&root).unwrap_or(&path).to_path_buf(),
                    line,
                    ty: field.ty,
                    ty_src,
                });
            }
        }
    }
    None
}

fn raw_expr_type(ty: &Type) -> bool {
    match ty {
        Type::Path(path) => path.path.segments.iter().any(|segment| {
            segment.ident == "Expr" || path_arguments_contain_raw_expr(&segment.arguments)
        }),
        Type::Reference(reference) => raw_expr_type(&reference.elem),
        Type::Paren(paren) => raw_expr_type(&paren.elem),
        Type::Group(group) => raw_expr_type(&group.elem),
        Type::Tuple(tuple) => tuple.elems.iter().any(raw_expr_type),
        Type::Array(array) => raw_expr_type(&array.elem),
        _ => false,
    }
}

fn path_arguments_contain_raw_expr(arguments: &PathArguments) -> bool {
    match arguments {
        PathArguments::AngleBracketed(args) => args.args.iter().any(|arg| match arg {
            GenericArgument::Type(ty) => raw_expr_type(ty),
            _ => false,
        }),
        PathArguments::Parenthesized(args) => {
            args.inputs.iter().any(raw_expr_type)
                || match &args.output {
                    syn::ReturnType::Type(_, ty) => raw_expr_type(ty),
                    syn::ReturnType::Default => false,
                }
        }
        PathArguments::None => false,
    }
}

fn line_for_span(source: &str, span: proc_macro2::Span) -> usize {
    let start = span.start();
    if start.line > 0 {
        return start.line;
    }
    source
        .lines()
        .position(|line| line.contains("Expr"))
        .unwrap_or(0)
        + 1
}

fn source_slice(source: &str, span: proc_macro2::Span) -> String {
    let start = span.start();
    let end = span.end();
    if start.line == 0 || end.line == 0 || start.line != end.line {
        return "Expr".to_string();
    }
    let Some(line) = source.lines().nth(start.line - 1) else {
        return "Expr".to_string();
    };
    line.chars()
        .skip(start.column)
        .take(end.column.saturating_sub(start.column))
        .collect()
}
