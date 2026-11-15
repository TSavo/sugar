"""Doctrine laws for fleet-agy-1 lane: broad catches must not swallow panics.

Audit (manager_summary_derivation / manager_protocol_construction /
binding_state) found a live offender:

``binding_state._semantic_value_cid_for_bound_node`` catches ``Exception``
(including ``SugarNotWritten``) and soft-succeeds with the node shape CID,
so ``seal_bound_binding_entry_v1`` can mint sealed testimony after sugar
refused. Seal must stay loud when value construction refused.

These instruments stay green when production refuses soft-seals:
SugarNotWritten refuses seal. No carrier/ExitSet, no silent None soft-greens.
"""

from __future__ import annotations

import tempfile

import pytest

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.binding_state import (
    BindingStateWireGap,
    RuntimeBindingEntryFactoryV1,
    seal_bound_binding_entry_v1,
)
from sugar_source_tree.nodes import Node
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _constant_entry():
    source = "def gen():\n    bound = 1\n    yield bound\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    function = next(SourceFile(path_source(path)).functions())
    value = next(node for node in function.walk() if node.kind == "Constant")
    factory = RuntimeBindingEntryFactoryV1(cid_of_json({"scope": "doctrine-audit"}))
    entry = factory.mint_entry(
        binding_site=value.fragment,
        projection_path=("value", 0),
        state=value,
    )
    return value, entry


def test_seal_refuses_when_node_sugar_raises_sugar_not_written():
    """Law: SugarNotWritten from node.sugar() must prevent sealing.

    Illegal shape (live offender):
        try: node.sugar(); except Exception: return node_construction_shape_cid(node)
        → seal_bound_binding_entry_v1 succeeds with shape-derived testimony

    Replacement: re-raise SugarNotWritten / map only non-refusal misses, or
    refuse seal with BindingStateWireGap. Never mint sealed testimony from a
    value whose sugar refused.
    """
    value, entry = _constant_entry()
    real_sugar = Node.sugar

    def refusing_sugar(self):
        raise SugarNotWritten(
            blame=self.fragment,
            owner="doctrine.seal-sugar",
            observed="sugar refused for bound value",
            requested="written constructed sugar",
            fix="write sugar or refuse seal; do not fall back to shape CID",
        )

    Node.sugar = refusing_sugar  # type: ignore[method-assign]
    try:
        with pytest.raises((SugarNotWritten, BindingStateWireGap)):
            seal_bound_binding_entry_v1(entry)
    finally:
        Node.sugar = real_sugar  # type: ignore[method-assign]


def test_seal_must_not_succeed_after_sugar_not_written():
    """Lying twin: successful seal after SugarNotWritten is the doctrine crime."""
    _value, entry = _constant_entry()
    real_sugar = Node.sugar

    def refusing_sugar(self):
        raise SugarNotWritten(
            blame=self.fragment,
            owner="doctrine.seal-sugar",
            observed="sugar refused for bound value",
            requested="written constructed sugar",
            fix="write sugar or refuse seal; do not fall back to shape CID",
        )

    Node.sugar = refusing_sugar  # type: ignore[method-assign]
    try:
        with pytest.raises((SugarNotWritten, BindingStateWireGap)):
            seal_bound_binding_entry_v1(entry)
    finally:
        Node.sugar = real_sugar  # type: ignore[method-assign]


def test_mutation_twin_tampered_seal_coordinate_still_refuses_after_sugar_refusal():
    """Mutation twin: stale coordinate cannot launder a refused sugar into a seal."""
    from dataclasses import replace

    _value, entry = _constant_entry()
    real_sugar = Node.sugar

    def refusing_sugar(self):
        raise SugarNotWritten(
            blame=self.fragment,
            owner="doctrine.seal-sugar",
            observed="sugar refused for bound value",
            requested="written constructed sugar",
            fix="write sugar or refuse seal; do not fall back to shape CID",
        )

    Node.sugar = refusing_sugar  # type: ignore[method-assign]
    try:
        tampered = replace(
            entry,
            coordinate=replace(entry.coordinate, cid="blake3-512:" + "f" * 128),
        )
        with pytest.raises((SugarNotWritten, BindingStateWireGap, ValueError)):
            seal_bound_binding_entry_v1(tampered)
    finally:
        Node.sugar = real_sugar  # type: ignore[method-assign]
