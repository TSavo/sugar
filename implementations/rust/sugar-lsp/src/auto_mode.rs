// SPDX-License-Identifier: MIT OR Apache-2.0
//
// auto_mode.rs — #4007 Auto mode (LSP client only).
//
// On unresolved / cold-pool vendor imports, the *client* reaches for source
// that is already on disk (pip install → site-packages / stdlib), lifts it
// through the frontend membrane (mint_project_scratch_proof), seals the
// resulting proof into an in-process cache keyed by source CID, and feeds
// those mementos into the base pool before solve.
//
// Solve never opens site-packages. The CLI does not get this loop.
//
// Opt-out: SUGAR_LSP_AUTO_LIFT=0
// Opt-in (default when unset): enabled for in-process path.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Mutex;

use sugar_verifier::load_all_proofs::{self, ProofBytes};
use sugar_verifier::types::MementoPool;
use sugar_verifier::Speaker;

/// Max .py files staged per vendor auto-lift (bounds first-hover cost).
const MAX_VENDOR_PY_FILES: usize = 40;
/// Max total bytes of staged .py content per vendor.
const MAX_VENDOR_PY_BYTES: usize = 1_500_000;

/// Process-wide memo: source content hash → staged proof bytes.
/// Second reference is free (DoD: pool hit keyed by source CID).
static AUTO_CACHE: Mutex<Option<HashMap<String, CachedAutoProof>>> = Mutex::new(None);

#[derive(Clone)]
#[allow(dead_code)]
struct CachedAutoProof {
    source_cid: String,
    proof_cid: String,
    bytes: Vec<u8>,
    module: String,
}

/// Whether auto-lift is enabled (default: on).
pub fn auto_lift_enabled() -> bool {
    match std::env::var("SUGAR_LSP_AUTO_LIFT") {
        Ok(v) => {
            let t = v.trim().to_ascii_lowercase();
            !(t == "0" || t == "false" || t == "off" || t == "no")
        }
        Err(_) => true,
    }
}

/// Top-level package names from import lines in `source`.
/// Skips relative imports (`.foo`) and empty.
pub fn extract_top_level_imports(source: &str) -> Vec<String> {
    let mut out = Vec::new();
    for line in source.lines() {
        let t = line.trim();
        if t.starts_with('#') || t.is_empty() {
            continue;
        }
        // import a, b.c  /  import a as x
        if let Some(rest) = t.strip_prefix("import ") {
            for part in rest.split(',') {
                let name = part
                    .trim()
                    .split_whitespace()
                    .next()
                    .unwrap_or("")
                    .split('.')
                    .next()
                    .unwrap_or("");
                push_mod(&mut out, name);
            }
            continue;
        }
        // from a.b import c
        if let Some(rest) = t.strip_prefix("from ") {
            let name = rest
                .trim()
                .split_whitespace()
                .next()
                .unwrap_or("");
            if name.starts_with('.') {
                continue;
            }
            let top = name.split('.').next().unwrap_or("");
            push_mod(&mut out, top);
        }
    }
    out.sort();
    out.dedup();
    out
}

fn push_mod(out: &mut Vec<String>, name: &str) {
    if name.is_empty() || !name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        return;
    }
    // Skip common non-vendor noise
    if matches!(name, "typing" | "__future__" | "annotations") {
        return;
    }
    if !out.iter().any(|x| x == name) {
        out.push(name.to_string());
    }
}

/// Resolve `import module` → filesystem root to lift (package dir or .py file parent).
pub fn resolve_module_path(module: &str) -> Result<PathBuf, String> {
    let py = python_bin();
    // Single-line Python so -c is indentation-safe.
    let code = format!(
        "import importlib.util,os,sys;\
spec=importlib.util.find_spec({mod:?});\
sys.exit(2) if spec is None else None;\
paths=list(spec.submodule_search_locations or []);\
print(paths[0]) if paths else (\
  print(os.path.dirname(os.path.abspath(spec.origin))) if (spec.origin and spec.origin!='built-in') else sys.exit(3)\
)",
        mod = module
    );
    let out = Command::new(&py)
        .args(["-c", &code])
        .output()
        .map_err(|e| format!("spawn python for resolve {module}: {e}"))?;
    if !out.status.success() {
        return Err(format!(
            "resolve {module} failed (status {:?}): {}",
            out.status.code(),
            String::from_utf8_lossy(&out.stderr)
        ));
    }
    let path = String::from_utf8_lossy(&out.stdout).trim().to_string();
    if path.is_empty() {
        return Err(format!("resolve {module}: empty path"));
    }
    let p = PathBuf::from(&path);
    if !p.exists() {
        return Err(format!("resolve {module}: path missing {path}"));
    }
    Ok(p)
}

fn python_bin() -> PathBuf {
    if let Ok(py) = std::env::var("PYTHON") {
        if !py.is_empty() {
            return PathBuf::from(py);
        }
    }
    if let Ok(py) = std::env::var("ITSDANGEROUS_LOGO_VENV") {
        let cand = PathBuf::from(&py).join("bin/python");
        if cand.is_file() {
            return cand;
        }
    }
    PathBuf::from("python3")
}

fn repo_python_kit_src() -> Option<PathBuf> {
    // sugar-lsp crate is at implementations/rust/sugar-lsp
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let kit = manifest
        .join("../../python/sugar-lift-py-tests/src")
        .canonicalize()
        .ok()?;
    if kit.join("sugar_lift_py_tests/lift_rpc.py").is_file() {
        Some(kit)
    } else {
        None
    }
}

fn source_tree_cid(root: &Path) -> Result<String, String> {
    let mut files = collect_py_files(root)?;
    files.sort();
    let mut hasher_input = Vec::new();
    for f in &files {
        let rel = f.strip_prefix(root).unwrap_or(f);
        hasher_input.extend_from_slice(rel.to_string_lossy().as_bytes());
        hasher_input.push(0);
        let bytes = fs::read(f).map_err(|e| format!("read {}: {e}", f.display()))?;
        hasher_input.extend_from_slice(&(bytes.len() as u64).to_le_bytes());
        hasher_input.extend_from_slice(&bytes);
    }
    Ok(format!(
        "blake3-512:{}",
        sugar_canonicalizer::blake3_512_hex(&hasher_input)
    ))
}

fn collect_py_files(root: &Path) -> Result<Vec<PathBuf>, String> {
    let mut out = Vec::new();
    let mut total = 0usize;
    fn walk(
        dir: &Path,
        out: &mut Vec<PathBuf>,
        total: &mut usize,
        depth: usize,
    ) -> Result<(), String> {
        if depth > 5 || out.len() >= MAX_VENDOR_PY_FILES || *total >= MAX_VENDOR_PY_BYTES {
            return Ok(());
        }
        let rd = match fs::read_dir(dir) {
            Ok(r) => r,
            Err(_) => return Ok(()),
        };
        for ent in rd.flatten() {
            let p = ent.path();
            let name = ent.file_name().to_string_lossy().to_string();
            if name.starts_with('.')
                || name == "__pycache__"
                || name == "node_modules"
                || name == ".git"
            {
                continue;
            }
            if p.is_dir() {
                walk(&p, out, total, depth + 1)?;
            } else if name.ends_with(".py") {
                let meta = fs::metadata(&p).map_err(|e| e.to_string())?;
                let n = meta.len() as usize;
                if *total + n > MAX_VENDOR_PY_BYTES || out.len() >= MAX_VENDOR_PY_FILES {
                    break;
                }
                *total += n;
                out.push(p);
            }
        }
        Ok(())
    }
    // Prefer tests/ if present (richer stated contracts).
    let tests = root.join("tests");
    if tests.is_dir() {
        walk(&tests, &mut out, &mut total, 0)?;
    }
    if out.is_empty() {
        walk(root, &mut out, &mut total, 0)?;
    }
    Ok(out)
}

/// Stage a throwaway project that lifts `module_root` sources with the real
/// python kit (same shape as real_python_kit_prove fixtures).
fn stage_vendor_project(module: &str, module_root: &Path) -> Result<PathBuf, String> {
    let kit = repo_python_kit_src()
        .ok_or_else(|| "python kit source not found (sugar_lift_py_tests)".to_string())?;
    let py = python_bin();

    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    // Prefer exec-friendly base when /tmp is noexec — still OK because we
    // invoke lift via /bin/sh wrapper.
    let base = std::env::var("SUGAR_LSP_AUTO_TMP")
        .map(PathBuf::from)
        .unwrap_or_else(|_| std::env::temp_dir());
    let project = base.join(format!(
        "sugar-lsp-auto-{}-{}-{}",
        module,
        std::process::id(),
        stamp
    ));
    fs::create_dir_all(&project).map_err(|e| e.to_string())?;

    // Copy selected .py files under project/vendor_src/ preserving names.
    let files = collect_py_files(module_root)?;
    if files.is_empty() {
        return Err(format!("auto-lift {module}: no .py files under {}", module_root.display()));
    }
    let src_dst = project.join("vendor_src");
    fs::create_dir_all(&src_dst).map_err(|e| e.to_string())?;
    for f in &files {
        let name = f.file_name().unwrap_or_default();
        // Flatten into vendor_src with unique names if collision
        let mut dst = src_dst.join(name);
        if dst.exists() {
            let h = sugar_canonicalizer::blake3_512_hex(f.to_string_lossy().as_bytes());
            dst = src_dst.join(format!("{}_{}", &h[..12], name.to_string_lossy()));
        }
        fs::copy(f, &dst).map_err(|e| format!("copy {}: {e}", f.display()))?;
    }

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift/python")).map_err(|e| e.to_string())?;
    fs::write(
        sugar.join("config.toml"),
        r#"[[plugins]]
name = "python-lift"
kind = "lift"
surface = "python"

[solvers]
default = "z3"

[solvers.dispatch]
linear_arithmetic = "z3"
default = "z3"

[solvers.z3]
binary = "z3"
ir_compiler = "smt-lib-v2.6"
flags = ["-smt2", "-in"]
timeout_seconds = 10
"#,
    )
    .map_err(|e| e.to_string())?;

    let wrapper = sugar.join("lift/python/run-lift-rpc.sh");
    let body = format!(
        "#!/bin/sh\nexport PYTHONPATH={kit}${{PYTHONPATH:+:$PYTHONPATH}}\nexec /bin/sh -c 'exec {py} -m sugar_lift_py_tests.lift_rpc --rpc'\n",
        kit = shell_quote(&kit.display().to_string()),
        py = shell_quote(&py.display().to_string()),
    );
    // Use /bin/sh in manifest; script body still needs to be readable.
    fs::write(&wrapper, body).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&wrapper).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&wrapper, perms).ok();
    }

    // Manifest: invoke via /bin/sh for noexec safety
    fs::write(
        sugar.join("lift/python/manifest.toml"),
        format!(
            "name = \"python\"\ncommand = [\"/bin/sh\", \"{}\"]\nworking_dir = \".\"\n",
            wrapper.display()
        ),
    )
    .map_err(|e| e.to_string())?;

    Ok(project)
}

fn shell_quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\"'\"'"))
}

/// Lift one importable module if not cached. Returns vendor-stamped ProofBytes.
pub fn auto_lift_module(module: &str) -> Result<Option<ProofBytes>, String> {
    let module_root = resolve_module_path(module)?;
    let source_cid = source_tree_cid(&module_root)?;

    {
        let mut guard = AUTO_CACHE.lock().map_err(|e| e.to_string())?;
        if guard.is_none() {
            *guard = Some(HashMap::new());
        }
        if let Some(cache) = guard.as_ref() {
            if let Some(hit) = cache.get(&source_cid) {
                return ProofBytes::try_from_parts(
                    format!("auto-lift:{module}"),
                    hit.proof_cid.clone(),
                    hit.bytes.clone(),
                    Speaker::vendor(format!("auto-lift:{module}")),
                )
                .map(Some)
                .map_err(|e| e.to_string());
            }
        }
    }

    let project = stage_vendor_project(module, &module_root)?;
    let scratch = project.join(".sugar-auto-scratch");
    let _ = fs::remove_dir_all(&scratch);
    fs::create_dir_all(&scratch).map_err(|e| e.to_string())?;

    let mint = sugar_cli::cmd_mint::mint_project_scratch_proof(&project, &scratch, false);
    // Best-effort cleanup of staged tree (keep cache only).
    let mint_result = mint;
    let _ = fs::remove_dir_all(&project);

    match mint_result {
        Ok(Some(scratch_proof)) => {
            let proof = ProofBytes::try_from_parts(
                format!("auto-lift:{module}"),
                scratch_proof.cid.clone(),
                scratch_proof.bytes.clone(),
                Speaker::vendor(format!("auto-lift:{module}")),
            )
            .map_err(|e| e.to_string())?;

            let mut guard = AUTO_CACHE.lock().map_err(|e| e.to_string())?;
            if let Some(cache) = guard.as_mut() {
                cache.insert(
                    source_cid.clone(),
                    CachedAutoProof {
                        source_cid: source_cid.clone(),
                        proof_cid: scratch_proof.cid,
                        bytes: scratch_proof.bytes,
                        module: module.to_string(),
                    },
                );
            }
            Ok(Some(proof))
        }
        Ok(None) => {
            // Zero contracts / no plugin output — honest empty (DoD).
            Ok(None)
        }
        Err(e) => Err(format!("auto-lift mint {module}: {e}")),
    }
}

/// For each top-level import in `source`, try auto-lift. Merge successful
/// vendor proofs into `base_pool`. Returns log lines for the LSP client.
pub fn auto_lift_imports_into_pool(source: &str, base_pool: &mut MementoPool) -> Vec<String> {
    if !auto_lift_enabled() {
        return vec!["auto-lift disabled (SUGAR_LSP_AUTO_LIFT=0)".into()];
    }
    let mods = extract_top_level_imports(source);
    if mods.is_empty() {
        return Vec::new();
    }
    let mut logs = Vec::new();
    let mut batch: Vec<ProofBytes> = Vec::new();
    for m in mods {
        match auto_lift_module(&m) {
            Ok(Some(p)) => {
                logs.push(format!("auto-lift: {m} → vendor proof sealed (source-cid cache)"));
                batch.push(p);
            }
            Ok(None) => {
                logs.push(format!(
                    "auto-lift: {m} → zero contracts (honest empty)"
                ));
            }
            Err(e) => {
                logs.push(format!("auto-lift: {m} skipped: {e}"));
            }
        }
    }
    if !batch.is_empty() {
        load_all_proofs::load_proof_bytes_into_pool(&batch, base_pool);
        logs.push(format!(
            "auto-lift: merged {} vendor proof(s) into base pool",
            batch.len()
        ));
    }
    logs
}

/// Test/support: clear the process cache (isolation between tests).
#[allow(dead_code)]
pub fn clear_auto_cache_for_tests() {
    if let Ok(mut g) = AUTO_CACHE.lock() {
        *g = Some(HashMap::new());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_import_and_from() {
        let src = r#"
import hmac
import hashlib as H
from uuid import UUID
from .relative import x
# import comment
from typing import List
"#;
        let mods = extract_top_level_imports(src);
        assert!(mods.contains(&"hmac".into()));
        assert!(mods.contains(&"hashlib".into()));
        assert!(mods.contains(&"uuid".into()));
        assert!(!mods.iter().any(|m| m == "typing"));
        assert!(!mods.iter().any(|m| m.starts_with('.')));
    }

    #[test]
    fn resolve_hmac_stdlib() {
        let p = resolve_module_path("hmac").expect("hmac stdlib");
        assert!(p.exists(), "{p:?}");
    }
}
