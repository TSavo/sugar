"""ADDED laws for source-visible attribute store faces.

Does **not** delete or rewrite store ExitSet composition laws
(``test_store_outcome_composition``, unpack twins). Those five named laws
remain the dual-face instrument for undecided formal stores via
``AttributeStoreRuntimeEffect``.

Python semantic law made constructible (PARTIAL):

  For ``obj.attr = value``, when the receiver runtime type is decided, project
  through Floor ``setattr`` (not the read path). Evaluate RHS then receiver
  once. Store halt preserves earlier state. Exception type originates in the
  store dispatch owner.

  Formal ``setattr_named`` carrier mint is pinned as the n-ary discharge
  contract (operator + operand order) but is not yet the sole formal arm —
  wiring it into ``_store`` would convert dual-face ExitSet composition into
  undischarged carriers and red the five named store laws without an
  individual per-test restatement. That switch is a separate partial step.

Named seams (``test_producer_and_consumer_methods_are_the_named_seams``):

  producer: ``AttributeStoreEffectSugar.desugar`` / ``_store``
  consumer: ``FloorValue.setattr`` / ``ObjectValue.setattr``

Pinned pandas 3.0.3 (line content verified on installed seat):

  ``pandas/tests/indexes/test_any_index.py:113``
  ``original_name, index.name = index.name, "foo"``
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.effect import AttributeStoreRuntimeEffect
from sugar_lift_py_tests.floor import (
    BytesValue,
    FloorValue,
    ListValue,
    NoneValue,
    ObjectField,
    ObjectMethodValue,
    ObjectValue,
    RaiseValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import PrimitiveSort, make_var, str_const
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Incomplete
from sugar_lift_py_tests.outcome.exit_set import Halted
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset
from sugar_lift_py_tests.sugar.store_effect_sugar import AttributeStoreEffectSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_lift_py_tests.lift_rpc import tree_construction_context_for_workspace
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

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
        return Complete(self.value)


def _store(receiver, value, log, site, attr: str = "attr"):
    return AttributeStoreEffectSugar(
        receiver=_ObservedSugar("receiver", receiver, log),
        value=_ObservedSugar("value", value, log),
        attr=attr,
        site=site,
    )


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
    assert hasattr(AttributeStoreEffectSugar, "desugar")
    assert hasattr(AttributeStoreEffectSugar, "_store")
    assert hasattr(AttributeStoreEffectSugar, "desugar_store")
    assert hasattr(AttributeStoreEffectSugar, "mint_setattr_named_carrier")
    assert hasattr(FloorValue, "setattr")
    assert hasattr(ObjectValue, "setattr")
    assert FloorValue.setattr is not FloorValue.attribute


# ---------------------------------------------------------------------------
# Evaluate-once / left-to-right
# ---------------------------------------------------------------------------


def test_attribute_store_evaluates_rhs_and_receiver_once_in_python_order(tmp_path):
    log: list[str] = []
    receiver = ObjectValue("R", (ObjectField("attr", TermValue(1)),))
    outcome = _store(receiver, TermValue(7), log, _site(tmp_path)).desugar()

    assert log == ["value", "receiver"]
    assert isinstance(outcome, Complete)
    assert outcome.value.fields[-1].value == TermValue(7)


def test_rhs_halt_wins_before_receiver_evaluation(tmp_path):
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.floor import RaiseValue

    log: list[str] = []

    @dataclass(frozen=True)
    class _RaisingValue(Sugar):
        def desugar(self, ctx=None):
            del ctx
            log.append("value")
            return Complete(
                RaiseValue(
                    RaiseEffect(
                        exception_type_coordinate=str_const("ValueError"),
                        occurrence=AuthenticatedRaiseLocus.of("attr_store.py:2:16"),
                    )
                )
            )

        @classmethod
        def witnesses(cls):
            raise AssertionError

    store = AttributeStoreEffectSugar(
        receiver=_ObservedSugar("receiver", ObjectValue("R", ()), log),
        value=_RaisingValue(),
        attr="attr",
        site=_site(tmp_path),
    )
    outcome = store.desugar()

    assert log == ["value"]
    assert outcome.value.effect.exception_type_coordinate == str_const("ValueError")


# ---------------------------------------------------------------------------
# Decided faces — store path ≠ read path
# ---------------------------------------------------------------------------


def test_ground_object_field_store_completes(tmp_path):
    receiver = ObjectValue("R", (ObjectField("attr", TermValue(0)),))
    outcome = _store(receiver, TermValue(9), [], _site(tmp_path)).desugar()
    assert isinstance(outcome, Complete)
    assert outcome.value.fields[-1].value == TermValue(9)


def test_readable_immutable_receiver_raises_on_store(tmp_path):
    receiver = TupleValue((TermValue(1),))
    outcome = _store(receiver, TermValue(7), [], _site(tmp_path)).desugar()

    assert isinstance(outcome, Incomplete)
    assert outcome.effect.exception_name == "AttributeError"
    assert outcome.effect.producer_node_owner == "TupleValue.setattr"


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
    assert isinstance(outcome, Incomplete)
    assert outcome.effect.exception_name == "AttributeError"
    assert outcome.effect.producer_node_owner == owner
    assert outcome.effect.occurrence_id == str(site)


@pytest.mark.parametrize("receiver", (StringValue("abc"), BytesValue(b"abc")))
def test_immutable_scalar_attribute_store_cannot_fabricate_completion(
    tmp_path, receiver
):
    outcome = _store(receiver, TermValue(7), [], _site(tmp_path)).desugar()
    assert not isinstance(outcome, Complete)


def test_none_setattr_is_attribute_error_on_store_path(tmp_path):
    outcome = _store(NoneValue(), TermValue(1), [], _site(tmp_path)).desugar()
    assert isinstance(outcome, Incomplete)
    assert outcome.effect.exception_name == "AttributeError"
    assert outcome.effect.producer_node_owner == "NoneValue.setattr"


def test_list_read_path_does_not_license_list_setattr(tmp_path):
    receiver = ListValue((TermValue(1),))
    outcome = _store(
        receiver, TermValue(7), [], _site(tmp_path), attr="append"
    ).desugar()
    assert isinstance(outcome, Incomplete)
    assert outcome.effect.exception_name == "AttributeError"
    assert outcome.effect.producer_node_owner == "ListValue.setattr"


def test_property_without_setter_raises_attribute_error_not_completed(tmp_path):
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    @dataclass(frozen=True)
    class _GetterBody(Sugar):
        def desugar(self, ctx=None):
            del ctx
            return Complete(
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
                body=_GetterBody(),
                descriptor_kind="property",
            ),
        ),
    )
    outcome = _store(receiver, TermValue(7), [], _site(tmp_path)).desugar()
    assert isinstance(outcome, Incomplete)
    assert outcome.effect.exception_name == "AttributeError"
    assert outcome.effect.producer_node_owner == "ObjectValue.setattr"


def test_undecided_retains_dual_face_runtime_effect(tmp_path):
    """Dual-face instrument intact — not replaced by SugarNotWritten."""
    outcome = _store(
        SymbolicValue(make_var("obj")), TermValue(7), [], _site(tmp_path)
    ).desugar()
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, AttributeStoreRuntimeEffect)


def test_formal_parameter_store_mints_setattr_named_carrier(tmp_path):
    """Formal parameters mint setattr_named (undischarged until caller)."""
    path = tmp_path / "formal_store.py"
    path.write_text("def target(o, p):\n    o.x = p\n    return p\n")
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    fn = next(
        SourceFile(
            path_source(str(path)),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        ).functions()
    )
    outcome = fn.sugar().desugar(None)
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.demand.operator == "setattr_named"


# ---------------------------------------------------------------------------
# setattr_named mint contract (n-ary worker producer side)
# ---------------------------------------------------------------------------


def test_setattr_named_carrier_mint_contract(tmp_path):
    """Operator string and operand order for the n-ary discharge worker."""
    site = _site(tmp_path)
    formal = _formal(site)
    receiver = SymbolicValue(make_var("obj"), formal)
    value = TermValue(7)
    carrier = AttributeStoreEffectSugar.mint_setattr_named_carrier(
        site=site, receiver=receiver, attr="attr", value=value
    )
    assert isinstance(carrier, NativeOperationExitCarrierV1)
    assert carrier.demand.operator == "setattr_named"
    assert len(carrier.operands) == 3
    assert carrier.demand.operand_coordinate_cids[0] == formal.coordinate_cid
    assert carrier.demand.operand_coordinate_cids[1] is None


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
            return Complete(
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
                body=_GetterBody(),
                descriptor_kind="property",
            ),
        ),
    )
    outcome = _store(receiver, TermValue(7), [], _site(tmp_path)).desugar()
    assert not (
        isinstance(outcome, Complete) and isinstance(outcome.value, ObjectValue)
    )


def test_exception_type_originates_in_store_dispatch_not_boundary(tmp_path):
    outcome = _store(NoneValue(), TermValue(1), [], _site(tmp_path)).desugar()
    assert outcome.effect.exception_name == "AttributeError"
    assert outcome.effect.producer_node_owner == "NoneValue.setattr"
    assert "setattr" in outcome.effect.producer_node_owner


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
    from sugar_lift_py_tests.sugar.assign_sugar import UnpackStoreAssignSugar

    unpack = next(
        stmt
        for stmt in function.sugar().statements
        if isinstance(stmt, UnpackStoreAssignSugar)
    )
    assert unpack.bindings[0][0] == "original_name"
    store = unpack.stores[0]
    assert isinstance(store, AttributeStoreEffectSugar)
    assert store.attr == "name"
    # Formal ``index`` mints setattr_named (undischarged until caller).
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    outcome = store.desugar(None)
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.demand.operator == "setattr_named"


def _real_pandas_name_store():
    """Return the exact line-113 store and its undischarged caller demand."""
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
    from sugar_lift_py_tests.sugar.assign_sugar import UnpackStoreAssignSugar

    unpack = next(
        statement
        for statement in function.sugar().statements
        if isinstance(statement, UnpackStoreAssignSugar)
    )
    store = unpack.stores[0]
    pending = store.desugar(None)
    assert isinstance(store, AttributeStoreEffectSugar)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setattr_named"
    assert store.site.line_col_span.start_line == CORPUS_LINE
    return store, pending


def test_real_pandas_name_store_caller_faces_and_discrimination() -> None:
    """The exact pandas store owns completion, AttributeError, and occurrence."""
    store, pending = _real_pandas_name_store()
    receiver_cid = pending.demand.operand_coordinate_cids[0]
    assert receiver_cid is not None

    writable = ObjectValue("WritableIndex", (ObjectField("name", NoneValue()),))
    completed = pending.discharge({receiver_cid: writable})
    assert len(completed.exits) == 1
    assert isinstance(completed.exits[0], Completed)

    @dataclass(frozen=True)
    class _GetterBody(Sugar):
        @classmethod
        def witnesses(cls):
            return ()

        def desugar(self, ctx=None):
            del ctx
            from sugar_lift_py_tests.floor.return_value import ReturnValue

            return Complete(
                BlockValue((ReturnValue(NoneValue()),), can_fall_through=False)
            )

    getter_only = ObjectValue(
        "GetterOnlyIndex",
        (),
        methods=(
            ObjectMethodValue(
                name="name",
                parameters=("self",),
                body=_GetterBody(),
                descriptor_kind="property",
            ),
        ),
    )
    getter_halt = pending.discharge({receiver_cid: getter_only}).exits[0]
    immutable_halt = pending.discharge(
        {receiver_cid: TupleValue((TermValue(1),))}
    ).exits[0]
    for halt, owner in (
        (getter_halt, "ObjectValue.setattr"),
        (immutable_halt, "TupleValue.setattr"),
    ):
        assert isinstance(halt, Halted)
        assert "AttributeError" in repr(halt.effect.exception_type_coordinate)
        assert (
            isinstance(halt.effect.occurrence_id, str)
            and ":" in halt.effect.occurrence_id
        ), (
            "authenticated raise locus must be a file:line:col occurrence id, "
            f"not presence-only; got {halt.effect.occurrence_id!r}"
        )
        assert f"'startLine': {CORPUS_LINE}" in halt.effect.occurrence_id

    for receiver, owner in (
        (getter_only, "ObjectValue.setattr"),
        (TupleValue((TermValue(1),)), "TupleValue.setattr"),
    ):
        direct = receiver.setattr("name", StringValue("foo"), store.site)
        assert isinstance(direct, Complete)
        assert isinstance(direct.value, RaiseValue)
        assert direct.value.effect.exception_name == "AttributeError"
        assert direct.value.effect.producer_node_owner == owner

    # A getter spelling is neither store authority nor permission to invent a
    # readable value: its deliberately unconstructed body remains loud.
    with pytest.raises(ConstructionPanic, match="CallSiteValue.force_floor"):
        getter_only.attribute("name", store.site)
    assert isinstance(getter_halt, Halted)
    assert not isinstance(getter_halt, Completed)

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

    produced = ExitSet((getter_halt,))
    routed = produced.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(_WrongExpected()),
            unmet=ExpectationNotMetEffect("raise", store.site),
        ),
    )
    assert routed.exits == (getter_halt,)
    assert routed.exits[0].state is getter_halt.state
    assert routed.exits[0].effect is getter_halt.effect


def test_same_spelled_foreign_provider_cannot_discharge_real_store() -> None:
    """Provider spelling is not the exact formal-coordinate authority."""
    _, pending = _real_pandas_name_store()
    receiver_cid = pending.demand.operand_coordinate_cids[0]
    assert receiver_cid is not None
    foreign_path = Path("same-spelled-provider.py")
    foreign_source = "def test_pickle_preserves_name(index, temp_file):\n    pass\n"
    foreign_tree = SourceFile(
        (foreign_source, str(foreign_path), "blake3-512:" + "00" * 64)
    )
    foreign = next(foreign_tree.functions())
    foreign_formal = _formal(foreign.fragment)
    assert foreign_formal.coordinate_cid != receiver_cid

    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge(
            {
                foreign_formal.coordinate_cid: ObjectValue(
                    "ForeignIndex", (ObjectField("name", NoneValue()),)
                )
            }
        )
