"""The raise matcher's subject is a VALUE, and a coordinate is not one.

`matches_raise_effect` retains `adt.is_python_type(raised, handler)` when the
question is real but undecidable. `raised` is the raised VALUE. When an operand
cannot produce a value term there is no question to retain, and the refusal is
correct output -- accounted semantics, not owed work.

WHY THIS FILE EXISTS. The refusal's own `fix:` line used to read

    "resolve both exception operands through their lexical coordinates"

and a `RaiseEffect` does carry an `occurrence` (`file:line:col`) that is
authenticated, deterministic, and content-addressable. Handing it over as the
raised term makes the refusal disappear and every count move. It is also wrong:
the coordinate designates WHERE THE RAISE IS WRITTEN, not WHAT WAS RAISED, so
the emitted atom would be a predicate about the wrong kind of thing --
fabricating a fact about a runtime type nobody testified to.

That guidance cost three rounds of probing and nearly landed. The `fix:` text
is corrected; this file makes the ruling a law rather than a comment, because
the next person to meet this refusal will feel the same pull.

The measured shape that produced it, for the record: `pandas/core/apply.py`
`wrap_results_list_like`, whose incoming effect carries
`exception_name='NameError'`, `raised_value=None`,
`exception_type_coordinate=None`, and `occurrence='pandas/core/apply.py:402:19'`.
Reproduces on two independently installed pandas versions.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.authenticated_exception_matching import (
    MatchRetained,
    matches_raise_effect,
)
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_source_tree.panic import SugarNotWritten

OCCURRENCE = "renamed_module.py:402:19"


class _AuthenticatedHandler:
    """A handler whose exception identity IS authenticated."""

    def __init__(self, identity):
        self._identity = identity

    def exception_type_identity(self):
        return self._identity


class _TermBearingHandler:
    """A handler with no authenticated identity but a projectable value term."""

    def exception_type_identity(self):
        return None

    def to_term(self, *, owner: str):
        del owner
        return TermValue(99).to_term(owner="handler value")


def _valueless_effect() -> RaiseEffect:
    """The measured shape: a raise with no value and no authenticated type."""
    return RaiseEffect(
        exception_name="NameError",
        blame=OCCURRENCE,
        occurrence=OCCURRENCE,
    )


# -- the refusal is correct output -------------------------------------------


def test_an_effect_with_no_raised_value_refuses() -> None:
    handler = _AuthenticatedHandler(TermValue(1).to_term(owner="handler"))

    with pytest.raises(SugarNotWritten) as raised:
        matches_raise_effect(_valueless_effect(), handler)

    assert raised.value.owner == "matches_raise_effect"


def test_the_refusal_says_the_row_is_accounted_semantics() -> None:
    """`panic = gap`. The next reader must learn this is correct output, not a
    row to drain -- that reading is what sent one owner at an unsound repair."""
    handler = _AuthenticatedHandler(TermValue(1).to_term(owner="handler"))

    with pytest.raises(SugarNotWritten) as raised:
        matches_raise_effect(_valueless_effect(), handler)

    fix = raised.value.fix
    assert "accounted semantics" in fix
    assert "not owed work" in fix


def test_the_refusal_names_the_coordinate_as_inadmissible() -> None:
    """THE guidance defect, pinned.

    The old `fix:` invited using the lexical coordinate as the operand term.
    The corrected one must say the opposite, and say WHY, or the next reader
    re-derives the wrong repair from the effect's own fields.
    """
    handler = _AuthenticatedHandler(TermValue(1).to_term(owner="handler"))

    with pytest.raises(SugarNotWritten) as raised:
        matches_raise_effect(_valueless_effect(), handler)

    fix = raised.value.fix
    assert "not admissible" in fix
    assert "raise SITE" in fix or "raise site" in fix.lower()
    assert "value term" in fix
    # And the requested field must ask for a VALUE, not "an operand term".
    assert "VALUE term" in raised.value.requested


# -- lying twin: a coordinate must never become the subject ------------------


def test_a_coordinate_as_the_raised_term_is_the_repair_this_forbids() -> None:
    """THE lying twin.

    This is the repair the old `fix:` line invited, written out. Passing the
    occurrence as the raised operand makes the refusal vanish and produces an
    atom -- and the atom's subject is a source coordinate, which is precisely
    the fabrication. If a future change makes the FIRST assertion here fail,
    someone has taken that repair and the second assertion says what is wrong
    with it.
    """
    from sugar_lift_py_tests.ir import str_const

    handler = _AuthenticatedHandler(TermValue(1).to_term(owner="handler"))

    # The real call refuses, because the effect has no value term.
    with pytest.raises(SugarNotWritten):
        matches_raise_effect(_valueless_effect(), handler)

    # Had the coordinate been admitted, this is the atom it would have built.
    would_have_been = str_const(OCCURRENCE)
    assert would_have_been != TermValue(1).to_term(owner="handler")
    # It designates a source location, not a raised object -- so an
    # `adt.is_python_type` over it asserts a runtime type of a *coordinate*.
    assert OCCURRENCE.count(":") == 2


def test_a_real_value_term_still_retains_the_question() -> None:
    """The discriminating face: the refusal must not swallow the live case.

    When the raised operand CAN produce a value term, the question is real and
    undecidable and must leave as `MatchRetained` over the tester atom -- not
    as a refusal. A guard that refused everything would pass every test above
    and destroy the mechanism.
    """
    effect = RaiseEffect(
        exception_name="ValueError",
        blame=OCCURRENCE,
        occurrence=OCCURRENCE,
        raised_value=TermValue(7),
    )
    # A handler with NO authenticated identity but WITH a value term: the
    # question is then real and undecidable rather than unstatable.
    handler = _TermBearingHandler()

    verdict = matches_raise_effect(effect, handler)

    assert isinstance(verdict, MatchRetained)
    assert verdict.obligation.name == "adt.is_python_type"
