// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar init [PROJECT]`.
//
// Creates:
//   <PROJECT>/sugar.toml
//   <PROJECT>/.sugar/cache/.gitkeep
//   <PROJECT>/.sugar/sample.invariant.rs
//   <PROJECT>/.github/workflows/sugar.yml

use std::path::{Path, PathBuf};

use anyhow::{anyhow, Context, Result};
use owo_colors::OwoColorize;

use crate::InitArgs;

pub fn run(args: InitArgs) -> u8 {
    let project = args.project.unwrap_or_else(|| PathBuf::from("."));
    match init_project(&project, args.force, args.out.quiet) {
        Ok(()) => crate::EXIT_OK,
        Err(e) => {
            eprintln!("{}: {e:#}", "error".red().bold());
            crate::EXIT_USER_ERROR
        }
    }
}

pub(crate) fn init_project(project: &Path, force: bool, quiet: bool) -> Result<()> {
    if !project.exists() {
        std::fs::create_dir_all(project)
            .with_context(|| format!("create project dir {}", project.display()))?;
    }

    let toml_path = project.join("sugar.toml");
    write_if_absent_or_force(&toml_path, &sugar_toml_template(), force, "sugar.toml")?;

    let cache_dir = project.join(".sugar").join("cache");
    std::fs::create_dir_all(&cache_dir)
        .with_context(|| format!("create {}", cache_dir.display()))?;
    let gitkeep = cache_dir.join(".gitkeep");
    write_if_absent_or_force(&gitkeep, "", force, ".sugar/cache/.gitkeep")?;

    let sample = project.join(".sugar").join("sample.invariant.rs");
    write_if_absent_or_force(
        &sample,
        SAMPLE_INVARIANT_RS,
        force,
        ".sugar/sample.invariant.rs",
    )?;

    let wf_dir = project.join(".github").join("workflows");
    std::fs::create_dir_all(&wf_dir).with_context(|| format!("create {}", wf_dir.display()))?;
    let wf_path = wf_dir.join("sugar.yml");
    write_if_absent_or_force(
        &wf_path,
        GITHUB_ACTION_TEMPLATE,
        force,
        ".github/workflows/sugar.yml",
    )?;

    if !quiet {
        println!("{}", "Initialized Sugar project".green().bold());
        println!("  root          : {}", project.display());
        println!("  sugar.toml : created");
        println!("  next steps    :");
        println!("    1. Author your first contract under .sugar/");
        println!("    2. Run `sugar prove` to verify the proof catalog.");
    }
    Ok(())
}

fn write_if_absent_or_force(path: &Path, contents: &str, force: bool, label: &str) -> Result<()> {
    if path.exists() && !force {
        return Err(anyhow!(
            "{} already exists at {} (use --force to overwrite)",
            label,
            path.display()
        ));
    }
    std::fs::write(path, contents).with_context(|| format!("write {}", path.display()))?;
    Ok(())
}

fn sugar_toml_template() -> String {
    r#"# Sugar project manifest.

[paths]
# Where signed .proof catalogs live. Walked recursively by `sugar prove`.
proofs = "."

# Where minted artifacts (cached implication mementos, etc.) are stored.
cache = ".sugar/cache"

[solver]
# Path to z3 binary; "z3" defers to PATH.
z3 = "z3"
"#
    .to_string()
}

const SAMPLE_INVARIANT_RS: &str = r#"// Sample Sugar invariant (Rust). Author with the kit primitives.
//
// use sugar_ir_symbolic::{Int, forall, gt, must, num};
//
// must("parseInt", forall(Int(), |n| gt(n, num(0))));
"#;

const GITHUB_ACTION_TEMPLATE: &str = r#"name: sugar
on:
  push:
    branches: [ main ]
  pull_request:
jobs:
  prove:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: install z3
        run: sudo apt-get update && sudo apt-get install -y z3
      - name: install sugar
        run: cargo install --git https://github.com/sugar/sugar sugar-cli
      - name: prove
        run: sugar prove .
"#;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn init_creates_expected_files() {
        let dir = std::env::temp_dir().join(format!("sugar-cli-init-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();

        init_project(&dir, false, true).expect("init");
        assert!(dir.join("sugar.toml").exists());
        assert!(dir.join(".sugar").join("cache").exists());
        assert!(dir.join(".sugar").join("sample.invariant.rs").exists());
        assert!(dir
            .join(".github")
            .join("workflows")
            .join("sugar.yml")
            .exists());

        // Re-running without --force fails.
        let again = init_project(&dir, false, true);
        assert!(again.is_err());

        // With --force, succeeds.
        init_project(&dir, true, true).expect("force re-init");

        std::fs::remove_dir_all(&dir).ok();
    }
}
