"""Subscript is an effect producer; unknown receiver types stay undecided."""

from __future__ import annotations

import hashlib

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    DictValue,
    ListValue,
    RaiseValue,
    SetValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

SITE_SHA256 = "0308786b24b61a2b98be5d649e57ee847d7993ae1d0e1823d7f760408523131f"
# Content manifest (relative path + per-file BLAKE3-512). Path-shape
# sha256:a223… is historical negative testimony only — never identity.
MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
HISTORICAL_PATH_SHAPE_DIGEST = (
    "sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0"
)


@pytest.fixture(scope="module")
def authenticated_site():
    corpus = authenticated_pandas_corpus()
    assert corpus.manifest_cid == MANIFEST_CID
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
        "    key = ((\"foo\", \"bar\", 0), 2)\n"
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
        MANIFEST_CID,
        1421,
    )
    # Path-shape is refusal testimony, not an accepted corpus identity.
    assert corpus.manifest_cid != HISTORICAL_PATH_SHAPE_DIGEST


def test_real_pandas_unknown_receiver_is_named_undecided(authenticated_site) -> None:
    receiver = CallSiteValue(
        "source-constructor",
        (),
        (),
        ctor("call:source-constructor", []),
        None,
    )
    temporal = TemporalContext.empty().bind_value(
        "series", receiver
    )

    with pytest.raises(SugarNotWritten) as raised:
        authenticated_site.sugar().desugar(ReduceContext(temporal))

    assert raised.value.owner == "SymbolicValue.subscript"
    assert "undecided receiver runtime type" in raised.value.observed
    assert "KeyError" not in raised.value.observed
    assert "KeyError" not in raised.value.requested


def test_truthful_out_of_range_concrete_list_emits_index_error(
    local_site,
) -> None:
    outcome = ListValue((TermValue(7),)).subscript(
        TermValue(1), local_site
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "IndexError"


def test_lying_in_range_concrete_list_does_not_emit_exception(
    local_site,
) -> None:
    outcome = ListValue((TermValue(7),)).subscript(
        TermValue(0), local_site
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TermValue)
    assert outcome.value.value == 7


def test_known_non_integer_list_index_emits_type_error(local_site) -> None:
    outcome = ListValue((TermValue(7),)).subscript(
        TermValue(1.5), local_site
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


def test_unknown_list_index_is_a_named_third_value(local_site) -> None:
    with pytest.raises(SugarNotWritten) as raised:
        ListValue((TermValue(7),)).subscript(
            SymbolicValue(make_var("index")), local_site
        )

    assert raised.value.owner == "ListValue.subscript"
    assert "undecided" in raised.value.observed


@pytest.mark.parametrize(
    "receiver",
    (
        ListValue((TermValue(7),)),
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

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


def test_lying_nested_tuple_key_must_not_be_guessed_for_unknown_receiver(
    local_site,
) -> None:
    nested_key = TupleValue(
        (
            TupleValue((StringValue("foo"), StringValue("bar"), TermValue(0))),
            TermValue(2),
        )
    )

    with pytest.raises(SugarNotWritten) as raised:
        SymbolicValue(make_var("receiver")).subscript(nested_key, local_site)

    assert raised.value.owner == "SymbolicValue.subscript"
    assert "undecided receiver runtime type" in raised.value.observed


def test_truthful_missing_dict_key_emits_key_error(local_site) -> None:
    outcome = DictValue(((StringValue("a"), TermValue(1)),)).subscript(
        StringValue("missing"), local_site
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "KeyError"


def test_lying_present_dict_key_does_not_emit_exception(local_site) -> None:
    outcome = DictValue(((StringValue("a"), TermValue(1)),)).subscript(
        StringValue("a"), local_site
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TermValue)
    assert outcome.value.value == 1


def test_unhashable_dict_key_emits_type_error(local_site) -> None:
    outcome = DictValue(()).subscript(ListValue((TermValue(1),)), local_site)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


def test_number_receiver_emits_type_error(local_site) -> None:
    outcome = TermValue(7).subscript(TermValue(0), local_site)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


def test_set_receiver_emits_type_error(local_site) -> None:
    outcome = SetValue((TermValue(1),)).subscript(TermValue(0), local_site)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"
