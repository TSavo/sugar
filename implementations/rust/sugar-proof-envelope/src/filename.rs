// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Cross-platform `.proof` filename helpers.
//
// A CID's canonical string form is `blake3-512:<128 hex>` (multihash
// discipline: the algorithm prefix travels with the digest so that the
// day we migrate to blake3-1024 or a post-quantum hash, the two forms
// coexist unambiguously and a loader can dispatch on the prefix).
//
// The literal `:` in that form is ILLEGAL in Windows filenames, so on
// disk we replace the colon with an underscore while KEEPING the prefix:
//
//   CID string form:        blake3-512:<128 hex>
//   on-disk filename stem:  blake3-512_<128 hex>
//   on-disk filename:       blake3-512_<128 hex>.proof
//
// `proof_filename` (format) and `cid_from_proof_stem` (parse) are exact
// inverses for the canonical form. Routing every writer through the
// former and the loader through the latter means the format and parse
// halves can never drift.

/// The canonical algorithm prefix carried by every CID string.
const HASH_TAG: &str = "blake3-512";

/// Format a CID string as a filesystem-safe stem: `blake3-512:<hex>` becomes
/// `blake3-512_<hex>`. The colon (illegal on Windows) is replaced by an
/// underscore; the algorithm prefix is retained so the stem stays
/// self-describing (crypto-agility / multihash discipline). Robust if the
/// CID already has no colon. This is the ONE place that owns the
/// colon-to-underscore filename transform; every on-disk filename derived
/// from a CID (`.proof`, `.witness`, cache files, report artifacts, ...)
/// routes through this helper rather than reimplementing the replacement.
pub fn cid_filename_stem(cid: &str) -> String {
    cid.replace(':', "_")
}

/// Format an on-disk `.proof` filename from a CID string.
///
/// `blake3-512:<hex>` becomes `blake3-512_<hex>.proof`. See
/// [`cid_filename_stem`] for the underlying transform.
pub fn proof_filename(cid: &str) -> String {
    format!("{}.proof", cid_filename_stem(cid))
}

/// Parse a `.proof` filename stem (the part before `.proof`) back into the
/// canonical CID string `blake3-512:<hex>`.
///
/// Accepts three shapes:
///   * `blake3-512_<hex>` — the colon-free on-disk form (this design)
///   * `blake3-512:<hex>` — the legacy colon form
///   * `<hex>`            — a bare 128-hex stem (prefix stripped)
///
/// The hex body must be exactly 128 lowercase/uppercase hex chars; any
/// other stem (e.g. the negative fixture `invalid-filename-cid`) yields
/// `None` so the loader keeps rejecting genuinely malformed stems.
pub fn cid_from_proof_stem(stem: &str) -> Option<String> {
    // Strip the algorithm prefix in either separator form, else treat the
    // whole stem as a bare hex body.
    let hex = stem
        .strip_prefix(&format!("{HASH_TAG}_"))
        .or_else(|| stem.strip_prefix(&format!("{HASH_TAG}:")))
        .unwrap_or(stem);
    if hex.len() == 128 && hex.bytes().all(|b| b.is_ascii_hexdigit()) {
        Some(format!("{HASH_TAG}:{hex}"))
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const HEX128: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    #[test]
    fn proof_filename_replaces_colon_with_underscore_and_keeps_prefix() {
        let cid = format!("blake3-512:{HEX128}");
        let name = proof_filename(&cid);
        assert!(!name.contains(':'), "filename must be colon-free: {name}");
        assert!(
            name.starts_with("blake3-512_"),
            "filename must keep the blake3-512_ prefix: {name}"
        );
        assert_eq!(name, format!("blake3-512_{HEX128}.proof"));
    }

    #[test]
    fn proof_filename_is_robust_when_cid_has_no_colon() {
        // A bare-hex "cid" (no separator) round-trips without a stray colon.
        let name = proof_filename(HEX128);
        assert!(!name.contains(':'));
        assert_eq!(name, format!("{HEX128}.proof"));
    }

    #[test]
    fn cid_from_proof_stem_round_trips_all_three_shapes() {
        let canonical = format!("blake3-512:{HEX128}");
        // underscore (on-disk) form
        assert_eq!(
            cid_from_proof_stem(&format!("blake3-512_{HEX128}")).as_deref(),
            Some(canonical.as_str())
        );
        // legacy colon form
        assert_eq!(
            cid_from_proof_stem(&format!("blake3-512:{HEX128}")).as_deref(),
            Some(canonical.as_str())
        );
        // bare hex form
        assert_eq!(
            cid_from_proof_stem(HEX128).as_deref(),
            Some(canonical.as_str())
        );
    }

    #[test]
    fn format_and_parse_are_inverses() {
        let canonical = format!("blake3-512:{HEX128}");
        let name = proof_filename(&canonical);
        let stem = name.trim_end_matches(".proof");
        assert_eq!(
            cid_from_proof_stem(stem).as_deref(),
            Some(canonical.as_str())
        );
    }

    #[test]
    fn cid_from_proof_stem_rejects_non_hex_stem() {
        // The deliberate negative fixture.
        assert_eq!(cid_from_proof_stem("invalid-filename-cid"), None);
        // Right prefix, wrong-length body.
        assert_eq!(cid_from_proof_stem("blake3-512_abcd"), None);
        // 128 chars but not all hex.
        let not_hex = "z".repeat(128);
        assert_eq!(cid_from_proof_stem(&not_hex), None);
    }
}
