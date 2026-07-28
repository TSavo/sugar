"""Compare is an effect producer; undecided native dispatch stays named-loud."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import CallSiteValue, NoneValue, SymbolicValue, TermValue
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.comparison_op_sugar import ComparisonOpSugar
from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Compare, Subscript
from sugar_source_tree.tree import SourceFile

# Content manifest (relative path + per-file BLAKE3-512). Path-shape
# sha256:a223… is historical negative testimony only — never identity.
MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
HISTORICAL_PATH_SHAPE_DIGEST = (
    "sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0"
)
DEMAND_TABLE_KEY = (
    "blake3-512:0ce7c645a7525f1fe5189b808162b49d3fc3ba3d898bfb3d5086e0f295b8b8d"
    "263fe7f530a6aa34adb125615a21e69fdee249e0314bf199b8f43580375153ab0"
)
COL_SITE_SHA256 = "a86bcccd3f041ac81a1d6f349d537ee1049c6afa4d799b9293b410da4409f038"
COL_SOURCE_CID = (
    "blake3-512:58f9629e47ef9bdb4137fbe31d1c322b22fd1918ec8da1b1725f344d0087d5a27"
    "f69cb188d8d417d0f6490c6a9531191e789f9e5df14e5070f93455673bacdad"
)
NUMERIC_SITE_SHA256 = "ad382bdf9178c34fffa4762b4014a8ef64d02e548433adaa8aba414398d6e5d8"
COMMON_SITE_SHA256 = "442441f4ea11ec95e361c54ddf5c599a49769928970af3daee3b9a482dce7754"
CATEGORICAL_EQ_SITE_SHA256 = (
    "b831a0a2339aaa702fc962a23f23b53e7f1eb08b45c6a93abddb42ee7e76690d"
)
MULTI_EQ_SITE_SHA256 = (
    "45fafbc8cd4dcc9bfcabd8f807e44e15377d729cfd7cf517c2b7ff72560aa343"
)
GETITEM_SITE_SHA256 = "d2940a05aea5aa4c8aea3569fcef114c0564eba844a26a4982263ad3b6c53000"


@dataclass(frozen=True)
class _ValueSugar(Sugar):
    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _corpus_root() -> Path:
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.manifest_cid, corpus.file_count) == (
        "3.0.3",
        MANIFEST_CID,
        1421,
    )
    assert corpus.manifest_cid != HISTORICAL_PATH_SHAPE_DIGEST
    return corpus.root


def _compare_at(path: Path, source: str, *, line: int) -> Compare:
    tree = SourceFile(
        (source, str(path), blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    matches = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Compare) and node.line_col_span().start_line == line
    )
    assert len(matches) == 1
    return matches[0]


def _synthetic_compare(expression: str) -> Compare:
    source = f"def f(left, container):\n    return {expression}\n"
    tree = SourceFile(
        (source, "compare-dual-edge.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, Compare))


def _formal_coordinate(
    node: Compare, name: str, ordinal: int
) -> FormalParameterCoordinateV1:
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )

    span = node.fragment.line_col_span
    owner = SourceFragmentCoordinateV1(
        node.fragment.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    return FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=node.fragment.source_cid,
        owner_definition_locus=owner,
        declaration_locus=owner,
        ordinal=ordinal,
        parameter_kind="positional-or-keyword",
        declared_name=name,
        sort=PrimitiveSort("Value"),
    )


def _assert_dual_dispatch(outcome, *, atom: str, blame: str) -> None:
    from sugar_lift_py_tests.floor import PredicateValue
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted, complement_guard

    assert isinstance(outcome, ExitSet)
    completed = next(exit_ for exit_ in outcome.exits if isinstance(exit_, Completed))
    halted = next(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
    assert isinstance(completed.value, PredicateValue)

    def atom_names(formula) -> set[str]:
        name = getattr(formula, "name", None)
        if isinstance(name, str):
            return {name}
        return {
            nested
            for operand in getattr(formula, "operands", ())
            for nested in atom_names(operand)
        }

    assert atom in atom_names(completed.value.formula)
    assert halted.effect.exception_name is None
    assert halted.effect.blame == blame
    assert halted.effect.producer_node_owner == "Compare"
    assert completed.guard == complement_guard(halted.guard)


def _assert_compare_dual(node, *, atom: str) -> None:
    _assert_dual_dispatch(
        node.sugar().desugar(None), atom=atom, blame=str(node.fragment)
    )


def _builtin_exception_identity(name: str):
    from sugar_lift_py_tests.ir import str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def test_launcher_authenticates_content_manifest_not_path_shape() -> None:
    corpus = authenticated_pandas_corpus()
    assert corpus.manifest_cid == MANIFEST_CID
    assert corpus.manifest_cid != HISTORICAL_PATH_SHAPE_DIGEST
    assert corpus.file_count == 1421


def test_shared_table_authenticates_the_exact_compare_site(tmp_path: Path) -> None:
    output = tmp_path / "table.json"
    pulled = subprocess.run(
        [
            str(_repo_root() / "bin/sugarbin"),
            "artifact",
            "pull",
            "--kind",
            "python-demand-table",
            "--content-key",
            DEMAND_TABLE_KEY,
            "--output",
            str(output),
            "--runtime",
            "cpython-3.12.13",
        ],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
        env={
            **dict(__import__("os").environ),
            "SUGAR_BINARY_ALLOW_BUILD": "0",
            "SUGAR_BINARY_PUBLISH": "0",
        },
    )
    assert pulled.returncode == 0 and output.is_file(), (
        "the authenticated #6464 demand table is absent; do not rebuild it: "
        + pulled.stderr
    )
    table = json.loads(output.read_text(encoding="utf-8"))
    assert table["authentication"]["python"] == "cpython-3.12.13"
    assert table["authentication"]["authenticatedCorpusManifestCid"] == MANIFEST_CID
    assert table["authentication"]["pandas"] == "3.0.3"
    assert table["identity"]["fileCount"] == 1421
    assert table["authentication"]["authenticatedCorpusManifestCid"] != (
        HISTORICAL_PATH_SHAPE_DIGEST
    )
    rows = tuple(
        row
        for row in table["rows"]
        if row.get("kind") == "context-manager-demand"
        and row.get("targetSymbol") == "pytest.raises"
        and row.get("gapKind") is None
        and row.get("useSite")
        == {
            "sourceCid": COL_SOURCE_CID,
            "startLine": 362,
            "startCol": 9,
            "endLine": 364,
            "endCol": 5,
        }
    )
    assert len(rows) == 1


def test_pandas_col_membership_retains_both_source_visible_faces() -> None:
    path = _corpus_root() / "tests/test_col.py"
    source = path.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode()).hexdigest() == COL_SITE_SHA256
    assert blake3_512_of(source.encode()) == COL_SOURCE_CID

    _assert_compare_dual(_compare_at(path, source, line=365), atom="py.in")


def test_literal_container_lying_twin_does_not_inherit_the_refusal() -> None:
    path = _corpus_root() / "tests/test_col.py"
    source = path.read_text(encoding="utf-8")
    lying = source.replace('1 in pd.col("a")', "1 in [1]")
    assert lying != source

    outcome = _compare_at(path, lying, line=365).sugar().desugar(None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)


def test_runtime_truthful_and_lying_twins_discriminate() -> None:
    import pandas as pd

    def raises_type_error(thunk) -> bool:
        try:
            thunk()
        except TypeError:
            return True
        return False

    with pytest.raises(TypeError, match="not .*iterable"):
        1 in pd.col("a")
    assert 1 in [1]
    with pytest.raises(AssertionError):
        assert raises_type_error(lambda: 1 in [1])


@pytest.mark.parametrize("op_kind", ["Lt", "NotEq", "In", "NotIn", "Eq"])
def test_every_nonidentity_comparison_keeps_undecided_call_dispatch_loud(
    op_kind: str,
) -> None:
    call_result = _ValueSugar(
        CallSiteValue("unknown", (), (), ctor("call:unknown", []), None)
    )
    ground = _ValueSugar(TermValue(1))
    left, right = (
        (ground, call_result)
        if op_kind in {"In", "NotIn"}
        else (
            call_result,
            ground,
        )
    )

    expression_by_kind = {
        "Lt": "left < 1",
        "NotEq": "left != 1",
        "In": "1 in container",
        "NotIn": "1 not in container",
        "Eq": "left == 1",
    }
    site = _synthetic_compare(expression_by_kind[op_kind]).fragment
    sugar = (
        EqualityOpSugar(left, right, site)
        if op_kind == "Eq"
        else ComparisonOpSugar(op_kind, left, right, site)
    )
    _assert_dual_dispatch(
        sugar.desugar(None),
        atom={
            "Lt": "py.lt",
            "NotEq": "py.eq",
            "Eq": "py.eq",
            "In": "py.in",
            "NotIn": "py.in",
        }[op_kind],
        blame=str(site),
    )


@pytest.mark.parametrize(
    ("op_kind", "operator", "atom"),
    (
        ("Lt", "<", "py.lt"),
        ("Gt", ">", "py.gt"),
        ("LtE", "<=", "py.le"),
        ("GtE", ">=", "py.ge"),
    ),
)
def test_undecided_symbolic_ordering_emits_completed_and_exceptional_edges(
    op_kind: str, operator: str, atom: str
) -> None:
    """Ordering keeps its solver atom and the native dispatch halt together."""
    node = _synthetic_compare(f"left {operator} 1")
    left = _ValueSugar(SymbolicValue(make_var("left")))
    right = _ValueSugar(TermValue(1))
    outcome = ComparisonOpSugar(op_kind, left, right, node.fragment).desugar(None)
    _assert_dual_dispatch(outcome, atom=atom, blame=str(node.fragment))


def test_symbolic_equality_keeps_solver_atom_and_exceptional_edge() -> None:
    """The landed ``py.eq`` atom survives beside possible native ``__eq__`` halt."""
    node = _synthetic_compare("left == 1")
    outcome = EqualityOpSugar(
        _ValueSugar(SymbolicValue(make_var("left"))),
        _ValueSugar(TermValue(1)),
        node.fragment,
    ).desugar(None)
    _assert_dual_dispatch(outcome, atom="py.eq", blame=str(node.fragment))


def test_two_symbolic_equality_operands_keep_both_dispatch_faces() -> None:
    """Two undecided operands neither fabricate totality nor refuse dispatch."""
    node = _synthetic_compare("left == container")
    outcome = EqualityOpSugar(
        _ValueSugar(SymbolicValue(make_var("left"))),
        _ValueSugar(SymbolicValue(make_var("right"))),
        node.fragment,
    ).desugar(None)
    _assert_dual_dispatch(outcome, atom="py.eq", blame=str(node.fragment))


def test_ground_decided_equality_still_completes() -> None:
    """Lying twin: two decided scalars do not gain a dispatch split.

    Ground ``1 == 2`` folds to a False literal (not a dual-edge ExitSet and
    not a residual py.eq invent). Accept the honest completed bool sugar.
    """
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar

    outcome = EqualityOpSugar(
        _ValueSugar(TermValue(1)),
        _ValueSugar(TermValue(2)),
        "compare-site",
    ).desugar(None)
    assert isinstance(outcome, Complete)
    assert not isinstance(outcome, ExitSet)
    assert isinstance(outcome.value, FalseBoolLiteralSugar)


@pytest.mark.parametrize(
    ("op_kind", "expression"),
    (("In", "1 in container"), ("NotIn", "1 not in container")),
)
def test_membership_law_routes_through_authenticated_contains(
    op_kind: str, expression: str
) -> None:
    node = _synthetic_compare(expression)
    outcome = ComparisonOpSugar(
        op_kind,
        _ValueSugar(TermValue(1)),
        _ValueSugar(SymbolicValue(make_var("container"))),
        node.fragment,
    ).desugar(None)
    _assert_dual_dispatch(outcome, atom="py.in", blame=str(node.fragment))


def test_formal_ordering_survives_until_authenticated_caller_discharge() -> None:
    """One ordered operation may honestly complete or halt at its callers."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

    node = _synthetic_compare("left < container")
    left_coordinate = _formal_coordinate(node, "left", 0)
    right_coordinate = _formal_coordinate(node, "container", 1)
    carrier = ComparisonOpSugar(
        "Lt",
        _ValueSugar(SymbolicValue(make_var("left"), left_coordinate)),
        _ValueSugar(SymbolicValue(make_var("container"), right_coordinate)),
        node.fragment,
    ).desugar(None)

    assert isinstance(carrier, NativeOperationExitCarrierV1)
    assert carrier.demand.operator == "less_than"
    assert carrier.demand.operand_coordinate_cids == (
        left_coordinate.coordinate_cid,
        right_coordinate.coordinate_cid,
    )

    completed = carrier.discharge(
        {
            left_coordinate.coordinate_cid: TermValue(1),
            right_coordinate.coordinate_cid: TermValue(2),
        }
    )
    halted = carrier.discharge(
        {
            left_coordinate.coordinate_cid: NoneValue(),
            right_coordinate.coordinate_cid: TermValue(2),
        }
    )
    assert len(completed.exits) == 1
    assert isinstance(completed.exits[0], Completed)
    assert len(halted.exits) == 1
    assert isinstance(halted.exits[0], Halted)
    assert halted.exits[0].effect.exception_name is None
    assert halted.exits[
        0
    ].effect.exception_type_coordinate == _builtin_exception_identity("TypeError")


def test_formal_ordering_rejects_a_lying_exception_identity() -> None:
    """A ValueError boundary cannot consume an authenticated TypeError halt."""
    from sugar_lift_py_tests.context_manager_contract import (
        AuthenticatedRaiseMatcher,
        EffectBoundaryDisposition,
    )
    from sugar_lift_py_tests.effect.expectation_not_met_effect import (
        ExpectationNotMetEffect,
    )
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import Halted

    class _ExpectedValueError:
        identity = _builtin_exception_identity("ValueError")

        def exception_type_identity(self):
            return self.identity

    node = _synthetic_compare("left < container")
    left_coordinate = _formal_coordinate(node, "left", 0)
    carrier = ComparisonOpSugar(
        "Lt",
        _ValueSugar(SymbolicValue(make_var("left"), left_coordinate)),
        _ValueSugar(TermValue(2)),
        node.fragment,
    ).desugar(None)
    exits = carrier.discharge({left_coordinate.coordinate_cid: NoneValue()})
    projected = exits.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_ExpectedValueError()),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )

    assert len(projected.exits) == 1
    assert isinstance(projected.exits[0], Halted)
    assert projected.exits[0].effect.exception_name is None
    assert projected.exits[
        0
    ].effect.exception_type_coordinate == _builtin_exception_identity("TypeError")


def test_formal_membership_records_authenticated_contains_receiver_order() -> None:
    """``item in container`` defers ``container.contains(item)`` in that order."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    node = _synthetic_compare("left in container")
    item_coordinate = _formal_coordinate(node, "left", 0)
    container_coordinate = _formal_coordinate(node, "container", 1)
    carrier = ComparisonOpSugar(
        "In",
        _ValueSugar(SymbolicValue(make_var("left"), item_coordinate)),
        _ValueSugar(SymbolicValue(make_var("container"), container_coordinate)),
        node.fragment,
    ).desugar(None)

    assert isinstance(carrier, NativeOperationExitCarrierV1)
    assert carrier.demand.operator == "contains"
    assert carrier.demand.operand_coordinate_cids == (
        container_coordinate.coordinate_cid,
        item_coordinate.coordinate_cid,
    )


def test_formal_equality_keeps_py_eq_solver_work_until_discharge() -> None:
    """A formal equality is deferred; its authenticated ground result completes."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.outcome.exit_set import Completed
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar

    node = _synthetic_compare("left == 2")
    left_coordinate = _formal_coordinate(node, "left", 0)
    carrier = EqualityOpSugar(
        _ValueSugar(SymbolicValue(make_var("left"), left_coordinate)),
        _ValueSugar(TermValue(2)),
        node.fragment,
    ).desugar(None)

    assert isinstance(carrier, NativeOperationExitCarrierV1)
    assert carrier.demand.operator == "equals"
    exits = carrier.discharge({left_coordinate.coordinate_cid: TermValue(1)})
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    assert isinstance(exits.exits[0].value, FalseBoolLiteralSugar)


def test_formal_ordering_keeps_swapped_operand_coordinates_distinct() -> None:
    node = _synthetic_compare("left < container")
    left_coordinate = _formal_coordinate(node, "left", 0)
    right_coordinate = _formal_coordinate(node, "container", 1)
    left = SymbolicValue(make_var("left"), left_coordinate)
    right = SymbolicValue(make_var("container"), right_coordinate)

    forward = ComparisonOpSugar(
        "Lt", _ValueSugar(left), _ValueSugar(right), node.fragment
    ).desugar(None)
    swapped = ComparisonOpSugar(
        "Lt", _ValueSugar(right), _ValueSugar(left), node.fragment
    ).desugar(None)

    assert forward.demand.operand_coordinate_cids == (
        left_coordinate.coordinate_cid,
        right_coordinate.coordinate_cid,
    )
    assert swapped.demand.operand_coordinate_cids == (
        right_coordinate.coordinate_cid,
        left_coordinate.coordinate_cid,
    )
    assert forward.demand.demand_cid != swapped.demand.demand_cid


def test_formal_identity_remains_total_without_a_native_operation_carrier() -> None:
    """A formal binding does not make ``is`` acquire a fabricated raise face."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    node = _synthetic_compare("left is container")
    left_coordinate = _formal_coordinate(node, "left", 0)
    outcome = ComparisonOpSugar(
        "Is",
        _ValueSugar(SymbolicValue(make_var("left"), left_coordinate)),
        _ValueSugar(SymbolicValue(make_var("container"))),
        node.fragment,
    ).desugar(None)

    assert isinstance(outcome, Complete)
    assert not isinstance(outcome, NativeOperationExitCarrierV1)


def test_identity_never_gains_an_exceptional_dispatch_edge() -> None:
    """LYING TWIN: ``is`` is total and must not inherit rich-operation edges."""
    node = _synthetic_compare("left is 1")
    outcome = ComparisonOpSugar(
        "Is",
        _ValueSugar(SymbolicValue(make_var("left"))),
        _ValueSugar(TermValue(1)),
        node.fragment,
    ).desugar(None)
    assert isinstance(outcome, Complete)


def test_ground_decided_membership_still_completes() -> None:
    """Lying twin: a decided finite container is not an undecided third value."""
    from sugar_lift_py_tests.floor import ListValue

    outcome = ComparisonOpSugar(
        "In",
        _ValueSugar(TermValue(1)),
        _ValueSugar(ListValue((TermValue(1),))),
        "compare-site",
    ).desugar(None)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)


def test_pandas_categorical_equality_retains_both_dispatch_faces() -> None:
    path = _corpus_root() / "tests/arrays/categorical/test_operators.py"
    source = path.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode()).hexdigest() == CATEGORICAL_EQ_SITE_SHA256
    assert source.count("c1 == c2") >= 1
    _assert_compare_dual(_compare_at(path, source, line=335), atom="py.eq")


def test_pandas_index_length_equality_retains_both_dispatch_faces() -> None:
    path = _corpus_root() / "tests/indexes/multi/test_equivalence.py"
    source = path.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode()).hexdigest() == MULTI_EQ_SITE_SHA256
    _assert_compare_dual(_compare_at(path, source, line=43), atom="py.eq")


def test_source_decided_membership_in_number_emits_type_error() -> None:
    from sugar_lift_py_tests.floor import RaiseValue

    twin = "def f():\n    return 1 in 2\n"
    tree = SourceFile(
        (twin, "in-number-twin.py", blake3_512_of(twin.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    node = next(
        n
        for n in tree.nodes()
        if isinstance(n, Compare) and n.line_col_span().start_line == 2
    )
    outcome = ComparisonOpSugar(
        "In",
        _ValueSugar(TermValue(1)),
        _ValueSugar(TermValue(2)),
        node.fragment,
    ).desugar(None)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


def test_source_decided_none_greater_than_emits_type_error() -> None:
    from sugar_lift_py_tests.floor import NoneValue, RaiseValue

    twin = "def f():\n    return None > 1\n"
    tree = SourceFile(
        (twin, "none-gt-twin.py", blake3_512_of(twin.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    node = next(
        n
        for n in tree.nodes()
        if isinstance(n, Compare) and n.line_col_span().start_line == 2
    )
    outcome = ComparisonOpSugar(
        "Gt",
        _ValueSugar(NoneValue()),
        _ValueSugar(TermValue(1)),
        node.fragment,
    ).desugar(None)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


def test_pandas_series_string_ordering_retains_both_faces() -> None:
    """``obj < "a"``: string right is decided; left Series type is not.

    Site: ``pandas/tests/arithmetic/test_numeric.py:146`` under
    ``pytest.raises(TypeError)``. Source does not state Series type at the
    Compare, so the producer cannot mint TypeError — only the named refusal.
    """
    path = _corpus_root() / "tests/arithmetic/test_numeric.py"
    source = path.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode()).hexdigest() == NUMERIC_SITE_SHA256
    assert source.count('obj < "a"') == 1

    import pandas

    series = pandas.Series([1.0, 2.0], dtype="float64")
    with pytest.raises(TypeError, match="Invalid comparison"):
        series < "a"  # noqa: B015

    _assert_compare_dual(_compare_at(path, source, line=146), atom="py.lt")


def test_source_decided_number_string_ordering_emits_type_error() -> None:
    """Truthful twin of the enrolled ``obj < "a"`` site with decided types.

    When both operands are source-visible ground values Python refuses to
    order, Compare constructs an authenticated TypeError RaiseValue — not
    ``py.lt`` and not a RuntimeEffect.  The enrolled pandas site still
    refuses because ``obj`` is undecided; this twin isolates the floor law
    on a workspace-relative locus the ground exit can cite.
    """
    from sugar_lift_py_tests.floor import RaiseValue, StringValue

    path = _corpus_root() / "tests/arithmetic/test_numeric.py"
    source = path.read_text(encoding="utf-8")
    assert source.count('obj < "a"') == 1
    _compare_at(path, source, line=146)

    twin = 'def f():\n    return 1.0 < "a"\n'
    tree = SourceFile(
        (twin, "number-lt-string-twin.py", blake3_512_of(twin.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    node = next(
        n
        for n in tree.nodes()
        if isinstance(n, Compare) and n.line_col_span().start_line == 2
    )
    outcome = ComparisonOpSugar(
        "Lt",
        _ValueSugar(TermValue(1.0)),
        _ValueSugar(StringValue("a")),
        node.fragment,
    ).desugar(None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"
    assert outcome.value.effect.blame is not None


@pytest.mark.parametrize(
    ("line", "op", "observed"),
    (
        (144, "<", "SymbolicValue < SymbolicValue"),
        (146, "<=", "SymbolicValue <= SymbolicValue"),
        (148, ">", "SymbolicValue > SymbolicValue"),
        (150, ">=", "SymbolicValue >= SymbolicValue"),
        (152, "<", "SymbolicValue < SymbolicValue"),
        (154, "<=", "SymbolicValue <= SymbolicValue"),
        (156, ">", "SymbolicValue > SymbolicValue"),
        (158, ">=", "SymbolicValue >= SymbolicValue"),
    ),
)
def test_pandas_left_right_ordering_faces_retain_both_edges(
    line: int, op: str, observed: str
) -> None:
    """``left < right`` family in arithmetic/common.py: both sides undecided.

    Eight faces of the same helper under TypeError expectations. Production
    construction sees only name coordinates — refuse without inventing exits.
    """
    path = _corpus_root() / "tests/arithmetic/common.py"
    source = path.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode()).hexdigest() == COMMON_SITE_SHA256
    _assert_compare_dual(
        _compare_at(path, source, line=line),
        atom={"<": "py.lt", "<=": "py.le", ">": "py.gt", ">=": "py.ge"}[op],
    )
    del observed  # documents the source operand pair beside each coordinate


@pytest.mark.parametrize(
    ("expression", "op_kind", "law_name", "atom"),
    (
        ("left < right", "Lt", "ordering", "py.lt"),
        ("needle in container", "In", "membership", "py.in"),
        ("left == right", "Eq", "equality", "py.eq"),
    ),
)
def test_undecided_dispatch_partition_keys_are_law_scoped(
    expression: str, op_kind: str, law_name: str, atom: str
) -> None:
    """Ordering / membership / equality dual edges use distinct partition families.

    The dual-edge construction is shared, but the ExitSet partition key names
    the law so residual measurement cannot collapse three mechanisms into one
    monomorphic ``comparison-native-dispatch`` coordinate.
    """
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.sugar.comparison_op_sugar import (
        CompareLaw,
        ComparisonOpSugar,
        compare_law_for,
        partition_key_for_law,
    )
    from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar

    assert compare_law_for(op_kind).value == law_name
    node = _synthetic_compare(expression)
    left = _ValueSugar(SymbolicValue(make_var("left")))
    right = _ValueSugar(SymbolicValue(make_var("right")))
    if op_kind == "Eq":
        outcome = EqualityOpSugar(left, right, node.fragment).desugar(None)
    elif op_kind == "In":
        outcome = ComparisonOpSugar(
            "In",
            _ValueSugar(SymbolicValue(make_var("needle"))),
            _ValueSugar(SymbolicValue(make_var("container"))),
            node.fragment,
        ).desugar(None)
    else:
        outcome = ComparisonOpSugar(op_kind, left, right, node.fragment).desugar(None)

    _assert_dual_dispatch(outcome, atom=atom, blame=str(node.fragment))
    expected_prefix = f"compare.{law_name}.dispatch"
    # partition() returns face stamps; law is sealed into the key used at mint.
    # Pin the key factory and that identity never dual-edges.
    assert partition_key_for_law(CompareLaw(law_name), node.fragment, op_kind)[0] == (
        expected_prefix
    )
    assert CompareLaw.IDENTITY not in (
        CompareLaw.ORDERING,
        CompareLaw.MEMBERSHIP,
        CompareLaw.EQUALITY,
    )


@pytest.mark.parametrize(("op_kind", "negated"), (("Is", False), ("IsNot", True)))
def test_identity_law_never_publishes_a_raise_partition(
    op_kind: str, negated: bool
) -> None:
    """Identity law is total for both ``is`` and ``is not``."""
    from sugar_lift_py_tests.floor import PredicateValue, SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.outcome import Complete, ExitSet
    from sugar_lift_py_tests.sugar.comparison_op_sugar import ComparisonOpSugar

    outcome = ComparisonOpSugar(
        op_kind,
        _ValueSugar(SymbolicValue(make_var("a"))),
        _ValueSugar(SymbolicValue(make_var("b"))),
        "identity-site",
    ).desugar(None)
    assert isinstance(outcome, Complete)
    assert not isinstance(outcome, ExitSet)
    assert isinstance(outcome.value, PredicateValue)
    assert ("not" in repr(outcome.value.formula)) is negated


def test_chained_comparison_composes_pair_ordering_laws() -> None:
    """Chaining law: ``a < b < c`` is And of pair ordering dual edges.

    Construction lives at ``Compare._construct_sugar`` (BoolOpSugar over
    adjacent ComparisonOpSugar pairs). Residual faces are ordered dual-edge
    composition under short-circuit And — not a monomorphic chain panic.
    """
    from sugar_lift_py_tests.ir import and_, atomic, make_var, not_
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

    node = _synthetic_compare("a < b < c")
    sugar = node.sugar()
    assert type(sugar).__name__ == "BoolOpSugar"
    assert sugar.op_kind == "And"
    assert len(sugar.values) == 2
    outcome = sugar.desugar(None)
    assert isinstance(outcome, ExitSet)
    halted = [face for face in outcome.exits if isinstance(face, Halted)]
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(halted) == 2
    assert halted[0].effect.occurrence_id != halted[1].effect.occurrence_id

    a, b, c = make_var("a"), make_var("b"), make_var("c")
    first_raises = atomic("python.lt_dispatch_raises", [a, b])
    first_true = atomic("py.lt", [a, b])
    second_raises = atomic("python.lt_dispatch_raises", [b, c])
    assert {face.guard for face in halted} == {
        first_raises,
        and_([not_(first_raises), and_([first_true, second_raises])]),
    }
    assert any(
        face.guard == and_([not_(first_raises), not_(first_true)]) for face in completed
    )


def test_chained_compare_leg_sites_follow_operator_occurrences_not_operands() -> None:
    """Repeated operand spelling cannot collapse two operator occurrences."""
    node = _synthetic_compare("left < left < left")
    sugar = node.sugar()

    first, second = sugar.values
    assert first.site.text.strip() == second.site.text.strip() == "<"
    assert first.site.source_cid == second.site.source_cid == node.fragment.source_cid
    assert first.site.line_col_span != second.site.line_col_span


def test_chained_compare_rejects_an_operator_coordinate_from_the_wrong_leg() -> None:
    """A same-spelling operator from leg one cannot authenticate leg two."""
    from sugar_source_tree.panic import SugarNotWritten

    node = _synthetic_compare("left < left < left")
    operands = (node.left, *node.comparators)
    tampered = (operands[0], operands[1], operands[1])

    with pytest.raises(SugarNotWritten, match="Compare._comparison_leg_site"):
        node._comparison_leg_site(1, tampered)


def test_decided_false_first_leg_emits_no_second_leg_occurrence() -> None:
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import Halted

    node = _synthetic_compare("2 < 1 < None")
    sugar = node.sugar()
    second_occurrence = str(sugar.values[1].site)
    outcome = sugar.desugar(None)

    effects = (
        tuple(exit_.effect for exit_ in outcome.exits if isinstance(exit_, Halted))
        if isinstance(outcome, ExitSet)
        else ()
    )
    assert all(effect.occurrence_id != second_occurrence for effect in effects)


def test_subscript_root_preserves_nested_compare_owned_halt() -> None:
    """The concrete 128th row keeps the Compare halt through Subscript."""
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import Halted

    path = _corpus_root() / "tests/series/indexing/test_getitem.py"
    source = path.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode()).hexdigest() == GETITEM_SITE_SHA256
    tree = SourceFile(
        (source, str(path), blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    subscript = next(
        node
        for node in tree.nodes()
        if isinstance(node, Subscript) and node.line_col_span().start_line == 595
    )
    comparison = next(
        node
        for node in tree.nodes()
        if isinstance(node, Compare) and node.line_col_span().start_line == 595
    )

    outcome = subscript.sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    compare_halt = next(
        face
        for face in outcome.exits
        if isinstance(face, Halted) and face.effect.producer_node_owner == "Compare"
    )
    assert compare_halt.effect.exception_name is None
    assert compare_halt.effect.blame == str(comparison.fragment)
