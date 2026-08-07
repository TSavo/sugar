"""Real pandas unpack-setitem coordinate production faces.

Corpus (pandas 3.0.3, content-verified):

  ``core/groupby/generic.py:1291``
  ``out, codes[-1] = out[sorter], codes[-1][sorter]``

Shape: Name + Subscript store unpack (``out`` binds, then ``codes[-1]`` stores).
Construction admits the leaf as ``UnpackStoreAssignSugar`` +
``SubscriptStoreEffectSugar``.  Production laws for the setitem half reuse the
#6630 projector: source evaluation is value→receiver→index; discharge mint is
receiver→index→value.  Later store halt preserves the earlier-binding pre-effect
state without fabricated completion (post-#6640 / #6644).

Does not touch carrier, reducer, ExitSet, setitem producer/projector, or census.
"""

from __future__ import annotations

import hashlib
import inspect

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import ListValue, TermValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.assign_sugar import UnpackStoreAssignSugar
from sugar_lift_py_tests.sugar.store_effect_sugar import SubscriptStoreEffectSugar
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
# site, with formals so the setitem demand discharges under authenticated actuals.
ISOMORPH = (
    "def f(out, codes, i, sorter, rhs_out, rhs_store):\n"
    "    out, codes[i] = rhs_out, rhs_store\n"
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


def _isomorph_helper():
    tree = _tree(ISOMORPH, "isomorph_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


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
        construction_context=tree_construction_context_for_workspace(
            corpus.root.parent
        ),
    )
    assigns = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Assign) and node.line_col_span().start_line == CORPUS_LINE
    )
    assert len(assigns) == 1
    sugar = assigns[0].sugar()
    assert isinstance(sugar, UnpackStoreAssignSugar)
    assert len(sugar.bindings) == 1
    assert sugar.bindings[0][0] == "out"
    assert len(sugar.stores) == 1
    assert isinstance(sugar.stores[0], SubscriptStoreEffectSugar)
    store = sugar.stores[0]
    # Store leaf is codes[...] = ...  (receiver name from source)
    assert store.receiver is not None
    assert store.index is not None
    assert store.value is not None


# ---------------------------------------------------------------------------
# Isomorphic production: discharge order + earlier-binding halt
# ---------------------------------------------------------------------------


def test_isomorph_helper_retains_setitem_discharge_order() -> None:
    """Discharge mint is receiver → index → value (not source-eval order)."""
    _, pending = _isomorph_helper()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setitem"
    # Isomorph formals: codes, i, rhs_store (out binds from name leaf, not setitem).
    names = tuple(operand.term.name for operand in pending.operands)
    assert names == ("codes", "i", "rhs_store")
    parameters = tuple(
        inspect.signature(_NATIVE_OPERATION_PROJECTORS["setitem"]).parameters
    )
    assert parameters == ("receiver", "index", "value", "site")
    # Source eval order for the store half is value → receiver → index.
    source_eval = ("rhs_store", "codes", "i")
    assert names != source_eval


def test_isomorph_eval_order_value_receiver_index_is_not_discharge_order() -> None:
    """Truthful twin: discharge ≠ eval; lying twin equating them fails."""
    _, pending = _isomorph_helper()
    discharge = tuple(operand.term.name for operand in pending.operands)
    source_eval = ("rhs_store", "codes", "i")
    assert discharge == ("codes", "i", "rhs_store")
    with pytest.raises(AssertionError):
        assert discharge == source_eval, "eval order is not discharge order"


def test_isomorph_mutable_completes_and_invalid_index_halts_with_earlier_state() -> (
    None
):
    """Completed store + IndexError halt carrying authentic pre-effect state."""
    _, pending = _isomorph_helper()
    assert pending.pre_effect_state is not None
    codes_cid, i_cid, rhs_cid = pending.demand.operand_coordinate_cids

    ok = pending.discharge(
        {
            codes_cid: ListValue((TermValue(0), TermValue(1))),
            i_cid: TermValue(0),
            rhs_cid: TermValue(99),
        }
    )
    assert isinstance(ok, ExitSet)
    assert isinstance(ok.exits[0], Completed)
    universe = ok.exits[0].value
    assert isinstance(universe, UniverseValue)
    lists = [s for s in universe.record.statements if isinstance(s, ListValue)]
    assert lists and lists[0] == ListValue((TermValue(99), TermValue(1)))

    bad = pending.discharge(
        {
            codes_cid: ListValue((TermValue(0),)),
            i_cid: TermValue(5),
            rhs_cid: TermValue(99),
        }
    )
    halted = bad.exits[0]
    assert isinstance(halted, Halted)
    assert not isinstance(halted, Completed)
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    # Authentic earlier-binding halt state — not fabricated completion.
    assert halted.state is not None
    assert pending.pre_effect_state.state is halted.state
    assert not isinstance(getattr(halted, "value", None), UniverseValue)


def test_isomorph_later_halt_discrimination_not_completed() -> None:
    """Bite: IndexError arm must not be a Completed body."""
    _, pending = _isomorph_helper()
    codes_cid, i_cid, rhs_cid = pending.demand.operand_coordinate_cids
    bad = pending.discharge(
        {
            codes_cid: ListValue((TermValue(0),)),
            i_cid: TermValue(5),
            rhs_cid: TermValue(99),
        }
    )
    with pytest.raises(AssertionError):
        assert isinstance(bad.exits[0], Completed)
    with pytest.raises(AssertionError):
        assert bad.exits[0].state is None


def test_isomorph_lying_swapped_index_value_mint_differs() -> None:
    """Truthful discharge order vs lying index/value swap are distinguishable."""
    function, truthful = _isomorph_helper()
    site = function.body[0].fragment
    obj_c, key_c, value_c = truthful.coordinates
    lying = NativeOperationExitCarrierV1.mint(
        site=site,
        operator="setitem",
        operands=(
            truthful.operands[0],
            truthful.operands[2],
            truthful.operands[1],
        ),
        coordinates=(obj_c, value_c, key_c),
    )
    actuals = {
        obj_c.coordinate_cid: ListValue((TermValue(0), TermValue(1), TermValue(2))),
        key_c.coordinate_cid: TermValue(1),
        value_c.coordinate_cid: TermValue(99),
    }
    truthful_face = truthful.discharge(actuals).exits[0]
    lying_face = lying.discharge(actuals).exits[0]
    assert isinstance(truthful_face, Completed)
    # Truthful post-state stores 99 at index 1.
    t_lists = [
        s for s in truthful_face.value.record.statements if isinstance(s, ListValue)
    ]
    assert t_lists[0] == ListValue((TermValue(0), TermValue(99), TermValue(2)))
    if isinstance(lying_face, Completed) and isinstance(
        lying_face.value, UniverseValue
    ):
        l_lists = [
            s for s in lying_face.value.record.statements if isinstance(s, ListValue)
        ]
        assert l_lists[0] != t_lists[0]
    elif isinstance(lying_face, Completed) and isinstance(lying_face.value, ListValue):
        assert lying_face.value != t_lists[0]
    else:
        assert isinstance(lying_face, Halted)


def test_isomorph_source_caller_invalid_index_preserves_state() -> None:
    source = ISOMORPH + "\nf([0], [0], 5, 0, 1, 9)\n"
    tree = _tree(source, "isomorph_call.py")
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    outcome = call.sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert "IndexError" in repr(halted.effect.exception_type_coordinate)
    assert halted.state is not None
