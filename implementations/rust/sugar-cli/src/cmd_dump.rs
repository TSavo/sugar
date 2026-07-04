// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar dump <PROOF-FILE>`: read the proof graph and say it out loud.
//
// Dead dumb: ask `ProofGraph::read` for the typed graph, then iterate it --
// atoms (data leaves), bodies (relationships, by atom CID), and members (typed
// views: kind + body pointer). dump never decodes the catalog and never parses
// member or atom bytes; the graph owns all of that. Atom bytes are already
// canonical JSON, so they print verbatim. Source/witness leaves never live in
// the catalog, so they surface as locator members, not bodies.

use std::path::PathBuf;

use anyhow::{anyhow, Context, Result};
use owo_colors::OwoColorize;
use serde_json::json;
use sugar_canonicalizer::blake3_512_of;
use sugar_proof_envelope::ProofGraph;

use crate::DumpArgs;

pub fn run(args: DumpArgs) -> u8 {
    match dump(&args.proof_file, args.out.json, args.out.quiet) {
        Ok(()) => crate::EXIT_OK,
        Err(e) => {
            eprintln!("{}: {e:#}", "error".red().bold());
            crate::EXIT_USER_ERROR
        }
    }
}

fn dump(path: &PathBuf, as_json: bool, quiet: bool) -> Result<()> {
    let bytes = std::fs::read(path).with_context(|| format!("read {}", path.display()))?;
    let derived_cid = blake3_512_of(&bytes);
    let graph = ProofGraph::read(&bytes)
        .map_err(|e| anyhow!("read proof graph from {}: {e}", path.display()))?;

    if as_json {
        let atoms: Vec<String> = graph
            .atoms()
            .map(|a| a.cid().as_str().to_string())
            .collect();
        let bodies: serde_json::Map<String, serde_json::Value> = graph
            .bodies()
            .map(|b| {
                let atom_cids: Vec<String> =
                    b.atoms().map(|a| a.cid().as_str().to_string()).collect();
                (b.cid().as_str().to_string(), json!(atom_cids))
            })
            .collect();
        let members: serde_json::Map<String, serde_json::Value> = graph
            .members_view()
            .map(|v| (v.cid().as_str().to_string(), v.json()))
            .collect();
        let payload = json!({
            "path": path.display().to_string(),
            "cid": derived_cid,
            "atoms": atoms,
            "bodies": bodies,
            "members": members,
        });
        println!("{}", serde_json::to_string_pretty(&payload)?);
        return Ok(());
    }

    if !quiet {
        println!("{}", "Sugar proof graph".bold());
        println!("  file   : {}", path.display());
        println!("  cid    : {}", derived_cid.cyan());
        println!();

        println!("  {} ({})", "atoms".bold(), graph.atoms().count());
        for atom in graph.atoms() {
            println!("    {} {}", "-".bold(), atom.cid().as_str().cyan());
            // Atom bytes ARE canonical JSON -- read them out verbatim, no parse.
            println!("        {}", String::from_utf8_lossy(atom.bytes()));
        }
        println!();

        println!("  {} ({})", "bodies".bold(), graph.bodies().count());
        for body in graph.bodies() {
            println!("    {} {}", "-".bold(), body.cid().as_str().cyan());
            for atom in body.atoms() {
                println!("        -> atom {}", atom.cid().as_str());
            }
        }
        println!();

        let members: Vec<_> = graph.members_view().collect();
        println!("  {} ({})", "members".bold(), members.len());
        for view in &members {
            let kind = view
                .kind()
                .map(|kind| kind.to_string())
                .unwrap_or_else(|| "<unknown>".to_string());
            println!(
                "    {} {} [{}]",
                "-".bold(),
                view.cid().as_str().cyan(),
                kind
            );
            if let Some(body_cid) = view.body_cid() {
                println!("        -> body {body_cid}");
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_file_errors_cleanly() {
        let p = PathBuf::from("/nope/no-proof-here.proof");
        let r = dump(&p, false, true);
        assert!(r.is_err());
    }
}
