"""Real pandas unpack-setitem coordinate production faces.

Corpus (pandas 3.0.3, content-verified):

  ``core/groupby/generic.py:1291``
  ``out, codes[-1] = out[sorter], codes[-1][sorter]``

Shape: Name + Subscript store unpack (``out`` binds, then ``codes[-1]`` stores).
Construction admits the leaf as ``DynamicUnpackStoreAssignSugar`` (the one
unpack, a display right-hand side among them, #7757 S2) +
``SubscriptStoreEffectSugar``.  The setitem half is the one item mutation
(``store_effect_sugar.item_mutation``, #7757 step 7): source evaluation is
value→receiver→index; the dispatched call is receiver→index→value.  A later
store halt keeps the earlier-binding state without fabricated completion.

Does not touch carrier, reducer, ExitSet, setitem producer/projector, or census.
"""

from __future__ import annotations

import hashlib

import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import ListValue, TermValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.assign_sugar import DynamicUnpackStoreAssignSugar
from sugar_lift_py_tests.sugar.store_effect_sugar import SubscriptStoreEffectSugar
from sugar_lift_py_tests.sugar.unpack_projection_targets import (
    NameUnpackTarget,
    StoreUnpackTarget,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Assign, Call, FunctionDef
from sugar_lift_py_tests.lift_rpc import tree_construction_context_for_workspace
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile

MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
GENERIC_SHA256 = "4973999fc2e383b31d4584b201ba0da7b2808297949bc4ff413906a269f2eb53"
CORPUS_REL = "core/groupby/generic.py"
CORPUS_LINE = 1291
CORPUS_TEXT = "out, codes[-1] = out[sorter], codes[-1][sorter]"

# Isomorphic production program: same Name+Subscript unpack shape as the corpus
# site, with formals.
ISOMORPH = (
    "def f(out, codes, i, sorter, rhs_out, rhs_store):\n"
    "    out, codes[i] = rhs_out, rhs_store\n"
    "    return out\n"
)

# Since #8925 ``codes`` above takes ``class:codes`` as an input of ``f``'s
# contract (an item store through an unpack leaf is read as ``codes[i] = v``
# is), so its store is the dispatched ``__setitem__`` edge, owed with its halt
# kept and answered at prove by the class each caller binds (#8864).  No item
# store waits on a caller's actual (#7757 step 7), so the same unpack on a
# formal whose class is no input -- ``held = codes`` reads ``codes`` bare, and
# the store goes through ``held`` -- is the undecided mutation, owed on both
# faces, its halt kept with the block's state.
ISOMORPH_UNDECIDED = (
    "def f(out, codes, i, sorter, rhs_out, rhs_store):\n"
    "    held = codes\n"
    "    out, held[i] = rhs_out, rhs_store\n"
    "    return out\n"
)

# The same unpack on a list the frame built: the receiver is decided, so the
# store is the list's own (``ListValue.setitem``), here at a bad index.
ISOMORPH_BAD_INDEX = (
    "def f(out, rhs_out):\n"
    "    codes = [0]\n"
    "    out, codes[5] = rhs_out, 99\n"
    "    return out\n"
)


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def _tree(source: str, name: str = "pandas_unpack_setitem.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _desugared(source: str, name: str):
    """``source``'s one function alone and its own proof's reduction."""
    tree = _tree(source, name)
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _isomorph_dispatched():
    """``ISOMORPH`` alone: ``codes``'s class is an input (#8925), so the
    unpack leaf store is the dispatched edge."""
    return _desugared(ISOMORPH, "isomorph_alone.py")


def _isomorph_undecided():
    """``ISOMORPH_UNDECIDED`` alone: the store is the undecided mutation."""
    return _desugared(ISOMORPH_UNDECIDED, "isomorph_undecided_alone.py")


def _dispatched_call(outcome, method: str = "__setitem__"):
    """The dispatched store's coordinate ``call:dispatch:<method>(<receiver>,
    <operands>..., py.class("0", class:<receiver>))``, read off the one halt
    its edge owes (``python:raised(<call term>, <occurrence>)``)."""
    from sugar_lift_py_tests.call_symbol import call_symbol
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    assert isinstance(outcome, ExitSet), type(outcome)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == f"UnknownCallee:dispatch:{method}"
    ]
    assert len(halts) == 1, outcome
    assert halts[0].state is not None
    assert f"python:dispatch:{method}" in {
        call.symbol for call in owed_calls(outcome)
    }
    raised = halts[0].effect.raised_by_call
    assert raised.name == "python:raised", raised
    call = raised.args[0]
    assert call.name == call_symbol(f"dispatch:{method}"), call
    return call


def _undecided_store(outcome):
    """The undecided mutation (``item_mutation`` over a receiver whose type
    nothing here decides, ``undecided_item_mutation_faces``): no carrier and
    no dispatched edge; one undetermined halt owned by ``UndecidedSetitem``,
    kept with the block's state; every completed face under the store's own
    ``python:setitem.completes`` atom; both faces owing the undecided member
    (symbol ``None``)."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    assert isinstance(outcome, ExitSet), type(outcome)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "UndecidedSetitem"
    ]
    assert len(halts) == 1, outcome
    (halt,) = halts
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.state is not None
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome
    for face in (halt, *completed):
        assert None in {call.symbol for call in owed_calls(ExitSet((face,)))}
    for face in completed:
        assert "python:setitem.completes" in str(face.guard)
    assert "python:dispatch:__setitem__" not in {
        call.symbol for call in owed_calls(outcome)
    }
    assert outcome.completed_value() is None


def _floor_store(receiver, index, value):
    """The one item mutation on a receiver the lift decided (the ``ListValue``
    a caller hands ``codes``): the list's own store, at the unpack's site."""
    from sugar_lift_py_tests.sugar.store_effect_sugar import item_mutation

    tree = _tree(ISOMORPH_UNDECIDED, "floor_store_site.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    site = function.body[1].fragment
    return item_mutation("__setitem__", receiver, (index, value), site, None, unit=None)


def _bad_index_halt() -> Halted:
    """``ISOMORPH_BAD_INDEX`` alone: its sole face, the store's named
    ``IndexError``, kept with the block's record."""
    _, exits = _desugared(ISOMORPH_BAD_INDEX, "isomorph_bad_index.py")
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1, exits
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    return halted


# ---------------------------------------------------------------------------
# Real corpus coordinate
# ---------------------------------------------------------------------------


def test_pandas_303_groupby_generic_1291_is_content_pinned() -> None:
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.file_count, corpus.manifest_cid) == (
        "3.0.3",
        1421,
        MANIFEST_CID,
    )
    path = corpus.root / CORPUS_REL
    assert hashlib.sha256(path.read_bytes()).hexdigest() == GENERIC_SHA256
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[CORPUS_LINE - 1].strip() == CORPUS_TEXT
    # Sibling same shape, different receiver.
    assert lines[1319].strip() == "out, left[-1] = out[sorter], left[-1][sorter]"


def test_real_coordinate_constructs_unpack_store_with_setitem_leaf() -> None:
    """Production construction at the real assign: Name bind + setitem store."""
    corpus = authenticated_pandas_corpus()
    path = corpus.root / CORPUS_REL
    # The corpus is an INSTALLED DISTRIBUTION: its address is the seat the
    # distribution recorded (`pandas/core/...`), relative to the INSTALL root --
    # not to `corpus.root`, which is `site-packages/pandas`. The oracle refuses a
    # locus derived from any other root, because such an address resolves in no
    # other checkout. The module door was checked first and is unusable here: it
    # answers with an ABSOLUTE filename, which yields no workspace-relative
    # identity at all.
    tree = SourceFile(
        workspace_path_source(str(path), root=str(corpus.root.parent)),
        # LOCUS root and CONTEXT root differ ON PURPOSE. The locus must be the
        # seat the distribution recorded (relative to the install root) or the
        # oracle refuses it. The context must NOT be rooted there: building a
        # context over all of site-packages materializes every installed
        # distribution and dies in numpy. It does not need to be -- workspace_root
        # is only a BOOLEAN GATE on the bridge branch; the symbol itself derives
        # from unit.filename, which the locus already fixed.
        construction_context=tree_construction_context_for_workspace(corpus.root),
    )
    assigns = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Assign) and node.line_col_span().start_line == CORPUS_LINE
    )
    assert len(assigns) == 1
    sugar = assigns[0].sugar()
    assert isinstance(sugar, DynamicUnpackStoreAssignSugar)
    names = [t.name for t in sugar.targets if isinstance(t, NameUnpackTarget)]
    assert names == ["out"]
    stores = [t.store for t in sugar.targets if isinstance(t, StoreUnpackTarget)]
    assert len(stores) == 1
    assert isinstance(stores[0], SubscriptStoreEffectSugar)
    store = stores[0]
    # Store leaf is codes[...] = ...  (receiver name from source)
    assert store.receiver is not None
    assert store.index is not None
    assert store.value is not None


# ---------------------------------------------------------------------------
# Isomorphic production: dispatch order + earlier-binding halt
# ---------------------------------------------------------------------------


def test_isomorph_helper_retains_setitem_discharge_order() -> None:
    """The dispatched call is receiver → index → value (not source-eval order)."""
    # Expected shape changed (#8925): on a formal whose class is an input the
    # store is the dispatched ``__setitem__`` edge, with ``class:codes``
    # riding last.
    from sugar_lift_py_tests.ir import str_const

    _, outcome = _isomorph_dispatched()
    call = _dispatched_call(outcome)
    # Isomorph formals: codes, i, rhs_store (out binds from name leaf, not setitem).
    names = tuple(arg.name for arg in call.args[:3])
    assert names == ("codes", "i", "rhs_store")
    rides = call.args[-1]
    assert rides.name == "py.class", rides
    assert rides.args[0] == str_const("0")
    assert rides.args[1].name == "class:codes", rides
    assert outcome.completed_value() is None
    # Source eval order for the store half is value → receiver → index.
    source_eval = ("rhs_store", "codes", "i")
    assert names != source_eval

    # Expected shape changed (#7757 step 7): on a formal whose class is no
    # input the store is the undecided mutation, never a ``setitem`` carrier
    # awaiting actuals, and the carrier's projector is deleted.
    _, undecided = _isomorph_undecided()
    _undecided_store(undecided)


def test_isomorph_eval_order_value_receiver_index_is_not_discharge_order() -> None:
    """Truthful twin: dispatch ≠ eval; lying twin equating them fails."""
    _, outcome = _isomorph_dispatched()
    dispatch = tuple(arg.name for arg in _dispatched_call(outcome).args[:3])
    source_eval = ("rhs_store", "codes", "i")
    assert dispatch == ("codes", "i", "rhs_store")
    with pytest.raises(AssertionError):
        assert dispatch == source_eval, "eval order is not dispatch order"


def test_isomorph_mutable_completes_and_invalid_index_halts_with_earlier_state() -> (
    None
):
    """Completed store + IndexError halt carrying the block's state."""
    ok = _floor_store(
        fresh(ListValue, (TermValue(0), TermValue(1))), TermValue(0), TermValue(99)
    )
    assert isinstance(ok, ExitSet)
    assert ok.completed_value() == fresh(ListValue, (TermValue(99), TermValue(1)))

    bad = _floor_store(fresh(ListValue, (TermValue(0),)), TermValue(5), TermValue(99))
    assert len(bad.exits) == 1
    assert isinstance(bad.exits[0], Halted)
    assert bad.exits[0].effect.exception_type_coordinate == _identity("IndexError")

    halted = _bad_index_halt()
    assert not isinstance(halted, Completed)
    # Authentic earlier-binding halt state — not fabricated completion.
    assert halted.state is not None
    assert not isinstance(getattr(halted, "value", None), UniverseValue)


def test_isomorph_later_halt_discrimination_not_completed() -> None:
    """Bite: IndexError arm must not be a Completed body."""
    halted = _bad_index_halt()
    with pytest.raises(AssertionError):
        assert isinstance(halted, Completed)
    with pytest.raises(AssertionError):
        assert halted.state is None


def test_isomorph_lying_swapped_index_value_mint_differs() -> None:
    """Truthful store vs lying index/value swap are distinguishable."""
    base = fresh(ListValue, (TermValue(0), TermValue(1), TermValue(2)))
    truthful = _floor_store(base, TermValue(1), TermValue(99))
    lying = _floor_store(base, TermValue(99), TermValue(1))
    # Truthful post-state stores 99 at index 1.
    t_list = truthful.completed_value()
    assert t_list == fresh(ListValue, (TermValue(0), TermValue(99), TermValue(2)))
    # The swap stores 1 at index 99: the named IndexError, never that list.
    (lying_face,) = lying.exits
    assert isinstance(lying_face, Halted)
    assert lying_face.effect.exception_type_coordinate == _identity("IndexError")
    with pytest.raises(AssertionError):
        assert lying.completed_value() == t_list


def test_isomorph_source_caller_invalid_index_preserves_state() -> None:
    """``f([0], [0], 5, 0, 1, 9)``: ``codes[5] = 9`` raises IndexError.

    Expected verdict changed (#7757 steps 5 and 6, #8705): the source call
    no longer is the one IndexError halt of the followed body.  It is the
    edge, which owes its halt; the IndexError is the list's own store at the
    call's actuals, which prove joins at the call (#8690, #8749), and a
    decided list's store halt keeps the block's state."""
    source = ISOMORPH + "\nf([0], [0], 5, 0, 1, 9)\n"
    tree = _tree(source, "isomorph_call.py")
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    outcome = call.sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    assert [face for face in outcome.exits if isinstance(face, Halted)], outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, outcome
    assert not isinstance(completed[0].value, UniverseValue)

    exits = _floor_store(fresh(ListValue, (TermValue(0),)), TermValue(5), TermValue(9))
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert "IndexError" in repr(halted.effect.exception_type_coordinate)
    assert _bad_index_halt().state is not None
