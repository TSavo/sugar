"""ADDED laws for source-visible attribute store faces.

Does **not** delete or rewrite store ExitSet composition laws
(``test_store_outcome_composition``, unpack twins). Those five named laws
remain the dual-face instrument for undecided stores via the one undecided
attribute mutation (``undecided_attribute_mutation_faces``: completes under
its own atom, or an undetermined raise).

Python semantic law made constructible (PARTIAL):

  For ``obj.attr = value``, when the receiver runtime type is decided, project
  through Floor ``setattr`` (not the read path). Evaluate RHS then receiver
  once. Store halt preserves earlier state. Exception type originates in the
  store dispatch owner.

  A store on a formal waits on no caller's actual (#7757): it is the
  undecided store (``store_effect_sugar.undecided_attribute_mutation_faces``),
  completing under its own atom -- or where prove decides the plain
  ``__dict__`` store, for a parameter whose class is a contract input -- and
  raising something undetermined under the complement.  No carrier is
  minted.

Named seams (``test_producer_and_consumer_methods_are_the_named_seams``):

  producer: the one field store, ``ReceiverFieldStoreSugar.desugar`` /
  ``_store`` (``store_effect_sugar.attribute_mutation`` for a receiver that
  is no source instance)
  consumer: ``FloorValue.setattr`` / ``ObjectValue.setattr``

Pinned pandas 3.0.3 (line content verified on installed seat):

  ``pandas/tests/indexes/test_any_index.py:113``
  ``original_name, index.name = index.name, "foo"``
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from frame_fresh import FRAME_FRESH, fresh

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import (
    BytesValue,
    FloorValue,
    ListValue,
    NoneValue,
    ObjectField,
    ObjectMethodValue,
    ObjectValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort, make_var, str_const
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.outcome.exit_set import Halted
from sugar_lift_py_tests.floor.receiver_field_store_value import (
    ReceiverFieldStoreValue,
)
from sugar_lift_py_tests.sugar.assign_sugar import KeyedStoreSugar
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset
from sugar_lift_py_tests.sugar.receiver_field_store_sugar import (
    ReceiverFieldStoreSugar,
)
from sugar_lift_py_tests.sugar import store_effect_sugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_lift_py_tests.lift_rpc import tree_construction_context_for_workspace
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import RaiseEffect

MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)

CORPUS_RELATIVE = "pandas/tests/indexes/test_any_index.py"
CORPUS_LINE = 113
CORPUS_TEXT = 'original_name, index.name = index.name, "foo"'


def _site(tmp_path: Path):
    path = tmp_path / "attr_store.py"
    path.write_text("def f(obj, value):\n    obj.attr = value\n")
    function = next(
        SourceFile(
            workspace_path_source(str(path), root=str(tmp_path)),
            construction_context=tree_construction_context_for_workspace(tmp_path),
        ).functions()
    )
    return function.body[0].fragment


@dataclass(frozen=True)
class _ObservedSugar(Sugar):
    label: str
    value: object
    log: list[str]

    @classmethod
    def witnesses(cls):
        raise AssertionError("test helper has no witness")

    def desugar(self, ctx=None):
        del ctx
        self.log.append(self.label)
        return ExitSet.completed(self.value)


def _store(receiver, value, log, site, attr: str = "attr"):
    return ReceiverFieldStoreSugar(
        receiver=_ObservedSugar("receiver", receiver, log),
        value=_ObservedSugar("value", value, log),
        attr=attr,
        site=site,
    )


def _setattr_calls(outcome, class_name: str):
    """Every ``call:<class_name>.__setattr__(<receiver>, <name>, <value>)``
    term the completed faces' guards name: the one unanswered call a store
    on an instance naming no class is (``ObjectValue.field_store_call``)."""
    target = f"call:{class_name}.__setattr__"

    def walk(node, depth=0):
        if getattr(node, "name", None) == target:
            yield node
        if depth > 64:
            return
        for child in (
            *(getattr(node, "args", ()) or ()),
            *(getattr(node, "operands", ()) or ()),
        ):
            yield from walk(child, depth + 1)

    calls = [
        call
        for arm in outcome.exits
        if isinstance(arm, Completed)
        for call in walk(arm.guard)
    ]
    assert calls, outcome
    return calls


def _the_store_is_the_call(outcome, class_name: str, value) -> None:
    """A store on an instance naming no class: ``type(o).__setattr__``, the
    one unanswered call, two-faced and owed (#7757 H1b).  The lift decides
    neither the plain store (no completed face holds the instance with the
    field stored, no ``ReceiverFieldStoreValue``) nor a property's
    ``AttributeError`` (no halt names it); the call's halt is kept."""
    from sugar_lift_py_tests.floor.object_identity import contents_current

    assert isinstance(outcome, ExitSet), type(outcome)
    assert outcome.halts(), outcome
    for halt in outcome.halts():
        assert getattr(halt.effect, "exception_name", None) != "AttributeError", (
            halt.effect
        )
        assert "AttributeError" not in repr(
            getattr(halt.effect, "exception_type_coordinate", None)
        ), halt.effect
        assert halt.owed, halt
    for arm in outcome.exits:
        assert arm.owed, arm
        if not isinstance(arm, Completed):
            continue
        assert not isinstance(arm.value, ReceiverFieldStoreValue), arm.value
        assert not (
            isinstance(arm.value, ObjectValue)
            and contents_current(arm.value)
            and any(f.name == "name" and f.value == value for f in arm.value.fields)
        ), arm.value
    _setattr_calls(outcome, class_name)


def _formal(site) -> FormalParameterCoordinateV1:
    span = site.line_col_span
    owner = SourceFragmentCoordinateV1(
        site.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    return FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=site.source_cid,
        owner_definition_locus=owner,
        declaration_locus=owner,
        ordinal=0,
        parameter_kind="positional-or-keyword",
        declared_name="obj",
        sort=PrimitiveSort("Value"),
    )


# ---------------------------------------------------------------------------
# Named seams
# ---------------------------------------------------------------------------


def test_producer_and_consumer_methods_are_the_named_seams() -> None:
    assert hasattr(ReceiverFieldStoreSugar, "desugar")
    assert hasattr(ReceiverFieldStoreSugar, "_store")
    assert callable(store_effect_sugar.attribute_mutation)
    # One attribute door: no carrier mint and no second projection beside it.
    assert not hasattr(store_effect_sugar, "mint_setattr_named_carrier")
    assert not hasattr(store_effect_sugar, "project_setattr")
    # One field store: no effect store beside it.
    assert not hasattr(store_effect_sugar, "AttributeStoreEffectSugar")
    # A chain's or an unpack's store target is ``o.x = v``'s own statement:
    # there is no second door that stores a value reduced elsewhere.
    assert not hasattr(ReceiverFieldStoreSugar, "desugar_store")
    assert hasattr(FloorValue, "setattr")
    assert hasattr(ObjectValue, "setattr")
    assert FloorValue.setattr is not FloorValue.attribute


# ---------------------------------------------------------------------------
# Evaluate-once / left-to-right
# ---------------------------------------------------------------------------


def test_attribute_store_evaluates_rhs_and_receiver_once_in_python_order(tmp_path):
    log: list[str] = []
    receiver = ObjectValue(
        "R", (ObjectField("attr", TermValue(1)),), allocation=FRAME_FRESH
    )
    site = _site(tmp_path)
    outcome = _store(receiver, TermValue(7), log, site).desugar()

    # Python order, each operand once: the value, then the receiver.
    assert log == ["value", "receiver"]
    # Expected verdict changed (#7757 H1b, #9065): ``R`` names no class, so
    # the store is ``type(o).__setattr__``, the one unanswered call, never a
    # completion the lift decided plain.  It is handed the receiver and the
    # value evaluated above, once each; both faces are kept.
    assert outcome.halts(), outcome
    assert not any(
        isinstance(getattr(arm, "value", None), ReceiverFieldStoreValue)
        for arm in outcome.exits
    ), outcome
    owner = str(site)
    for call in _setattr_calls(outcome, "R"):
        assert call.args[1:3] == (
            StringValue("attr").to_term(owner=owner),
            TermValue(7).to_term(owner=owner),
        ), call


def test_rhs_halt_wins_before_receiver_evaluation(tmp_path):
    from sugar_lift_py_tests.effect import RaiseEffect

    log: list[str] = []

    @dataclass(frozen=True)
    class _RaisingValue(Sugar):
        def desugar(self, ctx=None):
            del ctx
            log.append("value")
            return ExitSet.halted(
                RaiseEffect(
                    exception_type_coordinate=str_const("ValueError"),
                    occurrence=AuthenticatedRaiseLocus.of("attr_store.py:2:16"),
                )
            )

        @classmethod
        def witnesses(cls):
            raise AssertionError

    store = ReceiverFieldStoreSugar(
        receiver=_ObservedSugar(
            "receiver", ObjectValue("R", (), allocation=FRAME_FRESH), log
        ),
        value=_RaisingValue(),
        attr="attr",
        site=_site(tmp_path),
    )
    outcome = store.desugar()

    assert log == ["value"]
    assert len(outcome.exits) == 1 and outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert halt.effect.exception_type_coordinate == str_const("ValueError")


# ---------------------------------------------------------------------------
# Decided faces — store path ≠ read path
# ---------------------------------------------------------------------------


def test_a_store_on_an_instance_naming_no_class_is_the_call(tmp_path):
    """No class term, so no ``python:plain_store`` guard (#7757 H1b): the
    store is the one ``type(o).__setattr__`` call, both faces kept, and the
    field is never recorded as stored."""
    receiver = ObjectValue(
        "R", (ObjectField("attr", TermValue(0)),), allocation=FRAME_FRESH
    )
    outcome = _store(receiver, TermValue(9), [], _site(tmp_path)).desugar()
    assert outcome.halts(), outcome
    for arm in outcome.exits:
        assert not isinstance(getattr(arm, "value", None), ReceiverFieldStoreValue)


def test_readable_immutable_receiver_raises_on_store(tmp_path):
    receiver = TupleValue((TermValue(1),))
    outcome = _store(receiver, TermValue(7), [], _site(tmp_path)).desugar()

    assert len(outcome.exits) == 1 and outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert halt.effect.exception_name == "AttributeError"
    assert halt.effect.producer_node_owner == "TupleValue.setattr"


@pytest.mark.parametrize(
    ("receiver", "owner"),
    (
        (StringValue("abc"), "StringValue.setattr"),
        (BytesValue(b"abc"), "BytesValue.setattr"),
    ),
)
def test_immutable_scalar_attribute_store_has_exact_owner_occurrence(
    tmp_path, receiver, owner
):
    site = _site(tmp_path)
    outcome = _store(receiver, TermValue(7), [], site).desugar()
    assert len(outcome.exits) == 1 and outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert halt.effect.exception_name == "AttributeError"
    assert halt.effect.producer_node_owner == owner
    assert halt.effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


@pytest.mark.parametrize("receiver", (StringValue("abc"), BytesValue(b"abc")))
def test_immutable_scalar_attribute_store_cannot_fabricate_completion(
    tmp_path, receiver
):
    outcome = _store(receiver, TermValue(7), [], _site(tmp_path)).desugar()
    assert outcome.completed_value() is None


def test_none_setattr_is_attribute_error_on_store_path(tmp_path):
    outcome = _store(NoneValue(), TermValue(1), [], _site(tmp_path)).desugar()
    assert len(outcome.exits) == 1 and outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert halt.effect.exception_name == "AttributeError"
    assert halt.effect.producer_node_owner == "NoneValue.setattr"


def test_list_read_path_does_not_license_list_setattr(tmp_path):
    receiver = fresh(ListValue, (TermValue(1),))
    outcome = _store(
        receiver, TermValue(7), [], _site(tmp_path), attr="append"
    ).desugar()
    assert len(outcome.exits) == 1 and outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert halt.effect.exception_name == "AttributeError"
    assert halt.effect.producer_node_owner == "ListValue.setattr"


def test_property_without_setter_is_never_a_completed_plain_store(tmp_path):
    """A getter-only property's store raises ``AttributeError`` in Python.
    The lift never decides it (#7757 H1b): the store is the call, its halt
    face kept, and the field is never recorded as stored."""
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    @dataclass(frozen=True)
    class _GetterBody(Sugar):
        def desugar(self, ctx=None):
            del ctx
            return ExitSet.completed(
                BlockValue((ReturnValue(TermValue(1)),), can_fall_through=False)
            )

        @classmethod
        def witnesses(cls):
            return ()

    receiver = ObjectValue(
        "R",
        (),
        methods=(
            ObjectMethodValue(
                name="attr",
                parameters=("self",),
                descriptor_kind="property",
            ),
        ),
        allocation=FRAME_FRESH,
    )
    outcome = _store(receiver, TermValue(7), [], _site(tmp_path)).desugar()
    assert outcome.halts(), outcome
    for arm in outcome.exits:
        assert not isinstance(getattr(arm, "value", None), ReceiverFieldStoreValue)


def test_undecided_retains_dual_face_runtime_effect(tmp_path):
    """Dual-face instrument intact — not replaced by SugarNotWritten.

    A store on a receiver whose type nothing decides, formal or not, is the
    one undecided attribute mutation (``store_effect_sugar.
    undecided_attribute_mutation_faces``, #7757 NEW-4): it completes under
    ``python:setattr.completes`` and halts with the undetermined raise under
    its complement.  Neither face is dropped."""
    outcome = _store(
        SymbolicValue(make_var("obj")), TermValue(7), [], _site(tmp_path)
    ).desugar()
    assert len(outcome.exits) == 2
    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert done.value is not None
    assert "python:setattr.completes" in repr(done.guard)
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "UndecidedSetattr"


def _undecided_store(outcome):
    """The undecided store on a formal: no carrier, one
    ``UndeterminedRaiseEffect`` halt owned by ``UndecidedSetattr``, the
    undecided member owed on the halt and on every completed face, and no
    unconditional completion."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls, unanswered_call

    assert isinstance(outcome, ExitSet), type(outcome)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "UndecidedSetattr"
    ]
    assert len(halts) == 1, outcome
    (halt,) = halts
    assert type(halt.effect) is UndeterminedRaiseEffect
    owed = unanswered_call(None, halt.effect.site)
    assert owed in owed_calls(outcome)
    assert owed in halt.owed
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome
    assert all(owed in face.owed for face in completed)
    assert outcome.completed_value() is None
    return halt


def test_formal_parameter_store_is_the_undecided_store_not_a_carrier(tmp_path):
    """A store on a formal waits on no caller's actual (#7757): the function's
    own proof holds the undecided store, its halt kept, never a
    ``setattr_named`` carrier."""
    path = tmp_path / "formal_store.py"
    path.write_text("def target(o, p):\n    o.x = p\n    return p\n")
    from sugar_lift_python_source.source_oracle import path_source

    fn = next(
        SourceFile(
            path_source(str(path)),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        ).functions()
    )
    halt = _undecided_store(fn.sugar().desugar(None))
    assert halt.state is not None


# ---------------------------------------------------------------------------
# The one attribute door on a formal receiver
# ---------------------------------------------------------------------------


def test_attribute_mutation_on_a_formal_is_the_undecided_store(tmp_path):
    """The door itself: a formal receiver's store completes under
    ``python:setattr.completes(python:setattr(<receiver>, "attr", <key>))``
    -- the receiver named, the static name carried -- and halts under its
    complement.  No carrier is minted (``mint_setattr_named_carrier`` is
    gone)."""
    site = _site(tmp_path)
    receiver = SymbolicValue(make_var("obj"), _formal(site))
    outcome = store_effect_sugar.attribute_mutation(
        "__setattr__", receiver, "attr", (TermValue(7),), site, None, unit=None
    )
    _undecided_store(outcome)
    (done,) = [face for face in outcome.exits if isinstance(face, Completed)]
    atoms = [
        node
        for node in _formula_nodes(done.guard)
        if getattr(node, "name", None) == "python:setattr.completes"
    ]
    assert len(atoms) == 1, done.guard
    (operation,) = atoms[0].args
    assert operation.name == "python:setattr"
    assert operation.args[0] == receiver.to_term(owner="test")
    assert operation.args[1] == str_const("attr")


def _formula_nodes(node, depth=0):
    """Every term and formula node in ``node``, at any depth."""
    nodes = [node]
    if depth > 64:
        return nodes
    for child in (
        *(getattr(node, "args", ()) or ()),
        *(getattr(node, "operands", ()) or ()),
    ):
        nodes.extend(_formula_nodes(child, depth + 1))
    return nodes


# ---------------------------------------------------------------------------
# Preservation
# ---------------------------------------------------------------------------


def test_store_halt_preserves_state_completed_before_it(tmp_path):
    prior = _ObservedSugar(
        "prior", BlockValue((TermValue(99),), can_fall_through=True), []
    )
    store = _store(
        TupleValue((TermValue(1),)),
        TermValue(7),
        [],
        _site(tmp_path),
    )
    outcome = reduce_block_to_exitset((prior, store), None)

    halted = [exit_ for exit_ in outcome.exits if isinstance(exit_, Halted)]
    assert len(halted) == 1
    assert TermValue(99) in halted[0].state.entries


# ---------------------------------------------------------------------------
# Lying twins
# ---------------------------------------------------------------------------


def test_property_read_does_not_license_completed_store(tmp_path):
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    @dataclass(frozen=True)
    class _GetterBody(Sugar):
        def desugar(self, ctx=None):
            del ctx
            return ExitSet.completed(
                BlockValue((ReturnValue(TermValue(1)),), can_fall_through=False)
            )

        @classmethod
        def witnesses(cls):
            return ()

    receiver = ObjectValue(
        "R",
        (),
        methods=(
            ObjectMethodValue(
                name="attr",
                parameters=("self",),
                descriptor_kind="property",
            ),
        ),
        allocation=FRAME_FRESH,
    )
    outcome = _store(receiver, TermValue(7), [], _site(tmp_path)).desugar()
    assert not (
        outcome.completed_value() is not None
        and isinstance(outcome.completed_value(), ObjectValue)
    )


def test_exception_type_originates_in_store_dispatch_not_boundary(tmp_path):
    outcome = _store(NoneValue(), TermValue(1), [], _site(tmp_path)).desugar()
    assert len(outcome.exits) == 1 and outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert halt.effect.exception_name == "AttributeError"
    assert halt.effect.producer_node_owner == "NoneValue.setattr"
    assert "setattr" in halt.effect.producer_node_owner


# ---------------------------------------------------------------------------
# Corpus coordinate
# ---------------------------------------------------------------------------


def test_pinned_pandas_name_attr_unpack_coordinate_is_real() -> None:
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.file_count, corpus.manifest_cid) == (
        "3.0.3",
        1421,
        MANIFEST_CID,
    )
    install_root = corpus.root.parent
    path = install_root / CORPUS_RELATIVE
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[CORPUS_LINE - 1].strip() == CORPUS_TEXT

    tree = SourceFile(
        workspace_path_source(str(path), root=str(install_root)),
        construction_context=tree_construction_context_for_workspace(install_root),
    )
    function = next(
        fn for fn in tree.functions() if fn.name == "test_pickle_preserves_name"
    )
    unpack = _the_unpack(function)
    assert unpack.targets[0].name == "original_name"
    store = _store_target(unpack).store
    # The store target's own statement: the one field store, keyed.
    assert isinstance(store, KeyedStoreSugar)
    assert isinstance(store.store, ReceiverFieldStoreSugar)
    assert store.store.attr == "name"
    # Formal ``index``: the undecided store, waiting on no caller (#7757).
    _undecided_store(store.desugar(_member_bound(unpack)))


def _the_unpack(function):
    """Line 113's one unpack: its display right-hand side is evaluated once
    and unpacked at reduce, as any other is (#7757 S2)."""
    from sugar_lift_py_tests.sugar.assign_sugar import DynamicUnpackStoreAssignSugar

    return next(
        stmt
        for stmt in function.sugar().statements
        if isinstance(stmt, DynamicUnpackStoreAssignSugar)
    )


def _store_target(unpack):
    """The unpack's one store leaf (``index.name``)."""
    from sugar_lift_py_tests.sugar.unpack_projection_targets import StoreUnpackTarget

    (target,) = [t for t in unpack.targets if isinstance(t, StoreUnpackTarget)]
    return target


def _member_bound(unpack):
    """The context the line-113 store runs in: its member ``"foo"`` bound
    under the leaf's member key, and the Name leaf to its left
    (``original_name``) bound under its projection key, as the unpack binds
    both before the store.  The store writes the post-store state of every
    name that may hold its receiver (``KeyedStoreSugar.writes``),
    ``original_name`` among them, and that state reads the name where the
    unpack bound it: the old ``index.name`` of a formal ``index``, a value
    no caller has supplied."""
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
    from sugar_lift_py_tests.sugar.unpack_projection_targets import NameUnpackTarget
    from sugar_lift_py_tests.temporal.temporal_context import projection_key

    ctx = ReduceContext.root(owner="pandas-name-store")
    for target in unpack.targets:
        if isinstance(target, NameUnpackTarget) and target.evaluation is not None:
            name_key = projection_key(target.evaluation, target.name)
            ctx = ScopeRebind(
                name_key, SymbolicValue(make_var(target.name))
            ).extend_scope(ctx)
    key = _store_target(unpack).evaluation
    return ScopeRebind(key, StringValue("foo")).extend_scope(ctx)


def _real_pandas_name_store():
    """Return the exact line-113 store and its own outcome on the formal
    ``index``: the undecided store, waiting on no caller (#7757)."""
    corpus = authenticated_pandas_corpus()
    install_root = corpus.root.parent
    path = install_root / CORPUS_RELATIVE
    tree = SourceFile(
        workspace_path_source(str(path), root=str(install_root)),
        construction_context=tree_construction_context_for_workspace(install_root),
    )
    function = next(
        fn for fn in tree.functions() if fn.name == "test_pickle_preserves_name"
    )
    unpack = _the_unpack(function)
    keyed = _store_target(unpack).store
    store = keyed.store
    outcome = keyed.desugar(_member_bound(unpack))
    assert isinstance(store, ReceiverFieldStoreSugar)
    _undecided_store(outcome)
    assert store.site.line_col_span.start_line == CORPUS_LINE
    return store, outcome


def _stored(store, receiver):
    """The line-113 store through the one attribute door on a receiver
    whose type the lift decides: its floor's own store, every face kept."""
    return store_effect_sugar.attribute_mutation(
        "__setattr__",
        receiver,
        "name",
        (StringValue("foo"),),
        store.site,
        None,
        unit=None,
    )


def test_real_pandas_name_store_caller_faces_and_discrimination() -> None:
    """The exact pandas store on each receiver whose type is decided: an
    immutable builtin's own ``AttributeError`` at the occurrence; on a
    source instance naming no class, ``type(o).__setattr__``, the one
    unanswered call, both faces kept and owed.

    Expected verdict changed (#7757 H1b, #9065): the lift no longer decides
    that the store on ``WritableIndex`` completes plain, nor that the store
    on ``GetterOnlyIndex``'s getter-only property raises ``AttributeError``
    (``ObjectValue.setattr``'s lift-decided halt is deleted).  Prove decides
    both; the call's halt is kept.  The wrong-boundary law stands on the
    tuple's named halt."""
    store, _outcome = _real_pandas_name_store()

    writable = ObjectValue(
        "WritableIndex", (ObjectField("name", NoneValue()),), allocation=FRAME_FRESH
    )
    _the_store_is_the_call(
        _stored(store, writable), "WritableIndex", StringValue("foo")
    )

    @dataclass(frozen=True)
    class _GetterBody(Sugar):
        @classmethod
        def witnesses(cls):
            return ()

        def desugar(self, ctx=None):
            del ctx
            from sugar_lift_py_tests.floor.return_value import ReturnValue

            return ExitSet.completed(
                BlockValue((ReturnValue(NoneValue()),), can_fall_through=False)
            )

    getter_only = ObjectValue(
        "GetterOnlyIndex",
        (),
        methods=(
            ObjectMethodValue(
                name="name",
                parameters=("self",),
                descriptor_kind="property",
            ),
        ),
        allocation=FRAME_FRESH,
    )
    _the_store_is_the_call(
        _stored(store, getter_only), "GetterOnlyIndex", StringValue("foo")
    )
    _the_store_is_the_call(
        getter_only.setattr("name", StringValue("foo"), store.site, None),
        "GetterOnlyIndex",
        StringValue("foo"),
    )

    immutable_halt = _stored(store, TupleValue((TermValue(1),))).exits[0]
    assert isinstance(immutable_halt, Halted)
    assert "AttributeError" in repr(immutable_halt.effect.exception_type_coordinate)
    assert (
        isinstance(immutable_halt.effect.occurrence_id, str)
        and ":" in immutable_halt.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {immutable_halt.effect.occurrence_id!r}"
    )
    assert immutable_halt.effect.occurrence_id.startswith(
        f"{CORPUS_RELATIVE}:{CORPUS_LINE}:"
    ), immutable_halt.effect.occurrence_id

    direct = TupleValue((TermValue(1),)).setattr(
        "name", StringValue("foo"), store.site, None
    )
    assert len(direct.exits) == 1 and direct.halts() == direct.exits
    (direct_halt,) = direct.halts()
    assert isinstance(direct_halt.effect, RaiseEffect)
    assert direct_halt.effect.exception_name == "AttributeError"
    assert direct_halt.effect.producer_node_owner == "TupleValue.setattr"

    # A getter spelling is neither store authority nor permission to invent a
    # readable value.  Expected value changed (#7757 steps 6 and 8, #8751,
    # #8813): the read used to apply the getter's body and panic on it
    # (``CallSiteValue.force_floor``); the lifter never follows a callee body
    # now, so the read is the one call of the getter -- dispatched where the
    # instance's class names a join symbol, else the one unanswered call --
    # two-faced and owed, decided at prove.  Never the ``None`` the body
    # returns, and its raise is kept.
    read = getter_only.attribute("name", store.site, None)
    assert isinstance(read, ExitSet), read
    assert read.halts(), read
    assert all(
        exit_.value != NoneValue()
        for exit_ in read.exits
        if isinstance(exit_, Completed)
    ), read

    from sugar_lift_py_tests.context_manager_contract import (
        AuthenticatedRaiseMatcher,
        EffectBoundaryDisposition,
    )
    from sugar_lift_py_tests.effect import ExpectationNotMetEffect
    from sugar_lift_py_tests.ir import ctor

    class _WrongExpected:
        def exception_type_identity(self):
            return ctor(
                "python:exception_type_identity",
                [str_const("builtins"), str_const("ValueError")],
            )

    produced = ExitSet((immutable_halt,))
    routed = produced.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(_WrongExpected()),
            unmet=ExpectationNotMetEffect("raise", store.site),
        ),
    )
    assert routed.exits == (immutable_halt,)
    assert routed.exits[0].state is immutable_halt.state
    assert routed.exits[0].effect is immutable_halt.effect


def test_real_pandas_name_store_waits_on_no_provider() -> None:
    """The store on the formal ``index`` is the undecided store in its own
    proof: no actual, a same-spelled foreign provider's included, is ever
    substituted into it.  It stays owed, its halt kept, never a store some
    object performed (#7757; prove joins the caller's call at the edge)."""
    _, outcome = _real_pandas_name_store()
    halt = _undecided_store(outcome)
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert outcome.completed_value() is None
