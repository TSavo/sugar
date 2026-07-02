// SPDX-License-Identifier: Apache-2.0
//
// `sugar-walk-emit`: take a Rust source file, lift + walk + shadow,
// emit a proof.ir bundle as JCS-canonical bytes on stdout. It also has
// term and contract modes for single-function rust:rust exhibits.
//
// Usage:
//   sugar-walk-emit <source.rs> <callee_name> <caller_name>
//   sugar-walk-emit term <source.rs> <function_name> [output.term.json]
//   sugar-walk-emit contract <source.rs> <function_name> [output.contract.json]
//
// Example:
//   echo '<<bare-demo source>>' > demo.rs
//   sugar-walk-emit demo.rs f main > demo.proof.ir.json
//   blake3sum demo.proof.ir.json   # check matches the bundle's own CID

use std::env;
use std::fs;
use std::io::{self, Write};
use std::process::ExitCode;

use sugar_walk::emit::{shadow_proof_ir_cid, shadow_to_proof_ir};
use sugar_walk::{
    build_function_contract_with_file, build_shadow_source, lift_function_precondition,
    CalleeContract,
};

fn main() -> ExitCode {
    let args: Vec<String> = env::args().collect();
    if args.get(1).map(String::as_str) == Some("term") {
        return emit_term_mode(&args);
    }
    if args.get(1).map(String::as_str) == Some("contract") {
        return emit_contract_mode(&args);
    }
    if args.len() != 4 {
        eprintln!("usage: {} <source.rs> <callee_name> <caller_name>", args[0]);
        eprintln!(
            "   or: {} term <source.rs> <function_name> [output.term.json]",
            args[0]
        );
        eprintln!(
            "   or: {} contract <source.rs> <function_name> [output.contract.json]",
            args[0]
        );
        return ExitCode::from(1);
    }
    let source_path = &args[1];
    let callee_name = &args[2];
    let caller_name = &args[3];

    let src = match fs::read_to_string(source_path) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("error reading {}: {}", source_path, e);
            return ExitCode::from(2);
        }
    };
    let file: syn::File = match syn::parse_str(&src) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("error parsing {}: {}", source_path, e);
            return ExitCode::from(3);
        }
    };

    let callee_fn = match find_fn(&file, callee_name) {
        Some(f) => f,
        None => {
            eprintln!("function `{}` not found in {}", callee_name, source_path);
            return ExitCode::from(4);
        }
    };
    let caller_fn = match find_fn(&file, caller_name) {
        Some(f) => f,
        None => {
            eprintln!("function `{}` not found in {}", caller_name, source_path);
            return ExitCode::from(5);
        }
    };

    let pre = lift_function_precondition(&callee_fn);
    let formal_params = all_param_names(&callee_fn);
    let s = build_shadow_source(
        &caller_fn,
        &[CalleeContract {
            callee_name: callee_name.to_string(),
            formal_params,
            precondition: pre,
        }],
    );

    let bytes = shadow_to_proof_ir(&s);
    let cid = shadow_proof_ir_cid(&s);

    eprintln!(
        "# proof.ir bundle for caller={} callee={}",
        caller_name, callee_name
    );
    eprintln!("# bundle CID:        {}", cid);
    eprintln!("# bundle bytes:      {}", bytes.len());
    eprintln!("# shadowSource CID:  {}", s.cid);
    eprintln!("# slots:             {}", s.slots.len());
    eprintln!(
        "# arrivals (total):  {}",
        s.slots.iter().map(|sl| sl.arrivals.len()).sum::<usize>()
    );

    let mut stdout = io::stdout().lock();
    if let Err(e) = stdout.write_all(&bytes) {
        eprintln!("error writing stdout: {}", e);
        return ExitCode::from(6);
    }
    let _ = stdout.write_all(b"\n");
    ExitCode::SUCCESS
}

fn emit_contract_mode(args: &[String]) -> ExitCode {
    if args.len() != 4 && args.len() != 5 {
        eprintln!(
            "usage: {} contract <source.rs> <function_name> [output.contract.json]",
            args[0]
        );
        return ExitCode::from(1);
    }
    let source_path = &args[2];
    let function_name = &args[3];
    let src = match fs::read_to_string(source_path) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("error reading {}: {}", source_path, e);
            return ExitCode::from(2);
        }
    };
    let file: syn::File = match syn::parse_str(&src) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("error parsing {}: {}", source_path, e);
            return ExitCode::from(3);
        }
    };
    let item_fn = match find_fn(&file, function_name) {
        Some(f) => f,
        None => {
            eprintln!("function `{}` not found in {}", function_name, source_path);
            return ExitCode::from(4);
        }
    };
    let contract = build_function_contract_with_file(&item_fn, None, Some(source_path));
    eprintln!("# rust contract for function={}", function_name);
    eprintln!("# contract CID: {}", contract.cid);
    eprintln!("# contract bytes: {}", contract.canonical_bytes.len());
    if let Some(output_path) = args.get(4) {
        if let Err(e) = fs::write(output_path, &contract.canonical_bytes) {
            eprintln!("error writing {}: {}", output_path, e);
            return ExitCode::from(6);
        }
        return ExitCode::SUCCESS;
    }
    let mut stdout = io::stdout().lock();
    if let Err(e) = stdout.write_all(&contract.canonical_bytes) {
        eprintln!("error writing stdout: {}", e);
        return ExitCode::from(6);
    }
    let _ = stdout.write_all(b"\n");
    ExitCode::SUCCESS
}

fn emit_term_mode(args: &[String]) -> ExitCode {
    if args.len() != 4 && args.len() != 5 {
        eprintln!(
            "usage: {} term <source.rs> <function_name> [output.term.json]",
            args[0]
        );
        return ExitCode::from(1);
    }
    let source_path = &args[2];
    let function_name = &args[3];
    let src = match fs::read_to_string(source_path) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("error reading {}: {}", source_path, e);
            return ExitCode::from(2);
        }
    };
    let file: syn::File = match syn::parse_str(&src) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("error parsing {}: {}", source_path, e);
            return ExitCode::from(3);
        }
    };
    let bytes =
        match sugar_walk::emit::rust_function_term_json_for_file(&file, function_name, source_path)
        {
            Ok(bytes) => bytes,
            Err(e) => {
                eprintln!("term-emit skipped fn={}: {}", function_name, e);
                return ExitCode::from(5);
            }
        };
    let cid = match sugar_walk::emit::rust_function_term_json_cid_for_file(
        &file,
        function_name,
        source_path,
    ) {
        Ok(cid) => cid,
        Err(e) => {
            eprintln!("term-emit skipped fn={}: {}", function_name, e);
            return ExitCode::from(5);
        }
    };
    eprintln!("# rust term for function={}", function_name);
    eprintln!("# term CID: {}", cid);
    eprintln!("# term bytes: {}", bytes.len());
    if let Some(output_path) = args.get(4) {
        if let Err(e) = fs::write(output_path, &bytes) {
            eprintln!("error writing {}: {}", output_path, e);
            return ExitCode::from(6);
        }
        return ExitCode::SUCCESS;
    }
    let mut stdout = io::stdout().lock();
    if let Err(e) = stdout.write_all(&bytes) {
        eprintln!("error writing stdout: {}", e);
        return ExitCode::from(6);
    }
    let _ = stdout.write_all(b"\n");
    ExitCode::SUCCESS
}

fn find_fn(file: &syn::File, name: &str) -> Option<syn::ItemFn> {
    find_fn_in_items(&file.items, name)
}

fn find_fn_in_items(items: &[syn::Item], name: &str) -> Option<syn::ItemFn> {
    for item in items {
        match item {
            syn::Item::Fn(f) if f.sig.ident == name => return Some(f.clone()),
            syn::Item::Impl(impl_block) => {
                for impl_item in &impl_block.items {
                    if let syn::ImplItem::Fn(method) = impl_item {
                        if method.sig.ident == name {
                            return Some(syn::ItemFn {
                                attrs: method.attrs.clone(),
                                vis: method.vis.clone(),
                                sig: method.sig.clone(),
                                block: Box::new(method.block.clone()),
                            });
                        }
                    }
                }
            }
            syn::Item::Mod(module) => {
                if let Some((_, nested_items)) = &module.content {
                    if let Some(found) = find_fn_in_items(nested_items, name) {
                        return Some(found);
                    }
                }
            }
            // sugar-audit: not-mine(cli-helper-search-ignores-non-function-items)
            _ => {}
        }
    }
    None
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
                // Non-Ident patterns (`_: u32`, `(a, b): ...`, etc.) get a
                // stable positional placeholder so the arity stays aligned
                // with the callee's actual argument count.
                _ => format!("__arg{}", i),
            },
        })
        .collect()
}
