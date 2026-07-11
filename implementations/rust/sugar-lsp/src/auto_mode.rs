// SPDX-License-Identifier: MIT OR Apache-2.0
//
// auto_mode.rs — #4007 Auto mode (LSP client only).
//
// Pure form (this revision):
//   for each top-level import that is a *cold pool entry*:
//     1. already sealed for this source_cid?     → skip (process + disk)
//     2. vendor-shipped *.proof under package? → load as vendor, seal
//     3. disk auto cache under project?        → load, seal
//     4. Download sources (Maven-class, #4106) → sdist @ installed version
//     5. mint from richest root (downloaded tests/ preferred), seal, persist
//
// Solve never opens site-packages. CLI does not get this loop.
//
// Opt-out: SUGAR_LSP_AUTO_LIFT=0
// Download sources opt-out: SUGAR_LSP_DOWNLOAD_SOURCES=0
// Default: both on for in-process path.

use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Mutex;

use sugar_verifier::load_all_proofs::{self, ProofBytes};
use sugar_verifier::types::MementoPool;
use sugar_verifier::Speaker;

const MAX_VENDOR_PY_FILES: usize = 40;
const MAX_VENDOR_PY_BYTES: usize = 1_500_000;
const MAX_SHIPPED_PROOFS: usize = 8;

/// Process-wide memo: source_cid → sealed proof.
static AUTO_CACHE: Mutex<Option<HashMap<String, CachedAutoProof>>> = Mutex::new(None);

/// Modules already sealed this process (by top-level name) for quick skip.
static SEALED_MODULES: Mutex<Option<HashSet<String>>> = Mutex::new(None);

#[derive(Clone)]
#[allow(dead_code)]
struct CachedAutoProof {
    source_cid: String,
    proof_cid: String,
    bytes: Vec<u8>,
    module: String,
    origin: SealOrigin,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum SealOrigin {
    ProcessCache,
    DiskCache,
    VendorShipped,
    Minted,
    /// Minted from downloaded sdist/repo tree (#4106), not bare site-packages.
    DownloadedSources,
}

pub fn auto_lift_enabled() -> bool {
    match std::env::var("SUGAR_LSP_AUTO_LIFT") {
        Ok(v) => {
            let t = v.trim().to_ascii_lowercase();
            !(t == "0" || t == "false" || t == "off" || t == "no")
        }
        Err(_) => true,
    }
}

/// Maven-class companion: fetch sdist/sources for claim-rich lift (#4106/#4107).
/// Default on when auto-lift is on. Opt-out: SUGAR_LSP_DOWNLOAD_SOURCES=0.
pub fn download_sources_enabled() -> bool {
    if !auto_lift_enabled() {
        return false;
    }
    match std::env::var("SUGAR_LSP_DOWNLOAD_SOURCES") {
        Ok(v) => {
            let t = v.trim().to_ascii_lowercase();
            !(t == "0" || t == "false" || t == "off" || t == "no")
        }
        Err(_) => true,
    }
}

fn sources_cache_dir() -> PathBuf {
    if let Ok(p) = std::env::var("SUGAR_SOURCES_CACHE") {
        if !p.is_empty() {
            return PathBuf::from(p);
        }
    }
    if let Ok(home) = std::env::var("HOME") {
        return PathBuf::from(home).join(".cache/sugar/sources");
    }
    std::env::temp_dir().join("sugar-sources-cache")
}

fn download_sources_script() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("scripts/download_package_sources.py")
}

/// Ensure sources for `module` are local (cache or fetch sdist). Returns root path + log line.
pub fn ensure_downloaded_sources(module: &str) -> Result<(PathBuf, String), String> {
    if !download_sources_enabled() {
        return Err("download sources disabled (SUGAR_LSP_DOWNLOAD_SOURCES=0)".into());
    }
    let script = download_sources_script();
    if !script.is_file() {
        return Err(format!(
            "download_package_sources.py missing at {}",
            script.display()
        ));
    }
    let cache = sources_cache_dir();
    fs::create_dir_all(&cache).map_err(|e| e.to_string())?;
    let py = python_bin();
    let out = Command::new(&py)
        .args([
            script.to_str().unwrap_or(""),
            module,
            cache.to_str().unwrap_or(""),
        ])
        .output()
        .map_err(|e| format!("spawn download_package_sources: {e}"))?;
    let stdout = String::from_utf8_lossy(&out.stdout).trim().to_string();
    let stderr = String::from_utf8_lossy(&out.stderr).trim().to_string();
    let v: serde_json::Value = serde_json::from_str(&stdout).map_err(|e| {
        format!(
            "download_package_sources bad JSON: {e}; stdout={stdout:?} stderr={stderr:?}"
        )
    })?;
    if v.get("ok").and_then(|x| x.as_bool()) != Some(true) {
        let err = v
            .get("error")
            .and_then(|x| x.as_str())
            .unwrap_or("unknown download failure");
        return Err(err.to_string());
    }
    let root = v
        .get("root")
        .and_then(|x| x.as_str())
        .ok_or_else(|| "download ok but missing root".to_string())?;
    let via = v
        .get("via")
        .and_then(|x| x.as_str())
        .unwrap_or("download");
    let name = v
        .get("name")
        .and_then(|x| x.as_str())
        .unwrap_or(module);
    let version = v
        .get("version")
        .and_then(|x| x.as_str())
        .unwrap_or("?");
    let source_url = v
        .get("source_url")
        .and_then(|x| x.as_str())
        .unwrap_or("");
    let log = format!(
        "download-sources: {name}@{version} via={via} root={root} url={source_url}"
    );
    let path = PathBuf::from(root);
    if !path.is_dir() {
        return Err(format!("download root missing: {}", path.display()));
    }
    Ok((path, log))
}


pub fn extract_top_level_imports(source: &str) -> Vec<String> {
    let mut out = Vec::new();
    for line in source.lines() {
        let t = line.trim();
        if t.starts_with('#') || t.is_empty() {
            continue;
        }
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
        if let Some(rest) = t.strip_prefix("from ") {
            let name = rest.trim().split_whitespace().next().unwrap_or("");
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
    if matches!(name, "typing" | "__future__" | "annotations") {
        return;
    }
    if !out.iter().any(|x| x == name) {
        out.push(name.to_string());
    }
}

pub fn resolve_module_path(module: &str) -> Result<PathBuf, String> {
    let py = python_bin();
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

/// Stable filesystem token for source_cid (no path separators).
fn source_cid_token(source_cid: &str) -> String {
    let hex = source_cid
        .strip_prefix("blake3-512:")
        .unwrap_or(source_cid);
    // Keep it filename-safe and bounded.
    hex.chars()
        .filter(|c| c.is_ascii_hexdigit())
        .take(64)
        .collect()
}

fn auto_cache_dir(project_root: &Path) -> PathBuf {
    project_root.join(".sugar").join("imports").join("auto")
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
    let tests = root.join("tests");
    if tests.is_dir() {
        walk(&tests, &mut out, &mut total, 0)?;
    }
    if out.is_empty() {
        walk(root, &mut out, &mut total, 0)?;
    }
    Ok(out)
}

/// Find vendor-shipped `.proof` files under a package tree (and common sugar dirs).
pub fn find_shipped_proofs(module_root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let mut total_bytes = 0u64;
    fn walk(dir: &Path, out: &mut Vec<PathBuf>, total_bytes: &mut u64, depth: usize) {
        if depth > 4 || out.len() >= MAX_SHIPPED_PROOFS {
            return;
        }
        let rd = match fs::read_dir(dir) {
            Ok(r) => r,
            Err(_) => return,
        };
        for ent in rd.flatten() {
            let p = ent.path();
            let name = ent.file_name().to_string_lossy().to_string();
            if name.starts_with('.') && name != ".sugar" {
                // still enter .sugar
            }
            if name == "__pycache__" || name == "node_modules" || name == ".git" {
                continue;
            }
            if p.is_dir() {
                walk(&p, out, total_bytes, depth + 1);
            } else if name.ends_with(".proof") {
                if let Ok(meta) = fs::metadata(&p) {
                    *total_bytes += meta.len();
                    if *total_bytes > 32 * 1024 * 1024 {
                        return;
                    }
                }
                out.push(p);
                if out.len() >= MAX_SHIPPED_PROOFS {
                    return;
                }
            }
        }
    }
    // Prefer package-local sugar layouts first.
    for rel in [".sugar/imports", ".sugar", "sugar"] {
        let d = module_root.join(rel);
        if d.is_dir() {
            walk(&d, &mut out, &mut total_bytes, 0);
        }
    }
    if out.is_empty() {
        walk(module_root, &mut out, &mut total_bytes, 0);
    }
    out
}

fn ensure_cache() -> Result<(), String> {
    let mut g = AUTO_CACHE.lock().map_err(|e| e.to_string())?;
    if g.is_none() {
        *g = Some(HashMap::new());
    }
    let mut s = SEALED_MODULES.lock().map_err(|e| e.to_string())?;
    if s.is_none() {
        *s = Some(HashSet::new());
    }
    Ok(())
}

fn module_is_sealed(module: &str) -> bool {
    SEALED_MODULES
        .lock()
        .ok()
        .and_then(|g| g.as_ref().map(|s| s.contains(module)))
        .unwrap_or(false)
}

fn mark_module_sealed(module: &str) {
    if let Ok(mut g) = SEALED_MODULES.lock() {
        if g.is_none() {
            *g = Some(HashSet::new());
        }
        if let Some(s) = g.as_mut() {
            s.insert(module.to_string());
        }
    }
}

fn cache_get(source_cid: &str) -> Option<CachedAutoProof> {
    AUTO_CACHE
        .lock()
        .ok()
        .and_then(|g| g.as_ref().and_then(|m| m.get(source_cid).cloned()))
}

fn cache_put(entry: CachedAutoProof) {
    if let Ok(mut g) = AUTO_CACHE.lock() {
        if g.is_none() {
            *g = Some(HashMap::new());
        }
        if let Some(m) = g.as_mut() {
            mark_module_sealed(&entry.module);
            m.insert(entry.source_cid.clone(), entry);
        }
    }
}

/// Load durable auto proofs for this project into the process cache (once per call is fine).
pub fn warm_disk_auto_cache(project_root: &Path) -> Vec<String> {
    let mut logs = Vec::new();
    let dir = auto_cache_dir(project_root);
    if !dir.is_dir() {
        return logs;
    }
    let _ = ensure_cache();
    let rd = match fs::read_dir(&dir) {
        Ok(r) => r,
        Err(_) => return logs,
    };
    for ent in rd.flatten() {
        let p = ent.path();
        let name = ent.file_name().to_string_lossy().to_string();
        if !name.ends_with(".proof") {
            continue;
        }
        let stem = name.trim_end_matches(".proof");
        let meta_path = dir.join(format!("{stem}.meta"));
        let meta = fs::read_to_string(&meta_path).unwrap_or_default();
        let mut module = String::new();
        let mut source_cid = format!("blake3-512:{stem}");
        for line in meta.lines() {
            if let Some(v) = line.strip_prefix("module=") {
                module = v.trim().to_string();
            }
            if let Some(v) = line.strip_prefix("source_cid=") {
                source_cid = v.trim().to_string();
            }
        }
        if module.is_empty() {
            module = format!("unknown-{stem}");
        }
        if cache_get(&source_cid).is_some() {
            mark_module_sealed(&module);
            continue;
        }
        let bytes = match fs::read(&p) {
            Ok(b) => b,
            Err(_) => continue,
        };
        let proof_cid = format!(
            "blake3-512:{}",
            sugar_canonicalizer::blake3_512_hex(&bytes)
        );
        cache_put(CachedAutoProof {
            source_cid: source_cid.clone(),
            proof_cid,
            bytes,
            module: module.clone(),
            origin: SealOrigin::DiskCache,
        });
        logs.push(format!(
            "auto-lift: warmed disk cache for {module} ({source_cid})"
        ));
    }
    logs
}

fn persist_disk_cache(
    project_root: &Path,
    source_cid: &str,
    module: &str,
    proof_cid: &str,
    bytes: &[u8],
) -> Result<(), String> {
    let dir = auto_cache_dir(project_root);
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let token = source_cid_token(source_cid);
    if token.is_empty() {
        return Err("empty source_cid token".into());
    }
    let proof_path = dir.join(format!("{token}.proof"));
    let meta_path = dir.join(format!("{token}.meta"));
    fs::write(&proof_path, bytes).map_err(|e| e.to_string())?;
    fs::write(
        &meta_path,
        format!("module={module}\nsource_cid={source_cid}\nproof_cid={proof_cid}\n"),
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}

fn load_shipped_as_proof_bytes(module: &str, paths: &[PathBuf]) -> Result<Option<ProofBytes>, String> {
    if paths.is_empty() {
        return Ok(None);
    }
    // Concatenate is wrong; load first proof that parses, or merge via pool then
    // re-export is heavy. Prefer first readable shipped proof as the seal unit.
    for p in paths {
        let bytes = match fs::read(p) {
            Ok(b) if !b.is_empty() => b,
            _ => continue,
        };
        let proof_cid = format!(
            "blake3-512:{}",
            sugar_canonicalizer::blake3_512_hex(&bytes)
        );
        match ProofBytes::try_from_parts(
            format!("shipped:{module}"),
            proof_cid,
            bytes,
            Speaker::vendor(format!("shipped:{module}")),
        ) {
            Ok(pb) => return Ok(Some(pb)),
            Err(_) => continue,
        }
    }
    Ok(None)
}

fn stage_vendor_project(module: &str, module_root: &Path) -> Result<PathBuf, String> {
    let kit = repo_python_kit_src()
        .ok_or_else(|| "python kit source not found (sugar_lift_py_tests)".to_string())?;
    let py = python_bin();

    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
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

    let files = collect_py_files(module_root)?;
    if files.is_empty() {
        return Err(format!(
            "auto-lift {module}: no .py files under {}",
            module_root.display()
        ));
    }
    let src_dst = project.join("vendor_src");
    fs::create_dir_all(&src_dst).map_err(|e| e.to_string())?;
    for f in &files {
        let name = f.file_name().unwrap_or_default();
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
        "#!/bin/sh\nexport PYTHONPATH={kit}${{PYTHONPATH:+:$PYTHONPATH}}\nexec {py} -m sugar_lift_py_tests.lift_rpc --rpc\n",
        kit = shell_quote(&kit.display().to_string()),
        py = shell_quote(&py.display().to_string()),
    );
    fs::write(&wrapper, body).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&wrapper).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&wrapper, perms).ok();
    }

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

fn mint_module(module: &str, module_root: &Path) -> Result<Option<(String, Vec<u8>)>, String> {
    let project = stage_vendor_project(module, module_root)?;
    let scratch = project.join(".sugar-auto-scratch");
    let _ = fs::remove_dir_all(&scratch);
    fs::create_dir_all(&scratch).map_err(|e| e.to_string())?;
    let mint = sugar_cli::cmd_mint::mint_project_scratch_proof(&project, &scratch, false);
    let _ = fs::remove_dir_all(&project);
    match mint {
        Ok(Some(s)) => Ok(Some((s.cid, s.bytes))),
        Ok(None) => Ok(None),
        Err(e) => Err(format!("auto-lift mint {module}: {e}")),
    }
}

/// Seal one cold module into the process cache (and optionally disk).
/// Order: process cache → shipped .proof → disk auto cache → mint.
fn seal_cold_module(
    project_root: &Path,
    module: &str,
) -> Result<Option<(ProofBytes, SealOrigin)>, String> {
    ensure_cache()?;
    // Prefer claim-rich downloaded sources (sdist/tests) over bare site-packages.
    let mut download_log: Option<String> = None;
    let mut used_download = false;
    let module_root = match ensure_downloaded_sources(module) {
        Ok((root, log)) => {
            download_log = Some(log);
            used_download = true;
            root
        }
        Err(_e) => resolve_module_path(module)?,
    };
    let source_cid = source_tree_cid(&module_root)?;

    // 1) Process cache by source_cid
    if let Some(hit) = cache_get(&source_cid) {
        mark_module_sealed(module);
        let pb = ProofBytes::try_from_parts(
            format!("auto-lift:{module}"),
            hit.proof_cid,
            hit.bytes,
            Speaker::vendor(format!("auto-lift:{module}")),
        )
        .map_err(|e| e.to_string())?;
        return Ok(Some((pb, SealOrigin::ProcessCache)));
    }

    // 2) Vendor-shipped .proof under package
    let shipped = find_shipped_proofs(&module_root);
    if let Some(pb) = load_shipped_as_proof_bytes(module, &shipped)? {
        let bytes = pb.bytes.clone();
        let proof_cid = pb.expected_cid.to_string();
        cache_put(CachedAutoProof {
            source_cid: source_cid.clone(),
            proof_cid: proof_cid.clone(),
            bytes: bytes.clone(),
            module: module.to_string(),
            origin: SealOrigin::VendorShipped,
        });
        let _ = persist_disk_cache(project_root, &source_cid, module, &proof_cid, &bytes);
        return Ok(Some((pb, SealOrigin::VendorShipped)));
    }

    // 3) Disk auto cache for this source_cid
    let token = source_cid_token(&source_cid);
    let disk_path = auto_cache_dir(project_root).join(format!("{token}.proof"));
    if disk_path.is_file() {
        if let Ok(bytes) = fs::read(&disk_path) {
            if !bytes.is_empty() {
                let proof_cid = format!(
                    "blake3-512:{}",
                    sugar_canonicalizer::blake3_512_hex(&bytes)
                );
                cache_put(CachedAutoProof {
                    source_cid: source_cid.clone(),
                    proof_cid: proof_cid.clone(),
                    bytes: bytes.clone(),
                    module: module.to_string(),
                    origin: SealOrigin::DiskCache,
                });
                let pb = ProofBytes::try_from_parts(
                    format!("auto-lift:{module}"),
                    proof_cid,
                    bytes,
                    Speaker::vendor(format!("auto-lift:{module}")),
                )
                .map_err(|e| e.to_string())?;
                return Ok(Some((pb, SealOrigin::DiskCache)));
            }
        }
    }

    // 4) Mint from source (downloaded tree preferred when available)
    let _ = download_log; // retained for callers via outer logs if needed later
    match mint_module(module, &module_root)? {
        Some((proof_cid, bytes)) => {
            let origin = if used_download {
                SealOrigin::DownloadedSources
            } else {
                SealOrigin::Minted
            };
            cache_put(CachedAutoProof {
                source_cid: source_cid.clone(),
                proof_cid: proof_cid.clone(),
                bytes: bytes.clone(),
                module: module.to_string(),
                origin,
            });
            let _ = persist_disk_cache(project_root, &source_cid, module, &proof_cid, &bytes);
            let pb = ProofBytes::try_from_parts(
                format!("auto-lift:{module}"),
                proof_cid,
                bytes,
                Speaker::vendor(format!("auto-lift:{module}")),
            )
            .map_err(|e| e.to_string())?;
            Ok(Some((pb, origin)))
        }
        None => {
            // Honest empty: still mark sealed so we don't re-mint forever.
            mark_module_sealed(module);
            Ok(None)
        }
    }
}

/// Whether the resident base pool already attributes any member to this module
/// (prior import / sealed vendor). Cold = not sealed and no speaker id hit.
fn pool_covers_module(pool: &MementoPool, module: &str) -> bool {
    if module_is_sealed(module) {
        return true;
    }
    // Speaker ids we stamp: auto-lift:{m}, shipped:{m}
    let needles = [
        format!("auto-lift:{module}"),
        format!("shipped:{module}"),
    ];
    // Walk member_speaker map if accessible
    for (_cid, speaker) in pool.member_speaker.iter() {
        let id = speaker.id.as_str();
        if needles.iter().any(|n| id == n || id.contains(module)) {
            // contain(module) is weak; prefer exact needles
            if needles.iter().any(|n| id == n) {
                return true;
            }
        }
    }
    false
}

/// Auto-seal only **cold** imports into `base_pool`.
/// Prefers vendor-shipped proofs, then disk cache, then mint.
pub fn auto_lift_cold_imports_into_pool(
    project_root: &Path,
    source: &str,
    base_pool: &mut MementoPool,
) -> Vec<String> {
    if !auto_lift_enabled() {
        return vec!["auto-lift disabled (SUGAR_LSP_AUTO_LIFT=0)".into()];
    }
    let mut logs = warm_disk_auto_cache(project_root);
    let mods = extract_top_level_imports(source);
    if mods.is_empty() {
        return logs;
    }

    let mut batch: Vec<ProofBytes> = Vec::new();
    for m in mods {
        if pool_covers_module(base_pool, &m) {
            logs.push(format!("auto-lift: {m} warm (pool/sealed) — skip"));
            continue;
        }
        // Maven-class sources fetch (cache hit is cheap); mint root prefers this tree.
        if download_sources_enabled() {
            match ensure_downloaded_sources(&m) {
                Ok((_root, log)) => logs.push(log),
                Err(e) => logs.push(format!("download-sources: {m} skip: {e}")),
            }
        }
        match seal_cold_module(project_root, &m) {
            Ok(Some((pb, origin))) => {
                logs.push(format!(
                    "auto-lift: {m} cold → sealed via {origin:?}"
                ));
                batch.push(pb);
            }
            Ok(None) => {
                logs.push(format!(
                    "auto-lift: {m} cold → zero contracts (honest empty)"
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

/// Back-compat name used by prove_engine.
pub fn auto_lift_imports_into_pool(
    project_root: &Path,
    source: &str,
    base_pool: &mut MementoPool,
) -> Vec<String> {
    auto_lift_cold_imports_into_pool(project_root, source, base_pool)
}

#[allow(dead_code)]
pub fn clear_auto_cache_for_tests() {
    if let Ok(mut g) = AUTO_CACHE.lock() {
        *g = Some(HashMap::new());
    }
    if let Ok(mut g) = SEALED_MODULES.lock() {
        *g = Some(HashSet::new());
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
from typing import List
"#;
        let mods = extract_top_level_imports(src);
        assert!(mods.contains(&"hmac".into()));
        assert!(mods.contains(&"hashlib".into()));
        assert!(mods.contains(&"uuid".into()));
        assert!(!mods.iter().any(|m| m == "typing"));
    }

    #[test]
    fn resolve_hmac_stdlib() {
        let p = resolve_module_path("hmac").expect("hmac stdlib");
        assert!(p.exists(), "{p:?}");
    }

    #[test]
    fn source_cid_token_is_filename_safe() {
        let t = source_cid_token("blake3-512:deadbeefcafebabe");
        assert_eq!(t, "deadbeefcafebabe");
        assert!(!t.contains('/'));
        assert!(!t.contains(':'));
    }

    #[test]
    fn find_shipped_proofs_discovers_file() {
        let dir = std::env::temp_dir().join(format!(
            "sugar-shipped-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(dir.join(".sugar/imports")).unwrap();
        fs::write(dir.join(".sugar/imports/vendor.proof"), b"not-a-real-proof").unwrap();
        let found = find_shipped_proofs(&dir);
        assert!(!found.is_empty(), "{found:?}");
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn download_sources_enabled_defaults_on() {
        // Do not assert global env; just ensure function is callable.
        let _ = download_sources_enabled();
        let _ = sources_cache_dir();
        assert!(download_sources_script().is_file(), "helper script must ship in crate");
    }
}
