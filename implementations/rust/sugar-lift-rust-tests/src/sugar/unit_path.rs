// SPDX-License-Identifier: Apache-2.0
//
// Shared unit-path value vocabulary. For compiling Rust, `Zst` in a const-value
// context is a compiler-resolved zero-sized value constructor, not a runtime
// read. Sugars that own such contexts use this helper to model it as a literal
// identity term so arrays/options built from it compose structurally.

use crate::const_path_key;

pub(crate) fn unit_path_name(path: &syn::Path) -> Option<String> {
    let name = const_path_key(path)?;
    let final_ident = path.segments.last()?.ident.to_string();
    if !is_unit_value_ident(&final_ident) {
        return None;
    }
    Some(name)
}

pub(crate) fn unit_path_literal_name(name: &str) -> String {
    format!("literal:unitpath:{name}")
}

fn is_unit_value_ident(ident: &str) -> bool {
    if matches!(ident, "None" | "Some" | "Ok" | "Err") {
        return false;
    }
    let mut chars = ident.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    first.is_ascii_uppercase() && ident.chars().any(|ch| ch.is_ascii_lowercase())
}
