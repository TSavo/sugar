"""Corpus teeth for discharging a formal BinOp at a real pandas caller."""

from __future__ import annotations

import ast
import csv
from dataclasses import dataclass
import importlib.metadata
from pathlib import Path

import pandas as pd
import pandas._testing as tm
import pytest
from pandas import Series, Timedelta

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import CallSiteValue, StringValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
from sugar_lift_py_tests.source_call_resolution import SourceCallPreconstructionRefV1
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_call_preconstruction import (
    populate_source_visible_call_frames,
)
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.nodes import Call as SourceCall
from sugar_source_tree.nodes import BinOp as SourceBinOp
from sugar_source_tree.tree import SourceFile

MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
HELPER_PATH = "tests/arithmetic/common.py"
CALLER_PATH = "tests/arithmetic/test_timedelta64.py"
KEYWORD_CALLER_PATH = "tests/arithmetic/test_datetime64.py"
NESTED_DEFAULT_CALLER_PATH = "tests/util/test_deprecate_nonkeyword_arguments.py"


@dataclass(frozen=True)
class _Pair:
    helper: ast.FunctionDef
    operation: ast.BinOp
    caller: ast.FunctionDef
    call: ast.Call


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    assert len(matches) == 1
    return matches[0]


def _pair(
    *, helper_source: str | None = None, caller_source: str | None = None
) -> _Pair:
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.file_count, corpus.manifest_cid) == (
        "3.0.3",
        1421,
        MANIFEST_CID,
    )
    helper_source = (
        (corpus.root / HELPER_PATH).read_text(encoding="utf-8")
        if helper_source is None
        else helper_source
    )
    caller_source = (
        (corpus.root / CALLER_PATH).read_text(encoding="utf-8")
        if caller_source is None
        else caller_source
    )

    helper = _function(ast.parse(helper_source), "assert_invalid_addsub_type")
    operations = tuple(
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.BinOp)
        and isinstance(node.left, ast.Name)
        and isinstance(node.right, ast.Name)
        and (node.left.id, node.right.id) == ("left", "right")
        and isinstance(node.op, ast.Add)
    )
    assert len(operations) == 1
    operation = operations[0]
    assert operation.lineno == 55

    caller_tree = ast.parse(caller_source)
    imports = tuple(
        node
        for node in caller_tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "pandas.tests.arithmetic.common"
        and any(alias.name == "assert_invalid_addsub_type" for alias in node.names)
    )
    assert len(imports) == 1
    assert imports[0].lineno == 31

    caller = _function(caller_tree, "test_td64arr_addsub_numeric_scalar_invalid")
    rendered_decorators = tuple(ast.unparse(item) for item in caller.decorator_list)
    assert any(
        "pytest.mark.parametrize('other', ['a', 1, 1.5, np.array(2)])" == item
        for item in rendered_decorators
    )
    assignments = tuple(
        ast.unparse(node)
        for node in caller.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    )
    assert any(
        "tdser = Series(['59 Days', '59 Days', 'NaT'], dtype='m8[ns]')" == assignment
        for assignment in assignments
    )
    calls = tuple(
        node
        for node in ast.walk(caller)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "assert_invalid_addsub_type"
    )
    assert len(calls) == 1
    call = calls[0]
    assert call.lineno == 1172
    assert tuple(ast.unparse(arg) for arg in call.args) == ("tdarr", "other")
    return _Pair(helper, operation, caller, call)


def _actuals():
    """The concrete ``box_with_array=pd.array, other='a'`` caller arm."""
    tdser = Series(["59 Days", "59 Days", "NaT"], dtype="m8[ns]")
    return tm.box_expected(tdser, pd.array), "a"


def _keyword_call(*, caller_source: str | None = None) -> ast.Call:
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.file_count, corpus.manifest_cid) == (
        "3.0.3",
        1421,
        MANIFEST_CID,
    )
    source = (
        (corpus.root / KEYWORD_CALLER_PATH).read_text(encoding="utf-8")
        if caller_source is None
        else caller_source
    )
    caller = _function(ast.parse(source), "test_dt64arr_addsub_time_objects_raises")
    calls = tuple(
        node
        for node in ast.walk(caller)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "assert_invalid_addsub_type"
        and any(keyword.arg == "msg" for keyword in node.keywords)
    )
    assert len(calls) == 1
    call = calls[0]
    assert call.lineno == 1221
    assert tuple(ast.unparse(arg) for arg in call.args) == ("obj1", "obj2")
    assert tuple((item.arg, ast.unparse(item.value)) for item in call.keywords) == (
        ("msg", "msg"),
    )
    return call


def _nested_default_pair(*, source: str | None = None):
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.file_count, corpus.manifest_cid) == (
        "3.0.3",
        1421,
        MANIFEST_CID,
    )
    source = (
        (corpus.root / NESTED_DEFAULT_CALLER_PATH).read_text(encoding="utf-8")
        if source is None
        else source
    )
    tree = ast.parse(source)
    helper = _function(tree, "f")
    assert helper.lineno == 18
    assert tuple(argument.arg for argument in helper.args.args) == (
        "a",
        "b",
        "c",
        "d",
    )
    assert tuple(ast.unparse(default) for default in helper.args.defaults) == (
        "0",
        "0",
        "0",
    )
    returned = next(node for node in helper.body if isinstance(node, ast.Return))
    assert returned.lineno == 19
    assert ast.unparse(returned.value) == "a + b + c + d"

    calls = tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "f"
        and node.lineno in {28, 33, 38}
    )
    assert tuple(call.lineno for call in calls) == (28, 33, 38)
    assert tuple(ast.unparse(call) for call in calls) == (
        "f(19)",
        "f(19, d=6)",
        "f(1, 5)",
    )
    return source, calls


def test_helper_alone_has_only_formals_so_exception_identity_is_undischarged() -> None:
    """The helper occurrence authenticates an operation, never caller actuals."""
    pair = _pair()

    assert ast.unparse(pair.operation) == "left + right"
    assert tuple(argument.arg for argument in pair.helper.args.args[:2]) == (
        "left",
        "right",
    )
    assert all(
        isinstance(operand, ast.Name)
        for operand in (pair.operation.left, pair.operation.right)
    )


def test_real_omitted_and_keyword_helper_call_coordinates_are_pinned() -> None:
    default_pair = _pair()
    keyword_call = _keyword_call()

    assert default_pair.call.lineno == 1172
    assert not default_pair.call.keywords
    assert keyword_call.lineno == 1221
    assert keyword_call.keywords[0].arg == "msg"


def test_lying_keyword_caller_coordinate_is_rejected() -> None:
    corpus = authenticated_pandas_corpus()
    caller = (corpus.root / KEYWORD_CALLER_PATH).read_text(encoding="utf-8")
    lying = caller.replace(
        "assert_invalid_addsub_type(obj1, obj2, msg=msg)",
        "assert_invalid_addsub_type(obj1, obj2, expected=msg)",
        1,
    )

    with pytest.raises(AssertionError):
        _keyword_call(caller_source=lying)


def test_real_nested_default_binop_helper_and_callers_are_content_pinned() -> None:
    _, calls = _nested_default_pair()

    assert calls[0].args[0].value == 19
    assert calls[1].keywords[0].arg == "d"
    assert tuple(argument.value for argument in calls[2].args) == (1, 5)


def test_lying_nested_default_caller_coordinate_is_rejected() -> None:
    corpus = authenticated_pandas_corpus()
    source = (corpus.root / NESTED_DEFAULT_CALLER_PATH).read_text(encoding="utf-8")
    lying = source.replace("f(19, d=6)", "f(19, c=6)", 1)

    with pytest.raises(AssertionError):
        _nested_default_pair(source=lying)


def test_real_nested_default_binop_callers_name_only_binary_carrier_residuals() -> None:
    """Frames exist; only the nested BinOp dispatch carriers remain undecided."""
    source, _ = _nested_default_pair()
    tree = SourceFile(
        (
            source,
            NESTED_DEFAULT_CALLER_PATH,
            blake3_512_of(source.encode()),
        ),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    calls = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, SourceCall) and node.lineno in {28, 33, 38}
    )

    outcomes = tuple(call.sugar().desugar(None) for call in calls)

    assert len(outcomes) == 3
    for outcome in outcomes:
        assert isinstance(outcome, ExitSet)
        completed = tuple(
            exit_ for exit_ in outcome.exits if isinstance(exit_, Completed)
        )
        halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
        assert len(completed) == 1
        assert isinstance(completed[0].value, CallSiteValue)
        assert completed[0].value.source_call_frame_cid is not None
        assert len(halted) == 2
        assert all(
            "python.binary_dispatch_raises" in repr(exit_.guard)
            and exit_.effect.producer_node_owner == "Call"
            and exit_.effect.exception_type_coordinate is None
            for exit_ in halted
        )


def test_runtime_truth_names_the_candidate_exception_without_licensing_floor() -> None:
    """Runtime identifies TypeError; this alone cannot authenticate the Floor."""
    _pair()
    left, right = _actuals()

    with pytest.raises(TypeError) as raised:
        left + right

    assert type(raised.value) is TypeError
    assert type(raised.value).__module__ == "builtins"
    # The real helper consumes the same operation at the real caller arm.
    from pandas.tests.arithmetic.common import assert_invalid_addsub_type

    assert assert_invalid_addsub_type(left, right) is None


def test_candidate_pair_existing_floor_remains_undischarged() -> None:
    """The current call-result floor cannot authenticate TimedeltaArray + str.

    Caller substitution constructs ``tdarr`` through ``tm.box_expected``.  Its
    current Floor category is therefore a call result, not a source-decided
    TimedeltaArray.  The binary law conserves both runtime faces, but its halt
    has no exception-type coordinate.  #6588 classifies exactly this shape as
    Undischarged; borrowing ``pytest.raises(TypeError)`` would fabricate it.
    """
    pair = _pair()
    left = CallSiteValue(
        "tm.box_expected",
        (),
        (),
        ctor("call:tm.box_expected", []),
        None,
    )

    outcome = left.add(StringValue("a"), f"{HELPER_PATH}:{pair.operation.lineno}")

    halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
    completed = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Completed))
    assert len(halted) == 1
    assert len(completed) == 1
    assert halted[0].effect.exception_type_coordinate is None


def test_authenticated_box_expected_actual_names_type_error_edge(
    tmp_path: Path,
) -> None:
    """An authenticated attributed producer supplies the real helper's Floor."""
    pair = _pair()
    package = tmp_path / "unprivileged"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from unprivileged.helpers import box_expected\n", encoding="utf-8"
    )
    (package / "helpers.py").write_text(
        "def box_expected(expected):\n    return expected\n", encoding="utf-8"
    )
    metadata = tmp_path / "unprivileged_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: unprivileged-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("unprivileged/__init__.py", "", ""))
        writer.writerow(("unprivileged/helpers.py", "", ""))
        writer.writerow(("unprivileged_dist-1.0.dist-info/METADATA", "", ""))
        writer.writerow(("unprivileged_dist-1.0.dist-info/RECORD", "", ""))
    distribution = importlib.metadata.Distribution.at(metadata)

    actual_source = (
        "import unprivileged as tm\n"
        "def actual():\n"
        "    return tm.box_expected((1,))\n"
        "actual()\n"
    )
    actual_path = tmp_path / "real-binop-actual.py"
    actual_path.write_text(actual_source, encoding="utf-8")
    actual_context = TreeConstructionContextV1.for_source_call_construction(
        workspace_root=str(tmp_path)
    )
    actual_tree = SourceFile(
        workspace_path_source(str(actual_path), root=str(tmp_path)),
        construction_context=actual_context,
    )
    calls = tuple(node for node in actual_tree.nodes() if isinstance(node, SourceCall))
    actual_call = next(
        call for call in calls if getattr(call.func, "attr", None) == "box_expected"
    )
    populate_source_visible_call_frames(
        actual_tree,
        root=tmp_path,
        path=actual_path,
        distribution_index={"unprivileged": distribution},
    )

    actual_outcome = actual_call.sugar().desugar(None)
    assert hasattr(actual_outcome, "value")
    actual_return = actual_outcome.value.force_floor(
        None, owner="authenticated attributed producer", project_callsite=False
    ).statements[0]
    assert type(actual_return.value).__name__ == "TupleValue"
    corpus = authenticated_pandas_corpus()
    helper_path = corpus.root / HELPER_PATH
    helper_tree = SourceFile(
        workspace_path_source(str(helper_path), root=str(corpus.root.parent)),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    helper_operation = next(
        node
        for node in helper_tree.nodes()
        if isinstance(node, SourceBinOp)
        and node.line_col_span().start_line == pair.operation.lineno
    )
    produced = actual_return.value.add(StringValue("a"), helper_operation.fragment)
    raised = produced.value
    assert raised.effect.exception_type_coordinate == ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("TypeError")],
    )

    from sugar_lift_py_tests.context_manager_contract import (
        AuthenticatedRaiseMatcher,
        EffectBoundaryDisposition,
    )
    from sugar_lift_py_tests.effect import ExpectationNotMetEffect
    from sugar_lift_py_tests.outcome.exit_set import true_guard
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    class _WrongExpected:
        def exception_type_identity(self):
            return ctor(
                "python:exception_type_identity",
                [str_const("builtins"), str_const("ValueError")],
            )

    original = Halted(true_guard(), raised.effect, _ReducedBlock((), False, ()))
    routed = ExitSet((original,)).and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(_WrongExpected()),
            unmet=ExpectationNotMetEffect("raise", helper_operation.fragment),
        ),
    )
    assert routed.exits == (original,)


def test_installed_box_expected_source_call_has_an_authenticated_frame(
    tmp_path: Path,
) -> None:
    """Seam-1 specimen: installed ``tm.box_expected`` keeps its authenticated frame.

    Unrelated class/method body panics (Compare leg site in numpy_ arrays)
    must not erase the box_expected frame. Reachable-only source-frame
    construction parks incomplete callees; the leg-site panic itself is not
    weakened when that definition is the authenticated target.
    """
    source = (
        "import pandas as pd\n"
        "import pandas._testing as tm\n"
        "actual = tm.box_expected((1,), pd.array)\n"
    )
    path = tmp_path / "installed-box-actual.py"
    path.write_text(source, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction(
        workspace_root=str(tmp_path)
    )
    tree = SourceFile(
        workspace_path_source(str(path), root=str(tmp_path)),
        construction_context=context,
    )
    call = next(
        node
        for node in tree.nodes()
        if isinstance(node, SourceCall)
        and getattr(node.func, "attr", None) == "box_expected"
    )

    populate_source_visible_call_frames(tree, root=tmp_path, path=path)

    span = call.line_col_span()
    coordinate = SourceFragmentCoordinateV1(
        tree.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    assert isinstance(
        context.source_call_resolutions[coordinate],
        SourceCallPreconstructionRefV1,
    )
    result = (
        call.sugar()
        .desugar(None)
        .value._dig_floor_or_none(None, owner="installed box_expected return")
    )
    assert result is not None
    assert not isinstance(result, CallSiteValue)
    produced = result.add(StringValue("a"), call.fragment)
    halted = tuple(exit_ for exit_ in produced.exits if isinstance(exit_, Halted))
    assert len(halted) == 1
    assert halted[0].effect.exception_type_coordinate == ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("TypeError")],
    )


def test_runtime_wrong_expected_type_does_not_consume_candidate_exception() -> None:
    """At runtime a ValueError boundary leaves the candidate TypeError outside."""
    _pair()
    left, right = _actuals()

    with pytest.raises(TypeError) as escaped:
        with pytest.raises(ValueError):
            left + right

    assert type(escaped.value) is TypeError


def test_runtime_candidate_completes_for_normal_actuals() -> None:
    """Runtime completion is a candidate twin, not authenticated Floor proof."""
    pair = _pair()
    left, _ = _actuals()

    result = left + Timedelta("1D")

    assert ast.unparse(pair.operation) == "left + right"
    assert result.dtype == left.dtype
    assert result[0] == Timedelta("60D")


def test_lying_caller_coordinate_is_rejected_before_it_can_be_evidence() -> None:
    """Mutation tooth: a nearby but different helper call is not this pair."""
    corpus = authenticated_pandas_corpus()
    caller = (corpus.root / CALLER_PATH).read_text(encoding="utf-8")
    lying = caller.replace(
        "assert_invalid_addsub_type(tdarr, other)",
        "assert_invalid_addsub_type(other, tdarr)",
        1,
    )

    with pytest.raises(AssertionError):
        _pair(caller_source=lying)
