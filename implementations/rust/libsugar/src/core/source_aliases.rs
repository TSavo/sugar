// SPDX-License-Identifier: MIT OR Apache-2.0

use serde::{Deserialize, Serialize};

/// Canonical form of a parametric sort application.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParametricSortExpansion {
    /// The composite CID this expansion identifies. cid == blake3-512(JCS({
    /// "kind": "parametric-sort-application",
    /// "constructor_cid": <constructor_cid>,
    /// "arg_cids": <arg_cids>
    /// }))
    pub cid: String,
    pub constructor_cid: String,
    pub arg_cids: Vec<String>,
}

impl ParametricSortExpansion {
    pub fn compose_cid(constructor_cid: &str, arg_cids: &[String]) -> String {
        let canonical = serde_json::json!({
            "kind": "parametric-sort-application",
            "constructor_cid": constructor_cid,
            "arg_cids": arg_cids,
        });
        let jcs = crate::canonical::serializable_jcs(&canonical)
            .expect("parametric expansion canonicalizes");
        sugar_canonicalizer::blake3_512_of(jcs.as_bytes())
    }

    pub fn build(constructor_cid: &str, arg_cids: Vec<String>) -> Self {
        let cid = Self::compose_cid(constructor_cid, &arg_cids);
        Self {
            cid,
            constructor_cid: constructor_cid.to_string(),
            arg_cids,
        }
    }
}

#[derive(Debug, Clone)]
pub enum KitSourceAliasEntry {
    Primitive {
        target_cid: String,
    },
    Constructor {
        constructor_cid: String,
        arity: usize,
    },
    Shorthand {
        composite_cid: String,
        constructor_cid: String,
        arg_cids: Vec<String>,
    },
}

const SORT_INT_CID: &str =
    "blake3-512:30ffc51350121a7172f3e4064a33c45bbd345756979fccff6875cd2ab33e4964d098a99df80cfbdf1ec1a0738c5ac3476f0ff8f75589ea511d1acd82c74ecd58";
const SORT_STRING_CID: &str =
    "blake3-512:be8721d24849feb74c4721520bdba02d352a94f49253a627cd509127472aa1c47cbe99cb705cac4159b5365abcce0c9aaa4901fe67630827deb6be1f9daeea10";
const SORT_BOOL_CID: &str =
    "blake3-512:0ee13bf3fd6b7ecfbee72dfbfc18a7c0ea7f1663de6cca43cefb36f5b4c03665452646094a7c296e819e75d683c6ce4821f3d7db3c3c78ae97f2d4e3451d2074";
const SORT_FLOAT_CID: &str =
    "blake3-512:b979e70c4d5e53d9bdf13d6f08330be3c5b0714b8c770d69bbd05946b86c36df5274be8145a2683cc29c278155c9c1ee65b6897913524eecb9e4c89c71862f57";
const SORT_UNIT_CID: &str =
    "blake3-512:47682b09e5dba71f563db6249c6cb352f7d540986dc7f4cd8d4fb1aa6d9a503064033ee3eb9f36ee6f9e000f700f2f030ebfcfe2b2b8b7e81a345b0d56551f1b";
const SORT_BYTES_CID: &str =
    "blake3-512:7116ef6e62e6739b213a8394f975a53c771b89f08c36d27143827acfcfebc0e39e5b82c530be668c3cfd5ec6966ccaa42930b37fdb1f4ac25652a970be10fb6b";
const SORT_LIST_CID: &str =
    "blake3-512:e3f8d17445f9d2ce89c41c09cbeea08a8bc685d1c34a9fd3dfa7b1df17a94f40eab37396615501f1468baf2a1480fd5a27330ea23202b99876c5f4d97fa2cfb2";
const SORT_MAP_CID: &str =
    "blake3-512:b81923e3273fedfce0b84d401d8b30965d4c72530af6c7538d9ed9b2905348fa3c639636b21b3f47ac8a242e79eef8e278b1d6c9cfab8e289cf059cef94c82e1";
const SORT_REF_CID: &str =
    "blake3-512:37d8efe0ce6321d1a16f80aa06cbdf056c846b8a99613731e8d64d9581af61bc517fd8c87daaff2c817585a7dfd763e09ed729fdc71d25fe16fb1b2e6ca33534";

pub fn load_kit_source_aliases(
    kit: &str,
) -> std::collections::BTreeMap<String, KitSourceAliasEntry> {
    builtin_kit_source_aliases(kit)
}

fn builtin_kit_source_aliases(
    kit: &str,
) -> std::collections::BTreeMap<String, KitSourceAliasEntry> {
    let mut map = std::collections::BTreeMap::new();
    if kit != "rust" {
        return map;
    }

    insert_primitive_aliases(
        &mut map,
        &[
            "i8", "i16", "i32", "i64", "i128", "isize", "u8", "u16", "u32", "u64", "u128", "usize",
        ],
        SORT_INT_CID,
    );
    insert_primitive_aliases(&mut map, &["str", "String", "&str"], SORT_STRING_CID);
    insert_primitive_aliases(&mut map, &["bool"], SORT_BOOL_CID);
    insert_primitive_aliases(&mut map, &["f32", "f64"], SORT_FLOAT_CID);
    insert_primitive_aliases(&mut map, &["()"], SORT_UNIT_CID);
    insert_primitive_aliases(&mut map, &["Vec<u8>", "[u8]"], SORT_BYTES_CID);

    insert_constructor_aliases(&mut map, &["Vec"], SORT_LIST_CID, 1);
    insert_constructor_aliases(&mut map, &["HashMap", "BTreeMap", "Map"], SORT_MAP_CID, 2);
    insert_constructor_aliases(&mut map, &["RefMut", "Box", "&mut"], SORT_REF_CID, 1);

    map
}

fn insert_primitive_aliases(
    map: &mut std::collections::BTreeMap<String, KitSourceAliasEntry>,
    aliases: &[&str],
    target_cid: &str,
) {
    for alias in aliases {
        map.insert(
            (*alias).to_string(),
            KitSourceAliasEntry::Primitive {
                target_cid: target_cid.to_string(),
            },
        );
    }
}

fn insert_constructor_aliases(
    map: &mut std::collections::BTreeMap<String, KitSourceAliasEntry>,
    aliases: &[&str],
    constructor_cid: &str,
    arity: usize,
) {
    for alias in aliases {
        map.insert(
            (*alias).to_string(),
            KitSourceAliasEntry::Constructor {
                constructor_cid: constructor_cid.to_string(),
                arity,
            },
        );
    }
}

pub fn rust_type_to_sort_cid(
    rust_type: &str,
    aliases: &std::collections::BTreeMap<String, KitSourceAliasEntry>,
    expansions: &mut Vec<ParametricSortExpansion>,
) -> Option<String> {
    let trimmed = rust_type.trim();

    if trimmed.starts_with("&mut ")
        || (trimmed.starts_with("&mut") && !trimmed.starts_with("&mute"))
    {
        let inner_src = if trimmed.starts_with("&mut ") {
            &trimmed[5..]
        } else {
            &trimmed[4..]
        };
        let inner_cid = rust_type_to_sort_cid(inner_src, aliases, expansions)?;
        let mut_alias = aliases.get("&mut")?;
        if let KitSourceAliasEntry::Constructor {
            constructor_cid, ..
        } = mut_alias
        {
            let exp = ParametricSortExpansion::build(constructor_cid, vec![inner_cid]);
            let cid = exp.cid.clone();
            if !expansions.iter().any(|e| e.cid == cid) {
                expansions.push(exp);
            }
            return Some(cid);
        }
        return None;
    }

    let t = trimmed.trim_start_matches('&').trim();
    let t = if let Some(stripped) = t.strip_prefix("Option<").and_then(|s| s.strip_suffix('>')) {
        stripped.trim()
    } else if let Some(stripped) = t.strip_prefix("Result<") {
        let mut depth = 0i32;
        let mut end = stripped.len();
        for (i, ch) in stripped.chars().enumerate() {
            match ch {
                '<' => depth += 1,
                '>' => depth -= 1,
                ',' if depth == 0 => {
                    end = i;
                    break;
                }
                _ => {}
            }
        }
        stripped[..end].trim()
    } else {
        t
    };

    if let Some(entry) = aliases.get(t) {
        return resolve_alias_entry(entry, &[], aliases, expansions);
    }

    if let Some(open) = t.find('<') {
        if t.ends_with('>') {
            let outer = t[..open].trim();
            let inside = &t[open + 1..t.len() - 1];
            let arg_srcs = split_top_level_commas(inside);
            if let Some(entry) = aliases.get(outer) {
                return resolve_alias_entry(entry, &arg_srcs, aliases, expansions);
            }
        }
    }

    if let Some(rest) = t.strip_prefix('[').and_then(|s| s.strip_suffix(']')) {
        let inner_src = rest.split(';').next().unwrap_or(rest).trim();
        if inner_src == "u8" {
            if let Some(entry) = aliases.get("[u8]") {
                return resolve_alias_entry(entry, &[], aliases, expansions);
            }
        }
        if let Some(entry) = aliases.get("Vec") {
            if let KitSourceAliasEntry::Constructor { .. } = entry {
                return resolve_alias_entry(entry, &[inner_src.to_string()], aliases, expansions);
            }
        }
    }

    None
}

fn resolve_alias_entry(
    entry: &KitSourceAliasEntry,
    arg_srcs: &[String],
    aliases: &std::collections::BTreeMap<String, KitSourceAliasEntry>,
    expansions: &mut Vec<ParametricSortExpansion>,
) -> Option<String> {
    match entry {
        KitSourceAliasEntry::Primitive { target_cid } => Some(target_cid.clone()),
        KitSourceAliasEntry::Shorthand {
            composite_cid,
            constructor_cid,
            arg_cids,
        } => {
            let exp = ParametricSortExpansion {
                cid: composite_cid.clone(),
                constructor_cid: constructor_cid.clone(),
                arg_cids: arg_cids.clone(),
            };
            if !expansions.iter().any(|e| e.cid == exp.cid) {
                expansions.push(exp);
            }
            Some(composite_cid.clone())
        }
        KitSourceAliasEntry::Constructor {
            constructor_cid,
            arity,
        } => {
            if arg_srcs.len() != *arity {
                return None;
            }
            let mut arg_cids = Vec::with_capacity(arg_srcs.len());
            for a in arg_srcs {
                arg_cids.push(rust_type_to_sort_cid(a, aliases, expansions)?);
            }
            let exp = ParametricSortExpansion::build(constructor_cid, arg_cids);
            let cid = exp.cid.clone();
            if !expansions.iter().any(|e| e.cid == cid) {
                expansions.push(exp);
            }
            Some(cid)
        }
    }
}

fn split_top_level_commas(s: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut depth = 0i32;
    let mut cur = String::new();
    for c in s.chars() {
        if c == '<' {
            depth += 1;
        } else if c == '>' {
            depth -= 1;
        }
        if c == ',' && depth == 0 {
            out.push(cur.trim().to_string());
            cur.clear();
        } else {
            cur.push(c);
        }
    }
    if !cur.trim().is_empty() {
        out.push(cur.trim().to_string());
    }
    out
}
