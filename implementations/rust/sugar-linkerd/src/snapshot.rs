// SPDX-License-Identifier: MIT OR Apache-2.0
//
// snapshot.rs: warm-start snapshot persistence (R14).
//
// On shutdown the daemon writes its state to
//   ${XDG_CACHE_HOME}/sugar/linkerd/<projectCid>/snapshot.bin
// with a `snapshot.bin.checksum` file containing the blake3-512 of the
// snapshot bytes.
//
// On start, if the snapshot exists, we verify the checksum before
// loading.  On checksum mismatch we start cold (don't fail).

use std::path::Path;

use sugar_canonicalizer::blake3_512_of;

use crate::state::ProjectState;

/// Save `state` to `path`. Creates parent directories as needed.
/// Also writes `<path>.checksum` with the blake3-512 hex of the snapshot.
pub fn save(path: &Path, state: &ProjectState) -> Result<(), String> {
    let bytes = state.to_snapshot_bytes();
    let checksum = blake3_512_of(&bytes);

    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("create snapshot dir: {e}"))?;
    }

    std::fs::write(path, &bytes).map_err(|e| format!("write snapshot: {e}"))?;

    let checksum_path = checksum_path_for(path);
    std::fs::write(&checksum_path, checksum.as_bytes())
        .map_err(|e| format!("write checksum: {e}"))?;

    Ok(())
}

/// Load state from `path`. Returns:
/// - `Ok(Some(state))` if the snapshot exists and checksum verifies.
/// - `Ok(None)` if the snapshot does not exist.
/// - `Err(reason)` if the snapshot exists but the checksum fails or
///   the JSON is invalid.  Caller SHOULD start cold on error.
pub fn load(path: &Path) -> Result<Option<ProjectState>, String> {
    if !path.exists() {
        return Ok(None);
    }

    let bytes = std::fs::read(path).map_err(|e| format!("read snapshot: {e}"))?;

    // Verify checksum.
    let checksum_path = checksum_path_for(path);
    if checksum_path.exists() {
        let stored = std::fs::read_to_string(&checksum_path)
            .map_err(|e| format!("read checksum file: {e}"))?;
        let expected = blake3_512_of(&bytes);
        if stored.trim() != expected {
            return Err(format!(
                "snapshot checksum mismatch (stored={}, computed={}); starting cold",
                stored.trim(),
                expected
            ));
        }
    } else {
        // No checksum file: treat as corrupt.
        return Err("snapshot exists but checksum file is missing; starting cold".into());
    }

    let state = ProjectState::from_snapshot_bytes(&bytes)?;
    Ok(Some(state))
}

fn checksum_path_for(snapshot_path: &Path) -> std::path::PathBuf {
    let mut p = snapshot_path.to_path_buf();
    let name = p
        .file_name()
        .map(|n| format!("{}.checksum", n.to_string_lossy()))
        .unwrap_or_else(|| "snapshot.bin.checksum".to_string());
    p.set_file_name(name);
    p
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_save_load_roundtrip() {
        let dir = std::env::temp_dir().join(format!(
            "sugar-linkerd-snap-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.subsec_nanos())
                .unwrap_or(0)
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("snapshot.bin");

        // Empty state roundtrip.
        let state = ProjectState::new(16);
        save(&path, &state).expect("save");
        let loaded = load(&path).expect("load").expect("some");
        assert!(loaded.project_status().is_none());

        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn test_load_missing_returns_none() {
        let path = std::env::temp_dir().join("sugar-linkerd-nonexistent-snap.bin");
        let result = load(&path).expect("load");
        assert!(result.is_none());
    }

    #[test]
    fn test_checksum_mismatch_returns_err() {
        let dir = std::env::temp_dir().join(format!(
            "sugar-linkerd-snap-corrupt-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.subsec_nanos())
                .unwrap_or(0)
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("snapshot.bin");

        // Write valid snapshot.
        let state = ProjectState::new(16);
        save(&path, &state).expect("save");

        // Corrupt the snapshot bytes.
        std::fs::write(&path, b"corrupt bytes").unwrap();

        let result = load(&path);
        assert!(result.is_err(), "corrupted snapshot should return Err");

        std::fs::remove_dir_all(&dir).ok();
    }
}
