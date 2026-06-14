// SPDX-License-Identifier: Apache-2.0
//
// resolve_cache.rs: content-addressed per-file callee-resolution cache.
//
// Specs #1705 (content-addressed callee-resolution cache) and #1706 (per-file
// resolution cache with dependency-set granularity), serving #1707.
//
// THE INSIGHT (Sugar-native, "if you can't content-address it, it doesn't
// belong"): resolving a method-call position to a crate is DETERMINISTIC given
// the resolver's full INPUT, so it is content-addressable. A warm rust-analyzer
// alone still pays the workspace index on every COLD daemon start; a
// content-addressed cache persisted to disk skips rust-analyzer ENTIRELY when
// that input is unchanged, even from a fresh daemon process.
//
// KEY (#1706): `(blake3(file_content), baseResolutionContextCid)`, where the
// base context covers Cargo.lock + rust-toolchain only. Source sensitivity lives
// in each cached position's dependency evidence.
//
// HONESTY ABOUT THE INPUT (this is the subtle part, supra omnia rectum). A
// position's resolution is NOT a pure function of (this file's bytes + the
// dependency lock). Rust type inference flows ACROSS files: `let c =
// open_conn(); c.query()` resolves `query` against the type `open_conn` returns,
// which is declared in ANOTHER file. If that other file changes (e.g. the
// connection switches sqlite -> postgres, both registry crates), THIS file's
// bytes and Cargo.lock are unchanged, yet the correct resolution changed. Keying
// on this file alone would then serve a STALE hit and emit a wrong bridge: the
// exact cross-library confusion Sugar exists to prevent. So a per-file key is
// UNSOUND on its own.
//
// The fallback remains the #1705 WHOLE in-workspace source tree context
// (blake3 of Cargo.lock, rust-toolchain[.toml], plus the sorted hashes of every
// workspace `.rs` file). #1706 moves that source sensitivity out of the global
// key and into each cached position: when RA gives us readable definition
// files, the position records those file CIDs; when it cannot, the position
// records the coarse workspace context. A wrong/incomplete dependency set only
// ever causes a MISS (re-ask the warm RA), never a wrong HIT.
//
// VALUE: the COMPLETE resolution map for that file from one QUIESCENT pass:
// `{ "<line>:<col>": "<crate>" }`. A position that was resolved appears with its
// crate; a position that the oracle DETERMINISTICALLY refused (null definition,
// unmappable path, ambiguous) is recorded as a refusal so a cache hit reproduces
// the refusal WITHOUT re-asking RA. A file is only cached when EVERY queried
// position settled (resolved or deterministic-refuse) from a quiescent session;
// a not-ready/churn pass is never cached (a partial entry would wrongly suppress
// RA on a later run). This is what keeps the refuse-floor intact across caching.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use sugar_canonicalizer::blake3_512_of;

/// One position's resolution outcome inside a file's cache entry.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum PosOutcome {
    /// Resolved to a defining crate, with the best-effort receiver-type stem
    /// (None when the crate was definite but the type could not be
    /// disambiguated). The stem is cached alongside the crate so a cache hit
    /// reproduces the disambiguated panic-partial selection with no RA spawn.
    Crate {
        krate: String,
        type_stem: Option<String>,
        /// The receiver/param mutability effect from the method SIGNATURE
        /// ("Mutating" / "RefClean" / "Unknown"), cached alongside the crate so a
        /// cache hit reproduces the oracle's verdict with no RA spawn. Without
        /// this, a warm-cache re-run degraded every hit to "unknown" -> the
        /// source-audit reclassified NOTHING -> a hollow `ORACLE_MOVED 0` that
        /// looked like a real zero (a fake zero). The effect is a function of the
        /// same signature source the resolution depends on, so it is invalidated
        /// by the SAME deps -- caching it is sound. `#[serde(default)]` keeps old
        /// cache files (no effect field) loadable, defaulting to "" -> Unknown.
        #[serde(default)]
        effect: String,
    },
    /// Deterministically refused (null definition / unmappable / ambiguous).
    /// Recorded so a cache hit reproduces the refusal with no RA spawn.
    Refused,
}

/// One cached position plus the dependency evidence that makes the hit valid.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CachedPosition {
    pub outcome: PosOutcome,
    pub deps: ResolutionDeps,
}

impl CachedPosition {
    pub fn resolved(
        krate: &str,
        type_stem: Option<&str>,
        effect: &str,
        deps: ResolutionDeps,
    ) -> Self {
        Self {
            outcome: PosOutcome::Crate {
                krate: krate.to_string(),
                type_stem: type_stem.map(str::to_string),
                effect: effect.to_string(),
            },
            deps,
        }
    }

    pub fn refused(deps: ResolutionDeps) -> Self {
        Self {
            outcome: PosOutcome::Refused,
            deps,
        }
    }
}

/// The dependency evidence for one cached position.
///
/// `files` is the precise dependency set for #1706: each path key must still
/// read to the recorded content CID. `workspace_context_cid` is the conservative
/// #1705 fallback: when we cannot fully name the files a resolution depends on,
/// any workspace-source edit invalidates the position instead of serving a
/// stale answer.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Default)]
pub struct ResolutionDeps {
    #[serde(default)]
    pub files: BTreeMap<String, String>,
    #[serde(default)]
    pub workspace_context_cid: Option<String>,
}

impl ResolutionDeps {
    pub fn workspace(workspace_root: &Path) -> Self {
        Self {
            files: BTreeMap::new(),
            workspace_context_cid: Some(resolution_context_cid(workspace_root)),
        }
    }

    pub fn from_files<'a, I, P>(workspace_root: &Path, paths: I) -> Option<Self>
    where
        I: IntoIterator<Item = P>,
        P: AsRef<Path> + 'a,
    {
        let mut files = BTreeMap::new();
        for path in paths {
            let path = path.as_ref();
            let bytes = std::fs::read(path).ok()?;
            files.insert(
                dependency_path_key(workspace_root, path),
                blake3_512_of(&bytes),
            );
        }
        if files.is_empty() {
            None
        } else {
            Some(Self {
                files,
                workspace_context_cid: None,
            })
        }
    }

    pub fn validate(&self, workspace_root: &Path) -> bool {
        if self.files.is_empty() && self.workspace_context_cid.is_none() {
            return false;
        }
        if let Some(expected) = &self.workspace_context_cid {
            if resolution_context_cid(workspace_root) != *expected {
                return false;
            }
        }
        for (key, expected) in &self.files {
            let Some(path) = dependency_path_from_key(workspace_root, key) else {
                return false;
            };
            let Ok(bytes) = std::fs::read(path) else {
                return false;
            };
            if blake3_512_of(&bytes) != *expected {
                return false;
            }
        }
        true
    }
}

/// The cached resolution for one file at one (content, dep-set) state.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct FileResolution {
    /// "<line>:<col>" -> outcome. Complete for the positions queried in the
    /// quiescent pass that produced it.
    pub positions: BTreeMap<String, CachedPosition>,
}

/// The persisted cache: content-address key -> file resolution.
///
/// The key is `"<file_content_blake3>|<base_context_cid>"`. Two different files
/// with identical content AND base context legitimately share an entry:
/// position-level dependency validation decides which stored positions still
/// hit under the current workspace bytes.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ResolveCache {
    entries: BTreeMap<String, FileResolution>,
}

impl ResolveCache {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    #[allow(dead_code)]
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// Compute the content-address key for a file's bytes under a base context.
    pub fn key(file_content: &[u8], dep_set_cid: &str) -> String {
        let content_cid = blake3_512_of(file_content);
        format!("{content_cid}|{dep_set_cid}")
    }

    /// Look up a file's cached positions by content + base context. Callers must
    /// validate each `CachedPosition`'s deps before treating that position as a
    /// hit.
    pub fn get(&self, file_content: &[u8], dep_set_cid: &str) -> Option<&FileResolution> {
        self.entries.get(&Self::key(file_content, dep_set_cid))
    }

    /// Store a file's complete resolution. Tests use this for full-entry setup;
    /// production refreshes should prefer `merge_insert`.
    #[allow(dead_code)]
    pub fn insert(&mut self, file_content: &[u8], dep_set_cid: &str, resolution: FileResolution) {
        self.entries
            .insert(Self::key(file_content, dep_set_cid), resolution);
    }

    /// Merge a partial refresh into an existing file entry. #1706 refreshes
    /// only invalid positions, so rewriting the whole file entry would discard
    /// still-valid positions and force avoidable RA queries later.
    pub fn merge_insert(
        &mut self,
        file_content: &[u8],
        dep_set_cid: &str,
        resolution: FileResolution,
    ) {
        let entry = self
            .entries
            .entry(Self::key(file_content, dep_set_cid))
            .or_default();
        entry.positions.extend(resolution.positions);
    }

    /// Serialise to bytes for the sidecar.
    pub fn to_bytes(&self) -> Vec<u8> {
        serde_json::to_vec(self).unwrap_or_default()
    }

    /// Restore from sidecar bytes; an unreadable cache starts empty (it is a
    /// cache, never a source of truth: a miss just re-asks RA).
    pub fn from_bytes(bytes: &[u8]) -> Self {
        serde_json::from_slice(bytes).unwrap_or_default()
    }
}

/// The coarse cache generation key for #1706. It covers resolver-global inputs
/// shared by every position but deliberately does NOT include workspace source
/// bytes; source sensitivity now lives in each `CachedPosition`'s deps.
pub fn base_resolution_context_cid(workspace_root: &Path) -> String {
    let lock_bytes = read_nearest_ancestor_file(workspace_root, "Cargo.lock")
        .unwrap_or_else(|| b"no-cargo-lock".to_vec());
    let toolchain_bytes = read_nearest_ancestor_file(workspace_root, "rust-toolchain.toml")
        .or_else(|| read_nearest_ancestor_file(workspace_root, "rust-toolchain"))
        .unwrap_or_else(|| b"no-rust-toolchain".to_vec());

    let mut acc = String::new();
    acc.push_str("cargo-lock\0");
    acc.push_str(&blake3_512_of(&lock_bytes));
    acc.push('\n');
    acc.push_str("rust-toolchain\0");
    acc.push_str(&blake3_512_of(&toolchain_bytes));
    blake3_512_of(acc.as_bytes())
}

/// Compute the resolution-context CID: the SECOND key component, capturing every
/// input a position's resolution depends on BEYOND its own file's bytes.
///
/// It folds three things, in this order:
///   1. The dependency lock (`Cargo.lock`): a re-export or version bump can move
///      a callee to a different crate, so a dep change must invalidate.
///   2. The Rust toolchain pin (`rust-toolchain` or `rust-toolchain.toml`):
///      sysroot and language semantics can change with the selected toolchain.
///   3. A hash of the WHOLE in-workspace `.rs` source tree: rust type inference
///      flows across files (a receiver's type can be declared in another file),
///      so an edit to ANY workspace file can change THIS file's correct
///      resolution. Folding the tree makes any in-workspace edit invalidate
///      every entry. This is deliberately CONSERVATIVE (over-invalidates) to be
///      SOUND: a hit can never reflect stale cross-file type flow. A wrong key
///      only ever causes a MISS (re-ask the warm RA), never a wrong HIT.
///
/// Files are visited in sorted path order so the fold is deterministic. The walk
/// is bounded to `.rs` files and skips `target/` and dotted dirs (build output /
/// VCS are not resolver inputs). Paths are folded relative to `workspace_root`;
/// identical bytes in another worktree must produce the same context CID. Missing
/// Cargo/toolchain files contribute sentinels.
pub fn resolution_context_cid(workspace_root: &Path) -> String {
    use walkdir::WalkDir;

    // Search root + ancestors: a cargo workspace keeps these files at the
    // workspace root above member crates.
    let lock_bytes = read_nearest_ancestor_file(workspace_root, "Cargo.lock")
        .unwrap_or_else(|| b"no-cargo-lock".to_vec());
    let toolchain_bytes = read_nearest_ancestor_file(workspace_root, "rust-toolchain.toml")
        .or_else(|| read_nearest_ancestor_file(workspace_root, "rust-toolchain"))
        .unwrap_or_else(|| b"no-rust-toolchain".to_vec());

    // Sorted per-file content hashes of the workspace `.rs` tree.
    let mut file_hashes: Vec<(String, String)> = Vec::new();
    for entry in WalkDir::new(workspace_root)
        .into_iter()
        .filter_entry(|e| {
            // Skip target/ and dotted dirs (build output, VCS): not resolver
            // inputs, and target/ can be huge.
            let name = e.file_name().to_string_lossy();
            !(e.file_type().is_dir() && (name == "target" || name.starts_with('.')))
        })
        .filter_map(Result::ok)
    {
        if entry.file_type().is_file()
            && entry.path().extension().and_then(|s| s.to_str()) == Some("rs")
        {
            if let Ok(bytes) = std::fs::read(entry.path()) {
                file_hashes.push((
                    relative_path_key(workspace_root, entry.path()),
                    blake3_512_of(&bytes),
                ));
            }
        }
    }
    file_hashes.sort();

    // Fold lock + sorted (path, content-hash) pairs into one CID.
    let mut acc = String::new();
    acc.push_str("cargo-lock\0");
    acc.push_str(&blake3_512_of(&lock_bytes));
    acc.push('\n');
    acc.push_str("rust-toolchain\0");
    acc.push_str(&blake3_512_of(&toolchain_bytes));
    for (path, hash) in &file_hashes {
        acc.push('\n');
        acc.push_str(path);
        acc.push('\0');
        acc.push_str(hash);
    }
    blake3_512_of(acc.as_bytes())
}

fn read_nearest_ancestor_file(start: &Path, name: &str) -> Option<Vec<u8>> {
    let mut dir = Some(start);
    while let Some(d) = dir {
        let path = d.join(name);
        if let Ok(bytes) = std::fs::read(&path) {
            return Some(bytes);
        }
        dir = d.parent();
    }
    None
}

fn relative_path_key(root: &Path, path: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/")
}

fn dependency_path_key(workspace_root: &Path, path: &Path) -> String {
    let root =
        std::fs::canonicalize(workspace_root).unwrap_or_else(|_| workspace_root.to_path_buf());
    let normalized = std::fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf());
    if let Ok(rel) = normalized.strip_prefix(&root) {
        format!("workspace:{}", rel.to_string_lossy().replace('\\', "/"))
    } else {
        format!("file:{}", normalized.to_string_lossy().replace('\\', "/"))
    }
}

fn dependency_path_from_key(workspace_root: &Path, key: &str) -> Option<PathBuf> {
    if let Some(rel) = key.strip_prefix("workspace:") {
        Some(workspace_root.join(rel))
    } else {
        key.strip_prefix("file:").map(PathBuf::from)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::time::{SystemTime, UNIX_EPOCH};

    fn unique_temp_dir(label: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        std::env::temp_dir().join(format!("sugar-{label}-{nanos}-{}", std::process::id()))
    }

    fn write_minimal_workspace(root: &Path) {
        fs::create_dir_all(root.join("src")).expect("mkdir src");
        fs::write(root.join("Cargo.lock"), "version = 4\n").expect("write Cargo.lock");
        fs::write(
            root.join("rust-toolchain.toml"),
            "[toolchain]\nchannel = \"stable\"\n",
        )
        .expect("write rust-toolchain.toml");
        fs::write(
            root.join("src").join("lib.rs"),
            "pub fn answer() -> u32 { 42 }\n",
        )
        .expect("write lib.rs");
    }

    #[test]
    fn key_changes_with_content() {
        let k1 = ResolveCache::key(b"fn a() {}", "deps");
        let k2 = ResolveCache::key(b"fn b() {}", "deps");
        assert_ne!(k1, k2);
    }

    #[test]
    fn key_changes_with_dep_set() {
        let k1 = ResolveCache::key(b"same", "deps-1");
        let k2 = ResolveCache::key(b"same", "deps-2");
        assert_ne!(k1, k2);
    }

    #[test]
    fn hit_is_authoritative_for_whole_file() {
        let mut cache = ResolveCache::new();
        let mut res = FileResolution::default();
        res.positions.insert(
            "3:7".into(),
            CachedPosition::resolved(
                "std",
                Some("option"),
                "RefClean",
                ResolutionDeps::workspace(&unique_temp_dir("unused")),
            ),
        );
        res.positions.insert(
            "4:1".into(),
            CachedPosition::refused(ResolutionDeps::workspace(&unique_temp_dir("unused"))),
        );
        cache.insert(b"content", "deps", res);

        let hit = cache.get(b"content", "deps").unwrap();
        assert_eq!(
            hit.positions.get("3:7").map(|pos| &pos.outcome),
            Some(&PosOutcome::Crate {
                krate: "std".into(),
                type_stem: Some("option".into()),
                effect: "RefClean".into(),
            })
        );
        assert_eq!(
            hit.positions.get("4:1").map(|pos| &pos.outcome),
            Some(&PosOutcome::Refused)
        );
        // A different content is a miss.
        assert!(cache.get(b"changed", "deps").is_none());
    }

    #[test]
    fn roundtrips_through_bytes() {
        let mut cache = ResolveCache::new();
        let mut res = FileResolution::default();
        res.positions.insert(
            "1:0".into(),
            CachedPosition::resolved(
                "serde_json",
                None,
                "RefClean",
                ResolutionDeps::workspace(&unique_temp_dir("unused")),
            ),
        );
        cache.insert(b"x", "d", res);
        let bytes = cache.to_bytes();
        let restored = ResolveCache::from_bytes(&bytes);
        assert_eq!(restored.len(), 1);
        assert_eq!(
            restored
                .get(b"x", "d")
                .unwrap()
                .positions
                .get("1:0")
                .map(|pos| &pos.outcome),
            Some(&PosOutcome::Crate {
                krate: "serde_json".into(),
                type_stem: None,
                // the effect must survive the bytes roundtrip, not reset to unknown.
                effect: "RefClean".into(),
            })
        );
    }

    #[test]
    fn base_resolution_context_ignores_unrelated_source_edits() {
        let root = unique_temp_dir("ra-cache-base-context");
        write_minimal_workspace(&root);

        let before = base_resolution_context_cid(&root);
        fs::write(
            root.join("src").join("other.rs"),
            "pub fn other() -> u32 { 7 }\n",
        )
        .expect("write unrelated source");
        let after = base_resolution_context_cid(&root);

        let _ = fs::remove_dir_all(&root);

        assert_eq!(
            before, after,
            "the cache generation key should cover Cargo/toolchain inputs, not every source file"
        );
    }

    #[test]
    fn precise_file_dependencies_validate_independently() {
        let root = unique_temp_dir("ra-cache-position-deps");
        write_minimal_workspace(&root);
        let dep_a = root.join("src").join("dep_a.rs");
        let dep_b = root.join("src").join("dep_b.rs");
        fs::write(&dep_a, "pub fn a() {}\n").expect("write dep_a");
        fs::write(&dep_b, "pub fn b() {}\n").expect("write dep_b");

        let deps_a = ResolutionDeps::from_files(&root, [&dep_a]).expect("deps a");
        let deps_b = ResolutionDeps::from_files(&root, [&dep_b]).expect("deps b");

        assert!(deps_a.validate(&root), "dep_a starts valid");
        assert!(deps_b.validate(&root), "dep_b starts valid");

        fs::write(&dep_b, "pub fn b_changed() {}\n").expect("rewrite dep_b");

        assert!(
            deps_a.validate(&root),
            "editing dep_b must not invalidate a position that only depends on dep_a"
        );
        assert!(
            !deps_b.validate(&root),
            "editing dep_b must invalidate positions that named dep_b"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn merging_partial_refresh_preserves_other_positions() {
        let root = unique_temp_dir("ra-cache-merge");
        write_minimal_workspace(&root);
        let dep_a = root.join("src").join("dep_a.rs");
        let dep_b = root.join("src").join("dep_b.rs");
        fs::write(&dep_a, "pub fn a() {}\n").expect("write dep_a");
        fs::write(&dep_b, "pub fn b() {}\n").expect("write dep_b");

        let base = base_resolution_context_cid(&root);
        let mut cache = ResolveCache::new();
        let mut initial = FileResolution::default();
        initial.positions.insert(
            "1:1".into(),
            CachedPosition::resolved(
                "std",
                Some("option"),
                "RefClean",
                ResolutionDeps::from_files(&root, [&dep_a]).expect("dep a"),
            ),
        );
        initial.positions.insert(
            "2:1".into(),
            CachedPosition::refused(ResolutionDeps::from_files(&root, [&dep_b]).expect("dep b")),
        );
        cache.insert(b"caller", &base, initial);

        let mut refresh = FileResolution::default();
        refresh.positions.insert(
            "2:1".into(),
            CachedPosition::resolved(
                "std",
                Some("result"),
                "Mutating",
                ResolutionDeps::from_files(&root, [&dep_b]).expect("dep b refresh"),
            ),
        );
        cache.merge_insert(b"caller", &base, refresh);

        let hit = cache.get(b"caller", &base).expect("merged cache hit");
        assert_eq!(hit.positions.len(), 2);
        assert_eq!(
            hit.positions.get("1:1").map(|pos| &pos.outcome),
            Some(&PosOutcome::Crate {
                krate: "std".into(),
                type_stem: Some("option".into()),
                effect: "RefClean".into(),
            }),
            "partial refresh should not discard an unrelated cached position"
        );
        assert_eq!(
            hit.positions.get("2:1").map(|pos| &pos.outcome),
            Some(&PosOutcome::Crate {
                krate: "std".into(),
                type_stem: Some("result".into()),
                effect: "Mutating".into(),
            }),
            "refreshed position should be updated in place"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn resolution_context_is_content_addressed_not_worktree_path_addressed() {
        let root_a = unique_temp_dir("ra-cache-a");
        let root_b = unique_temp_dir("ra-cache-b");
        write_minimal_workspace(&root_a);
        write_minimal_workspace(&root_b);

        let cid_a = resolution_context_cid(&root_a);
        let cid_b = resolution_context_cid(&root_b);

        let _ = fs::remove_dir_all(&root_a);
        let _ = fs::remove_dir_all(&root_b);

        assert_eq!(
            cid_a, cid_b,
            "identical workspace bytes must produce the same resolution context CID across worktrees"
        );
    }

    #[test]
    fn resolution_context_changes_when_toolchain_changes() {
        let root = unique_temp_dir("ra-cache-toolchain");
        write_minimal_workspace(&root);

        let before = resolution_context_cid(&root);
        fs::write(
            root.join("rust-toolchain.toml"),
            "[toolchain]\nchannel = \"nightly\"\n",
        )
        .expect("rewrite rust-toolchain.toml");
        let after = resolution_context_cid(&root);

        let _ = fs::remove_dir_all(&root);

        assert_ne!(
            before, after,
            "rust-toolchain changes can affect resolution and must invalidate the cache generation"
        );
    }
}
