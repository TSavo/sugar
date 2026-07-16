// SPDX-License-Identifier: MIT OR Apache-2.0
// HAND-MAINTAINED. Enum totality is compiler-enforced; atom/op-table totality
// is enforced by the vocabulary audit test (tests/vocabulary_totality.rs).

#![allow(unused_imports, unused_mut)]
#![deny(unreachable_patterns)]

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use sugar_canonicalizer::{blake3_512_of, cid_hex, encode_jcs, Value as CValue};
use sugar_ir_compiler::{CompileError, CompiledFormula, FreeVar, OpacityEntry, OpacityManifest};
use sugar_ir_types::*;

use crate::{COMPILER_NAME, COMPILER_VERSION, DIALECT};

const BV32_SORT: &str = "(_ BitVec 32)";

pub fn emit_term(term: &Term) -> String {
    emit_term_with_expected(term, None)
}

fn emit_term_with_expected(term: &Term, expected_ret: Option<&str>) -> String {
    match term {
        // Quote Var names the same way ctor names are quoted: a synthetic
        // name like `#field:code` or `#pat:<hash>` (introduced by the
        // struct-literal / match lift) is not a legal simple SMT symbol --
        // unquoted, z3 reads the leading `#f`/`#p` as a malformed
        // bit-vector literal. `smt_quote` wraps it in `|...|`; it is a
        // no-op for ordinary names, so plain identifiers are unchanged.
        Term::Var { name, .. } => smt_quote(name),
        Term::Const { value, sort, .. } => {
            if expected_ret == Some(BV32_SORT) {
                if let Some(v) = value.as_i64() {
                    return i32_to_bv32_hex(v);
                }
            }
            let sort_name = match sort {
                Sort::Primitive { name } => name.as_str(),
                Sort::Function { .. } | Sort::Dependent { .. } | Sort::Region { .. } => {
                    panic!("smt-lib: Const cannot carry a Function/Dependent/Region sort in pure SMT-LIB v2.6");
                }
            };
            emit_const_value(value, sort_name)
        }
        Term::Ctor { name, args, .. } => {
            if name == "to_real" && args.len() == 1 {
                return format!(
                    "(to_real {})",
                    emit_term_with_expected(&args[0], Some("Int"))
                );
            }
            if name == "str.len" && args.len() == 1 {
                return format!("(str.len {})", emit_string_term(&args[0]));
            }
            // ── Composable string-theory Ctor terms ───────────────────────────────────
            // str.from_code, str.++, str.table-select are GENERAL SMT string-theory
            // operations produced by the Sugar lift.  base64 discharge is a consequence
            // of these general mechanisms; nothing here is base64-specific.
            //
            // str.from_code(arg) → one-char String from a codepoint Int.
            // When the arg is a bv32 Ctor (name starts with "bv32."), bridge via
            // bv2nat because str.from_code takes Int, not BitVec. For all other
            // arg kinds (Int Const, str.table-select ite-chain output, Var declared
            // Int) emit_term already produces the correct Int-sorted SMT expression.
            if name == "str.from_code" && args.len() == 1 {
                if matches!(&args[0], Term::Ctor { name: inner, .. } if inner.starts_with("bv32."))
                {
                    let empty = std::collections::HashMap::new();
                    if let Some(bv_smt) = emit_bv32_term(&args[0], &empty) {
                        return format!("(str.from_code (bv2nat {}))", bv_smt);
                    }
                }
                return format!("(str.from_code {})", emit_term(&args[0]));
            }
            // str.++(left, right) → SMT string concatenation.
            // Routes through emit_string_term so a composed string tree in term
            // position stays in the string theory.
            if name == "str.++" && args.len() == 2 {
                return format!(
                    "(str.++ {} {})",
                    emit_string_term(&args[0]),
                    emit_string_term(&args[1])
                );
            }
            // str.table-select(alpha_str_const, bv32_index) →
            //   nested (ite (= idx K) cp ...) codepoint-lookup chain.
            // The alphabet string constant supplies the N-entry table; the bv32 index
            // is a symbolic or concrete bitvector (e.g. a 6-bit sextet from base64
            // bit-slicing, or any other bit-interleaved index into a byte table).
            // Returns an Int codepoint; callers wrap with str.from_code to get a
            // one-character String.  GENERAL: any String-valued alphabet table.
            if name == "str.table-select" && args.len() == 2 {
                if let Term::Const {
                    value: serde_json::Value::String(alpha),
                    ..
                } = &args[0]
                {
                    let alpha = alpha.clone();
                    let empty = std::collections::HashMap::new();
                    if let Some(index_smt) = emit_bv32_term(&args[1], &empty) {
                        let codepoints: Vec<i64> = alpha.chars().map(|c| c as i64).collect();
                        // Build innermost-first (reverse order) so that element 0 is
                        // the outermost ite, matching the ite-chain in
                        // render_b64_blocks_body_with_input.
                        let mut acc = "0".to_string();
                        for (idx, &cp) in codepoints.iter().enumerate().rev() {
                            let idx_hex = i32_to_bv32_hex(idx as i64);
                            acc = format!("(ite (= {} {}) {} {})", index_smt, idx_hex, cp, acc);
                        }
                        return acc;
                    }
                }
            }
            // Symbolic-variant guarded split (#3445 Part 1 slice 2): a
            // `cf_ite(adt.is_*(r), cf_guarded(.., some/ok-arm), cf_guarded(..,
            // none-arm))` value renders as a native `ite` over the datatype
            // tester. See `emit_monadic_guarded_split`.
            if let Some(rendered) = emit_monadic_guarded_split(term, expected_ret) {
                return rendered;
            }
            if name.starts_with("bv32.") {
                let subst = std::collections::HashMap::new();
                if let Some(rendered) = emit_bv32_term(term, &subst) {
                    return rendered;
                }
            }
            if args.is_empty() {
                if name == OPT_NONE && expected_ret == Some("SugarOptionOption") {
                    return smt_quote(OPT_NONE_OPTION);
                }
                return smt_ctor_head(name, args.len());
            };
            let arg_sorts = ctor_arg_sorts(name, args);
            let head = monadic_ctor_head_for_signature(name, expected_ret, &arg_sorts)
                .map(smt_quote)
                .unwrap_or_else(|| smt_ctor_head_for_signature(name, args.len(), &arg_sorts));
            let args_str: Vec<String> = args
                .iter()
                .zip(arg_sorts.iter())
                .map(|(arg, sort)| emit_term_with_expected(arg, Some(sort)))
                .collect();
            format!("({} {})", head, args_str.join(" "))
        }
        Term::Lambda {
            param_name,
            param_sort,
            body,
            ..
        } => {
            let sort_str = emit_sort(param_sort);
            let body_str = emit_term_with_expected(body, None);
            // Quote the binder name so a unique-renamed param like `e#0`
            // (the `#N` suffix the lifter's LiftCtx appends) is a legal
            // SMT symbol `|e#0|` -- and matches the quoted Var reference to
            // it in the body. Unquoted, z3 reads `#0` as a malformed
            // bit-vector literal.
            format!(
                "(lambda (({} {})) {})",
                smt_quote(param_name),
                sort_str,
                body_str
            )
        }
        Term::Let { bindings, body, .. } => {
            let mut binding_strs = bindings.iter();
            let binding_strs = binding_strs
                .map(|b| format!("({} {})", smt_quote(&b.name), emit_term(&b.bound_term)));
            let binding_strs: Vec<String> = binding_strs.collect();
            let body_str = emit_term_with_expected(body, expected_ret);
            format!("(let ({}) {})", binding_strs.join(" "), body_str)
        }
    }
}

/// Emit a sort as SMT-LIB surface syntax. Returns (smt_string, reason_code)
/// where reason_code is Some if the sort was opaque.
fn emit_sort_with_reason(sort: &Sort) -> (String, Option<String>) {
    match sort {
        Sort::Primitive { name } if is_supported_smt_primitive_sort(name) => (name.clone(), None),
        // NUMBER HIERARCHY: a fixed-width integer sort (u8 … i128, usize, isize)
        // IS `Int` for SMT, with NO opaque reason. The width is a refinement that
        // rides in the lifted callsite KEY (so `1u8` and `1u64` stay distinct
        // calls); the VALUE is a concrete Int, so arithmetic on it is checked
        // exactly. Without this explicit entry the literal fell to the opaque
        // fallback below, whose `reason` flips quantifier binders / decls onto a
        // CID-named opaque sort and turned otherwise-decidable obligations into
        // `unknown`.
        Sort::Primitive { name } if is_int_width_sort(name) => ("Int".to_string(), None),
        Sort::Primitive { name } => (
            "Int".to_string(),
            Some(format!("opaque_primitive_sort:{name}")),
        ),
        Sort::Function { .. } => (
            "Int".to_string(),
            Some("predicate_quantification".to_string()),
        ),
        Sort::Dependent { .. } => ("Int".to_string(), Some("dependent_type".to_string())),
        Sort::Region { .. } => (
            "Int".to_string(),
            Some("other:RegionSort pre-resolved in composition".to_string()),
        ),
    }
}

fn is_supported_smt_primitive_sort(name: &str) -> bool {
    matches!(name, "Int" | "Bool" | "Real" | "String")
}

/// A Rust fixed-width integer sort. For SMT it IS `Int` (the value is concrete,
/// arithmetic is exact); the width is a refinement carried only in the lifted
/// callsite key. See `emit_sort_with_reason`.
fn is_int_width_sort(name: &str) -> bool {
    matches!(
        name,
        "u8" | "u16"
            | "u32"
            | "u64"
            | "u128"
            | "usize"
            | "i8"
            | "i16"
            | "i32"
            | "i64"
            | "i128"
            | "isize"
    )
}

pub fn emit_sort(sort: &Sort) -> String {
    emit_sort_with_reason(sort).0
}

/// Derive a deterministic, language-blind SMT-LIB sort name for an opaque
/// sort. Uses the blake3 CID of the serialized sort as the disambiguator so
/// two distinct opaque sorts always get distinct names, and the same sort
/// always gets the same name within a compilation unit.
///
/// Output format: `S_<first-32-hex-chars-of-CID>`. Prefix ensures the name
/// starts with a letter (SMT-LIB simple symbol rule). The 32-char CID prefix
/// gives 128 bits of collision resistance -- more than sufficient for any
/// realistic formula. The symbol is safe for SMT-LIB simple-symbol syntax
/// (only [A-Za-z0-9_]).
fn opaque_sort_smt_name(sort: &Sort) -> String {
    let serialized = serde_json::to_value(sort).unwrap_or(serde_json::Value::Null);
    let cid = position_cid_of(&serialized);
    // Sanitize: keep only alphanumeric and underscore, then prefix with S_.
    let safe: String = cid
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '_')
        .take(32)
        .collect();
    format!("S_{}", safe)
}

/// Walk a formula collecting the SMT sort names for all opaque-sorted
/// quantifiers (Forall/Exists/Choice) so that `(declare-sort <S> 0)` can be
/// emitted into the preamble before the body. Each distinct opaque sort name
/// is stored as a key (value is unused).
fn collect_opaque_quantifier_sorts_formula(formula: &Formula, out: &mut BTreeMap<String, ()>) {
    match formula {
        Formula::Atomic { .. } => {}
        Formula::And { operands }
        | Formula::Or { operands }
        | Formula::Not { operands }
        | Formula::Implies { operands } => {
            for o in operands {
                collect_opaque_quantifier_sorts_formula(o, out);
            }
        }
        Formula::Forall { sort, body, .. }
        | Formula::Exists { sort, body, .. }
        | Formula::Choice { sort, body, .. } => {
            let (_, reason) = emit_sort_with_reason(sort);
            if reason.is_some() {
                out.insert(opaque_sort_smt_name(sort), ());
            }
            collect_opaque_quantifier_sorts_formula(body, out);
        }
        Formula::Substitute { .. } | Formula::Apply { .. } => {}
        Formula::DivergenceBetween { source, target } => {
            collect_opaque_quantifier_sorts_formula(source, out);
            collect_opaque_quantifier_sorts_formula(target, out);
        }
    }
}

fn strong_tier_refusal(name: &str, reason: impl std::fmt::Display) -> CompileError {
    CompileError::MalformedIr(format!("{name}: {reason}; refusing rather than weakening"))
}

pub fn emit_formula(formula: &Formula) -> Result<String, CompileError> {
    match formula {
        Formula::Atomic { name, args } => {
            if name == "identity" && args.len() == 2 {
                return Ok(format!(
                    "(= {} {})",
                    emit_identity_term(&args[0]),
                    emit_identity_term(&args[1])
                ));
            }
            if let Some(rendered) = emit_string_theory_atomic(name, args)? {
                return Ok(rendered);
            }
            if let Some(rendered) = emit_bv32_theory_atomic(name, args)? {
                return Ok(rendered);
            }
            // Monadic ADT discriminant testers (`adt.is_some`/.../`adt.is_err`):
            // rendered as NATIVE datatype testers `((_ is |opt:some|) x)` routed
            // by operand ADT sort. NEVER a generic (EUF) atomic application -- an
            // uninterpreted tester collapses the sum. A branch BEFORE generic
            // atomic rendering (T's Part-1 ruling, #3445).
            if let Some(rendered) = emit_monadic_adt_tester_atomic(name, args)? {
                return Ok(rendered);
            }
            let smt_name = smt_atomic_name(name);
            if args.is_empty() {
                return Ok(smt_name.to_string());
            };
            let expected = expected_atomic_arg_sort(name, args);
            let args_str = args.iter();
            let args_str = args_str.map(|arg| emit_term_with_expected(arg, expected.as_deref()));
            let args_str: Vec<String> = args_str.collect();
            Ok(format!("({} {})", smt_name, args_str.join(" ")))
        }
        Formula::And { operands } => {
            let ops_str: Result<Vec<String>, CompileError> =
                operands.iter().map(emit_formula).collect();
            Ok(format!("({} {})", "and", ops_str?.join(" ")))
        }
        Formula::Or { operands } => {
            let ops_str: Result<Vec<String>, CompileError> =
                operands.iter().map(emit_formula).collect();
            Ok(format!("({} {})", "or", ops_str?.join(" ")))
        }
        Formula::Not { operands } => Ok(format!("(not {})", emit_formula(&operands[0])?)),
        Formula::Implies { operands } => Ok(format!(
            "(=> {} {})",
            emit_formula(&operands[0])?,
            emit_formula(&operands[1])?
        )),
        Formula::Forall { name, sort, body } => {
            let (sort_str, reason) = emit_sort_with_reason(sort);
            let body_str = emit_formula(body)?;
            // Opaque sort: use the CID-derived uninterpreted sort name declared
            // in the preamble. Collapsing to `true` is unsound: `forall x:S.
            // false` would then appear as `true` and pass falsely.
            let effective_sort = if reason.is_some() {
                opaque_sort_smt_name(sort)
            } else {
                sort_str
            };
            Ok(format!(
                "(forall (({} {})) {})",
                name, effective_sort, body_str
            ))
        }
        Formula::Exists { name, sort, body } => {
            let (sort_str, reason) = emit_sort_with_reason(sort);
            let body_str = emit_formula(body)?;
            let effective_sort = if reason.is_some() {
                opaque_sort_smt_name(sort)
            } else {
                sort_str
            };
            Ok(format!(
                "(exists (({} {})) {})",
                name, effective_sort, body_str
            ))
        }
        Formula::Choice {
            var_name,
            sort,
            body,
        } => {
            let (sort_str, reason) = emit_sort_with_reason(sort);
            let body_str = emit_formula(body)?;
            let effective_sort = if reason.is_some() {
                opaque_sort_smt_name(sort)
            } else {
                sort_str
            };
            let var_y = format!("{}_y", var_name);
            let body_y = body_str.replace(var_name, &var_y);
            let unique = format!(
                "(and {} (forall (({} {})) (=> {} (= {} {}))))",
                body_str, var_y, effective_sort, body_y, var_y, var_name
            );
            Ok(format!(
                "(exists (({} {})) {})",
                var_name, effective_sort, unique
            ))
        }
        // wp-rule schema nodes (spec 2026-05-13-wp-as-formula.md §2.3):
        // `substitute` / `apply` appear only inside an unreduced `wp_rule`
        // term and are eliminated by `libsugar::wp` before any solver
        // or compiler backend sees the formula. Reaching this arm is a bug.
        // TODO(wp-as-formula PR1+): teach sugar-ir-codegen to emit this arm.
        Formula::Substitute { .. } | Formula::Apply { .. } => {
            unreachable!(
                "wp-rule schema node reached the SMT-LIB formula emitter; \
                 must be reduced via libsugar::wp first"
            )
        }
        Formula::DivergenceBetween { .. } => {
            unreachable!(
                "platform divergence formula reached the SMT-LIB formula emitter; \
                 stage 4 must lower it before backend compilation"
            )
        }
    }
}

fn emit_string_theory_atomic(name: &str, args: &[Term]) -> Result<Option<String>, CompileError> {
    // STRING-ROUTED EQUALITY (G1 conjoin shape): `=` over a string const and a
    // callresult ctor lives in string theory so it stays sort-compatible with
    // a `str.chars-in-set` universe row over the SAME subject. The gate
    // (`routes_to_string_theory`) lives in the hand-maintained
    // `literal_encoding` module; see its doc for the deliberate exclusions
    // that keep the legacy Python opaque-Int regime byte-identical.
    if name == "=" && crate::literal_encoding::routes_to_string_theory(name, args) {
        return Ok(Some(format!(
            "(= {} {})",
            emit_string_term(&args[0]),
            emit_string_term(&args[1])
        )));
    }
    match name {
        "contains" if args.len() == 2 => Ok(Some(format!(
            "(str.contains {} {})",
            emit_string_term(&args[0]),
            emit_string_term(&args[1])
        ))),
        "prefix-of" if args.len() == 2 => Ok(Some(format!(
            "(str.prefixof {} {})",
            emit_string_term(&args[0]),
            emit_string_term(&args[1])
        ))),
        "suffix-of" if args.len() == 2 => Ok(Some(format!(
            "(str.suffixof {} {})",
            emit_string_term(&args[0]),
            emit_string_term(&args[1])
        ))),
        "str.is_ascii" if args.len() == 1 => Ok(Some(format!(
            "(str.in_re {} (re.* (re.range \"\\u{{0}}\" \"\\u{{7f}}\")))",
            emit_string_term(&args[0])
        ))),
        "str.is_ascii_alphabetic" if args.len() == 1 => Ok(Some(format!(
            "(str.in_re {} (re.union (re.range \"A\" \"Z\") (re.range \"a\" \"z\")))",
            emit_string_term(&args[0])
        ))),
        "str.is_ascii_alphanumeric" if args.len() == 1 => Ok(Some(format!(
            "(str.in_re {} (re.union (re.range \"0\" \"9\") (re.union (re.range \"A\" \"Z\") (re.range \"a\" \"z\"))))",
            emit_string_term(&args[0])
        ))),
        "str.is_ascii_digit" if args.len() == 1 => Ok(Some(format!(
            "(str.in_re {} (re.range \"0\" \"9\"))",
            emit_string_term(&args[0])
        ))),
        "str.is_ascii_octdigit" if args.len() == 1 => Ok(Some(format!(
            "(str.in_re {} (re.range \"0\" \"7\"))",
            emit_string_term(&args[0])
        ))),
        "str.is_ascii_lowercase" if args.len() == 1 => Ok(Some(format!(
            "(str.in_re {} (re.range \"a\" \"z\"))",
            emit_string_term(&args[0])
        ))),
        "str.is_ascii_uppercase" if args.len() == 1 => Ok(Some(format!(
            "(str.in_re {} (re.range \"A\" \"Z\"))",
            emit_string_term(&args[0])
        ))),
        "str.is_ascii_hexdigit" if args.len() == 1 => Ok(Some(format!(
            "(str.in_re {} (re.union (re.range \"0\" \"9\") (re.union (re.range \"A\" \"F\") (re.range \"a\" \"f\"))))",
            emit_string_term(&args[0])
        ))),
        "str.is_ascii_punctuation" if args.len() == 1 => Ok(Some(format!(
            "(str.in_re {} (re.union (re.range \"!\" \"/\") (re.union (re.range \":\" \"@\") (re.union (re.range \"[\" \"`\") (re.range \"{{\" \"~\")))))",
            emit_string_term(&args[0])
        ))),
        "str.is_ascii_graphic" if args.len() == 1 => Ok(Some(format!(
            "(str.in_re {} (re.range \"!\" \"~\"))",
            emit_string_term(&args[0])
        ))),
        "str.is_ascii_whitespace" if args.len() == 1 => Ok(Some(format!(
            "(str.in_re {} (re.union (re.union (re.union (re.union (re.range \" \" \" \") (re.range \"\\u{{9}}\" \"\\u{{9}}\")) (re.range \"\\u{{a}}\" \"\\u{{a}}\")) (re.range \"\\u{{c}}\" \"\\u{{c}}\")) (re.range \"\\u{{d}}\" \"\\u{{d}}\")))",
            emit_string_term(&args[0])
        ))),
        "str.is_ascii_control" if args.len() == 1 => Ok(Some(format!(
            "(str.in_re {} (re.union (re.range \"\\u{{0}}\" \"\\u{{1f}}\") (re.range \"\\u{{7f}}\" \"\\u{{7f}}\")))",
            emit_string_term(&args[0])
        ))),
        // str.chars-in-set: arg[0] = subject (String-sorted term), arg[1] = charset constant.
        // The charset is a String const whose value is the set of allowed characters.
        // Renders as: (str.in_re <subject> (re.* (re.union (str.to_re "c1") (str.to_re "c2") ...)))
        // Single-char set degenerates to: (str.in_re <subject> (re.* (str.to_re "c")))
        "str.chars-in-set" if args.len() == 2 => {
            let charset: Vec<char> = match &args[1] {
                Term::Const { value, sort }
                    if matches!(sort, Sort::Primitive { name } if name == "String") =>
                {
                    if let serde_json::Value::String(s) = value {
                        let mut chars: Vec<char> = s.chars().collect();
                        chars.sort_unstable();
                        chars.dedup();
                        chars
                    } else {
                        return Err(strong_tier_refusal(
                            name,
                            "charset payload is not a String value",
                        ));
                    }
                }
                _ => {
                    return Err(strong_tier_refusal(
                        name,
                        "expected arg[1] to be a String const charset",
                    ));
                }
            };
            if charset.is_empty() {
                return Err(strong_tier_refusal(
                    name,
                    "empty charset has no SMT-LIB membership encoding",
                ));
            }
            // Build the RE union over individual chars using str.to_re.
            // SMT-LIB string literals: see smt_string_char (printable ASCII
            // verbatim, everything else \u{...}).
            let char_re = |ch: char| -> String {
                let esc = smt_string_char(ch);
                format!("(str.to_re \"{}\")", esc)
            };
            let inner = if charset.len() == 1 {
                char_re(charset[0])
            } else {
                // Fold right into nested re.union pairs: (re.union c1 (re.union c2 ...))
                let mut iter = charset.iter().rev();
                let mut acc = char_re(*iter.next().unwrap());
                for ch in iter {
                    acc = format!("(re.union {} {})", char_re(*ch), acc);
                }
                acc
            };
            Ok(Some(format!(
                "(str.in_re {} (re.* {}))",
                emit_string_term(&args[0]),
                inner
            )))
        }
        // str.chars-not-in-set: arg[0] = subject (String-sorted term), arg[1] =
        // forbidden-charset constant. The complement universe row: derived from
        // a vendor translate/maketrans table, it swears the subject contains
        // NONE of the listed characters. Renders as a conjunction of negated
        // str.contains atoms, one per forbidden char -- the exact semantics of
        // a total byte-translate that maps each listed char away.
        "str.chars-not-in-set" if args.len() == 2 => {
            let charset: Vec<char> = match &args[1] {
                Term::Const { value, sort }
                    if matches!(sort, Sort::Primitive { name } if name == "String") =>
                {
                    if let serde_json::Value::String(s) = value {
                        let mut chars: Vec<char> = s.chars().collect();
                        chars.sort_unstable();
                        chars.dedup();
                        chars
                    } else {
                        return Err(strong_tier_refusal(
                            name,
                            "forbidden-charset payload is not a String value",
                        ));
                    }
                }
                _ => {
                    return Err(strong_tier_refusal(
                        name,
                        "expected arg[1] to be a String const forbidden charset",
                    ));
                }
            };
            if charset.is_empty() {
                return Err(strong_tier_refusal(
                    name,
                    "empty forbidden charset has no SMT-LIB complement encoding",
                ));
            }
            let subject = emit_string_term(&args[0]);
            let not_contains = |ch: char| -> String {
                let esc = smt_string_char(ch);
                format!("(not (str.contains {} \"{}\"))", subject, esc)
            };
            if charset.len() == 1 {
                Ok(Some(not_contains(charset[0])))
            } else {
                let parts: Vec<String> = charset.iter().map(|ch| not_contains(*ch)).collect();
                Ok(Some(format!("(and {})", parts.join(" "))))
            }
        }
        // ── Base64 STRONG TIER (paper 26 — "THE seam between tiers") ──────────
        // str.eq-bv-blocks: arg[0] = subject (the callresult String term),
        //                   arg[1] = a String const carrying the strong-tier
        //                            payload JSON walked from the vendor source.
        //
        // Payload JSON (all fields walked from Base64.java; NOTHING hand-authored):
        //   { "input_bytes": [98,97,114],            // the literal's UTF-8 bytes
        //     "vars": ["b0","b1","b2"],              // byte var names (parallel)
        //     "per_char": [ <bv-index-tree>, ... ],  // one index expr per output char
        //     "table": [65,66,...,47] }              // 64 codepoints, source order
        //
        // We render a SELF-CONTAINED string equality binding the subject to the
        // concatenation of per-character codepoints, computed by the solver from
        // the walked bit arithmetic. The byte vars are `let`-bound to the literal
        // bytes, so NO top-level declaration is emitted (additive: invisible to
        // the declaration-collection passes). Each index tree is a bv-expression
        // over the byte vars using the same `emit_bv32_term` vocabulary as G2;
        // the index selects a codepoint from the walked table via a nested `ite`,
        // and `str.from_code` bridges the codepoint Int to a one-char String.
        //
        //   (= <subject>
        //      (let ((b0 #x..)(b1 #x..)(b2 #x..))
        //         (str.++ (str.from_code <table-ite over per_char[0]>) ... )))
        //
        // GOOD claim → sat (z3 computes "YmFy"); alphabet-valid-but-WRONG claim
        // ("ZmFy") → unsat. The weak str.chars-in-set row cannot refute "ZmFy";
        // only these equations can. That refutation is the entire point.
        "str.eq-bv-blocks" if args.len() == 2 => Ok(Some(emit_b64_strong_blocks(
            &args[0], None, &args[1],
        )?)),
        "str.eq-bv-blocks" if args.len() == 3 => Ok(Some(emit_b64_strong_blocks(
            &args[0],
            Some(&args[1]),
            &args[2],
        )?)),
        // ── @Pattern REGEX UNIVERSE (Door 3 — regular-language membership) ─────
        // str.in-regex: arg[0] = subject (the callresult String term — the value
        //               the consumer claims is valid), arg[1] = a String const
        //               carrying the vendor's `@Pattern(regexp="…")` literal,
        //               walked verbatim from the annotation's AST.
        //
        // The regex literal is parsed into a regex AST and lowered to z3's native
        // RegLan theory: literals → str.to_re, char classes [a-z] → re.range/re.union,
        // '.' → re.allchar, '*' '+' '?' '{n,m}' → re.* re.+ re.opt re.loop,
        // alternation '|' → re.union, concatenation → re.++, anchors ^$ → full-match
        // (z3 str.in_re is already whole-string, anchors are identity). The lowering
        // authority lives in `crate::regex_regln` — a single place, so the supported
        // subset and its refusals are decided once.
        //
        // REFUSE BY NAME (not a regular language → never approximated): backreferences,
        // lookahead/behind, possessive/atomic groups. The parser returns Err with the
        // offending feature named; we propagate that as a compile refusal so the
        // atom never falls through to an unconstrained predicate.
        // The Java walker performs the SAME non-regular scan at walk time and refuses
        // to register, so a non-regular pattern never reaches this arm in practice;
        // this None is the defense-in-depth backstop.
        //
        // GOOD: a matching input's validity claim → str.in_re holds → sat → discharged.
        // BAD: a non-matching input claimed valid → str.in_re false → unsat →
        //      unsatisfied BY THE WALKED REGEX (membership-driven, not a within-test
        //      contradiction). The classic spotlight: a `@Pattern` an author believes
        //      rejects an injection but whose walked language ACCEPTS it.
        "str.in-regex" if args.len() == 2 => {
            let regex = match &args[1] {
                Term::Const {
                    value: serde_json::Value::String(s),
                    sort: Sort::Primitive { name },
                } if name == "String" => s,
                _ => {
                    return Err(strong_tier_refusal(
                        name,
                        "expected arg[1] to be a String const regex literal",
                    ));
                }
            };
            // Lower the regex literal to a z3 RegLan term. A non-regular feature
            // (or a malformed literal) is a typed refusal.
            let regln = crate::regex_regln::regex_to_regln(regex)
                .map_err(|e| strong_tier_refusal(name, e))?;
            Ok(Some(format!(
                "(str.in_re {} {})",
                emit_string_term(&args[0]),
                regln
            )))
        }
        _ if is_string_theory_atomic_predicate(name) => Err(strong_tier_refusal(
            name,
            format!("unsupported argument shape with {} args", args.len()),
        )),
        _ => Ok(None),
    }
}

/// Render the Base64 strong-tier `str.eq-bv-blocks` atom.
///
/// See the call-site comment in `emit_string_theory_atomic` for the payload
/// shape. Refuses loudly if the payload is malformed or cannot be encoded;
/// falling through to the generic predicate path would silently weaken the
/// strong-tier row.
fn emit_b64_strong_blocks(
    subject: &Term,
    input: Option<&Term>,
    payload: &Term,
) -> Result<String, CompileError> {
    // Payload is a String const carrying the JSON.
    let json_str = match payload {
        Term::Const {
            value: serde_json::Value::String(s),
            sort: Sort::Primitive { name },
        } if name == "String" => s,
        _ => {
            return Err(strong_tier_refusal(
                "str.eq-bv-blocks",
                "expected payload to be a String const carrying JSON",
            ));
        }
    };
    let body = render_b64_blocks_body_with_input(json_str, input).ok_or_else(|| {
        strong_tier_refusal(
            "str.eq-bv-blocks",
            "malformed or non-encodable strong-tier block payload JSON",
        )
    })?;
    Ok(format!("(= {} {})", emit_string_term(subject), body))
}

/// Render the RHS string expression of a Base64 strong-tier block payload — the
/// `(let (...) (str.++ ...))` term whose value is the encoded output string,
/// computed by the solver from the walked bit arithmetic. Public so the derive
/// path (`sugar derive` over a strong-tier universe) can reuse the exact same
/// rendering, keeping the derived string and the discharge check byte-aligned.
pub fn render_b64_blocks_body(payload_json: &str) -> Option<String> {
    render_b64_blocks_body_with_input(payload_json, None)
}

fn render_b64_blocks_body_with_input(payload_json: &str, input: Option<&Term>) -> Option<String> {
    let payload: serde_json::Value = serde_json::from_str(payload_json).ok()?;

    let vars = payload.get("vars")?.as_array()?;
    let per_char = payload.get("per_char")?.as_array()?;
    let table = payload.get("table")?.as_array()?;

    // Build the byte-var substitution. Old payloads carry concrete
    // `input_bytes`; general body universes carry a separate input String term
    // and derive bN from `(str.at input N)` in solver-land.
    let mut subst: std::collections::HashMap<String, String> = std::collections::HashMap::new();
    let mut let_binds: Vec<String> = Vec::new();
    if let Some(input_bytes) = payload.get("input_bytes").and_then(|v| v.as_array()) {
        if input_bytes.len() != vars.len() {
            return None;
        }
        for (vname_v, byte_v) in vars.iter().zip(input_bytes.iter()) {
            let vname = vname_v.as_str()?;
            let b = byte_v.as_i64()?;
            let hex = i32_to_bv32_hex(b);
            subst.insert(vname.to_string(), hex.clone());
            let_binds.push(format!("({} {})", vname, hex));
        }
    } else {
        let input_smt = emit_string_term(input?);
        for (idx, vname_v) in vars.iter().enumerate() {
            let vname = vname_v.as_str()?;
            let byte = format!(
                "((_ int2bv 32) (str.to_code (str.at {} {})))",
                input_smt, idx
            );
            subst.insert(vname.to_string(), byte.clone());
            let_binds.push(format!("({} {})", vname, byte));
        }
    }

    // Build the table-lookup `ite` chain ONCE as a parameterised closure over an
    // already-rendered BV index expression. Each table entry is a walked
    // codepoint (Int), keyed by its source-order index (the BV index value).
    let table_ite = |index_smt: &str| -> Option<String> {
        // Innermost default: codepoint 0 (unreachable for a valid 6-bit index;
        // present so the ite is total). We fold from the last entry inward.
        let mut acc = "0".to_string();
        for (idx, cp_v) in table.iter().enumerate().rev() {
            let cp = cp_v.as_i64()?;
            let idx_hex = i32_to_bv32_hex(idx as i64);
            acc = format!("(ite (= {} {}) {} {})", index_smt, idx_hex, cp, acc);
        }
        Some(acc)
    };

    // Render each output character: str.from_code over the table-selected codepoint.
    // We render the index tree DIRECTLY from raw JSON (not via IrTerm) because the
    // walked index nodes carry no `sort` field — deserializing into IrTerm::Const
    // would fail. This mirrors `derive_query::render_bv_term`.
    let mut char_terms: Vec<String> = Vec::new();
    for index_tree in per_char {
        let index_smt = render_bv_index_json(index_tree, &subst)?;
        let cp_smt = table_ite(&index_smt)?;
        char_terms.push(format!("(str.from_code {})", cp_smt));
    }
    // PHASE 2 mod-3 tail: the '=' pad chars. These are NOT table-indexed (the pad
    // is outside the 64-entry alphabet); their codepoint is the AST-resolved pad
    // value the Java walker pinned (e.g. PAD_DEFAULT='='=61). Absent field (the
    // mod-0 and urlsafe-tail cases) → no extra chars → byte-identical to before.
    if let Some(pad_chars) = payload.get("pad_chars").and_then(|v| v.as_array()) {
        for cp_v in pad_chars {
            let cp = cp_v.as_i64()?;
            char_terms.push(format!("(str.from_code {})", cp));
        }
    }
    if char_terms.is_empty() {
        return None;
    }

    let concat = if char_terms.len() == 1 {
        char_terms.pop().unwrap()
    } else {
        format!("(str.++ {})", char_terms.join(" "))
    };

    if let_binds.is_empty() {
        Some(concat)
    } else {
        Some(format!("(let ({}) {})", let_binds.join(" "), concat))
    }
}

/// Render a bv-expression tree from RAW JSON (var/const/ctor nodes) into an
/// SMT-LIB (_ BitVec 32) expression, substituting `var` nodes from `subst`.
/// Const nodes here carry no `sort` field (they are bare `{"kind":"const",
/// "value":N}`), so we cannot reuse `emit_bv32_term`. The op vocabulary is the
/// same one the G2 walker / derive path use.
fn render_bv_index_json(
    node: &serde_json::Value,
    subst: &std::collections::HashMap<String, String>,
) -> Option<String> {
    let kind = node.get("kind")?.as_str()?;
    match kind {
        "var" => {
            let name = node.get("name")?.as_str()?;
            subst.get(name).cloned()
        }
        "const" => {
            let v = node.get("value")?.as_i64()?;
            Some(i32_to_bv32_hex(v))
        }
        "ctor" => {
            let name = node.get("name")?.as_str()?;
            let args = node.get("args")?.as_array()?;
            let bin = |smt_op: &str| -> Option<String> {
                if args.len() != 2 {
                    return None;
                }
                let l = render_bv_index_json(&args[0], subst)?;
                let r = render_bv_index_json(&args[1], subst)?;
                Some(format!("({} {} {})", smt_op, l, r))
            };
            match name {
                "bv32.and" => bin("bvand"),
                "bv32.or" => bin("bvor"),
                "bv32.shl" => bin("bvshl"),
                "bv32.lshr" => bin("bvlshr"),
                "bv32.add" => bin("bvadd"),
                _ => None, // any other op = unwalkable here; atomic callers refuse
            }
        }
        _ => None,
    }
}

/// Render a CRC value-pin bv32 tree from RAW JSON (var/const/ctor nodes) into an
/// SMT-LIB `(_ BitVec 32)` expression. The walked crc-FOL reuses the SAME bv32
/// node shapes the recurrence/numeric walkers emit, but its const nodes carry NO
/// `sort` field (bare `{"kind":"const","value":N}`), so it cannot be rendered via
/// `emit_bv32_term` (which needs IrTerm). The op vocabulary is the full bv32 set
/// the value-pin walk produces: the table's folded ite-chains (ite over eq/ne)
/// and the stateful update's xor / lshr / and / xor-with-(-1) inversion.
fn render_crc_bv_json(
    node: &serde_json::Value,
    subst: &std::collections::HashMap<String, String>,
) -> Option<String> {
    let kind = node.get("kind")?.as_str()?;
    match kind {
        "var" => subst.get(node.get("name")?.as_str()?).cloned(),
        "const" => Some(i32_to_bv32_hex(node.get("value")?.as_i64()?)),
        "ctor" => {
            let name = node.get("name")?.as_str()?;
            let args = node.get("args")?.as_array()?;
            let bin = |op: &str| -> Option<String> {
                if args.len() != 2 {
                    return None;
                }
                let l = render_crc_bv_json(&args[0], subst)?;
                let r = render_crc_bv_json(&args[1], subst)?;
                Some(format!("({} {} {})", op, l, r))
            };
            match name {
                "bv32.and" => bin("bvand"),
                "bv32.or" => bin("bvor"),
                "bv32.xor" => bin("bvxor"),
                "bv32.add" => bin("bvadd"),
                "bv32.mul" => bin("bvmul"),
                "bv32.shl" => bin("bvshl"),
                "bv32.lshr" => bin("bvlshr"),
                "bv32.neg" if args.len() == 1 => {
                    let a = render_crc_bv_json(&args[0], subst)?;
                    Some(format!("(bvneg {})", a))
                }
                "bv32.ite" if args.len() == 3 => {
                    let c = render_crc_bv_json_bool(&args[0], subst)?;
                    let t = render_crc_bv_json(&args[1], subst)?;
                    let f = render_crc_bv_json(&args[2], subst)?;
                    Some(format!("(ite {} {} {})", c, t, f))
                }
                _ => None,
            }
        }
        _ => None,
    }
}

/// Render the Bool-sorted condition of a CRC value-pin ite (eq/ne/slt over bv32).
fn render_crc_bv_json_bool(
    node: &serde_json::Value,
    subst: &std::collections::HashMap<String, String>,
) -> Option<String> {
    let name = node.get("name")?.as_str()?;
    let args = node.get("args")?.as_array()?;
    if args.len() != 2 {
        return None;
    }
    let l = render_crc_bv_json(&args[0], subst)?;
    let r = render_crc_bv_json(&args[1], subst)?;
    match name {
        "bv32.eq" => Some(format!("(= {} {})", l, r)),
        "bv32.ne" => Some(format!("(not (= {} {}))", l, r)),
        "bv32.slt" => Some(format!("(bvslt {} {})", l, r)),
        "bv32.ule" => Some(format!("(bvule {} {})", l, r)),
        _ => None,
    }
}

/// Render an MT seeding value-pin SSA payload as a nested `let` chain.
///
/// Payload shape (emitted by the Java `MtSeedingWalker`):
/// ```json
/// { "binds":  [ {"name":"w0","tree":<bv32-json>}, {"name":"w1","tree":<bv32-json>}, ... ],
///   "result": <bv32-json referencing bind names via {"kind":"var","name":"wK"}> }
/// ```
/// Each bind's `tree` may reference any EARLIER bind name as a `var` node. We
/// build `(let ((w0 t0)) (let ((w1 t1)) ... result))` so the recurrence shares
/// sub-terms (linear SMT size) and every bind is in scope for all later binds.
///
/// `var` nodes render to the bare SMT symbol (the bind name). The per-bind trees
/// use the SAME bv32 vocabulary as the CRC pin (`render_crc_bv_json`), so adding
/// this path touches no existing rendering. Malformed payload rendering still
/// returns `None` at this low-level helper boundary; atomic emitters convert that
/// to a loud `CompileError` instead of falling through to a generic predicate.
fn render_mt_let_chain(payload: &serde_json::Value) -> Option<String> {
    let binds = payload.get("binds")?.as_array()?;
    let result = payload.get("result")?;

    // `var` nodes carry the SSA bind name; render it as the bare SMT symbol by
    // mapping each name to itself. (render_crc_bv_json's `var` arm does
    // `subst.get(name)`, so an identity map yields the symbol verbatim.)
    let mut subst: std::collections::HashMap<String, String> = std::collections::HashMap::new();

    // Render every bind RHS first (each in scope of the binds declared before it),
    // accumulating the (name rhs) pairs, then fold the nested lets inside-out.
    let mut pairs: Vec<(String, String)> = Vec::with_capacity(binds.len());
    for b in binds {
        let bname = b.get("name")?.as_str()?.to_string();
        let tree = b.get("tree")?;
        let rhs = render_crc_bv_json(tree, &subst)?;
        // The bind name becomes referenceable by later binds and the result.
        subst.insert(bname.clone(), bname.clone());
        pairs.push((bname, rhs));
    }
    let result_smt = render_crc_bv_json(result, &subst)?;

    // Fold inside-out: innermost is `result`, wrap each bind from last to first.
    let mut acc = result_smt;
    for (bname, rhs) in pairs.into_iter().rev() {
        acc = format!("(let (({} {})) {})", bname, rhs, acc);
    }
    Some(acc)
}

fn is_string_theory_atomic_predicate(name: &str) -> bool {
    matches!(
        name,
        "contains"
            | "prefix-of"
            | "suffix-of"
            | "str.is_ascii"
            | "str.is_ascii_alphabetic"
            | "str.is_ascii_alphanumeric"
            | "str.is_ascii_digit"
            | "str.is_ascii_octdigit"
            | "str.is_ascii_lowercase"
            | "str.is_ascii_uppercase"
            | "str.is_ascii_hexdigit"
            | "str.is_ascii_punctuation"
            | "str.is_ascii_graphic"
            | "str.is_ascii_whitespace"
            | "str.is_ascii_control"
            | "str.chars-in-set"
            | "str.chars-not-in-set"
            | "str.eq-bv-blocks"
            | "str.in-regex"
    )
}

// ── G2: BV32 theory emitter ───────────────────────────────────────────────
//
// `int32.eq-bv-expr(subject_ctor, bv_tree)` asserts that the result of the
// subject call equals the BV expression tree evaluated at the subject's args.
//
// The BV tree uses `var` nodes whose names are the method parameter names from
// the vendor source. The subject ctor's args carry the call-site int literals
// in parameter order. We build a substitution: param_name → i32 literal.
//
// The rendered SMT-LIB:
//   (= (|call:abs| #x80000000) (ite (bvslt #x80000000 #x00000000) (bvneg #x80000000) #x80000000))
//
// BV operator mapping:
//   bv32.ite  → ite          (standard ternary; condition is Bool-sorted bvslt)
//   bv32.slt  → bvslt        (signed less-than; yields Bool in SMT-LIB)
//   bv32.neg  → bvneg        (two's-complement negation)
//   bv32.and  → bvand        (bitwise AND)

/// Render an i64 (interpreted as i32 for BV32) as an SMT-LIB bitvector hex literal.
/// `#x` followed by exactly 8 hex digits (32-bit two's complement).
fn i32_to_bv32_hex(v: i64) -> String {
    let bits = v as i32 as u32;
    format!("#x{:08x}", bits)
}

/// Render a BV32 expression tree, substituting var nodes from `subst`.
/// Returns None if the tree contains an unrecognised node shape.
fn emit_bv32_term(
    term: &Term,
    subst: &std::collections::HashMap<String, String>,
) -> Option<String> {
    match term {
        Term::Var { name } => {
            // Prefer the substitution (used when vars are let-bound to bv32 hex
            // literals in the strong-universe path). Fall back to the raw SMT
            // symbol so `emit_bv32_term` can be called from `emit_term` with an
            // empty substitution for symbolic bv32 sub-expressions.
            Some(
                subst
                    .get(name.as_str())
                    .cloned()
                    .unwrap_or_else(|| smt_quote(name)),
            )
        }
        Term::Const { value, .. } => {
            let v = match value {
                serde_json::Value::Number(n) => n.as_i64()?,
                _ => return None,
            };
            Some(i32_to_bv32_hex(v))
        }
        Term::Ctor { name, args } => match name.as_str() {
            "bv32.ite" if args.len() == 3 => {
                // condition (Bool-sorted bvslt), true-branch, false-branch
                let cond = emit_bv32_bool_term(&args[0], subst)?;
                let tb = emit_bv32_term(&args[1], subst)?;
                let fb = emit_bv32_term(&args[2], subst)?;
                Some(format!("(ite {} {} {})", cond, tb, fb))
            }
            "bv32.neg" if args.len() == 1 => {
                let inner = emit_bv32_term(&args[0], subst)?;
                Some(format!("(bvneg {})", inner))
            }
            "bv32.and" if args.len() == 2 => {
                let l = emit_bv32_term(&args[0], subst)?;
                let r = emit_bv32_term(&args[1], subst)?;
                Some(format!("(bvand {} {})", l, r))
            }
            // ── Base64 strong-tier ops (paper 26 seam). Each maps 1:1 to a Java
            // operator read from the vendor's Base64.java AST:
            //   bv32.or   → bvor    (Java `|`, the alphabet-block OR — tail path)
            //   bv32.shl  → bvshl   (Java `<<`, the accumulation/extraction shifts)
            //   bv32.lshr → bvlshr  (Java `>>`, the work-area extraction shifts)
            //   bv32.add  → bvadd   (Java `+`, the per-byte accumulation `(w<<8)+b`)
            "bv32.or" if args.len() == 2 => {
                let l = emit_bv32_term(&args[0], subst)?;
                let r = emit_bv32_term(&args[1], subst)?;
                Some(format!("(bvor {} {})", l, r))
            }
            "bv32.shl" if args.len() == 2 => {
                let l = emit_bv32_term(&args[0], subst)?;
                let r = emit_bv32_term(&args[1], subst)?;
                Some(format!("(bvshl {} {})", l, r))
            }
            "bv32.lshr" if args.len() == 2 => {
                let l = emit_bv32_term(&args[0], subst)?;
                let r = emit_bv32_term(&args[1], subst)?;
                Some(format!("(bvlshr {} {})", l, r))
            }
            "bv32.add" if args.len() == 2 => {
                let l = emit_bv32_term(&args[0], subst)?;
                let r = emit_bv32_term(&args[1], subst)?;
                Some(format!("(bvadd {} {})", l, r))
            }
            // ── Recurrence strong-tier ops (paper 26 keystone). Each maps 1:1 to a
            // Java operator read from the vendor's recurrence AST (e.g. Mersenne
            // Twister's `1812433253 * (mt ^ (mt >> 30))` seeding recurrence):
            //   bv32.mul  → bvmul   (Java `*`, the LCG-style multiply in the seed mix)
            //   bv32.xor  → bvxor   (Java `^`, the fold and the twist xors)
            "bv32.mul" if args.len() == 2 => {
                let l = emit_bv32_term(&args[0], subst)?;
                let r = emit_bv32_term(&args[1], subst)?;
                Some(format!("(bvmul {} {})", l, r))
            }
            "bv32.xor" if args.len() == 2 => {
                let l = emit_bv32_term(&args[0], subst)?;
                let r = emit_bv32_term(&args[1], subst)?;
                Some(format!("(bvxor {} {})", l, r))
            }
            _ => None,
        },
        _ => None,
    }
}

/// Render a BV32 Bool-sorted sub-expression (comparison operators).
fn emit_bv32_bool_term(
    term: &Term,
    subst: &std::collections::HashMap<String, String>,
) -> Option<String> {
    match term {
        Term::Ctor { name, args } => match name.as_str() {
            "bv32.slt" if args.len() == 2 => {
                let l = emit_bv32_term(&args[0], subst)?;
                let r = emit_bv32_term(&args[1], subst)?;
                Some(format!("(bvslt {} {})", l, r))
            }
            "bv32.ule" if args.len() == 2 => {
                let l = emit_bv32_term(&args[0], subst)?;
                let r = emit_bv32_term(&args[1], subst)?;
                Some(format!("(bvule {} {})", l, r))
            }
            // Equality/disequality on bv32 — the low-bit MAG01 gate condition
            // (`y & 1 == 1`) in the recurrence twist renders to these.
            "bv32.eq" if args.len() == 2 => {
                let l = emit_bv32_term(&args[0], subst)?;
                let r = emit_bv32_term(&args[1], subst)?;
                Some(format!("(= {} {})", l, r))
            }
            "bv32.ne" if args.len() == 2 => {
                let l = emit_bv32_term(&args[0], subst)?;
                let r = emit_bv32_term(&args[1], subst)?;
                Some(format!("(not (= {} {}))", l, r))
            }
            _ => None,
        },
        _ => None,
    }
}

/// Collect unique var names from a BV term in DFS pre-order.
fn collect_bv32_vars(term: &Term, out: &mut Vec<String>) {
    match term {
        Term::Var { name } => {
            let s = name.to_string();
            if !out.contains(&s) {
                out.push(s);
            }
        }
        Term::Ctor { args, .. } => {
            for a in args {
                collect_bv32_vars(a, out);
            }
        }
        Term::Const { .. } => {}
        _ => {}
    }
}

/// Render a subject ctor as a BV32 application: `(|call:abs| #x80000000)`.
/// Every ctor arg must be an integer const (rendered as a BV32 hex literal).
fn render_bv32_subject(subject: &Term) -> Option<String> {
    let (subj_name, subj_args) = match subject {
        Term::Ctor { name, args } => (name.as_str(), args.as_slice()),
        _ => return None,
    };
    let subj_bv_args: Vec<String> = subj_args
        .iter()
        .map(|a| match a {
            Term::Const { value, .. } => value.as_i64().map(i32_to_bv32_hex),
            _ => None,
        })
        .collect::<Option<Vec<_>>>()?;
    if subj_bv_args.is_empty() {
        Some(smt_quote(subj_name).to_string())
    } else {
        Some(format!(
            "({} {})",
            smt_quote(subj_name),
            subj_bv_args.join(" ")
        ))
    }
}

/// G2: BV32-theory atom emitter — handles both bv32 atom shapes.
///
/// `int32.eq-bv-expr(subject_ctor, bv_tree)`:
///   `args[0]` = subject ctor (`call:abs(i:-2147483648)`)
///   `args[1]` = BV expression tree (`bv32.ite(bv32.slt(a, 0), bv32.neg(a), a)`)
///   Builds substitution param_name[i] → BV32 hex of subject.args[i];
///   renders `(= subject_bv bv_expr)`.
///
/// `int32.eq-const(subject_ctor, IntConst)` (synthetic, from bv32 contagion):
///   the sworn sibling equality promoted to bv32; renders `(= subject_bv hex)`.
fn emit_bv32_theory_atomic(name: &str, args: &[Term]) -> Result<Option<String>, CompileError> {
    if !crate::literal_encoding::routes_to_bv32_theory(name) {
        return Ok(None);
    }
    // ── CRC value-pin (paper 26 — connect the folded table to the value) ──
    // `crc32.eq-walked(asserted_int_const, walked_bv_tree)`:
    //   args[0] = the test's asserted CRC value (an Int const; truncated to bv32)
    //   args[1] = the WALKED closed crc-FOL — the symbolic table+update+inversion
    //             computation walked from the vendor's CRC32C AST. It contains no
    //             free vars (the input is literal, the table is folded), so it
    //             renders with an EMPTY substitution and constant-folds in z3 to
    //             the genuine CRC value.
    // Rendered: `(= <asserted_hex> <walked_smt>)`. GOOD (vendor-sworn value) → sat
    // → discharged; BAD (wrong value) → unsat → unsatisfied BY THE WALKED
    // COMPUTATION (a single equation, not a within-test contradiction).
    if name == "crc32.eq-walked" && args.len() == 2 {
        let asserted = match &args[0] {
            Term::Const { value, .. } => value
                .as_i64()
                .map(i32_to_bv32_hex)
                .ok_or_else(|| strong_tier_refusal(name, "expected arg[0] to be an Int const"))?,
            _ => {
                return Err(strong_tier_refusal(
                    name,
                    "expected arg[0] to be an Int const",
                ));
            }
        };
        // args[1] is a String const carrying the walked crc-FOL JSON (its bv32
        // nodes have no `sort` field, so they are rendered from RAW JSON, not via
        // emit_bv32_term — mirroring render_b64_blocks_body).
        let json_str = match &args[1] {
            Term::Const {
                value: serde_json::Value::String(s),
                sort: Sort::Primitive { name },
            } if name == "String" => s,
            _ => {
                return Err(strong_tier_refusal(
                    name,
                    "expected arg[1] to be a String const carrying walked CRC JSON",
                ));
            }
        };
        let node: serde_json::Value = serde_json::from_str(json_str)
            .map_err(|e| strong_tier_refusal(name, format!("malformed walked CRC JSON: {e}")))?;
        let empty: std::collections::HashMap<String, String> = std::collections::HashMap::new();
        let walked = render_crc_bv_json(&node, &empty).ok_or_else(|| {
            strong_tier_refusal(name, "walked CRC JSON contains a non-encodable bv32 node")
        })?;
        return Ok(Some(format!("(= {} {})", asserted, walked)));
    }
    // ── MT seeding value-pin (paper 26 — inter-procedural seed-state walk) ──
    // `mt32.eq-seeded(asserted_int_const, ssa_let_chain_payload)`:
    //   args[0] = the test's asserted reference value (Int const; truncated to bv32)
    //   args[1] = a String const carrying the SSA `let`-chain JSON. The MT seeding
    //             chain (624-word initializeState + mixSeedAndState + mixState) and
    //             the twist (the 624-word regeneration in next()) form a recurrence
    //             where each word references earlier words; inlining the bv32 tree
    //             would blow up exponentially. Instead the Java walker emits the
    //             computation in SSA form — a list of named binds `{name, tree}`
    //             where each `tree` references earlier names via `var` nodes — plus
    //             a `result` tree. We render it as a NESTED `let` chain so every
    //             bind sees all prior binds and sub-terms are shared (linear size).
    //   No free vars (seed is the literal Nishimura seed, bounds are concrete), so
    //   it constant-folds in z3 to the genuine reference value.
    // Rendered: `(= asserted_hex (let ((w0 t0)) (let ((w1 t1)) ... result)))`.
    // GOOD (vendor-sworn value) → sat → discharged; BAD (wrong value) → unsat →
    // unsatisfied BY THE WALKED RECURRENCE (a single equation, not a contradiction).
    if name == "mt32.eq-seeded" && args.len() == 2 {
        let asserted = match &args[0] {
            Term::Const { value, .. } => value
                .as_i64()
                .map(i32_to_bv32_hex)
                .ok_or_else(|| strong_tier_refusal(name, "expected arg[0] to be an Int const"))?,
            _ => {
                return Err(strong_tier_refusal(
                    name,
                    "expected arg[0] to be an Int const",
                ));
            }
        };
        let json_str = match &args[1] {
            Term::Const {
                value: serde_json::Value::String(s),
                sort: Sort::Primitive { name },
            } if name == "String" => s,
            _ => {
                return Err(strong_tier_refusal(
                    name,
                    "expected arg[1] to be a String const carrying MT SSA JSON",
                ));
            }
        };
        let payload: serde_json::Value = serde_json::from_str(json_str)
            .map_err(|e| strong_tier_refusal(name, format!("malformed MT SSA JSON: {e}")))?;
        let walked = render_mt_let_chain(&payload).ok_or_else(|| {
            strong_tier_refusal(name, "MT SSA JSON contains a non-encodable bv32 node")
        })?;
        return Ok(Some(format!("(= {} {})", asserted, walked)));
    }
    if name == "int32.eq-bv-expr" && args.len() == 2 {
        let subject = &args[0];
        let bv_tree = &args[1];
        // subject must be a ctor
        let subj_args = match subject {
            Term::Ctor { args, .. } => args.as_slice(),
            _ => {
                return Err(strong_tier_refusal(
                    name,
                    "expected arg[0] to be a subject ctor",
                ));
            }
        };
        // Collect var names from the BV tree in DFS order — these are the
        // method parameter names, in the same order as the subject's args.
        let mut var_names: Vec<String> = Vec::new();
        collect_bv32_vars(bv_tree, &mut var_names);
        // Build substitution map
        let mut subst: std::collections::HashMap<String, String> = std::collections::HashMap::new();
        for (i, vname) in var_names.iter().enumerate() {
            if i >= subj_args.len() {
                break;
            }
            let bv_lit = match &subj_args[i] {
                Term::Const { value, .. } => {
                    if let Some(v) = value.as_i64() {
                        i32_to_bv32_hex(v)
                    } else {
                        return Err(strong_tier_refusal(
                            name,
                            "subject ctor arguments must be Int consts",
                        ));
                    }
                }
                _ => {
                    return Err(strong_tier_refusal(
                        name,
                        "subject ctor arguments must be Int consts",
                    ));
                }
            };
            subst.insert(vname.clone(), bv_lit);
        }
        let subj_rendered = render_bv32_subject(subject)
            .ok_or_else(|| strong_tier_refusal(name, "subject ctor cannot be rendered as bv32"))?;
        // Render the BV expression tree
        let bv_rendered = emit_bv32_term(bv_tree, &subst).ok_or_else(|| {
            strong_tier_refusal(
                name,
                "bv expression tree contains a non-encodable bv32 node",
            )
        })?;
        return Ok(Some(format!("(= {} {})", subj_rendered, bv_rendered)));
    }
    // Synthetic sibling equality promoted by bv32 contagion.
    if name == "int32.eq-const" && args.len() == 2 {
        let subject = &args[0];
        let lit = match &args[1] {
            Term::Const { value, .. } => value
                .as_i64()
                .map(i32_to_bv32_hex)
                .ok_or_else(|| strong_tier_refusal(name, "expected arg[1] to be an Int const"))?,
            _ => {
                return Err(strong_tier_refusal(
                    name,
                    "expected arg[1] to be an Int const",
                ));
            }
        };
        let subj_rendered = render_bv32_subject(subject)
            .ok_or_else(|| strong_tier_refusal(name, "subject ctor cannot be rendered as bv32"))?;
        return Ok(Some(format!("(= {} {})", subj_rendered, lit)));
    }
    // G2b: synthetic comparison-bound atoms over bv32 subjects.
    // int32.{lt,lte,gt,gte}-const(subject, IntConst) → (bvs{lt,le,gt,ge} subject_bv hex)
    let cmp_smt = match name {
        "int32.lt-const" => Some("bvslt"),
        "int32.lte-const" => Some("bvsle"),
        "int32.gt-const" => Some("bvsgt"),
        "int32.gte-const" => Some("bvsge"),
        _ => None,
    };
    if let Some(bv_op) = cmp_smt {
        if args.len() == 2 {
            let subject = &args[0];
            let lit = match &args[1] {
                Term::Const { value, .. } => {
                    value.as_i64().map(i32_to_bv32_hex).ok_or_else(|| {
                        strong_tier_refusal(name, "expected arg[1] to be an Int const")
                    })?
                }
                _ => {
                    return Err(strong_tier_refusal(
                        name,
                        "expected arg[1] to be an Int const",
                    ));
                }
            };
            let subj_rendered = render_bv32_subject(subject).ok_or_else(|| {
                strong_tier_refusal(name, "subject ctor cannot be rendered as bv32")
            })?;
            return Ok(Some(format!("({} {} {})", bv_op, subj_rendered, lit)));
        }
    }
    Err(strong_tier_refusal(
        name,
        format!("unsupported argument shape with {} args", args.len()),
    ))
}

fn emit_string_term(term: &Term) -> String {
    match term {
        Term::Const { value, sort } => {
            if matches!(sort, Sort::Primitive { name } if name == "String") {
                if let serde_json::Value::String(s) = value {
                    return smt_string_literal(s);
                }
            }
            emit_term(term)
        }
        Term::Var { name } => smt_quote(name),
        Term::Ctor { name, args } if name == "str.++" && args.len() == 2 => {
            format!(
                "(str.++ {} {})",
                emit_string_term(&args[0]),
                emit_string_term(&args[1])
            )
        }
        // The Python kit carries bytes literals as hex in ProofIR. When a
        // charset universe string-taints the term, unwrap to byte content so
        // bytes equalities meet charset universes in one theory. Kind
        // distinctness (b"a" != "a") is enforced kit-side by refusing
        // literal-vs-literal cross-kind rows before emission.
        Term::Ctor { name, args } if name == "python:bytes" && args.len() == 1 => match &args[0] {
            Term::Const { value, sort } if matches!(sort, Sort::Primitive { name } if name == "String") =>
            {
                if let serde_json::Value::String(hex) = value {
                    if let Some(decoded) = python_bytes_hex_to_string(hex) {
                        return smt_string_literal(&decoded);
                    }
                }
                emit_string_term(&args[0])
            }
            _ => emit_string_term(&args[0]),
        },
        Term::Let { body, .. } => emit_string_term(body),
        _ => emit_term(term),
    }
}

fn python_bytes_hex_to_string(hex: &str) -> Option<String> {
    if !hex.len().is_multiple_of(2) {
        return None;
    }
    let mut out = String::with_capacity(hex.len() / 2);
    for index in (0..hex.len()).step_by(2) {
        let byte = u8::from_str_radix(&hex[index..index + 2], 16).ok()?;
        out.push(char::from(byte));
    }
    Some(out)
}

// One SMT-LIB 2.6 string-character escape, shared by every string emitter.
// The standard admits ONLY printable ASCII (U+0020..U+007E) verbatim, with
// `"` doubled; EVERY other code point -- C0 controls, DEL, the C1 range, and
// all non-ASCII -- MUST be a `\u{...}` escape. Emitting such a byte raw
// produces a malformed literal that z3 rejects or mis-sorts ("Sorts Int and
// String are incompatible"), which surfaces as a FALSE consistency violation
// on any vendor test carrying non-ASCII data (UTF-8 headers, IRIs, cookies).
fn smt_string_char(ch: char) -> String {
    match ch {
        '"' => "\"\"".to_string(),
        '\u{20}'..='\u{7e}' => ch.to_string(),
        _ => format!("\\u{{{:x}}}", ch as u32),
    }
}

fn smt_string_literal(s: &str) -> String {
    let mut out = String::from("\"");
    for ch in s.chars() {
        out.push_str(&smt_string_char(ch));
    }
    out.push('"');
    out
}

// String/bool literal encoding + cross-type distinctness live in the
// hand-maintained `literal_encoding` module (NOT here) so a regeneration of
// this file cannot silently revert them. See that module's header for the
// full Python-`==`-semantics rationale.
use crate::literal_encoding::{emit_const_value as encode_const, LiteralConstants};

// isinstance disjointness axioms live in the hand-maintained
// `isinstance_encoding` module (NOT here) so a regeneration of this file
// cannot silently revert the soundness-critical type-disjointness encoding.
use crate::isinstance_encoding::IsinstanceClauses;

const IDENTITY_SORT: &str = "SugarIdentity";

fn emit_const_value(value: &serde_json::Value, sort_name: &str) -> String {
    // A `Real`-sorted const is a real literal carried as a CANONICAL DECIMAL
    // STRING (e.g. "0.00000015") so its CID is deterministic. Emit it verbatim as
    // an SMT-LIB Real literal. SMT-LIB has no negative real *literal*, so a
    // leading "-" renders as the unary-minus application `(- X)`.
    if sort_name == "Real" {
        if let Some(s) = value.as_str() {
            return match s.strip_prefix('-') {
                Some(mag) => format!("(- {mag})"),
                None => s.to_string(),
            };
        }
    }
    // A wide `Int`-sorted const (value > u64::MAX, within i128) is carried as a
    // decimal STRING (serde_json's default Number parse would lose precision to
    // f64). Emit it as the SMT-LIB integer NUMERAL it denotes -- NOT a
    // hash-named opaque symbol, which `encode_const` would do for any string.
    // Fixed-width Rust integer sorts (`i128`, `u64`, ...) are normalized to SMT
    // `Int` by `emit_sort_with_reason`, so their wide decimal-string values use
    // this same numeric path. SMT-LIB has no negative integer literal, so a
    // leading "-" renders as the unary-minus application `(- N)`. An in-range
    // Int still arrives as a Number and falls through to `encode_const`
    // unchanged (byte-identical).
    if sort_name == "Int" || is_int_width_sort(sort_name) {
        if let Some(s) = value.as_str() {
            if s.parse::<i128>().is_ok() {
                return match s.strip_prefix('-') {
                    Some(mag) => format!("(- {mag})"),
                    None => s.to_string(),
                };
            }
        }
    }
    // Every other sort: the Int-universe literal encoding (int/bool -> int value,
    // string/None -> hash-named uninterpreted Int const). Unchanged, so every
    // pre-existing (Real-free) formula is byte-for-byte identical.
    encode_const(value)
}

fn identity_const_name(value: &serde_json::Value, sort_name: &str) -> String {
    smt_quote(&format!(
        "identity:const:{}",
        identity_const_name_suffix(value, sort_name)
    ))
}

fn identity_const_name_suffix(value: &serde_json::Value, sort_name: &str) -> String {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(sort_name.as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(
        serde_json::to_string(value)
            .unwrap_or_else(|_| "null".to_string())
            .as_bytes(),
    );
    let full = blake3_512_of(&bytes);
    let hex_part = cid_hex(&full).unwrap_or(&full);
    let short: String = hex_part
        .chars()
        .filter(|c| c.is_ascii_hexdigit())
        .take(24)
        .collect();
    short
}

fn identity_var_name(name: &str) -> String {
    smt_quote(&format!("identity:var:{name}"))
}

fn identity_ctor_head(name: &str, arity: usize) -> String {
    smt_quote(&format!("identity:ctor:{name}#arity{arity}"))
}

fn emit_identity_term(term: &Term) -> String {
    match term {
        Term::Var { name, .. } => identity_var_name(name),
        Term::Const { value, sort, .. } => {
            let sort_name = match sort {
                Sort::Primitive { name } => name.as_str(),
                Sort::Function { .. } => "Function",
                Sort::Dependent { .. } => "Dependent",
                Sort::Region { .. } => "Region",
            };
            identity_const_name(value, sort_name)
        }
        Term::Ctor { name, args, .. } => {
            let rendered_args: Vec<String> = args.iter().map(emit_identity_term).collect();
            if rendered_args.is_empty() {
                identity_ctor_head(name, 0)
            } else {
                format!(
                    "({} {})",
                    identity_ctor_head(name, rendered_args.len()),
                    rendered_args.join(" ")
                )
            }
        }
        Term::Lambda { body, .. } => emit_identity_term(body),
        Term::Let { bindings, body, .. } => {
            let mut rendered = emit_identity_term(body);
            for binding in bindings.iter().rev() {
                rendered = format!(
                    "(let (({} {})) {})",
                    identity_var_name(&binding.name),
                    emit_identity_term(&binding.bound_term),
                    rendered
                );
            }
            rendered
        }
    }
}

fn collect_identity_literals_formula(formula: &Formula, out: &mut BTreeSet<String>) {
    match formula {
        Formula::Atomic { name, args } if name == "identity" && args.len() == 2 => {
            for arg in args {
                collect_identity_literals_term(arg, out);
            }
        }
        Formula::Atomic { .. } => {}
        Formula::And { operands } | Formula::Or { operands } | Formula::Implies { operands } => {
            for operand in operands {
                collect_identity_literals_formula(operand, out);
            }
        }
        Formula::Not { operands } => {
            for operand in operands {
                collect_identity_literals_formula(operand, out);
            }
        }
        Formula::Forall { body, .. }
        | Formula::Exists { body, .. }
        | Formula::Choice { body, .. } => {
            collect_identity_literals_formula(body, out);
        }
        Formula::Substitute { target, .. } => collect_identity_literals_formula(target, out),
        Formula::Apply { args, .. } => {
            for arg in args {
                collect_identity_literals_formula(arg, out);
            }
        }
        Formula::DivergenceBetween { source, target } => {
            collect_identity_literals_formula(source, out);
            collect_identity_literals_formula(target, out);
        }
    }
}

fn collect_identity_literals_term(term: &Term, out: &mut BTreeSet<String>) {
    match term {
        Term::Const { value, sort, .. } => {
            let sort_name = match sort {
                Sort::Primitive { name } => name.as_str(),
                Sort::Function { .. } => "Function",
                Sort::Dependent { .. } => "Dependent",
                Sort::Region { .. } => "Region",
            };
            out.insert(identity_const_name(value, sort_name));
        }
        Term::Ctor { name, args, .. } => {
            if args.is_empty() {
                out.insert(identity_ctor_head(name, 0));
            }
            for arg in args {
                collect_identity_literals_term(arg, out);
            }
        }
        Term::Lambda { body, .. } => collect_identity_literals_term(body, out),
        Term::Let { bindings, body, .. } => {
            for binding in bindings {
                collect_identity_literals_term(&binding.bound_term, out);
            }
            collect_identity_literals_term(body, out);
        }
        Term::Var { .. } => {}
    }
}

fn identity_distinctness_preamble(formula: &Formula) -> String {
    let mut literals = BTreeSet::new();
    collect_identity_literals_formula(formula, &mut literals);
    if literals.len() < 2 {
        String::new()
    } else {
        format!(
            "(assert (distinct {}))\n",
            literals.into_iter().collect::<Vec<_>>().join(" ")
        )
    }
}

// smt_quote renders a name as an SMT-LIB symbol, quoting with |...| when it is
// not a valid simple symbol (e.g. lifted ctor names like `go:call`, which
// contain ':' -- an unquoted ':' is a syntax error z3 rejects). Applied
// consistently at ctor applications and their declare-fun, so the symbol
// matches. NOTE: mirror this in tools/generate-from-cddl.py on regeneration.
fn smt_quote(name: &str) -> String {
    if name == "_" {
        return "|sugar:_|".to_string();
    }
    let simple = !name.is_empty()
        && !name.chars().next().is_some_and(|c| c.is_ascii_digit())
        && !name.contains(['\\', '|'])
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "~!@$%^&*_-+=<>.?/".contains(c));
    if simple {
        name.to_string()
    } else {
        let escaped = name.replace('\\', "\\\\").replace('|', "\\|");
        format!("|{}|", escaped)
    }
}

fn smt_ctor_head(name: &str, arity: usize) -> String {
    if name.starts_with("closure:") && !name.contains("#arity") {
        smt_quote(&format!("{name}#arity{arity}"))
    } else {
        smt_quote(name)
    }
}

fn smt_ctor_head_for_signature(name: &str, arity: usize, arg_sorts: &[String]) -> String {
    smt_quote(&ctor_decl_key_for_signature(name, arity, arg_sorts))
}

fn ctor_decl_key_for_signature(name: &str, arity: usize, arg_sorts: &[String]) -> String {
    let mut key = if name.starts_with("closure:") {
        format!("{name}#arity{arity}")
    } else {
        name.to_string()
    };
    if should_monomorphize_ctor_by_arg_sort(name) && arg_sorts.iter().any(|sort| sort != "Int") {
        key.push_str("#args:");
        key.push_str(
            &arg_sorts
                .iter()
                .map(|sort| sort_name_fragment(sort))
                .collect::<Vec<_>>()
                .join(","),
        );
    }
    key
}

fn should_monomorphize_ctor_by_arg_sort(name: &str) -> bool {
    matches!(name, "ref" | "deref")
}

fn sort_name_fragment(sort: &str) -> String {
    sort.chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '_' {
                ch
            } else {
                '_'
            }
        })
        .collect()
}

fn ctor_arg_sorts(name: &str, args: &[Term]) -> Vec<String> {
    args.iter()
        .enumerate()
        .map(|(idx, arg)| {
            method_arg_sort(name, idx, arg)
                .or_else(|| known_term_sort(arg))
                .unwrap_or_else(|| "Int".to_string())
        })
        .collect()
}

fn monadic_ctor_head_for_signature(
    name: &str,
    expected_ret: Option<&str>,
    arg_sorts: &[String],
) -> Option<&'static str> {
    match (name, arg_sorts) {
        (OPT_SOME, [sort]) if sort == "SugarOption" => Some(OPT_SOME_OPTION),
        (RES_OK, [sort]) if sort == "SugarOption" => Some(RES_OK_OPTION),
        (RES_ERR, [_]) if expected_ret == Some("SugarResultOption") => Some(RES_ERR_OPTION),
        _ => None,
    }
}

fn smt_atomic_name(name: &str) -> &str {
    match name {
        "eq" => "=",
        "ne" | "neq" => "distinct",
        "gt" => ">",
        "py.gt" => ">",
        "gte" => ">=",
        "py.ge" => ">=",
        "lt" => "<",
        "lte" => "<=",
        "py.le" => "<=",
        "\u{2260}" => "distinct",
        "\u{2264}" => "<=",
        "\u{2265}" => ">=",
        other => other,
    }
}

/// Compute the positionCid for an IR subterm.
fn position_cid_of(value: &serde_json::Value) -> String {
    let cv = to_cvalue(value);
    let jcs = encode_jcs(&cv);
    blake3_512_of(jcs.as_bytes())
}

fn to_cvalue(v: &serde_json::Value) -> Arc<CValue> {
    match v {
        serde_json::Value::Null => CValue::null(),
        serde_json::Value::Bool(b) => CValue::boolean(*b),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                CValue::integer(i128::from(i))
            } else if let Some(u) = n.as_u64() {
                CValue::integer(i128::from(u))
            } else if let Some(f) = n.as_f64() {
                CValue::string(format!("{}", f))
            } else {
                CValue::null()
            }
        }
        serde_json::Value::String(s) => CValue::string(s.clone()),
        serde_json::Value::Array(arr) => CValue::array(arr.iter().map(to_cvalue).collect()),
        serde_json::Value::Object(obj) => {
            CValue::object(obj.iter().map(|(k, v)| (k.clone(), to_cvalue(v))))
        }
    }
}

/// Walk a formula collecting opacity entries for sorts the SMT-LIB
/// compiler cannot handle. Returns (formula_string, opacities).
fn emit_formula_with_opacities(
    formula: &Formula,
    opacities: &mut Vec<OpacityEntry>,
) -> Result<String, CompileError> {
    match formula {
        Formula::Atomic { args, .. } => {
            for a in args {
                collect_opacities_term(a, opacities);
            }
            emit_formula(formula)
        }
        Formula::And { operands } => {
            let ops: Result<Vec<String>, CompileError> = operands
                .iter()
                .map(|o| emit_formula_with_opacities(o, opacities))
                .collect();
            Ok(format!("({} {})", "and", ops?.join(" ")))
        }
        Formula::Or { operands } => {
            let ops: Result<Vec<String>, CompileError> = operands
                .iter()
                .map(|o| emit_formula_with_opacities(o, opacities))
                .collect();
            Ok(format!("({} {})", "or", ops?.join(" ")))
        }
        Formula::Not { operands } => Ok(format!(
            "(not {})",
            emit_formula_with_opacities(&operands[0], opacities)?
        )),
        Formula::Implies { operands } => Ok(format!(
            "(=> {} {})",
            emit_formula_with_opacities(&operands[0], opacities)?,
            emit_formula_with_opacities(&operands[1], opacities)?
        )),
        Formula::Forall { name, sort, body } => {
            let (_, reason) = emit_sort_with_reason(sort);
            let effective_sort = if let Some(reason_code) = reason {
                // Record opacity provenance. Still emit a sound quantifier
                // using the CID-derived uninterpreted sort name declared in
                // the preamble. Collapsing to `true` is unsound.
                let serialized = serde_json::to_value(sort).unwrap_or(serde_json::Value::Null);
                let cid = position_cid_of(&serialized);
                opacities.push(OpacityEntry {
                    position_cid: cid,
                    reason_code,
                });
                opaque_sort_smt_name(sort)
            } else {
                emit_sort(sort)
            };
            let body_str = emit_formula_with_opacities(body, opacities)?;
            Ok(format!(
                "(forall (({} {})) {})",
                name, effective_sort, body_str
            ))
        }
        Formula::Exists { name, sort, body } => {
            let (_, reason) = emit_sort_with_reason(sort);
            let effective_sort = if let Some(reason_code) = reason {
                let serialized = serde_json::to_value(sort).unwrap_or(serde_json::Value::Null);
                let cid = position_cid_of(&serialized);
                opacities.push(OpacityEntry {
                    position_cid: cid,
                    reason_code,
                });
                opaque_sort_smt_name(sort)
            } else {
                emit_sort(sort)
            };
            let body_str = emit_formula_with_opacities(body, opacities)?;
            Ok(format!(
                "(exists (({} {})) {})",
                name, effective_sort, body_str
            ))
        }
        Formula::Choice {
            var_name,
            sort,
            body,
        } => {
            let (_, reason) = emit_sort_with_reason(sort);
            let effective_sort = if let Some(reason_code) = reason {
                let serialized = serde_json::to_value(sort).unwrap_or(serde_json::Value::Null);
                let cid = position_cid_of(&serialized);
                opacities.push(OpacityEntry {
                    position_cid: cid,
                    reason_code,
                });
                opaque_sort_smt_name(sort)
            } else {
                emit_sort(sort)
            };
            let body_str = emit_formula_with_opacities(body, opacities)?;
            let var_y = format!("{}_y", var_name);
            let body_y = body_str.replace(var_name, &var_y);
            let unique = format!(
                "(and {} (forall (({} {})) (=> {} (= {} {}))))",
                body_str, var_y, effective_sort, body_y, var_y, var_name
            );
            Ok(format!(
                "(exists (({} {})) {})",
                var_name, effective_sort, unique
            ))
        }
        // wp-rule schema nodes (spec 2026-05-13-wp-as-formula.md §2.3):
        // see the note in `emit_formula`.
        // TODO(wp-as-formula PR1+): teach sugar-ir-codegen to emit this arm.
        Formula::Substitute { .. } | Formula::Apply { .. } => {
            unreachable!(
                "wp-rule schema node reached the SMT-LIB opacity emitter; \
                 must be reduced via libsugar::wp first"
            )
        }
        Formula::DivergenceBetween { .. } => {
            unreachable!(
                "platform divergence formula reached the SMT-LIB opacity emitter; \
                 stage 4 must lower it before backend compilation"
            )
        }
    }
}

fn collect_opacities_term(term: &Term, opacities: &mut Vec<OpacityEntry>) {
    match term {
        Term::Var { .. } | Term::Const { .. } => {}
        Term::Ctor { args, .. } => {
            for a in args {
                collect_opacities_term(a, opacities);
            }
        }
        Term::Lambda {
            param_sort, body, ..
        } => {
            let (_, reason) = emit_sort_with_reason(param_sort);
            if let Some(reason_code) = reason {
                let serialized =
                    serde_json::to_value(param_sort).unwrap_or(serde_json::Value::Null);
                let cid = position_cid_of(&serialized);
                opacities.push(OpacityEntry {
                    position_cid: cid,
                    reason_code,
                });
            }
            collect_opacities_term(body, opacities);
        }
        Term::Let { bindings, body, .. } => {
            for b in bindings {
                collect_opacities_term(&b.bound_term, opacities);
            }
            collect_opacities_term(body, opacities);
        }
    }
}

pub fn collect_free_vars_formula(
    formula: &Formula,
    out: &mut BTreeMap<String, String>,
    bound: &BTreeSet<String>,
) {
    match formula {
        Formula::Atomic { name, args } => {
            if name == "identity" && args.len() == 2 {
                for a in args {
                    collect_free_vars_identity_term(a, out, bound);
                }
                return;
            }
            if crate::literal_encoding::routes_to_string_theory(name, args) {
                for a in args {
                    collect_free_vars_string_term(a, out, bound);
                }
                return;
            }
            // G2: BV32 atoms — var nodes in the BV tree are method-parameter
            // names substituted at emit time from the subject ctor's int args.
            // They are NOT free vars in the SMT sense; skip this atom entirely.
            if crate::literal_encoding::routes_to_bv32_theory(name) {
                return;
            }
            if name == "=" && args.iter().any(term_is_bv32_value) {
                for a in args {
                    collect_free_vars_term_bv32_result(a, out, bound);
                }
                return;
            }
            if is_float_refinement_atomic_predicate(name) {
                for a in args {
                    collect_free_vars_term_ctx(a, out, bound, true);
                }
                return;
            }
            // A var in an atom that carries a `Real` const is a real-arithmetic
            // operand (e.g. `(< (- a b) 0.00000015)`): declare it `Real`, not
            // `Int`. Atoms with no Real const collect exactly as before, so all
            // pre-existing (Real-free) formulas are byte-for-byte identical.
            let real_ctx = args.iter().any(term_has_real_const);
            // A var in an `=` atom whose OTHER operand is a monadic Option/Result
            // value (`opt:some`/.../`res:err`) must declare with that ADT sort, not
            // `Int` (`const A: Option = ...; assert_eq!(A, Some(2))` -> `A` must be
            // `SugarOption` to meet `opt:some(2)` well-sortedly). This mirrors the
            // `real_ctx` override above; absent any monadic operand it is `None`, so
            // all pre-existing formulas are byte-for-byte identical.
            let adt_ctx = if name == "=" {
                args.iter().find_map(monadic_operand_sort)
            } else {
                // A monadic ADT tester establishes its symbolic operand's ADT
                // sort (`adt.is_some(r)` -> `r: SugarOption`), so the free-var
                // pass declares `r` with that datatype sort and the native tester
                // `((_ is |opt:some|) r)` is well-sorted. Absent a tester this is
                // `None`, so all pre-existing formulas are byte-for-byte identical.
                monadic_adt_tester_operand_sort(name, args)
            };
            for a in args {
                collect_free_vars_term_ctx_adt(a, out, bound, real_ctx, adt_ctx);
            }
        }
        Formula::And { operands } => {
            for o in operands {
                collect_free_vars_formula(o, out, bound);
            }
        }
        Formula::Or { operands } => {
            for o in operands {
                collect_free_vars_formula(o, out, bound);
            }
        }
        Formula::Not { operands } => {
            for o in operands {
                collect_free_vars_formula(o, out, bound);
            }
        }
        Formula::Implies { operands } => {
            for o in operands {
                collect_free_vars_formula(o, out, bound);
            }
        }
        Formula::Forall {
            name,
            sort: _,
            body,
        } => {
            let mut nb = bound.clone();
            nb.insert(name.clone());
            collect_free_vars_formula(body, out, &nb);
        }
        Formula::Exists {
            name,
            sort: _,
            body,
        } => {
            let mut nb = bound.clone();
            nb.insert(name.clone());
            collect_free_vars_formula(body, out, &nb);
        }
        Formula::Choice {
            var_name,
            sort: _,
            body,
        } => {
            let mut nb = bound.clone();
            nb.insert(var_name.clone());
            collect_free_vars_formula(body, out, &nb);
        }
        // wp-rule schema nodes (spec 2026-05-13-wp-as-formula.md §2.3):
        // see the note in `emit_formula`.
        // TODO(wp-as-formula PR1+): teach sugar-ir-codegen to emit this arm.
        Formula::Substitute { .. } | Formula::Apply { .. } => {
            unreachable!(
                "wp-rule schema node reached the SMT-LIB free-var collector; \
                 must be reduced via libsugar::wp first"
            )
        }
        Formula::DivergenceBetween { source, target } => {
            collect_free_vars_formula(source, out, bound);
            collect_free_vars_formula(target, out, bound);
        }
    }
}

/// True iff the term contains a `Real`-sorted constant anywhere. Used to mark an
/// enclosing atom as real-arithmetic so its variable operands declare as `Real`.
fn term_has_real_const(term: &Term) -> bool {
    match term {
        Term::Const { sort, .. } => {
            matches!(sort, Sort::Primitive { name } if name == "Real")
        }
        Term::Ctor { args, .. } => args.iter().any(term_has_real_const),
        Term::Lambda { body, .. } => term_has_real_const(body),
        Term::Let { bindings, body, .. } => {
            bindings.iter().any(|b| term_has_real_const(&b.bound_term)) || term_has_real_const(body)
        }
        Term::Var { .. } => false,
    }
}

/// The ADT sort a monadic operand carries (`SugarOption` / `SugarResult`), or
/// `None` for any non-monadic term. Used as the `=`-atom var-sort context.
fn monadic_operand_sort(term: &Term) -> Option<&'static str> {
    match known_term_sort(term).as_deref() {
        Some("SugarOption") => Some("SugarOption"),
        Some("SugarResult") => Some("SugarResult"),
        Some("SugarOptionOption") => Some("SugarOptionOption"),
        Some("SugarResultOption") => Some("SugarResultOption"),
        _ => None,
    }
}

fn collect_free_vars_term_ctx(
    term: &Term,
    out: &mut BTreeMap<String, String>,
    bound: &BTreeSet<String>,
    real_ctx: bool,
) {
    collect_free_vars_term_ctx_adt(term, out, bound, real_ctx, None);
}

fn collect_free_vars_term_ctx_adt(
    term: &Term,
    out: &mut BTreeMap<String, String>,
    bound: &BTreeSet<String>,
    real_ctx: bool,
    adt_ctx: Option<&str>,
) {
    match term {
        Term::Var { name, .. } => {
            if !bound.contains(name) {
                if real_ctx {
                    // Real dominates Int: a var used as a real operand anywhere is
                    // declared Real regardless of collection order.
                    out.insert(name.clone(), "Real".to_string());
                } else if let Some(adt) = adt_ctx {
                    // A var compared `=` against a monadic Option/Result value
                    // declares with that ADT sort (overrides the Int default), so
                    // the equality is well-sorted. ADT dominates Int like Real does.
                    out.insert(name.clone(), adt.to_string());
                } else {
                    out.entry(name.clone()).or_insert_with(|| "Int".to_string());
                }
            }
        }
        Term::Const { .. } => {}
        Term::Ctor { args, .. } => {
            if let Term::Ctor { name, args } = term {
                if name == "str.len" && args.len() == 1 {
                    collect_free_vars_string_term(&args[0], out, bound);
                    return;
                }
            }
            // A monadic tester/selector (`adt.is_some(r)`, `opt:some#0(r)`) in
            // TERM position (a guarded-split guard/branch, #3445 Part 1 slice 2)
            // establishes its symbolic operand's ADT sort. Declare it here so the
            // native tester `((_ is |opt:some|) r)` is well-sorted; the `Int`
            // default from the generic recursion below would sort-mismatch it.
            // ADT dominates Int (like Real), so an unconditional insert is safe.
            if let Some((var, sort)) = monadic_operand_carrier_sort(term) {
                if !bound.contains(var) {
                    out.insert(var.to_string(), sort.to_string());
                }
            }
            // The ADT context applies ONLY to a var sitting DIRECTLY as an `=`
            // operand (`assert_eq!(A, Some(2))` -> `A: SugarOption`). It must NOT
            // propagate into ANY ctor's args: a monadic ctor's field is Int
            // (`opt:some(x)` -> `x: Int`), and an opaque call's args
            // (`method:compare_exchange(a, ..)`) are Int (the receiver/operands are
            // opaque), NOT the call RESULT's ADT sort. Drop adt_ctx for all nested
            // ctor args.
            for a in args {
                collect_free_vars_term_ctx_adt(a, out, bound, real_ctx, None);
            }
        }
        Term::Lambda {
            param_name,
            param_sort: _,
            body,
            ..
        } => {
            let mut nb = bound.clone();
            nb.insert(param_name.clone());
            collect_free_vars_term_ctx_adt(body, out, &nb, real_ctx, adt_ctx);
        }
        Term::Let { bindings, body, .. } => {
            let mut current_bound = bound.clone();
            for b in bindings {
                collect_free_vars_term_ctx_adt(
                    &b.bound_term,
                    out,
                    &current_bound,
                    real_ctx,
                    adt_ctx,
                );
                current_bound.insert(b.name.clone());
            }
            collect_free_vars_term_ctx_adt(body, out, &current_bound, real_ctx, adt_ctx);
        }
    }
}

fn collect_free_vars_term_bv32_result(
    term: &Term,
    out: &mut BTreeMap<String, String>,
    bound: &BTreeSet<String>,
) {
    match term {
        Term::Var { name, .. } => {
            if !bound.contains(name) {
                out.insert(name.clone(), BV32_SORT.to_string());
            }
        }
        Term::Const { .. } => {}
        Term::Ctor { name, args, .. } if is_bv32_ctor_name(name) => {
            for arg in args {
                collect_free_vars_term_bv32_result(arg, out, bound);
            }
        }
        Term::Ctor { args, .. } => {
            for arg in args {
                collect_free_vars_term_ctx(arg, out, bound, false);
            }
        }
        Term::Lambda {
            param_name, body, ..
        } => {
            let mut nb = bound.clone();
            nb.insert(param_name.clone());
            collect_free_vars_term_bv32_result(body, out, &nb);
        }
        Term::Let { bindings, body } => {
            let mut current_bound = bound.clone();
            for binding in bindings {
                collect_free_vars_term_bv32_result(&binding.bound_term, out, &current_bound);
                current_bound.insert(binding.name.clone());
            }
            collect_free_vars_term_bv32_result(body, out, &current_bound);
        }
    }
}

fn collect_free_vars_identity_term(
    term: &Term,
    out: &mut BTreeMap<String, String>,
    bound: &BTreeSet<String>,
) {
    match term {
        Term::Var { name, .. } => {
            if !bound.contains(name) {
                out.entry(format!("identity:var:{name}"))
                    .or_insert_with(|| IDENTITY_SORT.to_string());
            }
        }
        Term::Const { .. } => {}
        Term::Ctor { args, .. } => {
            for a in args {
                collect_free_vars_identity_term(a, out, bound);
            }
        }
        Term::Lambda {
            param_name, body, ..
        } => {
            let mut nb = bound.clone();
            nb.insert(param_name.clone());
            collect_free_vars_identity_term(body, out, &nb);
        }
        Term::Let { bindings, body, .. } => {
            let mut current_bound = bound.clone();
            for b in bindings {
                collect_free_vars_identity_term(&b.bound_term, out, &current_bound);
                current_bound.insert(b.name.clone());
            }
            collect_free_vars_identity_term(body, out, &current_bound);
        }
    }
}

fn collect_free_vars_string_term(
    term: &Term,
    out: &mut BTreeMap<String, String>,
    bound: &BTreeSet<String>,
) {
    match term {
        Term::Var { name, .. } => {
            if !bound.contains(name) {
                out.insert(name.clone(), "String".to_string());
            }
        }
        Term::Const { .. } => {}
        Term::Ctor { name, args } => {
            if is_builtin_term_operator(name) {
                // A genuine string operator (`str.++`, `str.len`, ...): its
                // operands are themselves string-sorted, so they stay in
                // string context.
                for a in args {
                    collect_free_vars_string_term(a, out, bound);
                }
            } else {
                // A non-builtin callresult ctor (`method:to_string`,
                // `c:callresult_*`) is String-RETURNING, but its ARGUMENTS are
                // the opaque call receiver/args -- NOT strings. The ctor-decl
                // pass declares this ctor's params via `known_term_sort` (Int
                // for a Var), so the free-var pass must collect those arg vars
                // as Int to MATCH. Marking the receiver String desyncs the
                // param sort from the var declaration, and z3 rejects the
                // ill-sorted `(method:to_string <String>)` application with
                // `unknown constant method:to_string (String)` -- which the
                // verifier soundly refuses, turning every to_string/Display
                // showcase row red. Only the ctor's RETURN sort is String
                // (set by `expected_atomic_arg_sort`).
                for a in args {
                    collect_free_vars_term_ctx(a, out, bound, false);
                }
            }
        }
        Term::Lambda {
            param_name, body, ..
        } => {
            let mut nb = bound.clone();
            nb.insert(param_name.clone());
            collect_free_vars_string_term(body, out, &nb);
        }
        Term::Let { bindings, body, .. } => {
            let mut current_bound = bound.clone();
            for b in bindings {
                collect_free_vars_string_term(&b.bound_term, out, &current_bound);
                current_bound.insert(b.name.clone());
            }
            collect_free_vars_string_term(body, out, &current_bound);
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct CtorSignature {
    args: Vec<String>,
    ret: String,
}

fn sort_name(sort: &Sort) -> String {
    emit_sort(sort)
}

fn known_term_sort(term: &Term) -> Option<String> {
    match term {
        Term::Const { sort, value } => {
            // String AND bool literals are encoded into the Int universe (see
            // `literal_encoding`): strings as hash-named uninterpreted Int
            // consts, bools as concrete ints (True->1, False->0). Return "Int"
            // for both so ctor-decl / predicate-decl passes emit consistent
            // Int-sort declarations rather than ill-sorted String/Bool ones
            // that z3 rejects against an Int free var.
            match sort {
                Sort::Primitive { name }
                    if name == "String" && matches!(value, serde_json::Value::String(_)) =>
                {
                    return Some("Int".to_string());
                }
                Sort::Primitive { name }
                    if name == "Bool" && matches!(value, serde_json::Value::Bool(_)) =>
                {
                    return Some("Int".to_string());
                }
                _ => {}
            }
            Some(sort_name(sort))
        }
        Term::Var { .. } if crate::literal_encoding::term_is_string_tainted(term) => {
            Some("String".to_string())
        }
        Term::Var { .. } => Some("Int".to_string()),
        Term::Ctor { name, .. } if name == "str.len" => Some("Int".to_string()),
        Term::Ctor { name, .. } if name == "to_real" => Some("Real".to_string()),
        Term::Ctor { name, .. } if is_bv32_ctor_name(name) && term_renders_as_bv32(term) => {
            Some(BV32_SORT.to_string())
        }
        // A monadic Option/Result ctor IS its ADT sort. Returning it lets a `=`
        // between a monadic value and an OPAQUE call result (`x.and(Some(2)) ==
        // Some(2)`) declare the opaque call with the matching ADT return sort, so
        // the script stays well-sorted and the two sides meet structurally
        // (`SugarOption`/`SugarResult` -- not the default `Int`, which would be
        // ill-sorted against the ADT and z3-reject the script).
        Term::Ctor { name, args } if name == OPT_SOME => {
            if args.first().and_then(|arg| known_term_sort(arg)).as_deref() == Some("SugarOption") {
                Some("SugarOptionOption".to_string())
            } else {
                Some("SugarOption".to_string())
            }
        }
        Term::Ctor { name, .. } if name == OPT_NONE => Some("SugarOption".to_string()),
        Term::Ctor { name, args } if name == RES_OK => {
            if args.first().and_then(|arg| known_term_sort(arg)).as_deref() == Some("SugarOption") {
                Some("SugarResultOption".to_string())
            } else {
                Some("SugarResult".to_string())
            }
        }
        Term::Ctor { name, .. } if name == RES_ERR => Some("SugarResult".to_string()),
        Term::Ctor { name, .. } if known_method_return_sort(name).is_some() => {
            known_method_return_sort(name).map(str::to_string)
        }
        Term::Ctor { .. } => None,
        Term::Lambda { .. } => None,
        Term::Let { body, .. } => known_term_sort(body),
    }
}

fn known_method_return_sort(name: &str) -> Option<&'static str> {
    match name {
        "method:ok" | "method:err" | "method:as_mut" | "method:as_ref" => Some("SugarOption"),
        "method:try_fold" | "method:try_rfold" => Some("SugarOption"),
        "method:try_reduce" => Some("SugarOptionOption"),
        "method:try_find" => Some("SugarResultOption"),
        _ => None,
    }
}

fn method_arg_sort(name: &str, index: usize, arg: &Term) -> Option<String> {
    match (name, index) {
        ("method:ok" | "method:err", 0) => Some("SugarResult".to_string()),
        ("method:is_ok" | "method:is_err", 0) => {
            known_term_sort(arg).filter(|sort| sort == "SugarResult")
        }
        ("method:unwrap" | "method:expect", 0) => {
            known_term_sort(arg).filter(|sort| sort == "SugarOption" || sort == "SugarResult")
        }
        _ => None,
    }
}

fn expected_atomic_arg_sort(name: &str, args: &[Term]) -> Option<String> {
    if is_float_refinement_atomic_predicate(name) {
        return Some("Real".to_string());
    }
    // Monadic ADT tester: its single operand carries the established ADT sort so
    // the operand renders / declares against the datatype, never `Int`.
    if let Some(sort) = monadic_adt_tester_operand_sort(name, args) {
        return Some(sort.to_string());
    }
    // String-theory atoms (and string-routed `=`) render their operands via
    // `emit_string_term`, so a ctor operand (`callresult_*`) must be DECLARED
    // with a `String` return sort or the script is ill-sorted.
    if crate::literal_encoding::routes_to_string_theory(name, args) {
        return Some("String".to_string());
    }
    // G2: BV32 atoms — the subject ctor is declared with `(_ BitVec 32)` sort.
    // The BV tree (args[1]) contains BV-operator ctors which must NOT be
    // declared as uninterpreted functions; they are handled in
    // `emit_bv32_theory_atomic` and are excluded from ctor-decl collection.
    if crate::literal_encoding::routes_to_bv32_theory(name) {
        return Some(BV32_SORT.to_string());
    }
    let smt_name = smt_atomic_name(name);
    if name == "py.eq" || matches!(smt_name, "=" | "distinct" | "<" | "<=" | ">" | ">=") {
        let known: Vec<String> = args.iter().filter_map(known_term_sort).collect();
        for preferred in ["SugarOptionOption", "SugarResultOption"] {
            if known.iter().any(|sort| sort == preferred) {
                return Some(preferred.to_string());
            }
        }
        return known.into_iter().next().or_else(|| Some("Int".to_string()));
    }
    None
}

fn collect_ctor_decls_formula(formula: &Formula, out: &mut BTreeMap<String, CtorSignature>) {
    match formula {
        Formula::Atomic { name, args } => {
            if name == "identity" && args.len() == 2 {
                for arg in args {
                    collect_identity_decls_term(arg, out);
                }
                return;
            }
            // G2: BV32 atoms — declare the subject ctor (args[0]) with ALL sorts
            // as `(_ BitVec 32)`: the arg sorts AND the return sort. Skip args[1]
            // (the BV expression tree) entirely: its operator ctors (bv32.ite,
            // bv32.slt, bv32.neg, ...) are SMT-LIB bitvector theory builtins and
            // must NOT be declared as uninterpreted functions (that would shadow
            // the theory and cause false results).
            if crate::literal_encoding::routes_to_bv32_theory(name) {
                let bv32_sort = BV32_SORT;
                if !args.is_empty() {
                    // Manually declare the subject ctor with all-BV32 signature.
                    // args[0] must be a Ctor; its args (the int literals at the
                    // call-site) are rendered as BV32 hex by emit_bv32_theory_atomic,
                    // so we must declare the ctor with BV32 argument sorts too.
                    if let Term::Ctor {
                        name: subj_name,
                        args: subj_args,
                    } = &args[0]
                    {
                        let arity = subj_args.len();
                        let arg_sorts: Vec<String> =
                            (0..arity).map(|_| bv32_sort.to_string()).collect();
                        out.entry(subj_name.clone())
                            .or_insert_with(|| CtorSignature {
                                args: arg_sorts,
                                ret: bv32_sort.to_string(),
                            });
                    }
                }
                return;
            }
            let expected = expected_atomic_arg_sort(name, args);
            for arg in args {
                collect_ctor_decls_term(arg, expected.as_deref(), out);
            }
        }
        Formula::And { operands } | Formula::Or { operands } | Formula::Implies { operands } => {
            for operand in operands {
                collect_ctor_decls_formula(operand, out);
            }
        }
        Formula::Not { operands } => {
            for operand in operands {
                collect_ctor_decls_formula(operand, out);
            }
        }
        Formula::Forall { body, .. }
        | Formula::Exists { body, .. }
        | Formula::Choice { body, .. } => {
            collect_ctor_decls_formula(body, out);
        }
        // wp-rule schema nodes (spec 2026-05-13-wp-as-formula.md §2.3):
        // see the note in `emit_formula`.
        // TODO(wp-as-formula PR1+): teach sugar-ir-codegen to emit this arm.
        Formula::Substitute { .. } | Formula::Apply { .. } => {
            unreachable!(
                "wp-rule schema node reached the SMT-LIB ctor-decl collector; \
                 must be reduced via libsugar::wp first"
            )
        }
        Formula::DivergenceBetween { source, target } => {
            collect_ctor_decls_formula(source, out);
            collect_ctor_decls_formula(target, out);
        }
    }
}

/// True iff `name` is an SMT-LIB theory operator that may appear in TERM
/// position and MUST stay interpreted -- never declared as an uninterpreted
/// function. This is the term-position analogue of
/// `is_builtin_atomic_predicate` (which covers boolean-position builtins).
///
/// The set is `+ - *`: the exact arithmetic operators the verifier's solver
/// dispatcher (`sugar-verifier/src/solvers/dispatch.rs`) classifies as
/// linear-arithmetic. A Java/Go/... lifter lowers `x * 2` to `ctor("*", ...)`,
/// so without this guard the honesty-layer ctor-declaration pass emitted
/// `(declare-fun * (Int Int) Int)`, shadowing the theory and turning a proven
/// `(= (* 3 2) 6)` obligation `sat` (false counterexample).
///
/// Integer `/` and `%` are DELIBERATELY excluded: SMT-LIB Int division/modulo
/// semantics (Euclidean) differ from source truncation, so leaving them
/// uninterpreted is the sound choice (the cardinal-sin guard). They keep
/// getting declared uninterpreted, exactly as before.
fn is_builtin_term_operator(name: &str) -> bool {
    matches!(
        name,
        "+" | "-"
            | "*"
            | "str.len"
            | "to_real"
            | "str.++"
            // Composable string-theory Ctor terms: emitted inline by
            // emit_term_with_expected, never as declared uninterpreted functions.
            | "str.from_code"   // → (str.from_code <int>): SMT string theory builtin
            | "str.table-select" // → ite-chain codepoint lookup: emitted inline
            // Symbolic-variant guarded split (#3445 Part 1 slice 2): the value
            // control-flow wrappers are interpreted inline into a native `ite`
            // (see emit_monadic_guarded_split), never declared uninterpreted.
            | CF_ITE
            | CF_GUARDED
    )
}

fn is_bv32_ctor_name(name: &str) -> bool {
    name.starts_with("bv32.")
}

fn term_renders_as_bv32(term: &Term) -> bool {
    let subst = std::collections::HashMap::new();
    emit_bv32_term(term, &subst).is_some()
}

fn term_is_bv32_value(term: &Term) -> bool {
    matches!(term, Term::Ctor { name, .. } if is_bv32_ctor_name(name) && term_renders_as_bv32(term))
}

// ── Monadic Option/Result algebraic datatypes ──────────────────────────────
//
// The Rust lifter grounds the std `Option`/`Result` CONSTRUCTORS (`Some(x)`,
// `None`, `Ok(x)`, `Err(x)`) to reserved ctor names -- `opt:some`/`opt:none`/
// `res:ok`/`res:err` (see `sugar-lift-rust-tests/src/sugar/monadic.rs`). They
// ARE algebraic datatypes, so we declare them to z3 as such via
// `declare-datatypes` rather than as plain uninterpreted functions. The ADT
// gives constructor INJECTIVITY (`Some a = Some b <=> a = b`) and DISTINCTNESS
// (`Some _ != None`, `Ok _ != Err _`) for free -- the structural-equality teeth:
// `Some(1) == Some(2)` is UNSAT, `Some(1) == None` is UNSAT, `Ok(a) == Err(b)`
// is false. A bare uninterpreted `Some` would let z3 model `Some(1) = Some(2)`
// (no injectivity) -> SAT -> a fake-dig. Monomorphic over `Int` (the lifter's
// inner is always a grounded int literal here); a nested-monadic inner would be
// ill-sorted and surface as a loud z3 error (sound under-claim, never a false
// pass).
const OPT_SOME: &str = "opt:some";
const OPT_NONE: &str = "opt:none";
const RES_OK: &str = "res:ok";
const RES_ERR: &str = "res:err";
const OPT_SOME_OPTION: &str = "opt:some#option";
const OPT_NONE_OPTION: &str = "opt:none#option";
const RES_OK_OPTION: &str = "res:ok#option";
const RES_ERR_OPTION: &str = "res:err#option";

/// True iff `name` is one of the reserved monadic ctor names -- declared as an
/// ADT constructor, NOT as an uninterpreted function.
fn is_monadic_ctor(name: &str) -> bool {
    matches!(name, OPT_SOME | OPT_NONE | RES_OK | RES_ERR)
}

/// True iff `name` is a monadic ADT FIELD SELECTOR (`opt:some#0`, `res:ok#0`,
/// `res:err#0`, and the `#option`-wrapped variants). Each `declare-datatypes`
/// constructor declares its payload accessor (`(opt:some (opt:some#0 Int))`, see
/// `monadic_adt_preamble`), so the selector is ALREADY a native datatype
/// projection in the ADT theory. A symbolic-variant guard region reads a
/// payload out of a symbolic operand with this selector (the some-arm of
/// `cf_ite(adt.is_some(r), cf_guarded(is_some, opt:some#0(r)), ...)`, #3445
/// Part 1 slice 2). Like the testers (`is_monadic_adt_tester`) and the ctors
/// (`is_monadic_ctor`), it must NEVER be re-declared as an uninterpreted
/// function -- a second `(declare-fun opt:some#0 ...)` shadows the datatype
/// selector and strips its projection law, so `opt:some#0(opt:some(v)) = v` no
/// longer holds and the payload floats free (the selector twin of the tester's
/// EUF-collapse). It renders as the native application `(|opt:some#0| r)`.
fn is_monadic_field_accessor(name: &str) -> bool {
    let Some(ctor) = name.strip_suffix("#0") else {
        return false;
    };
    matches!(
        ctor,
        OPT_SOME | RES_OK | RES_ERR | OPT_SOME_OPTION | RES_OK_OPTION | RES_ERR_OPTION
    )
}

// ── Monadic ADT discriminant testers (Part 1 carrier, #3445) ────────────────
//
// The reserved atomic family `adt.is_some`/`adt.is_none`/`adt.is_ok`/`adt.is_err`
// is EMITTER-INTERPRETED as a NATIVE datatype tester over the already-declared
// SugarOption/SugarResult ADTs -- `((_ is |opt:some|) x)` etc. The discriminant
// laws (`is_some(Some _) = true`, `is_some(None) = false`, mutual exclusion, and
// `is_some xor is_none`) come FREE from z3's datatype theory. The names are
// NAMESPACED (`adt.` prefix) so they cannot collide with the legacy syntactic
// `is_some` guards, which remain uninterpreted predicates until retired.
//
// SOUNDNESS: these testers must live in the SAME ADT theory as the constructors,
// NEVER as an EUF (uninterpreted) predicate. An uninterpreted `adt.is_some` would
// be a fresh Bool function z3 assigns freely -- collapsing the sum and turning a
// lie SAT (fake-dig). So `is_builtin_atomic_predicate` claims them (no
// `declare-fun`), and this renderer is the only place they take a value.
const ADT_IS_SOME: &str = "adt.is_some";
const ADT_IS_NONE: &str = "adt.is_none";
const ADT_IS_OK: &str = "adt.is_ok";
const ADT_IS_ERR: &str = "adt.is_err";

/// True iff `name` is one of the reserved monadic ADT discriminant testers.
fn is_monadic_adt_tester(name: &str) -> bool {
    matches!(name, ADT_IS_SOME | ADT_IS_NONE | ADT_IS_OK | ADT_IS_ERR)
}

/// Resolve the `(adt_sort, constructor)` a tester discriminates over its single
/// operand, or a LOUD refusal when the operand sort cannot be established.
///
/// The tester family fixes the sum (`is_some`/`is_none` -> Option family,
/// `is_ok`/`is_err` -> Result family). The operand's `known_term_sort` then
/// selects the wrap depth: a concrete monadic value carries its exact ADT sort;
/// a bare symbolic operand (`known_term_sort` -> the `Int` default) is ESTABLISHED
/// at the family's base ADT sort (this is the symbolic-variant guard lane -- the
/// operand is declared with that ADT sort by the free-var pass, so the tester is
/// well-sorted; it is NOT a silent Int-predicate fallback). Any operand whose
/// established sort belongs to the OTHER family, or is a non-ADT theory sort
/// (`String`/`Real`/BitVec/opaque), is UNESTABLISHABLE -> RED.
fn monadic_adt_tester_ctor(
    name: &str,
    arg: &Term,
) -> Result<(&'static str, &'static str), CompileError> {
    let option_family = matches!(name, ADT_IS_SOME | ADT_IS_NONE);
    let operand = known_term_sort(arg);
    let sort: &'static str = match (option_family, operand.as_deref()) {
        // `Int` is `known_term_sort`'s default for a bare symbolic operand: the
        // tester family establishes it at the base ADT sort.
        (true, Some("SugarOption")) | (true, Some("Int")) => "SugarOption",
        (true, Some("SugarOptionOption")) => "SugarOptionOption",
        (false, Some("SugarResult")) | (false, Some("Int")) => "SugarResult",
        (false, Some("SugarResultOption")) => "SugarResultOption",
        (_, other) => {
            return Err(strong_tier_refusal(
                name,
                format!(
                    "monadic ADT tester operand sort unestablishable (got {other:?}); \
                     the symbolic-variant guard lane refuses rather than falling back \
                     to a silent Int predicate"
                ),
            ));
        }
    };
    let ctor = match (name, sort) {
        (ADT_IS_SOME, "SugarOption") => OPT_SOME,
        (ADT_IS_SOME, "SugarOptionOption") => OPT_SOME_OPTION,
        (ADT_IS_NONE, "SugarOption") => OPT_NONE,
        (ADT_IS_NONE, "SugarOptionOption") => OPT_NONE_OPTION,
        (ADT_IS_OK, "SugarResult") => RES_OK,
        (ADT_IS_OK, "SugarResultOption") => RES_OK_OPTION,
        (ADT_IS_ERR, "SugarResult") => RES_ERR,
        (ADT_IS_ERR, "SugarResultOption") => RES_ERR_OPTION,
        // The (family, sort) pairs above are exhaustive for the resolved sorts.
        _ => unreachable!("tester/sort pairing already constrained by family"),
    };
    Ok((sort, ctor))
}

/// The operand ADT sort a tester establishes for its single operand, or `None`
/// for a non-tester name / unresolvable operand. Used by the free-var and
/// arg-sort passes so a symbolic operand is DECLARED with the matching ADT sort.
fn monadic_adt_tester_operand_sort(name: &str, args: &[Term]) -> Option<&'static str> {
    if !is_monadic_adt_tester(name) {
        return None;
    }
    let arg = args.first()?;
    monadic_adt_tester_ctor(name, arg)
        .ok()
        .map(|(sort, _)| sort)
}

/// Render a reserved monadic ADT tester as a native datatype discriminant, or
/// `Ok(None)` if `name` is not a tester. A wrong arity or unestablishable operand
/// sort is a LOUD refusal, never a silent generic atomic.
fn emit_monadic_adt_tester_atomic(
    name: &str,
    args: &[Term],
) -> Result<Option<String>, CompileError> {
    if !is_monadic_adt_tester(name) {
        return Ok(None);
    }
    if args.len() != 1 {
        return Err(strong_tier_refusal(
            name,
            format!(
                "monadic ADT tester expects exactly one operand, got {}",
                args.len()
            ),
        ));
    }
    let (sort, ctor) = monadic_adt_tester_ctor(name, &args[0])?;
    let operand = emit_term_with_expected(&args[0], Some(sort));
    // `((_ is |opt:some|) x)`: the tester lives in the ADT theory, so the
    // discriminant laws are z3-native. The ctor name is `smt_quote`d to match
    // the `declare-datatypes` constructor symbol.
    Ok(Some(format!("((_ is {}) {})", smt_quote(ctor), operand)))
}

// ── Symbolic-variant guarded split (#3445 Part 1 slice 2) ───────────────────
//
// The Rust kit lifts `symbolic_opt.unwrap_or(default)` (and `unwrap_or_default`)
// over a SYMBOLIC Option/Result receiver `r` to a value-level guarded split
//
//     cf_ite(adt.is_some(r), cf_guarded(is_some, opt:some#0(r)),
//                            cf_guarded(is_none, default))
//
// (T's Part-1 ruling: OptionAdaptorSugar stays a value producer whose produced
// value is a control-flow term; the discriminant carrier is the reserved
// `adt.is_*` tester family, NEVER a new Formula variant). This renders as a
// NATIVE builtin `ite` whose guard is the native datatype tester
// `((_ is |opt:some|) r)` and whose then-branch is the native selector
// projection `(|opt:some#0| r)`. The tester's Bool result + same-sorted branches
// are well-sorted, so z3 threads the datatype discriminant/projection laws --
// THAT is the teeth. `cf_ite`/`cf_guarded` are interpreted inline here and never
// declared as uninterpreted functions (that would strip the tester to a free
// EUF Bool and collapse the sum). The `cf_guarded(guard, value)` marker carries
// the path condition for the language-blind verifier; in the native `ite` the
// condition is already threaded by the tester, so we render its VALUE operand.
const CF_ITE: &str = "cf_ite";
const CF_GUARDED: &str = "cf_guarded";

/// The ADT sort a monadic FIELD ACCESSOR (`opt:some#0`, ...) establishes for its
/// single operand. Mirrors the tester's `monadic_adt_tester_operand_sort` so a
/// symbolic operand appearing ONLY under a selector/tester in TERM position
/// (the guarded-split value) is still declared with the matching ADT sort.
fn monadic_field_accessor_operand_sort(name: &str) -> Option<&'static str> {
    match name {
        "opt:some#0" => Some("SugarOption"),
        "res:ok#0" | "res:err#0" => Some("SugarResult"),
        "opt:some#option#0" => Some("SugarOptionOption"),
        "res:ok#option#0" | "res:err#option#0" => Some("SugarResultOption"),
        _ => None,
    }
}

/// The ADT sort a monadic tester/selector Term::Ctor establishes for its operand
/// var, or `None` if `term` is not such a single-operand carrier. Used by the
/// free-var pass so `r` in `cf_ite(adt.is_some(r), .., opt:some#0(r))` is
/// declared `SugarOption`, not the `Int` default (which would sort-mismatch the
/// native tester `((_ is |opt:some|) r)`).
fn monadic_operand_carrier_sort(term: &Term) -> Option<(&str, &'static str)> {
    let Term::Ctor { name, args } = term else {
        return None;
    };
    if args.len() != 1 {
        return None;
    }
    let Term::Var { name: var, .. } = &args[0] else {
        return None;
    };
    let sort = if is_monadic_adt_tester(name) {
        monadic_adt_tester_operand_sort(name, args)?
    } else {
        monadic_field_accessor_operand_sort(name)?
    };
    Some((var.as_str(), sort))
}

/// Unwrap a `cf_guarded(guard, value)` branch marker to its VALUE operand. A
/// non-`cf_guarded` branch (e.g. a bare default term) is returned unchanged.
fn guarded_branch_value(term: &Term) -> &Term {
    match term {
        Term::Ctor { name, args } if name == CF_GUARDED && args.len() == 2 => &args[1],
        other => other,
    }
}

/// Render a symbolic-variant guarded split `cf_ite(adt.is_*(r), then, else)` as a
/// native builtin `ite`, or `None` when `term` is not a monadic guarded split.
/// An `adt.is_*` guard whose operand sort is unestablishable is a LOUD panic (the
/// kit only ever builds establishable splits; a failure here is a kit bug, never
/// a silent EUF fall-through). See the module comment above.
fn emit_monadic_guarded_split(term: &Term, expected_ret: Option<&str>) -> Option<String> {
    let Term::Ctor { name, args } = term else {
        return None;
    };
    if name != CF_ITE || args.len() != 3 {
        return None;
    }
    let Term::Ctor {
        name: guard_name,
        args: guard_args,
    } = &args[0]
    else {
        return None;
    };
    if !is_monadic_adt_tester(guard_name) {
        return None;
    }
    let tester = emit_monadic_adt_tester_atomic(guard_name, guard_args)
        .unwrap_or_else(|e| {
            panic!("smt-lib: guarded-split tester `{guard_name}` unestablishable: {e:?}")
        })
        .unwrap_or_else(|| panic!("smt-lib: `{guard_name}` is not a tester in a guarded split"));
    let then_str = emit_term_with_expected(guarded_branch_value(&args[1]), expected_ret);
    let else_str = emit_term_with_expected(guarded_branch_value(&args[2]), expected_ret);
    Some(format!("(ite {tester} {then_str} {else_str})"))
}

/// Which monadic ADTs a formula references, so the preamble declares ONLY the
/// datatypes actually used (no unused `declare-datatypes` churn).
#[derive(Default, Clone, Copy)]
struct MonadicAdtsUsed {
    option: bool,
    result: bool,
    option_option: bool,
    result_option: bool,
}

fn collect_monadic_adts_formula(formula: &Formula, used: &mut MonadicAdtsUsed) {
    match formula {
        Formula::Atomic { args, .. } => {
            for arg in args {
                collect_monadic_adts_term(arg, used);
            }
        }
        Formula::And { operands } | Formula::Or { operands } | Formula::Implies { operands } => {
            for operand in operands {
                collect_monadic_adts_formula(operand, used);
            }
        }
        Formula::Not { operands } => {
            for operand in operands {
                collect_monadic_adts_formula(operand, used);
            }
        }
        Formula::Forall { body, .. }
        | Formula::Exists { body, .. }
        | Formula::Choice { body, .. } => {
            collect_monadic_adts_formula(body, used);
        }
        Formula::Substitute { .. } | Formula::Apply { .. } => {}
        Formula::DivergenceBetween { source, target } => {
            collect_monadic_adts_formula(source, used);
            collect_monadic_adts_formula(target, used);
        }
    }
}

fn collect_monadic_adts_term(term: &Term, used: &mut MonadicAdtsUsed) {
    match term {
        Term::Ctor { name, args } => {
            if let Some(sort) = known_term_sort(term) {
                mark_monadic_sort(&sort, used);
            } else if is_monadic_field_accessor(name) {
                // A payload selector (`opt:some#0(r)`) reads out of an ADT even
                // when no bare constructor appears in the term; its datatype
                // must still be declared or the selector is unsorted.
                match name.as_str() {
                    "opt:some#0" => mark_monadic_sort("SugarOption", used),
                    "res:ok#0" | "res:err#0" => mark_monadic_sort("SugarResult", used),
                    "opt:some#option#0" => mark_monadic_sort("SugarOptionOption", used),
                    "res:ok#option#0" | "res:err#option#0" => {
                        mark_monadic_sort("SugarResultOption", used)
                    }
                    _ => {}
                }
            } else if is_monadic_adt_tester(name) {
                // A tester (`adt.is_none(r)`) in TERM position (a guarded-split
                // guard, #3445 Part 1) needs its datatype declared even when
                // neither a constructor nor a selector appears in the term
                // (e.g. a none-arm whose default is a bare literal).
                if let Some(sort) = monadic_adt_tester_operand_sort(name, args) {
                    mark_monadic_sort(sort, used);
                }
            } else {
                match name.as_str() {
                    OPT_SOME | OPT_NONE => used.option = true,
                    RES_OK | RES_ERR => used.result = true,
                    _ => {}
                }
            }
            for arg in args {
                collect_monadic_adts_term(arg, used);
            }
        }
        Term::Lambda { body, .. } => collect_monadic_adts_term(body, used),
        Term::Let { bindings, body } => {
            for binding in bindings {
                collect_monadic_adts_term(&binding.bound_term, used);
            }
            collect_monadic_adts_term(body, used);
        }
        Term::Var { .. } | Term::Const { .. } => {}
    }
}

/// The `(declare-datatypes ...)` preamble lines for whichever monadic ADTs the
/// formula uses. Constructor names are `smt_quote`d so they MATCH the ctor
/// application `emit_term` renders (`(|opt:some| x)`). Monomorphic over `Int`.
fn monadic_adt_preamble(used: MonadicAdtsUsed) -> String {
    // Each constructor declares a field accessor `<ctor>#0`; the WHOLE accessor
    // name is `smt_quote`d (`|opt:some#0|`), not the bare ctor + a trailing `#0`
    // outside the quotes (`|opt:some|#0`, which z3 rejects).
    let field = |ctor: &str| smt_quote(&format!("{ctor}#0"));
    let mut out = String::new();
    if used.option {
        out.push_str(&format!(
            "(declare-datatypes ((SugarOption 0)) ((({some} ({some_f} Int)) ({none}))))\n",
            some = smt_quote(OPT_SOME),
            some_f = field(OPT_SOME),
            none = smt_quote(OPT_NONE),
        ));
    }
    if used.result {
        out.push_str(&format!(
            "(declare-datatypes ((SugarResult 0)) ((({ok} ({ok_f} Int)) ({err} ({err_f} Int)))))\n",
            ok = smt_quote(RES_OK),
            ok_f = field(RES_OK),
            err = smt_quote(RES_ERR),
            err_f = field(RES_ERR),
        ));
    }
    if used.option_option {
        out.push_str(&format!(
            "(declare-datatypes ((SugarOptionOption 0)) ((({some} ({some_f} SugarOption)) ({none}))))\n",
            some = smt_quote(OPT_SOME_OPTION),
            some_f = field(OPT_SOME_OPTION),
            none = smt_quote(OPT_NONE_OPTION),
        ));
    }
    if used.result_option {
        out.push_str(&format!(
            "(declare-datatypes ((SugarResultOption 0)) ((({ok} ({ok_f} SugarOption)) ({err} ({err_f} Int)))))\n",
            ok = smt_quote(RES_OK_OPTION),
            ok_f = field(RES_OK_OPTION),
            err = smt_quote(RES_ERR_OPTION),
            err_f = field(RES_ERR_OPTION),
        ));
    }
    out
}

fn mark_monadic_sort(sort: &str, used: &mut MonadicAdtsUsed) {
    match sort {
        "SugarOption" => used.option = true,
        "SugarResult" => used.result = true,
        "SugarOptionOption" => {
            used.option = true;
            used.option_option = true;
        }
        "SugarResultOption" => {
            used.option = true;
            used.result_option = true;
        }
        _ => {}
    }
}

fn collect_monadic_adts_signature(signature: &CtorSignature, used: &mut MonadicAdtsUsed) {
    mark_monadic_sort(&signature.ret, used);
    for arg in &signature.args {
        mark_monadic_sort(arg, used);
    }
}

fn collect_ctor_decls_term(
    term: &Term,
    expected_ret: Option<&str>,
    out: &mut BTreeMap<String, CtorSignature>,
) {
    match term {
        Term::Ctor { name, args } => {
            let arg_sorts: Vec<String> = args
                .iter()
                .enumerate()
                .map(|(idx, arg)| {
                    method_arg_sort(name, idx, arg)
                        .or_else(|| known_term_sort(arg))
                        .unwrap_or_else(|| "Int".to_string())
                })
                .collect();
            // Arithmetic theory operators stay interpreted: declaring them as
            // uninterpreted functions would shadow the SMT theory and let the
            // solver pick a counterexample interpretation. The monadic
            // Option/Result ctors (`opt:some`/`opt:none`/`res:ok`/`res:err`) are
            // declared as ALGEBRAIC DATATYPES (`declare-datatypes`, see
            // `monadic_adt_preamble`), NOT uninterpreted functions -- a second
            // `(declare-fun opt:some ...)` would shadow the ADT constructor and
            // strip its injectivity/distinctness teeth. Both are EXCLUDED from
            // the uninterpreted-fn pass. Still recurse into the arguments so any
            // genuine non-builtin ctor nested underneath (e.g. `method:foo`) is
            // declared.
            let is_interpreted_builtin = is_builtin_term_operator(name)
                || (is_bv32_ctor_name(name) && term_renders_as_bv32(term));
            // A monadic ADT tester (`adt.is_some`) can appear in TERM position as
            // the guard of a guarded split (#3445 Part 1 slice 2). Like the ctors
            // and selectors it is interpreted natively and must NEVER be declared
            // as an uninterpreted `(declare-fun adt.is_some (SugarOption) Int)` --
            // that shadows the datatype discriminant and collapses the sum.
            if !is_interpreted_builtin
                && !is_monadic_ctor(name)
                && !is_monadic_field_accessor(name)
                && !is_monadic_adt_tester(name)
            {
                let decl_key = ctor_decl_key_for_signature(name, args.len(), &arg_sorts);
                out.entry(decl_key).or_insert_with(|| CtorSignature {
                    args: arg_sorts.clone(),
                    ret: expected_ret
                        .or_else(|| known_method_return_sort(name))
                        .unwrap_or("Int")
                        .to_string(),
                });
            }
            for (arg, arg_sort) in args.iter().zip(arg_sorts.iter()) {
                collect_ctor_decls_term(arg, Some(arg_sort), out);
            }
        }
        Term::Lambda { body, .. } => collect_ctor_decls_term(body, expected_ret, out),
        Term::Let { bindings, body } => {
            for binding in bindings {
                collect_ctor_decls_term(&binding.bound_term, None, out);
            }
            collect_ctor_decls_term(body, expected_ret, out);
        }
        Term::Var { .. } | Term::Const { .. } => {}
    }
}

fn collect_identity_decls_term(term: &Term, out: &mut BTreeMap<String, CtorSignature>) {
    match term {
        Term::Const { value, sort, .. } => {
            let sort_name = match sort {
                Sort::Primitive { name } => name.as_str(),
                Sort::Function { .. } => "Function",
                Sort::Dependent { .. } => "Dependent",
                Sort::Region { .. } => "Region",
            };
            out.entry(format!(
                "identity:const:{}",
                identity_const_name_suffix(value, sort_name)
            ))
            .or_insert_with(|| CtorSignature {
                args: Vec::new(),
                ret: IDENTITY_SORT.to_string(),
            });
        }
        Term::Ctor { name, args, .. } => {
            for a in args {
                collect_identity_decls_term(a, out);
            }
            let arg_sorts: Vec<String> = args.iter().map(|_| IDENTITY_SORT.to_string()).collect();
            out.entry(format!("identity:ctor:{name}#arity{}", args.len()))
                .or_insert_with(|| CtorSignature {
                    args: arg_sorts,
                    ret: IDENTITY_SORT.to_string(),
                });
        }
        Term::Lambda { body, .. } => collect_identity_decls_term(body, out),
        Term::Let { bindings, body, .. } => {
            for binding in bindings {
                collect_identity_decls_term(&binding.bound_term, out);
            }
            collect_identity_decls_term(body, out);
        }
        Term::Var { .. } => {}
    }
}

/// True iff `name` (after `smt_atomic_name` normalization) is an SMT-LIB
/// builtin/theory predicate that needs no declaration. Everything else is a
/// user-defined (uninterpreted) predicate symbol -- `is_some`, `is_ok`,
/// `is_empty`, ... -- that MUST be declared as a Bool-returning function
/// before it can appear in boolean position. This recognizes no particular
/// predicate name as special: it is the COMPLEMENT of the builtin set, so it
/// is generic and language-blind.
fn is_builtin_atomic_predicate(name: &str) -> bool {
    if is_string_theory_atomic_predicate(name) {
        return true;
    }
    // Monadic ADT discriminant testers are EMITTER-INTERPRETED as native
    // datatype testers (`((_ is |opt:some|) x)`); they must NEVER be declared as
    // uninterpreted `(declare-fun adt.is_some (...) Bool)` predicates -- an EUF
    // tester collapses the sum. Claiming them here keeps the predicate-decl pass
    // from emitting a declaration.
    if is_monadic_adt_tester(name) {
        return true;
    }
    matches!(
        smt_atomic_name(name),
        // Equality / relational theory predicates.
        "=" | "distinct" | "<" | "<=" | ">" | ">="
        // Boolean literals (nullary, emitted verbatim).
        | "true" | "false"
        // The lifetime-kernel predicate is declared explicitly in the preamble.
        | "Outlives"
    )
}

fn is_float_refinement_atomic_predicate(name: &str) -> bool {
    matches!(
        name,
        "float.f32.is_nan"
            | "float.f64.is_nan"
            | "float.f32.is_infinite"
            | "float.f64.is_infinite"
            | "float.f32.is_finite"
            | "float.f64.is_finite"
            | "float.f32.is_normal"
            | "float.f64.is_normal"
            | "float.f32.is_sign_positive"
            | "float.f64.is_sign_positive"
            | "float.f32.is_sign_negative"
            | "float.f64.is_sign_negative"
    )
}

/// Family (e) float floor axioms (#3415; T's 2026-07-03 ruling: "Float specials:
/// as floored, fully reduced axioms, or refused. They CANNOT be computed, so they
/// leverage identity only.")
///
/// A float special value enters the universe as a FLOOR value: the ground ctor
/// `float:fW(<const bits>)`, where the IEEE bit pattern IS the identity. Whenever a
/// float-refinement predicate (`float.fW.is_X`) is applied to such a ground floor
/// term, the floor OWNS the predicate's value: we classify the bit pattern (pure
/// bit inspection -- NO float arithmetic) and emit the value as a ground axiom
/// `(assert (float.fW.is_X (float:fW bits)))` or its negation. This anchors the
/// otherwise-uninterpreted refinement predicate, so a semantic lie
/// (`f32::NAN.is_finite()`, `f32::INFINITY == f32::NEG_INFINITY`) is refuted instead
/// of passing under an unconstrained interpretation.
///
/// The axiom is a Python-TRUE ground fact (quantifier-free, no free vars), so it is
/// sound on BOTH the asserted and negated paths: like the identity-distinctness and
/// literal-constant preambles, it only removes spurious models, never adds one.
fn float_floor_axiom_preamble(formula: &Formula) -> String {
    let mut atoms: Vec<(&str, &Term)> = Vec::new();
    collect_float_floor_atoms(formula, &mut atoms);
    let mut seen = BTreeSet::new();
    let mut out = String::new();
    for (name, arg) in atoms {
        let Some(value) = classify_float_floor_predicate(name, arg) else {
            continue;
        };
        let atom = Formula::Atomic {
            name: name.to_string(),
            args: vec![arg.clone()],
        };
        let axiom = if value {
            atom
        } else {
            Formula::Not {
                operands: vec![atom],
            }
        };
        let Ok(rendered) = emit_formula(&axiom) else {
            continue;
        };
        if seen.insert(rendered.clone()) {
            out.push_str(&format!("(assert {})\n", rendered));
        }
    }
    out
}

fn collect_float_floor_atoms<'a>(formula: &'a Formula, out: &mut Vec<(&'a str, &'a Term)>) {
    match formula {
        Formula::Atomic { name, args } => {
            if is_float_refinement_atomic_predicate(name)
                && args.len() == 1
                && ground_float_ctor_bits(&args[0]).is_some()
            {
                out.push((name.as_str(), &args[0]));
            }
        }
        Formula::And { operands } | Formula::Or { operands } | Formula::Implies { operands } => {
            for o in operands {
                collect_float_floor_atoms(o, out);
            }
        }
        Formula::Not { operands } => {
            for o in operands {
                collect_float_floor_atoms(o, out);
            }
        }
        Formula::Forall { body, .. }
        | Formula::Exists { body, .. }
        | Formula::Choice { body, .. } => collect_float_floor_atoms(body, out),
        Formula::Substitute { .. } | Formula::Apply { .. } => {}
        Formula::DivergenceBetween { source, target } => {
            collect_float_floor_atoms(source, out);
            collect_float_floor_atoms(target, out);
        }
    }
}

/// `(width, bits)` if `term` is a ground `float:fW(<int const>)` floor ctor;
/// `None` for symbolic bits or any other shape.
fn ground_float_ctor_bits(term: &Term) -> Option<(&'static str, u64)> {
    let Term::Ctor { name, args } = term else {
        return None;
    };
    let width = match name.as_str() {
        "float:f32" => "f32",
        "float:f64" => "f64",
        _ => return None,
    };
    if args.len() != 1 {
        return None;
    }
    let Term::Const { value, .. } = &args[0] else {
        return None;
    };
    let bits = value
        .as_u64()
        .or_else(|| value.as_i64().and_then(|v| u64::try_from(v).ok()))?;
    Some((width, bits))
}

/// Classify a ground float floor term against a refinement predicate by pure IEEE
/// bit inspection. Returns the predicate's boolean value, or `None` when the
/// predicate/floor widths disagree or the method is unrecognized.
fn classify_float_floor_predicate(name: &str, arg: &Term) -> Option<bool> {
    let (ctor_width, bits) = ground_float_ctor_bits(arg)?;
    let (pred_width, method) = name.strip_prefix("float.")?.split_once('.')?;
    if pred_width != ctor_width {
        return None;
    }
    // Classify at the NATIVE width -- widening f32 -> f64 would misreport
    // `is_normal` for f32 subnormals (which become normal f64 values).
    match pred_width {
        "f32" => {
            let v = f32::from_bits(bits as u32);
            Some(match method {
                "is_nan" => v.is_nan(),
                "is_infinite" => v.is_infinite(),
                "is_finite" => v.is_finite(),
                "is_normal" => v.is_normal(),
                "is_sign_positive" => v.is_sign_positive(),
                "is_sign_negative" => v.is_sign_negative(),
                _ => return None,
            })
        }
        "f64" => {
            let v = f64::from_bits(bits);
            Some(match method {
                "is_nan" => v.is_nan(),
                "is_infinite" => v.is_infinite(),
                "is_finite" => v.is_finite(),
                "is_normal" => v.is_normal(),
                "is_sign_positive" => v.is_sign_positive(),
                "is_sign_negative" => v.is_sign_negative(),
                _ => return None,
            })
        }
        _ => None,
    }
}

/// Collect every NON-BUILTIN atomic predicate that appears in boolean
/// position, mapped to its declared signature (`(argSorts) Bool`).
///
/// This is the predicate analogue of `collect_ctor_decls_formula`: a ctor
/// (`Ok`, `method:unwrap`) sitting in TERM position is declared as a value
/// function by that pass, but a PREDICATE (`is_some`) sitting in BOOLEAN
/// position -- e.g. as the antecedent/consequent of an implication in a
/// guard-discharge obligation `(=> (is_some opt) (is_some opt))` -- was never
/// declared, so the solver rejected it with `unknown constant is_some`. Here
/// we declare it `(declare-fun is_some (<argSorts>) Bool)`. Arg sorts reuse
/// the same `known_term_sort` heuristic the ctor pass uses (var/ctor -> Int),
/// matching the `(declare-const opt Int)` the free-var pass already emits, so
/// applications type-check. A nullary atomic (the boolean literals, or a
/// 0-ary user predicate constant) is left to the existing handling.
fn collect_predicate_decls_formula(formula: &Formula, out: &mut BTreeMap<String, CtorSignature>) {
    match formula {
        Formula::Atomic { name, args } => {
            if name == "identity" && args.len() == 2 {
                return;
            }
            // G2: BV32 atoms are emitted as theory expressions — do not declare
            // them as uninterpreted predicates.
            if crate::literal_encoding::routes_to_bv32_theory(name) {
                return;
            }
            if !args.is_empty() && !is_builtin_atomic_predicate(name) {
                let expected = expected_atomic_arg_sort(name, args);
                let arg_sorts: Vec<String> = args
                    .iter()
                    .map(|arg| {
                        known_term_sort(arg)
                            .or_else(|| expected.clone())
                            .unwrap_or_else(|| "Int".to_string())
                    })
                    .collect();
                out.entry(smt_atomic_name(name).to_string())
                    .or_insert_with(|| CtorSignature {
                        args: arg_sorts,
                        ret: "Bool".to_string(),
                    });
            }
        }
        Formula::And { operands } | Formula::Or { operands } | Formula::Implies { operands } => {
            for operand in operands {
                collect_predicate_decls_formula(operand, out);
            }
        }
        Formula::Not { operands } => {
            for operand in operands {
                collect_predicate_decls_formula(operand, out);
            }
        }
        Formula::Forall { body, .. }
        | Formula::Exists { body, .. }
        | Formula::Choice { body, .. } => {
            collect_predicate_decls_formula(body, out);
        }
        Formula::Substitute { .. } | Formula::Apply { .. } => {
            unreachable!(
                "wp-rule schema node reached the SMT-LIB predicate-decl collector; \
                 must be reduced via libsugar::wp first"
            )
        }
        Formula::DivergenceBetween { source, target } => {
            collect_predicate_decls_formula(source, out);
            collect_predicate_decls_formula(target, out);
        }
    }
}

// ── G2: bv32 contagion (mirror of G1's string-theory routing) ─────────────
//
// G1 made `=(call, "literal")` route to string theory because the STRING CONST
// on the RHS self-identifies the atom as string-sorted. For bv32 the sibling
// sworn equality is `=(call:abs, IntConst)` — an Int const that looks identical
// to a legacy Int equality. The ONLY signal that it must live in the bv32 sort
// is that the SAME ctor subject appears inside an `int32.eq-bv-expr` universe
// atom elsewhere in the conjunction.
//
// So bv32 is CONTAGIOUS PER-TERM: we run a formula-level pre-pass that (1)
// collects every ctor subject appearing as args[0] of an `int32.eq-bv-expr`
// atom, then (2) rewrites every sibling `=(subject, IntConst)` over those
// subjects into a synthetic `int32.eq-const` atom carrying `[subject, IntConst]`.
// The emitter renders `int32.eq-const` as `(= |call:abs| <i32_to_bv32_hex>)`,
// and the subject ctor is declared ONCE as `(_ BitVec 32)`. No mixed-sort STOP:
// bv32-universe + Int-equality on the SAME term is not a conflict — it is the
// same term promoted to bv32. The genuine String-vs-Int STOP (B7) is untouched.

/// The synthetic atom name a promoted bv32 sibling equality carries.
const BV32_EQ_CONST: &str = "int32.eq-const";

/// Synthetic atom names for promoted bv32 sibling comparison bounds.
/// These are produced by `apply_bv32_contagion` when a sibling `<`/`<=`/`>`/`>=`
/// atom appears over a term that is also the subject of an `int32.eq-bv-expr` atom.
/// The emitter renders them as the corresponding BV signed-comparison operator.
const BV32_LT_CONST: &str = "int32.lt-const";
const BV32_LTE_CONST: &str = "int32.lte-const";
const BV32_GT_CONST: &str = "int32.gt-const";
const BV32_GTE_CONST: &str = "int32.gte-const";

/// Collect the set of ctor subjects (full Term::Ctor) that appear as args[0]
/// of any `int32.eq-bv-expr` atom in the formula.
fn collect_bv32_subjects(formula: &Formula, out: &mut Vec<Term>) {
    match formula {
        Formula::Atomic { name, args } => {
            if name == "int32.eq-bv-expr" && !args.is_empty() {
                if let Term::Ctor { .. } = &args[0] {
                    if !out.contains(&args[0]) {
                        out.push(args[0].clone());
                    }
                }
            }
        }
        Formula::And { operands }
        | Formula::Or { operands }
        | Formula::Not { operands }
        | Formula::Implies { operands } => {
            for o in operands {
                collect_bv32_subjects(o, out);
            }
        }
        Formula::Forall { body, .. }
        | Formula::Exists { body, .. }
        | Formula::Choice { body, .. } => collect_bv32_subjects(body, out),
        Formula::DivergenceBetween { source, target } => {
            collect_bv32_subjects(source, out);
            collect_bv32_subjects(target, out);
        }
        Formula::Substitute { .. } | Formula::Apply { .. } => {}
    }
}

/// True iff the term is an Int const (integer-valued).
fn is_int_const(t: &Term) -> bool {
    matches!(
        t,
        Term::Const { value, .. } if value.as_i64().is_some()
    )
}

/// Rewrite qualifying `=(subject, IntConst)` atoms into `int32.eq-const`
/// atoms when `subject` is a known bv32 subject. Recurses structurally.
fn promote_bv32_siblings_formula(formula: &Formula, subjects: &[Term]) -> Formula {
    match formula {
        Formula::Atomic { name, args } => {
            if name == "=" && args.len() == 2 {
                // Identify (subject, IntConst) in either order.
                let promote = |subj: &Term, lit: &Term| -> Option<Formula> {
                    if subjects.contains(subj) && is_int_const(lit) {
                        Some(Formula::Atomic {
                            name: BV32_EQ_CONST.to_string(),
                            args: vec![subj.clone(), lit.clone()],
                        })
                    } else {
                        None
                    }
                };
                if let Some(f) = promote(&args[0], &args[1]) {
                    return f;
                }
                if let Some(f) = promote(&args[1], &args[0]) {
                    return f;
                }
            }
            // G2b: promote comparison-bound atoms over bv32 subjects.
            // `<`/`<=`/`>`/`>=` where args[0] is a bv32 subject and args[1]
            // is an Int literal → synthetic int32.{lt,lte,gt,gte}-const atom.
            // The call is always normalised to args[0] by the Java lifter.
            let cmp_synthetic = match name.as_str() {
                "<" => Some(BV32_LT_CONST),
                "<=" => Some(BV32_LTE_CONST),
                ">" => Some(BV32_GT_CONST),
                ">=" => Some(BV32_GTE_CONST),
                _ => None,
            };
            if let Some(synthetic) = cmp_synthetic {
                if args.len() == 2 && subjects.contains(&args[0]) && is_int_const(&args[1]) {
                    return Formula::Atomic {
                        name: synthetic.to_string(),
                        args: args.clone(),
                    };
                }
            }
            formula.clone()
        }
        Formula::And { operands } => Formula::And {
            operands: operands
                .iter()
                .map(|o| promote_bv32_siblings_formula(o, subjects))
                .collect(),
        },
        Formula::Or { operands } => Formula::Or {
            operands: operands
                .iter()
                .map(|o| promote_bv32_siblings_formula(o, subjects))
                .collect(),
        },
        Formula::Not { operands } => Formula::Not {
            operands: operands
                .iter()
                .map(|o| promote_bv32_siblings_formula(o, subjects))
                .collect(),
        },
        Formula::Implies { operands } => Formula::Implies {
            operands: operands
                .iter()
                .map(|o| promote_bv32_siblings_formula(o, subjects))
                .collect(),
        },
        Formula::Forall { name, sort, body } => Formula::Forall {
            name: name.clone(),
            sort: sort.clone(),
            body: Box::new(promote_bv32_siblings_formula(body, subjects)),
        },
        Formula::Exists { name, sort, body } => Formula::Exists {
            name: name.clone(),
            sort: sort.clone(),
            body: Box::new(promote_bv32_siblings_formula(body, subjects)),
        },
        Formula::Choice {
            var_name,
            sort,
            body,
        } => Formula::Choice {
            var_name: var_name.clone(),
            sort: sort.clone(),
            body: Box::new(promote_bv32_siblings_formula(body, subjects)),
        },
        Formula::DivergenceBetween { source, target } => Formula::DivergenceBetween {
            source: Box::new(promote_bv32_siblings_formula(source, subjects)),
            target: Box::new(promote_bv32_siblings_formula(target, subjects)),
        },
        Formula::Substitute { .. } | Formula::Apply { .. } => formula.clone(),
    }
}

/// Top-level bv32 contagion pre-pass: collect bv32 subjects, then promote the
/// sibling Int equalities over them. Returns the formula unchanged if there are
/// no bv32 atoms (the common case — byte-for-byte identical output).
pub(crate) fn apply_bv32_contagion(formula: &Formula) -> Formula {
    let mut subjects: Vec<Term> = Vec::new();
    collect_bv32_subjects(formula, &mut subjects);
    if subjects.is_empty() {
        return formula.clone();
    }
    promote_bv32_siblings_formula(formula, &subjects)
}

fn collect_string_tainted_subjects(formula: &Formula, out: &mut Vec<Term>) {
    match formula {
        Formula::Atomic { name, args } => {
            if crate::literal_encoding::forces_string_sort(name) {
                for a in args {
                    if matches!(a, Term::Ctor { .. } | Term::Var { .. }) {
                        if !out.contains(a) {
                            out.push(a.clone());
                        }
                    }
                }
            }
        }
        Formula::And { operands }
        | Formula::Or { operands }
        | Formula::Not { operands }
        | Formula::Implies { operands } => {
            for o in operands {
                collect_string_tainted_subjects(o, out);
            }
        }
        Formula::Forall { body, .. } | Formula::Exists { body, .. } => {
            collect_string_tainted_subjects(body, out)
        }
        _ => {}
    }
}

pub fn compile_formula(formula: &Formula) -> Result<CompiledFormula, CompileError> {
    let formula = &apply_bv32_contagion(formula);
    {
        let mut tainted = Vec::new();
        collect_string_tainted_subjects(formula, &mut tainted);
        crate::literal_encoding::set_string_tainted(tainted);
    }
    let mut free_vars = BTreeMap::new();
    let bound = BTreeSet::new();
    collect_free_vars_formula(formula, &mut free_vars, &bound);
    let mut ctor_decls = BTreeMap::new();
    collect_ctor_decls_formula(formula, &mut ctor_decls);
    let mut predicate_decls = BTreeMap::new();
    collect_predicate_decls_formula(formula, &mut predicate_decls);

    let mut opacities: Vec<OpacityEntry> = Vec::new();
    let body_formula = emit_formula_with_opacities(formula, &mut opacities)?;

    // Sort opacities by positionCid ascending, then reasonCode ascending.
    opacities.sort_by(|a, b| {
        a.position_cid
            .cmp(&b.position_cid)
            .then_with(|| a.reason_code.cmp(&b.reason_code))
    });
    opacities.dedup();

    let opacity_manifest = OpacityManifest {
        protocol_version: "ir-compiler-protocol/2".to_string(),
        compiler: DIALECT.to_string(),
        compiler_version: COMPILER_VERSION.to_string(),
        opacities,
    };

    // Check whether the formula references Outlives. If so, inject the
    // kernel axioms (per protocol/specs/2026-05-05-outlives-kernel-axioms.md §2).
    let has_outlives = has_outlives_predicate(formula);
    let has_identity = has_identity_predicate(formula);
    let mut preamble = String::new();
    preamble.push_str("(set-logic ALL)\n");
    // Declare the monadic Option/Result ADTs (if used) BEFORE any constant /
    // ctor declaration, so a `SugarOption`/`SugarResult`-sorted symbol can refer
    // to the datatype. The ADT enforces constructor injectivity + distinctness
    // (the structural-equality teeth for `Some`/`None`/`Ok`/`Err`).
    {
        let mut monadic = MonadicAdtsUsed::default();
        collect_monadic_adts_formula(formula, &mut monadic);
        for sort in free_vars.values() {
            mark_monadic_sort(sort, &mut monadic);
        }
        for signature in ctor_decls.values() {
            collect_monadic_adts_signature(signature, &mut monadic);
        }
        for signature in predicate_decls.values() {
            collect_monadic_adts_signature(signature, &mut monadic);
        }
        preamble.push_str(&monadic_adt_preamble(monadic));
    }
    if has_outlives {
        // Declare the Region sort and Outlives predicate.
        preamble.push_str("(declare-sort Region 0)\n");
        preamble.push_str("(declare-fun Outlives (Region Region) Bool)\n");
        // Kernel axiom 1: reflexivity. Outlives(r, r) always holds.
        preamble.push_str("(assert (forall ((r Region)) (Outlives r r)))\n");
        // Kernel axiom 2: transitivity. Outlives(r1, r2) and Outlives(r2, r3) imply Outlives(r1, r3).
        preamble.push_str("(assert (forall ((r1 Region) (r2 Region) (r3 Region)) (=> (and (Outlives r1 r2) (Outlives r2 r3)) (Outlives r1 r3))))\n");
        // Kernel axiom 3: 'static top element. Outlives('static, r) for every region r.
        // 'static outlives every region per spec §2.3 (corrected in commit 655ab84).
        preamble.push_str("(declare-fun static_region () Region)\n");
        preamble.push_str("(assert (forall ((r Region)) (Outlives static_region r)))\n");
    }
    if has_identity {
        preamble.push_str(&format!("(declare-sort {IDENTITY_SORT} 0)\n"));
    }
    // Declare every opaque-sorted quantifier sort as an uninterpreted sort.
    // These are sorts the SMT-LIB backend cannot encode natively (non-builtin
    // primitive sorts, function sorts, dependent sorts, ...). Rather than
    // collapsing the quantifier to `true` (which is unsound: `forall x:S.
    // false` would falsely pass), we model each opaque sort as a fresh
    // uninterpreted sort via `(declare-sort <S> 0)`. Z3 then reasons over it
    // under an open-world assumption, which is sound: it can only produce
    // false-negatives (undecidable), never false-positives (false-pass).
    let mut opaque_sort_decls: BTreeMap<String, ()> = BTreeMap::new();
    collect_opaque_quantifier_sorts_formula(formula, &mut opaque_sort_decls);
    for sort_name in opaque_sort_decls.keys() {
        preamble.push_str(&format!("(declare-sort {} 0)\n", sort_name));
    }
    for (name, sort) in free_vars.iter() {
        preamble.push_str(&format!("(declare-const {} {})\n", smt_quote(name), sort));
    }
    // Declare every non-builtin ctor head as an UNINTERPRETED FUNCTION
    // symbol (`Ok`, `Err`, `Some`, `field`, `method:foo`, `tuple`,
    // `json!`-keyed macro terms, ...). This is the reflexive-discharge
    // encoding: an obligation `result == <body term>` whose body term is a
    // self-derived enum/struct/call/macro shape lowers to `f(args) ==
    // f(args)`, which is provable by reflexivity/congruence under ANY
    // interpretation of `f` (the solver never needs to know what `f`
    // means). It is SOUND: if the two sides genuinely differ (a lifter bug
    // emits `result == Ok(x)` for a body returning `Err(x)`), the encoding
    // yields `Ok(x) == Err(x)`, which z3 refutes (the negation is sat), so
    // the obligation stays honestly undecidable. The encoding is
    // self-protecting; it is reflexivity, not blanket-pass.
    //
    // The same declarations were already emitted on the asserted path
    // (`compile_asserted_formula`); they were missing here on the negated
    // path, which is why the lift-time whitelist had to refuse every
    // non-arithmetic post term. With declarations present the whitelist is
    // obsolete: the negated path renders any ctor head as a declared
    // uninterpreted symbol instead of an undeclared-function error.
    for (name, signature) in ctor_decls.iter() {
        preamble.push_str(&format!(
            "(declare-fun {} ({}) {})\n",
            smt_ctor_head(name, signature.args.len()),
            signature.args.join(" "),
            signature.ret
        ));
    }
    // Declare every non-builtin atomic PREDICATE in boolean position (e.g.
    // `is_some` in a guard-discharge obligation `(=> (is_some opt) (is_some
    // opt))`). Skip any name already declared as a value ctor above, so a
    // symbol used in both term and boolean position is declared exactly once.
    for (name, signature) in predicate_decls.iter() {
        if ctor_decls.contains_key(name) {
            continue;
        }
        preamble.push_str(&format!(
            "(declare-fun {} ({}) {})\n",
            smt_ctor_head(name, signature.args.len()),
            signature.args.join(" "),
            signature.ret
        ));
    }
    preamble.push_str(&identity_distinctness_preamble(formula));
    // Declare string-literal constants and emit the cross-type distinctness
    // axiom (str/None distinct from each other and from concrete int/bool
    // values; bool encoded as int; floats residual). See `literal_encoding`.
    // The axiom is a Python-TRUE fact, so it is sound on the negated path too:
    // it only removes spurious models, never adds one.
    preamble.push_str(&LiteralConstants::from_formula_for_legacy_literals(formula).preamble());
    // Emit isinstance disjointness clauses for genuinely-disjoint builtin type
    // pairs that appear with the same subject in the formula. These are
    // Python-TRUE facts (ground, quantifier-free). See `isinstance_encoding`.
    preamble.push_str(&IsinstanceClauses::from_formula(formula).preamble());
    // Family (e) float floor axioms (#3415): anchor `float.fW.is_X` refinement
    // predicates over ground `float:fW(bits)` floor terms to their classified value.
    preamble.push_str(&float_floor_axiom_preamble(formula));
    let body = format!("(assert (not {}))\n(check-sat)\n", body_formula);
    let free_vars_vec = free_vars
        .into_iter()
        .map(|(name, sort)| FreeVar { name, sort });
    let free_vars_vec = free_vars_vec.collect();
    Ok(CompiledFormula {
        preamble,
        body,
        free_vars: free_vars_vec,
        opacity_manifest,
        metadata: serde_json::Value::Null,
    })
}

pub fn compile_asserted_formula(formula: &Formula) -> Result<CompiledFormula, CompileError> {
    let formula = &apply_bv32_contagion(formula);
    {
        let mut tainted = Vec::new();
        collect_string_tainted_subjects(formula, &mut tainted);
        crate::literal_encoding::set_string_tainted(tainted);
    }
    let mut free_vars = BTreeMap::new();
    let bound = BTreeSet::new();
    collect_free_vars_formula(formula, &mut free_vars, &bound);

    let mut opacities: Vec<OpacityEntry> = Vec::new();
    let body_formula = emit_formula_with_opacities(formula, &mut opacities)?;

    opacities.sort_by(|a, b| {
        a.position_cid
            .cmp(&b.position_cid)
            .then_with(|| a.reason_code.cmp(&b.reason_code))
    });
    opacities.dedup();

    let opacity_manifest = OpacityManifest {
        protocol_version: "ir-compiler-protocol/2".to_string(),
        compiler: DIALECT.to_string(),
        compiler_version: COMPILER_VERSION.to_string(),
        opacities,
    };

    let mut ctor_decls = BTreeMap::new();
    collect_ctor_decls_formula(formula, &mut ctor_decls);
    let mut predicate_decls = BTreeMap::new();
    collect_predicate_decls_formula(formula, &mut predicate_decls);

    let has_outlives = has_outlives_predicate(formula);
    let has_identity = has_identity_predicate(formula);
    let mut preamble = String::new();
    preamble.push_str("(set-logic ALL)\n");
    // Declare the monadic Option/Result ADTs (if used) BEFORE any constant /
    // ctor declaration (see the matching block in `compile_formula`).
    {
        let mut monadic = MonadicAdtsUsed::default();
        collect_monadic_adts_formula(formula, &mut monadic);
        for sort in free_vars.values() {
            mark_monadic_sort(sort, &mut monadic);
        }
        for signature in ctor_decls.values() {
            collect_monadic_adts_signature(signature, &mut monadic);
        }
        for signature in predicate_decls.values() {
            collect_monadic_adts_signature(signature, &mut monadic);
        }
        preamble.push_str(&monadic_adt_preamble(monadic));
    }
    if has_outlives {
        preamble.push_str("(declare-sort Region 0)\n");
        preamble.push_str("(declare-fun Outlives (Region Region) Bool)\n");
        preamble.push_str("(assert (forall ((r Region)) (Outlives r r)))\n");
        preamble.push_str("(assert (forall ((r1 Region) (r2 Region) (r3 Region)) (=> (and (Outlives r1 r2) (Outlives r2 r3)) (Outlives r1 r3))))\n");
        preamble.push_str("(declare-fun static_region () Region)\n");
        preamble.push_str("(assert (forall ((r Region)) (Outlives static_region r)))\n");
    }
    if has_identity {
        preamble.push_str(&format!("(declare-sort {IDENTITY_SORT} 0)\n"));
    }
    // Declare opaque-sorted quantifier sorts as uninterpreted sorts (see the
    // matching block in `compile_formula` for full rationale).
    let mut opaque_sort_decls: BTreeMap<String, ()> = BTreeMap::new();
    collect_opaque_quantifier_sorts_formula(formula, &mut opaque_sort_decls);
    for sort_name in opaque_sort_decls.keys() {
        preamble.push_str(&format!("(declare-sort {} 0)\n", sort_name));
    }
    for (name, sort) in free_vars.iter() {
        preamble.push_str(&format!("(declare-const {} {})\n", smt_quote(name), sort));
    }
    for (name, signature) in ctor_decls.iter() {
        preamble.push_str(&format!(
            "(declare-fun {} ({}) {})\n",
            smt_ctor_head(name, signature.args.len()),
            signature.args.join(" "),
            signature.ret
        ));
    }
    // Declare non-builtin atomic predicates in boolean position (see the
    // matching block in `compile_formula`). Same de-dup against ctor decls.
    for (name, signature) in predicate_decls.iter() {
        if ctor_decls.contains_key(name) {
            continue;
        }
        preamble.push_str(&format!(
            "(declare-fun {} ({}) {})\n",
            smt_ctor_head(name, signature.args.len()),
            signature.args.join(" "),
            signature.ret
        ));
    }
    preamble.push_str(&identity_distinctness_preamble(formula));
    // Declare string-literal constants and emit the cross-type distinctness
    // axiom (str/None distinct from each other and from concrete int/bool
    // values; bool encoded as int; floats residual). See `literal_encoding`.
    preamble.push_str(&LiteralConstants::from_formula_for_legacy_literals(formula).preamble());
    // Emit isinstance disjointness clauses (see `isinstance_encoding`).
    preamble.push_str(&IsinstanceClauses::from_formula(formula).preamble());
    // Family (e) float floor axioms (#3415): see `float_floor_axiom_preamble`.
    preamble.push_str(&float_floor_axiom_preamble(formula));

    let body = format!("(assert {})\n(check-sat)\n", body_formula);
    let free_vars_vec = free_vars
        .into_iter()
        .map(|(name, sort)| FreeVar { name, sort })
        .collect();
    Ok(CompiledFormula {
        preamble,
        body,
        free_vars: free_vars_vec,
        opacity_manifest,
        metadata: serde_json::Value::Null,
    })
}

/// Recursively check whether a formula tree references the `Outlives`
/// atomic predicate.
fn has_outlives_predicate(formula: &Formula) -> bool {
    match formula {
        Formula::Atomic { name, .. } => name == "Outlives",
        Formula::And { operands } | Formula::Or { operands } | Formula::Implies { operands } => {
            operands.iter().any(has_outlives_predicate)
        }
        Formula::Not { operands } => operands.iter().any(has_outlives_predicate),
        Formula::Forall { body, .. } | Formula::Exists { body, .. } => has_outlives_predicate(body),
        Formula::Choice { body, .. } => has_outlives_predicate(body),
        // wp-rule schema nodes (spec 2026-05-13-wp-as-formula.md §2.3):
        // see the note in `emit_formula`.
        // TODO(wp-as-formula PR1+): teach sugar-ir-codegen to emit this arm.
        Formula::Substitute { target, .. } => has_outlives_predicate(target),
        Formula::Apply { args, .. } => args.iter().any(has_outlives_predicate),
        Formula::DivergenceBetween { source, target } => {
            has_outlives_predicate(source) || has_outlives_predicate(target)
        }
    }
}

/// Recursively check whether a formula tree references the language-neutral
/// Sugar identity predicate.
fn has_identity_predicate(formula: &Formula) -> bool {
    match formula {
        Formula::Atomic { name, args } => name == "identity" && args.len() == 2,
        Formula::And { operands } | Formula::Or { operands } | Formula::Implies { operands } => {
            operands.iter().any(has_identity_predicate)
        }
        Formula::Not { operands } => operands.iter().any(has_identity_predicate),
        Formula::Forall { body, .. } | Formula::Exists { body, .. } => has_identity_predicate(body),
        Formula::Choice { body, .. } => has_identity_predicate(body),
        Formula::Substitute { target, .. } => has_identity_predicate(target),
        Formula::Apply { args, .. } => args.iter().any(has_identity_predicate),
        Formula::DivergenceBetween { source, target } => {
            has_identity_predicate(source) || has_identity_predicate(target)
        }
    }
}

#[cfg(test)]
mod emit_term_direct_tests {
    use super::*;
    use sugar_ir_types::IrTerm as Term;

    fn int_sort() -> Sort {
        Sort::Primitive { name: "Int".into() }
    }

    fn int_const(value: i64) -> Term {
        Term::Const {
            value: serde_json::json!(value),
            sort: int_sort(),
        }
    }

    fn var(name: &str) -> Term {
        Term::Var { name: name.into() }
    }

    #[test]
    fn lambda_emits_expected_smt_lib() {
        let term = Term::Lambda {
            param_name: "x".into(),
            param_sort: int_sort(),
            body: Box::new(var("x")),
        };

        assert_eq!(emit_term(&term), "(lambda ((x Int)) x)");
    }

    #[test]
    fn let_emits_expected_smt_lib() {
        let term = Term::Let {
            bindings: vec![LetBinding {
                name: "x".into(),
                bound_term: int_const(1),
            }],
            body: Box::new(var("x")),
        };

        assert_eq!(emit_term(&term), "(let ((x 1)) x)");
    }

    #[test]
    fn ctor_emits_expected_smt_lib() {
        let term = Term::Ctor {
            name: "call:f".into(),
            args: vec![var("x"), int_const(1)],
        };

        assert_eq!(emit_term(&term), "(|call:f| x 1)");
    }

    #[test]
    fn explicit_int_to_real_bridge_emits_interpreted_operator() {
        let term = Term::Ctor {
            name: "to_real".into(),
            args: vec![int_const(1)],
        };

        assert_eq!(emit_term(&term), "(to_real 1)");
    }
}

// ──────────────────────────────────────────────────────────────────────────
// Base64 strong-tier (`str.eq-bv-blocks`) emitter tests (paper 26 seam).
// ADDITIVE: these exercise the new string-theory atom and the four new bv32
// ops (shl/lshr/or/add). They do not touch the discharge emission.
// ──────────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod b64_strong_tests {
    use super::*;
    use sugar_ir_types::IrTerm as Term;

    fn s(name: &str) -> Sort {
        Sort::Primitive { name: name.into() }
    }

    /// Build the per-char index tree for output char `k` of a full 3-byte block,
    /// EXACTLY mirroring the vendor's Base64.java full-block path:
    ///   work = ((((0<<8)+b0)<<8)+b1)<<8)+b2     (line 778, x3)
    ///   idx_k = (work >> shift_k) & 0x3f          (lines 780-783; MASK_6BITS=0x3f)
    /// shifts: [18, 12, 6, 0].
    fn block_index_tree(shift: i64) -> serde_json::Value {
        // accumulation: (((0<<8)+b0)<<8 + b1)<<8 + b2
        let acc = serde_json::json!({
          "kind":"ctor","name":"bv32.add","args":[
            {"kind":"ctor","name":"bv32.shl","args":[
              {"kind":"ctor","name":"bv32.add","args":[
                {"kind":"ctor","name":"bv32.shl","args":[
                  {"kind":"ctor","name":"bv32.add","args":[
                    {"kind":"ctor","name":"bv32.shl","args":[
                      {"kind":"const","value":0},
                      {"kind":"const","value":8}]},
                    {"kind":"var","name":"b0"}]},
                  {"kind":"const","value":8}]},
                {"kind":"var","name":"b1"}]},
              {"kind":"const","value":8}]},
            {"kind":"var","name":"b2"}]
        });
        let shifted = if shift == 0 {
            acc
        } else {
            serde_json::json!({"kind":"ctor","name":"bv32.lshr","args":[acc, {"kind":"const","value": shift}]})
        };
        serde_json::json!({"kind":"ctor","name":"bv32.and","args":[shifted, {"kind":"const","value":63}]})
    }

    /// Standard table codepoints in source order (A-Za-z0-9+/), walked by G1.
    fn std_table() -> Vec<i64> {
        let t = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        t.chars().map(|c| c as i64).collect()
    }

    fn bar_payload() -> Term {
        let payload = serde_json::json!({
            "input_bytes": [98, 97, 114],     // "bar"
            "vars": ["b0","b1","b2"],
            "per_char": [
                block_index_tree(18),
                block_index_tree(12),
                block_index_tree(6),
                block_index_tree(0),
            ],
            "table": std_table(),
        });
        Term::Const {
            value: serde_json::Value::String(payload.to_string()),
            sort: s("String"),
        }
    }

    fn bar_general_payload() -> Term {
        let payload = serde_json::json!({
            "vars": ["b0","b1","b2"],
            "per_char": [
                block_index_tree(18),
                block_index_tree(12),
                block_index_tree(6),
                block_index_tree(0),
            ],
            "table": std_table(),
        });
        Term::Const {
            value: serde_json::Value::String(payload.to_string()),
            sort: s("String"),
        }
    }

    fn subject() -> Term {
        Term::Ctor {
            name: "call:encodeBase64String".into(),
            args: vec![Term::Const {
                value: serde_json::Value::String("bar".into()),
                sort: s("String"),
            }],
        }
    }

    #[test]
    fn new_bv_ops_render() {
        let subst: std::collections::HashMap<String, String> =
            [("b0".to_string(), "#x00000062".to_string())]
                .into_iter()
                .collect();
        let mk = |op: &str| Term::Ctor {
            name: op.into(),
            args: vec![
                Term::Var { name: "b0".into() },
                Term::Const {
                    value: serde_json::json!(8),
                    sort: s("Int"),
                },
            ],
        };
        assert_eq!(
            emit_bv32_term(&mk("bv32.shl"), &subst).unwrap(),
            "(bvshl #x00000062 #x00000008)"
        );
        assert_eq!(
            emit_bv32_term(&mk("bv32.lshr"), &subst).unwrap(),
            "(bvlshr #x00000062 #x00000008)"
        );
        assert_eq!(
            emit_bv32_term(&mk("bv32.or"), &subst).unwrap(),
            "(bvor #x00000062 #x00000008)"
        );
        assert_eq!(
            emit_bv32_term(&mk("bv32.add"), &subst).unwrap(),
            "(bvadd #x00000062 #x00000008)"
        );
        // Recurrence keystone ops (paper 26): multiply + xor for MT-style seeding.
        assert_eq!(
            emit_bv32_term(&mk("bv32.mul"), &subst).unwrap(),
            "(bvmul #x00000062 #x00000008)"
        );
        assert_eq!(
            emit_bv32_term(&mk("bv32.xor"), &subst).unwrap(),
            "(bvxor #x00000062 #x00000008)"
        );
    }

    #[test]
    fn recurrence_mt_seed_step_renders() {
        // The Mersenne Twister seeding recurrence step, exactly as the
        // RecurrenceUniverseWalker emits it for one unrolled iteration:
        //   mt = 1812433253 * (mt ^ (mt >> 30)) + i      (i concrete = 1)
        // over a prior scalar `mt` substituted to a bv32 literal.
        let subst: std::collections::HashMap<String, String> =
            [("mt".to_string(), "#x012bd6e8".to_string())]
                .into_iter()
                .collect();
        let v = || Term::Var { name: "mt".into() };
        let c = |n: i64| Term::Const {
            value: serde_json::json!(n),
            sort: s("Int"),
        };
        let ctor = |name: &str, args: Vec<Term>| Term::Ctor {
            name: name.into(),
            args,
        };
        // mt >> 30
        let shifted = ctor("bv32.lshr", vec![v(), c(30)]);
        // mt ^ (mt >> 30)
        let folded = ctor("bv32.xor", vec![v(), shifted]);
        // 1812433253 * folded
        let mult = ctor("bv32.mul", vec![c(1812433253), folded]);
        // (1812433253 * folded) + 1
        let step = ctor("bv32.add", vec![mult, c(1)]);
        let rendered = emit_bv32_term(&step, &subst).expect("MT seed step must render");
        assert_eq!(
            rendered,
            "(bvadd (bvmul #x6c078965 (bvxor #x012bd6e8 (bvlshr #x012bd6e8 #x0000001e))) #x00000001)"
        );
    }

    #[test]
    fn recurrence_mag01_gate_ite_renders() {
        // The twist's MAG01-gated write low-bit branch:
        //   (y & 1) == 1 ? MAG01[1] : MAG01[0]
        // → bv32.ite(bv32.eq(bv32.and(y,1),1), 0x9908b0df, 0x0)
        let subst: std::collections::HashMap<String, String> =
            [("y".to_string(), "#x00000003".to_string())]
                .into_iter()
                .collect();
        let v = || Term::Var { name: "y".into() };
        let c = |n: i64| Term::Const {
            value: serde_json::json!(n),
            sort: s("Int"),
        };
        let ctor = |name: &str, args: Vec<Term>| Term::Ctor {
            name: name.into(),
            args,
        };
        let low = ctor("bv32.and", vec![v(), c(1)]);
        let cond = ctor("bv32.eq", vec![low, c(1)]);
        let ite = ctor("bv32.ite", vec![cond, c(0x9908b0dfu32 as i64), c(0)]);
        let rendered = emit_bv32_term(&ite, &subst).expect("MAG01 gate must render");
        // bvand then = compare then ite over the two MAG01 entries.
        assert!(
            rendered.starts_with("(ite (= (bvand #x00000003 #x00000001) #x00000001)"),
            "gate must render as ite over the low-bit equality: {rendered}"
        );
        assert!(
            rendered.contains("#x9908b0df"),
            "MAG01[1] entry missing: {rendered}"
        );
    }

    #[test]
    fn emits_self_contained_string_equality() {
        let rendered = emit_string_theory_atomic("str.eq-bv-blocks", &[subject(), bar_payload()])
            .expect("str.eq-bv-blocks must not refuse")
            .expect("str.eq-bv-blocks must render");
        // Subject equality, let-bound bytes, four chars via str.from_code, the
        // walked ops, and the 6-bit mask all present.
        assert!(
            rendered.starts_with("(= "),
            "must be an equality: {rendered}"
        );
        assert!(
            rendered.contains("(let ((b0 #x00000062) (b1 #x00000061) (b2 #x00000072))"),
            "bytes must be let-bound to the literal's UTF-8 bytes: {rendered}"
        );
        assert!(
            rendered.contains("str.from_code"),
            "char bridge missing: {rendered}"
        );
        assert_eq!(
            rendered.matches("str.from_code").count(),
            4,
            "exactly 4 output chars: {rendered}"
        );
        assert!(
            rendered.contains("bvlshr"),
            "extraction shift op missing: {rendered}"
        );
        assert!(
            rendered.contains("bvshl"),
            "accumulation shift op missing: {rendered}"
        );
        assert!(
            rendered.contains("bvadd"),
            "accumulation add op missing: {rendered}"
        );
        assert!(
            rendered.contains("#x0000003f"),
            "MASK_6BITS (0x3f) missing: {rendered}"
        );
        // The table-ite must carry walked codepoints, e.g. 'Y'=89, 'm'=109.
        assert!(
            rendered.contains(" 89 "),
            "table codepoint 89 ('Y') missing: {rendered}"
        );
    }

    #[test]
    fn emits_symbolic_input_string_bytes_for_general_universe() {
        let rendered = emit_string_theory_atomic(
            "str.eq-bv-blocks",
            &[
                Term::Var { name: "out".into() },
                Term::Var {
                    name: "input".into(),
                },
                bar_general_payload(),
            ],
        )
        .expect("general str.eq-bv-blocks must not refuse")
        .expect("general str.eq-bv-blocks must render");
        assert!(
            rendered.contains("(str.to_code (str.at input 0))"),
            "b0 must come from the symbolic input string: {rendered}"
        );
        assert!(
            rendered.contains("(str.to_code (str.at input 1))"),
            "b1 must come from the symbolic input string: {rendered}"
        );
        assert!(
            rendered.contains("(str.to_code (str.at input 2))"),
            "b2 must come from the symbolic input string: {rendered}"
        );
        assert!(
            !rendered.contains("#x00000062"),
            "general universe must not bake bar's bytes into the body: {rendered}"
        );
    }

    #[test]
    fn malformed_payload_refuses() {
        let bad = Term::Const {
            value: serde_json::Value::String("not json".into()),
            sort: s("String"),
        };
        let err = emit_b64_strong_blocks(&subject(), None, &bad)
            .expect_err("malformed payload must refuse");
        assert!(
            err.to_string().contains("str.eq-bv-blocks"),
            "error must name the atom: {err}"
        );
    }

    // z3 integration: GOOD claim sat, alphabet-valid-but-WRONG claim unsat.
    // Uses a plain String-sorted subject var (the real pipeline supplies the
    // ctor subject + its declarations via compile_formula; here we isolate the
    // equation logic — the conjoin with the sworn equality is what binds the
    // subject to the claim, modelled below by the second assert over `subj`).
    fn run_claim(claim: &str) -> String {
        use std::io::Write;
        use std::process::{Command, Stdio};
        let subj = Term::Var {
            name: "subj".into(),
        };
        let atom = emit_string_theory_atomic("str.eq-bv-blocks", &[subj, bar_payload()])
            .unwrap()
            .unwrap();
        let claim_lit = format!("\"{}\"", claim);
        // Assert the strong-tier definition AND the sworn equality over the same
        // subject. Conjoined: GOOD claim sat, alphabet-valid-but-wrong unsat.
        let script = format!(
            "(set-logic ALL)\n(declare-const subj String)\n\
             (assert {atom})\n(assert (= subj {claim_lit}))\n(check-sat)\n"
        );
        let mut child = Command::new("z3")
            .args(["-smt2", "-in"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("spawn z3");
        child
            .stdin
            .as_mut()
            .unwrap()
            .write_all(script.as_bytes())
            .unwrap();
        let out = child.wait_with_output().unwrap();
        String::from_utf8_lossy(&out.stdout).trim().to_string()
    }

    #[test]
    fn z3_good_claim_sat_bad_claim_unsat() {
        use std::process::Command;
        if Command::new("z3").arg("--version").output().is_err() {
            eprintln!("z3 absent: skipping b64 strong-tier z3 integration test");
            return;
        }
        let good = run_claim("YmFy");
        assert!(
            good.starts_with("sat"),
            "GOOD claim YmFy must be sat; got: {good}"
        );
        // ZmFy is alphabet-valid (every char in the standard table) but WRONG.
        // Only the block equations can refute it.
        let bad = run_claim("ZmFy");
        assert!(
            bad.starts_with("unsat"),
            "alphabet-valid-but-wrong ZmFy must be unsat; got: {bad}"
        );
    }

    fn run_compiled_claim(claim: &str) -> String {
        use std::io::Write;
        use std::process::{Command, Stdio};

        let out = Term::Var { name: "out".into() };
        let formula = Formula::And {
            operands: vec![
                Formula::Atomic {
                    name: "str.eq-bv-blocks".into(),
                    args: vec![out.clone(), bar_payload()],
                },
                Formula::Atomic {
                    name: "=".into(),
                    args: vec![
                        out,
                        Term::Const {
                            value: serde_json::Value::String(claim.into()),
                            sort: s("String"),
                        },
                    ],
                },
            ],
        };
        let parts = compile_asserted_formula(&formula).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let mut child = Command::new("z3")
            .args(["-smt2", "-in"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("spawn z3");
        child
            .stdin
            .as_mut()
            .unwrap()
            .write_all(script.as_bytes())
            .unwrap();
        let out = child.wait_with_output().unwrap();
        String::from_utf8_lossy(&out.stdout).trim().to_string()
    }

    fn run_compiled_general_claim(claim: &str) -> String {
        use std::io::Write;
        use std::process::{Command, Stdio};

        let input = Term::Var {
            name: "input".into(),
        };
        let out = Term::Var { name: "out".into() };
        let formula = Formula::And {
            operands: vec![
                Formula::Atomic {
                    name: "str.eq-bv-blocks".into(),
                    args: vec![out.clone(), input.clone(), bar_general_payload()],
                },
                Formula::Atomic {
                    name: "=".into(),
                    args: vec![
                        input,
                        Term::Const {
                            value: serde_json::Value::String("bar".into()),
                            sort: s("String"),
                        },
                    ],
                },
                Formula::Atomic {
                    name: "=".into(),
                    args: vec![
                        out,
                        Term::Const {
                            value: serde_json::Value::String(claim.into()),
                            sort: s("String"),
                        },
                    ],
                },
            ],
        };
        let parts = compile_asserted_formula(&formula).expect("compile");
        let script = format!("{}{}", parts.preamble, parts.body);
        let mut child = Command::new("z3")
            .args(["-smt2", "-in"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("spawn z3");
        child
            .stdin
            .as_mut()
            .unwrap()
            .write_all(script.as_bytes())
            .unwrap();
        let out = child.wait_with_output().unwrap();
        String::from_utf8_lossy(&out.stdout).trim().to_string()
    }

    #[test]
    fn compiled_var_subject_equality_routes_to_string_theory() {
        use std::process::Command;
        if Command::new("z3").arg("--version").output().is_err() {
            eprintln!("z3 absent: skipping compiled b64 z3 integration test");
            return;
        }

        let good = run_compiled_claim("YmFy");
        assert!(
            good.starts_with("sat"),
            "compiled GOOD claim YmFy must be sat; got: {good}"
        );
        let bad = run_compiled_claim("ZmFy");
        assert!(
            bad.starts_with("unsat"),
            "compiled wrong ZmFy claim must be unsat; got: {bad}"
        );
    }

    #[test]
    fn compiled_general_input_fact_routes_to_string_theory() {
        use std::process::Command;
        if Command::new("z3").arg("--version").output().is_err() {
            eprintln!("z3 absent: skipping compiled general b64 z3 integration test");
            return;
        }

        let good = run_compiled_general_claim("YmFy");
        assert!(
            good.starts_with("sat"),
            "general GOOD claim YmFy must be sat; got: {good}"
        );
        let bad = run_compiled_general_claim("ZmFy");
        assert!(
            bad.starts_with("unsat"),
            "general wrong ZmFy claim must be unsat; got: {bad}"
        );
    }

    // ── PHASE 2: mod-3 tail emitter (sextet chars + AST-resolved '=' pad) ──
    // A 2-byte tail ("ba") emits 3 sextet chars over (b0,b1) + 1 pad char; a
    // 1-byte tail ("f") emits 2 sextet chars over (b0) + 2 pad chars. The sextet
    // index trees mirror Base64.java case-2 / case-1 (>>10/>>4/<<2 ; >>2/<<4),
    // masked with 0x3f. The pad codepoint (61='=') is carried in `pad_chars`,
    // NOT routed through the table-ite (the pad is outside the 64-char alphabet).

    fn tail2_sextet(op: &str, shift: i64) -> serde_json::Value {
        // work = ((0<<8)+b0)<<8 + b1   (2 accumulations)
        let acc = serde_json::json!({
          "kind":"ctor","name":"bv32.add","args":[
            {"kind":"ctor","name":"bv32.shl","args":[
              {"kind":"ctor","name":"bv32.add","args":[
                {"kind":"ctor","name":"bv32.shl","args":[
                  {"kind":"const","value":0},{"kind":"const","value":8}]},
                {"kind":"var","name":"b0"}]},
              {"kind":"const","value":8}]},
            {"kind":"var","name":"b1"}]
        });
        let shifted = serde_json::json!({"kind":"ctor","name":op,"args":[acc, {"kind":"const","value": shift}]});
        serde_json::json!({"kind":"ctor","name":"bv32.and","args":[shifted, {"kind":"const","value":63}]})
    }
    fn tail1_sextet(op: &str, shift: i64) -> serde_json::Value {
        // work = (0<<8)+b0   (1 accumulation)
        let acc = serde_json::json!({
          "kind":"ctor","name":"bv32.add","args":[
            {"kind":"ctor","name":"bv32.shl","args":[
              {"kind":"const","value":0},{"kind":"const","value":8}]},
            {"kind":"var","name":"b0"}]
        });
        let shifted = serde_json::json!({"kind":"ctor","name":op,"args":[acc, {"kind":"const","value": shift}]});
        serde_json::json!({"kind":"ctor","name":"bv32.and","args":[shifted, {"kind":"const","value":63}]})
    }

    fn tail2_payload() -> Term {
        // "ba" = [98,97]; case 2: >>10, >>4, <<2 ; + 1 '=' pad.
        let payload = serde_json::json!({
            "input_bytes": [98, 97],
            "vars": ["b0","b1"],
            "per_char": [
                tail2_sextet("bv32.lshr", 10),
                tail2_sextet("bv32.lshr", 4),
                tail2_sextet("bv32.shl", 2),
            ],
            "table": std_table(),
            "pad_chars": [61],
        });
        Term::Const {
            value: serde_json::Value::String(payload.to_string()),
            sort: s("String"),
        }
    }
    fn tail1_payload() -> Term {
        // "f" = [102]; case 1: >>2, <<4 ; + 2 '=' pads.
        let payload = serde_json::json!({
            "input_bytes": [102],
            "vars": ["b0"],
            "per_char": [
                tail1_sextet("bv32.lshr", 2),
                tail1_sextet("bv32.shl", 4),
            ],
            "table": std_table(),
            "pad_chars": [61, 61],
        });
        Term::Const {
            value: serde_json::Value::String(payload.to_string()),
            sort: s("String"),
        }
    }

    #[test]
    fn tail_emits_pad_chars_as_literal_codepoints() {
        let r2 = emit_string_theory_atomic(
            "str.eq-bv-blocks",
            &[
                Term::Var {
                    name: "subj".into(),
                },
                tail2_payload(),
            ],
        )
        .unwrap()
        .unwrap();
        // 3 sextet + 1 pad = 4 chars; pad rendered as (str.from_code 61).
        assert_eq!(
            r2.matches("str.from_code").count(),
            4,
            "2-byte tail: 3 sextet + 1 pad: {r2}"
        );
        assert!(
            r2.contains("(str.from_code 61)"),
            "pad '=' (61) literal char missing: {r2}"
        );
        let r1 = emit_string_theory_atomic(
            "str.eq-bv-blocks",
            &[
                Term::Var {
                    name: "subj".into(),
                },
                tail1_payload(),
            ],
        )
        .unwrap()
        .unwrap();
        // 2 sextet + 2 pad = 4 chars.
        assert_eq!(
            r1.matches("str.from_code").count(),
            4,
            "1-byte tail: 2 sextet + 2 pad: {r1}"
        );
        assert_eq!(
            r1.matches("(str.from_code 61)").count(),
            2,
            "two pad chars expected: {r1}"
        );
    }

    fn run_tail_claim(payload: Term, claim: &str) -> String {
        use std::io::Write;
        use std::process::{Command, Stdio};
        let atom = emit_string_theory_atomic(
            "str.eq-bv-blocks",
            &[
                Term::Var {
                    name: "subj".into(),
                },
                payload,
            ],
        )
        .unwrap()
        .unwrap();
        let script = format!(
            "(set-logic ALL)\n(declare-const subj String)\n\
             (assert {atom})\n(assert (= subj \"{claim}\"))\n(check-sat)\n"
        );
        let mut child = Command::new("z3")
            .args(["-smt2", "-in"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("spawn z3");
        child
            .stdin
            .as_mut()
            .unwrap()
            .write_all(script.as_bytes())
            .unwrap();
        String::from_utf8_lossy(&child.wait_with_output().unwrap().stdout)
            .trim()
            .to_string()
    }

    #[test]
    fn z3_tail_good_sat_bad_padded_lie_unsat() {
        use std::process::Command;
        if Command::new("z3").arg("--version").output().is_err() {
            eprintln!("z3 absent: skipping b64 tail z3 integration test");
            return;
        }
        // 2-byte tail "ba" -> "YmE=". GOOD claim sat.
        assert!(
            run_tail_claim(tail2_payload(), "YmE=").starts_with("sat"),
            "GOOD 2-byte tail YmE= must be sat"
        );
        // "YmX=" is alphabet-valid (Y,m,X all in table; '=' is the sworn pad) but
        // WRONG (3rd char should be E, not X). Weak tier would discharge it; only
        // the tail sextet equations refute it.
        assert!(
            run_tail_claim(tail2_payload(), "YmX=").starts_with("unsat"),
            "alphabet-valid-but-wrong padded YmX= must be unsat"
        );
        // A claim with the WRONG pad count ("YmEX" instead of "YmE=") is refuted
        // by the pinned pad char.
        assert!(
            run_tail_claim(tail2_payload(), "YmEX").starts_with("unsat"),
            "wrong-pad YmEX must be unsat (pad char pinned)"
        );
        // 1-byte tail "f" -> "Zg==". GOOD sat; alphabet-valid lie "ZX==" unsat.
        assert!(
            run_tail_claim(tail1_payload(), "Zg==").starts_with("sat"),
            "GOOD 1-byte tail Zg== must be sat"
        );
        assert!(
            run_tail_claim(tail1_payload(), "ZX==").starts_with("unsat"),
            "alphabet-valid-but-wrong padded ZX== must be unsat"
        );
    }
}

#[cfg(test)]
mod str_table_select_tests {
    //! Unit tests for the composable string-theory Ctor terms added to the SMT
    //! backend: `str.table-select`, `str.from_code`, and `str.++`.
    //!
    //! These tests operate entirely at the SMT emission layer.  The z3 round-trip
    //! tests (good/bad twins) verify that the SYMBOLIC TEETH work: the "good"
    //! formula is SAT and the "bad" formula is UNSAT via the composed consistency
    //! obligation -- NOT via a self-contradiction, NOT via the witness.
    use super::*;
    use sugar_ir_types::IrTerm as Term;

    fn s(name: &str) -> Sort {
        Sort::Primitive { name: name.into() }
    }

    /// Build a `str.table-select(alpha, const_sextet)` IrTerm.
    fn table_select(alpha: &str, sextet: i64) -> Term {
        Term::Ctor {
            name: "str.table-select".into(),
            args: vec![
                Term::Const {
                    value: serde_json::Value::String(alpha.to_string()),
                    sort: s("String"),
                },
                Term::Const {
                    value: serde_json::json!(sextet),
                    sort: s("u32"),
                },
            ],
        }
    }

    /// Build a `str.from_code(arg)` IrTerm.
    fn from_code(arg: Term) -> Term {
        Term::Ctor {
            name: "str.from_code".into(),
            args: vec![arg],
        }
    }

    /// Build a `str.++(left, right)` IrTerm.
    fn str_concat(left: Term, right: Term) -> Term {
        Term::Ctor {
            name: "str.++".into(),
            args: vec![left, right],
        }
    }

    // ── SMT emission shape tests ──────────────────────────────────────────────

    #[test]
    fn str_table_select_emits_ite_chain() {
        // A 3-entry table with sextets [0, 1, 2] -> codepoints [65, 66, 67].
        // sextet 1 => codepoint 66 ('B').
        let alpha = "ABC";
        let term = table_select(alpha, 1);
        let smt = emit_term(&term);
        // The ite chain must contain at least one (ite ...) expression.
        assert!(
            smt.contains("ite"),
            "str.table-select must emit an ite chain, got: {smt}"
        );
        // It must compare against the sextet hex values.
        assert!(
            smt.contains("#x00000001"),
            "ite chain must compare against idx #x00000001, got: {smt}"
        );
        // It must contain the codepoints.
        assert!(
            smt.contains("66"),
            "ite chain must contain codepoint 66 ('B'), got: {smt}"
        );
    }

    #[test]
    fn str_from_code_with_int_arg_emits_str_from_code() {
        // str.from_code with an Int const: -> (str.from_code 90)
        let term = Term::Ctor {
            name: "str.from_code".into(),
            args: vec![Term::Const {
                value: serde_json::json!(90i64),
                sort: s("Int"),
            }],
        };
        let smt = emit_term(&term);
        assert_eq!(
            smt, "(str.from_code 90)",
            "Int-sorted str.from_code must emit directly"
        );
    }

    #[test]
    fn str_concat_emits_str_concat_smt() {
        // str.++("hello", "world") -> (str.++ "hello" "world")
        let term = str_concat(
            Term::Const {
                value: serde_json::Value::String("hello".into()),
                sort: s("String"),
            },
            Term::Const {
                value: serde_json::Value::String("world".into()),
                sort: s("String"),
            },
        );
        let smt = emit_term(&term);
        assert_eq!(
            smt, r#"(str.++ "hello" "world")"#,
            "str.++ must emit as SMT string concatenation"
        );
    }

    #[test]
    fn str_table_select_not_declared_as_uninterpreted_fn() {
        // str.table-select must be treated as a builtin -- it must NOT appear
        // in the set of ctor declarations collected for uninterpreted functions.
        let term = table_select("ABC", 1);
        let mut decls = std::collections::BTreeMap::new();
        collect_ctor_decls_term(&term, None, &mut decls);
        assert!(
            !decls.keys().any(|k| k.contains("str.table-select")),
            "str.table-select must not be declared as uninterpreted fn, got decls: {decls:?}"
        );
    }

    #[test]
    fn str_from_code_not_declared_as_uninterpreted_fn() {
        let term = from_code(Term::Const {
            value: serde_json::json!(65i64),
            sort: s("Int"),
        });
        let mut decls = std::collections::BTreeMap::new();
        collect_ctor_decls_term(&term, None, &mut decls);
        assert!(
            !decls.keys().any(|k| k.contains("str.from_code")),
            "str.from_code must not be declared as uninterpreted fn, got decls: {decls:?}"
        );
    }

    // ── z3 round-trip: SYMBOLIC TEETH ────────────────────────────────────────
    //
    // "foo" (bytes 102, 111, 111) encodes to "Zm9v" in standard base64.
    // Sextets: s0=25, s1=38, s2=61, s3=47.
    //
    // The GOOD formula `(= "Zm9v" (str.++ ...))` must be SAT (composed correctly).
    // The BAD formula `(= "XXXX" (str.++ ...))` must be UNSAT (refuted by the
    // composed consistency obligation, NOT by a self-contradiction or the witness).
    // A SECOND wrong value ("AAAA") must also be UNSAT.

    const STD_B64_ALPHA: &str = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

    /// Build a 4-char base64 output term for input bytes (102,111,111) = "foo".
    /// Uses concrete bv32 sextet constants -- no symbolic variables -- so the
    /// formula is a pure arithmetic/string-theory SAT/UNSAT query.
    fn foo_encode_term() -> Term {
        // sextets for "foo": [25, 38, 61, 47]
        let chars: Vec<Term> = [25i64, 38, 61, 47]
            .iter()
            .map(|&s| from_code(table_select(STD_B64_ALPHA, s)))
            .collect();
        // str.++(chars[0], str.++(chars[1], str.++(chars[2], chars[3])))
        str_concat(
            chars[0].clone(),
            str_concat(
                chars[1].clone(),
                str_concat(chars[2].clone(), chars[3].clone()),
            ),
        )
    }

    fn run_str_formula(expected: &str, rhs_term: &Term) -> String {
        use std::io::Write;
        use std::process::{Command, Stdio};
        let rhs_smt = emit_term(rhs_term);
        let script =
            format!("(set-logic ALL)\n(assert (= \"{expected}\" {rhs_smt}))\n(check-sat)\n");
        let mut child = Command::new("z3")
            .args(["-smt2", "-in"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("spawn z3");
        child
            .stdin
            .as_mut()
            .unwrap()
            .write_all(script.as_bytes())
            .unwrap();
        String::from_utf8_lossy(&child.wait_with_output().unwrap().stdout)
            .trim()
            .to_string()
    }

    #[test]
    fn composed_foo_encode_good_twin_is_sat() {
        use std::process::Command;
        if Command::new("z3").arg("--version").output().is_err() {
            eprintln!("z3 absent: skipping str_table_select z3 integration test");
            return;
        }
        let rhs = foo_encode_term();
        assert!(
            run_str_formula("Zm9v", &rhs).starts_with("sat"),
            "GOOD twin: encode(foo)==Zm9v must be SAT via composed str.table-select + str.from_code + str.++"
        );
    }

    #[test]
    fn composed_foo_encode_bad_twin_xxxx_is_unsat() {
        use std::process::Command;
        if Command::new("z3").arg("--version").output().is_err() {
            eprintln!("z3 absent: skipping str_table_select z3 integration test");
            return;
        }
        let rhs = foo_encode_term();
        assert!(
            run_str_formula("XXXX", &rhs).starts_with("unsat"),
            "BAD twin: encode(foo)==XXXX must be UNSAT (refuted by composed consistency)"
        );
    }

    #[test]
    fn composed_foo_encode_bad_twin_aaaa_is_unsat() {
        use std::process::Command;
        if Command::new("z3").arg("--version").output().is_err() {
            eprintln!("z3 absent: skipping str_table_select z3 integration test");
            return;
        }
        let rhs = foo_encode_term();
        assert!(
            run_str_formula("AAAA", &rhs).starts_with("unsat"),
            "BAD twin (different wrong value): encode(foo)==AAAA must be UNSAT"
        );
    }
}

// ──────────────────────────────────────────────────────────────────────────
// Monadic ADT discriminant tester emission (Part 1 carrier, #3445).
//
// Teeth for T's Part-1 ruling: the reserved atomic family `adt.is_*` renders as
// NATIVE datatype testers `((_ is |opt:some|) x)` routed by operand ADT sort,
// NEVER as an EUF `(declare-fun adt.is_* (...) Bool)` predicate (which would
// collapse the sum and turn a lie SAT). Unestablishable operand sort = RED.
// ──────────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod monadic_adt_tester_tests {
    use super::*;
    use sugar_ir_types::IrTerm as Term;

    fn var(name: &str) -> Term {
        Term::Var { name: name.into() }
    }

    fn int_const(value: i64) -> Term {
        Term::Const {
            value: serde_json::json!(value),
            sort: Sort::Primitive { name: "Int".into() },
        }
    }

    fn ctor(name: &str, args: Vec<Term>) -> Term {
        Term::Ctor {
            name: name.into(),
            args,
        }
    }

    fn tester(name: &str, arg: Term) -> Formula {
        Formula::Atomic {
            name: name.into(),
            args: vec![arg],
        }
    }

    fn full_script(f: &Formula) -> String {
        let compiled = compile_formula(f).expect("compile_formula");
        format!("{}{}", compiled.preamble, compiled.body)
    }

    // TOOTH 1 (truthful render + EUF-collapse regression): a tester over a
    // symbolic option operand renders the NATIVE datatype tester, declares the
    // operand with the ADT sort, and NEVER declares `adt.is_*` as an
    // uninterpreted predicate.
    #[test]
    fn adt_is_some_over_symbolic_operand_renders_native_tester_not_euf() {
        let script = full_script(&tester(ADT_IS_SOME, var("r")));
        assert!(
            script.contains("((_ is |opt:some|) r)"),
            "must render the native datatype tester; got:\n{script}"
        );
        // The symbolic operand is declared with the ADT sort (well-sorted).
        assert!(
            script.contains("(declare-const r SugarOption)"),
            "operand must be declared SugarOption; got:\n{script}"
        );
        // EUF-collapse regression: the tester is NEVER an uninterpreted predicate.
        assert!(
            !script.contains("declare-fun |adt.is") && !script.contains("declare-fun adt.is"),
            "adt.is_* must NOT be declared as an uninterpreted predicate; got:\n{script}"
        );
        // The reserved atomic name never leaks into the script verbatim -- it is
        // fully interpreted into the datatype tester.
        assert!(
            !script.contains("adt.is_some"),
            "reserved tester name must be fully interpreted away; got:\n{script}"
        );
    }

    // TOOTH 2 (per-family routing): each tester routes to its ADT constructor
    // discriminant over the correct declared datatype.
    #[test]
    fn each_family_routes_to_its_constructor_discriminant() {
        let none = full_script(&tester(ADT_IS_NONE, var("r")));
        assert!(none.contains("((_ is |opt:none|) r)"), "{none}");
        assert!(none.contains("(declare-const r SugarOption)"), "{none}");

        let ok = full_script(&tester(ADT_IS_OK, var("r")));
        assert!(ok.contains("((_ is |res:ok|) r)"), "{ok}");
        assert!(ok.contains("(declare-const r SugarResult)"), "{ok}");
        assert!(ok.contains("(declare-datatypes ((SugarResult 0))"), "{ok}");

        let err = full_script(&tester(ADT_IS_ERR, var("r")));
        assert!(err.contains("((_ is |res:err|) r)"), "{err}");
        assert!(err.contains("(declare-const r SugarResult)"), "{err}");
    }

    // TOOTH 3 (wrap-depth from operand): a tester over a NESTED concrete monadic
    // value routes to the Option-wrapped constructor (`opt:some#option`).
    #[test]
    fn tester_over_nested_value_routes_to_wrapped_constructor() {
        let nested = ctor(OPT_SOME, vec![ctor(OPT_SOME, vec![int_const(5)])]);
        let script = full_script(&tester(ADT_IS_SOME, nested));
        assert!(
            script.contains("((_ is |opt:some#option|)"),
            "nested value must route to the wrapped constructor; got:\n{script}"
        );
    }

    // TOOTH 4 (unestablishable / mismatched operand = RED, loudly): a tester
    // whose operand sort belongs to the OTHER family, or a wrong arity, refuses
    // rather than falling back to a silent Int predicate.
    #[test]
    fn tester_over_wrong_family_operand_is_red() {
        // adt.is_some over a concrete Result value: family mismatch -> RED.
        let mismatched = tester(ADT_IS_SOME, ctor(RES_OK, vec![int_const(1)]));
        assert!(
            compile_formula(&mismatched).is_err(),
            "adt.is_some over a SugarResult operand must refuse"
        );
        // Direct renderer refusal (loud CompileError), not Ok(None).
        assert!(
            emit_monadic_adt_tester_atomic(ADT_IS_SOME, &[ctor(RES_ERR, vec![int_const(1)])])
                .is_err()
        );
    }

    #[test]
    fn tester_with_wrong_arity_is_red() {
        assert!(emit_monadic_adt_tester_atomic(ADT_IS_SOME, &[var("a"), var("b")]).is_err());
        assert!(emit_monadic_adt_tester_atomic(ADT_IS_OK, &[]).is_err());
    }

    // The tester family is claimed as builtin/interpreted so no decl pass emits
    // a `(declare-fun adt.is_* ...)`.
    #[test]
    fn tester_family_is_builtin_interpreted() {
        for name in [ADT_IS_SOME, ADT_IS_NONE, ADT_IS_OK, ADT_IS_ERR] {
            assert!(
                is_builtin_atomic_predicate(name),
                "{name} must be treated as builtin/interpreted"
            );
        }
    }

    // SELECTOR EXCLUSION (#3445 Part 1 slice 2, discovered sub-requirement of
    // #3727): a payload selector `opt:some#0(r)` reads out of the ADT as a NATIVE
    // datatype projection (the some-arm value of the symbolic-variant guarded
    // split `cf_ite(adt.is_some(r), cf_guarded(is_some, opt:some#0(r)), ...)`).
    // It must render as the application `(|opt:some#0| r)` and NEVER be
    // re-declared as an uninterpreted function -- a second `(declare-fun
    // opt:some#0 ...)` shadows the datatype selector and strips its projection
    // law (`opt:some#0(opt:some v) = v`), so the payload floats free. This is the
    // SELECTOR twin of the tester's EUF-collapse regression. The co-located
    // tester establishes `r: SugarOption`, so the selector is well-sorted.
    #[test]
    fn payload_selector_renders_native_projection_not_euf() {
        let f = Formula::And {
            operands: vec![
                tester(ADT_IS_SOME, var("r")),
                Formula::Atomic {
                    name: "=".into(),
                    args: vec![ctor("opt:some#0", vec![var("r")]), int_const(5)],
                },
            ],
        };
        let script = full_script(&f);
        // Native selector projection application over the ADT operand.
        assert!(
            script.contains("(|opt:some#0| r)"),
            "payload selector must render as a native datatype projection; got:\n{script}"
        );
        // EUF-collapse twin regression: the selector is NEVER an uninterpreted fn.
        assert!(
            !script.contains("declare-fun |opt:some#0|")
                && !script.contains("declare-fun opt:some#0"),
            "opt:some#0 must NOT be declared as an uninterpreted function; got:\n{script}"
        );
        // The datatype (whose declaration carries the selector) is emitted, and
        // the symbolic operand is declared with the ADT sort.
        assert!(
            script.contains("(declare-datatypes ((SugarOption 0))"),
            "SugarOption datatype (carrying the selector) must be declared; got:\n{script}"
        );
        assert!(
            script.contains("(declare-const r SugarOption)"),
            "operand must be declared SugarOption; got:\n{script}"
        );
    }

    // The selector family is recognized as a datatype projection (excluded from
    // the uninterpreted-fn decl pass); the nullary `opt:none` has no field, and a
    // generic ctor accessor is NOT a monadic selector.
    #[test]
    fn monadic_field_accessor_recognizer_is_exact() {
        for name in [
            "opt:some#0",
            "res:ok#0",
            "res:err#0",
            "opt:some#option#0",
            "res:ok#option#0",
            "res:err#option#0",
        ] {
            assert!(is_monadic_field_accessor(name), "{name} must be a selector");
        }
        for name in [
            "opt:none#0",
            "opt:some",
            "call:foo#0",
            "opt:some#1",
            "res:ok",
        ] {
            assert!(
                !is_monadic_field_accessor(name),
                "{name} must NOT be a selector"
            );
        }
    }
}
