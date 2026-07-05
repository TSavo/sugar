// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Visible end-to-end demonstration of paper 07's Rust source walk.
//
// This binary intentionally mirrors the current `walk_emit` API path:
// parse Rust source with syn, lift the callee precondition, build the
// caller shadow source, print arrival CIDs, and compose the chain.

use std::process::ExitCode;

use sugar_walk::{
    build_shadow_source, compose_chain, edge_memento_cid, lift_function_precondition,
    CalleeContract, ShadowArrival,
};

const BARE_DEMO_SRC: &str = r#"
fn f(x: u32) -> u32 {
    if x < 10 {
        panic!();
    }
    x + 1
}

fn main() {
    let y = 12;
    let _z = f(y);
}
"#;

fn main() -> ExitCode {
    let file: syn::File = match syn::parse_str(BARE_DEMO_SRC) {
        Ok(file) => file,
        Err(e) => {
            eprintln!("error parsing demo source: {e}");
            return ExitCode::from(1);
        }
    };

    let callee = match find_fn(&file, "f") {
        Some(f) => f,
        None => {
            eprintln!("demo source missing callee `f`");
            return ExitCode::from(2);
        }
    };
    let caller = match find_fn(&file, "main") {
        Some(f) => f,
        None => {
            eprintln!("demo source missing caller `main`");
            return ExitCode::from(3);
        }
    };

    let precondition = lift_function_precondition(&callee);
    let formal_params = all_param_names(&callee);
    let shadow = build_shadow_source(
        &caller,
        &[CalleeContract {
            callee_name: "f".to_string(),
            formal_params,
            precondition,
        }],
    );

    println!("shadow source: {}", shadow.cid);
    println!("slots: {}", shadow.slots.len());

    let arrivals: Vec<&ShadowArrival> = shadow.all_arrivals().map(|(_, arrival)| arrival).collect();
    if arrivals.is_empty() {
        eprintln!("demo produced no shadow arrivals");
        return ExitCode::from(4);
    }

    for arrival in &arrivals {
        println!(
            "arrival: cid={} source_index={} predecessor={:?} allocation={:?}",
            edge_memento_cid(arrival),
            arrival.source_index,
            arrival.predecessor_cid,
            arrival.allocation_cid,
        );
    }

    let edge = compose_chain(arrivals.iter().copied());
    println!("composed edge: {}", edge.cid);
    ExitCode::SUCCESS
}

fn find_fn(file: &syn::File, name: &str) -> Option<syn::ItemFn> {
    file.items.iter().find_map(|item| match item {
        syn::Item::Fn(f) if f.sig.ident == name => Some(f.clone()),
        // sugar-audit: not-mine(demo-helper-search-ignores-non-target-items)
        _ => None,
    })
}

fn all_param_names(item_fn: &syn::ItemFn) -> Vec<String> {
    item_fn
        .sig
        .inputs
        .iter()
        .enumerate()
        .map(|(i, arg)| match arg {
            syn::FnArg::Receiver(_) => "__self".to_string(),
            syn::FnArg::Typed(pt) => match &*pt.pat {
                syn::Pat::Ident(p) => p.ident.to_string(),
                _ => format!("__arg{}", i),
            },
        })
        .collect()
}
