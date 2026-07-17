// SPDX-License-Identifier: MIT OR Apache-2.0
//
// #3855 sugar-walk purification remainder: self-locating source locator types.
//
// `SourceMemento` / `SrcSpan` are language-neutral wire locators (file + span +
// CIDs + param names). They never carry source text or AST. They lived under
// sugar-walk only because the Rust SourceOracle minted them there; the types
// themselves are membrane currency shared by sugar-compiler (tree/resolve/kit)
// and every kit face.
//
// Home is libsugar so sugar-compiler can hold the locator without a
// sugar-compiler → sugar-walk Cargo edge (arch-guard ban). sugar-walk re-exports
// the same types for BindKit / walk_rpc / historical `sugar_walk::source_oracle`
// call sites.

use serde_json::{json, Value};

/// A source span, 1-based line / 0-based column.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SrcSpan {
    pub start_line: usize,
    pub start_col: usize,
    pub end_line: usize,
    pub end_col: usize,
}

/// Content-addressed pointer to a source function body (or finer locus).
///
/// Never carries source text or serialized AST. Consumers re-read the
/// authoritative source file and recompute CIDs to prove the pointer still
/// names the same body.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SourceMemento {
    pub file: String,
    pub function_name: String,
    pub span: SrcSpan,
    pub param_names: Vec<String>,
    pub source_cid: String,
    pub template_cid: String,
}

impl SourceMemento {
    pub fn source_function_name(&self) -> Option<&str> {
        (!self.function_name.is_empty()).then_some(self.function_name.as_str())
    }

    pub fn to_json(&self) -> Value {
        let mut value = json!({
            "kind": "source-memento",
            "file": self.file,
            "span": {
                "start_line": self.span.start_line,
                "start_col": self.span.start_col,
                "end_line": self.span.end_line,
                "end_col": self.span.end_col,
            },
            "paramNames": self.param_names,
            "param_names": self.param_names,
            "source_cid": self.source_cid,
            "template_cid": self.template_cid,
        });
        if let Some(name) = self.source_function_name() {
            value["sourceFunctionName"] = json!(name);
            value["source_function_name"] = json!(name);
        }
        value
    }

    /// Extract the source text this memento's span refers to from a full source
    /// file string. Returns `None` when the line/column indices are out of range
    /// or the byte slice is not valid UTF-8.
    ///
    /// Span coordinates: `start_line` / `end_line` are 1-indexed; `start_col`
    /// / `end_col` are 0-indexed byte offsets within the line (exclusive end),
    /// matching proc_macro2 / syn conventions.
    pub fn extract_term_source<'a>(&self, source_text: &'a str) -> Option<&'a str> {
        if self.span.start_line == 0 || self.span.start_line != self.span.end_line {
            return None; // absent or multi-line: not supported
        }
        let line = source_text.lines().nth(self.span.start_line - 1)?; // 1→0 indexed
        let bytes = line.as_bytes();
        let start = self.span.start_col.min(bytes.len());
        let end = self.span.end_col.min(bytes.len());
        if start >= end {
            return None;
        }
        match std::str::from_utf8(&bytes[start..end]) {
            Ok(source) => Some(source),
            Err(_) => None,
        }
    }

    /// Like `to_json` but stamps a `sourceOracle.source` field with the term
    /// text extracted from `source_text` at the stored span. Consumers that
    /// have the source text in scope (e.g. test helpers, CLI renderers) call
    /// this instead of a separate oracle RPC round-trip.
    pub fn to_json_stamped(&self, source_text: &str) -> Value {
        let mut value = self.to_json();
        if let Some(source) = self.extract_term_source(source_text) {
            value["sourceOracle"] = json!({
                "status": "resolved",
                "source": source,
            });
        }
        value
    }

    pub fn to_body_source_json(&self) -> Value {
        json!({
            "file": self.file,
            "span": {
                "start_line": self.span.start_line,
                "start_col": self.span.start_col,
                "end_line": self.span.end_line,
                "end_col": self.span.end_col,
            },
            "source_cid": self.source_cid,
            "template_cid": self.template_cid,
            "param_names": self.param_names,
        })
    }

    pub fn from_body_source(
        source_function_name: Option<String>,
        body_source: &Value,
    ) -> Option<Self> {
        let file = body_source.get("file").and_then(Value::as_str)?.to_string();
        let span = body_source.get("span")?;
        let param_names = match body_source
            .get("param_names")
            .or_else(|| body_source.get("paramNames"))
            .and_then(Value::as_array)
        {
            Some(arr) => arr
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect(),
            None => Vec::new(),
        };
        let function_name = match source_function_name {
            Some(name) => name,
            None => String::new(),
        };
        let source_cid = body_source
            .get("source_cid")
            .or_else(|| body_source.get("sourceCid"))
            .and_then(Value::as_str)
            .filter(|cid| !cid.trim().is_empty())?
            .to_string();
        let template_cid = body_source
            .get("template_cid")
            .or_else(|| body_source.get("templateCid"))
            .and_then(Value::as_str)
            .filter(|cid| !cid.trim().is_empty())?
            .to_string();
        Some(SourceMemento {
            file,
            function_name,
            span: SrcSpan {
                start_line: span.get("start_line").and_then(Value::as_u64)? as usize,
                start_col: span.get("start_col").and_then(Value::as_u64)? as usize,
                end_line: span.get("end_line").and_then(Value::as_u64)? as usize,
                end_col: span.get("end_col").and_then(Value::as_u64)? as usize,
            },
            source_cid,
            template_cid,
            param_names,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn from_body_source_round_trips_to_json_fields() {
        let body = json!({
            "file": "src/lib.rs",
            "span": {
                "start_line": 10,
                "start_col": 0,
                "end_line": 20,
                "end_col": 1,
            },
            "param_names": ["x", "y"],
            "source_cid": "blake3-512:src",
            "template_cid": "blake3-512:tpl",
        });
        let m = SourceMemento::from_body_source(Some("add".into()), &body).expect("parse");
        assert_eq!(m.file, "src/lib.rs");
        assert_eq!(m.function_name, "add");
        assert_eq!(m.param_names, vec!["x", "y"]);
        assert_eq!(m.span.start_line, 10);
        let v = m.to_json();
        assert_eq!(v["kind"], "source-memento");
        assert_eq!(v["sourceFunctionName"], "add");
        assert_eq!(v["source_cid"], "blake3-512:src");
    }

    #[test]
    fn extract_term_source_single_line() {
        let m = SourceMemento {
            file: "f.rs".into(),
            function_name: "f".into(),
            span: SrcSpan {
                start_line: 2,
                start_col: 4,
                end_line: 2,
                end_col: 7,
            },
            param_names: vec![],
            source_cid: "c".into(),
            template_cid: "t".into(),
        };
        let src = "fn f() {\n    foo\n}\n";
        assert_eq!(m.extract_term_source(src), Some("foo"));
    }
}
