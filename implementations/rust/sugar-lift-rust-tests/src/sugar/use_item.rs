// SPDX-License-Identifier: Apache-2.0
//
// `UseSugar`: compiler import facts, not type checking. For compiling Rust, the
// compiler has already accepted `use super::*`; this sugar materializes the visible
// parent const items / value functions into the current registries so `ConstSugar`
// and value-call sugar can recurse into their source.

use std::collections::BTreeSet;

use syn::{Item, UseTree};

use crate::{ConstRegistry, ConstSourceRegistry, FnRegistry, FunctionSourceRegistry};

pub(crate) fn const_imports_for_items(
    items: &[Item],
    source_path: &str,
    source_consts: &ConstSourceRegistry,
) -> ConstRegistry {
    let mut seen = BTreeSet::new();
    const_imports_for_items_seen(items, source_path, source_consts, &mut seen)
}

pub(crate) fn const_imports_for_items_seen(
    items: &[Item],
    source_path: &str,
    source_consts: &ConstSourceRegistry,
    seen: &mut BTreeSet<String>,
) -> ConstRegistry {
    let mut out = ConstRegistry::new();
    for item in items {
        match item {
            Item::Use(u) => collect_use_tree(&u.tree, source_path, source_consts, &mut out, seen),
            Item::Mod(m) => {
                if let Some((_, items)) = &m.content {
                    let nested =
                        const_imports_for_items_seen(items, source_path, source_consts, seen);
                    out.merge_all(&nested);
                }
            }
            _ => {}
        }
    }
    out
}

pub(crate) fn fn_imports_for_items(
    items: &[Item],
    source_path: &str,
    source_fns: &FunctionSourceRegistry,
) -> FnRegistry {
    let mut out = FnRegistry::new();
    for item in items {
        match item {
            Item::Use(u) => collect_use_tree_fns(&u.tree, source_path, source_fns, &mut out),
            Item::Mod(m) => {
                if let Some((_, items)) = &m.content {
                    let nested = fn_imports_for_items(items, source_path, source_fns);
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
    seen: &mut BTreeSet<String>,
) {
    match tree {
        UseTree::Path(path) if path.ident == "super" => {
            collect_super_use_tree(&path.tree, source_path, source_consts, out, seen)
        }
        UseTree::Group(group) => {
            for item in &group.items {
                collect_use_tree(item, source_path, source_consts, out, seen);
            }
        }
        _ => {}
    }
}

fn collect_use_tree_fns(
    tree: &UseTree,
    source_path: &str,
    source_fns: &FunctionSourceRegistry,
    out: &mut FnRegistry,
) {
    match tree {
        UseTree::Path(path) if path.ident == "super" => {
            collect_super_use_tree_fns(&path.tree, source_path, source_fns, out)
        }
        UseTree::Path(path) if path.ident == "crate" => {
            collect_crate_use_tree_fns(&path.tree, source_path, source_fns, out)
        }
        UseTree::Group(group) => {
            for item in &group.items {
                collect_use_tree_fns(item, source_path, source_fns, out);
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
    seen: &mut BTreeSet<String>,
) {
    match tree {
        UseTree::Glob(_) => {
            let Some(parent_path) = parent_module_source_path(source_path) else {
                return;
            };
            let parent_consts =
                source_consts.effective_registry_for_source_seen(&parent_path, seen);
            out.merge_all(&parent_consts);
        }
        UseTree::Name(name) => {
            let Some(parent_path) = parent_module_source_path(source_path) else {
                return;
            };
            let parent_consts =
                source_consts.effective_registry_for_source_seen(&parent_path, seen);
            if let Some(expr) = parent_consts.lookup(&name.ident.to_string()) {
                out.insert(&name.ident.to_string(), expr);
            }
        }
        UseTree::Path(path) => collect_super_module_use_tree(
            &path.ident.to_string(),
            &path.tree,
            source_path,
            source_consts,
            out,
            seen,
        ),
        UseTree::Group(group) => {
            for item in &group.items {
                collect_super_use_tree(item, source_path, source_consts, out, seen);
            }
        }
        _ => {}
    }
}

fn collect_super_module_use_tree(
    module: &str,
    tree: &UseTree,
    source_path: &str,
    source_consts: &ConstSourceRegistry,
    out: &mut ConstRegistry,
    seen: &mut BTreeSet<String>,
) {
    let Some(module_path) = sibling_module_source_path(source_path, module) else {
        return;
    };
    let module_consts = source_consts.effective_registry_for_source_seen(&module_path, seen);
    match tree {
        UseTree::Name(name) if name.ident == "self" => {
            out.merge_prefixed(module, &module_consts);
        }
        UseTree::Name(name) => {
            if let Some(expr) = module_consts.lookup(&name.ident.to_string()) {
                out.insert(&name.ident.to_string(), expr);
            }
        }
        UseTree::Rename(rename) if rename.ident == "self" => {
            out.merge_prefixed(&rename.rename.to_string(), &module_consts);
        }
        UseTree::Glob(_) => {
            out.merge_all(&module_consts);
        }
        UseTree::Group(group) => {
            for item in &group.items {
                collect_super_module_use_tree(module, item, source_path, source_consts, out, seen);
            }
        }
        _ => {}
    }
}

fn collect_crate_use_tree_fns(
    tree: &UseTree,
    source_path: &str,
    source_fns: &FunctionSourceRegistry,
    out: &mut FnRegistry,
) {
    match tree {
        UseTree::Path(path) => {
            collect_crate_module_use_tree_fns(
                &path.ident.to_string(),
                &path.tree,
                source_path,
                source_fns,
                out,
            );
        }
        UseTree::Group(group) => {
            for item in &group.items {
                collect_crate_use_tree_fns(item, source_path, source_fns, out);
            }
        }
        _ => {}
    }
}

fn collect_crate_module_use_tree_fns(
    module: &str,
    tree: &UseTree,
    source_path: &str,
    source_fns: &FunctionSourceRegistry,
    out: &mut FnRegistry,
) {
    let Some(module_fns) = crate_module_fns(source_path, module, source_fns) else {
        return;
    };
    match tree {
        UseTree::Glob(_) => {
            out.merge_all(module_fns);
        }
        UseTree::Name(name) => {
            if let Some(item) = module_fns.lookup(&name.ident.to_string()) {
                out.insert(&name.ident.to_string(), item);
            }
        }
        UseTree::Group(group) => {
            for item in &group.items {
                collect_crate_module_use_tree_fns(module, item, source_path, source_fns, out);
            }
        }
        _ => {}
    }
}

fn crate_module_fns<'a>(
    source_path: &str,
    module: &str,
    source_fns: &'a FunctionSourceRegistry,
) -> Option<&'a FnRegistry> {
    let mut candidates = Vec::new();
    if let Some((crate_root, _)) = source_path.split_once('/') {
        candidates.push(format!("{crate_root}/{module}/mod.rs"));
        candidates.push(format!("{crate_root}/{module}.rs"));
    }
    candidates.push(format!("{module}/mod.rs"));
    candidates.push(format!("{module}.rs"));
    candidates
        .into_iter()
        .find_map(|candidate| source_fns.registry_for_source(&candidate))
}

fn collect_super_use_tree_fns(
    tree: &UseTree,
    source_path: &str,
    source_fns: &FunctionSourceRegistry,
    out: &mut FnRegistry,
) {
    let Some(parent_path) = parent_module_source_path(source_path) else {
        return;
    };
    match tree {
        UseTree::Glob(_) => {
            if let Some(parent_fns) = source_fns.registry_for_source(&parent_path) {
                out.merge_all(parent_fns);
            }
        }
        UseTree::Name(name) => {
            if let Some(parent_fns) = source_fns.registry_for_source(&parent_path) {
                if let Some(item) = parent_fns.lookup(&name.ident.to_string()) {
                    out.insert(&name.ident.to_string(), item);
                }
            }
        }
        UseTree::Group(group) => {
            for item in &group.items {
                collect_super_use_tree_fns(item, source_path, source_fns, out);
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

fn sibling_module_source_path(source_path: &str, module: &str) -> Option<String> {
    let (dir, _) = source_path.rsplit_once('/')?;
    Some(format!("{dir}/{module}.rs"))
}
