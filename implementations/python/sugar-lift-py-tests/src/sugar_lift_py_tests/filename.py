# SPDX-License-Identifier: MIT OR Apache-2.0
#
# Cross-platform CID filename helpers. Mirrors
# implementations/rust/sugar-proof-envelope/src/filename.rs 1:1.
#
# A CID's canonical string form is `blake3-512:<128 hex>` (multihash
# discipline: the algorithm prefix travels with the digest so that the
# day we migrate to blake3-1024 or a post-quantum hash, the two forms
# coexist unambiguously and a loader can dispatch on the prefix).
#
# The literal `:` in that form is ILLEGAL in Windows filenames, so on
# disk we replace the colon with an underscore while KEEPING the prefix:
#
#   CID string form:        blake3-512:<128 hex>
#   on-disk filename stem:  blake3-512_<128 hex>
#   on-disk filename:       blake3-512_<128 hex>.proof
#
# `proof_filename` / `cid_filename` (format) and `cid_from_proof_stem`
# (parse) are exact inverses for the canonical form. Routing every writer
# through the former and every loader through the latter means the format
# and parse halves can never drift -- this is the ONE place that owns CID
# filename-stem knowledge for the Python kit; consumers reimplementing the
# colon/underscore transform or the stem-parse are side doors.

from __future__ import annotations

HASH_TAG = "blake3-512"


def cid_filename_stem(cid: str) -> str:
    """Format a CID string as a filesystem-safe stem: ``blake3-512:<hex>``
    becomes ``blake3-512_<hex>``. Robust if ``cid`` already has no colon."""
    return cid.replace(":", "_")


def proof_filename(cid: str) -> str:
    """Format an on-disk ``.proof`` filename from a CID string."""
    return cid_filename_stem(cid) + ".proof"


def cid_filename(cid: str, ext: str) -> str:
    """Format an on-disk filename with an arbitrary extension (``.witness``,
    etc) from a CID string. Same colon-to-underscore transform as
    ``proof_filename``, generalized to non-``.proof`` artifacts."""
    return cid_filename_stem(cid) + ext


def cid_from_proof_stem(stem: str) -> str | None:
    """Parse a ``.proof``/``.witness`` filename stem (the part before the
    extension) back into the canonical CID string ``blake3-512:<hex>``.

    Accepts three shapes:
      * ``blake3-512_<hex>`` -- the colon-free on-disk form (this design)
      * ``blake3-512:<hex>`` -- the legacy colon form
      * ``<hex>``            -- a bare 128-hex stem (prefix stripped)

    The hex body must be exactly 128 hex chars; any other stem yields
    ``None`` so the loader keeps rejecting genuinely malformed stems.
    """
    if stem.startswith(HASH_TAG + "_"):
        hex_body = stem[len(HASH_TAG) + 1 :]
    elif stem.startswith(HASH_TAG + ":"):
        hex_body = stem[len(HASH_TAG) + 1 :]
    else:
        hex_body = stem
    if len(hex_body) == 128 and all(c in "0123456789abcdefABCDEF" for c in hex_body):
        return f"{HASH_TAG}:{hex_body}"
    return None
