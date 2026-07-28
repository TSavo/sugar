"""Consumer proof: GeneratorConstructionV1.to_term reads sealed binding testimony.

Producer seals BindingEntryV1 at allocate. The term preimage carries
constructed-value testimony CIDs from sealed entries — never coordinate-only
fallback, never consumer-fabricated testimony.
"""

from __future__ import annotations

import tempfile

import pytest

from sugar_lift_py_tests.generator_construction import (
    GeneratorConstructionV1,
    ReturnStepV1,
    YieldStepV1,
)
from sugar_lift_py_tests.ir import num
from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.binding_provenance import ConstructedValueTestimonyV1
from sugar_source_tree.binding_state import (
    BindingStateWireGap,
    RuntimeBindingEntryFactoryV1,
    seal_bound_binding_entry_v1,
)
from sugar_source_tree.tree import SourceFile


def _entry_pair(source_a: str, source_b: str | None = None):
    def _one(source: str):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
            handle.write(source)
            path = handle.name
        function = next(SourceFile(path_source(path)).functions())
        assignment = next(node for node in function.walk() if node.kind == "Assign")
        factory = RuntimeBindingEntryFactoryV1(
            cid_of_json({"scope": function.fragment.seal().to_dict()})
        )
        return factory.mint_entry(
            binding_site=assignment.targets[0].fragment,
            projection_path=("targets", 0),
            state=assignment.value,
        )

    left = _one(source_a)
    right = _one(source_b or source_a)
    return left, right


def _machine(binding):
    return GeneratorConstructionV1.allocate(
        allocation_coordinate="call:gen:1",
        frame_coordinate="frame:gen",
        binding_state=binding,
        steps=(YieldStepV1(num(1)), ReturnStepV1(num(2))),
    )


def test_allocate_seals_binding_entries_with_constructed_value_testimony():
    entry, _ = _entry_pair("def gen():\n    bound = 7\n    yield bound\n")
    assert entry.constructed_value_testimony is None
    machine = _machine((entry,))
    sealed = machine.binding_state[0]
    testimony = sealed.require_constructed_value_testimony()
    assert isinstance(testimony, ConstructedValueTestimonyV1)
    # Successfully sealed: wire does not delay a gap.
    assert sealed.wire()["state"]["kind"] == "bound"


def test_to_term_preimage_carries_sealed_testimony_not_coordinate_only():
    entry, _ = _entry_pair("def gen():\n    bound = 7\n    yield bound\n")
    machine = _machine((entry,))
    sealed = machine.binding_state[0]
    preimage = machine.construction_term_preimage()
    item = preimage["bindingState"][0]
    assert item["kind"] == "sealed-bound-binding"
    assert item["coordinateCid"] == sealed.coordinate.cid
    assert (
        item["constructedValueTestimonyCid"]
        == sealed.require_constructed_value_testimony().cid
    )
    assert item["entry"] == sealed.wire()


def test_identical_sealed_bindings_yield_identical_terms():
    left_entry, right_entry = _entry_pair(
        "def gen():\n    bound = 7\n    yield bound\n"
    )
    # Same source text → same value content; coordinates differ by occurrence.
    # Seal with the same semantic path through allocate.
    left = _machine((left_entry,))
    right = _machine((right_entry,))
    # Different factory occurrences → different coordinates → different terms.
    # Same sealed entry reused twice must match.
    same = _machine((left_entry,))
    assert left.to_term(owner="test") == same.to_term(owner="test")
    assert left.construction_term_cid() == same.construction_term_cid()
    # Distinct coordinates still differ.
    assert left.to_term(owner="test") != right.to_term(owner="test")


def test_changed_value_content_changes_term():
    left_entry, _ = _entry_pair("def gen():\n    bound = 1\n    yield bound\n")
    right_entry, _ = _entry_pair("def gen():\n    bound = 2\n    yield bound\n")
    left = _machine((left_entry,))
    right = _machine((right_entry,))
    assert left.to_term(owner="test") != right.to_term(owner="test")
    assert (
        left.binding_state[0].require_constructed_value_testimony().cid
        != right.binding_state[0].require_constructed_value_testimony().cid
    )


def test_unsealed_entry_cannot_project_term_without_producer_seal():
    """Lying twin: stripping sealed_state after allocate is not the live path.

    Allocate always seals; force an unsealed entry into construction_term_preimage
    via a hand-built machine to prove the consumer refuses fabrication.
    """
    entry, _ = _entry_pair("def gen():\n    bound = 7\n    yield bound\n")
    # Bypass allocate seal by constructing the frozen dataclass directly.
    machine = GeneratorConstructionV1(
        allocation_coordinate="call:gen:1",
        frame_coordinate="frame:gen",
        binding_state=(entry,),  # unsealed
        steps=(YieldStepV1(num(1)),),
        instance_coordinate="blake3-512:" + "a" * 128,
    )
    with pytest.raises(BindingStateWireGap, match="testimony unavailable"):
        machine.construction_term_preimage()


def test_mismatched_supplied_testimony_refuses_before_allocate():
    entry, _ = _entry_pair("def gen():\n    bound = 7\n    yield bound\n")
    lying = ConstructedValueTestimonyV1.mint(
        entry.state.fragment,
        cid_of_json({"kind": "lying", "value": -1}),
    )
    with pytest.raises(BindingStateWireGap, match="does not match"):
        seal_bound_binding_entry_v1(entry, testimony=lying)


def test_primitive_binding_stubs_still_allocate_without_entry_seal():
    """Existing non-entry binding stubs remain valid allocate inputs."""
    machine = _machine(("bound:x",))
    assert machine.binding_state == ("bound:x",)
    preimage = machine.construction_term_preimage()
    assert preimage["bindingState"] == [{"kind": "primitive", "value": "bound:x"}]
