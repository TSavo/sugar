// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `mint-plugin-cid` — compute the content CID for a plugin file per
// 2026-05-12-plugin-protocol.md §6.1.
//
// Usage:
//   mint-plugin-cid <path-to-plugin.json>
//
// Reads the file as a `{ envelope, header }` plugin file (any layer with a
// `header` object), parses `header` into PluginHeader (ignoring the existing
// `cid` field), and prints the computed CID on stdout.
//
// This is the canonical minting recipe for plugin defaults under PEP 1.7.0.
// Used to (re)mint CIDs for substrate defaults like java-canonical.json and
// java-canonical-bodies.json so the `cid` field in the plugin file matches
// the loader's verification.

use std::process::ExitCode;

use sugar_plugin_loader::cid::compute_plugin_cid;
use sugar_plugin_loader::types::PluginHeader;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 2 {
        eprintln!("usage: {} <plugin.json>", args[0]);
        return ExitCode::from(2);
    }

    let path = &args[1];
    let raw = match std::fs::read_to_string(path) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("mint-plugin-cid: read {path}: {e}");
            return ExitCode::from(1);
        }
    };

    let root: serde_json::Value = match serde_json::from_str(&raw) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("mint-plugin-cid: parse JSON {path}: {e}");
            return ExitCode::from(1);
        }
    };

    // The header lives at root["header"]. Parse it as PluginHeader (the
    // existing `cid` field is ignored by compute_plugin_cid per §6.1).
    let header_val = match root.get("header") {
        Some(h) => h.clone(),
        None => {
            eprintln!("mint-plugin-cid: {path}: missing top-level `header` object");
            return ExitCode::from(1);
        }
    };

    let header: PluginHeader = match serde_json::from_value(header_val) {
        Ok(h) => h,
        Err(e) => {
            eprintln!("mint-plugin-cid: {path}: header does not match PluginHeader shape: {e}");
            return ExitCode::from(1);
        }
    };

    let cid = compute_plugin_cid(&header);
    println!("{cid}");
    ExitCode::SUCCESS
}
