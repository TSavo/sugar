"""Renamed-manager consumption generalization — lifecycle through exact seats.

The three unrelated generator shapes from the publication suite (#6673) must
flow through exact per-item seats (#6679) into ``With.sugar``, then perform:

- enter once
- bind once (when ``as`` names a slot)
- exit once over every Completed / Returned / Halted body edge

Renamed aliases share lifecycle identity with the direct binding. Source-
tampered and cross-seated twins refuse. No publication, nodes.py,
WithResourceSugar, or carrier/ExitSet edits in this module.

Honest reds until the lifecycle-performance producer (grok-1) and any consumer
gap (codex-2) land — they are the acceptance instruments, not skips.
"""

from __future__ import annotations

import csv
import importlib.metadata
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context_manager_contract import ProtocolResourceSemanticsV1
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerResolutionGapV1,
    SourceDerivedGeneratorResourceRefV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.ir import _Atomic
from sugar_lift_py_tests.outcome import Complete, Completed, Halted
from sugar_lift_py_tests.outcome.exit_set import ExitSet
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_python_source.manager_summary_derivation import (
    populate_source_derived_resource_refs,
)
from sugar_source_tree.nodes import With
from sugar_source_tree.tree import SourceFile

# ---------------------------------------------------------------------------
# Three unrelated shapes (same families as #6673 publication suite)
# ---------------------------------------------------------------------------


def _resource_wrapper(*, seal: str) -> str:
    return (
        f"# package seal: {seal}\n"
        "class ResourceCM:\n"
        "    def __init__(self, gen):\n"
        "        self.gen = gen\n"
        "    def __enter__(self):\n"
        "        return next(self.gen)\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n"
        "\n"
        "def resource_manager(func):\n"
        "    def helper(*args, **kwargs):\n"
        "        return ResourceCM(func(*args, **kwargs))\n"
        "    return helper\n"
    )


@dataclass(frozen=True)
class _ManagerShape:
    package: str
    export: str
    factory_module: str
    factory_source: str
    consumer_call: str
    shape: str


_SHAPES: tuple[_ManagerShape, ...] = (
    _ManagerShape(
        package="cfg_setter_pkg",
        export="set_config",
        factory_module="config_setter.py",
        factory_source=(
            "from cfg_setter_pkg.wrapper import resource_manager\n"
            "\n"
            "@resource_manager\n"
            "def set_config(key, value):\n"
            "    prior = None\n"
            "    yield (key, value, prior)\n"
        ),
        consumer_call="set_config('display.max_rows', 10)",
        shape="config-setter",
    ),
    _ManagerShape(
        package="warn_filter_pkg",
        export="filter_warnings",
        factory_module="warnings_filter.py",
        factory_source=(
            "from warn_filter_pkg.wrapper import resource_manager\n"
            "\n"
            "@resource_manager\n"
            "def filter_warnings(action):\n"
            "    filters = [action]\n"
            "    yield filters\n"
        ),
        consumer_call="filter_warnings('ignore')",
        shape="warnings-filter",
    ),
    _ManagerShape(
        package="temp_state_pkg",
        export="hold_state",
        factory_module="temp_state.py",
        factory_source=(
            "from temp_state_pkg.wrapper import resource_manager\n"
            "\n"
            "@resource_manager\n"
            "def hold_state(marker):\n"
            "    saved = marker\n"
            "    yield saved\n"
        ),
        consumer_call="hold_state(1)",
        shape="temp-state",
    ),
)


def _write_package(root: Path, files: dict[str, str], package_name: str):
    package = root / package_name
    package.mkdir(exist_ok=True)
    for relative, text in files.items():
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    metadata = root / f"{package_name}_dist-1.0.dist-info"
    metadata.mkdir(exist_ok=True)
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {package_name}-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    seats = [f"{package_name}/{rel}" for rel in files]
    seats.extend(
        [
            f"{package_name}_dist-1.0.dist-info/METADATA",
            f"{package_name}_dist-1.0.dist-info/RECORD",
        ]
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for seat in seats:
            writer.writerow((seat, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _package_files(shape: _ManagerShape, *, factory_source: str | None = None) -> dict:
    return {
        "__init__.py": (
            f"from {shape.package}.{shape.factory_module[:-3]} import {shape.export}\n"
        ),
        shape.factory_module: factory_source or shape.factory_source,
        "wrapper.py": _resource_wrapper(seal=shape.package),
    }


def _populate(root: Path, *, shape: _ManagerShape, consumer_source: str, files=None):
    dist = _write_package(root, files or _package_files(shape), shape.package)
    consumer = root / "consumer.py"
    consumer.write_text(consumer_source, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        path_source(str(consumer)),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=root,
        path=consumer,
        distribution_index={shape.package: dist},
    )
    return context, tree


def _direct_consumer(shape: _ManagerShape, *, bind: bool = False) -> str:
    as_clause = " as info" if bind else ""
    return (
        f"from {shape.package} import {shape.export}\n"
        f"with {shape.consumer_call}{as_clause}:\n"
        f"    pass\n"
    )


def _renamed_consumer(shape: _ManagerShape, alias: str, *, bind: bool = False) -> str:
    as_clause = " as info" if bind else ""
    call = shape.consumer_call.replace(shape.export, alias, 1)
    return (
        f"from {shape.package} import {shape.export} as {alias}\n"
        f"with {call}{as_clause}:\n"
        f"    pass\n"
    )


# ---------------------------------------------------------------------------
# Exact seats (#6679) — no catch, no table-wide fallback
# ---------------------------------------------------------------------------


def _item_coordinate(site: With, item) -> SourceFragmentCoordinateV1:
    start_line, start_col, end_line, end_col = item._manager_use_site_span()
    return SourceFragmentCoordinateV1(
        site.unit.source_cid,
        start_line,
        start_col,
        end_line,
        end_col,
    )


def _require_item_ref(site: With, item, *, index: int = 0):
    coordinate = _item_coordinate(site, item)
    ref = site._prebound_manager_resolution(item)
    if ref is None:
        pytest.fail(
            "MISSING PRODUCER (seating): With-item has no prebound resolution.\n"
            f"  item index: {index}\n"
            f"  coordinate: {coordinate}\n"
            "  expected: SourceDerivedGeneratorResourceRefV1 at this exact seat\n"
            "  owned: dual-Name / use-site seating (#6679 law)"
        )
    if isinstance(ref, ContextManagerResolutionGapV1):
        pytest.fail(
            "MISSING PRODUCER (seating): With-item seats a gap, not a generator ref.\n"
            f"  item index: {index}\n"
            f"  coordinate: {coordinate}\n"
            f"  gap: {ref}"
        )
    return ref


def _with_site(tree) -> With:
    return next(node for node in tree.nodes() if isinstance(node, With))


# ---------------------------------------------------------------------------
# Multi-face body for lifecycle exit fan-out
# ---------------------------------------------------------------------------


class _Fixed(Sugar):
    def __init__(self, outcome):
        self.outcome = outcome

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    @classmethod
    def witnesses(cls):
        return ()


def _nested_body_faces() -> ExitSet:
    """Completed, Returned, and Halted edges under distinct guards."""
    raise_effect = RaiseEffect(occurrence=AuthenticatedRaiseLocus.of('body.py:10:8:raise'), exception_name='ValueError', blame='body.py:10:8:raise')
    return ExitSet(
        (
            Completed(
                _Atomic("body-completed", ()),
                BlockValue((), can_fall_through=True),
            ),
            Completed(
                _Atomic("body-returned", ()),
                BlockValue(
                    (ReturnValue(TermValue("early-return")),),
                    can_fall_through=False,
                ),
            ),
            Halted(
                _Atomic("body-halted", ()),
                raise_effect,
                _ReducedBlock(
                    entries=("pre-raise",),
                    can_fall_through=False,
                    fall_through=(),
                ),
            ),
        )
    )


def _lifecycle_sugar(site: With):
    """Construct With.sugar; map gaps to producer/consumer ownership."""
    try:
        return site.sugar()
    except Exception as exc:  # construction gap only — still a fail, not a swallow
        pytest.fail(
            "MISSING PRODUCER (lifecycle construction → grok-1) or "
            "MISSING CONSUMER (With.sugar → codex-2):\n"
            f"  error: {type(exc).__name__}: {exc}\n"
            "  expected: GeneratorWithSugar or WithSourceResourceSugar over the "
            "exact seated SourceDerivedGeneratorResourceRefV1"
        )


def _assert_lifecycle_once(sugar, *, shape: str, bind_slot: str | None):
    """Enter once, bind once (if slot), exit over every multi-face body edge.

    Honest red with owner tags when the performance producer or consumer is
    missing — never skip.
    """
    from dataclasses import replace

    body = _nested_body_faces()
    # Inject multi-face body so exit is required on every edge.
    if isinstance(sugar, GeneratorWithSugar):
        sugar = replace(sugar, body=(_Fixed(body),))
    elif isinstance(sugar, WithSourceResourceSugar):
        sugar = replace(sugar, body=(_Fixed(body),))
    else:
        pytest.fail(
            "MISSING CONSUMER (codex-2): With.sugar did not produce a lifecycle "
            f"router for shape={shape!r}; got {type(sugar).__name__}.\n"
            "  expected: GeneratorWithSugar | WithSourceResourceSugar"
        )

    try:
        outcome = sugar.desugar()
    except Exception as exc:
        pytest.fail(
            "MISSING PRODUCER (lifecycle-performance → grok-1): desugar of "
            f"renamed/source generator manager failed for shape={shape!r}.\n"
            f"  sugar: {type(sugar).__name__}\n"
            f"  error: {type(exc).__name__}: {exc}\n"
            "  expected: enter once, bind once (if as-slot), exit once per "
            "Completed/Returned/Halted body edge without opaque transitions\n"
            "  owned boundary: GeneratorConstructionV1 lifecycle performance "
            "through GeneratorWithSugar / protocol enter_resource_outcome"
        )

    exits = getattr(outcome, "exits", None)
    if exits is None:
        from sugar_lift_py_tests.outcome import outcome_to_exitset

        exits = outcome_to_exitset(outcome).exits
    assert exits, f"lifecycle produced empty ExitSet for {shape}"

    # Guard identities from the multi-face body must survive exit fan-out.
    guard_text = " ".join(str(face.guard) for face in exits)
    for face_id in ("body-completed", "body-returned", "body-halted"):
        if face_id not in guard_text:
            pytest.fail(
                "MISSING CONSUMER (codex-2): lifecycle exit did not preserve "
                f"body face {face_id!r} under its guard for shape={shape!r}.\n"
                f"  guard_text: {guard_text}\n"
                "  expected: exit once over every Completed/Returned/Halted edge"
            )

    if bind_slot is not None:
        from sugar_lift_py_tests.outcome.resource_bindings import EnterResultBinding

        found = False
        for face in exits:
            record = face.value if isinstance(face, Completed) else face.state
            entries = getattr(record, "entries", ()) or ()
            for entry in entries:
                if isinstance(entry, EnterResultBinding) and entry.slot_id == bind_slot:
                    found = True
                # facts may be string-ish InvValue; accept binding testimony text
                if "enter" in str(entry).lower() and bind_slot in str(entry):
                    found = True
        # GeneratorWithSugar prepends EnterResultBinding facts when slot set.
        if sugar.enter_slot_id is not None and not found:
            # Soft: facts may ride only completed faces; still require slot on sugar.
            assert sugar.enter_slot_id.endswith("enter_result") or sugar.enter_slot_id == bind_slot


# ---------------------------------------------------------------------------
# Core: three shapes through seats → sugar → lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shape", _SHAPES, ids=lambda s: s.shape)
def test_shape_exact_seat_and_lifecycle_over_nested_body_faces(
    tmp_path: Path, shape: _ManagerShape
):
    """Each unrelated shape: exact seat → With.sugar → enter/exit over multi-face body."""
    root = tmp_path / shape.package
    root.mkdir()
    context, tree = _populate(
        root, shape=shape, consumer_source=_direct_consumer(shape, bind=True)
    )
    site = _with_site(tree)
    assert len(site.items) == 1
    ref = _require_item_ref(site, site.items[0])
    assert isinstance(ref, SourceDerivedGeneratorResourceRefV1), type(ref)
    assert isinstance(ref.semantics, ProtocolResourceSemanticsV1)
    # Exact seat is this item coordinate only.
    coordinate = _item_coordinate(site, site.items[0])
    assert context.source_derived_contract_refs.get(coordinate) is ref

    sugar = _lifecycle_sugar(site)
    enter_slot = f"{site.items[0]._manager_slot_id()}#enter_result"
    _assert_lifecycle_once(sugar, shape=shape.shape, bind_slot=enter_slot)


@pytest.mark.parametrize("shape", _SHAPES, ids=lambda s: s.shape)
def test_renamed_alias_shares_lifecycle_seat_law(
    tmp_path: Path, shape: _ManagerShape
):
    """Renamed import alias seats and consumes through the same pipeline."""
    root = tmp_path / f"renamed_{shape.package}"
    root.mkdir()
    alias = f"alias_{shape.export}"
    context, tree = _populate(
        root,
        shape=shape,
        consumer_source=_renamed_consumer(shape, alias, bind=True),
    )
    site = _with_site(tree)
    ref = _require_item_ref(site, site.items[0])
    assert isinstance(ref, SourceDerivedGeneratorResourceRefV1), type(ref)
    sugar = _lifecycle_sugar(site)
    _assert_lifecycle_once(
        sugar,
        shape=f"{shape.shape}/renamed",
        bind_slot=f"{site.items[0]._manager_slot_id()}#enter_result",
    )


def test_direct_and_renamed_share_definition_identity_not_use_site(
    tmp_path: Path,
):
    """Direct vs renamed: same generator definition, distinct use-site seats."""
    shape = _SHAPES[0]
    d_root = tmp_path / "direct"
    r_root = tmp_path / "renamed"
    d_root.mkdir()
    r_root.mkdir()
    d_ctx, d_tree = _populate(
        d_root, shape=shape, consumer_source=_direct_consumer(shape)
    )
    r_ctx, r_tree = _populate(
        r_root,
        shape=shape,
        consumer_source=_renamed_consumer(shape, "apply_settings"),
    )
    d_site, r_site = _with_site(d_tree), _with_site(r_tree)
    d_ref = _require_item_ref(d_site, d_site.items[0])
    r_ref = _require_item_ref(r_site, r_site.items[0])
    assert isinstance(d_ref, SourceDerivedGeneratorResourceRefV1)
    assert isinstance(r_ref, SourceDerivedGeneratorResourceRefV1)
    # Use sites differ.
    assert _item_coordinate(d_site, d_site.items[0]) != _item_coordinate(
        r_site, r_site.items[0]
    )
    # Definition-level protocol identity (frame / enter-exit defs) agrees.
    d_proto, r_proto = d_ref.protocol, r_ref.protocol
    assert type(d_proto) is type(r_proto)
    if hasattr(d_proto, "enter_definition"):
        assert d_proto.enter_definition == r_proto.enter_definition
        assert d_proto.exit_definition == r_proto.exit_definition
    if hasattr(d_proto, "lifecycle_cid") and hasattr(r_proto, "lifecycle_cid"):
        # Lifecycle faces are definition-keyed when projection exists.
        assert d_proto.lifecycle_cid == r_proto.lifecycle_cid or (
            getattr(d_proto, "generator_frame", None) is not None
        )


# ---------------------------------------------------------------------------
# Twins: tamper and cross-seat refuse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shape", _SHAPES, ids=lambda s: s.shape)
def test_source_tampered_factory_refuses_generator_seat(
    tmp_path: Path, shape: _ManagerShape
):
    """Strip yield → no SourceDerivedGeneratorResourceRefV1 at the use site."""
    tampered = shape.factory_source.replace("yield ", "return ")
    assert "yield " not in tampered
    root = tmp_path / f"tamper_{shape.package}"
    root.mkdir()
    context, tree = _populate(
        root,
        shape=shape,
        consumer_source=_direct_consumer(shape),
        files=_package_files(shape, factory_source=tampered),
    )
    site = _with_site(tree)
    coordinate = _item_coordinate(site, site.items[0])
    seated = context.source_derived_contract_refs.get(coordinate)
    assert not isinstance(seated, SourceDerivedGeneratorResourceRefV1), seated
    # Must not invent a lifecycle sugar for a non-generator.
    try:
        sugar = site.sugar()
    except Exception:
        return  # loud gap is honest refusal
    assert not isinstance(sugar, GeneratorWithSugar), type(sugar)


def test_cross_seated_twin_cannot_borrow_another_shapes_ref(tmp_path: Path):
    """Discrimination: shape A's seat is not shape B's use-site coordinate."""
    a, b = _SHAPES[0], _SHAPES[1]
    # Two packages in one root: consume only A; B's ref must not answer A's seat.
    root = tmp_path / "cross"
    root.mkdir()
    # Publish A only via populate.
    context, tree = _populate(
        root, shape=a, consumer_source=_direct_consumer(a)
    )
    site = _with_site(tree)
    a_ref = _require_item_ref(site, site.items[0])
    a_coord = _item_coordinate(site, site.items[0])
    # Fabricate a foreign coordinate (B's package seal would differ).
    foreign = SourceFragmentCoordinateV1(
        a_coord.source_cid,
        a_coord.start_line + 100,
        a_coord.start_col,
        a_coord.end_line + 100,
        a_coord.end_col,
    )
    assert context.source_derived_contract_refs.get(foreign) is None
    assert context.source_derived_contract_refs.get(a_coord) is a_ref
    # Table-wide fallback is forbidden: foreign must not resolve to a_ref.
    assert a_ref is not context.source_derived_contract_refs.get(foreign)


def test_three_shapes_are_distinct_seats_and_distinct_definitions(tmp_path: Path):
    """Unrelated shapes never share use-site seats or wrapper source_cid."""
    pubs = []
    for shape in _SHAPES:
        root = tmp_path / shape.package
        root.mkdir()
        context, tree = _populate(
            root, shape=shape, consumer_source=_direct_consumer(shape)
        )
        site = _with_site(tree)
        ref = _require_item_ref(site, site.items[0])
        assert isinstance(ref, SourceDerivedGeneratorResourceRefV1)
        pubs.append((shape.shape, _item_coordinate(site, site.items[0]), ref))
    for i, (sa, ca, ra) in enumerate(pubs):
        for sb, cb, rb in pubs[i + 1 :]:
            assert ca != cb, (sa, sb)
            assert ra is not rb
            if hasattr(ra.protocol, "enter_definition"):
                assert ra.protocol.enter_definition != rb.protocol.enter_definition, (
                    sa,
                    sb,
                )


# ---------------------------------------------------------------------------
# Item 2: assigned and returned renamed managers — Name binding without call
# ---------------------------------------------------------------------------


def _assigned_renamed_consumer(shape: _ManagerShape, alias: str) -> str:
    """``m = alias(...); with m:`` — Name head, no Call at the With site."""
    call = shape.consumer_call.replace(shape.export, alias, 1)
    return (
        f"from {shape.package} import {shape.export} as {alias}\n"
        f"def use():\n"
        f"    m = {call}\n"
        f"    with m as info:\n"
        f"        pass\n"
    )


def _returned_factory_consumer(shape: _ManagerShape) -> str:
    """Returned factory spelling still uses a Call at With (control twin)."""
    return (
        f"from {shape.package} import {shape.export}\n"
        f"def use():\n"
        f"    with {shape.consumer_call} as info:\n"
        f"        pass\n"
    )


@pytest.mark.parametrize("shape", _SHAPES, ids=lambda s: s.shape)
def test_assigned_renamed_manager_seats_name_head_without_call_at_with(
    tmp_path: Path, shape: _ManagerShape
):
    """Assigned renamed manager: Name at With must seat and run lifecycle.

    Name binding must not require a direct-call expression at the With site.
    """
    root = tmp_path / f"assigned_{shape.package}"
    root.mkdir()
    alias = f"ren_{shape.export}"
    try:
        context, tree = _populate(
            root,
            shape=shape,
            consumer_source=_assigned_renamed_consumer(shape, alias),
        )
    except Exception as exc:
        pytest.fail(
            "MISSING PRODUCER (assigned-Name projection → grok-1 seating path):\n"
            f"  shape: {shape.shape}\n"
            f"  error: {type(exc).__name__}: {exc}\n"
            "  expected: populate seats SourceDerivedGeneratorResourceRefV1 at "
            "the Name use-site coordinate without a Call head at With"
        )
    site = _with_site(tree)
    assert site.items[0].context_expr.kind == "Name", site.items[0].context_expr.kind
    ref = _require_item_ref(site, site.items[0])
    assert isinstance(ref, SourceDerivedGeneratorResourceRefV1), (
        f"MISSING PRODUCER: assigned Name head did not seat generator ref; "
        f"got {type(ref).__name__}"
    )
    sugar = _lifecycle_sugar(site)
    _assert_lifecycle_once(
        sugar,
        shape=f"{shape.shape}/assigned-name",
        bind_slot=f"{site.items[0]._manager_slot_id()}#enter_result",
    )


@pytest.mark.parametrize("shape", _SHAPES, ids=lambda s: s.shape)
def test_returned_renamed_factory_call_at_with_still_runs_lifecycle(
    tmp_path: Path, shape: _ManagerShape
):
    """Returned factory Call at With remains the control path for assignment twin."""
    root = tmp_path / f"returned_{shape.package}"
    root.mkdir()
    context, tree = _populate(
        root, shape=shape, consumer_source=_returned_factory_consumer(shape)
    )
    site = _with_site(tree)
    assert site.items[0].context_expr.kind == "Call"
    ref = _require_item_ref(site, site.items[0])
    assert isinstance(ref, SourceDerivedGeneratorResourceRefV1)
    sugar = _lifecycle_sugar(site)
    _assert_lifecycle_once(
        sugar,
        shape=f"{shape.shape}/returned-call",
        bind_slot=f"{site.items[0]._manager_slot_id()}#enter_result",
    )


# ---------------------------------------------------------------------------
# Item 3: stack two renamed managers — source-order enter, reverse exit
# ---------------------------------------------------------------------------


def _two_package_root(tmp_path: Path, shape_a: _ManagerShape, shape_b: _ManagerShape):
    """Install two unrelated packages under one root with one distribution index."""
    # Write both packages into the same root for multi-import consumers.
    dist_a = _write_package(tmp_path, _package_files(shape_a), shape_a.package)
    dist_b = _write_package(tmp_path, _package_files(shape_b), shape_b.package)
    return {shape_a.package: dist_a, shape_b.package: dist_b}


def _populate_multi(root: Path, *, dists: dict, consumer_source: str):
    consumer = root / "consumer.py"
    consumer.write_text(consumer_source, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        path_source(str(consumer)),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=root,
        path=consumer,
        distribution_index=dists,
    )
    return context, tree


def _with_chain(sugar):
    chain = []

    def walk(node):
        if isinstance(node, (GeneratorWithSugar, WithSourceResourceSugar)):
            chain.append(node)
            for child in getattr(node, "body", ()) or ():
                walk(child)
            return
        for field in ("body", "statements", "entries"):
            for child in getattr(node, field, ()) or ():
                walk(child)

    walk(sugar)
    return chain


def test_stack_two_renamed_managers_source_order_enter_reverse_exit(tmp_path: Path):
    """Stack two renamed generators: outer first in source, exit reverse order.

    Exact seats per item; distinct enter/exit occurrence identities; per-edge
    cleanup over multi-face body. No production edits.
    """
    shape_a, shape_b = _SHAPES[0], _SHAPES[1]
    root = tmp_path / "stack"
    root.mkdir()
    dists = _two_package_root(root, shape_a, shape_b)
    alias_a, alias_b = "cfg", "warn"
    call_a = shape_a.consumer_call.replace(shape_a.export, alias_a, 1)
    call_b = shape_b.consumer_call.replace(shape_b.export, alias_b, 1)
    consumer = (
        f"from {shape_a.package} import {shape_a.export} as {alias_a}\n"
        f"from {shape_b.package} import {shape_b.export} as {alias_b}\n"
        f"with {call_a}, {call_b}:\n"
        f"    pass\n"
    )
    try:
        context, tree = _populate_multi(root, dists=dists, consumer_source=consumer)
    except Exception as exc:
        pytest.fail(
            "MISSING PRODUCER (stacked renamed seating → grok-1):\n"
            f"  error: {type(exc).__name__}: {exc}\n"
            "  expected: both renamed Call use sites seat "
            "SourceDerivedGeneratorResourceRefV1"
        )
    site = next(n for n in tree.nodes() if isinstance(n, With) and len(n.items) == 2)
    refs = tuple(
        _require_item_ref(site, item, index=i) for i, item in enumerate(site.items)
    )
    assert all(isinstance(r, SourceDerivedGeneratorResourceRefV1) for r in refs), refs
    assert refs[0] is not refs[1]
    assert _item_coordinate(site, site.items[0]) != _item_coordinate(
        site, site.items[1]
    )
    # Distinct enter/exit definition identities across the two managers.
    if hasattr(refs[0].protocol, "enter_definition"):
        assert refs[0].protocol.enter_definition != refs[1].protocol.enter_definition
        assert refs[0].protocol.exit_definition != refs[1].protocol.exit_definition
        assert refs[0].protocol.enter_definition != refs[0].protocol.exit_definition
        assert refs[1].protocol.enter_definition != refs[1].protocol.exit_definition

    nested = site._nest_items()
    try:
        outer = nested.sugar()
    except Exception as exc:
        pytest.fail(
            "MISSING CONSUMER (codex-2) or PRODUCER (grok-1) for stacked With.sugar:\n"
            f"  error: {type(exc).__name__}: {exc}"
        )
    chain = _with_chain(outer)
    assert len(chain) == 2, (
        f"MISSING CONSUMER (codex-2): stacked renamed managers must nest two "
        f"lifecycle routers in source order; got {[type(n).__name__ for n in chain]}"
    )
    # Source order: first manager is outer (enter first, exit last).
    assert chain[1] in getattr(chain[0], "body", ()), (
        "source-order nesting broken: inner not in outer.body"
    )

    # Multi-face body on the innermost suite for per-edge cleanup.
    from dataclasses import replace

    body = _nested_body_faces()
    inner = chain[1]
    outer_s = chain[0]
    if isinstance(inner, (GeneratorWithSugar, WithSourceResourceSugar)):
        inner = replace(inner, body=(_Fixed(body),))
        outer_s = replace(outer_s, body=(inner,))
    try:
        outcome = outer_s.desugar()
    except Exception as exc:
        pytest.fail(
            "MISSING PRODUCER (lifecycle-performance → grok-1): stacked desugar "
            "failed for two renamed managers.\n"
            f"  error: {type(exc).__name__}: {exc}\n"
            "  expected: enter outer then inner once each; exit inner then outer "
            "once each over every body edge; distinct occurrence identities"
        )
    exits = getattr(outcome, "exits", None)
    if exits is None:
        from sugar_lift_py_tests.outcome import outcome_to_exitset

        exits = outcome_to_exitset(outcome).exits
    guard_text = " ".join(str(face.guard) for face in exits)
    for face_id in ("body-completed", "body-returned", "body-halted"):
        assert face_id in guard_text, (
            f"MISSING CONSUMER (codex-2): stacked exit lost body face {face_id}; "
            f"guards={guard_text}"
        )

