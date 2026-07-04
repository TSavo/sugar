// SPDX-License-Identifier: MIT OR Apache-2.0
//
// sugar doctor: validate a kit's config/manifest wiring up front.

use std::path::PathBuf;

use clap::Parser;
use owo_colors::OwoColorize;
use serde_json::{json, Value};

use crate::doctor::{
    oracle_requested_from_env, run_report_with_context, CheckStatus, DoctorCheck, DoctorContext,
    DoctorMode, DoctorReport,
};
use crate::{EXIT_OK, EXIT_USER_ERROR};

#[derive(Parser, Debug, Clone)]
pub struct DoctorArgs {
    /// Kit directory to validate. Defaults to the current directory.
    /// Must contain a .sugar/config.toml file.
    #[arg(long)]
    pub target: Option<PathBuf>,

    /// Emit structured JSON instead of human-readable text.
    #[arg(long)]
    pub json: bool,

    /// Doctor policy mode.
    #[arg(long, value_enum, default_value_t = DoctorMode::Structural)]
    pub mode: DoctorMode,

    /// Request oracle host readiness checks.
    #[arg(long)]
    pub oracle: bool,
}

pub fn run(args: DoctorArgs) -> u8 {
    let target = match resolve_target(args.target.as_ref()) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("{}: {e}", "error".red().bold());
            return EXIT_USER_ERROR;
        }
    };

    let context = DoctorContext::new(args.mode)
        .with_oracle_requested(args.oracle || oracle_requested_from_env());
    let report = run_report_with_context(&target, context);

    if args.json {
        print_json(&report);
    } else {
        print_human(&report);
    }

    if report.ok {
        EXIT_OK
    } else {
        EXIT_USER_ERROR
    }
}

/// Resolve the target kit directory from an optional CLI path.
fn resolve_target(target: Option<&PathBuf>) -> Result<PathBuf, String> {
    let path = match target {
        Some(p) => {
            if p.is_absolute() {
                p.clone()
            } else {
                std::env::current_dir()
                    .map_err(|e| format!("read current directory: {e}"))?
                    .join(p)
            }
        }
        None => std::env::current_dir().map_err(|e| format!("read current directory: {e}"))?,
    };

    let canonical = path
        .canonicalize()
        .map_err(|e| format!("resolve target {}: {e}", path.display()))?;

    if !canonical.join(".sugar/config.toml").is_file() {
        return Err(format!(
            "target is not a sugar kit (missing .sugar/config.toml): {}",
            canonical.display()
        ));
    }

    Ok(canonical)
}

fn print_human(report: &DoctorReport) {
    println!(
        "{} {}",
        "sugar doctor".bold(),
        report.target.display().to_string().dimmed()
    );
    println!();

    let mut passes = 0usize;
    let mut warns = 0usize;
    let mut fails = 0usize;

    for check in &report.checks {
        let (label, colored_name) = match check.status {
            CheckStatus::Pass => {
                passes += 1;
                (
                    "pass".green().bold().to_string(),
                    check.name.green().to_string(),
                )
            }
            CheckStatus::Warn => {
                warns += 1;
                (
                    "warn".yellow().bold().to_string(),
                    check.name.yellow().to_string(),
                )
            }
            CheckStatus::Fail => {
                fails += 1;
                (
                    "FAIL".red().bold().to_string(),
                    check.name.red().to_string(),
                )
            }
        };
        println!("  [{label}] {colored_name}");
        if check.status != CheckStatus::Pass || !check.detail.is_empty() {
            println!("         {}", check.detail);
        }
    }

    println!();
    if report.ok {
        println!(
            "{}: {} passed, {} warned, {} failed",
            "ok".green().bold(),
            passes,
            warns,
            fails
        );
    } else {
        println!(
            "{}: {} passed, {} warned, {} failed",
            "FAIL".red().bold(),
            passes,
            warns,
            fails
        );
    }
}

fn print_json(report: &DoctorReport) {
    println!(
        "{}",
        serde_json::to_string_pretty(&legacy_report_json(report)).unwrap_or_default()
    );
}

fn legacy_report_json(report: &DoctorReport) -> Value {
    let checks_json: Vec<Value> = report.checks.iter().map(legacy_check_json).collect();
    json!({
        "checks": checks_json,
        "mode": report.mode.as_str(),
        "ok": report.ok,
        "releaseReady": report.release_ready,
    })
}

fn legacy_check_json(check: &DoctorCheck) -> Value {
    let _ = (&check.id, &check.severity, &check.domain, &check.evidence);
    json!({
        "name": check.name,
        "status": check.status.as_str(),
        "detail": check.detail,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn json_output_keeps_legacy_shape() {
        let td = TempDir::new().unwrap();
        let kit = td.path();
        fs::create_dir_all(kit.join(".sugar/imports")).unwrap();
        fs::write(
            kit.join(".sugar/config.toml"),
            "# test kit\n[authoring]\nsurface = \"test-surface\"\n",
        )
        .unwrap();

        let report = run_report_with_context(kit, DoctorContext::default());
        let value = legacy_report_json(&report);
        let first_check = value["checks"][0].as_object().expect("first check object");

        assert!(value.get("ok").is_some());
        assert_eq!(
            value.get("mode").and_then(Value::as_str),
            Some("structural")
        );
        assert!(first_check.contains_key("name"));
        assert!(first_check.contains_key("status"));
        assert!(first_check.contains_key("detail"));
        assert!(!first_check.contains_key("id"));
        assert!(!first_check.contains_key("domain"));
        assert!(!first_check.contains_key("severity"));
        assert!(!first_check.contains_key("evidence"));
    }

    #[test]
    fn default_mode_is_structural() {
        let args = DoctorArgs::try_parse_from(["doctor"]).unwrap();

        assert_eq!(args.mode, DoctorMode::Structural);
    }

    #[test]
    fn strict_mode_argument_parses() {
        let args = DoctorArgs::try_parse_from(["doctor", "--mode", "strict"]).unwrap();

        assert_eq!(args.mode, DoctorMode::Strict);
    }

    #[test]
    fn release_gate_mode_argument_parses() {
        let args = DoctorArgs::try_parse_from(["doctor", "--mode", "releaseGate"]).unwrap();

        assert_eq!(args.mode, DoctorMode::ReleaseGate);
    }

    #[test]
    fn oracle_argument_requests_oracle_checks() {
        let args = DoctorArgs::try_parse_from(["doctor", "--oracle"]).unwrap();

        assert!(args.oracle);
    }

    #[test]
    fn invalid_mode_is_a_parse_error() {
        let err = DoctorArgs::try_parse_from(["doctor", "--mode", "invalid"])
            .expect_err("invalid mode should fail before doctor checks run")
            .to_string();

        assert!(
            err.contains("invalid"),
            "parse error should name the invalid value: {err}"
        );
        assert!(
            err.contains("structural") && err.contains("strict") && err.contains("releaseGate"),
            "parse error should list valid modes: {err}"
        );
    }
}
