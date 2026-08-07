"""A CITED protocol identity must never be readable as a DERIVED one.

#7384: an off-population target cites, it does not construct. An
``@contextmanager`` from ``contextlib`` cannot have its protocol derived --
that would mean materializing the decorator to read the manager class it
returns, which the membrane refuses, correctly. Option (A) publishes the
authenticated decorator identity itself as an opaque protocol identity.

The bar this file holds: the citation must stay visibly a citation IN THE
CONTENT ADDRESS. A downstream reader holding only the value -- without asking
the producer, without reading a variable name, without knowing which code path
minted it -- must be able to tell a citation from a derivation. So:

- the two wire forms are mutually undecodable, by each decoder's own key set;
- their CIDs cannot collide, because the preimages differ;
- the publication seat is a CLOSED two-member union, not an open door;
- a citation with nothing cited refuses, so absence never wears its clothes.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    CitedOpaqueProtocolIdentityV1,
    ContractRefProtocolError,
    NativeProtocolSlot,
    SourceDerivedGeneratorResourceRefV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_python_source.manager_summary_derivation import (
    _publish_native_definition,
    populate_source_derived_resource_refs,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile

_HELPERS = """\
from contextlib import contextmanager

@contextmanager
def alpha(flag):
    if flag:
        raise ValueError("enter-a")
    yield "resource-a"
    raise RuntimeError("exit-a")
"""


def _distribution(root: Path) -> importlib.metadata.Distribution:
    package = root / "unprivileged"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from unprivileged.helpers import alpha\n", encoding="utf-8"
    )
    (package / "helpers.py").write_text(_HELPERS, encoding="utf-8")
    metadata = root / "unprivileged_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: unprivileged-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        "unprivileged/__init__.py",
        "unprivileged/helpers.py",
        "unprivileged_dist-1.0.dist-info/METADATA",
        "unprivileged_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _publish(tmp_path: Path):
    """Publish the off-population ``@contextmanager`` road; return the context."""
    distribution = _distribution(tmp_path)
    path = tmp_path / "consumer.py"
    path.write_text(
        "from unprivileged import alpha\nwith alpha(False):\n    pass\n",
        encoding="utf-8",
    )
    context = TreeConstructionContextV1.for_source_call_construction(
        workspace_root=str(tmp_path)
    )
    tree = SourceFile(path_source(str(path)), construction_context=context)
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )
    return context


_DERIVED = SourceFragmentCoordinateV1("blake3-512:" + "ab" * 64, 1, 0, 2, 4)
_CITED = CitedOpaqueProtocolIdentityV1(
    NativeProtocolSlot.CONTEXT_ENTER.value,
    "contextlib",
    "contextmanager",
    "blake3-512:" + "cd" * 64,
    "call-target-off-population",
)


def test_cited_wire_is_refused_by_the_constructed_decoder() -> None:
    """The derived decoder rejects a citation by its own key set, not a check."""
    with pytest.raises(ContractRefProtocolError):
        SourceFragmentCoordinateV1.decode(_CITED.wire())


def test_derived_wire_is_refused_by_the_cited_decoder() -> None:
    """And the reverse: neither form can be read as the other."""
    with pytest.raises(ContractRefProtocolError):
        CitedOpaqueProtocolIdentityV1.decode(_DERIVED.wire())


def test_cited_and_derived_content_addresses_cannot_collide() -> None:
    """Different preimages, therefore different CIDs -- provenance in the value."""
    assert _CITED.wire() != _DERIVED.wire()
    assert _CITED.cid != _DERIVED.cid
    assert _CITED.wire()["kind"] == "cited-opaque-protocol-identity"
    assert "kind" not in _DERIVED.wire()


def test_cited_enter_and_exit_are_distinct_identities() -> None:
    """The slot is part of the citation, so enter and exit never coincide."""
    exit_ = CitedOpaqueProtocolIdentityV1(
        NativeProtocolSlot.CONTEXT_EXIT.value,
        _CITED.module_name,
        _CITED.exported_name,
        _CITED.resolved_object_cid,
        _CITED.membrane_kind,
    )
    assert exit_ != _CITED
    assert exit_.cid != _CITED.cid


def test_citation_without_testimony_refuses() -> None:
    """A citation with nothing cited is an absence in a citation's clothes."""
    for blanked in range(5):
        fields = [
            NativeProtocolSlot.CONTEXT_ENTER.value,
            "contextlib",
            "contextmanager",
            "blake3-512:" + "cd" * 64,
            "call-target-off-population",
        ]
        fields[blanked] = ""
        with pytest.raises(ContractRefProtocolError):
            CitedOpaqueProtocolIdentityV1(*fields)


def test_publication_seat_is_a_closed_two_member_union() -> None:
    """Only a derived coordinate or a citation may be published as a definition."""

    class _NotADefinition:
        def wire(self):  # pragma: no cover - must never be reached
            return {"kind": "cited-opaque-protocol-identity"}

    with pytest.raises(TypeError):
        _publish_native_definition(
            object(), _DERIVED, NativeProtocolSlot.CONTEXT_ENTER, _NotADefinition()
        )


def test_off_population_manager_publishes_a_citation_not_a_span(tmp_path) -> None:
    """The road fires, and what it publishes announces itself as cited."""
    context = _publish(tmp_path)
    published = [
        value
        for value in context.source_derived_contract_refs.values()
        if isinstance(value, SourceDerivedGeneratorResourceRefV1)
    ]
    assert len(published) == 1
    definitions = context.contract_refs.native_definitions
    slots = {
        slot: definition
        for (_receiver, slot), definition in definitions.items()
        if slot
        in (NativeProtocolSlot.CONTEXT_ENTER, NativeProtocolSlot.CONTEXT_EXIT)
    }
    assert set(slots) == {
        NativeProtocolSlot.CONTEXT_ENTER,
        NativeProtocolSlot.CONTEXT_EXIT,
    }
    for slot, definition in slots.items():
        # From the value alone: this is a citation, and it names what it cites.
        assert isinstance(definition, CitedOpaqueProtocolIdentityV1)
        assert definition.slot == slot.value
        assert (definition.module_name, definition.exported_name) == (
            "contextlib",
            "contextmanager",
        )
        assert definition.membrane_kind == "call-target-off-population"
        with pytest.raises(ContractRefProtocolError):
            SourceFragmentCoordinateV1.decode(definition.wire())


def test_published_protocol_preimage_carries_the_citation(tmp_path) -> None:
    """The protocol CID is over the cited wire form -- a derivation would differ."""
    context = _publish(tmp_path)
    protocols = [
        value.protocol
        for value in context.source_derived_contract_refs.values()
        if isinstance(value, SourceDerivedGeneratorResourceRefV1)
    ]
    assert len(protocols) == 1
    preimage = protocols[0].preimage
    assert preimage["enterDefinition"]["kind"] == "cited-opaque-protocol-identity"
    assert preimage["exitDefinition"]["kind"] == "cited-opaque-protocol-identity"
    assert preimage["enterDefinition"] != preimage["exitDefinition"]
