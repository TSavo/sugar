// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Shared vocabulary-totality audit helpers for the IR compiler backends.

#![allow(dead_code)]

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value as Json};

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum SymbolPosition {
    Atom,
    Ctor,
}

impl SymbolPosition {
    pub fn as_str(self) -> &'static str {
        match self {
            SymbolPosition::Atom => "atom",
            SymbolPosition::Ctor => "ctor",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct CorpusKey {
    pub position: SymbolPosition,
    pub name: String,
    pub arity: usize,
}

#[derive(Debug, Clone)]
pub struct CorpusSymbol {
    pub key: CorpusKey,
    pub examples: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct Corpus {
    pub symbols: Vec<CorpusSymbol>,
}

impl Corpus {
    pub fn total(&self) -> usize {
        self.symbols.len()
    }

    pub fn unique_names(&self) -> usize {
        self.symbols
            .iter()
            .map(|symbol| (symbol.key.position, symbol.key.name.as_str()))
            .collect::<BTreeSet<_>>()
            .len()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Disposition {
    Encoded,
    Allowlisted,
    Refused,
    RedPinned,
}

impl Disposition {
    fn as_str(self) -> &'static str {
        match self {
            Disposition::Encoded => "encoded",
            Disposition::Allowlisted => "allowlisted",
            Disposition::Refused => "refused",
            Disposition::RedPinned => "red-pinned",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct AuditRow {
    pub position: SymbolPosition,
    pub name: String,
    pub arity: usize,
    pub disposition: Disposition,
    pub detail: String,
    pub example: String,
}

#[derive(Debug, Clone)]
pub struct BackendReport {
    pub backend: &'static str,
    pub corpus_symbols: usize,
    pub corpus_unique_names: usize,
    pub rows: Vec<AuditRow>,
}

impl BackendReport {
    pub fn new(backend: &'static str, corpus: &Corpus, mut rows: Vec<AuditRow>) -> Self {
        rows.sort();
        Self {
            backend,
            corpus_symbols: corpus.total(),
            corpus_unique_names: corpus.unique_names(),
            rows,
        }
    }

    pub fn red_rows(&self) -> Vec<&AuditRow> {
        self.rows
            .iter()
            .filter(|row| row.disposition == Disposition::RedPinned)
            .collect()
    }

    pub fn red_keys(&self) -> Vec<(&str, &str, usize)> {
        self.rows
            .iter()
            .filter(|row| row.disposition == Disposition::RedPinned)
            .map(|row| (row.position.as_str(), row.name.as_str(), row.arity))
            .collect()
    }

    pub fn is_zero(&self) -> bool {
        self.red_rows().is_empty()
    }

    pub fn counts(&self) -> BTreeMap<&'static str, usize> {
        let mut counts = BTreeMap::from([
            ("allowlisted", 0),
            ("encoded", 0),
            ("red-pinned", 0),
            ("refused", 0),
        ]);
        for row in &self.rows {
            *counts.entry(row.disposition.as_str()).or_insert(0) += 1;
        }
        counts
    }

    pub fn to_json(&self) -> String {
        let rows = self
            .rows
            .iter()
            .map(|row| {
                json!({
                    "position": row.position.as_str(),
                    "name": row.name,
                    "arity": row.arity,
                    "disposition": row.disposition.as_str(),
                    "detail": row.detail,
                    "example": row.example,
                })
            })
            .collect::<Vec<_>>();
        serde_json::to_string_pretty(&json!({
            "backend": self.backend,
            "corpusSymbols": self.corpus_symbols,
            "corpusUniqueNames": self.corpus_unique_names,
            "isZero": self.is_zero(),
            "counts": self.counts(),
            "rows": rows,
        }))
        .expect("serialize vocabulary audit report")
    }

    pub fn to_expected_red_literal(&self, const_name: &str) -> String {
        let mut out = String::new();
        out.push_str(&format!(
            "const {const_name}: &[(&str, &str, usize)] = &[\n"
        ));
        for row in self.red_rows() {
            out.push_str(&format!(
                "    ({:?}, {:?}, {}),\n",
                row.position.as_str(),
                row.name,
                row.arity
            ));
        }
        out.push_str("];\n");
        out
    }
}

pub fn repo_root_from_manifest(manifest_dir: &str) -> PathBuf {
    PathBuf::from(manifest_dir)
        .parent()
        .expect("compiler crate has rust workspace parent")
        .parent()
        .expect("rust workspace has implementations parent")
        .parent()
        .expect("implementations has repo root parent")
        .to_path_buf()
}

pub fn collect_corpus(manifest_dir: &str) -> Result<Corpus, String> {
    let root = repo_root_from_manifest(manifest_dir);
    let mut found: BTreeMap<CorpusKey, BTreeSet<String>> = BTreeMap::new();
    for rel in [
        "conformance",
        "examples",
        "protocol/conformance",
        "implementations",
    ] {
        let dir = root.join(rel);
        if dir.is_dir() {
            collect_dir(&root, &dir, &mut found)?;
        }
    }
    let symbols = found
        .into_iter()
        .map(|(key, examples)| CorpusSymbol {
            key,
            examples: examples.into_iter().take(5).collect(),
        })
        .collect();
    Ok(Corpus { symbols })
}

pub fn formula_json_for(symbol: &CorpusSymbol) -> Json {
    match symbol.key.position {
        SymbolPosition::Atom => json!({
            "kind": "atomic",
            "name": symbol.key.name,
            "args": term_args(symbol.key.arity),
        }),
        SymbolPosition::Ctor => {
            let term = json!({
                "kind": "ctor",
                "name": symbol.key.name,
                "args": term_args(symbol.key.arity),
            });
            json!({
                "kind": "atomic",
                "name": "=",
                "args": [term.clone(), term],
            })
        }
    }
}

pub fn maude_json_for(symbol: &CorpusSymbol) -> Json {
    match symbol.key.position {
        SymbolPosition::Atom => formula_json_for(symbol),
        SymbolPosition::Ctor => {
            let term = json!({
                "kind": "ctor",
                "name": symbol.key.name,
                "args": maude_var_args(symbol.key.arity),
            });
            let arity = (0..symbol.key.arity).map(|_| "Elt").collect::<Vec<_>>();
            let variables = (0..symbol.key.arity)
                .map(|idx| json!({"name": maude_var_name(idx), "sort": "Elt"}))
                .collect::<Vec<_>>();
            json!({
                "kind": "equational_theory",
                "theory": {
                    "name": "vocabulary-audit",
                    "sorts": ["Elt"],
                    "operators": [{
                        "name": symbol.key.name,
                        "arity": arity,
                        "result": "Elt",
                    }],
                    "variables": variables,
                    "equations": [],
                },
                "obligation": {
                    "lhs": term.clone(),
                    "rhs": term,
                },
            })
        }
    }
}

pub fn audit_row(
    symbol: &CorpusSymbol,
    disposition: Disposition,
    detail: impl Into<String>,
) -> AuditRow {
    AuditRow {
        position: symbol.key.position,
        name: symbol.key.name.clone(),
        arity: symbol.key.arity,
        disposition,
        detail: detail.into(),
        example: symbol
            .examples
            .first()
            .cloned()
            .unwrap_or_else(|| "<unknown>".to_string()),
    }
}

fn collect_dir(
    root: &Path,
    dir: &Path,
    found: &mut BTreeMap<CorpusKey, BTreeSet<String>>,
) -> Result<(), String> {
    for entry in fs::read_dir(dir).map_err(|err| format!("read dir {}: {err}", dir.display()))? {
        let entry = entry.map_err(|err| format!("read dir entry {}: {err}", dir.display()))?;
        let path = entry.path();
        if path.is_dir() {
            if !skip_dir(&path) {
                collect_dir(root, &path, found)?;
            }
            continue;
        }
        if !read_for_corpus(&path) {
            continue;
        }
        let rel = path
            .strip_prefix(root)
            .map_err(|err| format!("strip {}: {err}", path.display()))?
            .to_string_lossy()
            .replace('\\', "/");
        let bytes = fs::read(&path).map_err(|err| format!("read {}: {err}", path.display()))?;
        let text = String::from_utf8_lossy(&bytes);
        if !looks_relevant(&text) {
            continue;
        }
        collect_json_snippets(&text, &rel, found);
        let normalized = normalize_escaped_json(&text);
        if normalized != text {
            collect_json_snippets(&normalized, &rel, found);
        }
    }
    Ok(())
}

fn skip_dir(path: &Path) -> bool {
    path.file_name()
        .and_then(|name| name.to_str())
        .is_some_and(|name| {
            matches!(
                name,
                ".git" | ".worktrees" | "node_modules" | "target" | "vendor"
            )
        })
}

fn read_for_corpus(path: &Path) -> bool {
    matches!(
        path.extension().and_then(|ext| ext.to_str()),
        Some("json" | "toml" | "proof" | "rs" | "txt")
    )
}

fn looks_relevant(text: &str) -> bool {
    text.contains("\"kind\"")
        && (text.contains("\"atomic\"") || text.contains("\"ctor\""))
        && text.contains("\"name\"")
}

fn collect_json_snippets(text: &str, rel: &str, found: &mut BTreeMap<CorpusKey, BTreeSet<String>>) {
    let bytes = text.as_bytes();
    let mut idx = 0;
    while idx < bytes.len() {
        let byte = bytes[idx];
        if byte != b'{' && byte != b'[' {
            idx += 1;
            continue;
        }
        if let Some(end) = balanced_json_end(bytes, idx) {
            if let Ok(value) = serde_json::from_str::<Json>(&text[idx..end]) {
                collect_value(&value, rel, found);
                idx = end;
                continue;
            }
        }
        idx += 1;
    }
}

fn balanced_json_end(bytes: &[u8], start: usize) -> Option<usize> {
    let mut stack = Vec::new();
    let mut in_string = false;
    let mut escaped = false;
    for (idx, byte) in bytes.iter().enumerate().skip(start) {
        if in_string {
            if escaped {
                escaped = false;
            } else if *byte == b'\\' {
                escaped = true;
            } else if *byte == b'"' {
                in_string = false;
            }
            continue;
        }
        match *byte {
            b'"' => in_string = true,
            b'{' | b'[' => stack.push(*byte),
            b'}' => {
                if stack.pop() != Some(b'{') {
                    return None;
                }
                if stack.is_empty() {
                    return Some(idx + 1);
                }
            }
            b']' => {
                if stack.pop() != Some(b'[') {
                    return None;
                }
                if stack.is_empty() {
                    return Some(idx + 1);
                }
            }
            _ => {}
        }
    }
    None
}

fn collect_value(value: &Json, rel: &str, found: &mut BTreeMap<CorpusKey, BTreeSet<String>>) {
    match value {
        Json::Object(obj) => {
            if let (Some(kind), Some(name)) = (
                obj.get("kind").and_then(Json::as_str),
                obj.get("name").and_then(Json::as_str),
            ) {
                let position = match kind {
                    "atomic" => Some(SymbolPosition::Atom),
                    "ctor" => Some(SymbolPosition::Ctor),
                    _ => None,
                };
                if let Some(position) = position {
                    let arity = obj.get("args").and_then(Json::as_array).map_or(0, Vec::len);
                    found
                        .entry(CorpusKey {
                            position,
                            name: name.to_string(),
                            arity,
                        })
                        .or_default()
                        .insert(rel.to_string());
                }
            }
            for child in obj.values() {
                collect_value(child, rel, found);
            }
        }
        Json::Array(values) => {
            for child in values {
                collect_value(child, rel, found);
            }
        }
        _ => {}
    }
}

fn normalize_escaped_json(text: &str) -> String {
    text.replace("\\\"", "\"")
        .replace("\\u{2260}", "\u{2260}")
        .replace("\\u{2264}", "\u{2264}")
        .replace("\\u{2265}", "\u{2265}")
}

fn term_args(arity: usize) -> Vec<Json> {
    (0..arity)
        .map(|idx| json!({"kind": "var", "name": format!("x{idx}")}))
        .collect()
}

fn maude_var_args(arity: usize) -> Vec<Json> {
    (0..arity)
        .map(|idx| json!({"kind": "var", "name": maude_var_name(idx)}))
        .collect()
}

fn maude_var_name(idx: usize) -> String {
    format!("X{idx}")
}
