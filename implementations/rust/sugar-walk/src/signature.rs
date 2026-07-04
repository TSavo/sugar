// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Rust language signature lookup.
//
// Lifted Rust terms resolve surface constructors into the rust:rust operation
// address space. The old menagerie catalog is gone; derive stable local
// operation CIDs from canonical operation names instead of reading a side table.

use std::collections::HashMap;
use std::sync::OnceLock;

use sugar_canonicalizer::blake3_512_of;

pub const RUST_LANGUAGE_SIGNATURE_CID: &str = "blake3-512:6e96976ee181cc32de6dfb326b9b9a96e5f47b7ba8afef9606d93cee15984fc1c81de78491da094a788bf50725b26824e22b16d79a5b80dc76cd169c59aa844c";

static OP_CIDS: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();

pub fn op_cid(surface_name: &str) -> Option<&'static str> {
    let op_name = canonical_operation_name(surface_name)?;
    OP_CIDS.get_or_init(load_op_cids).get(op_name).copied()
}

pub fn canonical_operation_name(surface_name: &str) -> Option<&str> {
    match surface_name {
        "==" | "=" | "eq" => Some("eq"),
        "!=" | "ne" => Some("ne"),
        "\u{2260}" => Some("ne"),
        "+" | "add" => Some("add"),
        "-" | "sub" => Some("sub"),
        "*" | "mul" => Some("mul"),
        "/" | "div" => Some("div"),
        "%" | "rem" => Some("rem"),
        "<" | "lt" => Some("lt"),
        "<=" | "le" => Some("le"),
        "\u{2264}" => Some("le"),
        ">" | "gt" => Some("gt"),
        ">=" | "ge" => Some("ge"),
        "\u{2265}" => Some("ge"),
        "&&" | "and" => Some("and"),
        "||" | "or" => Some("or"),
        "!" | "not" => Some("not"),
        "&" | "bit_and" => Some("bit_and"),
        "|" | "bit_or" => Some("bit_or"),
        "^" | "bit_xor" => Some("bit_xor"),
        "<<" | "shl" => Some("shl"),
        ">>" | "shr" => Some("shr"),
        "bit-not" | "bit_not" => Some("bit_not"),
        "field" => Some("field"),
        name if name.starts_with("method:") => Some("method_call"),
        name if name.starts_with("call:") => Some("call_result"),
        name if name.starts_with("macro_call:") => Some("call_result"),
        op @ ("skip" | "seq" | "if" | "while" | "for" | "switch" | "call" | "return" | "break"
        | "continue" | "deref" | "member" | "assign" | "neg" | "panic" | "try"
        | "try_option" | "match" | "match_expr" | "borrow" | "borrow_mut" | "deref_raw"
        | "drop" | "await" | "index" | "box_new" | "closure" | "closure_call" | "cast"
        | "move" | "range" | "range_incl" | "tuple" | "array" | "array_repeat" | "len"
        | "ite" | "method_call" | "call_result" | "loop" | "let" | "into_iter" | "next"
        | "arm" | "arms" | "guarded_arm" | "if_let" | "while_let" | "pattern_ok"
        | "pattern_err" | "pattern_some" | "pattern_none" | "pattern_wild"
        | "pattern_bind") => Some(op),
        // sugar-audit: not-mine(non-signature-operation-name-has-no-rust-op-cid)
        _ => None,
    }
}

fn load_op_cids() -> HashMap<&'static str, &'static str> {
    let mut by_name = HashMap::new();
    for op_name in KNOWN_OP_NAMES {
        let cid = blake3_512_of(format!("sugar:rust-op:{op_name}").as_bytes());
        by_name.insert(
            *op_name,
            Box::leak(cid.to_string().into_boxed_str()) as &'static str,
        );
    }
    by_name
}

const KNOWN_OP_NAMES: &[&str] = &[
    "add",
    "and",
    "arm",
    "arms",
    "array",
    "array_repeat",
    "assign",
    "await",
    "bit_and",
    "bit_not",
    "bit_or",
    "bit_xor",
    "borrow",
    "borrow_mut",
    "box_new",
    "break",
    "call",
    "call_result",
    "cast",
    "closure",
    "closure_call",
    "continue",
    "deref",
    "deref_raw",
    "div",
    "drop",
    "eq",
    "field",
    "for",
    "ge",
    "gt",
    "guarded_arm",
    "if",
    "if_let",
    "index",
    "into_iter",
    "ite",
    "le",
    "len",
    "let",
    "loop",
    "lt",
    "match",
    "match_expr",
    "member",
    "method_call",
    "move",
    "mul",
    "ne",
    "neg",
    "next",
    "not",
    "or",
    "panic",
    "pattern_bind",
    "pattern_err",
    "pattern_none",
    "pattern_ok",
    "pattern_some",
    "pattern_wild",
    "range",
    "range_incl",
    "rem",
    "return",
    "seq",
    "shl",
    "shr",
    "skip",
    "sub",
    "switch",
    "try",
    "try_option",
    "tuple",
    "while",
    "while_let",
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolves_core_aliases_to_operation_cids() {
        assert_eq!(op_cid("=="), op_cid("eq"));
        assert_eq!(op_cid("="), op_cid("eq"));
        assert_eq!(op_cid("+"), op_cid("add"));
        assert_eq!(op_cid("method:is_some"), op_cid("method_call"));
        assert_eq!(op_cid("call:foo"), op_cid("call_result"));
        assert!(op_cid("seq").unwrap().starts_with("blake3-512:"));
    }
}
