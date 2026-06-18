// SPDX-License-Identifier: Apache-2.0
//
// `UseSugar`: compiler import facts, not type checking. For compiling Rust, the
// compiler has already accepted `use super::*`; this sugar materializes the visible
// parent const items into the current const registry so `ConstSugar` can recurse into
// their initializer expressions.

use syn::{Item, UseTree};

use crate::{ConstRegistry, ConstSourceRegistry};

pub(crate) fn const_imports_for_items(
    items: &[Item],
    source_path: &str,
    source_consts: &ConstSourceRegistry,
) -> ConstRegistry {
    let mut out = ConstRegistry::new();
    for item in items {
        match item {
            Item::Use(u) => collect_use_tree(&u.tree, source_path, source_consts, &mut out),
            Item::Mod(m) => {
                if let Some((_, items)) = &m.content {
                    let nested = const_imports_for_items(items, source_path, source_consts);
                    out.merge_all(&nested);
                }
            }
            _ => {}
        }
    }
    out
}

fn collect_use_tree(
    tree: &UseTree,
    source_path: &str,
    source_consts: &ConstSourceRegistry,
    out: &mut ConstRegistry,
) {
    match tree {
        UseTree::Path(path) if path.ident == "super" => {
            collect_super_use_tree(&path.tree, source_path, source_consts, out)
        }
        UseTree::Group(group) => {
            for item in &group.items {
                collect_use_tree(item, source_path, source_consts, out);
            }
        }
        _ => {}
    }
}

fn collect_super_use_tree(
    tree: &UseTree,
    source_path: &str,
    source_consts: &ConstSourceRegistry,
    out: &mut ConstRegistry,
) {
    let Some(parent_path) = parent_module_source_path(source_path) else {
        return;
    };
    match tree {
        UseTree::Glob(_) => {
            if let Some(parent_consts) = source_consts.registry_for_source(&parent_path) {
                out.merge_all(parent_consts);
            }
        }
        UseTree::Name(name) => {
            if let Some(parent_consts) = source_consts.registry_for_source(&parent_path) {
                if let Some(expr) = parent_consts.lookup(&name.ident.to_string()) {
                    out.insert(&name.ident.to_string(), expr);
                }
            }
        }
        UseTree::Group(group) => {
            for item in &group.items {
                collect_super_use_tree(item, source_path, source_consts, out);
            }
        }
        _ => {}
    }
}

fn parent_module_source_path(source_path: &str) -> Option<String> {
    let tests_suffix = "/tests.rs";
    if let Some(base) = source_path.strip_suffix(tests_suffix) {
        return Some(format!("{base}.rs"));
    }
    None
}
