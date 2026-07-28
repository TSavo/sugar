"""Import-use source CID must pair with retained source text (path_source law).

Dual-door identity — ``read_text()`` for the string and ``blake3(read_bytes())``
for the CID — goes stale under CRLF/universal-newlines translation and aborts
nested-manager publication before lifecycle. The producer mint repairs the pair
from the retained source without re-reading disk or weakening authentication.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.import_binding import (
    _paired_source_cid,
    authenticated_import_use_receipts,
)
from sugar_lift_python_source.canonical import blake3_512_of


def test_paired_source_cid_repairs_dual_door_crlf(tmp_path: Path) -> None:
    """read_text + blake3(read_bytes) under CRLF must not refuse mint."""
    path = tmp_path / "consumer.py"
    path.write_bytes(b"from pkg import f\r\nx = f()\r\n")
    # Dual-door (the historical nested-manager fixture pattern):
    source = path.read_text(encoding="utf-8")  # LF after universal newlines
    claimed = blake3_512_of(path.read_bytes())  # still CRLF bytes
    assert blake3_512_of(source.encode("utf-8")) != claimed

    paired = _paired_source_cid(source, claimed)
    assert paired == blake3_512_of(source.encode("utf-8"))
    assert paired != claimed

    receipts, outcomes = authenticated_import_use_receipts(
        tmp_path, path, source, claimed, module_identities={}
    )
    assert outcomes
    assert receipts
    for receipt in receipts:
        # Receipt post_init requires source recomputes to source_cid.
        assert blake3_512_of(receipt.source.encode("utf-8")) == receipt.source_cid


def test_paired_source_cid_preserves_honest_match() -> None:
    source = "from pkg import f\nx = f()\n"
    cid = blake3_512_of(source.encode("utf-8"))
    assert _paired_source_cid(source, cid) == cid


def test_nested_manager_publication_survives_dual_door_consumer_identity(
    tmp_path: Path,
) -> None:
    """Vertical pin: nested publication with dual-door consumer triple.

    Same construction as test_generator_nested_managers._publish identity mint
    (read_text + blake3(read_bytes)). On CRLF bytes this used to raise
    ``authenticated import-use source CID is stale`` before nested layers ran.
    """
    import csv
    import importlib.metadata

    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedGeneratorResourceRefV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.manager_summary_derivation import (
        GeneratorBackedLifecycleProtocolV1,
        populate_source_derived_resource_refs,
    )
    from sugar_source_tree.tree import SourceFile

    package = tmp_path / "unprivileged"
    package.mkdir()
    helpers = (
        "from contextlib import contextmanager\r\n"
        "\r\n"
        "@contextmanager\r\n"
        "def inner():\r\n"
        "    prior = None\r\n"
        "    yield 'inner'\r\n"
        "\r\n"
        "@contextmanager\r\n"
        "def outer():\r\n"
        "    with inner():\r\n"
        "        yield 'outer'\r\n"
    )
    (package / "__init__.py").write_bytes(
        b"from unprivileged.helpers import outer, inner\r\n"
    )
    (package / "helpers.py").write_bytes(helpers.encode("utf-8"))
    metadata = tmp_path / "unprivileged_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_bytes(
        b"Metadata-Version: 2.1\r\nName: unprivileged-dist\r\nVersion: 1.0\r\n"
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in (
            "unprivileged/__init__.py",
            "unprivileged/helpers.py",
            "unprivileged_dist-1.0.dist-info/METADATA",
            "unprivileged_dist-1.0.dist-info/RECORD",
        ):
            writer.writerow((file, "", ""))
    distribution = importlib.metadata.Distribution.at(metadata)

    path = tmp_path / "consumer.py"
    path.write_bytes(b"from unprivileged import outer\r\nwith outer():\r\n    pass\r\n")
    # Dual-door identity (do not "fix" by switching to path_source here).
    text = path.read_text(encoding="utf-8")
    claimed = blake3_512_of(path.read_bytes())
    assert blake3_512_of(text.encode("utf-8")) != claimed

    context = TreeConstructionContextV1.for_source_call_construction(
        workspace_root=str(tmp_path)
    )
    tree = SourceFile((text, str(path), claimed), construction_context=context)
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )
    refs = [
        v
        for v in context.source_derived_contract_refs.values()
        if isinstance(v, SourceDerivedGeneratorResourceRefV1)
    ]
    assert refs, "nested outer must publish despite dual-door consumer identity"
    protocol = refs[0].generator_protocol
    assert isinstance(protocol, GeneratorBackedLifecycleProtocolV1)
    assert len(protocol.nested_manager_layers) == 1
