use std::process::Command;

fn main() {
    for path in git_paths_to_watch() {
        println!("cargo:rerun-if-changed={path}");
    }
    println!("cargo:rerun-if-env-changed=SUGAR_BUILD_STAMP");
    println!("cargo:rerun-if-env-changed=SUGAR_BUILD_GIT_HEAD");
    let git_head = std::env::var("SUGAR_BUILD_GIT_HEAD")
        .ok()
        .or_else(|| git_output(&["rev-parse", "HEAD"]))
        .unwrap_or_else(|| "unknown".to_string());
    let build_stamp = std::env::var("SUGAR_BUILD_STAMP")
        .ok()
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| git_head.clone());
    println!("cargo:rustc-env=SUGAR_BUILD_GIT_HEAD={git_head}");
    println!("cargo:rustc-env=SUGAR_BUILD_STAMP={build_stamp}");
}

fn git_paths_to_watch() -> Vec<String> {
    let mut paths = Vec::new();
    if let Some(path) = git_output(&["rev-parse", "--git-path", "HEAD"]) {
        paths.push(path);
    }
    if let Some(symbolic) = git_output(&["symbolic-ref", "-q", "HEAD"]) {
        if let Some(path) = git_output(&["rev-parse", "--git-path", &symbolic]) {
            paths.push(path);
        }
    }
    if let Some(path) = git_output(&["rev-parse", "--git-path", "packed-refs"]) {
        paths.push(path);
    }
    paths
}

fn git_output(args: &[&str]) -> Option<String> {
    let output = Command::new("git").args(args).output().ok()?;
    if !output.status.success() {
        return None;
    }
    let text = String::from_utf8(output.stdout).ok()?;
    let trimmed = text.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}
