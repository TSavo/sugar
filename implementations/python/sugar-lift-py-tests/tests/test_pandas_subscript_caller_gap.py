"""Pinned pandas Subscript helpers have no source caller to discharge them."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
)
from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import ListValue, SymbolicValue, TermValue
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, make_var, str_const
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Subscript
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)


@dataclass(frozen=True)
class _Candidate:
    relative_path: str
    helper_name: str
    helper_line: int
    with_line: int
    operation_line: int
    receiver_name: str
    index_name: str


EXPECTED_CANDIDATES = (
    _Candidate(
        "tests/extension/base/getitem.py",
        "test_getitem_integer_with_missing_raises",
        256,
        258,
        259,
        "data",
        "idx",
    ),
    _Candidate(
        "tests/indexes/test_any_index.py",
        "test_getitem_error",
        149,
        161,
        162,
        "index",
        "item",
    ),
)


def _read(path: Path, relative_path: str, overrides: dict[str, str]) -> str:
    return overrides.get(relative_path, path.read_text(encoding="utf-8"))


def _direct_formal_candidates(
    root: Path, *, overrides: dict[str, str] | None = None
) -> tuple[_Candidate, ...]:
    """Find the exact ``with pytest.raises(...): receiver[index]`` shape."""
    overrides = {} if overrides is None else overrides
    candidates = []
    for path in root.rglob("*.py"):
        relative_path = path.relative_to(root).as_posix()
        source = _read(path, relative_path, overrides)
        if "pytest.raises" not in source:
            continue
        tree = ast.parse(source, filename=relative_path)
        for helper in ast.walk(tree):
            if not isinstance(helper, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            formals = {
                argument.arg
                for argument in (
                    *helper.args.posonlyargs,
                    *helper.args.args,
                    *helper.args.kwonlyargs,
                )
            }
            for statement in ast.walk(helper):
                if not isinstance(statement, (ast.With, ast.AsyncWith)):
                    continue
                is_pytest_raises = any(
                    isinstance(item.context_expr, ast.Call)
                    and isinstance(item.context_expr.func, ast.Attribute)
                    and isinstance(item.context_expr.func.value, ast.Name)
                    and item.context_expr.func.value.id == "pytest"
                    and item.context_expr.func.attr == "raises"
                    for item in statement.items
                )
                if (
                    not is_pytest_raises
                    or len(statement.body) != 1
                    or not isinstance(statement.body[0], ast.Expr)
                    or not isinstance(statement.body[0].value, ast.Subscript)
                ):
                    continue
                operation = statement.body[0].value
                if (
                    not isinstance(operation.ctx, ast.Load)
                    or not isinstance(operation.value, ast.Name)
                    or not isinstance(operation.slice, ast.Name)
                    or operation.value.id not in formals
                    or operation.slice.id not in formals
                    or operation.value.id == operation.slice.id
                ):
                    continue
                candidates.append(
                    _Candidate(
                        relative_path,
                        helper.name,
                        helper.lineno,
                        statement.lineno,
                        operation.lineno,
                        operation.value.id,
                        operation.slice.id,
                    )
                )
    return tuple(sorted(candidates, key=lambda candidate: candidate.relative_path))


def _explicit_calls(
    root: Path,
    candidates: tuple[_Candidate, ...],
    *,
    overrides: dict[str, str] | None = None,
) -> tuple[tuple[str, int, str], ...]:
    overrides = {} if overrides is None else overrides
    names = {candidate.helper_name for candidate in candidates}
    calls = []
    for path in root.rglob("*.py"):
        relative_path = path.relative_to(root).as_posix()
        source = _read(path, relative_path, overrides)
        if not any(f"{name}(" in source for name in names):
            continue
        tree = ast.parse(source, filename=relative_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr if isinstance(node.func, ast.Attribute) else None
            )
            if name in names:
                calls.append((relative_path, node.lineno, name))
    return tuple(sorted(calls))


def _assert_no_source_caller(
    root: Path, *, overrides: dict[str, str] | None = None
) -> None:
    candidates = _direct_formal_candidates(root, overrides=overrides)
    assert candidates == EXPECTED_CANDIDATES
    assert _explicit_calls(root, candidates, overrides=overrides) == ()


def _authenticated_root() -> Path:
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.file_count, corpus.manifest_cid) == (
        "3.0.3",
        1421,
        MANIFEST_CID,
    )
    return corpus.root


def test_pinned_pandas_has_no_subscript_helper_caller_pair_to_discharge() -> None:
    """The corpus has helpers, but no source call supplies both actuals.

    Pytest fixture/parametrization injection is not a source call edge.  Until
    one definition-coordinate door projects ``__getitem__`` through a real
    formal-to-actual binding, these helpers must remain undischarged rather
    than borrow the exception expected by ``pytest.raises``.
    """
    _assert_no_source_caller(_authenticated_root())


def test_lying_inserted_caller_makes_the_absence_claim_fail() -> None:
    """Mutation tooth: a real call makes the honest-negative ratchet bite."""
    root = _authenticated_root()
    relative_path = "tests/indexes/test_any_index.py"
    source = (root / relative_path).read_text(encoding="utf-8")
    lying = source + "\n\ntest_getitem_error([1], 2)\n"

    with pytest.raises(AssertionError):
        _assert_no_source_caller(root, overrides={relative_path: lying})


def _formal_coordinate(
    site: object, name: str, ordinal: int
) -> FormalParameterCoordinateV1:
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
        ordinal=ordinal,
        parameter_kind="positional-or-keyword",
        declared_name=name,
        sort=PrimitiveSort("Value"),
    )


def _synthetic_carrier() -> tuple[
    NativeOperationExitCarrierV1,
    FormalParameterCoordinateV1,
    FormalParameterCoordinateV1,
]:
    """Construct the producer-only helper form; pandas absence is tested above."""
    source = "def helper(obj, key):\n    return obj[key]\n"
    tree = SourceFile(
        (source, "synthetic-subscript-helper.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    node = next(item for item in tree.nodes() if isinstance(item, Subscript))
    obj_coordinate = _formal_coordinate(node.fragment, "obj", 0)
    key_coordinate = _formal_coordinate(node.fragment, "key", 1)
    outcome = SymbolicValue(make_var("obj"), obj_coordinate).subscript(
        SymbolicValue(make_var("key"), key_coordinate), node.fragment
    )
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    return outcome, obj_coordinate, key_coordinate


def test_synthetic_formals_mint_the_getitem_carrier_door() -> None:
    """Synthetic boundary: formal ``obj[key]`` is resumable at a real caller.

    The real pandas absence is established above.  This synthetic arm names
    the general capability precisely: formal ``obj[key]`` mints a
    ``NativeOperationExitCarrierV1`` for ``subscript`` whose operation locus
    survives caller discharge.
    """
    carrier, obj_coordinate, key_coordinate = _synthetic_carrier()

    assert carrier.demand.operator == "subscript"
    assert carrier.demand.operand_coordinate_cids == (
        obj_coordinate.coordinate_cid,
        key_coordinate.coordinate_cid,
    )


def test_swapped_receiver_and_index_retain_distinct_ordered_coordinates() -> None:
    carrier, obj_coordinate, key_coordinate = _synthetic_carrier()
    swapped = SymbolicValue(make_var("key"), key_coordinate).subscript(
        SymbolicValue(make_var("obj"), obj_coordinate), carrier.site
    )

    assert isinstance(swapped, NativeOperationExitCarrierV1)
    assert swapped.demand.operand_coordinate_cids == (
        key_coordinate.coordinate_cid,
        obj_coordinate.coordinate_cid,
    )
    assert swapped.demand.demand_cid != carrier.demand.demand_cid


def test_coordinate_free_subscript_retains_existing_named_symbolic_refusal() -> None:
    carrier, _, _ = _synthetic_carrier()

    with pytest.raises(SugarNotWritten) as raised:
        SymbolicValue(make_var("obj")).subscript(
            SymbolicValue(make_var("key")), carrier.site
        )

    assert raised.value.owner == "SymbolicValue.subscript"
    assert "undecided receiver runtime type" in raised.value.observed


def test_helper_alone_stays_named_undischarged() -> None:
    carrier, _, _ = _synthetic_carrier()

    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        carrier.discharge({})


def test_caller_actuals_can_complete_the_original_subscript() -> None:
    carrier, obj_coordinate, key_coordinate = _synthetic_carrier()

    exits = carrier.discharge(
        {
            obj_coordinate.coordinate_cid: ListValue((TermValue(7),)),
            key_coordinate.coordinate_cid: TermValue(0),
        }
    )

    assert exits.exits == (Completed(exits.exits[0].guard, TermValue(7)),)


def test_caller_actuals_can_name_an_exception_at_the_original_subscript() -> None:
    carrier, obj_coordinate, key_coordinate = _synthetic_carrier()

    exits = carrier.discharge(
        {
            obj_coordinate.coordinate_cid: ListValue((TermValue(7),)),
            key_coordinate.coordinate_cid: TermValue(1),
        }
    )

    assert len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate is not None
    assert halted.effect.occurrence_id == str(carrier.demand.source_node.wire())


class _Expected:
    def __init__(self, name: str):
        self.identity = ctor(
            "python:exception_type_identity",
            [str_const("builtins"), str_const(name)],
        )

    def exception_type_identity(self):
        return self.identity


def test_lying_boundary_exception_type_leaves_operation_halted_and_unconsumed() -> None:
    carrier, obj_coordinate, key_coordinate = _synthetic_carrier()
    exits = carrier.discharge(
        {
            obj_coordinate.coordinate_cid: ListValue((TermValue(7),)),
            key_coordinate.coordinate_cid: TermValue(1),
        }
    )

    routed = exits.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected("ValueError")),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )

    assert len(routed.exits) == 1
    assert isinstance(routed.exits[0], Halted)
    assert routed.exits[0].effect.occurrence_id == str(carrier.demand.source_node.wire())
    assert (
        routed.exits[0].effect.exception_type_coordinate
        != _Expected("ValueError").identity
    )


def test_undecided_caller_receiver_stays_loud() -> None:
    carrier, obj_coordinate, key_coordinate = _synthetic_carrier()

    with pytest.raises(SugarNotWritten) as raised:
        carrier.discharge(
            {
                obj_coordinate.coordinate_cid: SymbolicValue(make_var("actual_obj")),
                key_coordinate.coordinate_cid: TermValue(0),
            }
        )

    assert raised.value.owner == "SymbolicValue.subscript"
    assert "undecided receiver runtime type" in raised.value.observed


def test_undecided_caller_key_stays_loud() -> None:
    carrier, obj_coordinate, key_coordinate = _synthetic_carrier()

    with pytest.raises(SugarNotWritten) as raised:
        carrier.discharge(
            {
                obj_coordinate.coordinate_cid: ListValue((TermValue(7),)),
                key_coordinate.coordinate_cid: SymbolicValue(make_var("actual_key")),
            }
        )

    assert raised.value.owner == "ListValue.subscript"
    assert "undecided" in raised.value.observed
