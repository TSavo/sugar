use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::process::Command;

const WALK_SKIP_DIRS: &[&str] = &[
    ".git",
    ".jj",
    ".tmp",
    "target",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
];

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("sugar-cli lives under implementations/rust/sugar-cli")
        .to_path_buf()
}

#[test]
fn bcargo_syncs_ir_compiler_manifests() {
    let root = repo_root();
    let bcargo = fs::read_to_string(root.join("bin").join("bcargo")).expect("read bin/bcargo");

    assert!(
        bcargo.contains("sync_dir .sugar/ir-compilers"),
        "bcargo must sync .sugar/ir-compilers so remote verifier runs can resolve manifest-backed ProofIR compiler dialects"
    );
    assert!(
        bcargo.contains("sync_dir docs/perf"),
        "bcargo must sync docs/perf so remote perf-gate tests see the documented RSS and dhat commands"
    );
    assert!(
        bcargo.contains("sync_dir .github"),
        "bcargo must sync .github so remote CI-wiring tests see workflow sources"
    );
}

#[test]
fn bcargo_sync_contract_covers_live_test_artifact_classes() {
    let root = repo_root();
    let report = bcargo_sync_contract_report(&root).expect("build bcargo sync contract");

    assert!(
        report.missing.is_empty(),
        "bcargo sync contract missing {} artifact class(es):\n{}",
        report.missing.len(),
        report.render_missing()
    );
    eprintln!(
        "bcargo-sync-contract: artifacts={} missing={} classes={}",
        report.artifacts.len(),
        report.missing.len(),
        report.render_class_counts()
    );
    assert!(
        report
            .artifacts
            .iter()
            .any(|artifact| artifact.rel_path.ends_with(".sugar/runs")),
        "artifact census must include checked-in .sugar/runs proof fixtures"
    );
    assert!(
        report
            .artifacts
            .iter()
            .any(|artifact| artifact.rel_path.ends_with("tests/fixtures")),
        "artifact census must include tests/fixtures directories"
    );
    assert!(
        report
            .artifacts
            .iter()
            .any(|artifact| artifact.rel_path == "conformance/typed_pipeline/interfaces.toml"),
        "artifact census must include manifest TOMLs used by conformance tests"
    );
    assert!(
        !report
            .artifacts
            .iter()
            .any(|artifact| artifact.rel_path.contains(".llbc")),
        ".llbc-era fixture directories are dead and must not re-enter the sync floor"
    );
}

#[test]
fn planted_unsynced_artifact_class_is_reported() {
    let temp = tempfile::tempdir().expect("tempdir");
    write_fixture_tree(temp.path());
    write_bcargo(
        temp.path(),
        r#"
sync_file Cargo.toml
"#,
    );

    let report = bcargo_sync_contract_report(temp.path()).expect("build planted report");

    assert!(
        report
            .missing
            .iter()
            .any(|missing| missing.artifact.rel_path.ends_with("tests/fixtures")),
        "planted tests/fixtures artifact class should be missing:\n{}",
        report.render_missing()
    );
}

#[test]
fn planted_synced_artifact_class_is_legal() {
    let temp = tempfile::tempdir().expect("tempdir");
    write_fixture_tree(temp.path());
    write_bcargo(
        temp.path(),
        r#"
sync_file Cargo.toml
sync_dir implementations/rust
"#,
    );

    let report = bcargo_sync_contract_report(temp.path()).expect("build planted report");

    assert!(
        report.missing.is_empty(),
        "legal fixture reference should be covered:\n{}",
        report.render_missing()
    );
}

#[test]
fn bcargo_remote_root_cleanup_contract() {
    let root = repo_root();
    let status = Command::new("bash")
        .arg(root.join("tests").join("bcargo_remote_root_cleanup.sh"))
        .arg(&root)
        .status()
        .expect("run bcargo remote root cleanup contract");

    assert!(
        status.success(),
        "bcargo remote root cleanup contract failed with {status}"
    );
}

fn write_fixture_tree(root: &Path) {
    let tests = root.join("implementations/rust/planted/tests");
    let fixtures = tests.join("fixtures");
    fs::create_dir_all(&fixtures).expect("mkdir fixtures");
    fs::write(
        tests.join("planted.rs"),
        r#"#[test]
fn reads_fixture() {
    let _ = include_str!("fixtures/source.rpc_source");
}
"#,
    )
    .expect("write planted test");
    fs::write(fixtures.join("source.rpc_source"), "fixture").expect("write fixture");
}

fn write_bcargo(root: &Path, body: &str) {
    let bin = root.join("bin");
    fs::create_dir_all(&bin).expect("mkdir bin");
    fs::write(bin.join("bcargo"), body).expect("write bcargo");
}

#[derive(Debug)]
struct SyncContractReport {
    artifacts: Vec<Artifact>,
    missing: Vec<MissingArtifact>,
}

impl SyncContractReport {
    fn render_missing(&self) -> String {
        self.missing
            .iter()
            .map(|missing| {
                format!(
                    "crime=bcargo-sync-missing-artifact-class owner=bin/bcargo \
                     shape={} path={} replacement={}",
                    missing.artifact.class, missing.artifact.rel_path, missing.replacement
                )
            })
            .collect::<Vec<_>>()
            .join("\n")
    }

    fn render_class_counts(&self) -> String {
        let mut counts = BTreeMap::new();
        for artifact in &self.artifacts {
            *counts.entry(artifact.class).or_insert(0usize) += 1;
        }
        counts
            .into_iter()
            .map(|(class, count)| format!("{class}={count}"))
            .collect::<Vec<_>>()
            .join(",")
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct Artifact {
    rel_path: String,
    class: &'static str,
}

#[derive(Debug)]
struct MissingArtifact {
    artifact: Artifact,
    replacement: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum SyncKind {
    Dir,
    FixtureDir,
    File,
}

#[derive(Debug)]
struct SyncRule {
    kind: SyncKind,
    rel_path: String,
}

fn bcargo_sync_contract_report(root: &Path) -> io::Result<SyncContractReport> {
    let bcargo = fs::read_to_string(root.join("bin").join("bcargo"))?;
    let sync_rules = parse_sync_rules(&bcargo);
    let sync_excludes = parse_sync_excludes(&bcargo);
    let artifacts = collect_artifacts(root)?;
    let missing = artifacts
        .iter()
        .filter(|artifact| !is_covered(artifact, &sync_rules, &sync_excludes))
        .map(|artifact| MissingArtifact {
            artifact: artifact.clone(),
            replacement: replacement_for(artifact),
        })
        .collect();

    Ok(SyncContractReport { artifacts, missing })
}

fn parse_sync_rules(bcargo: &str) -> Vec<SyncRule> {
    bcargo
        .lines()
        .filter_map(|line| {
            let code = line.split('#').next().unwrap_or("").trim();
            let (kind, rest) = if let Some(rest) = code.strip_prefix("sync_dir ") {
                (SyncKind::Dir, rest)
            } else if let Some(rest) = code.strip_prefix("sync_fixture_dir ") {
                (SyncKind::FixtureDir, rest)
            } else if let Some(rest) = code.strip_prefix("sync_file ") {
                (SyncKind::File, rest)
            } else {
                return None;
            };
            let rel_path = rest
                .split_whitespace()
                .next()?
                .trim_matches('"')
                .to_string();
            Some(SyncRule { kind, rel_path })
        })
        .collect()
}

fn parse_sync_excludes(bcargo: &str) -> Vec<String> {
    bcargo
        .lines()
        .filter_map(|line| {
            let trimmed = line.trim();
            let (_, pattern) = trimmed.split_once("--exclude='")?;
            let (pattern, _) = pattern.split_once('\'')?;
            Some(pattern.trim_end_matches('/').to_string())
        })
        .collect()
}

fn collect_artifacts(root: &Path) -> io::Result<Vec<Artifact>> {
    let mut artifacts = BTreeSet::new();
    collect_artifacts_from(root, root, &mut artifacts)?;
    Ok(artifacts.into_iter().collect())
}

fn collect_artifacts_from(
    root: &Path,
    dir: &Path,
    artifacts: &mut BTreeSet<Artifact>,
) -> io::Result<()> {
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        let file_name = entry.file_name();
        let file_name = file_name.to_string_lossy();
        if entry.file_type()?.is_dir() {
            if WALK_SKIP_DIRS.contains(&file_name.as_ref()) {
                continue;
            }
            let rel_path = rel_path(root, &path);
            if is_fixture_dir_name(&file_name) {
                artifacts.insert(Artifact {
                    rel_path,
                    class: "fixture-dir",
                });
                continue;
            }
            if is_sugar_runs_dir(&path) {
                artifacts.insert(Artifact {
                    rel_path,
                    class: "sugar-runs-proof-fixtures",
                });
                continue;
            }
            collect_artifacts_from(root, &path, artifacts)?;
        } else {
            let rel_path = rel_path(root, &path);
            if let Some(class) = artifact_file_class(&path) {
                artifacts.insert(Artifact { rel_path, class });
            }
        }
    }
    Ok(())
}

fn is_fixture_dir_name(name: &str) -> bool {
    matches!(name, "fixtures" | "fixture" | "goldens" | "golden")
}

fn is_sugar_runs_dir(path: &Path) -> bool {
    path.file_name().and_then(|name| name.to_str()) == Some("runs")
        && path.parent().and_then(|parent| parent.file_name())
            == Some(std::ffi::OsStr::new(".sugar"))
}

fn artifact_file_class(path: &Path) -> Option<&'static str> {
    let file_name = path.file_name()?.to_string_lossy();
    if file_name.ends_with(".proof") {
        return Some("proof-bundle");
    }
    if file_name.ends_with(".proofir-cbor") {
        return Some("binary-proofir-fixture");
    }
    if file_name.contains("golden") {
        return Some("golden-file");
    }
    if matches!(file_name.as_ref(), "fixtures.toml" | "interfaces.toml") {
        return Some("manifest-toml");
    }
    None
}

fn is_covered(artifact: &Artifact, rules: &[SyncRule], excludes: &[String]) -> bool {
    rules
        .iter()
        .any(|rule| rule_covers(rule, artifact, excludes))
}

fn rule_covers(rule: &SyncRule, artifact: &Artifact, excludes: &[String]) -> bool {
    match rule.kind {
        SyncKind::File => artifact.rel_path == rule.rel_path,
        SyncKind::Dir => {
            path_is_under(&artifact.rel_path, &rule.rel_path)
                && !is_excluded_by_sync_dir(&artifact.rel_path, &rule.rel_path, excludes)
        }
        SyncKind::FixtureDir => path_is_under(&artifact.rel_path, &rule.rel_path),
    }
}

fn path_is_under(path: &str, root: &str) -> bool {
    path == root
        || path
            .strip_prefix(root)
            .is_some_and(|rest| rest.starts_with('/'))
}

fn is_excluded_by_sync_dir(path: &str, sync_root: &str, excludes: &[String]) -> bool {
    let rest = path
        .strip_prefix(sync_root)
        .unwrap_or(path)
        .trim_matches('/');
    excludes
        .iter()
        .any(|exclude| path_contains_component_sequence(rest, exclude))
}

fn path_contains_component_sequence(path: &str, needle: &str) -> bool {
    let path = format!("/{}/", path.trim_matches('/'));
    let needle = format!("/{}/", needle.trim_matches('/'));
    path.contains(&needle)
}

fn replacement_for(artifact: &Artifact) -> String {
    if artifact.rel_path.contains("/.sugar/runs") {
        return format!("add sync_fixture_dir {}", artifact.rel_path);
    }
    if let Some(root) = broad_sync_root(&artifact.rel_path) {
        return format!("add sync_dir {root}");
    }
    format!("add sync_file {}", artifact.rel_path)
}

fn broad_sync_root(path: &str) -> Option<String> {
    for root in [
        "implementations/rust",
        "implementations/python",
        "implementations/java",
        "implementations/go",
        "examples",
        "protocol",
        "conformance",
        "tests",
        "tools",
        "scripts",
        "bootstrap",
        "docs/perf",
        "docs/self-application",
        ".github",
    ] {
        if path_is_under(path, root) {
            return Some(root.to_string());
        }
    }
    None
}

fn rel_path(root: &Path, path: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .components()
        .map(|component| component.as_os_str().to_string_lossy())
        .collect::<Vec<_>>()
        .join("/")
}
