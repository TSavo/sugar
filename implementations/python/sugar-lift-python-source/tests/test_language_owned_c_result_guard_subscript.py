"""A C call's opaque result rides under guards and may raise when subscripted.

``LanguageOwnedCExtensionResultValue`` is the Completed face of a two-faced C
call (#7578). Two gaps remained:

* A bare C call as an expression statement inside ``try`` crashed: the result
  entry could not ride under the try's guard
  (``write more Floor: implement LanguageOwnedCExtensionResultValue.guarded``).
  It now rides unchanged, like ``CallSiteValue``: it states no fact, and the
  enclosing face already sits under the call's completion atom.
* ``decimal.getcontext()[0]`` refused (no subscript floor). It now takes the
  #7587 opaque-subscript law: a symbolic ``py.subscript`` completes only under
  ``python:subscript.completes(python:subscript(<result>, <site>))`` keyed on
  the subscript site, and the complement halts with an
  ``UndeterminedRaiseEffect``. No exception class or member is invented.

The result term is keyed on its call site, as the call's completion atom
already is, so two calls of the same C function are never forced to return
equal results.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.language_owned_contextvar import (
    LanguageOwnedCExtensionResultValue,
)
from sugar_lift_py_tests.outcome import Completed, Halted

from test_undetermined_raise_except_matching import (
    _entries,
    _exits,
    _handler,
    _returns_one,
    _subject,
    _undetermined_halts,
)

CALL = "LanguageOwnedCExtensionCallableValue:_decimal.getcontext"
SUBSCRIPT = "LanguageOwnedCExtensionResultValue.subscript"


def _plain_returns(exits):
    """Unguarded record returns: reached when no earlier guarded entry fired."""
    rows = []
    for face in exits.exits:
        if not isinstance(face, Completed):
            continue
        record = getattr(face.value, "record", None)
        for entry in getattr(record, "statements", ()):
            if type(entry).__name__ == "ReturnValue":
                rows.append((entry.value, repr(face.guard)))
    return rows


def test_bare_c_call_statement_inside_try_rides_the_guard(tmp_path) -> None:
    exits = _exits(
        tmp_path,
        "import decimal\n"
        "def f():\n"
        "    try:\n"
        "        decimal.getcontext()\n"
        "    except ValueError:\n"
        "        return 1\n"
        "    return 2\n",
    )
    head, _ = _subject(CALL)
    not_completed = "kind='not', operands=(_Atomic(name='python:c_extension.call_completes'"
    # The caught arm and the escaping raise both sit under the call's failure;
    # the record's residual ``return 2`` is therefore the completed call.
    (caught,) = _returns_one(exits)
    assert head in caught[2] and _handler("ValueError") in caught[2]
    assert not_completed in caught[2]
    (escaping,) = _undetermined_halts(exits, CALL)
    assert "kind='not', operands=(" + head in escaping[2]
    assert not_completed in escaping[2]
    (residual,) = _plain_returns(exits)
    assert "value=2" in repr(residual[0])


def test_subscript_of_c_result_may_raise(tmp_path) -> None:
    exits = _exits(tmp_path, "import decimal\ndef f():\n    return decimal.getcontext()[0]\n")
    halts = [f for f in exits.exits if isinstance(f, Halted)]
    owners = sorted(h.effect.producer_node_owner for h in halts)
    assert owners == [CALL, SUBSCRIPT]
    assert all(isinstance(h.effect, UndeterminedRaiseEffect) for h in halts)
    (subscript_halt,) = [h for h in halts if h.effect.producer_node_owner == SUBSCRIPT]
    guard = repr(subscript_halt.guard)
    # Reached only after the call completed, and only when the subscript did not.
    assert "python:c_extension.call_completes" in guard
    assert "kind='not', operands=(_Atomic(name='python:subscript.completes'" in guard
    returned = [*(r[1:] for r in _entries(exits) if r[0] == "return"), *_plain_returns(exits)]
    ((value, _guard),) = returned
    assert "py.subscript" in repr(value)
    assert "python:c_extension.result" in repr(value)
    (completed,) = [f for f in exits.exits if isinstance(f, Completed)]
    assert "kind='not'" not in repr(completed.guard)
    assert "python:subscript.completes" in repr(completed.guard)


def test_subscript_raise_is_matched_like_any_undetermined_raise(tmp_path) -> None:
    exits = _exits(
        tmp_path,
        "import decimal\n"
        "def f():\n"
        "    try:\n"
        "        return decimal.getcontext()[0]\n"
        "    except KeyError:\n"
        "        return 1\n",
    )
    caught = _returns_one(exits)
    assert len(caught) == 2  # one per may-raise operation
    for producer in (CALL, SUBSCRIPT):
        head, producer_text = _subject(producer)
        assert any(producer_text in row[2] and _handler("KeyError") in row[2] for row in caught)
        (escaping,) = _undetermined_halts(exits, producer)
        assert "kind='not', operands=(" + head in escaping[2]


def test_two_subscript_sites_are_not_forced_to_agree(tmp_path) -> None:
    exits = _exits(
        tmp_path,
        "import decimal\n"
        "def f():\n"
        "    c = decimal.getcontext()\n"
        "    c[0]\n"
        "    return c[0]\n",
    )
    halts = [
        f for f in exits.exits
        if isinstance(f, Halted) and f.effect.producer_node_owner == SUBSCRIPT
    ]
    assert len(halts) == 2
    assert len({h.effect.occurrence_id for h in halts}) == 2


def test_result_term_is_keyed_on_its_call_site() -> None:
    first = LanguageOwnedCExtensionResultValue("_decimal", "getcontext", site="e.py:3:4")
    second = LanguageOwnedCExtensionResultValue("_decimal", "getcontext", site="e.py:4:4")
    assert first.to_term(owner="t") != second.to_term(owner="t")
    assert first.guarded(object()) is first
