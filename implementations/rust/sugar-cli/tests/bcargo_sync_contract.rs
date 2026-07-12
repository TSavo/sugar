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
    let rules = parse_sync_rules(&bcargo);
    let synced = |path: &str| {
        rules
            .iter()
            .any(|rule| rule.kind == SyncKind::Path && rule.rel_path == path)
    };

    assert!(
        synced(".sugar/ir-compilers"),
        "bcargo must sync .sugar/ir-compilers so remote verifier runs can resolve manifest-backed ProofIR compiler dialects"
    );
    assert!(
        synced("docs/perf"),
        "bcargo must sync docs/perf so remote perf-gate tests see the documented RSS and dhat commands"
    );
    assert!(
        synced(".github"),
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
sync_paths=(
  Cargo.toml
)
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
sync_paths=(
  Cargo.toml
  implementations/rust
)
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
fn untracked_run_products_do_not_enter_the_census() {
    let temp = tempfile::tempdir().expect("tempdir");
    write_fixture_tree(temp.path());
    write_bcargo(
        temp.path(),
        r#"
sync_paths=(
  Cargo.toml
)
"#,
    );
    let runs = temp
        .path()
        .join("examples/planted-showcase/good/.sugar/runs");
    fs::create_dir_all(&runs).expect("mkdir runs");
    fs::write(runs.join("blake3-512_planted.proof"), "run product").expect("write run product");

    // Track everything EXCEPT the runs dir, then census. The tracked
    // tests/fixtures class must still be reported missing; the untracked
    // run products must not impersonate a fixture.
    let git = |args: &[&str]| {
        let status = std::process::Command::new("git")
            .arg("-C")
            .arg(temp.path())
            .args(args)
            .status()
            .expect("run git");
        assert!(status.success(), "git {args:?} failed");
    };
    git(&["init", "-q"]);
    git(&["add", "implementations", "bin"]);

    let report = bcargo_sync_contract_report(temp.path()).expect("build tracked report");

    assert!(
        report
            .missing
            .iter()
            .any(|missing| missing.artifact.rel_path.ends_with("tests/fixtures")),
        "tracked tests/fixtures artifact class should still be missing:\n{}",
        report.render_missing()
    );
    assert!(
        !report
            .artifacts
            .iter()
            .any(|artifact| artifact.rel_path.contains(".sugar/runs")),
        "untracked .sugar/runs run products must not enter the census:\n{}",
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
    /// An entry in bcargo's `sync_paths=( ... )` array: shipped by the single
    /// rsync, subject to the `--exclude` filters.
    Path,
    /// An `--include='/path/***'` filter rule: puts a fixture tree back in
    /// front of the generated-output excludes, so nothing under it is excluded.
    Include,
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
    let artifacts = collect_artifacts(root, tracked_paths(root).as_ref())?;
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
    let mut rules = Vec::new();
    let mut in_sync_paths = false;
    for line in bcargo.lines() {
        let code = line.split('#').next().unwrap_or("").trim();
        if code == "sync_paths=(" {
            in_sync_paths = true;
            continue;
        }
        if in_sync_paths {
            if code == ")" {
                in_sync_paths = false;
                continue;
            }
            if let Some(rel_path) = code.split_whitespace().next() {
                rules.push(SyncRule {
                    kind: SyncKind::Path,
                    rel_path: rel_path.trim_matches('"').to_string(),
                });
            }
            continue;
        }
        if let Some((_, pattern)) = code.split_once("--include='") {
            if let Some((pattern, _)) = pattern.split_once('\'') {
                let rel_path = pattern
                    .trim_start_matches('/')
                    .trim_end_matches('*')
                    .trim_end_matches('/')
                    .to_string();
                rules.push(SyncRule {
                    kind: SyncKind::Include,
                    rel_path,
                });
            }
        }
    }
    rules
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

/// Every path `git ls-files` reports for `root`, or None when `root` is not a
/// git checkout (the planted tempdir fixtures). The census only wants the
/// COMMITTED corpus: `.sugar/runs` is also where sugar writes generated run
/// products, so a filesystem-only walk cannot tell a trust-root fixture from
/// the residue of the last local example run, and the test's verdict would
/// depend on working-tree dirt instead of on the repo.
fn tracked_paths(root: &Path) -> Option<BTreeSet<String>> {
    if let Some(tracked) = git_tracked_paths(root) {
        return Some(tracked);
    }
    // Remote bcargo checkouts have no .git; bcargo ships the tracked-file
    // list alongside the sync so the census can still ask VCS-tracked-ness.
    manifest_tracked_paths(root)
}

fn git_tracked_paths(root: &Path) -> Option<BTreeSet<String>> {
    let output = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(["ls-files", "-z"])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    Some(parse_nul_separated_paths(&output.stdout))
}

fn manifest_tracked_paths(root: &Path) -> Option<BTreeSet<String>> {
    let bytes = fs::read(root.join(".bcargo-tracked-manifest")).ok()?;
    Some(parse_nul_separated_paths(&bytes))
}

fn parse_nul_separated_paths(bytes: &[u8]) -> BTreeSet<String> {
    String::from_utf8_lossy(bytes)
        .split('\0')
        .filter(|path| !path.is_empty())
        .map(str::to_string)
        .collect()
}

fn is_tracked_file(tracked: Option<&BTreeSet<String>>, rel_path: &str) -> bool {
    tracked.is_none_or(|tracked| tracked.contains(rel_path))
}

fn is_tracked_dir(tracked: Option<&BTreeSet<String>>, rel_path: &str) -> bool {
    tracked.is_none_or(|tracked| {
        let prefix = format!("{rel_path}/");
        tracked
            .range(prefix.clone()..)
            .next()
            .is_some_and(|path| path.starts_with(&prefix))
    })
}

fn collect_artifacts(root: &Path, tracked: Option<&BTreeSet<String>>) -> io::Result<Vec<Artifact>> {
    let mut artifacts = BTreeSet::new();
    collect_artifacts_from(root, root, tracked, &mut artifacts)?;
    Ok(artifacts.into_iter().collect())
}

fn collect_artifacts_from(
    root: &Path,
    dir: &Path,
    tracked: Option<&BTreeSet<String>>,
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
                if is_tracked_dir(tracked, &rel_path) {
                    artifacts.insert(Artifact {
                        rel_path,
                        class: "fixture-dir",
                    });
                }
                continue;
            }
            if is_sugar_runs_dir(&path) {
                if is_tracked_dir(tracked, &rel_path) {
                    artifacts.insert(Artifact {
                        rel_path,
                        class: "sugar-runs-proof-fixtures",
                    });
                }
                continue;
            }
            collect_artifacts_from(root, &path, tracked, artifacts)?;
        } else {
            let rel_path = rel_path(root, &path);
            if !is_tracked_file(tracked, &rel_path) {
                continue;
            }
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
        SyncKind::Path => {
            path_is_under(&artifact.rel_path, &rule.rel_path)
                && !is_excluded_by_sync_dir(&artifact.rel_path, &rule.rel_path, excludes)
        }
        SyncKind::Include => path_is_under(&artifact.rel_path, &rule.rel_path),
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
        return format!(
            "add --include='/{}/***' ahead of the excludes in bin/bcargo",
            artifact.rel_path
        );
    }
    if let Some(root) = broad_sync_root(&artifact.rel_path) {
        return format!("add {root} to sync_paths in bin/bcargo");
    }
    format!("add {} to sync_paths in bin/bcargo", artifact.rel_path)
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
