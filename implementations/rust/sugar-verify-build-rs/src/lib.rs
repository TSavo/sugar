// sugar-verify crate: Cargo build.rs integration
//
// Add to Cargo.toml:
//   [build-dependencies]
//   sugar-verify = "0.1"
//
// In your build.rs:
//   fn main() {
//       sugar_verify::verify_project().expect("proof verification failed");
//   }
//
// The memento IS the verification. The .proof protocol IS the cache.
// The hash IS the boundary. This runs natively in your Rust toolchain.

use std::path::Path;
use std::process::Command;

pub fn verify_project() -> Result<(), Box<dyn std::error::Error>> {
    let manifest_dir =
        std::env::var("CARGO_MANIFEST_DIR").map_err(|_| "CARGO_MANIFEST_DIR not set")?;

    // Check if there are any .proof files in the project or dependencies
    let has_proofs = has_proof_files(&manifest_dir)?;
    if !has_proofs {
        return Ok(());
    }

    println!("cargo:rerun-if-changed=.sugar/config.toml");
    println!("cargo:rerun-if-changed=.sugar/");

    // Run sugar verify
    let output = Command::new("sugar")
        .arg("verify")
        .current_dir(&manifest_dir)
        .output()?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("sugar verify failed:\n{}", stderr).into());
    }

    Ok(())
}

fn has_proof_files(dir: &str) -> Result<bool, Box<dyn std::error::Error>> {
    let path = Path::new(dir);

    // Check project root
    if let Ok(entries) = std::fs::read_dir(path) {
        for entry in entries {
            if let Ok(entry) = entry {
                let name = entry.file_name();
                if name.to_string_lossy().ends_with(".proof") {
                    return Ok(true);
                }
            }
        }
    }

    // Check node_modules or vendor directories for dependency proofs
    for vendor_dir in &["node_modules", "vendor", "deps"] {
        let vendor_path = path.join(vendor_dir);
        if vendor_path.exists() {
            if let Ok(entries) = std::fs::read_dir(&vendor_path) {
                for entry in entries {
                    if let Ok(entry) = entry {
                        if entry.file_type().map(|t| t.is_dir()).unwrap_or(false) {
                            let pkg_path = entry.path();
                            if let Ok(files) = std::fs::read_dir(&pkg_path) {
                                for file in files {
                                    if let Ok(file) = file {
                                        let name = file.file_name();
                                        if name.to_string_lossy().ends_with(".proof") {
                                            return Ok(true);
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Ok(false)
}
