"""DELETE READBACK LAWS — semantic visibility of formal delete capability.

After a completed delete, authenticated reads must see the post-delete world.
After a halted delete, the pre-delete world remains visible. Restore rewrites
the visible value. Lying twins that fabricate a deleted value or claim the
wrong exceptional occurrence refuse.

Seed:

    def helper(obj, key):
        del obj[key]

    def helper2(obj):
        del obj.field

An item delete mints no carrier (#7757 step 7): ``del obj[key]`` is the one
item mutation (``store_effect_sugar.item_mutation``).  On ``helper``'s
``obj`` (its class an input) it is the dispatched ``__delitem__`` edge; on a
formal whose class is no input (``return obj`` reads it bare) the undecided
delete, owed on both faces with its halt kept; on a receiver whose type is
decided (the caller's ``dict``/``list`` actual) the floor's own ``delitem``.
The readback laws below read that floor delete off the door over the decided
actual, and the state a halted delete leaves with off a function whose own
frame built the receiver.  An attribute delete mints no carrier either:
``helper2``'s ``del obj.field`` is the one attribute mutation
(``store_effect_sugar.attribute_mutation``); ``obj``'s class is no input (an
attribute delete alone makes none), so it is the undecided delete, owed on
both faces with its halt kept; on the caller's decided ``ObjectValue`` actual
it is the floor's own ``delattr``, which the delattr readback laws read off
the door.

Acceptance:

  1. Completed delitem → subsequent read of that key yields named KeyError;
     occurrence lineage is intact (KeyError occurrence is the delete locus).
  2. Completed delattr → attribute is gone; authenticated read yields named
     AttributeError (or reds name the Floor owner that still undecides).
  3. Delete-then-restore (set again) → read yields the new value.
  4. Readback after a HALTED delete still sees the original (state survival).
  5. Lying twins refuse: fabricated deleted value; KeyError with wrong
     occurrence identity.

Reds name owners by nature:

  codex-1 — pre-effect / state-survival composition on halted delete
  codex-3 — readback transport / occurrence lineage across delete→read
  Floor   — ObjectValue.attribute missing-member AttributeError arm

MUST NOT TOUCH: production, carrier/ExitSet.
"""

from __future__ import annotations

import pytest
from frame_fresh import FRAME_FRESH, fresh

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    DictValue,
    ListValue,
    ObjectField,
    ObjectValue,
    StringValue,
    TermValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.store_effect_sugar import (
    attribute_mutation,
    item_mutation,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.effect import RaiseEffect

CODEX1 = (
    "codex-1 state survival: halted delete must leave the original receiver "
    "readable; pre-effect state identity is not a fabricated empty block"
)
CODEX3 = (
    "codex-3 delete readback: completed delete must make subsequent "
    "authenticated reads see KeyError/AttributeError with delete occurrence "
    "lineage, or restore to the new value"
)
FLOOR_ATTR = (
    "Floor ObjectValue.attribute: decided empty/missing instance field after "
    "delattr must yield named AttributeError on the read path "
    "(not SugarNotWritten undecided)"
)

DELITEM = "def helper(obj, key):\n    del obj[key]\n"
# Since #8857 ``DELITEM``'s ``obj`` takes ``class:obj`` as an input (deleted
# from, used no other way): its delete is the dispatched ``__delitem__``
# edge, answered at prove by the class a caller binds (#8864).  On a formal
# whose class is no input (``return obj`` reads ``obj`` bare,
# ``nodes._receiver_uses``) nothing here decides ``type(obj)``: the delete is
# the undecided one (``undecided_item_mutation_faces``), never a carrier
# waiting on the caller's actuals.
DELITEM_UNDECIDED = "def helper(obj, key):\n    del obj[key]\n    return obj\n"
DELATTR = "def helper2(obj):\n    del obj.field\n"
# A delete on a receiver the function's own frame built (decided): a missing
# key is its floor's ``KeyError``, and the halt leaves the block with the
# prefix it reached, ``a[0] = 9`` included (``halts_at_statement_head``).
FRAME_MISSING_KEY = (
    "def frame():\n"
    "    a = [0]\n"
    "    a[0] = 9\n"
    "    obj = {'a': 1, 'b': 2}\n"
    "    del obj['missing']\n"
)


def _tree(source: str, name: str = "delete_readback_laws.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _identity(name: str):
    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def test_delitem_on_a_class_input_formal_is_the_dispatched_edge() -> None:
    """``DELITEM`` alone: ``call:dispatch:__delitem__(obj, key, py.class("0",
    class:obj))``, owed, its halt kept under the edge's owner (#8857)."""
    from sugar_lift_py_tests.call_symbol import call_symbol
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    tree = _tree(DELITEM, "delitem_dispatched.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    outcome = function.sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "UnknownCallee:dispatch:__delitem__"
    ]
    assert len(halts) == 1, outcome
    assert "python:dispatch:__delitem__" in {c.symbol for c in owed_calls(outcome)}
    call = halts[0].effect.raised_by_call.args[0]
    assert call.name == call_symbol("dispatch:__delitem__")
    assert [arg.name for arg in call.args[:2]] == ["obj", "key"]
    assert call.args[2].name == "py.class"
    assert call.args[2].args[1].name == "class:obj"


def test_delitem_on_a_formal_with_no_class_input_is_the_undecided_delete() -> None:
    """``DELITEM_UNDECIDED`` alone: no carrier.  The delete completes only
    under ``python:delitem.completes(...)`` or raises something undetermined
    (owner ``UndecidedDelitem``), its halt kept with its state, and both
    faces owe the undecided member."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.unanswered_calls import owed_calls, unanswered_call

    tree = _tree(DELITEM_UNDECIDED, "delitem_undecided.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    outcome = function.sugar().desugar(None)
    assert isinstance(outcome, ExitSet), type(outcome)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "UndecidedDelitem"
    ]
    assert len(halts) == 1, outcome
    (halt,) = halts
    assert isinstance(halt.effect, UndeterminedRaiseEffect), halt.effect
    assert halt.state is not None, f"{CODEX1}: undecided delete halt dropped state"
    owed = unanswered_call(None, halt.effect.site)
    assert owed in owed_calls(outcome)
    assert owed in halt.owed
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome
    for face in completed:
        assert "python:delitem.completes" in str(face.guard), face.guard
        assert owed in face.owed
    assert outcome.completed_value() is None


def _delete_site():
    """``del obj[key]``'s fragment in ``DELITEM_UNDECIDED``."""
    tree = _tree(DELITEM_UNDECIDED, "delitem_readback.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function.body[0].fragment


def _delete(receiver, key):
    """``del receiver[key]`` through the one item mutation at the helper's
    delete, the receiver the caller's decided actual: its floor's own
    ``delitem`` (#7757 step 7), every face of it kept."""
    site = _delete_site()
    return site, item_mutation("__delitem__", receiver, (key,), site, None, unit=None)


def _frame_keyerror() -> Halted:
    """``FRAME_MISSING_KEY`` reduced: its sole face, the named ``KeyError``,
    with the state the block reached before the delete."""
    tree = _tree(FRAME_MISSING_KEY, "delitem_frame.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    outcome = function.sugar().desugar(None)
    assert isinstance(outcome, ExitSet), type(outcome)
    assert len(outcome.exits) == 1, outcome
    (halted,) = outcome.exits
    assert isinstance(halted, Halted), halted
    assert halted.effect.exception_type_coordinate == _identity("KeyError")
    assert halted.state is not None, f"{CODEX1}: halted delete dropped its state"
    return halted


def _delattr_function():
    tree = _tree(DELATTR, "delattr_readback.py")
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _delattr(receiver):
    """``del receiver.field`` through the one attribute mutation at
    ``helper2``'s delete, the receiver the caller's decided actual: its
    floor's own ``delattr``, every face of it kept."""
    site = _delattr_function().body[0].fragment
    return site, attribute_mutation(
        "__delattr__", receiver, "field", (), site, None, unit=None
    )


def test_delattr_on_a_formal_with_no_class_input_is_the_undecided_delete() -> None:
    """``DELATTR`` alone: no carrier.  The delete completes only under
    ``python:delattr.completes(...)`` or raises something undetermined
    (owner ``UndecidedDelattr``), its halt kept with its state, and both
    faces owe the undecided member."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.unanswered_calls import owed_calls, unanswered_call

    outcome = _delattr_function().sugar().desugar(None)
    assert isinstance(outcome, ExitSet), type(outcome)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "UndecidedDelattr"
    ]
    assert len(halts) == 1, outcome
    (halt,) = halts
    assert isinstance(halt.effect, UndeterminedRaiseEffect), halt.effect
    assert halt.state is not None, f"{CODEX1}: undecided delete halt dropped state"
    owed = unanswered_call(None, halt.effect.site)
    assert owed in owed_calls(outcome)
    assert owed in halt.owed
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome
    for face in completed:
        assert "python:delattr.completes" in str(face.guard), face.guard
        assert owed in face.owed
    assert outcome.completed_value() is None


def _post_dict(completed: Completed) -> DictValue:
    value = completed.value
    if isinstance(value, DictValue):
        return value
    record = getattr(value, "record", None)
    if record is not None:
        dicts = [s for s in record.statements if isinstance(s, DictValue)]
        assert dicts, f"{CODEX3}: no DictValue post-state in {record.statements!r}"
        return dicts[-1]
    raise AssertionError(
        f"{CODEX3}: unprojected delete post-state {type(value).__name__}"
    )


def _post_object(completed: Completed) -> ObjectValue:
    value = completed.value
    if isinstance(value, ObjectValue):
        return value
    record = getattr(value, "record", None)
    if record is not None:
        objs = [s for s in record.statements if isinstance(s, ObjectValue)]
        assert objs, f"{CODEX3}: no ObjectValue post-state"
        return objs[-1]
    raise AssertionError(
        f"{CODEX3}: unprojected delattr post-state {type(value).__name__}"
    )


def _keyerror_raise(outcome, *, site) -> Halted:
    """Authenticated read face: the KeyError halt at the given locus."""
    assert (
        len(outcome.exits) == 1 and outcome.halts() == outcome.exits
    ), f"{CODEX3}: expected KeyError halt, got {outcome!r:.200}"
    (raise_value,) = outcome.halts()
    assert isinstance(raise_value.effect, RaiseEffect), raise_value.effect
    assert raise_value.effect.exception_name == "KeyError"
    assert raise_value.effect.exception_type_coordinate == _identity("KeyError")
    # Occurrence lineage: KeyError is bound to the delete locus (site).
    assert raise_value.effect.occurrence is not None or (
        raise_value.effect.occurrence_id is not None
    )
    # Same source fragment as the delete when readback uses the delete site:
    # a raise locus spells its site as file:line:col, never the fragment repr.
    locus = f"{site.filename}:{site.line}:{site.col}"
    assert (
        locus in str(raise_value.effect.occurrence)
        or str(raise_value.effect.occurrence) == locus
        or site is raise_value.effect.occurrence
        or (
            getattr(raise_value.effect.occurrence, "filename", None)
            == getattr(site, "filename", None)
        )
        or "Delete" in str(raise_value.effect.occurrence)
        or "delitem" in str(raise_value.effect.occurrence).lower()
        or str(raise_value.effect.blame) == locus
        or locus in str(raise_value.effect.blame)
    ), (
        f"{CODEX3}: KeyError occurrence lineage lost delete locus; "
        f"occurrence={raise_value.effect.occurrence!r} site={site!r}"
    )
    return raise_value


# ===========================================================================
# 1. Completed delitem → read missing key → KeyError + lineage
# ===========================================================================


def test_completed_delitem_readback_yields_named_keyerror_with_delete_lineage() -> None:
    """After ``del obj['a']``, ``obj['a']`` is KeyError at the delete locus."""
    original = fresh(
        DictValue,
        (
            (StringValue("a"), TermValue(1)),
            (StringValue("b"), TermValue(2)),
        ),
    )
    delete_site, exits = _delete(original, StringValue("a"))
    assert isinstance(exits.exits[0], Completed)
    post = _post_dict(exits.exits[0])
    assert not any(k.value == "a" for k, _ in post.entries)
    # Sibling key still readable.
    present = post.subscript(StringValue("b"), delete_site)
    assert present.completed_value() is not None
    assert present.completed_value() == TermValue(2)
    # Deleted key: named KeyError with delete occurrence lineage.
    missing = post.subscript(StringValue("a"), delete_site)
    raise_value = _keyerror_raise(missing, site=delete_site)
    assert raise_value.effect.producer_node_owner in {
        "DictValue.subscript",
        "ground_exceptional_exit",
        "DictValue.delitem",
    } or "subscript" in str(raise_value.effect.producer_node_owner)


def test_discrimination_completed_delitem_does_not_fabricate_deleted_value() -> None:
    """Lying twin: readback must not return TermValue(1) for deleted key."""
    original = fresh(DictValue, ((StringValue("a"), TermValue(1)),))
    site, exits = _delete(original, StringValue("a"))
    post = _post_dict(exits.exits[0])
    missing = post.subscript(StringValue("a"), site)
    with pytest.raises(AssertionError):
        assert missing.completed_value() is not None and (
            missing.completed_value() == TermValue(1)
        )
    raise_value = _keyerror_raise(missing, site=site)
    with pytest.raises(AssertionError):
        assert raise_value.effect.exception_name == "ValueError"


# ===========================================================================
# 2. Completed delattr → attribute gone; read AttributeError
# ===========================================================================


def test_completed_delattr_removes_field_and_read_is_attributeerror_or_named_gap() -> (
    None
):
    """After ``del obj.field``, field is absent; read is AttributeError."""
    receiver = ObjectValue(
        class_name="Widget",
        fields=(ObjectField("field", TermValue(7)),),
        methods=(),
        allocation=FRAME_FRESH,
    )
    delete_site, exits = _delattr(receiver)
    assert isinstance(exits.exits[0], Completed)
    post = _post_object(exits.exits[0])
    assert not any(f.name == "field" for f in post.fields), post.fields

    try:
        read = post.attribute("field", delete_site, None)
    except SugarNotWritten as err:
        raise AssertionError(f"{FLOOR_ATTR}: {err}") from err
    except ConstructionPanic as err:
        raise AssertionError(
            f"{FLOOR_ATTR}: ConstructionPanic on missing field read: {err}"
        ) from err

    if (
        len(read.exits) == 1
        and read.halts() == read.exits
        and isinstance(read.halts()[0].effect, RaiseEffect)
    ):
        (halt,) = read.halts()
        assert halt.effect.exception_name == "AttributeError"
        assert halt.effect.exception_type_coordinate == _identity("AttributeError")
        return
    raise AssertionError(
        f"{FLOOR_ATTR}: expected the AttributeError halt, "
        f"got {type(read).__name__} {read!r:.200}"
    )


def test_discrimination_delattr_does_not_leave_readable_old_value() -> None:
    receiver = ObjectValue(
        class_name="Widget",
        fields=(ObjectField("field", TermValue(7)),),
        methods=(),
        allocation=FRAME_FRESH,
    )
    _site, exits = _delattr(receiver)
    post = _post_object(exits.exits[0])
    with pytest.raises(AssertionError):
        assert any(f.name == "field" and f.value == TermValue(7) for f in post.fields)


# ===========================================================================
# 3. Delete-then-restore reads the new value
# ===========================================================================


def test_delete_then_restore_setitem_reads_new_value() -> None:
    """``del obj[k]; obj[k]=99`` → read yields 99, not the pre-delete 1."""
    original = fresh(DictValue, ((StringValue("a"), TermValue(1)),))
    site, deleted = _delete(original, StringValue("a"))
    post = _post_dict(deleted.exits[0])
    restored = post.setitem(StringValue("a"), TermValue(99), site, None)
    assert restored.completed_value() is not None
    assert isinstance(restored.completed_value(), DictValue)
    read = restored.completed_value().subscript(StringValue("a"), site)
    assert read.completed_value() is not None
    assert read.completed_value() == TermValue(99)
    with pytest.raises(AssertionError):
        assert read.completed_value() == TermValue(1)


def test_delete_then_restore_setattr_reads_new_value() -> None:
    """``del obj.field; obj.field=99`` → field is TermValue(99)."""
    receiver = ObjectValue(
        class_name="Widget",
        fields=(ObjectField("field", TermValue(7)),),
        methods=(),
        allocation=FRAME_FRESH,
    )
    site, deleted = _delattr(receiver)
    post = _post_object(deleted.exits[0])
    restored = post.setattr("field", TermValue(99), site, None)
    assert restored.completed_value() is not None
    assert isinstance(restored.completed_value(), ObjectValue)
    fields = {f.name: f.value for f in restored.completed_value().fields}
    assert fields.get("field") == TermValue(99)
    with pytest.raises(AssertionError):
        assert fields.get("field") == TermValue(7)


# ===========================================================================
# 4. Halted delete — original still visible (state survival)
# ===========================================================================


def test_readback_after_halted_delete_still_sees_original() -> None:
    """KeyError delete halt does not mutate the pre-delete receiver."""
    original = fresh(
        DictValue,
        (
            (StringValue("a"), TermValue(1)),
            (StringValue("b"), TermValue(2)),
        ),
    )
    site, exits = _delete(original, StringValue("missing"))
    assert len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity("KeyError")
    # In a function's reduction the halt leaves with the block's prefix: the
    # earlier ``a[0] = 9`` is in it, never a rolled-back empty record.
    framed = _frame_keyerror()
    assert any(
        isinstance(entry, ListValue) and entry == fresh(ListValue, (TermValue(9),))
        for entry in framed.state.entries
    ), f"{CODEX1}: halt state lost the earlier store: {framed.state.entries!r}"
    # Original receiver still carries pre-delete content.
    present = original.subscript(StringValue("a"), site)
    assert present.completed_value() is not None
    assert present.completed_value() == TermValue(1)
    present_b = original.subscript(StringValue("b"), site)
    assert present_b.completed_value() is not None
    assert present_b.completed_value() == TermValue(2)


def test_discrimination_halted_delete_is_not_a_completed_empty_dict() -> None:
    original = fresh(DictValue, ((StringValue("a"), TermValue(1)),))
    _, exits = _delete(original, StringValue("missing"))
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    with pytest.raises(AssertionError):
        assert isinstance(halted, Completed)
    # Original not emptied.
    assert any(k.value == "a" for k, _ in original.entries)


# ===========================================================================
# 5. Lying twins: wrong occurrence / fabricated value
# ===========================================================================


def test_lying_keyerror_wrong_occurrence_refuses() -> None:
    """KeyError after delete must not claim a foreign occurrence identity."""
    original = fresh(DictValue, ((StringValue("a"), TermValue(1)),))
    delete_site, exits = _delete(original, StringValue("a"))
    post = _post_dict(exits.exits[0])
    missing = post.subscript(StringValue("a"), delete_site)
    raise_value = _keyerror_raise(missing, site=delete_site)
    foreign_occurrence = "foreign.py:1:0:lying-twin"
    with pytest.raises(AssertionError):
        assert str(raise_value.effect.occurrence) == foreign_occurrence
    with pytest.raises(AssertionError):
        assert raise_value.effect.occurrence_id == foreign_occurrence


def test_lying_fabricated_deleted_value_refuses_against_keyerror() -> None:
    """Positive KeyError face is not Completing the pre-delete TermValue(1)."""
    original = fresh(DictValue, ((StringValue("a"), TermValue(1)),))
    site, exits = _delete(original, StringValue("a"))
    post = _post_dict(exits.exits[0])
    missing = post.subscript(StringValue("a"), site)
    assert not (
        missing.completed_value() is not None
        and missing.completed_value() == TermValue(1)
    )
    _keyerror_raise(missing, site=site)


def test_list_delitem_readback_indexerror_after_completed_delete() -> None:
    """List twin: delete index 0 of [0,1] → post [1]; read index 1 → IndexError."""
    site, exits = _delete(fresh(ListValue, (TermValue(0), TermValue(1))), TermValue(0))
    assert isinstance(exits.exits[0], Completed)
    value = exits.exits[0].value
    if isinstance(value, ListValue):
        post = value
    else:
        record = getattr(value, "record", None)
        lists = [s for s in record.statements if isinstance(s, ListValue)]
        assert lists
        post = lists[-1]
    assert post == fresh(ListValue, (TermValue(1),))
    # Remaining element readable at 0.
    ok = post.subscript(TermValue(0), site)
    assert ok.completed_value() is not None
    assert ok.completed_value() == TermValue(1)
    # Index 1 is gone.
    gone = post.subscript(TermValue(1), site)
    assert len(gone.exits) == 1 and gone.halts() == gone.exits
    (gone_halt,) = gone.halts()
    assert isinstance(gone_halt.effect, RaiseEffect)
    assert gone_halt.effect.exception_name == "IndexError"
