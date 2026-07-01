"""Plugin-memento minting for the PEP 1.7.0 plugin loader.

The loader (``sugar-plugin-loader/src/loader.rs``) is language-agnostic: it
spawns this kit, sends ``sugar.plugin.describe``, and the ``result`` MUST be
a full plugin memento ``{envelope, header, metadata}``, not a flat capability
object. The loader then:

  1. shape-validates the three top-level keys (§3 / loader.rs:parse_and_validate),
  2. requires ``header.schemaVersion == "1"``,
  3. requires at least one ``header.protocol_versions`` token to be runtime-
     accepted (``pep/1.7.0``),
  4. RECOMPUTES ``header.cid`` per §6.1 and refuses on mismatch.

§6.1 content CID:

    cid = "blake3-512:" ++ hex(BLAKE3-512(JCS(input)))

where ``input`` is the header object with the ``cid`` field ELIDED:

    { content, critical, kind, protocol_versions (sorted asc),
      provenance_cid, schemaVersion, version }

JCS (RFC 8785) is reproduced here with python's ``json.dumps`` using sorted
keys, the compact ``(",", ":")`` separators, and ``ensure_ascii=False``. For
the data domain used here (strings, ints, bools, nested objects/arrays; no
floats) this is byte-identical to the rust ``sugar_canonicalizer::encode_jcs``
used by the loader. The ``test_plugin_memento`` golden test pins this against
the rust loader's ``dummy-sugar.json`` fixture CID so any divergence is caught.

Signing is intentionally a placeholder (zero-bytes ed25519): full signature
verification is §12 out-of-scope for the loader skeleton (see
``sugar-plugin-loader/src/types.rs`` doc on ``PluginEnvelope``). Wire a real
provenance signer when integrating this kit into the signing registry.
"""

from __future__ import annotations

import json
from typing import Any

import blake3

from . import predicate_table as pt

PLUGIN_KIND = "emit"
PLUGIN_VERSION = "0.1.0"
PROTOCOL_VERSIONS = ["pep/1.7.0"]
PROVENANCE_CID = "blake3-512:provenance-sugar-emit-python-pytest-0.1.0"

# Placeholder ed25519 envelope: 64-byte zero signature, 32-byte zero key, in the
# spec's "ed25519:<base64>" form. Real signing is the loader-integration
# follow-up (see module docstring).
_ZERO_SIGNATURE = "ed25519:" + ("A" * 86 + "==")
_ZERO_SIGNER = "ed25519:" + ("A" * 43 + "=")


def _jcs(value: Any) -> str:
    """RFC 8785 JCS encoding for the plugin-memento data domain."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_plugin_cid(header: dict[str, Any]) -> str:
    """Recompute the §6.1 content CID from a header dict (cid field elided).

    Mirrors ``sugar-plugin-loader/src/cid.rs::compute_plugin_cid``.
    """
    protocol_versions = sorted(header["protocol_versions"])
    cid_input = {
        "content": header["content"],
        "critical": header["critical"],
        "kind": header["kind"],
        "protocol_versions": protocol_versions,
        "provenance_cid": header["provenance_cid"],
        "schemaVersion": header["schemaVersion"],
        "version": header["version"],
    }
    return (
        "blake3-512:"
        + blake3.blake3(_jcs(cid_input).encode("utf-8")).digest(length=64).hex()
    )


def plugin_content() -> dict[str, Any]:
    """The opaque ``content`` payload: this kit's capability summary.

    The loader does not inspect ``content`` (§1.2: validators MUST NOT validate
    the inner shape); it is the consumer/dispatcher that reads the capabilities.
    """
    return {
        "name": "sugar-emit-python-pytest",
        "version": PLUGIN_VERSION,
        "kind": PLUGIN_KIND,
        "target_language": "python",
        "target_framework": "pytest",
        "capabilities": {
            "kits": ["python"],
            "emits": "pytest-assertions",
            "predicates": pt.supported_predicates(),
        },
    }


def plugin_header() -> dict[str, Any]:
    """The header with a correctly-computed, self-verifying ``cid``."""
    header = {
        "content": plugin_content(),
        "critical": False,
        "kind": PLUGIN_KIND,
        "protocol_versions": list(PROTOCOL_VERSIONS),
        "provenance_cid": PROVENANCE_CID,
        "schemaVersion": "1",
        "version": PLUGIN_VERSION,
    }
    header["cid"] = compute_plugin_cid(header)
    return header


def plugin_memento() -> dict[str, Any]:
    """The full ``{envelope, header, metadata}`` the loader's describe expects."""
    return {
        "envelope": {
            "declaredAt": "2026-05-23T00:00:00.000Z",
            "signature": _ZERO_SIGNATURE,
            "signer": _ZERO_SIGNER,
        },
        "header": plugin_header(),
        "metadata": {
            "maintainer": "T Savo <evilgenius@nefariousplan.com>",
            "note": (
                "PEP 1.7.0 pytest emitter: materializes neutral predicates as "
                "native pytest assertions. Mapping is inline python (no catalog "
                "template family)."
            ),
            "source_url": "implementations/python/sugar-emit-python-pytest",
        },
    }


# Mint once at module load: the memento (and its CID) is deterministic.
PLUGIN_MEMENTO: dict[str, Any] = plugin_memento()
