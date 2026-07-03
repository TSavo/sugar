use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Copy)]
struct CodeLine<'a> {
    number: usize,
    code: &'a str,
}

#[derive(Debug, Clone)]
struct Offender {
    axis: &'static str,
    path: String,
    line: usize,
    symbol: String,
    replacement: &'static str,
    line_count: usize,
}

#[test]
fn source_fragment_delta_epsilon_frontier_matches_expected_counts() {
    let offenders = collect_offenders();
    let observed = offender_counts(&offenders);
    let expected = expected_frontier_counts();

    assert_eq!(
        observed,
        expected,
        "SourceFragment delta-epsilon frontier moved.\n\
         This is the #2927 SourceFragment migration instrument: delete expected \
         rows when a drain removes offenders, and treat new rows as regression \
         alarms.\n\n\
         observed R = {}\n\
         expected R = {}\n\n{}",
        render_count_map(&observed),
        render_count_map(&expected),
        render_offenders(&offenders)
    );
}

#[test]
#[ignore = "red-by-design until the #2927 SourceFragment migration reaches stable zero"]
fn source_fragment_is_the_only_raw_ast_boundary() {
    let offenders = collect_offenders();

    assert!(
        offenders.is_empty(),
        "SourceFragment delta-epsilon R vector is not stable zero.\n\
         Law: SourceFragment is the only production API by which Rust sugar talks \
         to the AST. Sugar recognizers, helpers, floors, and reports must ask \
         SourceFragment for typed fragments, literal facts, source loci, and \
         grammar/accounting shape; raw syn access belongs behind that one door.\n\n\
         R = {}\n\n{}",
        render_counts(&offenders),
        render_offenders(&offenders)
    );
}

fn collect_offenders() -> Vec<Offender> {
    let mut line_offenders = Vec::new();
    for path in sugar_sources() {
        let rel = relative_to_manifest(&path);
        if rel == "src/sugar/source_fragment.rs" {
            continue;
        }
        let src = fs::read_to_string(&path)
            .unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
        line_offenders.extend(raw_ast_boundary_offenders(&rel, &src));
    }
    let mut offenders = collapse_by_file_axis(line_offenders);
    offenders.sort_by_key(|offender| {
        (
            offender.axis,
            offender.path.clone(),
            offender.line,
            offender.symbol.clone(),
        )
    });
    offenders
}

fn expected_frontier_counts() -> BTreeMap<&'static str, (usize, usize)> {
    BTreeMap::from([
        ("raw_ast_signature", (141, 1132)),
        ("raw_ast_variant_pattern", (117, 1934)),
        ("raw_syn_import", (124, 124)),
        ("source_fragment_escape_accessor", (94, 153)),
    ])
}

fn manifest_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn sugar_sources() -> Vec<PathBuf> {
    let mut out = Vec::new();
    collect_rs_files(&manifest_dir().join("src/sugar"), &mut out);
    out.sort();
    out
}

fn collect_rs_files(dir: &Path, out: &mut Vec<PathBuf>) {
    for entry in fs::read_dir(dir).unwrap_or_else(|err| panic!("read {}: {err}", dir.display())) {
        let entry = entry.expect("read directory entry");
        let path = entry.path();
        let file_type = entry.file_type().expect("read directory entry type");
        if file_type.is_dir() {
            collect_rs_files(&path, out);
        } else if path.extension().is_some_and(|ext| ext == "rs") {
            out.push(path);
        }
    }
}

fn relative_to_manifest(path: &Path) -> String {
    path.strip_prefix(manifest_dir())
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/")
}

fn raw_ast_boundary_offenders(path: &str, src: &str) -> Vec<Offender> {
    let mut offenders = Vec::new();
    for line in production_lines(src) {
        if is_comment_or_empty(line.code) {
            continue;
        }
        if raw_syn_import(line.code) {
            offenders.push(offender(
                "raw_syn_import",
                path,
                line,
                "move the imported AST inspection behind a SourceFragment accessor",
            ));
        }
        if raw_escape_accessor(line.code) {
            offenders.push(offender(
                "source_fragment_escape_accessor",
                path,
                line,
                "replace as_expr/as_stmt/as_item with a typed SourceFragment method",
            ));
        }
        if raw_variant_pattern(line.code) {
            offenders.push(offender(
                "raw_ast_variant_pattern",
                path,
                line,
                "move Expr/Stmt/Item variant matching behind SourceFragment",
            ));
        }
        if raw_ast_signature(line.code) {
            offenders.push(offender(
                "raw_ast_signature",
                path,
                line,
                "pass or return SourceFragment/SugarBody instead of raw syn nodes",
            ));
        }
    }
    offenders
}

fn offender(
    axis: &'static str,
    path: &str,
    line: CodeLine<'_>,
    replacement: &'static str,
) -> Offender {
    Offender {
        axis,
        path: path.to_string(),
        line: line.number,
        symbol: line.code.trim().to_string(),
        replacement,
        line_count: 1,
    }
}

fn collapse_by_file_axis(offenders: Vec<Offender>) -> Vec<Offender> {
    let mut grouped = BTreeMap::<(&'static str, String), Offender>::new();
    for offender in offenders {
        let key = (offender.axis, offender.path.clone());
        grouped
            .entry(key)
            .and_modify(|entry| {
                entry.line_count += 1;
                if offender.line < entry.line {
                    entry.line = offender.line;
                    entry.symbol = offender.symbol.clone();
                    entry.replacement = offender.replacement;
                }
            })
            .or_insert(offender);
    }
    grouped.into_values().collect()
}

fn raw_syn_import(line: &str) -> bool {
    let trimmed = line.trim_start();
    trimmed.starts_with("use syn::")
        && RAW_AST_TYPE_TOKENS
            .iter()
            .any(|token| contains_word(line, token))
}

fn raw_escape_accessor(line: &str) -> bool {
    ["as_expr()", "as_stmt()", "as_item()"]
        .iter()
        .any(|needle| line.contains(needle))
}

fn raw_variant_pattern(line: &str) -> bool {
    RAW_AST_VARIANT_PREFIXES
        .iter()
        .any(|prefix| line.contains(prefix))
}

fn raw_ast_signature(line: &str) -> bool {
    RAW_AST_TYPE_TOKENS
        .iter()
        .any(|token| raw_type_signature_fragment(line, token))
}

fn raw_type_signature_fragment(line: &str, token: &str) -> bool {
    [
        format!(": &{token}"),
        format!(": &'_ {token}"),
        format!(": {token}"),
        format!("-> &{token}"),
        format!("-> Option<&{token}>"),
        format!("-> Option<{token}>"),
        format!("Vec<&{token}>"),
        format!("Vec<{token}>"),
        format!("Box<{token}>"),
    ]
    .iter()
    .any(|fragment| line.contains(fragment))
}

fn contains_word(line: &str, word: &str) -> bool {
    let mut start = 0;
    while let Some(rel) = line[start..].find(word) {
        let idx = start + rel;
        let before = line[..idx].chars().next_back();
        let after = line[idx + word.len()..].chars().next();
        if !before.is_some_and(is_ident_char) && !after.is_some_and(is_ident_char) {
            return true;
        }
        start = idx + word.len();
    }
    false
}

fn is_ident_char(ch: char) -> bool {
    ch == '_' || ch.is_ascii_alphanumeric()
}

fn is_comment_or_empty(line: &str) -> bool {
    let trimmed = line.trim_start();
    trimmed.is_empty()
        || trimmed.starts_with("//")
        || trimmed.starts_with("///")
        || trimmed.starts_with("//!")
        || trimmed.starts_with('*')
}

fn production_lines(text: &str) -> Vec<CodeLine<'_>> {
    let mut out = Vec::new();
    let mut pending_cfg_test = false;
    let mut test_depth = None::<i32>;

    for (idx, raw) in text.lines().enumerate() {
        let number = idx + 1;
        let trimmed = raw.trim_start();
        if trimmed.starts_with("#[cfg(test)]") {
            pending_cfg_test = true;
            continue;
        }
        if pending_cfg_test && (trimmed.starts_with("mod ") || trimmed.starts_with("fn ")) {
            let mut depth = raw.matches('{').count() as i32 - raw.matches('}').count() as i32;
            if depth <= 0 && raw.contains('{') {
                pending_cfg_test = false;
                continue;
            }
            if depth == 0 {
                depth = 1;
            }
            test_depth = Some(depth);
            pending_cfg_test = false;
            continue;
        }
        pending_cfg_test = false;
        if let Some(depth) = &mut test_depth {
            *depth += raw.matches('{').count() as i32;
            *depth -= raw.matches('}').count() as i32;
            if *depth <= 0 {
                test_depth = None;
            }
            continue;
        }
        out.push(CodeLine { number, code: raw });
    }

    out
}

fn render_counts(offenders: &[Offender]) -> String {
    if offenders.is_empty() {
        return "{}".to_string();
    }
    render_count_map(&offender_counts(offenders))
}

fn offender_counts(offenders: &[Offender]) -> BTreeMap<&'static str, (usize, usize)> {
    let mut counts = BTreeMap::<&'static str, (usize, usize)>::new();
    for offender in offenders {
        let entry = counts.entry(offender.axis).or_default();
        entry.0 += 1;
        entry.1 += offender.line_count;
    }
    counts
}

fn render_count_map(counts: &BTreeMap<&'static str, (usize, usize)>) -> String {
    if counts.is_empty() {
        return "{}".to_string();
    }
    let parts: Vec<String> = counts
        .iter()
        .map(|(axis, (files, lines))| format!("{axis}: {files} files / {lines} lines"))
        .collect();
    format!("{{{}}}", parts.join(", "))
}

fn render_offenders(offenders: &[Offender]) -> String {
    offenders
        .iter()
        .map(|offender| {
            format!(
                "{}:{} [{}; {} line(s)]\n  first illegal: {}\n  fix: {}",
                offender.path,
                offender.line,
                offender.axis,
                offender.line_count,
                offender.symbol,
                offender.replacement
            )
        })
        .collect::<Vec<_>>()
        .join("\n")
}

const RAW_AST_VARIANT_PREFIXES: &[&str] = &[
    "Expr::",
    "Stmt::",
    "Item::",
    "ImplItem::",
    "Pat::",
    "Type::",
    "syn::Expr::",
    "syn::Stmt::",
    "syn::Item::",
    "syn::ImplItem::",
    "syn::Pat::",
    "syn::Type::",
];

const RAW_AST_TYPE_TOKENS: &[&str] = &[
    "Block",
    "Expr",
    "ExprArray",
    "ExprAssign",
    "ExprBinary",
    "ExprBlock",
    "ExprCall",
    "ExprCast",
    "ExprClosure",
    "ExprField",
    "ExprForLoop",
    "ExprIf",
    "ExprIndex",
    "ExprLit",
    "ExprLoop",
    "ExprMacro",
    "ExprMatch",
    "ExprMethodCall",
    "ExprPath",
    "ExprRange",
    "ExprReference",
    "ExprRepeat",
    "ExprStruct",
    "ExprTuple",
    "ExprUnary",
    "ExprWhile",
    "ImplItem",
    "Item",
    "Pat",
    "PatIdent",
    "Stmt",
    "Type",
];
