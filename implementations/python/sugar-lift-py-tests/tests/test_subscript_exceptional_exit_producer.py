"""Subscript is an effect producer; unknown receiver types stay undecided."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (

    CallSiteValue,
    DictValue,
    ListValue,
    SetValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.no_call_body_attribution import (
    CANONICAL_CORPUS_MANIFEST_CID,
    CANONICAL_CORPUS_MANIFEST_SHA256,
    FAMILY_DENOMINATORS,
    HISTORICAL_PATH_SHAPE_DIGEST,
    AttributionOutcome,
    ProducerFamily,
    attribute_body_probes,
    discover_no_call_body_probes,
    require_expected_denominators,
)
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile

from sugar_lift_py_tests.repo_root import resolve_repo_root
from sugar_lift_py_tests.effect import RaiseEffect

SITE_SHA256 = "0308786b24b61a2b98be5d649e57ee847d7993ae1d0e1823d7f760408523131f"
# Content manifest (relative path + per-file BLAKE3-512): the one canonical
# coordinate, ``CANONICAL_CORPUS_MANIFEST_CID``, read by its own name. Path-shape
# sha256:a223… is historical negative testimony only — never identity.
MANIFEST_SHA256 = CANONICAL_CORPUS_MANIFEST_SHA256


REJECTED_VENDOR_FILTER_SEEDS = (
    (
        "tests/indexes/multi/test_sorting.py",
        147,
        'dfm.loc[1, "z"]',
        "assert_produces_warning",
    ),
    (
        "tests/indexing/multiindex/test_multiindex.py",
        29,
        'df.loc[1, "z"]',
        "assert_produces_warning",
    ),
    (
        "tests/indexing/multiindex/test_multiindex.py",
        33,
        "df.loc[0,]",
        "assert_produces_warning",
    ),
    (
        "tests/series/accessors/test_list_accessor.py",
        101,
        "ser.list[1:None:0]",
        "external_error_raised",
    ),
    (
        "tests/series/accessors/test_list_accessor.py",
        133,
        "ser.list[-1]",
        "external_error_raised",
    ),
    (
        "tests/series/accessors/test_list_accessor.py",
        135,
        "ser.list[5]",
        "external_error_raised",
    ),
)


@pytest.fixture(scope="module")
def authenticated_corpus():
    return authenticated_pandas_corpus()


@pytest.fixture(scope="module")
def authenticated_site(authenticated_corpus):
    corpus = authenticated_corpus
    assert corpus.manifest_cid == CANONICAL_CORPUS_MANIFEST_CID
    site = corpus.root / "tests/test_multilevel.py"
    assert hashlib.sha256(site.read_bytes()).hexdigest() == SITE_SHA256

    source = SourceFile(
        workspace_path_source(str(site), root=str(corpus.root.parent)),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(
        node
        for node in source.nodes()
        if type(node).__name__ == "Subscript" and node.fragment.line == 158
    )


@pytest.fixture
def local_site(tmp_path):
    source_path = tmp_path / "nested_tuple_subscript.py"
    source_path.write_text(
        "def nested_tuple_lookup(values):\n"
        '    key = (("foo", "bar", 0), 2)\n'
        "    return values[key]\n"
        "\n"
        "def control(values):\n"
        "    return values[0]\n",
        encoding="utf-8",
    )
    source = SourceFile(
        workspace_path_source(str(source_path), root=str(tmp_path)),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(function.fragment for function in source.functions())


def test_launcher_authenticates_the_exact_corpus() -> None:
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.manifest_cid, corpus.file_count) == (
        "3.0.3",
        CANONICAL_CORPUS_MANIFEST_CID,
        1421,
    )
    # Path-shape is refusal testimony, not an accepted corpus identity.
    assert corpus.manifest_cid != HISTORICAL_PATH_SHAPE_DIGEST
    assert MANIFEST_SHA256 == (
        "sha256:0ee4e945d69e60941f74ad064215a44d9f02a0b23b081e2a507d893bdd22a938"
    )


@pytest.mark.parametrize(
    "relative_path,line,expected_expression,expected_manager",
    REJECTED_VENDOR_FILTER_SEEDS,
)
def test_non_vendor_subscript_seed_is_real_and_has_no_call_descendant(
    authenticated_corpus,
    relative_path,
    line,
    expected_expression,
    expected_manager,
) -> None:
    corpus = authenticated_corpus
    source = (corpus.root / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=relative_path)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.With, ast.AsyncWith))
        and len(node.body) == 1
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Subscript)
        and node.body[0].value.lineno == line
    ]

    assert len(matches) == 1
    expression = matches[0].body[0].value
    assert ast.dump(expression, include_attributes=False) == ast.dump(
        ast.parse(expected_expression, mode="eval").body,
        include_attributes=False,
    )
    assert not any(isinstance(node, ast.Call) for node in ast.walk(expression))
    assert any(
        isinstance(item.context_expr, ast.Call)
        and (
            (
                isinstance(item.context_expr.func, ast.Name)
                and item.context_expr.func.id == expected_manager
            )
            or (
                isinstance(item.context_expr.func, ast.Attribute)
                and item.context_expr.func.attr == expected_manager
            )
        )
        for item in matches[0].items
    )


def test_authenticated_subscript_family_owns_no_construction_panics() -> None:
    corpus = authenticated_pandas_corpus()
    inventory = require_expected_denominators(
        discover_no_call_body_probes(
            corpus.root,
            families=frozenset({ProducerFamily.SUBSCRIPT}),
        ).probes,
        families=frozenset({ProducerFamily.SUBSCRIPT}),
    )
    probes = tuple(
        probe for probe in inventory if probe.family is ProducerFamily.SUBSCRIPT
    )
    report = attribute_body_probes(probes)
    row = report.by_family[ProducerFamily.SUBSCRIPT]
    reattributed_gaps = tuple(
        body
        for body in report.bodies
        if body.outcome is AttributionOutcome.CONSTRUCTION_PANIC
    )
    # Residual dual-edge index producers: data[ub + 1] follows the BinOp
    # dispatch partition; ser[df > 5] follows the Compare dispatch partition.
    # SubscriptSugar sequences those ExitSets so Halted faces survive when the
    # completed face cannot decide the lookup.  Each probe reduces its body
    # with no context, so the operands are undecided: the operation is the one
    # two-faced outcome (``_assert_two_faced_read``; the undecided binary and
    # comparison, #8318, #8620), whose raise has a type nothing here decides.
    # That halt is never dropped and never named a type it is not: such a body
    # is undischarged, its nameless face stated in the identity list.  Where
    # an operand is decided the exit is authenticated under its owner.
    required_exit_sites = {
        "tests/extension/base/getitem.py:147:Subscript": "BinOp",
        "tests/series/indexing/test_getitem.py:595:Subscript": "Compare",
    }
    required_non_vendor_sites = {
        "tests/indexes/multi/test_sorting.py:147:Subscript",
        "tests/indexing/multiindex/test_multiindex.py:29:Subscript",
        "tests/indexing/multiindex/test_multiindex.py:33:Subscript",
        "tests/series/accessors/test_list_accessor.py:101:Subscript",
        "tests/series/accessors/test_list_accessor.py:133:Subscript",
        "tests/series/accessors/test_list_accessor.py:135:Subscript",
    }

    print(row, flush=True)
    print(f"subscriptConstructionPanics={len(reattributed_gaps)}", flush=True)
    for gap in reattributed_gaps:
        print(
            f"constructionPanic site={gap.body_id} owner={gap.detail}",
            flush=True,
        )

    by_id = {body.body_id: body for body in report.bodies}
    undischarged = {
        body.body_id
        for body in report.bodies
        if body.outcome is AttributionOutcome.UNDISCHARGED
    }
    for body_id, owner in required_exit_sites.items():
        body = by_id.get(body_id)
        assert body is not None, body_id
        assert (
            body.outcome is AttributionOutcome.AUTHENTICATED_EXIT
            and body.detail == owner
        ) or body.outcome is AttributionOutcome.UNDISCHARGED, (
            body_id,
            body.outcome,
            body.detail,
        )

    assert row.enrolled == FAMILY_DENOMINATORS[ProducerFamily.SUBSCRIPT]
    assert {probe.body_id for probe in probes} >= required_non_vendor_sites
    # A body that left by none of the four arms (``AttributionInvariantError``:
    # it completed with no raise face, so a halt may have been dropped) is a
    # discrepancy, never an arm: name it before the total that misses it.
    assert report.discrepancies == (), report.discrepancies
    assert row.outcome_total == 392
    assert len(undischarged) == row.undischarged
    assert {
        discrepancy.body_id
        for discrepancy in report.exceptional_exit_identity_discrepancies
    } == undischarged
    assert report.conservation_shortfall == 0
    assert not reattributed_gaps, reattributed_gaps
    assert row.construction_panics == 0


def _assert_two_faced_read(outcome, owner: str | None = None) -> None:
    """The one two-faced unanswered read: completes under the subscript's
    completes atom, else an undetermined raise; owed at its site.  No
    KeyError or IndexError is guessed."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    halts = [
        arm
        for arm in outcome.exits
        if isinstance(arm, Halted) and isinstance(arm.effect, UndeterminedRaiseEffect)
    ]
    assert halts
    if owner is not None:
        assert [halt.effect.producer_node_owner for halt in halts] == [owner]
    completed = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert any("python:subscript_op.completes" in repr(arm.guard) for arm in completed)
    assert not [arm for arm in outcome.halts() if isinstance(arm.effect, RaiseEffect)]
    assert any(item.site is not None for item in owed_calls(outcome))


def test_real_pandas_unknown_receiver_is_two_faced(authenticated_site) -> None:
    receiver = CallSiteValue(
        "source-constructor",
        (),
        (),
        ctor("call:source-constructor", []),
        None,
    )
    temporal = TemporalContext.empty().bind_value("series", receiver)

    _assert_two_faced_read(
        authenticated_site.sugar().desugar(ReduceContext(temporal))
    )


def test_truthful_out_of_range_concrete_list_emits_index_error(
    local_site,
) -> None:
    outcome = fresh(ListValue, (TermValue(7),)).subscript(TermValue(1), local_site)

    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "IndexError"


def test_lying_in_range_concrete_list_does_not_emit_exception(
    local_site,
) -> None:
    outcome = fresh(ListValue, (TermValue(7),)).subscript(TermValue(0), local_site)

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), TermValue)
    assert outcome.completed_value().value == 7


def test_known_non_integer_list_index_emits_type_error(local_site) -> None:
    outcome = fresh(ListValue, (TermValue(7),)).subscript(TermValue(1.5), local_site)

    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "TypeError"


def test_unknown_list_index_is_the_two_faced_unanswered_read(local_site) -> None:
    outcome = fresh(ListValue, (TermValue(7),)).subscript(
        SymbolicValue(make_var("index")), local_site
    )

    _assert_two_faced_read(outcome, "ListValue.subscript")


@pytest.mark.parametrize(
    "receiver",
    (
        fresh(ListValue, (TermValue(7),)),
        TupleValue((TermValue(7),)),
        StringValue("x"),
    ),
)
def test_truthful_nested_tuple_index_emits_type_error(local_site, receiver) -> None:
    nested_key = TupleValue(
        (
            TupleValue((StringValue("foo"), StringValue("bar"), TermValue(0))),
            TermValue(2),
        )
    )

    outcome = receiver.subscript(nested_key, local_site)

    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "TypeError"


def test_lying_nested_tuple_key_must_not_be_guessed_for_unknown_receiver(
    local_site,
) -> None:
    nested_key = TupleValue(
        (
            TupleValue((StringValue("foo"), StringValue("bar"), TermValue(0))),
            TermValue(2),
        )
    )

    outcome = SymbolicValue(make_var("receiver")).subscript(nested_key, local_site)

    _assert_two_faced_read(outcome, "SymbolicValue.subscript")


def test_truthful_missing_dict_key_emits_key_error(local_site) -> None:
    outcome = fresh(DictValue, ((StringValue("a"), TermValue(1)),)).subscript(
        StringValue("missing"), local_site
    )

    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "KeyError"


def test_lying_present_dict_key_does_not_emit_exception(local_site) -> None:
    outcome = fresh(DictValue, ((StringValue("a"), TermValue(1)),)).subscript(
        StringValue("a"), local_site
    )

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), TermValue)
    assert outcome.completed_value().value == 1


def test_unhashable_dict_key_emits_type_error(local_site) -> None:
    outcome = fresh(DictValue, ()).subscript(
        fresh(ListValue, (TermValue(1),)), local_site
    )

    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "TypeError"


def test_number_receiver_emits_type_error(local_site) -> None:
    outcome = TermValue(7).subscript(TermValue(0), local_site)

    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "TypeError"


def test_set_receiver_emits_type_error(local_site) -> None:
    outcome = fresh(SetValue, (TermValue(1),)).subscript(TermValue(0), local_site)

    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "TypeError"
