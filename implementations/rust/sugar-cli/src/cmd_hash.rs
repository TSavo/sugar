// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar hash [FILE]`: print blake3-512:<hex> of file or stdin.

use std::io::Read;

use owo_colors::OwoColorize;
use serde_json::json;
use sugar_canonicalizer::blake3_512_of;

use crate::HashArgs;

pub fn run(args: HashArgs) -> u8 {
    match read_input(args.file.as_deref()) {
        Ok(bytes) => {
            let cid = blake3_512_of(&bytes);
            if args.out.json {
                let payload = json!({"cid": cid, "bytes": bytes.len()});
                println!("{}", payload);
            } else {
                println!("{cid}");
            }
            crate::EXIT_OK
        }
        Err(e) => {
            eprintln!("{}: {e}", "error".red().bold());
            crate::EXIT_USER_ERROR
        }
    }
}

fn read_input(path: Option<&std::path::Path>) -> std::io::Result<Vec<u8>> {
    match path {
        Some(p) => std::fs::read(p),
        None => {
            let mut buf = Vec::new();
            std::io::stdin().read_to_end(&mut buf)?;
            Ok(buf)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn hash_known_input_matches_lib() {
        // Write a temp file, hash it, compare to the lib's direct hash.
        let dir = std::env::temp_dir();
        let p = dir.join(format!("sugar-cli-hash-test-{}", std::process::id()));
        let bytes = b"the quick brown fox";
        {
            let mut f = std::fs::File::create(&p).unwrap();
            f.write_all(bytes).unwrap();
        }
        let direct = blake3_512_of(bytes);
        let got = read_input(Some(&p)).unwrap();
        assert_eq!(blake3_512_of(&got), direct);
        std::fs::remove_file(&p).ok();
    }

    #[test]
    fn hash_missing_file_returns_user_error() {
        let r = read_input(Some(std::path::Path::new(
            "/this/path/does/not/exist/please-trust-me",
        )));
        assert!(r.is_err());
    }

    #[test]
    fn empty_input_hashes_consistently() {
        let h1 = blake3_512_of(b"");
        let h2 = blake3_512_of(b"");
        assert_eq!(h1, h2);
        assert!(h1.starts_with("blake3-512:"));
    }
}
