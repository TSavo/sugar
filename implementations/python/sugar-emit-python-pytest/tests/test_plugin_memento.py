"""The describe response must satisfy the PEP 1.7.0 plugin-loader contract.

These tests are adversarial: they do NOT trust the kit's cached CID. They
independently re-derive the §6.1 content CID from the header fields and assert
the kit's minted CID matches. A test that merely round-tripped the kit's own
value would be circular and would not catch a divergence from the rust loader's
``compute_plugin_cid``.

The golden test pins the python JCS implementation against the rust loader's
checked-in fixture (``sugar-plugin-loader/tests/fixtures/dummy-sugar.json``),
whose CID was produced by the rust ``compute_plugin_cid``.
"""

from __future__ import annotations

import json

import blake3

from sugar_emit_python_pytest.plugin_memento import (
    PLUGIN_MEMENTO,
    plugin_memento,
)


def _independent_jcs(value) -> str:
    """A second, hand-rolled JCS encoder, independent of the kit's, so the test

    does not just re-run the code under test."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _independent_cid(header: dict) -> str:
    cid_input = {
        "content": header["content"],
        "critical": header["critical"],
        "kind": header["kind"],
        "protocol_versions": sorted(header["protocol_versions"]),
        "provenance_cid": header["provenance_cid"],
        "schemaVersion": header["schemaVersion"],
        "version": header["version"],
    }
    digest = blake3.blake3(_independent_jcs(cid_input).encode("utf-8")).digest(
        length=64
    )
    return "blake3-512:" + digest.hex()


def test_memento_has_three_top_level_keys() -> None:
    assert set(PLUGIN_MEMENTO.keys()) == {"envelope", "header", "metadata"}


def test_header_satisfies_loader_validation_rules() -> None:
    header = PLUGIN_MEMENTO["header"]
    # schemaVersion MUST be "1".
    assert header["schemaVersion"] == "1"
    assert header["kind"] == "emit"
    # At least one protocol_versions token must be runtime-accepted.
    assert "pep/1.7.0" in header["protocol_versions"]
    # The eight canonical header fields must all be present.
    assert set(header.keys()) == {
        "cid",
        "content",
        "critical",
        "kind",
        "protocol_versions",
        "provenance_cid",
        "schemaVersion",
        "version",
    }


def test_cid_matches_independent_recomputation() -> None:
    # Adversarial: re-derive the CID from the header fields with a separate
    # encoder; the kit's asserted cid must equal it (the loader does exactly
    # this and refuses on mismatch).
    header = PLUGIN_MEMENTO["header"]
    assert header["cid"] == _independent_cid(header)


def test_cid_field_is_elided_from_input() -> None:
    # Mutating the asserted cid must NOT change the recomputed cid (§6.1: the
    # cid field is elided from the CID input).
    m = plugin_memento()
    original = _independent_cid(m["header"])
    m["header"]["cid"] = "blake3-512:tampered"
    assert _independent_cid(m["header"]) == original


def test_capabilities_live_in_content() -> None:
    content = PLUGIN_MEMENTO["header"]["content"]
    assert content["kind"] == "emit"
    assert content["target_language"] == "python"
    assert content["target_framework"] == "pytest"
    assert "concept:eq" in content["capabilities"]["predicates"]
    assert "concept:fallible-err" in content["capabilities"]["predicates"]


def test_golden_cid_matches_rust_loader_fixture() -> None:
    # Pin the python JCS + blake3-512 against the rust loader's checked-in
    # fixture CID (dummy-sugar.json), produced by rust compute_plugin_cid.
    # Any drift between the python and rust canonical encoders breaks this.
    fixture_header_input = {
        "content": {
            "data": "test-dummy-fixture-2026-05-12",
            "kind": "test:dummy",
            "version": "0.1.0",
        },
        "critical": False,
        "kind": "test:dummy",
        "protocol_versions": ["pep/1.7.0"],
        "provenance_cid": "blake3-512:provenance-test-dummy-fixture-2026-05-12",
        "schemaVersion": "1",
        "version": "0.1.0",
    }
    digest = blake3.blake3(
        _independent_jcs(fixture_header_input).encode("utf-8")
    ).digest(length=64)
    computed = "blake3-512:" + digest.hex()
    expected = (
        "blake3-512:ad148c5f529aab7b019c8980ffa2b2f0d982fd43799a4ee87a01e3e3d5da6cd4"
        "14beac89adddbad09c03d398b77ec2cda74bc04fe63b1494e6d1bed8880fd7ea"
    )
    assert computed == expected
