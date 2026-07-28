"""Returned / assigned resource managers construct through the one With algebra.

A returned resource is a factory call that yields an object with source-visible
``__enter__`` / ``__exit__``.  The consumer may write that call directly
(``with make_guard(x):``) or assign once and consume the Name
(``m = make_guard(x); with m:``).  Both spellings must project to the same
reaching call, install a ``SourceDerivedContextManagerRefV1`` with
``ProtocolResourceSemanticsV1``, and construct ``WithSourceResourceSugar`` so
``ExitSet.and_exit`` runs ``__exit__`` over every outgoing body edge.

Fixture-supplied formals (``def use(resource): with resource:``) have no local
acquisition call.  Their obligation is the formal coordinate
(``FixtureSuppliedResourceObligationV1``); without sealed actual-value
testimony the With stays a typed resolution gap — never a silent dissolve and
never a second algebra.
"""

from __future__ import annotations

import csv
import importlib.metadata
from dataclasses import replace
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    ProtocolResourceSemanticsV1,
    ReturnTruthinessDispositionV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    NativeProtocolSlot,
    SourceDerivedContextManagerRefV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.fixture_resource_obligation import (
    FixtureSuppliedResourceObligationV1,
)
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
from sugar_lift_py_tests.sugar.resource_coord_sugar import (
    ExitTracebackRefSugar,
    ExitTypeRefSugar,
    ExitValueRefSugar,
    ManagerRefSugar,
)
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_summary_derivation import (
    _projected_manager_call_uses,
    populate_source_derived_resource_refs,
)
from sugar_source_tree.tree import SourceFile

_GUARD_SOURCE = (
    "class Guard:\n"
    "    def __init__(self, marker):\n"
    "        self.marker = marker\n"
    "    def __enter__(self):\n"
    "        return self.marker\n"
    "    def __exit__(self, effect_type, effect, traceback):\n"
    "        return False\n"
    "\n"
    "def make_guard(marker):\n"
    "    return Guard(marker)\n"
)


def _source_resource(**kwargs):
    manager_slot = kwargs["manager_slot_id"]
    face = kwargs["exit_face_id"]
    enter_definition = SourceFragmentCoordinateV1(
        "blake3-512:" + "e" * 128, 1, 0, 1, 1
    )
    exit_definition = SourceFragmentCoordinateV1(
        "blake3-512:" + "x" * 128, 2, 0, 2, 1
    )
    return WithSourceResourceSugar(
        enter=MethodCallSugar(
            receiver=ManagerRefSugar(slot_id=manager_slot, site=None),
            name="__enter__",
            args=(),
            native_definition_coordinate=enter_definition,
            site=None,
        ),
        exit=MethodCallSugar(
            receiver=ManagerRefSugar(slot_id=manager_slot, site=None),
            name="__exit__",
            args=(
                ExitTypeRefSugar(face_id=face, site=None),
                ExitValueRefSugar(face_id=face, site=None),
                ExitTracebackRefSugar(face_id=face, site=None),
            ),
            native_definition_coordinate=exit_definition,
            site=None,
        ),
        enter_definition=enter_definition,
        exit_definition=exit_definition,
        **kwargs,
    )


def _distribution(root: Path, source: str, *, exported: str = "make_guard"):
    package = root / "arbitrary"
    package.mkdir()
    (package / "__init__.py").write_text(
        f"from arbitrary.manager import {exported}\n", encoding="utf-8"
    )
    (package / "manager.py").write_text(source, encoding="utf-8")
    metadata = root / "arbitrary_dist-1.0.dist-info"
    metadata.mkdir()
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


def _tree(root: Path, consumer: str, *, dist):
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


def _with_chain(sugar):
    chain = []

    def walk(node):
        if isinstance(
            node, (WithSourceResourceSugar, WithResourceSugar, WithEffectBoundarySugar)
        ):
            chain.append(node)
            for child in getattr(node, "body", ()) or ():
                walk(child)
            return
        for field in ("body", "statements", "entries"):
            for child in getattr(node, field, ()) or ():
                walk(child)

    walk(sugar)
    return chain


class _FixedSugar(Sugar):
    def __init__(self, outcome, *, probe=None):
        self._outcome = outcome
        self._probe = probe

    def desugar(self, ctx=None):
        del ctx
        if self._probe is not None:
            self._probe.append(1)
        return self._outcome

    @classmethod
    def witnesses(cls):
        return ()


class _FloorValue:
    def __init__(self, label: str):
        self.label = label

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import str_const

        return str_const(self.label)


def test_single_assigned_returned_resource_projects_reaching_call(tmp_path: Path):
    """LAW: ``m = make_guard(x); with m:`` projects the Name to the assignment call."""
    dist = _distribution(tmp_path, _GUARD_SOURCE)
    consumer = (
        "from arbitrary import make_guard\n"
        "def f(x):\n"
        "    m = make_guard(x)\n"
        "    with m:\n"
        "        pass\n"
        "    return x\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    projected = _projected_manager_call_uses(tree)
    rows = sorted(
        (call.line_col_span().start_line, coordinate.start_line, coordinate.start_col)
        for coordinate, call, _exit in projected.values()
    )
    assert rows == [(3, 4, 9)]


def test_discrimination_single_assigned_is_not_vacuous_empty(tmp_path: Path):
    """BITE: a projection that still ignored single-item Names would yield []."""
    dist = _distribution(tmp_path, _GUARD_SOURCE)
    del dist
    consumer = (
        "from arbitrary import make_guard\n"
        "def f(x):\n"
        "    m = make_guard(x)\n"
        "    with m:\n"
        "        pass\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    with pytest.raises(AssertionError):
        assert _projected_manager_call_uses(tree) == {}


def test_single_assigned_returned_resource_constructs_with_source_resource(
    tmp_path: Path,
):
    """Truthful: assigned returned resource installs ProtocolResource and constructs."""
    dist = _distribution(tmp_path, _GUARD_SOURCE)
    consumer = (
        "from arbitrary import make_guard\n"
        "def f(x):\n"
        "    m = make_guard(x)\n"
        "    with m:\n"
        "        raise ValueError('boom')\n"
        "    return x\n"
    )
    tree, context, _ = _tree(tmp_path, consumer, dist=dist)
    refs = list(context.source_derived_contract_refs.values())
    assert len(refs) == 1
    assert isinstance(refs[0], SourceDerivedContextManagerRefV1)
    assert isinstance(refs[0].semantics, ProtocolResourceSemanticsV1)

    with_node = next(node for node in tree.nodes() if node.kind == "With")
    sugar = with_node.sugar()
    assert isinstance(sugar, WithSourceResourceSugar)

    faces = sugar.desugar().exits
    assert any(
        isinstance(face, Halted)
        and getattr(face.effect, "exception_name", None) == "ValueError"
        for face in faces
    ), faces


def test_direct_call_returned_resource_still_constructs(tmp_path: Path):
    """Direct ``with make_guard(x):`` remains the authoritative non-assigned twin."""
    dist = _distribution(tmp_path, _GUARD_SOURCE)
    consumer = (
        "from arbitrary import make_guard\n"
        "def f(x):\n"
        "    with make_guard(x):\n"
        "        raise ValueError('boom')\n"
        "    return x\n"
    )
    tree, context, _ = _tree(tmp_path, consumer, dist=dist)
    assert any(
        isinstance(ref, SourceDerivedContextManagerRefV1)
        and isinstance(ref.semantics, ProtocolResourceSemanticsV1)
        for ref in context.source_derived_contract_refs.values()
    )
    sugar = next(node for node in tree.nodes() if node.kind == "With").sugar()
    assert isinstance(sugar, WithSourceResourceSugar)


def test_authenticated_pandas_303_get_handle_is_real_resource_reproducer():
    """Pinned pandas site: source IOHandles enter/exit around frame output."""
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

    corpus = authenticated_pandas_corpus()
    frame_source = (corpus.root / "core/frame.py").read_text(encoding="utf-8")
    manager_source = (corpus.root / "io/common.py").read_text(encoding="utf-8")

    assert frame_source.splitlines()[2987].strip().startswith("with get_handle(")
    assert "class IOHandles" in manager_source
    assert (
        "def __enter__(self) -> IOHandles[AnyStr]:\n        return self"
        in manager_source
    )
    assert "def __exit__(\n        self," in manager_source
    assert "    ) -> None:\n        self.close()" in manager_source


def test_real_option_context_coordinates_drive_every_resource_lifecycle_face():
    """The producer's two real coordinates are the sole lifecycle authority."""
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    corpus = authenticated_pandas_corpus()
    root = corpus.root.parent
    path = root / "pandas/tests/io/formats/test_ipython_compat.py"
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = open_source_file_for_construction(
        path, root=root, construction_context=context, populate_derived=False
    )
    populate_source_derived_resource_refs(tree, root=root, path=path)
    with_node = next(
        node
        for node in tree.nodes()
        if node.kind == "With" and node.line_col_span().start_line == 25
    )
    receiver = next(
        coordinate
        for coordinate in context.source_manager_provider_calls
        if coordinate.start_line == 25
    )
    refs = context.contract_refs
    enter_definition = refs.require_native_definition(
        receiver, NativeProtocolSlot.CONTEXT_ENTER
    )
    exit_definition = refs.require_native_definition(
        receiver, NativeProtocolSlot.CONTEXT_EXIT
    )
    assert isinstance(enter_definition, SourceFragmentCoordinateV1)
    assert isinstance(exit_definition, SourceFragmentCoordinateV1)
    assert enter_definition != exit_definition

    class RecordingDefinitionDoor:
        def __init__(self, delegate):
            self.delegate = delegate
            self.calls = []

        def __getattr__(self, name):
            return getattr(self.delegate, name)

        def require_native_definition(self, use_site, slot):
            self.calls.append((use_site, slot))
            return self.delegate.require_native_definition(use_site, slot)

    recording = RecordingDefinitionDoor(refs)
    object.__setattr__(context, "contract_refs", recording)
    resource = with_node.sugar()

    assert isinstance(resource, WithSourceResourceSugar)
    assert recording.calls == [
        (receiver, NativeProtocolSlot.CONTEXT_ENTER),
        (receiver, NativeProtocolSlot.CONTEXT_EXIT),
    ]
    assert resource.enter.native_definition_coordinate == enter_definition
    assert resource.exit.native_definition_coordinate == exit_definition

    completed = replace(
        resource,
        body=(_FixedSugar(Complete(BlockValue((), can_fall_through=True))),),
    ).desugar()
    returned = replace(
        resource,
        body=(
            _FixedSugar(
                Complete(
                    BlockValue(
                        (ReturnValue(TermValue(7)),), can_fall_through=False
                    )
                )
            ),
        ),
    ).desugar()
    effect = RaiseEffect(exception_name="ValueError", occurrence="consumer.py:26:8")
    halted = replace(
        resource,
        body=(_FixedSugar(Incomplete(effect)),),
    ).desugar()

    assert any(isinstance(face, Completed) for face in completed.exits)
    assert any(
        isinstance(entry, ReturnValue)
        for face in returned.exits
        if isinstance(face, Completed)
        for entry in face.value.contribution()
    )
    assert any(
        isinstance(face, Halted) and face.effect is effect for face in halted.exits
    )


def test_real_option_context_published_ref_selects_source_resource_at_construction():
    """The closed generator-resource ref outranks the legacy generator path."""
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    corpus = authenticated_pandas_corpus()
    root = corpus.root.parent
    path = root / "pandas/tests/io/formats/test_ipython_compat.py"
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = open_source_file_for_construction(
        path, root=root, construction_context=context, populate_derived=False
    )
    populate_source_derived_resource_refs(tree, root=root, path=path)
    with_node = next(
        node
        for node in tree.nodes()
        if node.kind == "With" and node.line_col_span().start_line == 25
    )
    receiver = next(
        coordinate
        for coordinate in context.source_manager_provider_calls
        if coordinate.start_line == 25
    )
    refs = context.contract_refs
    enter_definition = refs.require_native_definition(
        receiver, NativeProtocolSlot.CONTEXT_ENTER
    )
    exit_definition = refs.require_native_definition(
        receiver, NativeProtocolSlot.CONTEXT_EXIT
    )

    class RecordingDefinitionDoor:
        def __init__(self, delegate):
            self.delegate = delegate
            self.calls = []

        def __getattr__(self, name):
            return getattr(self.delegate, name)

        def require_native_definition(self, use_site, slot):
            self.calls.append((use_site, slot))
            return self.delegate.require_native_definition(use_site, slot)

    recording = RecordingDefinitionDoor(refs)
    object.__setattr__(context, "contract_refs", recording)

    resource = with_node.sugar()

    assert isinstance(resource, WithSourceResourceSugar)
    assert recording.calls == [
        (receiver, NativeProtocolSlot.CONTEXT_ENTER),
        (receiver, NativeProtocolSlot.CONTEXT_EXIT),
    ]
    assert resource.enter.native_definition_coordinate == enter_definition
    assert resource.exit.native_definition_coordinate == exit_definition


@pytest.mark.parametrize("manager_name", ("borrowed_state", "temporary_setting"))
def test_renamed_source_generator_resources_use_the_same_closed_factory_arm(
    tmp_path: Path, manager_name: str
):
    """Selection follows the published ref type, never a manager spelling."""
    implementation = (
        "from contextlib import contextmanager\n\n"
        "@contextmanager\n"
        f"def {manager_name}(value):\n"
        "    try:\n"
        "        yield value\n"
        "    finally:\n"
        "        release(value)\n"
    )
    dist = _distribution(tmp_path, implementation, exported=manager_name)
    tree, context, _ = _tree(
        tmp_path,
        f"from arbitrary import {manager_name}\n"
        f"with {manager_name}(7) as entered:\n"
        "    observed = entered\n",
        dist=dist,
    )
    with_node = next(node for node in tree.nodes() if node.kind == "With")
    receiver = next(iter(context.source_manager_provider_calls))

    class RecordingDefinitionDoor:
        def __init__(self, delegate):
            self.delegate = delegate
            self.calls = []

        def __getattr__(self, name):
            return getattr(self.delegate, name)

        def require_native_definition(self, use_site, slot):
            self.calls.append((use_site, slot))
            return self.delegate.require_native_definition(use_site, slot)

    recording = RecordingDefinitionDoor(context.contract_refs)
    object.__setattr__(context, "contract_refs", recording)

    resource = with_node.substitute({}).sugar()

    assert isinstance(resource, WithSourceResourceSugar)
    assert recording.calls == [
        (receiver, NativeProtocolSlot.CONTEXT_ENTER),
        (receiver, NativeProtocolSlot.CONTEXT_EXIT),
    ]
    assert resource.enter.native_definition_coordinate == resource.enter_definition
    assert resource.exit.native_definition_coordinate == resource.exit_definition


def test_source_true_exit_publishes_truthiness_and_consumes_raise(tmp_path: Path):
    """Source-derived ``return True`` is suppression testimony, not a name arm."""
    implementation = _GUARD_SOURCE.replace("return False", "return True")
    dist = _distribution(tmp_path, implementation)
    consumer = (
        "from arbitrary import make_guard\n"
        "def f(x):\n"
        "    with make_guard(x):\n"
        "        raise ValueError('boom')\n"
        "    return x\n"
    )

    tree, context, _ = _tree(tmp_path, consumer, dist=dist)
    reference = next(iter(context.source_derived_contract_refs.values()))

    assert isinstance(reference.semantics, ProtocolResourceSemanticsV1)
    assert isinstance(
        reference.semantics.exit.disposition, ReturnTruthinessDispositionV1
    )
    sugar = next(node for node in tree.nodes() if node.kind == "With").sugar()
    assert isinstance(sugar, WithSourceResourceSugar)
    assert not any(
        isinstance(face, Halted)
        and getattr(face.effect, "exception_name", None) == "ValueError"
        for face in sugar.desugar().exits
    )


def test_source_undecided_exit_never_silently_swallows_raise(tmp_path: Path):
    """A source-visible symbolic return retains suppress and propagate faces."""
    implementation = _GUARD_SOURCE.replace("return False", "return self.marker")
    dist = _distribution(tmp_path, implementation)
    consumer = (
        "from arbitrary import make_guard\n"
        "def f(x):\n"
        "    with make_guard(x):\n"
        "        raise ValueError('boom')\n"
        "    return x\n"
    )

    tree, context, _ = _tree(tmp_path, consumer, dist=dist)
    reference = next(iter(context.source_derived_contract_refs.values()))

    assert isinstance(reference.semantics, ProtocolResourceSemanticsV1)
    assert isinstance(
        reference.semantics.exit.disposition, ReturnTruthinessDispositionV1
    )
    sugar = next(node for node in tree.nodes() if node.kind == "With").sugar()
    exits = sugar.desugar().exits
    assert any(isinstance(face, Completed) for face in exits)
    assert any(
        isinstance(face, Halted)
        and getattr(face.effect, "exception_name", None) == "ValueError"
        for face in exits
    )


def test_nested_assigned_resources_compose_through_one_algebra(tmp_path: Path):
    """LAW: ``with m, n:`` nests two source-derived resources; halt runs both exits.

    Nesting IS Python's multi-manager law.  Each level owns ``and_exit`` over
    every outgoing body edge, so a body halt exits the inner manager then the
    outer under NeverSuppresses without a second control model.
    """
    dist = _distribution(tmp_path, _GUARD_SOURCE)
    consumer = (
        "from arbitrary import make_guard\n"
        "def f(x):\n"
        "    m = make_guard(x)\n"
        "    n = make_guard(x)\n"
        "    with m, n:\n"
        "        raise ValueError('boom')\n"
        "    return x\n"
    )
    tree, context, _ = _tree(tmp_path, consumer, dist=dist)
    refs = [
        ref
        for ref in context.source_derived_contract_refs.values()
        if isinstance(ref, SourceDerivedContextManagerRefV1)
    ]
    assert len(refs) == 2
    assert all(isinstance(ref.semantics, ProtocolResourceSemanticsV1) for ref in refs)

    sugar = next(node for node in tree.nodes() if node.kind == "With").sugar()
    chain = _with_chain(sugar)
    assert len(chain) == 2
    assert all(isinstance(node, WithSourceResourceSugar) for node in chain)
    assert chain[1] in chain[0].body

    faces = sugar.desugar().exits
    assert any(
        isinstance(face, Halted)
        and getattr(face.effect, "exception_name", None) == "ValueError"
        for face in faces
    ), faces


def test_discrimination_nested_assigned_does_not_collapse_to_one(tmp_path: Path):
    """BITE: collapsing multi-item nesting into one resource would hide exit order."""
    dist = _distribution(tmp_path, _GUARD_SOURCE)
    consumer = (
        "from arbitrary import make_guard\n"
        "def f(x):\n"
        "    m = make_guard(x)\n"
        "    n = make_guard(x)\n"
        "    with m, n:\n"
        "        pass\n"
    )
    tree, _, _ = _tree(tmp_path, consumer, dist=dist)
    sugar = next(node for node in tree.nodes() if node.kind == "With").sugar()
    with pytest.raises(AssertionError):
        assert len(_with_chain(sugar)) == 1


def test_failure_entering_inner_assigned_resource_still_exits_outer():
    """LAW: enter-halt of the inner With is an outgoing body edge of the outer.

    Shared algebra only: outer ``and_exit`` must run; inner ``__exit__`` must not
    (the inner manager was never entered).
    """
    outer_exit, inner_exit = [], []
    halt = RaiseEffect(exception_name="OSError", occurrence="inner.py:1:0")
    inner = _source_resource(
        manager=_FixedSugar(Complete(_FloorValue("inner-mgr"))),
        protocol=_ProbeProtocol(enter=Incomplete(halt), exit_probe=inner_exit),
        summary=_never_suppresses_summary(),
        body=(),
        manager_slot_id="B",
        enter_slot_id=None,
        exit_face_id="B#exit_face",
        site=None,
    )
    outer = _source_resource(
        manager=_FixedSugar(Complete(_FloorValue("outer-mgr"))),
        protocol=_ProbeProtocol(
            enter=Complete(_Entered(_FloorValue("entered"))),
            exit_probe=outer_exit,
        ),
        summary=_never_suppresses_summary(),
        body=(inner,),
        manager_slot_id="A",
        enter_slot_id=None,
        exit_face_id="A#exit_face",
        site=None,
    )
    out = outer.desugar()
    assert inner_exit == [], "inner was never entered"
    assert outer_exit == [1], "outer __exit__ must run on inner enter-halt"
    assert any(
        isinstance(face, Halted) and face.effect == halt for face in out.exits
    ), out.exits


def test_discrimination_outer_exit_is_not_skipped_on_enter_halt():
    """BITE: completion-only exit would leave the outer exit probe empty."""
    outer_exit, inner_exit = [], []
    halt = RaiseEffect(exception_name="OSError", occurrence="inner.py:1:0")
    inner = _source_resource(
        manager=_FixedSugar(Complete(_FloorValue("inner-mgr"))),
        protocol=_ProbeProtocol(enter=Incomplete(halt), exit_probe=inner_exit),
        summary=_never_suppresses_summary(),
        body=(),
        manager_slot_id="B",
        enter_slot_id=None,
        exit_face_id="B#exit_face",
        site=None,
    )
    outer = _source_resource(
        manager=_FixedSugar(Complete(_FloorValue("outer-mgr"))),
        protocol=_ProbeProtocol(
            enter=Complete(_Entered(_FloorValue("entered"))),
            exit_probe=outer_exit,
        ),
        summary=_never_suppresses_summary(),
        body=(inner,),
        manager_slot_id="A",
        enter_slot_id=None,
        exit_face_id="A#exit_face",
        site=None,
    )
    outer.desugar()
    with pytest.raises(AssertionError):
        assert outer_exit == []


def test_fixture_supplied_formal_manager_stays_typed_loud_without_actual(
    tmp_path: Path,
):
    """Fixture formal as manager: no local acquisition call → typed gap.

    The formal coordinate still mints a fixture-supplied obligation.  Construction
    of enter/exit requires sealed actual-value testimony the frame does not
    contain, so With refuses rather than inventing a local manager.
    """
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.panic import SourceTreePanic

    # Obligation minting uses a body-free formal frame (no With construction).
    obligation_src = tmp_path / "formal_only.py"
    obligation_src.write_text(
        "def use(resource):\n    return resource\n", encoding="utf-8"
    )
    frame = next(
        SourceFile(path_source(str(obligation_src))).functions()
    ).source_visible_call_frame()
    obligation = FixtureSuppliedResourceObligationV1.mint(frame.formal_coordinates[0])
    assert obligation.kind == "fixture-supplied-resource-obligation"
    assert obligation.formal_coordinate_cid == frame.formal_coordinates[0].cid

    consumer = (
        "def use(resource):\n"
        "    with resource:\n"
        "        raise ValueError('boom')\n"
        "    return resource\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(tree, root=tmp_path, path=path)
    assert context.source_derived_contract_refs == {}
    assert _projected_manager_call_uses(tree) == {}

    with_node = next(node for node in tree.nodes() if node.kind == "With")
    with pytest.raises(SourceTreePanic):
        with_node.sugar()


def test_undecided_rebinding_blocks_single_assigned_resource(tmp_path: Path):
    """Lying twin: rebinding the Name away from the acquired call stays unprojected."""
    consumer = (
        "from arbitrary import make_guard\n"
        "def f(x, undecided):\n"
        "    m = make_guard(x)\n"
        "    m = undecided\n"
        "    with m:\n"
        "        pass\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    assert _projected_manager_call_uses(tree) == {}


# ---------------------------------------------------------------------------
# Probe protocol / summaries for the pure ExitSet algebra twins above
# ---------------------------------------------------------------------------


class _Entered:
    def __init__(self, enter_value):
        self.enter_value = enter_value


class _ProbeProtocol:
    def __init__(self, *, enter, exit_probe=None):
        self._enter = enter
        self._exit_probe = exit_probe

    def enter_resource_outcome(self, ctx=None):
        del ctx
        return self._enter

    def exit_outcome_for(self, entered, ctx=None):
        del entered, ctx
        if self._exit_probe is not None:
            self._exit_probe.append(1)
        from sugar_lift_py_tests.floor import BlockValue

        return Complete(BlockValue((), can_fall_through=True))


def _never_suppresses_summary():
    from types import SimpleNamespace

    from sugar_lift_py_tests.context_manager_contract import NeverSuppresses

    return SimpleNamespace(
        semantics=SimpleNamespace(exit=SimpleNamespace(disposition=NeverSuppresses()))
    )
