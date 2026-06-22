use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("sugar-cli lives under implementations/rust/sugar-cli")
        .to_path_buf()
}

fn tracked_files(root: &Path) -> Vec<PathBuf> {
    let output = Command::new("git")
        .arg("-C")
        .arg(root)
        .arg("ls-files")
        .output()
        .expect("run git ls-files");
    if output.status.success() {
        return String::from_utf8(output.stdout)
            .expect("git ls-files output is utf-8")
            .lines()
            .map(|line| root.join(line))
            .collect();
    }

    let mut files = Vec::new();
    collect_files(root, &mut files);
    files
}

fn collect_files(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
            continue;
        };
        if matches!(
            name,
            ".git"
                | ".jj"
                | ".sugar"
                | ".worktrees"
                | "node_modules"
                | "target"
                | "provekit-warnings"
                | "provekit-worktrees"
        ) {
            continue;
        }
        if path.is_dir() {
            collect_files(&path, out);
        } else {
            out.push(path);
        }
    }
}

#[test]
fn tracked_sources_use_windows_safe_proof_globs() {
    let root = repo_root();
    let legacy_glob = concat!("blake3-512:", "*.proof");
    let test_file = Path::new(file!());

    let mut offenders = Vec::new();
    for path in tracked_files(&root) {
        let rel = path.strip_prefix(&root).unwrap_or(&path);
        if rel == test_file {
            continue;
        }
        let Ok(text) = fs::read_to_string(&path) else {
            continue;
        };
        for (idx, line) in text.lines().enumerate() {
            if line.contains(legacy_glob) {
                offenders.push(format!("{}:{}: {line}", rel.display(), idx + 1));
            }
        }
    }

    assert!(
        offenders.is_empty(),
        "proof files are written with sugar_proof_envelope::proof_filename(); \
         tracked sources must use the Windows-safe blake3-512_<hex>.proof path form:\n{}",
        offenders.join("\n")
    );
}
