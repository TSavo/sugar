// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar version`.

use std::collections::BTreeSet;
use std::path::PathBuf;

use clap::{Args, Subcommand};
use owo_colors::OwoColorize;
use serde_json::{json, Value};

use crate::VersionArgs;

const CLI_VERSION: &str = env!("CARGO_PKG_VERSION");

#[derive(Subcommand, Debug, Clone)]
pub enum VersionCmd {
    /// Check that a candidate contract set is a compatible extension.
    CheckExtension(VersionCheckExtensionArgs),
}

#[derive(Args, Debug, Clone)]
pub struct VersionCheckExtensionArgs {
    /// Baseline release receipt JSON.
    #[arg(long)]
    pub previous: PathBuf,
    /// Candidate release receipt JSON.
    #[arg(long)]
    pub candidate: PathBuf,
}

pub fn run(args: VersionArgs) -> u8 {
    if let Some(cmd) = args.cmd {
        return match cmd {
            VersionCmd::CheckExtension(check_args) => {
                run_check_extension(check_args, args.out.json, args.out.quiet)
            }
        };
    }

    if args.out.json {
        let payload = json!({
            "name": "sugar",
            "version": CLI_VERSION,
        });
        println!("{}", serde_json::to_string_pretty(&payload).unwrap());
    } else {
        println!("{} {}", "sugar".bold(), CLI_VERSION);
    }
    crate::EXIT_OK
}

fn run_check_extension(args: VersionCheckExtensionArgs, json_out: bool, quiet: bool) -> u8 {
    match check_extension(&args.previous, &args.candidate) {
        Ok(report) => {
            let ok = report["ok"].as_bool().unwrap_or(false);
            if json_out {
                println!("{}", serde_json::to_string_pretty(&report).unwrap());
            } else if !quiet {
                let label = if ok {
                    "accepted".green().to_string()
                } else {
                    "rejected".red().to_string()
                };
                println!("version check-extension: {label}");
                println!("  rule: {}", report["rule"]);
                println!("  missingContracts: {}", report["missingContracts"]);
            }
            if ok {
                crate::EXIT_OK
            } else {
                crate::EXIT_VERIFY_FAIL
            }
        }
        Err(error) => {
            eprintln!("{}: {error}", "error".red().bold());
            crate::EXIT_USER_ERROR
        }
    }
}

fn check_extension(previous_path: &PathBuf, candidate_path: &PathBuf) -> Result<Value, String> {
    let previous = read_json(previous_path)?;
    let candidate = read_json(candidate_path)?;
    let previous_set = string_set(&previous, "contracts")?;
    let candidate_set = string_set(&candidate, "contracts")?;
    let missing = previous_set
        .difference(&candidate_set)
        .cloned()
        .collect::<Vec<_>>();
    let previous_contract_set_cid = string_field(&previous, "contractSetCid")?;
    let candidate_previous = candidate
        .get("previousContractSetCid")
        .and_then(Value::as_str)
        .unwrap_or("");
    let previous_link_ok = candidate_previous == previous_contract_set_cid;
    let candidate_contract_set_cid = candidate
        .get("contractSetCid")
        .and_then(Value::as_str)
        .unwrap_or("");
    let candidate_contract_set_cid_present = !candidate_contract_set_cid.is_empty();
    let previous_identity = package_identity(&previous);
    let candidate_identity = package_identity(&candidate);
    let identity_ok =
        receipt_identity_is_complete(&previous_identity) && previous_identity == candidate_identity;
    let ok =
        missing.is_empty() && previous_link_ok && candidate_contract_set_cid_present && identity_ok;
    let verdict = if ok { "accepted" } else { "rejected" };
    Ok(json!({
        "ok": ok,
        "verdict": verdict,
        "rule": "oldSet subset newSet",
        "previousContractSetCid": previous_contract_set_cid,
        "candidatePreviousContractSetCid": candidate_previous,
        "candidateContractSetCid": candidate_contract_set_cid,
        "candidateContractSetCidPresent": candidate_contract_set_cid_present,
        "previousLinkOk": previous_link_ok,
        "previousIdentity": previous_identity,
        "candidateIdentity": candidate_identity,
        "identityOk": identity_ok,
        "missingContracts": missing,
    }))
}

fn read_json(path: &PathBuf) -> Result<Value, String> {
    let text =
        std::fs::read_to_string(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    serde_json::from_str(&text).map_err(|e| format!("parse {}: {e}", path.display()))
}

fn string_field<'a>(value: &'a Value, field: &str) -> Result<&'a str, String> {
    value
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("receipt missing string field `{field}`"))
}

fn string_set(value: &Value, field: &str) -> Result<BTreeSet<String>, String> {
    let array = value
        .get(field)
        .and_then(Value::as_array)
        .ok_or_else(|| format!("receipt missing array field `{field}`"))?;
    array
        .iter()
        .map(|entry| {
            entry
                .as_str()
                .map(str::to_string)
                .ok_or_else(|| format!("receipt field `{field}` must contain only strings"))
        })
        .collect()
}

fn package_identity(receipt: &Value) -> Value {
    json!({
        "ecosystem": receipt
            .get("ecosystem")
            .and_then(Value::as_str)
            .unwrap_or(""),
        "name": receipt
            .pointer("/package/name")
            .and_then(Value::as_str)
            .unwrap_or(""),
    })
}

fn receipt_identity_is_complete(identity: &Value) -> bool {
    identity
        .get("ecosystem")
        .and_then(Value::as_str)
        .is_some_and(|value| !value.is_empty())
        && identity
            .get("name")
            .and_then(Value::as_str)
            .is_some_and(|value| !value.is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::OutputFlags;

    #[test]
    fn version_string_present() {
        // The crate version string isn't empty: env! is compile-time.
        assert!(!CLI_VERSION.is_empty());
    }

    #[test]
    fn version_command_exits_ok() {
        let args = VersionArgs {
            cmd: None,
            out: OutputFlags {
                json: true,
                quiet: false,
            },
        };
        assert_eq!(run(args), crate::EXIT_OK);
    }
}
