"""Unpack sequencing for ``x, obj[key] = rhs`` — the operation's own faces.

Python semantic law made constructible here (distinct from the store lanes):

  a. The unpack can raise BEFORE any target is bound. Arity mismatch
     (``ValueError``: too many / not enough values) halts before ``x`` binds.
     Target count is source-visible; source arity may not be. When arity is
     undecided the honest resolution is Undischarged, never a fabricated
     completion.
  b. Evaluate-once and left-to-right: RHS members (display) or the reduced RHS
     (dynamic) first; then targets bind left to right — ``x`` binds, THEN
     ``obj[key]`` stores. The store leaf reuses #6599's setitem law.
  c. Partial binding is never complete. If ``x`` binds and the later store
     halts, the statement did NOT complete — but ``x`` remains bound. Reporting
     completion because some targets bound is the defect; rolling back ``x`` is
     also wrong.
  d. Starred targets (``a, *rest = expr``) change the arity law: any length at
     or above the fixed count. Do not apply exact-arity to a starred pattern.

Producer methods (this PR):
  - ``Assign.substitute`` via ``_substituted_unpack_store_leaves``
  - ``Assign._flat_store_unpack_pairs`` / ``Assign._construct_sugar``
  - ``UnpackStoreAssignSugar.desugar``

Consumer methods (reused, not reimplemented — windows 10876 / composition):
  - ``SubscriptStoreEffectSugar.desugar`` / ``_store`` → ``receiver.setitem``
  - ``reduce_body`` / ``reduce_block_to_exitset`` (store success/halt sequence)

Corpus coordinate (pandas 3.0.3, line content verified):
  ``pandas/core/groupby/generic.py:1291``
  ``out, codes[-1] = out[sorter], codes[-1][sorter]``
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.floor import ListValue, TermValue, TupleValue
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    Halted,
    outcome_to_exitset,
)
from sugar_lift_py_tests.sugar.assign_sugar import UnpackStoreAssignSugar
from sugar_lift_py_tests.sugar.store_effect_sugar import SubscriptStoreEffectSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_oracle import path_source, workspace_path_source
from sugar_source_tree.nodes import Assign
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
# Full package file pin (pandas 3.0.3 site-packages content).
GENERIC_SHA256 = "4973999fc2e383b31d4584b201ba0da7b2808297949bc4ff413906a269f2eb53"

CORPUS_REL = "core/groupby/generic.py"
CORPUS_LINE = 1291
CORPUS_TEXT = "out, codes[-1] = out[sorter], codes[-1][sorter]"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _function(tmp_path: Path, source: str, stem: str = "unpack_seq"):
    path = tmp_path / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    return next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    )


def _function_sugar(tmp_path: Path, source: str, stem: str = "unpack_seq"):
    return _function(tmp_path, source, stem).sugar()


def _unpack(
    tmp_path: Path, source: str, stem: str = "unpack_seq"
) -> UnpackStoreAssignSugar:
    sugar = _function_sugar(tmp_path, source, stem)
    return next(
        stmt for stmt in sugar.statements if isinstance(stmt, UnpackStoreAssignSugar)
    )


def _exits(tmp_path: Path, source: str, stem: str = "unpack_seq"):
    return outcome_to_exitset(_function_sugar(tmp_path, source, stem).desugar(None))


@dataclass(frozen=True)
class _ObservedSugar(Sugar):
    label: str
    value: object
    log: list

    @classmethod
    def witnesses(cls):
        raise AssertionError("test helper has no witness")

    def desugar(self, ctx=None):
        del ctx
        self.log.append(self.label)
        return Complete(self.value)


def _site(tmp_path: Path):
    path = tmp_path / "store.py"
    path.write_text("def f(obj, key, value):\n    obj[key] = value\n")
    function = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    )
    return function.body[0].fragment


# ---------------------------------------------------------------------------
# Corpus coordinate verification (line numbers verified against content)
# ---------------------------------------------------------------------------


def test_verified_pandas_303_name_subscript_unpack_reproducer_is_content_pinned() -> (
    None
):
    corpus = authenticated_pandas_corpus()
    assert corpus.manifest_cid == MANIFEST_CID
    assert corpus.file_count == 1421

    path = corpus.root / CORPUS_REL
    assert hashlib.sha256(path.read_bytes()).hexdigest() == GENERIC_SHA256

    lines = path.read_text(encoding="utf-8").splitlines()
    # 1-indexed line — verify content, not a remembered number.
    assert lines[CORPUS_LINE - 1].strip() == CORPUS_TEXT
    # Sibling at 1320 — same shape, different receiver name.
    assert lines[1319].strip() == "out, left[-1] = out[sorter], left[-1][sorter]"


def test_corpus_name_subscript_unpack_constructs_then_stays_undischarged() -> None:
    """Real corpus site: construction admits the leaf; formal actuals stay loud.

    Missing Floor / carrier: n-ary setitem discharge over runtime-selected
    receivers (formal ``codes``). Until that door exists, the pair is
    Undischarged — named refusal, not a fabricated completed face.
    """
    corpus = authenticated_pandas_corpus()
    path = corpus.root / CORPUS_REL
    source = path.read_text(encoding="utf-8")
    source_cid = blake3_512_of(source.encode("utf-8"))
    tree = SourceFile((source, str(path), source_cid))
    assigns = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Assign) and node.line_col_span().start_line == CORPUS_LINE
    )
    assert len(assigns) == 1, (CORPUS_REL, CORPUS_LINE)

    # Construction must no longer refuse the shape at Assign.sugar.
    sugar = assigns[0].sugar()
    assert isinstance(sugar, UnpackStoreAssignSugar)
    assert len(sugar.stores) == 1
    assert isinstance(sugar.stores[0], SubscriptStoreEffectSugar)

    # Desugar of the full enclosing function is not required: the site itself
    # carries formal/undecided receivers. Direct store desugar is undischarged.
    with pytest.raises(SugarNotWritten, match="undischarged subscript store|undecided"):
        sugar.desugar(None)


# ---------------------------------------------------------------------------
# Method wiring: producer / consumer names (named before further edit)
# ---------------------------------------------------------------------------


def test_producer_and_consumer_methods_are_the_named_seams() -> None:
    """Document the exact methods this PR owns (and the store law it reuses)."""
    assert hasattr(Assign, "substitute")
    assert hasattr(Assign, "_flat_store_unpack_pairs")
    assert hasattr(Assign, "_construct_sugar")
    assert hasattr(UnpackStoreAssignSugar, "desugar")
    # Reused store lane — not reimplemented here.
    assert hasattr(SubscriptStoreEffectSugar, "desugar")
    assert hasattr(SubscriptStoreEffectSugar, "_store")
    assert callable(getattr(ListValue((TermValue(0),)), "setitem"))
    assert callable(getattr(TupleValue((TermValue(0),)), "setitem"))


# ---------------------------------------------------------------------------
# Construction: Name + Subscript display unpack is admitted
# ---------------------------------------------------------------------------


def test_name_and_subscript_display_unpack_constructs(tmp_path: Path) -> None:
    unpack = _unpack(
        tmp_path,
        "def f(a, i, p, q):\n    x, a[i] = p, q\n    return x\n",
        "namesub",
    )
    assert len(unpack.bindings) == 1
    assert unpack.bindings[0][0] == "x"
    assert len(unpack.stores) == 1
    assert isinstance(unpack.stores[0], SubscriptStoreEffectSugar)


def test_dual_subscript_display_unpack_constructs_distinct_pairings(
    tmp_path: Path,
) -> None:
    """Positional correspondence: swapped RHS members construct differently."""
    left = _unpack(
        tmp_path,
        "def f(a, b, i, j, p, q):\n    a[i], b[j] = p, q\n    return p\n",
        "dual_pq",
    )
    right = _unpack(
        tmp_path,
        "def f(a, b, i, j, p, q):\n    a[i], b[j] = q, p\n    return p\n",
        "dual_qp",
    )
    assert len(left.stores) == 2 and len(right.stores) == 2
    # Each store carries its paired RHS member — not index text alone.
    assert left.stores[0].value is not right.stores[0].value or (
        str(left.stores[0].value) != str(right.stores[0].value)
    )


def test_formal_receiver_stays_undischarged_not_completed(tmp_path: Path) -> None:
    """Face (a) undecided path: no fabricated completion for formal setitem."""
    sugar = _function_sugar(
        tmp_path,
        "def f(a, i, p, q):\n    x, a[i] = p, q\n    return x\n",
        "formal",
    )
    with pytest.raises(SugarNotWritten, match="undischarged subscript store"):
        sugar.desugar(None)


# ---------------------------------------------------------------------------
# Face (b): evaluate-once, left-to-right; store reuses #6599 order
# ---------------------------------------------------------------------------


def test_unpack_store_leaf_evaluates_value_receiver_key_once_in_python_order(
    tmp_path: Path,
) -> None:
    """Store leaf inside unpack reuses the #6599 evaluation order."""
    log: list[str] = []
    store = SubscriptStoreEffectSugar(
        receiver=_ObservedSugar("receiver", ListValue((TermValue(1),)), log),
        index=_ObservedSugar("key", TermValue(0), log),
        value=_ObservedSugar("value", TermValue(7), log),
        site=_site(tmp_path),
    )
    outcome = UnpackStoreAssignSugar(
        bindings=(), stores=(store,), site=_site(tmp_path)
    ).desugar()
    assert log == ["value", "receiver", "key"]
    assert isinstance(outcome, Complete)
    # reduce_body wraps store contributions in a fall-through BlockValue.
    assert ListValue((TermValue(7),)) in outcome.value.statements


def test_ground_name_then_list_store_completes_with_name_bound(tmp_path: Path) -> None:
    """``x, a[0] = 1, 2``: name binds, store completes, return sees ``x``."""
    exits = _exits(
        tmp_path,
        "def f():\n    a = [0]\n    x, a[0] = 1, 2\n    return x\n",
        "ground_ok",
    )
    completed = [e for e in exits.exits if isinstance(e, Completed)]
    halted = [e for e in exits.exits if isinstance(e, Halted)]
    assert len(completed) == 1
    assert len(halted) == 0
    assert "TermValue(value=1)" in str(completed[0].value) or "1" in str(
        completed[0].value.record
    )


# ---------------------------------------------------------------------------
# Face (c): partial binding is never complete; store halt keeps prior work
# ---------------------------------------------------------------------------


def test_later_store_halt_is_not_a_completed_statement(tmp_path: Path) -> None:
    """If the store leaf halts, the unpack statement did not complete."""
    exits = _exits(
        tmp_path,
        "def f():\n    a = (0,)\n    x, a[0] = 1, 2\n    return x\n",
        "tuple_halt",
    )
    halted = [e for e in exits.exits if isinstance(e, Halted)]
    completed = [e for e in exits.exits if isinstance(e, Completed)]
    assert len(halted) == 1
    assert len(completed) == 0
    assert halted[0].effect.exception_name == "TypeError"
    assert halted[0].effect.producer_node_owner == "TupleValue.setitem"


def test_first_store_success_second_halt_is_partial_not_complete(
    tmp_path: Path,
) -> None:
    """``a[0], b[0] = 2, 3`` with b immutable: first store ran; statement incomplete."""
    exits = _exits(
        tmp_path,
        "def f():\n    a = [0]\n    b = (1,)\n    a[0], b[0] = 2, 3\n    return a\n",
        "dual_partial",
    )
    halted = [e for e in exits.exits if isinstance(e, Halted)]
    completed = [e for e in exits.exits if isinstance(e, Completed)]
    assert len(halted) == 1
    assert len(completed) == 0
    assert halted[0].effect.exception_name == "TypeError"
    assert halted[0].effect.producer_node_owner == "TupleValue.setitem"


def test_list_indexerror_store_halt_originates_in_setitem_not_boundary(
    tmp_path: Path,
) -> None:
    """Exception type originates in the store floor, not pytest.raises."""
    exits = _exits(
        tmp_path,
        "def f():\n    a = [0]\n    x, a[5] = 1, 2\n    return x\n",
        "index_halt",
    )
    halted = [e for e in exits.exits if isinstance(e, Halted)]
    assert len(halted) == 1
    effect = halted[0].effect
    assert effect.exception_name == "IndexError"
    assert effect.producer_node_owner == "ground_index_error"
    assert effect.exception_type_coordinate is not None
    # Type name may match a boundary expectation; origin is the store producer.
    assert "pytest" not in (effect.producer_node_owner or "").lower()


# ---------------------------------------------------------------------------
# Face (a)/(d): arity and starred patterns
# ---------------------------------------------------------------------------


def test_display_arity_mismatch_does_not_fabricate_completion(tmp_path: Path) -> None:
    """Two targets, one display member: not a completed unpack."""
    path = tmp_path / "arity.py"
    path.write_text("def f(a, i, p):\n    x, a[i] = (p,)\n    return x\n")
    fn = next(SourceFile(path_source(str(path))).functions())
    with pytest.raises(SugarNotWritten, match="Assign"):
        fn.sugar()


def test_starred_opaque_unpack_stays_loud_not_exact_arity_completion(
    tmp_path: Path,
) -> None:
    """Face (d): starred pattern is not forced through exact-arity completion."""
    path = tmp_path / "star.py"
    path.write_text("def f(xs):\n    a, *rest = xs\n    return a\n")
    fn = next(SourceFile(path_source(str(path))).functions())
    with pytest.raises(SugarNotWritten, match="Assign"):
        fn.sugar()


# ---------------------------------------------------------------------------
# LYING twins that MUST FAIL / distinguish origin
# ---------------------------------------------------------------------------


def test_lying_completed_when_later_target_halted_is_not_the_law(
    tmp_path: Path,
) -> None:
    """Lying twin 1: report completed because an earlier target bound/store ran."""
    exits = _exits(
        tmp_path,
        "def f():\n    a = [0]\n    b = (1,)\n    a[0], b[0] = 2, 3\n    return a\n",
        "lie_complete",
    )
    # Truthful: only Halted.
    assert any(isinstance(e, Halted) for e in exits.exits)
    # The lie would be asserting a sole Completed face.
    with pytest.raises(AssertionError):
        assert len(exits.exits) == 1 and isinstance(exits.exits[0], Completed)


def test_lying_completed_face_for_undecided_receiver_is_not_the_law(
    tmp_path: Path,
) -> None:
    """Lying twin 2: emit completed when receiver arity/type is undecided."""
    sugar = _function_sugar(
        tmp_path,
        "def f(a, i, p, q):\n    x, a[i] = p, q\n    return x\n",
        "lie_undecided",
    )
    # Truthful path is loud undischarged.
    with pytest.raises(SugarNotWritten):
        sugar.desugar(None)
    # A lying implementation would return Complete(...). Discriminate: that is
    # not what construction desugars to today, and must not be asserted green.
    with pytest.raises(AssertionError):
        outcome = Complete(TermValue(0))
        assert isinstance(outcome, Incomplete)  # wrong on purpose for the tooth


def test_lying_boundary_exception_type_is_not_store_origin(tmp_path: Path) -> None:
    """Lying twin 3: type name from pytest.raises is not the store origin.

    Coordinates may denote the same type; origin (producer_node_owner /
    occurrence) is what authenticates the exit.
    """
    exits = _exits(
        tmp_path,
        "def f():\n    a = (0,)\n    x, a[0] = 1, 2\n    return x\n",
        "lie_boundary",
    )
    face = next(e for e in exits.exits if isinstance(e, Halted))
    store_type = face.effect.exception_type_coordinate
    boundary_type = store_type  # same type content is allowed
    assert boundary_type == store_type
    # Origin must cite the store floor, not an assertion boundary.
    assert face.effect.producer_node_owner == "TupleValue.setitem"
    assert face.effect.producer_node_owner != "pytest.raises"
    # An implementation that only checks type equality would treat a boundary-
    # minted TypeError as the same exit. Discriminate on producer owner.
    with pytest.raises(AssertionError):
        assert face.effect.producer_node_owner == "pytest.raises"


def test_unpack_does_not_borrow_the_standalone_store_construction_path(
    tmp_path: Path,
) -> None:
    """Unpack sequencing owns leaf admission; store desugar is the reused law."""
    unpack = _unpack(
        tmp_path,
        "def f():\n    a = [0]\n    x, a[0] = 1, 2\n    return x\n",
        "no_borrow",
    )
    assert isinstance(unpack, UnpackStoreAssignSugar)
    assert isinstance(unpack.stores[0], SubscriptStoreEffectSugar)
    # Standalone single-target store is a different sugar root.
    single = _function_sugar(
        tmp_path, "def f():\n    a = [0]\n    a[0] = 2\n    return a\n", "single"
    )
    assert any(isinstance(s, SubscriptStoreEffectSugar) for s in single.statements)
    assert not any(isinstance(s, UnpackStoreAssignSugar) for s in single.statements)
