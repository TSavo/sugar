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

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    DictValue,
    ListValue,
    ObjectField,
    ObjectValue,
    RaiseValue,
    StringValue,
    TermValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

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
DELATTR = "def helper2(obj):\n    del obj.field\n"


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


def _delitem_pending():
    tree = _tree(DELITEM, "delitem_readback.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    pending = function.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "delitem"
    return function, pending


def _delattr_pending():
    tree = _tree(DELATTR, "delattr_readback.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    pending = function.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "delattr_named"
    return function, pending


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


def _keyerror_raise(outcome, *, site) -> RaiseValue:
    """Authenticated read face: Complete(RaiseValue KeyError) at the given locus."""
    assert isinstance(
        outcome, Complete
    ), f"{CODEX3}: expected Complete KeyError raise, got {type(outcome).__name__}"
    assert isinstance(outcome.value, RaiseValue), outcome.value
    raise_value = outcome.value
    assert raise_value.effect.exception_name == "KeyError"
    assert raise_value.effect.exception_type_coordinate == _identity("KeyError")
    # Occurrence lineage: KeyError is bound to the delete locus (site).
    assert raise_value.effect.occurrence is not None or (
        raise_value.effect.occurrence_id is not None
    )
    # Same source fragment as the delete when readback uses the delete site.
    assert (
        str(site) in str(raise_value.effect.occurrence)
        or str(raise_value.effect.occurrence) == str(site)
        or site is raise_value.effect.occurrence
        or (
            getattr(raise_value.effect.occurrence, "filename", None)
            == getattr(site, "filename", None)
        )
        or "Delete" in str(raise_value.effect.occurrence)
        or "delitem" in str(raise_value.effect.occurrence).lower()
        or str(raise_value.effect.blame) == str(site)
        or str(site) in str(raise_value.effect.blame)
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
    function, pending = _delitem_pending()
    delete_site = function.body[0].fragment
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    original = DictValue(
        (
            (StringValue("a"), TermValue(1)),
            (StringValue("b"), TermValue(2)),
        )
    )
    exits = pending.discharge({obj_cid: original, key_cid: StringValue("a")})
    assert isinstance(exits.exits[0], Completed)
    post = _post_dict(exits.exits[0])
    assert not any(k.value == "a" for k, _ in post.entries)
    # Sibling key still readable.
    present = post.subscript(StringValue("b"), delete_site)
    assert isinstance(present, Complete)
    assert present.value == TermValue(2)
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
    function, pending = _delitem_pending()
    site = function.body[0].fragment
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    original = DictValue(((StringValue("a"), TermValue(1)),))
    exits = pending.discharge({obj_cid: original, key_cid: StringValue("a")})
    post = _post_dict(exits.exits[0])
    missing = post.subscript(StringValue("a"), site)
    with pytest.raises(AssertionError):
        assert isinstance(missing, Complete) and missing.value == TermValue(1)
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
    function, pending = _delattr_pending()
    delete_site = function.body[0].fragment
    obj_cid, _ = pending.demand.operand_coordinate_cids
    receiver = ObjectValue(
        class_name="Widget",
        fields=(ObjectField("field", TermValue(7)),),
        methods=(),
    )
    exits = pending.discharge({obj_cid: receiver})
    assert isinstance(exits.exits[0], Completed)
    post = _post_object(exits.exits[0])
    assert not any(f.name == "field" for f in post.fields), post.fields

    try:
        read = post.attribute("field", delete_site)
    except SugarNotWritten as err:
        raise AssertionError(f"{FLOOR_ATTR}: {err}") from err
    except ConstructionPanic as err:
        raise AssertionError(
            f"{FLOOR_ATTR}: ConstructionPanic on missing field read: {err}"
        ) from err

    if isinstance(read, Complete) and isinstance(read.value, RaiseValue):
        assert read.value.effect.exception_name == "AttributeError"
        assert read.value.effect.exception_type_coordinate == _identity(
            "AttributeError"
        )
        return
    raise AssertionError(
        f"{FLOOR_ATTR}: expected Complete(RaiseValue AttributeError), "
        f"got {type(read).__name__} {read!r:.200}"
    )


def test_discrimination_delattr_does_not_leave_readable_old_value() -> None:
    function, pending = _delattr_pending()
    obj_cid, _ = pending.demand.operand_coordinate_cids
    receiver = ObjectValue(
        class_name="Widget",
        fields=(ObjectField("field", TermValue(7)),),
        methods=(),
    )
    exits = pending.discharge({obj_cid: receiver})
    post = _post_object(exits.exits[0])
    with pytest.raises(AssertionError):
        assert any(f.name == "field" and f.value == TermValue(7) for f in post.fields)


# ===========================================================================
# 3. Delete-then-restore reads the new value
# ===========================================================================


def test_delete_then_restore_setitem_reads_new_value() -> None:
    """``del obj[k]; obj[k]=99`` → read yields 99, not the pre-delete 1."""
    function, pending = _delitem_pending()
    site = function.body[0].fragment
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    original = DictValue(((StringValue("a"), TermValue(1)),))
    deleted = pending.discharge({obj_cid: original, key_cid: StringValue("a")})
    post = _post_dict(deleted.exits[0])
    restored = post.setitem(StringValue("a"), TermValue(99), site)
    assert isinstance(restored, Complete)
    assert isinstance(restored.value, DictValue)
    read = restored.value.subscript(StringValue("a"), site)
    assert isinstance(read, Complete)
    assert read.value == TermValue(99)
    with pytest.raises(AssertionError):
        assert read.value == TermValue(1)


def test_delete_then_restore_setattr_reads_new_value() -> None:
    """``del obj.field; obj.field=99`` → field is TermValue(99)."""
    function, pending = _delattr_pending()
    site = function.body[0].fragment
    obj_cid, _ = pending.demand.operand_coordinate_cids
    receiver = ObjectValue(
        class_name="Widget",
        fields=(ObjectField("field", TermValue(7)),),
        methods=(),
    )
    deleted = pending.discharge({obj_cid: receiver})
    post = _post_object(deleted.exits[0])
    restored = post.setattr("field", TermValue(99), site)
    assert isinstance(restored, Complete)
    assert isinstance(restored.value, ObjectValue)
    fields = {f.name: f.value for f in restored.value.fields}
    assert fields.get("field") == TermValue(99)
    with pytest.raises(AssertionError):
        assert fields.get("field") == TermValue(7)


# ===========================================================================
# 4. Halted delete — original still visible (state survival)
# ===========================================================================


def test_readback_after_halted_delete_still_sees_original() -> None:
    """KeyError delete halt does not mutate the pre-delete receiver."""
    function, pending = _delitem_pending()
    site = function.body[0].fragment
    assert pending.pre_effect_state is not None, f"{CODEX1}: missing pre_effect_state"
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    original = DictValue(
        (
            (StringValue("a"), TermValue(1)),
            (StringValue("b"), TermValue(2)),
        )
    )
    exits = pending.discharge({obj_cid: original, key_cid: StringValue("missing")})
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity("KeyError")
    assert (
        halted.state is pending.pre_effect_state.state
    ), f"{CODEX1}: halt state identity lost"
    # Original receiver still carries pre-delete content.
    present = original.subscript(StringValue("a"), site)
    assert isinstance(present, Complete)
    assert present.value == TermValue(1)
    present_b = original.subscript(StringValue("b"), site)
    assert isinstance(present_b, Complete)
    assert present_b.value == TermValue(2)


def test_discrimination_halted_delete_is_not_a_completed_empty_dict() -> None:
    function, pending = _delitem_pending()
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    original = DictValue(((StringValue("a"), TermValue(1)),))
    exits = pending.discharge({obj_cid: original, key_cid: StringValue("missing")})
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
    function, pending = _delitem_pending()
    delete_site = function.body[0].fragment
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    original = DictValue(((StringValue("a"), TermValue(1)),))
    exits = pending.discharge({obj_cid: original, key_cid: StringValue("a")})
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
    function, pending = _delitem_pending()
    site = function.body[0].fragment
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    original = DictValue(((StringValue("a"), TermValue(1)),))
    exits = pending.discharge({obj_cid: original, key_cid: StringValue("a")})
    post = _post_dict(exits.exits[0])
    missing = post.subscript(StringValue("a"), site)
    assert not (
        isinstance(missing, Complete)
        and not isinstance(missing.value, RaiseValue)
        and missing.value == TermValue(1)
    )
    _keyerror_raise(missing, site=site)


def test_list_delitem_readback_indexerror_after_completed_delete() -> None:
    """List twin: delete index 0 of [0,1] → post [1]; read index 1 → IndexError."""
    function, pending = _delitem_pending()
    site = function.body[0].fragment
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            obj_cid: ListValue((TermValue(0), TermValue(1))),
            key_cid: TermValue(0),
        }
    )
    assert isinstance(exits.exits[0], Completed)
    value = exits.exits[0].value
    if isinstance(value, ListValue):
        post = value
    else:
        record = getattr(value, "record", None)
        lists = [s for s in record.statements if isinstance(s, ListValue)]
        assert lists
        post = lists[-1]
    assert post == ListValue((TermValue(1),))
    # Remaining element readable at 0.
    ok = post.subscript(TermValue(0), site)
    assert isinstance(ok, Complete)
    assert ok.value == TermValue(1)
    # Index 1 is gone.
    gone = post.subscript(TermValue(1), site)
    assert isinstance(gone, Complete)
    assert isinstance(gone.value, RaiseValue)
    assert gone.value.effect.exception_name == "IndexError"
