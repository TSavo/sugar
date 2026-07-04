// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Thin forward-propagation core for the Rust LSP plugin.
//
// This module intentionally models the v1.0.0 floor as a small statement IR.
// Parser-specific lowering can stay separate while the implication loop,
// branch merge, diagnostic shape, and top fallback remain easy to test.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt::Write as _;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Post {
    constraints: Vec<String>,
    is_top: bool,
}

impl Post {
    pub fn known<const N: usize>(constraints: [&str; N]) -> Self {
        Self::from_strings(constraints.into_iter().map(String::from), false)
    }

    pub fn empty() -> Self {
        Self {
            constraints: Vec::new(),
            is_top: false,
        }
    }

    pub fn top() -> Self {
        Self {
            constraints: Vec::new(),
            is_top: true,
        }
    }

    pub fn is_top(&self) -> bool {
        self.is_top
    }

    pub fn constraints(&self) -> &[String] {
        &self.constraints
    }

    fn from_strings<I>(constraints: I, is_top: bool) -> Self
    where
        I: IntoIterator<Item = String>,
    {
        if is_top {
            return Self::top();
        }
        let mut set = BTreeSet::new();
        for constraint in constraints {
            if !constraint.is_empty() {
                set.insert(constraint);
            }
        }
        Self {
            constraints: set.into_iter().collect(),
            is_top: false,
        }
    }

    fn combine(&self, next: &Post) -> Post {
        if self.is_top || next.is_top {
            return Post::top();
        }
        Post::from_strings(
            self.constraints
                .iter()
                .cloned()
                .chain(next.constraints.iter().cloned()),
            false,
        )
    }

    fn branch_merge(&self, other: &Post) -> Post {
        if self.is_top || other.is_top {
            return Post::top();
        }
        let other_constraints: BTreeSet<_> = other.constraints.iter().collect();
        Post::from_strings(
            self.constraints
                .iter()
                .filter(|constraint| other_constraints.contains(constraint))
                .cloned(),
            false,
        )
    }

    fn cid(&self) -> String {
        if self.is_top {
            return cid_for_bytes(b"post:top");
        }
        let payload = format!("post:known:{}", self.constraints.join("\n"));
        cid_for_bytes(payload.as_bytes())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Stmt {
    Reset,
    Assign {
        post: Post,
    },
    Call {
        callee_id: String,
        range: LspRange,
    },
    IfElse {
        then_branch: Vec<Stmt>,
        else_branch: Vec<Stmt>,
    },
    Unsupported,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LspPosition {
    pub line: u32,
    pub character: u32,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LspRange {
    pub start: LspPosition,
    pub end: LspPosition,
}

impl LspRange {
    pub fn single_line(line: u32, start_character: u32, end_character: u32) -> Self {
        Self {
            start: LspPosition {
                line,
                character: start_character,
            },
            end: LspPosition {
                line,
                character: end_character,
            },
        }
    }

    fn to_json(&self) -> serde_json::Value {
        serde_json::json!({
            "start": {
                "line": self.start.line,
                "character": self.start.character,
            },
            "end": {
                "line": self.end.line,
                "character": self.end.character,
            }
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BaselineEntry {
    pub callee_id: String,
    pub pre: Option<Post>,
    pub post: Option<Post>,
    pub contract_name: String,
    pub member_cid: String,
    pub contract_cid: String,
    pub attestation_cid: String,
    pub pre_cid: String,
    pub post_cid: String,
    pub signer: String,
    pub signer_role: String,
    pub baseline_contract_set_cid: String,
    pub baseline_index_cid: String,
}

impl BaselineEntry {
    pub fn new(callee_id: impl Into<String>, pre: Option<Post>, post: Option<Post>) -> Self {
        let callee_id = callee_id.into();
        let contract_name = format!("rust_baseline_{}", sanitize_identifier(&callee_id));
        let pre_cid = pre
            .as_ref()
            .map(Post::cid)
            .unwrap_or_else(|| cid_for_bytes(format!("{callee_id}:pre:none").as_bytes()));
        let post_cid = post
            .as_ref()
            .map(Post::cid)
            .unwrap_or_else(|| cid_for_bytes(format!("{callee_id}:post:none").as_bytes()));
        let seed = format!("{callee_id}|{pre_cid}|{post_cid}");

        Self {
            callee_id,
            pre,
            post,
            contract_name,
            member_cid: cid_for_bytes(format!("member:{seed}").as_bytes()),
            contract_cid: cid_for_bytes(format!("contract:{seed}").as_bytes()),
            attestation_cid: cid_for_bytes(format!("attestation:{seed}").as_bytes()),
            pre_cid,
            post_cid,
            signer: "ed25519:foundation-v0".into(),
            signer_role: "foundation-baseline".into(),
            baseline_contract_set_cid: cid_for_bytes(
                format!("baseline-contract-set:{seed}").as_bytes(),
            ),
            baseline_index_cid: cid_for_bytes(format!("baseline-index:{seed}").as_bytes()),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DiagnosticData {
    pub schema_version: u32,
    pub kind: String,
    pub callee: String,
    pub callee_contract_cid: String,
    pub callee_attestation_cid: String,
    pub callee_pre_cid: String,
    pub callee_post_cid: String,
    pub current_post_cid: String,
    pub missing_conjuncts: Vec<String>,
    pub signer: String,
    pub signer_role: String,
    pub baseline_contract_set_cid: String,
    pub baseline_index_cid: String,
}

impl DiagnosticData {
    fn to_json(&self) -> serde_json::Value {
        serde_json::json!({
            "schema_version": self.schema_version,
            "kind": self.kind,
            "callee": self.callee,
            "callee_contract_cid": self.callee_contract_cid,
            "callee_attestation_cid": self.callee_attestation_cid,
            "callee_pre_cid": self.callee_pre_cid,
            "callee_post_cid": self.callee_post_cid,
            "current_post_cid": self.current_post_cid,
            "missing_conjuncts": self.missing_conjuncts,
            "signer": self.signer,
            "signer_role": self.signer_role,
            "baseline_contract_set_cid": self.baseline_contract_set_cid,
            "baseline_index_cid": self.baseline_index_cid,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LspDiagnostic {
    pub range: LspRange,
    pub severity: u8,
    pub source: String,
    pub code: String,
    pub message: String,
    pub data: DiagnosticData,
}

impl LspDiagnostic {
    pub fn to_lsp_json(&self) -> serde_json::Value {
        serde_json::json!({
            "range": self.range.to_json(),
            "severity": self.severity,
            "source": self.source,
            "code": self.code,
            "message": self.message,
            "data": self.data.to_json(),
        })
    }
}

#[derive(Clone, Debug, Default)]
pub struct ForwardPropagator {
    index: BTreeMap<String, BaselineEntry>,
}

impl ForwardPropagator {
    pub fn new<I>(entries: I) -> Self
    where
        I: IntoIterator<Item = BaselineEntry>,
    {
        let index = entries
            .into_iter()
            .map(|entry| (entry.callee_id.clone(), entry))
            .collect();
        Self { index }
    }

    pub fn floor_v1_seed_index() -> Self {
        Self::new([BaselineEntry::new(
            "checkPositive",
            Some(Post::known(["x > 0"])),
            Some(Post::known(["returns true"])),
        )])
    }

    pub fn lower_floor_source(source: &str) -> Vec<Stmt> {
        let mut stmts = Vec::new();
        let mut brace_depth = 0i32;
        let mut top_block_depth: Option<i32> = None;
        let scan_source = mask_rust_non_code(source);

        for (line_idx, line) in scan_source.lines().enumerate() {
            let trimmed = line.trim_start();
            let is_function_definition = is_rust_function_header(trimmed);
            if is_function_definition {
                stmts.push(Stmt::Reset);
                top_block_depth = None;
            }

            if starts_top_fallback_block(trimmed) {
                let opens = line.matches('{').count() as i32;
                let closes = line.matches('}').count() as i32;
                top_block_depth = Some(brace_depth + opens - closes);
                if top_block_depth == Some(brace_depth) {
                    top_block_depth = Some(brace_depth + 1);
                }
            }

            if !is_function_definition {
                for (start, arg) in check_positive_calls(line) {
                    let range = LspRange::single_line(
                        line_idx as u32,
                        start as u32,
                        (start + "checkPositive".len()) as u32,
                    );

                    if top_block_depth.is_some() {
                        stmts.push(Stmt::Unsupported);
                    } else {
                        stmts.push(Stmt::Assign {
                            post: post_for_check_positive_arg(&arg),
                        });
                    }

                    stmts.push(Stmt::Call {
                        callee_id: "checkPositive".into(),
                        range,
                    });
                }
            }

            brace_depth += line.matches('{').count() as i32;
            brace_depth -= line.matches('}').count() as i32;
            if let Some(depth) = top_block_depth {
                if brace_depth < depth {
                    top_block_depth = None;
                }
            }
        }

        stmts
    }

    pub fn emit_diagnostics(&self, function_body: &[Stmt]) -> Vec<LspDiagnostic> {
        let mut diagnostics = Vec::new();
        let _ = self.walk_block(function_body, Post::empty(), &mut diagnostics);
        diagnostics
    }

    pub fn check_callsite(
        &self,
        callee_id: &str,
        current_post: &Post,
        range: LspRange,
    ) -> Option<LspDiagnostic> {
        if current_post.is_top() {
            return None;
        }

        let entry = self.index.get(callee_id)?;
        let pre = entry.pre.as_ref()?;
        let current_constraints: BTreeSet<_> = current_post.constraints().iter().collect();
        let missing_conjuncts: Vec<String> = pre
            .constraints()
            .iter()
            .filter(|constraint| !current_constraints.contains(constraint))
            .cloned()
            .collect();

        if missing_conjuncts.is_empty() {
            return None;
        }

        Some(LspDiagnostic {
            range,
            severity: 1,
            source: "sugar".into(),
            code: "sugar.lsp.implication_failed".into(),
            message: "callee precondition not established at this callsite".into(),
            data: DiagnosticData {
                schema_version: 1,
                kind: "sugar.lsp.implication_failed".into(),
                callee: entry.callee_id.clone(),
                callee_contract_cid: entry.contract_cid.clone(),
                callee_attestation_cid: entry.attestation_cid.clone(),
                callee_pre_cid: entry.pre_cid.clone(),
                callee_post_cid: entry.post_cid.clone(),
                current_post_cid: current_post.cid(),
                missing_conjuncts,
                signer: entry.signer.clone(),
                signer_role: entry.signer_role.clone(),
                baseline_contract_set_cid: entry.baseline_contract_set_cid.clone(),
                baseline_index_cid: entry.baseline_index_cid.clone(),
            },
        })
    }

    fn walk_block(
        &self,
        body: &[Stmt],
        start_post: Post,
        diagnostics: &mut Vec<LspDiagnostic>,
    ) -> Post {
        let mut current_post = start_post;

        for stmt in body {
            match stmt {
                Stmt::Reset => {
                    current_post = Post::empty();
                }
                Stmt::Assign { post } => {
                    current_post = current_post.combine(post);
                }
                Stmt::Call { callee_id, range } => {
                    let diagnostic = self.check_callsite(callee_id, &current_post, range.clone());
                    let failed_precondition = diagnostic.is_some();
                    if let Some(diagnostic) = diagnostic {
                        diagnostics.push(diagnostic);
                    }
                    if !failed_precondition {
                        current_post = match self
                            .index
                            .get(callee_id)
                            .and_then(|entry| entry.post.as_ref())
                        {
                            Some(post) => current_post.combine(post),
                            None if self.index.contains_key(callee_id) => current_post,
                            None => Post::top(),
                        };
                    }
                }
                Stmt::IfElse {
                    then_branch,
                    else_branch,
                } => {
                    let then_post = self.walk_block(then_branch, current_post.clone(), diagnostics);
                    let else_post = self.walk_block(else_branch, current_post.clone(), diagnostics);
                    current_post = then_post.branch_merge(&else_post);
                }
                Stmt::Unsupported => {
                    current_post = Post::top();
                }
            }
        }

        current_post
    }
}

fn sanitize_identifier(value: &str) -> String {
    value
        .chars()
        .map(|ch| if ch.is_ascii_alphanumeric() { ch } else { '_' })
        .collect()
}

fn starts_top_fallback_block(trimmed: &str) -> bool {
    let loop_head = strip_rust_label(trimmed).unwrap_or(trimmed).trim_start();
    loop_head.starts_with("for ")
        || loop_head.starts_with("for(")
        || loop_head.starts_with("while ")
        || loop_head.starts_with("while(")
        || loop_head.starts_with("loop ")
        || loop_head.starts_with("loop{")
}

fn is_rust_function_header(trimmed: &str) -> bool {
    let mut rest = trimmed;
    loop {
        if rest.starts_with("fn ") {
            return true;
        }
        if let Some(next) = rest.strip_prefix("pub ") {
            rest = next.trim_start();
            continue;
        }
        if let Some(next) = rest
            .strip_prefix("pub(")
            .and_then(|tail| tail.find(')').map(|close| tail[close + 1..].trim_start()))
        {
            rest = next;
            continue;
        }
        let mut consumed = false;
        for prefix in ["async ", "unsafe ", "const "] {
            if let Some(next) = rest.strip_prefix(prefix) {
                rest = next.trim_start();
                consumed = true;
                break;
            }
        }
        if !consumed {
            if let Some(next) = rest.strip_prefix("extern ") {
                rest = skip_rust_abi_literal(next).trim_start();
                consumed = true;
            }
        }
        if !consumed {
            return false;
        }
    }
}

fn skip_rust_abi_literal(value: &str) -> &str {
    let trimmed = value.trim_start();
    if let Some(end) = rust_raw_string_end(trimmed.as_bytes(), 0) {
        return &trimmed[end..];
    }

    let bytes = trimmed.as_bytes();
    if bytes.first() != Some(&b'"') {
        return trimmed;
    }

    let mut idx = 1usize;
    let mut escaped = false;
    while idx < bytes.len() {
        let byte = bytes[idx];
        idx += 1;
        if escaped {
            escaped = false;
        } else if byte == b'\\' {
            escaped = true;
        } else if byte == b'"' {
            return &trimmed[idx..];
        } else if byte == b'\n' {
            break;
        }
    }

    trimmed
}

fn check_positive_calls(line: &str) -> Vec<(usize, String)> {
    const NAME: &str = "checkPositive";
    let mut calls = Vec::new();
    let mut search_from = 0usize;
    while let Some(relative_start) = line[search_from..].find(NAME) {
        let start = search_from + relative_start;
        let bytes = line.as_bytes();
        if start > 0 && is_identifier_byte(bytes[start - 1]) {
            search_from = start + NAME.len();
            continue;
        }

        let mut cursor = start + NAME.len();
        if cursor < bytes.len() && is_identifier_byte(bytes[cursor]) {
            search_from = cursor;
            continue;
        }
        while cursor < bytes.len() && matches!(bytes[cursor], b' ' | b'\t') {
            cursor += 1;
        }
        if cursor >= bytes.len() || bytes[cursor] != b'(' {
            search_from = start + NAME.len();
            continue;
        }

        let args_start = cursor + 1;
        let mut depth = 1i32;
        let mut end = args_start;
        while end < bytes.len() {
            match bytes[end] {
                b'(' => depth += 1,
                b')' => {
                    depth -= 1;
                    if depth == 0 {
                        break;
                    }
                }
                _ => {}
            }
            end += 1;
        }
        if end < bytes.len() && depth == 0 {
            calls.push((start, line[args_start..end].trim().to_string()));
            search_from = end + 1;
        } else {
            break;
        }
    }
    calls
}

fn mask_rust_non_code(source: &str) -> String {
    let bytes = source.as_bytes();
    let mut out = String::with_capacity(source.len());
    let mut idx = 0usize;

    while idx < bytes.len() {
        if bytes[idx..].starts_with(b"//") {
            idx = mask_until_newline(bytes, idx, &mut out);
        } else if bytes[idx..].starts_with(b"/*") {
            idx = mask_rust_block_comment(bytes, idx, &mut out);
        } else if let Some(end) = rust_raw_string_end(bytes, idx) {
            mask_range(bytes, idx, end, &mut out);
            idx = end;
        } else if bytes[idx] == b'"' || bytes[idx..].starts_with(b"b\"") {
            idx = mask_escaped_delimited(bytes, idx, b'"', &mut out);
        } else if bytes[idx..].starts_with(b"b'") {
            idx = mask_escaped_delimited(bytes, idx, b'\'', &mut out);
        } else if bytes[idx] == b'\'' && !is_rust_lifetime_start(bytes, idx) {
            idx = mask_escaped_delimited(bytes, idx, b'\'', &mut out);
        } else {
            out.push(bytes[idx] as char);
            idx += 1;
        }
    }

    out
}

fn rust_raw_string_end(bytes: &[u8], start: usize) -> Option<usize> {
    let (hash_start, quote_idx) = if bytes[start] == b'r' {
        (start + 1, start + 1)
    } else if bytes[start..].starts_with(b"br") {
        (start + 2, start + 2)
    } else {
        return None;
    };

    let mut cursor = quote_idx;
    while cursor < bytes.len() && bytes[cursor] == b'#' {
        cursor += 1;
    }
    if cursor >= bytes.len() || bytes[cursor] != b'"' {
        return None;
    }
    let hash_count = cursor - hash_start;
    cursor += 1;

    while cursor < bytes.len() {
        if bytes[cursor] == b'"' {
            let hashes_end = cursor + 1 + hash_count;
            if hashes_end <= bytes.len()
                && bytes[cursor + 1..hashes_end]
                    .iter()
                    .all(|byte| *byte == b'#')
            {
                return Some(hashes_end);
            }
        }
        cursor += 1;
    }

    Some(bytes.len())
}

fn mask_rust_block_comment(bytes: &[u8], start: usize, out: &mut String) -> usize {
    let mut idx = start;
    let mut depth = 0i32;
    while idx < bytes.len() {
        if bytes[idx..].starts_with(b"/*") {
            depth += 1;
            mask_range(bytes, idx, idx + 2, out);
            idx += 2;
        } else if bytes[idx..].starts_with(b"*/") {
            depth -= 1;
            mask_range(bytes, idx, idx + 2, out);
            idx += 2;
            if depth == 0 {
                break;
            }
        } else {
            push_masked_byte(out, bytes[idx]);
            idx += 1;
        }
    }
    idx
}

fn mask_until_newline(bytes: &[u8], start: usize, out: &mut String) -> usize {
    let mut idx = start;
    while idx < bytes.len() && bytes[idx] != b'\n' {
        push_masked_byte(out, bytes[idx]);
        idx += 1;
    }
    if idx < bytes.len() {
        out.push('\n');
        idx += 1;
    }
    idx
}

fn mask_escaped_delimited(bytes: &[u8], start: usize, delimiter: u8, out: &mut String) -> usize {
    let mut idx = if bytes[start] == b'b' {
        start + 1
    } else {
        start
    };
    mask_range(bytes, start, idx + 1, out);
    idx += 1;

    let mut escaped = false;
    while idx < bytes.len() {
        let byte = bytes[idx];
        push_masked_byte(out, byte);
        idx += 1;
        if byte == b'\n' {
            break;
        }
        if escaped {
            escaped = false;
        } else if byte == b'\\' {
            escaped = true;
        } else if byte == delimiter {
            break;
        }
    }
    idx
}

fn mask_range(bytes: &[u8], start: usize, end: usize, out: &mut String) {
    for byte in &bytes[start..end] {
        push_masked_byte(out, *byte);
    }
}

fn push_masked_byte(out: &mut String, byte: u8) {
    if byte == b'\n' {
        out.push('\n');
    } else {
        out.push(' ');
    }
}

fn strip_rust_label(value: &str) -> Option<&str> {
    let bytes = value.as_bytes();
    if bytes.len() < 3 || bytes[0] != b'\'' {
        return None;
    }

    let next = bytes[1];
    if !next.is_ascii_alphabetic() && next != b'_' {
        return None;
    }

    let mut cursor = 2usize;
    while cursor < bytes.len() && is_identifier_byte(bytes[cursor]) {
        cursor += 1;
    }

    if cursor < bytes.len() && bytes[cursor] == b':' {
        Some(&value[cursor + 1..])
    } else {
        None
    }
}

fn is_rust_lifetime_start(bytes: &[u8], quote_idx: usize) -> bool {
    if quote_idx + 1 >= bytes.len() {
        return false;
    }

    let next = bytes[quote_idx + 1];
    if !next.is_ascii_alphabetic() && next != b'_' {
        return false;
    }

    let mut cursor = quote_idx + 2;
    while cursor < bytes.len() && is_identifier_byte(bytes[cursor]) {
        cursor += 1;
    }

    cursor >= bytes.len() || bytes[cursor] != b'\''
}

fn is_identifier_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || byte == b'_'
}

fn post_for_check_positive_arg(arg: &str) -> Post {
    match arg.parse::<i64>() {
        Ok(value) if value > 0 => Post::known(["x > 0"]),
        Ok(_) => Post::known(["x <= 0"]),
        Err(_) => Post::top(),
    }
}

fn cid_for_bytes(bytes: &[u8]) -> String {
    let mut hasher = blake3::Hasher::new();
    hasher.update(bytes);
    let mut reader = hasher.finalize_xof();
    let mut out = [0u8; 64];
    reader.fill(&mut out);

    let mut cid = String::from("blake3-512:");
    for byte in out {
        let _ = write!(&mut cid, "{byte:02x}");
    }
    cid
}
