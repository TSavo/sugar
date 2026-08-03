"""Returned assertion managers preserve factored message-pattern faces.

A source helper that returns an authenticated EffectBoundary manager must keep
``match=None`` and ``match=pattern`` faces distinct through:

- caller return / assignment projection
- ``populate_source_derived_resource_refs``
- ``With.sugar`` construction
- raise routing and authenticated ``as excinfo`` binding

Direct construction of the same manager class is the twin: face identities and
outcomes must match. A lying wrapper that returns an ordinary resource under the
assertion spelling cannot borrow the EffectBoundary contract.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    EffectBoundarySemanticsV1,
    NoMessagePatternV1,
    OptionalFormalArgumentProjectionV1,
    ProtocolResourceSemanticsV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerResolutionGapV1,
    FactoredSourceDerivedContextManagerRefV1,
    SourceDerivedContextManagerRefV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_summary_derivation import (
    populate_source_derived_resource_refs,
)
from sugar_source_tree.nodes import With
from sugar_source_tree.tree import SourceFile

# Match sole-path dual-mode / as-binding fixtures that populate already seals.
_ASSERTION_MANAGER = (
    "class Boundary:\n"
    "    def __init__(self, expected, match=None):\n"
    "        self.expected = expected\n"
    "        self.match = match\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, effect_type, effect, traceback):\n"
    "        if effect_type is None:\n"
    "            raise RuntimeError()\n"
    "        return effect_type is self.expected\n"
    "\n"
    "def make_boundary(expected, match=None):\n"
    "    return Boundary(expected, match)\n"
    "\n"
    "def boundary(expected, match=None):\n"
    "    return Boundary(expected, match)\n"
)

# Required match formal (sole-path message twin). Optional default confuses
# soft formal indexing when the use site writes match=.
_ASSERTION_MANAGER_WITH_MESSAGE = (
    "class Boundary:\n"
    "    def __init__(self, expected, match):\n"
    "        self.expected = expected\n"
    "        self.match = match\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, effect_type, effect, traceback):\n"
    "        if effect_type is None:\n"
    "            raise RuntimeError()\n"
    "        return (effect_type is self.expected) and (\n"
    "            effect.message == self.match\n"
    "        )\n"
    "\n"
    "def make_boundary(expected, match):\n"
    "    return Boundary(expected, match)\n"
    "\n"
    "def boundary(expected, match):\n"
    "    return Boundary(expected, match)\n"
)

_LYING_WRAPPER = (
    "class OrdinaryResource:\n"
    "    def __init__(self, expected, match=None):\n"
    "        self.expected = expected\n"
    "        self.match = match\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, effect_type, effect, traceback):\n"
    "        return False\n"
    "\n"
    "def make_boundary(expected, match=None):\n"
    "    return OrdinaryResource(expected, match)\n"
)


def _distribution(root: Path, source: str, *, exported: str = "make_boundary"):
    package = root / "arbitrary"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(
        f"from arbitrary.manager import {exported}\n",
        encoding="utf-8",
    )
    (package / "manager.py").write_text(source, encoding="utf-8")
    metadata = root / "arbitrary_dist-1.0.dist-info"
    metadata.mkdir(exist_ok=True)
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: arbitrary-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        "arbitrary/__init__.py",
        "arbitrary/manager.py",
        "arbitrary_dist-1.0.dist-info/METADATA",
        "arbitrary_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _populate(root: Path, consumer: str, *, dist):
    path = root / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=root,
        path=path,
        distribution_index={"arbitrary": dist},
    )
    return tree, context, path


def _with_node(tree):
    return next(node for node in tree.nodes() if isinstance(node, With))


def _reference(context, tree):
    node = _with_node(tree)
    return node._prebound_manager_resolution(node.items[0]), node


def _message_operand(reference):
    if isinstance(reference, FactoredSourceDerivedContextManagerRefV1):
        return {
            face.value.message_pattern_operand
            for face in reference.boundary_faces.exits
            if isinstance(face, Completed)
        }
    if isinstance(reference, SourceDerivedContextManagerRefV1):
        return {reference.semantics.message_pattern_operand}
    return None


def _face_guard_names(reference):
    if not isinstance(reference, FactoredSourceDerivedContextManagerRefV1):
        return set()
    return {
        getattr(face.guard, "name", None)
        for face in reference.boundary_faces.exits
        if isinstance(face, Completed)
    }


def _observed_binding(face):
    from sugar_lift_py_tests.effect_router import ObservedEffectBinding

    record = face.value if isinstance(face, Completed) else face.state
    entries = getattr(record, "entries", ()) or ()
    return next(
        (entry for entry in entries if isinstance(entry, ObservedEffectBinding)),
        None,
    )


def test_returned_manager_match_none_preserves_no_message_pattern(tmp_path: Path):
    """Returned factory with written match=None seals NoMessagePattern, not a gap."""
    dist = _distribution(tmp_path, _ASSERTION_MANAGER)
    consumer = (
        "import arbitrary\n"
        "def use():\n"
        "    with arbitrary.make_boundary(ValueError) as info:\n"
        "        raise ValueError('boom')\n"
    )
    tree, context, _ = _populate(tmp_path, consumer, dist=dist)
    reference, node = _reference(context, tree)

    assert not isinstance(reference, ContextManagerResolutionGapV1), reference
    assert isinstance(reference, SourceDerivedContextManagerRefV1), reference
    assert isinstance(reference.semantics, EffectBoundarySemanticsV1)
    assert isinstance(reference.semantics.message_pattern_operand, NoMessagePatternV1)

    sugar = node.sugar()
    assert isinstance(sugar, WithEffectBoundarySugar)
    assert sugar.observation_slot_id is not None
    assert sugar.observation_slot_id.endswith("#observation")

    exits = outcome_to_exitset(sugar.desugar())
    completed = [face for face in exits.exits if isinstance(face, Completed)]
    assert len(completed) == 1
    binding = _observed_binding(completed[0])
    assert binding is not None
    assert binding.slot_id == sugar.observation_slot_id
    assert getattr(binding.effect, "exception_name", None) == "ValueError"


def test_returned_manager_pattern_preserves_message_obligation(tmp_path: Path):
    """Returned match=pattern seals the obligation; excinfo binds consumed occurrence."""
    dist = _distribution(
        tmp_path, _ASSERTION_MANAGER_WITH_MESSAGE, exported="boundary"
    )
    consumer = (
        "import arbitrary\n"
        "def use():\n"
        "    pattern = 'needle'\n"
        "    with arbitrary.boundary(ValueError, match=pattern) as info:\n"
        "        raise ValueError('needle')\n"
    )
    tree, context, _ = _populate(tmp_path, consumer, dist=dist)
    reference, node = _reference(context, tree)

    assert not isinstance(reference, ContextManagerResolutionGapV1), reference
    assert isinstance(reference, SourceDerivedContextManagerRefV1), reference
    assert isinstance(reference.semantics, EffectBoundarySemanticsV1)
    # Message obligation preserved through return / populate / With.
    assert isinstance(
        reference.semantics.message_pattern_operand,
        OptionalFormalArgumentProjectionV1,
    )

    sugar = node.sugar()
    assert isinstance(sugar, WithEffectBoundarySugar)
    assert sugar.observation_slot_id is not None
    # Single sealed pattern face (not collapsed to NoMessagePattern).
    assert sugar.semantics is not None
    assert isinstance(
        sugar.semantics.message_pattern_operand, OptionalFormalArgumentProjectionV1
    )
    assert sugar.semantics.message_pattern_operand == (
        reference.semantics.message_pattern_operand
    )

    exits = outcome_to_exitset(sugar.desugar())
    completed = [face for face in exits.exits if isinstance(face, Completed)]
    assert completed, exits.exits
    binding = _observed_binding(completed[0])
    assert binding is not None
    assert binding.slot_id == sugar.observation_slot_id
    assert getattr(binding.effect, "exception_name", None) == "ValueError"
    # Bind only the consumed raise occurrence — not a fabricated twin.
    occurrence = (
        getattr(binding.effect, "occurrence_id", None)
        or getattr(binding.effect, "occurrence", None)
        or getattr(binding.effect, "blame", None)
    )
    assert occurrence == str(binding)
    assert all(_observed_binding(face) is None for face in exits.exits if isinstance(face, Halted))


def test_direct_imported_name_manager_with_keyword_uses_source_contract(
    tmp_path: Path,
):
    """Exact imported callee identity advances to its deeper source-body gap."""
    dist = _distribution(
        tmp_path, _ASSERTION_MANAGER_WITH_MESSAGE, exported="boundary"
    )
    consumer = (
        "from arbitrary import boundary as hold\n"
        "def use():\n"
        "    pattern = 'needle'\n"
        "    with hold(ValueError, match=pattern) as info:\n"
        "        raise ValueError('needle')\n"
    )
    tree, context, _ = _populate(tmp_path, consumer, dist=dist)
    reference, _ = _reference(context, tree)

    assert isinstance(reference, ContextManagerResolutionGapV1), reference
    assert reference.target_symbol == "python:arbitrary.boundary"
    assert reference.kind == "source-body-gap"
    assert "CallSiteSugar at arbitrary/manager.py:18:11" in reference.detail
    assert (
        "source call definition is not this call's exact typed occurrence"
        in reference.detail
    )


def test_direct_imported_name_manager_with_double_star_stays_loud(
    tmp_path: Path,
):
    """Imported ``**kwargs`` call advances to the same earlier provider-body gap."""
    dist = _distribution(
        tmp_path, _ASSERTION_MANAGER_WITH_MESSAGE, exported="boundary"
    )
    consumer = (
        "from arbitrary import boundary as hold\n"
        "def use(options):\n"
        "    with hold(ValueError, **options) as info:\n"
        "        raise ValueError('needle')\n"
    )
    tree, context, _ = _populate(tmp_path, consumer, dist=dist)
    reference, _ = _reference(context, tree)

    assert isinstance(reference, ContextManagerResolutionGapV1), reference
    assert reference.target_symbol == "python:arbitrary.boundary"
    # The provider body fails before actual binding, so the prospective
    # ``incomplete-call-actuals`` terminal is not observable yet.  Pin the
    # earlier owner rather than pretending the **kwargs layer executed.
    assert reference.kind == "source-body-gap"
    assert "CallSiteSugar at arbitrary/manager.py:18:11" in reference.detail
    assert (
        "source call definition is not this call's exact typed occurrence"
        in reference.detail
    )


def test_shadowed_imported_name_manager_is_not_authorized(tmp_path: Path):
    """A nearby import cannot authorize a parameter-shadowed manager call."""
    dist = _distribution(
        tmp_path, _ASSERTION_MANAGER_WITH_MESSAGE, exported="boundary"
    )
    consumer = (
        "from arbitrary import boundary\n"
        "def use(boundary):\n"
        "    with boundary(ValueError, match='needle') as info:\n"
        "        raise ValueError('needle')\n"
    )
    _, context, _ = _populate(tmp_path, consumer, dist=dist)

    assert context.source_derived_contract_refs == {}


def test_returned_manager_pattern_mismatch_preserves_halt_without_binding(
    tmp_path: Path,
):
    """Discrimination: message mismatch keeps the identical halt unbound."""
    dist = _distribution(
        tmp_path, _ASSERTION_MANAGER_WITH_MESSAGE, exported="boundary"
    )
    consumer = (
        "import arbitrary\n"
        "def use():\n"
        "    pattern = 'needle'\n"
        "    with arbitrary.boundary(ValueError, match=pattern) as info:\n"
        "        raise ValueError('different')\n"
    )
    tree, context, _ = _populate(tmp_path, consumer, dist=dist)
    reference, node = _reference(context, tree)

    assert isinstance(reference, SourceDerivedContextManagerRefV1), reference
    assert isinstance(reference.semantics, EffectBoundarySemanticsV1)
    assert isinstance(
        reference.semantics.message_pattern_operand,
        OptionalFormalArgumentProjectionV1,
    )

    sugar = node.sugar()
    exits = outcome_to_exitset(sugar.desugar())
    halted = [face for face in exits.exits if isinstance(face, Halted)]
    assert halted, exits.exits
    # Complement / mismatch: original halt retained, no excinfo binding.
    assert all(_observed_binding(face) is None for face in halted)
    assert any(
        getattr(face.effect, "exception_name", None) == "ValueError" for face in halted
    )
    # Pattern obligation still present on the sugar (not collapsed to None).
    assert isinstance(
        sugar.semantics.message_pattern_operand, OptionalFormalArgumentProjectionV1
    )


def test_direct_and_returned_twins_share_message_operand_and_binding(
    tmp_path: Path,
):
    """Direct Boundary(...) and make_boundary(...) twins agree on face + outcome."""
    direct_root = tmp_path / "direct"
    returned_root = tmp_path / "returned"
    direct_root.mkdir()
    returned_root.mkdir()
    dist_direct = _distribution(direct_root, _ASSERTION_MANAGER, exported="boundary")
    dist_returned = _distribution(
        returned_root, _ASSERTION_MANAGER, exported="make_boundary"
    )

    direct_consumer = (
        "import arbitrary\n"
        "def use():\n"
        "    with arbitrary.boundary(ValueError) as info:\n"
        "        raise ValueError('boom')\n"
    )
    returned_consumer = (
        "import arbitrary\n"
        "def use():\n"
        "    with arbitrary.make_boundary(ValueError) as info:\n"
        "        raise ValueError('boom')\n"
    )

    direct_tree, direct_ctx, _ = _populate(
        direct_root, direct_consumer, dist=dist_direct
    )
    returned_tree, returned_ctx, _ = _populate(
        returned_root, returned_consumer, dist=dist_returned
    )

    direct_ref, direct_node = _reference(direct_ctx, direct_tree)
    returned_ref, returned_node = _reference(returned_ctx, returned_tree)

    assert _message_operand(direct_ref) == _message_operand(returned_ref)
    assert isinstance(direct_ref, type(returned_ref))

    direct_sugar = direct_node.sugar()
    returned_sugar = returned_node.sugar()
    assert type(direct_sugar) is type(returned_sugar) is WithEffectBoundarySugar

    direct_exits = outcome_to_exitset(direct_sugar.desugar())
    returned_exits = outcome_to_exitset(returned_sugar.desugar())
    assert len(direct_exits.exits) == len(returned_exits.exits) == 1
    assert isinstance(direct_exits.exits[0], Completed)
    assert isinstance(returned_exits.exits[0], Completed)
    assert _observed_binding(direct_exits.exits[0]) is not None
    assert _observed_binding(returned_exits.exits[0]) is not None
    assert (
        _observed_binding(direct_exits.exits[0]).effect.exception_name
        == _observed_binding(returned_exits.exits[0]).effect.exception_name
        == "ValueError"
    )


def test_assigned_returned_manager_projects_to_same_effect_boundary(tmp_path: Path):
    """``m = make_boundary(...); with m:`` keeps the assertion contract through return.

    Full desugar of a bare Name manager still needs call-site actual projection
    (CallSiteValue). This test pins the production obligation: the *derived
    ref* after return projection must remain EffectBoundary + NoMessagePattern.
    """
    dist = _distribution(tmp_path, _ASSERTION_MANAGER)
    consumer = (
        "import arbitrary\n"
        "def use():\n"
        "    m = arbitrary.make_boundary(ValueError)\n"
        "    with m:\n"
        "        raise ValueError('boom')\n"
    )
    tree, context, _ = _populate(tmp_path, consumer, dist=dist)
    refs = list(context.source_derived_contract_refs.values())
    assert refs, "assigned returned manager left no source-derived ref"
    reference = refs[0]
    assert not isinstance(reference, ContextManagerResolutionGapV1), reference
    assert isinstance(reference, SourceDerivedContextManagerRefV1), type(reference)
    assert isinstance(reference.semantics, EffectBoundarySemanticsV1)
    assert isinstance(reference.semantics.message_pattern_operand, NoMessagePatternV1)

    node = _with_node(tree)
    sugar = node.sugar()
    assert isinstance(sugar, WithEffectBoundarySugar)
    # Name heads do not re-mint CallSiteValue; production still constructs the
    # EffectBoundary sugar from the projected ref (not a gap / resource lie).
    assert sugar.semantics is not None or sugar.boundary_faces is not None
    if isinstance(sugar.semantics, EffectBoundarySemanticsV1):
        assert isinstance(
            sugar.semantics.message_pattern_operand, NoMessagePatternV1
        )


def test_lying_wrapper_cannot_borrow_assertion_contract(tmp_path: Path):
    """Lying twin: returned ordinary resource stays out of EffectBoundary."""
    dist = _distribution(tmp_path, _LYING_WRAPPER, exported="make_boundary")
    consumer = (
        "import arbitrary\n"
        "def use():\n"
        "    with arbitrary.make_boundary(ValueError) as info:\n"
        "        raise ValueError('boom')\n"
    )
    tree, context, _ = _populate(tmp_path, consumer, dist=dist)
    reference, node = _reference(context, tree)

    if isinstance(reference, SourceDerivedContextManagerRefV1):
        assert not isinstance(reference.semantics, EffectBoundarySemanticsV1), (
            reference.semantics
        )
        # Resource path is honest; EffectBoundary must not be invented.
        assert isinstance(reference.semantics, ProtocolResourceSemanticsV1)
    else:
        # Loud gap is also honest for a non-assertion return.
        assert isinstance(reference, ContextManagerResolutionGapV1), reference

    # Construction must not produce WithEffectBoundarySugar for the lie.
    try:
        sugar = node.sugar()
    except Exception:
        return
    assert not isinstance(sugar, WithEffectBoundarySugar), type(sugar)


def test_returned_factored_dual_face_manager_preserves_both_guards(tmp_path: Path):
    """Production join: runtime-selected match=None|pattern stays factored.

    When the returned manager's receiver carries both match faces, the derived
    ref must be FactoredSourceDerivedContextManagerRefV1 with both original
    face guards — never a single sealed summary and never a generic gap.

    If caller-return projection drops the factored ref, this test stays RED and
    names the missing producer rather than reconstructing the manager locally.
    """
    # Constructor partitions when ``flag`` is undecided: match=None on one face,
    # match=pattern on the other. Soft derivation then emits both edges.
    dual = (
        "class Boundary:\n"
        "    def __init__(self, expected, match=None, flag=None):\n"
        "        self.expected = expected\n"
        "        if flag:\n"
        "            self.match = match\n"
        "        else:\n"
        "            self.match = None\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        # Undecided equality keeps soft formals path live.\n"
        "        if effect_type is None:\n"
        "            raise RuntimeError('unmet')\n"
        "        return (effect_type is self.expected) and (\n"
        "            self.match is None or effect.message == self.match\n"
        "        )\n"
        "\n"
        "def make_boundary(expected, match=None, flag=None):\n"
        "    return Boundary(expected, match, flag)\n"
    )
    dist = _distribution(tmp_path, dual)
    # Symbolic flag via undecided formal: leave flag as a bare Name parameter
    # so construction partitions. Consumer passes a formal.
    consumer = (
        "import arbitrary\n"
        "def use(flag):\n"
        "    with arbitrary.make_boundary(ValueError, 'needle', flag) as info:\n"
        "        raise ValueError('needle')\n"
    )
    tree, context, _ = _populate(tmp_path, consumer, dist=dist)
    reference, node = _reference(context, tree)

    if isinstance(reference, FactoredSourceDerivedContextManagerRefV1):
        names = _face_guard_names(reference)
        operands = _message_operand(reference)
        assert NoMessagePatternV1() in operands
        assert any(
            isinstance(op, OptionalFormalArgumentProjectionV1) for op in operands
        )
        sugar = node.sugar()
        assert isinstance(sugar, WithEffectBoundarySugar)
        assert sugar.boundary_faces is not None
        sugar_ops = {
            face.value.message_pattern_operand
            for face in sugar.boundary_faces.exits
            if isinstance(face, Completed)
        }
        assert sugar_ops == operands
        assert sugar.observation_slot_id is not None
        # Both original face identities ride the sugar.
        assert len(sugar._guarded_semantics()) == 2
        return

    # Production path did not preserve factored faces. Stay RED with a precise
    # handoff — do not reconstruct the manager or inject a synthetic factored ref.
    detail = {
        "reference_type": type(reference).__name__,
        "kind": getattr(reference, "kind", None),
        "detail": getattr(reference, "detail", None),
        "semantics_type": type(getattr(reference, "semantics", None)).__name__,
        "message_operand": (
            type(getattr(getattr(reference, "semantics", None), "message_pattern_operand", None)).__name__
            if isinstance(reference, SourceDerivedContextManagerRefV1)
            else None
        ),
    }
    pytest.fail(
        "MISSING PRODUCER: returned dual-face assertion manager lost factored "
        "message-pattern faces before With consumption.\n"
        f"  observed reference: {detail}\n"
        "  expected: FactoredSourceDerivedContextManagerRefV1 with both "
        "NoMessagePatternV1 and pattern-obligation faces under their guards\n"
        "  missing method contract: a producer that projects the returned "
        "manager's ReceiverStatePartitionValue match faces through caller "
        "return / populate into FactoredSourceDerivedContextManagerRefV1 "
        "without collapsing to one sealed summary or a generic gap\n"
        "  owned boundary: returned-manager transport after construct_manager_behavior "
        "+ derive_manager_summary soft dual-face emission; not local reconstruction"
    )
