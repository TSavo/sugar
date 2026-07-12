// SPDX-License-Identifier: MIT OR Apache-2.0
//
// fol_format.rs: Rust port of `editors/vscode-sugar/src/proveClient.ts`'s
// `prettyFol` / `formatDetail` / `provenValueOf`, so the in-process LSP
// renders the IDENTICAL three-fact hover/diagnostic block ("Vendor fact" /
// "Vendor universe" / "Your fact" / "Conjoined" / "The fix (z3.model)") the
// VS Code extension shows, from the SAME `verification` JSON
// `sugar_verifier::report::row_to_json` stamps onto each row
// (`vendorFactFol` / `vendorUniverseFol` / `clientFactFol`).

/// Strip a leading `⊢` turnstile (and surrounding whitespace) from `s`.
fn strip_turnstile(s: &str) -> String {
    let trimmed = s.trim_start();
    match trimmed.strip_prefix('⊢') {
        Some(rest) => rest.trim_start().to_string(),
        None => trimmed.to_string(),
    }
}

/// Split `s` on `sep` at bracket-depth 0, ignoring separators inside quoted
/// strings or nested `(...)`/`[...]`. Mirrors `proveClient.ts`'s `splitTop`.
fn split_top(s: &str, sep: &str) -> Vec<String> {
    let chars: Vec<char> = s.chars().collect();
    let sep_chars: Vec<char> = sep.chars().collect();
    let mut parts = Vec::new();
    let mut depth: i32 = 0;
    let mut in_str = false;
    let mut start = 0usize;
    let mut i = 0usize;
    while i < chars.len() {
        let ch = chars[i];
        if in_str {
            if ch == '"' && (i == 0 || chars[i - 1] != '\\') {
                in_str = false;
            }
            i += 1;
            continue;
        }
        if ch == '"' {
            in_str = true;
            i += 1;
            continue;
        }
        if ch == '(' || ch == '[' {
            depth += 1;
            i += 1;
            continue;
        }
        if ch == ')' || ch == ']' {
            depth -= 1;
            i += 1;
            continue;
        }
        if depth == 0 && starts_with_at(&chars, i, &sep_chars) {
            parts.push(chars[start..i].iter().collect());
            i += sep_chars.len();
            start = i;
            continue;
        }
        i += 1;
    }
    parts.push(chars[start..].iter().collect());
    parts
}

fn starts_with_at(chars: &[char], i: usize, pat: &[char]) -> bool {
    if pat.is_empty() || i + pat.len() > chars.len() {
        return false;
    }
    chars[i..i + pat.len()] == *pat
}

/// Does `s` carry ANY comma outside a quoted string? Despite the name (kept
/// to match `proveClient.ts`'s `hasTopComma` verbatim), this is a coarse
/// pre-check with NO depth gate on the comma itself -- bracket depth is
/// still tracked (so quote-escaping inside nested parens behaves), but a
/// comma at any depth trips it. The actual depth-0 split happens in
/// `split_top`; this function only decides whether it is worth looking.
fn has_top_comma(s: &str) -> bool {
    let chars: Vec<char> = s.chars().collect();
    let mut in_str = false;
    let mut i = 0usize;
    while i < chars.len() {
        let ch = chars[i];
        if in_str {
            if ch == '"' && (i == 0 || chars[i - 1] != '\\') {
                in_str = false;
            }
            i += 1;
            continue;
        }
        match ch {
            '"' => in_str = true,
            '(' | '[' => {}
            ')' | ']' => {}
            ',' => return true,
            _ => {}
        }
        i += 1;
    }
    false
}

/// Recursively break one FOL conjunct: every top-level comma inside the
/// outermost call becomes a line break + indent. Mirrors `breakCall`.
fn break_call(s: &str, pad: &str, indent: &str) -> String {
    let s = s.trim();
    if !has_top_comma(s) {
        return format!("{pad}{s}");
    }
    let chars: Vec<char> = s.chars().collect();
    let mut in_str = false;
    let mut i = 0usize;
    while i < chars.len() {
        let ch = chars[i];
        if in_str {
            if ch == '"' && (i == 0 || chars[i - 1] != '\\') {
                in_str = false;
            }
            i += 1;
            continue;
        }
        if ch == '"' {
            in_str = true;
            i += 1;
            continue;
        }
        if ch == '(' || ch == '[' {
            let mut depth: i32 = 1;
            let mut j = i + 1;
            let mut in_str2 = false;
            while j < chars.len() {
                let c2 = chars[j];
                if in_str2 {
                    if c2 == '"' && chars[j - 1] != '\\' {
                        in_str2 = false;
                    }
                    j += 1;
                    continue;
                }
                match c2 {
                    '"' => in_str2 = true,
                    '(' | '[' => depth += 1,
                    ')' | ']' => {
                        depth -= 1;
                        if depth == 0 {
                            break;
                        }
                    }
                    _ => {}
                }
                j += 1;
            }
            let head: String = chars[..=i].iter().collect();
            let body_end = j.min(chars.len());
            let body: String = chars[(i + 1)..body_end].iter().collect();
            let tail: String = chars[body_end..].iter().collect();
            let args = split_top(&body, ", ");
            if args.len() < 2 {
                let inner_one = break_call(&body, pad, indent);
                let inner_lines: Vec<&str> = inner_one.split('\n').collect();
                if inner_lines.len() == 1 {
                    return format!("{pad}{s}");
                }
                let mut lines: Vec<String> = inner_lines.iter().map(|l| (*l).to_string()).collect();
                lines[0] = format!("{pad}{head}{}", lines[0].trim_start());
                let last = lines.len() - 1;
                lines[last] = format!("{}{tail}", lines[last]);
                return lines.join("\n");
            }
            let child_pad = format!("{pad}{indent}");
            let inner = args
                .iter()
                .map(|a| break_call(a, &child_pad, indent))
                .collect::<Vec<_>>()
                .join(",\n");
            return format!("{pad}{head}\n{inner}\n{pad}{tail}");
        }
        i += 1;
    }
    format!("{pad}{s}")
}

/// Pretty-print one FOL formula: break top-level `∧` conjuncts onto their
/// own lines, and long call argument lists onto indented sub-lines. NOTHING
/// is truncated. Mirrors `proveClient.ts`'s `prettyFol`.
pub fn pretty_fol(fol: &str, indent: &str) -> String {
    let conjuncts = split_top(fol, " ∧ ");
    if conjuncts.len() > 1 {
        conjuncts
            .iter()
            .enumerate()
            .map(|(i, c)| {
                let body = break_call(c, indent, indent);
                if i == 0 {
                    body
                } else {
                    let lead_len = indent.chars().count().saturating_sub(2);
                    let lead: String = indent.chars().take(lead_len).collect();
                    format!("{lead}∧ {}", body.trim_start())
                }
            })
            .collect::<Vec<_>>()
            .join("\n")
    } else {
        break_call(fol, indent, indent)
    }
}

/// The three conjoined facts a `row_to_json` "consistency" row's
/// `verification` object carries (when reachable at prove-emission time).
#[derive(Debug, Clone, Default)]
pub struct ConjoinedFacts<'a> {
    pub vendor_universe_fol: Option<&'a str>,
    pub client_fact_fol: Option<&'a str>,
    pub vendor_fact_fol: Option<&'a str>,
}

/// Build the IDE hover/diagnostic message: the three conjoined facts in
/// human-readable FOL under `Vendor fact` / `Vendor universe` / `Your fact`
/// headings, the `Conjoined` block, the solver verdict, and (when a proven
/// value is reachable) `The fix (z3.model)` -- the Quick Fix's replacement
/// value. Mirrors `proveClient.ts`'s `formatDetail`.
pub fn format_detail(facts: &ConjoinedFacts, status: &str, reason: &str) -> String {
    let mut lines: Vec<String> = Vec::new();
    let mut parts: Vec<String> = Vec::new();

    let mut section = |label: &str, fol: &str| {
        lines.push(label.to_string());
        lines.push(pretty_fol(&format!("⊢ {}", strip_turnstile(fol)), "    "));
    };

    if let Some(f) = facts.vendor_fact_fol {
        section("Vendor fact:", f);
        parts.push(strip_turnstile(f));
    }
    if let Some(f) = facts.vendor_universe_fol {
        section("Vendor universe:", f);
        parts.push(strip_turnstile(f));
    }
    if let Some(f) = facts.client_fact_fol {
        section("Your fact:", f);
        parts.push(strip_turnstile(f));
    }

    let verdict = if status == "unsatisfied" {
        "UNSAT".to_string()
    } else {
        status.to_uppercase()
    };

    if !parts.is_empty() {
        lines.push("Conjoined:".to_string());
        let conj = parts
            .iter()
            .map(|p| format!("({p})"))
            .collect::<Vec<_>>()
            .join(" ∧ ");
        lines.push(pretty_fol(&conj, "    "));
        lines.push(format!("  →  {verdict}"));

        let vendor_val = facts.vendor_fact_fol.and_then(rhs_of);
        if let (Some(vv), Some(cff)) = (vendor_val.as_deref(), facts.client_fact_fol) {
            let stripped = strip_turnstile(cff);
            let yours = stripped
                .split(" ∧ ")
                .filter_map(|c| rhs_of(c.trim()))
                .find(|v| v != vv);
            if let Some(y) = yours {
                lines.push("The fix (z3.model):".to_string());
                lines.push(format!(
                    "    replace {y} with {vv}   — Quick Fix (⌘.) applies it"
                ));
            }
        }
    } else {
        lines.push(format!("z3: {status} — {reason}"));
    }

    lines.join("\n")
}

/// The proven right-hand value of a `... = <value>` FOL string, e.g.
/// `⊢ call:encodeBase64("xyz") = "eHl6"` -> `"eHl6"`. Mirrors
/// `extension.ts`'s `provenValueOf`.
pub fn rhs_of(fol: &str) -> Option<String> {
    let idx = fol.rfind(" = ")?;
    let rhs = fol[idx + 3..].trim();
    if rhs.is_empty() {
        None
    } else {
        Some(rhs.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pretty_fol_single_conjunct_no_comma_is_flat() {
        assert_eq!(pretty_fol("call:foo(1) = 2", "    "), "    call:foo(1) = 2");
    }

    #[test]
    fn pretty_fol_breaks_top_level_conjunction() {
        let out = pretty_fol("a = 1 ∧ b = 2", "    ");
        assert_eq!(out, "    a = 1\n  ∧ b = 2");
    }

    #[test]
    fn pretty_fol_breaks_multi_arg_call_on_commas() {
        let out = pretty_fol("call:f(1, 2, 3) = 4", "    ");
        assert!(
            out.contains("call:f(\n"),
            "expected a broken call, got: {out}"
        );
        assert!(
            out.contains("        1,\n"),
            "expected indented args, got: {out}"
        );
    }

    #[test]
    fn format_detail_reports_z3_status_when_no_facts_reachable() {
        let facts = ConjoinedFacts::default();
        let msg = format_detail(&facts, "undecidable", "no sound discharger");
        assert_eq!(msg, "z3: undecidable — no sound discharger");
    }

    #[test]
    fn format_detail_includes_all_three_facts_and_the_fix() {
        let facts = ConjoinedFacts {
            vendor_universe_fol: Some("⊢ str.eq-bv-blocks(out, base64.blocks(x))"),
            client_fact_fol: Some("⊢ call:encodeBase64(\"xyz\") = \"AAAA\""),
            vendor_fact_fol: Some("⊢ call:encodeBase64(\"xyz\") = \"eHl6\""),
        };
        let msg = format_detail(&facts, "unsatisfied", "solver found a counterexample");
        assert!(msg.contains("Vendor fact:"));
        assert!(msg.contains("Vendor universe:"));
        assert!(msg.contains("Your fact:"));
        assert!(msg.contains("Conjoined:"));
        assert!(msg.contains("UNSAT"));
        assert!(msg.contains("The fix (z3.model):"));
        assert!(msg.contains("replace \"AAAA\" with \"eHl6\""));
    }

    #[test]
    fn rhs_of_extracts_the_proven_value() {
        assert_eq!(
            rhs_of("⊢ call:encodeBase64(\"xyz\") = \"eHl6\""),
            Some("\"eHl6\"".to_string())
        );
        assert_eq!(rhs_of("no equals here"), None);
    }
}
