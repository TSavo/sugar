"""Plugin-memento minting for the PEP 1.7.0 Hypothesis emitter."""

from __future__ import annotations

import json
from typing import Any

import blake3

from .emitter import supported_predicates

PLUGIN_KIND = "emit"
PLUGIN_VERSION = "0.1.0"
PROTOCOL_VERSIONS = ["pep/1.7.0"]
PROVENANCE_CID = "blake3-512:provenance-sugar-emit-python-hypothesis-0.1.0"

_ZERO_SIGNATURE = "ed25519:" + ("A" * 86 + "==")
_ZERO_SIGNER = "ed25519:" + ("A" * 43 + "=")


def _jcs(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_plugin_cid(header: dict[str, Any]) -> str:
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
    return {
        "name": "sugar-emit-python-hypothesis",
        "version": PLUGIN_VERSION,
        "kind": PLUGIN_KIND,
        "target_language": "python",
        "target_framework": "hypothesis",
        "capabilities": {
            "kits": ["python"],
            "emits": "hypothesis-properties",
            "predicates": supported_predicates(),
        },
    }


def plugin_header() -> dict[str, Any]:
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
    return {
        "envelope": {
            "declaredAt": "2026-05-29T00:00:00.000Z",
            "signature": _ZERO_SIGNATURE,
            "signer": _ZERO_SIGNER,
        },
        "header": plugin_header(),
        "metadata": {
            "maintainer": "T Savo <evilgenius@nefariousplan.com>",
            "note": (
                "PEP 1.7.0 Hypothesis emitter: materializes safe neutral "
                "predicate slices as native Python property tests."
            ),
            "source_url": "implementations/python/sugar-emit-python-hypothesis",
        },
    }


PLUGIN_MEMENTO: dict[str, Any] = plugin_memento()
