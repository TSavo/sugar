"""Reducing a non-local call target inside authenticated manager-factory source.

A call whose target is not defined in the factory's own module used to end
construction at ``opaque-call-target`` unconditionally.  But the defining
module's own top-level import IS a static export of that module, so the same
authenticated export/re-export resolver that authenticated the factory can
authenticate its callee.  These twins pin the two faces:

* callee reachable in the authenticated artifact -> constructed contract,
  asserted by the ACTUAL receiver state (field names and field values), with
  discrimination arms that perturb the defining source and must fail;
* callee NOT reachable in the authenticated artifact (native, stdlib outside
  the artifact, absent module) -> the site stays typed-loud at
  ``call-target-source-absent``.  That is the correct outcome, never a
  fabricated contract.  The kind names the CONDITION; the callee spelling
  rides ``detail`` and is never part of the key.

All fixture source here is neutral and written for this test.  No vendor text,
no vendor names, no name arms.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_lift_py_tests.ir import _term_content_cid
from sugar_lift_py_tests.floor import ObjectValue, TermValue
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import (
    ConstructedCallActualV1,
    ConstructedManagerBehaviorV1,
    ManagerConstructionGapV1,
    _ExternalCallTargetGap,
    _resolve_external_call_frame,
    construct_manager_behavior,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.binding_provenance import ConstructedValueTestimonyV1
from sugar_source_tree.nodes import Call, Constant
from sugar_source_tree.panic import OpaqueSourceCallResolutionGap
from sugar_source_tree.tree import SourceFile

# No hermetic-frames fixture: there is no process state left to clear.  Every
# resolution memo is owned by a SourceResolutionSession bounded to its own
# construction, so each test is isolated by construction rather than by a
# fixture that scrubs globals after the fact.


def _distribution(
    root: Path, *, factory_source: str, support_source: str
) -> importlib.metadata.Distribution:
    package = root / "arbitrary"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "from arbitrary.manager import make_guard\n", encoding="utf-8"
    )
    (package / "manager.py").write_text(factory_source, encoding="utf-8")
    (package / "support.py").write_text(support_source, encoding="utf-8")
    metadata = root / "arbitrary_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: arbitrary-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        "arbitrary/__init__.py",
        "arbitrary/manager.py",
        "arbitrary/support.py",
        "arbitrary_dist-1.0.dist-info/METADATA",
        "arbitrary_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _construct(root: Path, *, factory_source: str, support_source: str):
    """Authenticate the fixture artifact and construct ``make_guard(23)``."""
    graph = DependencyArtifactGraph.authenticate(
        _distribution(
            root, factory_source=factory_source, support_source=support_source
        )
    )
    consumer = "import arbitrary\narbitrary.make_guard(23)\n"
    path = root / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode())
    receipts, _ = authenticated_import_use_receipts(root, path, consumer, source_cid)
    resolved = resolve_import_binding(receipts[0], graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    source_file = SourceFile((consumer, str(path), source_cid))
    call = next(item for item in source_file.nodes() if isinstance(item, Call))
    literal = next(item for item in call.args if isinstance(item, Constant))
    value = TermValue(23)
    testimony = ConstructedValueTestimonyV1.mint(
        literal.fragment, _term_content_cid(value.to_term(owner="test"))
    )
    actual = ConstructedCallActualV1(literal, value, testimony)
    return (
        construct_manager_behavior(
            resolved, graph=graph, actuals=(actual,), call_site=call.fragment
        ),
        value,
    )


def _opaque_gap(root: Path, *, factory_source: str, support_source: str):
    with pytest.raises(OpaqueSourceCallResolutionGap) as raised:
        _construct(root, factory_source=factory_source, support_source=support_source)
    return raised.value


_CROSS_MODULE_CLASS_FACTORY = (
    "from arbitrary.support import ScopedSlot\n"
    "\n"
    "def make_guard(expected):\n"
    "    return ScopedSlot(expected)\n"
)

_CROSS_MODULE_CLASS_SUPPORT = (
    "class ScopedSlot:\n" "    def __init__(self, label):\n" "        self.label = 7\n"
)


def test_cross_module_class_call_target_reduces_to_constructed_receiver(tmp_path):
    """POSITIVE: the callee lives in another authenticated module of the artifact.

    Before the export door existed this ended typed-loud: ``ScopedSlot`` is not
    a definition of ``arbitrary.manager`` and not a semantic builtin.
    """
    result, _ = _construct(
        tmp_path,
        factory_source=_CROSS_MODULE_CLASS_FACTORY,
        support_source=_CROSS_MODULE_CLASS_SUPPORT,
    )

    assert isinstance(result, ConstructedManagerBehaviorV1), result
    assert isinstance(result.receiver_state, ObjectValue)
    fields = {field.name: field.value for field in result.receiver_state.fields}
    assert fields == {"label": TermValue(7)}
    assert result.receiver_state_cid.startswith("blake3-512:")


def test_cross_module_class_discrimination_field_name(tmp_path):
    """DISCRIMINATION: perturb the DEFINING source; the contract must move."""
    baseline, _ = _construct(
        tmp_path / "a",
        factory_source=_CROSS_MODULE_CLASS_FACTORY,
        support_source=_CROSS_MODULE_CLASS_SUPPORT,
    )
    perturbed, _ = _construct(
        tmp_path / "b",
        factory_source=_CROSS_MODULE_CLASS_FACTORY,
        support_source=(
            "class ScopedSlot:\n"
            "    def __init__(self, label):\n"
            "        self.marker = 7\n"
        ),
    )
    assert isinstance(baseline, ConstructedManagerBehaviorV1), baseline
    assert isinstance(perturbed, ConstructedManagerBehaviorV1), perturbed

    assert {f.name for f in baseline.receiver_state.fields} == {"label"}
    assert {f.name for f in perturbed.receiver_state.fields} == {"marker"}
    # The receiver identity is derived from the defining source, not from the
    # name of the call target: a lying twin cannot reuse the truthful CID.
    assert baseline.receiver_state_cid != perturbed.receiver_state_cid


def test_cross_module_class_discrimination_stored_value(tmp_path):
    """DISCRIMINATION: the stored value comes from the callee body, not the call."""
    result, _ = _construct(
        tmp_path,
        factory_source=_CROSS_MODULE_CLASS_FACTORY,
        support_source=(
            "class ScopedSlot:\n"
            "    def __init__(self, label):\n"
            "        self.label = 99\n"
        ),
    )
    assert isinstance(result, ConstructedManagerBehaviorV1), result
    fields = {field.name: field.value for field in result.receiver_state.fields}
    assert fields != {"label": TermValue(7)}
    assert fields == {"label": TermValue(99)}


def test_cross_module_function_hop_then_class_reduces(tmp_path):
    """POSITIVE: two hops -- imported function whose own body calls a local class."""
    result, _ = _construct(
        tmp_path,
        factory_source=(
            "from arbitrary.support import build_slot\n"
            "\n"
            "def make_guard(expected):\n"
            "    return build_slot(expected)\n"
        ),
        support_source=(
            "class ScopedSlot:\n"
            "    def __init__(self):\n"
            "        self.label = 7\n"
            "\n"
            "def build_slot(label):\n"
            "    return ScopedSlot()\n"
        ),
    )

    assert isinstance(result, ConstructedManagerBehaviorV1), result
    fields = {field.name: field.value for field in result.receiver_state.fields}
    assert fields == {"label": TermValue(7)}


def test_reexport_chain_call_target_reduces(tmp_path):
    """POSITIVE: the callee name is reached through a re-export hop, not a definition."""
    gap = _opaque_gap(
        tmp_path,
        factory_source=(
            "from arbitrary import ScopedSlot\n"
            "\n"
            "def make_guard(expected):\n"
            "    return ScopedSlot(expected)\n"
        ),
        support_source=_CROSS_MODULE_CLASS_SUPPORT,
    )
    # ``arbitrary/__init__.py`` written by the fixture only re-exports
    # make_guard, so ``arbitrary.ScopedSlot`` is NOT statically exported.
    # This is the honest negative face of the re-export door.
    assert gap.observed == "call-target-source-absent:ScopedSlot"


def test_unavailable_callee_stays_typed_loud(tmp_path):
    """REQUIRED LOUD TWIN: callee outside the authenticated artifact.

    ``pathlib`` is not part of this distribution's authenticated file
    manifest.  No source, no contract -- and specifically no fabricated one.
    """
    gap = _opaque_gap(
        tmp_path,
        factory_source=(
            "from pathlib import Path\n"
            "\n"
            "def make_guard(expected):\n"
            "    return Path(expected)\n"
        ),
        support_source="MARKER = 1\n",
    )

    assert gap.observed == "call-target-source-absent:Path"


def test_absent_module_callee_stays_typed_loud(tmp_path):
    """REQUIRED LOUD TWIN: import of a module absent from the artifact."""
    gap = _opaque_gap(
        tmp_path,
        factory_source=(
            "from arbitrary.missing import ScopedSlot\n"
            "\n"
            "def make_guard(expected):\n"
            "    return ScopedSlot(expected)\n"
        ),
        support_source="MARKER = 1\n",
    )

    assert gap.observed == "call-target-source-absent:ScopedSlot"


def test_undefined_free_name_call_stays_typed_loud(tmp_path):
    """REQUIRED LOUD TWIN: no import, no definition -- nothing to authenticate."""
    gap = _opaque_gap(
        tmp_path,
        factory_source=(
            "def make_guard(expected):\n    return unbound_helper(expected)\n"
        ),
        support_source="MARKER = 1\n",
    )

    assert gap.observed == "call-target-source-absent:unbound_helper"


def _resolved_pair(root: Path, *, factory_source: str, support_source: str):
    graph = DependencyArtifactGraph.authenticate(
        _distribution(
            root, factory_source=factory_source, support_source=support_source
        )
    )
    consumer = "import arbitrary\narbitrary.make_guard(23)\n"
    path = root / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode())
    receipts, _ = authenticated_import_use_receipts(root, path, consumer, source_cid)
    resolved = resolve_import_binding(receipts[0], graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    return graph, resolved


@pytest.mark.parametrize(
    "name,available",
    [
        ("ScopedSlot", True),
        ("MISSING_NAME", False),
        ("Path", False),
        ("make_guard", True),
    ],
)
def test_external_call_frame_demand_maps_exactly_onto_availability(
    tmp_path, name, available
):
    """The demand table and the resolution table are one bijection.

    Every demanded name gets exactly one answer, and the answer is decided by
    whether the defining source is authenticated in this artifact -- never by
    which package or module the name happens to come from.
    """
    graph, resolved = _resolved_pair(
        tmp_path,
        factory_source=(
            "from pathlib import Path\n"
            "from arbitrary.support import ScopedSlot\n"
            "\n"
            "def make_guard(expected):\n"
            "    return ScopedSlot(expected)\n"
        ),
        support_source=_CROSS_MODULE_CLASS_SUPPORT,
    )

    frame = _resolve_external_call_frame(
        name, resolved=resolved, graph=graph, session=SourceResolutionSession()
    )

    declined = isinstance(frame, _ExternalCallTargetGap)
    assert (not declined) is available
    if available:
        # The frame is the callee's OWN definition, addressed by content.
        assert frame.frame_cid.startswith("blake3-512:")
        assert frame.definition_fragment_cid.startswith("blake3-512:")
    else:
        # A decline is not a bare `None`: it names WHICH decline it was, so an
        # in-artifact symbol the door failed on can never be read as coverage.
        assert frame.kind == "call-target-source-absent"


def test_external_call_frame_is_the_callee_defining_source_not_the_caller(tmp_path):
    """The projected frame carries the DEFINING module's source identity."""
    graph, resolved = _resolved_pair(
        tmp_path,
        factory_source=_CROSS_MODULE_CLASS_FACTORY,
        support_source=_CROSS_MODULE_CLASS_SUPPORT,
    )

    frame = _resolve_external_call_frame(
        "ScopedSlot",
        resolved=resolved,
        graph=graph,
        session=SourceResolutionSession(),
    )

    assert frame is not None
    assert frame.source_identity_cid == graph.modules["arbitrary.support"].source_cid
    assert frame.source_identity_cid != resolved.source_cid


def test_mutually_recursive_cross_module_call_stays_typed_loud(tmp_path):
    """REQUIRED LOUD TWIN: a cross-module cycle must not loop or fabricate."""
    gap = _opaque_gap(
        tmp_path,
        factory_source=(
            "from arbitrary.support import build_slot\n"
            "\n"
            "def make_guard(expected):\n"
            "    return build_slot(expected)\n"
        ),
        support_source=(
            "from arbitrary.manager import make_guard\n"
            "\n"
            "def build_slot(label):\n"
            "    return make_guard(label)\n"
        ),
    )

    assert gap.observed == "call-graph-cycle:make_guard"
