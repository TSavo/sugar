// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Gate-parity instruments (#2998).
//
// These tests are policy gates, not drains. They make two architectural rules
// executable for the Rust lift kit:
// - lift crates do not invoke solvers;
// - contract construction stays in explicitly sanctioned chokepoint modules.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use quote::ToTokens;
use syn::spanned::Spanned;

const SANCTIONED_CONTRACT_CONSTRUCTOR_MODULES: &[SanctionedModule] = &[
    SanctionedModule {
        file: "implementations/rust/libsugar/src/core/primitives.rs",
        reason: "core compose primitive materializes composed function contracts",
    },
    SanctionedModule {
        file: "implementations/rust/libsugar/src/core/stubs.rs",
        reason: "core stub domain projects terms into placeholder function contracts",
    },
    SanctionedModule {
        file: "implementations/rust/libsugar/src/core/types.rs",
        reason: "core canonical type module is the shared Contract memento constructor",
    },
    SanctionedModule {
        file: "implementations/rust/sugar-cli/src/kit_path/lift_plugin.rs",
        reason: "core lift plugin mints the lift response contract for plugin sessions (relocated from libsugar/src/core/lift_plugin.rs by #evict-2-liftplugin-pathexec)",
    },
    SanctionedModule {
        file: "implementations/rust/sugar-walk/src/bin/walk_emit.rs",
        reason: "walk emit CLI builds source contracts for explicit contract-mode output",
    },
    SanctionedModule {
        file: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        reason: "walk RPC emits function, totality, manifest, and builtin contract entries",
    },
    SanctionedModule {
        file: "implementations/rust/sugar-walk/src/bind.rs",
        reason: "bind kit mints the bind response contract for term-document payloads (relocated from libsugar/src/core/bind.rs by #evict-1-bind)",
    },
    SanctionedModule {
        file: "implementations/rust/sugar-walk/src/contract.rs",
        reason: "canonical AST-to-FunctionContractMemento builder",
    },
    SanctionedModule {
        file: "implementations/rust/sugar-walk/src/envelope.rs",
        reason: "substrate contract-envelope mint_args and mint_contract wrapper",
    },
    SanctionedModule {
        file: "implementations/rust/sugar-walk/src/type_decl.rs",
        reason: "type-declaration lift synthesizes impl-method function contracts",
    },
];

#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd)]
struct SanctionedModule {
    file: &'static str,
    reason: &'static str,
}

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
struct SourceSite {
    file: String,
    line: usize,
    pattern: String,
    snippet: String,
}

#[derive(Debug, Clone)]
struct ScannedFile {
    rel: String,
    raw_lines: Vec<String>,
    stripped_lines: Vec<String>,
    cfg_test_ranges: Vec<(usize, usize)>,
}

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-walk has rust workspace parent")
        .parent()
        .expect("rust workspace has implementations parent")
        .parent()
        .expect("implementations has repo root parent")
        .to_path_buf()
}

fn lift_source_roots(root: &Path) -> Vec<PathBuf> {
    vec![
        root.join("implementations/rust/sugar-walk/src"),
        root.join("implementations/rust/sugar-lift/src"),
        root.join("implementations/rust/sugar-lift-contracts/src"),
        // Relocated from `libsugar/src/core/lift_plugin.rs` to `sugar-cli`
        // by #evict-2-liftplugin-pathexec.
        root.join("implementations/rust/sugar-cli/src/kit_path/lift_plugin.rs"),
    ]
}

fn rust_files_under(root: &Path) -> Result<Vec<PathBuf>, String> {
    if root.is_file() {
        return Ok(vec![root.to_path_buf()]);
    }
    if !root.is_dir() {
        return Err(format!("source root missing: {}", root.display()));
    }
    let mut files = Vec::new();
    collect_rust_files(root, &mut files)?;
    files.sort();
    Ok(files)
}

fn collect_rust_files(dir: &Path, files: &mut Vec<PathBuf>) -> Result<(), String> {
    for entry in fs::read_dir(dir).map_err(|err| format!("read dir {}: {err}", dir.display()))? {
        let entry = entry.map_err(|err| format!("read dir entry {}: {err}", dir.display()))?;
        let path = entry.path();
        if path.is_dir() {
            if path
                .components()
                .any(|component| component.as_os_str() == "tests")
            {
                continue;
            }
            collect_rust_files(&path, files)?;
        } else if path.extension().and_then(|ext| ext.to_str()) == Some("rs") {
            files.push(path);
        }
    }
    Ok(())
}

fn scan_files(root: &Path, roots: &[PathBuf]) -> Result<Vec<ScannedFile>, String> {
    let mut scanned = Vec::new();
    for source_root in roots {
        for path in rust_files_under(source_root)? {
            let rel = path
                .strip_prefix(root)
                .map_err(|err| format!("strip {}: {err}", path.display()))?
                .to_string_lossy()
                .replace('\\', "/");
            let source = fs::read_to_string(&path)
                .map_err(|err| format!("read {}: {err}", path.display()))?;
            let parsed = syn::parse_file(&source).map_err(|err| format!("parse {rel}: {err}"))?;
            scanned.push(ScannedFile {
                rel,
                raw_lines: source.lines().map(str::to_string).collect(),
                stripped_lines: strip_comments(&source)
                    .lines()
                    .map(str::to_string)
                    .collect(),
                cfg_test_ranges: cfg_test_ranges(&parsed),
            });
        }
    }
    scanned.sort_by(|left, right| left.rel.cmp(&right.rel));
    Ok(scanned)
}

fn strip_comments(source: &str) -> String {
    let chars = source.chars().collect::<Vec<_>>();
    let mut out = String::with_capacity(source.len());
    let mut i = 0;
    let mut block_depth = 0usize;
    let mut quote: Option<char> = None;
    let mut escaped = false;

    while i < chars.len() {
        let ch = chars[i];
        let next = chars.get(i + 1).copied();

        if block_depth > 0 {
            if ch == '/' && next == Some('*') {
                out.push(' ');
                out.push(' ');
                block_depth += 1;
                i += 2;
            } else if ch == '*' && next == Some('/') {
                out.push(' ');
                out.push(' ');
                block_depth -= 1;
                i += 2;
            } else {
                out.push(if ch == '\n' { '\n' } else { ' ' });
                i += 1;
            }
            continue;
        }

        if let Some(active_quote) = quote {
            out.push(ch);
            if escaped {
                escaped = false;
            } else if ch == '\\' {
                escaped = true;
            } else if ch == active_quote {
                quote = None;
            }
            i += 1;
            continue;
        }

        match (ch, next) {
            ('/', Some('/')) => {
                out.push(' ');
                out.push(' ');
                i += 2;
                while i < chars.len() && chars[i] != '\n' {
                    out.push(' ');
                    i += 1;
                }
            }
            ('/', Some('*')) => {
                out.push(' ');
                out.push(' ');
                block_depth = 1;
                i += 2;
            }
            ('"', _) => {
                quote = Some(ch);
                out.push(ch);
                i += 1;
            }
            _ => {
                out.push(ch);
                i += 1;
            }
        }
    }

    out
}

fn cfg_test_ranges(file: &syn::File) -> Vec<(usize, usize)> {
    let mut ranges = Vec::new();
    collect_cfg_test_item_ranges(&file.items, &mut ranges);
    ranges.sort();
    ranges
}

fn collect_cfg_test_item_ranges(items: &[syn::Item], ranges: &mut Vec<(usize, usize)>) {
    for item in items {
        if attrs_include_cfg_test(item_attrs(item)) {
            push_span_range(item.span(), ranges);
            continue;
        }
        if let syn::Item::Mod(module) = item {
            if let Some((_, items)) = &module.content {
                collect_cfg_test_item_ranges(items, ranges);
            }
        }
    }
}

fn item_attrs(item: &syn::Item) -> &[syn::Attribute] {
    match item {
        syn::Item::Const(item) => &item.attrs,
        syn::Item::Enum(item) => &item.attrs,
        syn::Item::ExternCrate(item) => &item.attrs,
        syn::Item::Fn(item) => &item.attrs,
        syn::Item::ForeignMod(item) => &item.attrs,
        syn::Item::Impl(item) => &item.attrs,
        syn::Item::Macro(item) => &item.attrs,
        syn::Item::Mod(item) => &item.attrs,
        syn::Item::Static(item) => &item.attrs,
        syn::Item::Struct(item) => &item.attrs,
        syn::Item::Trait(item) => &item.attrs,
        syn::Item::TraitAlias(item) => &item.attrs,
        syn::Item::Type(item) => &item.attrs,
        syn::Item::Union(item) => &item.attrs,
        syn::Item::Use(item) => &item.attrs,
        _ => &[],
    }
}

fn attrs_include_cfg_test(attrs: &[syn::Attribute]) -> bool {
    attrs.iter().any(|attr| {
        attr.path().is_ident("cfg") && attr.meta.to_token_stream().to_string().contains("test")
    })
}

fn push_span_range(span: proc_macro2::Span, ranges: &mut Vec<(usize, usize)>) {
    let start = span.start().line;
    let end = span.end().line.max(start);
    ranges.push((start, end));
}

fn line_in_ranges(line: usize, ranges: &[(usize, usize)]) -> bool {
    ranges
        .iter()
        .any(|(start, end)| (*start..=*end).contains(&line))
}

fn is_sanctioned(raw_lines: &[String], line: usize) -> bool {
    line.checked_sub(2)
        .and_then(|idx| raw_lines.get(idx))
        .is_some_and(|line| line.contains("sugar-audit: not-mine("))
}

fn push_site(
    sites: &mut Vec<SourceSite>,
    file: &ScannedFile,
    line: usize,
    pattern: &str,
    snippet: &str,
) {
    if is_sanctioned(&file.raw_lines, line) {
        return;
    }
    sites.push(SourceSite {
        file: file.rel.clone(),
        line,
        pattern: pattern.to_string(),
        snippet: snippet.trim().to_string(),
    });
}

fn scan_solver_ownership(root: &Path) -> Result<Vec<SourceSite>, String> {
    let files = scan_files(root, &lift_source_roots(root))?;
    let mut sites = Vec::new();
    for file in &files {
        scan_solver_lines(file, &mut sites);
    }
    sites.sort();
    Ok(sites)
}

fn scan_solver_lines(file: &ScannedFile, sites: &mut Vec<SourceSite>) {
    for (idx, line) in file.stripped_lines.iter().enumerate() {
        let line_no = idx + 1;
        if line_in_ranges(line_no, &file.cfg_test_ranges) {
            continue;
        }
        for pattern in solver_patterns(line) {
            push_site(sites, file, line_no, pattern, line);
        }
    }
}

fn solver_patterns(line: &str) -> Vec<&'static str> {
    let mut patterns = Vec::new();
    if line.contains("Solver::") {
        patterns.push("Solver::");
    }
    if line.contains("check_sat") {
        patterns.push("check_sat");
    }
    if line.contains("check-sat") {
        patterns.push("check-sat");
    }
    for seat in ["z3", "cvc5", "vampire", "bitwuzla", "maude"] {
        if contains_word(line, seat) {
            patterns.push(seat);
        }
    }
    patterns
}

fn contains_word(line: &str, needle: &str) -> bool {
    let mut start = 0;
    while let Some(offset) = line[start..].find(needle) {
        let absolute = start + offset;
        let before = line[..absolute].chars().next_back();
        let after = line[absolute + needle.len()..].chars().next();
        if !before.is_some_and(is_ident_char) && !after.is_some_and(is_ident_char) {
            return true;
        }
        start = absolute + needle.len();
    }
    false
}

fn is_ident_char(ch: char) -> bool {
    ch == '_' || ch.is_ascii_alphanumeric()
}

fn scan_contract_constructors(root: &Path) -> Result<Vec<SourceSite>, String> {
    let roots = vec![
        root.join("implementations/rust/sugar-walk/src"),
        root.join("implementations/rust/libsugar/src/core"),
        // Single-file root, not a directory: `lift_plugin.rs` relocated out of
        // `libsugar/src/core` to `sugar-cli` (#evict-2-liftplugin-pathexec).
        // Scanning only this one file (not all of sugar-cli/src) keeps this
        // gate's scope as narrow as before the move; silently losing
        // visibility into its `lift_response_contract(` mint site would be
        // the exact "silent loss" this gate exists to forbid.
        root.join("implementations/rust/sugar-cli/src/kit_path/lift_plugin.rs"),
    ];
    let files = scan_files(root, &roots)?;
    let mut sites = Vec::new();
    for file in &files {
        scan_contract_constructor_lines(file, &mut sites);
    }
    sites.sort();
    Ok(sites)
}

fn scan_contract_constructor_lines(file: &ScannedFile, sites: &mut Vec<SourceSite>) {
    for (idx, line) in file.stripped_lines.iter().enumerate() {
        let line_no = idx + 1;
        if line_in_ranges(line_no, &file.cfg_test_ranges) {
            continue;
        }
        for pattern in contract_constructor_patterns(line) {
            push_site(sites, file, line_no, pattern, line);
        }
    }
}

fn contract_constructor_patterns(line: &str) -> Vec<&'static str> {
    let mut patterns = Vec::new();
    if is_struct_literal_line(line, "FunctionContractMemento") {
        patterns.push("FunctionContractMemento {");
    }
    if is_struct_literal_line(line, "Contract") {
        patterns.push("Contract {");
    }
    if is_struct_literal_line(line, "MintContractArgs") {
        patterns.push("MintContractArgs {");
    }
    if is_struct_literal_line(line, "MintBridgeArgs") {
        patterns.push("MintBridgeArgs {");
    }

    const SUBSTRINGS: &[&str] = &[
        "build_function_contract(",
        "build_function_contract_with_file(",
        "build_function_contract_with_file_and_post_override(",
        "wrap_function_contract(",
        "wrap_function_contract_cached(",
        "mint_args(",
        "mint_contract(",
        "mint_bridge(",
        "memento_from_parts(",
        "bind_response_contract(",
        "lift_response_contract(",
        "composed_to_contract(",
        "pure_identity_contract(",
        "\"kind\": \"contract\"",
        "\"kind\": \"function-contract\"",
    ];
    patterns.extend(
        SUBSTRINGS
            .iter()
            .copied()
            .filter(|pattern| line.contains(pattern)),
    );
    patterns
}

fn is_struct_literal_line(line: &str, type_name: &str) -> bool {
    let trimmed = line.trim_start();
    trimmed.starts_with(&format!("{type_name} {{"))
        || trimmed.contains(&format!("= {type_name} {{"))
        || trimmed.contains(&format!("({type_name} {{"))
        || trimmed.contains(&format!("Ok({type_name} {{"))
}

fn modules_with_contract_constructors(sites: &[SourceSite]) -> Vec<String> {
    sites
        .iter()
        .map(|site| site.file.clone())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

fn expected_contract_constructor_modules() -> Vec<String> {
    SANCTIONED_CONTRACT_CONSTRUCTOR_MODULES
        .iter()
        .map(|module| module.file.to_string())
        .collect()
}

fn format_sites(sites: &[SourceSite]) -> String {
    let mut grouped = BTreeMap::<&str, Vec<&SourceSite>>::new();
    for site in sites {
        grouped.entry(&site.file).or_default().push(site);
    }
    let mut out = String::new();
    for (file, sites) in grouped {
        out.push_str(file);
        out.push('\n');
        for site in sites {
            out.push_str(&format!(
                "  line {} [{}]: {}\n",
                site.line, site.pattern, site.snippet
            ));
        }
    }
    out
}

fn pasteable_sanctioned_modules(observed: &[String]) -> String {
    let mut out = String::new();
    out.push_str("const SANCTIONED_CONTRACT_CONSTRUCTOR_MODULES: &[SanctionedModule] = &[\n");
    for file in observed {
        out.push_str(&format!(
            "    SanctionedModule {{ file: {:?}, reason: \"<reason>\" }},\n",
            file
        ));
    }
    out.push_str("];\n");
    out
}

fn scanned_file_from_source(rel: &str, source: &str) -> ScannedFile {
    let parsed = syn::parse_file(source).expect("synthetic source parses");
    ScannedFile {
        rel: rel.to_string(),
        raw_lines: source.lines().map(str::to_string).collect(),
        stripped_lines: strip_comments(source).lines().map(str::to_string).collect(),
        cfg_test_ranges: cfg_test_ranges(&parsed),
    }
}

#[test]
fn solver_scanner_detects_synthetic_solver_invocation() {
    let file = scanned_file_from_source(
        "synthetic.rs",
        r#"
        fn production() {
            let _child = std::process::Command::new("z3").spawn();
            let _script = "(check-sat)";
            let _solver = Solver::new();
        }

        #[cfg(test)]
        mod tests {
            fn ignored() {
                let _child = std::process::Command::new("cvc5").spawn();
            }
        }
        "#,
    );
    let mut sites = Vec::new();
    scan_solver_lines(&file, &mut sites);

    assert_eq!(
        sites
            .iter()
            .map(|site| site.pattern.as_str())
            .collect::<Vec<_>>(),
        ["z3", "check-sat", "Solver::"]
    );
}

#[test]
fn lift_ownership_gate_has_no_solver_invocations() {
    let sites = scan_solver_ownership(&repo_root()).expect("scan lift ownership gate");

    assert!(
        sites.is_empty(),
        "solver invocation patterns are forbidden in lift-owned crates; move solver work to verifier/CLI dispatch or mark a true false-positive with `// sugar-audit: not-mine(<reason>)`\n{}",
        format_sites(&sites)
    );
}

#[test]
fn contract_constructor_scanner_detects_synthetic_minting_site() {
    let file = scanned_file_from_source(
        "synthetic.rs",
        r#"
        fn production() {
            let _contract = FunctionContractMemento {
                fn_name: "f".to_string(),
            };
            let _wrapped = mint_contract(&args);
        }

        #[cfg(test)]
        mod tests {
            fn ignored() {
                let _contract = Contract {
                    fn_name: "fixture".to_string(),
                };
            }
        }
        "#,
    );
    let mut sites = Vec::new();
    scan_contract_constructor_lines(&file, &mut sites);

    assert_eq!(
        sites
            .iter()
            .map(|site| site.pattern.as_str())
            .collect::<Vec<_>>(),
        ["FunctionContractMemento {", "mint_contract("]
    );
}

#[test]
fn contract_construction_stays_inside_sanctioned_modules() {
    let sites = scan_contract_constructors(&repo_root()).expect("scan contract constructors");
    let observed = modules_with_contract_constructors(&sites);
    let expected = expected_contract_constructor_modules();

    assert_eq!(
        observed,
        expected,
        "contract constructor modules changed; move new minting behind an existing chokepoint or extend SANCTIONED_CONTRACT_CONSTRUCTOR_MODULES with a one-line reason in the same PR\n\nSites:\n{}\nPasteable module list:\n{}",
        format_sites(&sites),
        pasteable_sanctioned_modules(&observed)
    );
}
