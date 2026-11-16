"""One import door (#7837): every import-bound reference reads one table.

The lexical import pass keys the target symbol of every import-bound
reference -- a Name, or a ``Name.attr...`` chain whose head is import-bound --
by that reference's own coordinate, under ONE law (the strict one). Every call
with a target symbol is spelled by it (``call:<target_symbol>``), never by the
local alias, whatever the callee's shape; every import-member value read is a
closed reference ``ref:<target_symbol>``, never a free variable. A bare module
alias is not a member and keeps its name.

A dotted read (``idn.CONST``) runs ``getattr`` where it is read and the lifter
holds no module's namespace, so it is the two-faced undecided read: the
reference under its completes atom, an undetermined raise under the
complement, and the ``undecided`` member owed under the same target symbol. A
name ``from idn import CONST`` bound is read by name and cannot raise there.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.import_binding import authenticated_import_uses

from test_import_bound_callee_is_closed import (
    _application,
    _function_outcome,
    _post,
    _scoped,
)


def _value(post):
    """The value ``out`` is equated to."""
    assert post.name == "="
    return post.args[1]


@pytest.mark.parametrize(
    "source",
    [
        "from idn import ident\n\n\ndef f():\n    return ident(3)\n",
        "from idn import ident as g\n\n\ndef f():\n    return g(3)\n",
        "import idn\n\n\ndef f():\n    return idn.ident(3)\n",
        "import idn as q\n\n\ndef f():\n    return q.ident(3)\n",
    ],
    ids=["from-import", "from-import-alias", "module", "module-alias"],
)
def test_every_import_bound_call_is_spelled_by_its_target_symbol(source) -> None:
    post = _post(source)
    assert _application(post).name == "call:idn.ident"
    assert _scoped(post, ()).formula.free_vars == {"out"}


@pytest.mark.parametrize(
    ("source", "spelling"),
    [
        ("import idn\n\n\ndef f():\n    m = idn\n    return m.ident(3)\n", "call:ident"),
        (
            "from idn import ident\n\n\ndef f():\n    g = ident\n    return g(3)\n",
            "py.call",
        ),
    ],
    ids=["alias-var", "member-var"],
)
def test_a_call_through_a_local_holding_an_import_is_not_the_doors(
    source, spelling
) -> None:
    """THE DISCRIMINATION: the door is lexical.  It keys a reference by that
    reference's own coordinate, and ``m`` / ``g`` are locals: a read of one is
    a reference to its assignment's evaluation, never ``idn`` / ``ident`` read
    again where the local is used (temporal choice 1, #7757 item 7).  So the
    call through the local is a call on the value the local holds, spelled as
    any such call is, and the door's ``call:<target_symbol>`` is not written
    for it: nothing here joins it to ``idn.ident``.  These once passed only
    because the rewrite substituted the bound alias for the local at its
    read, the second way of reading an alias that item 7 deleted.  Pinned so
    a change that starts deciding the call is seen."""
    assert _application(_post(source)).name == spelling


def test_a_submodule_import_call_is_a_call() -> None:
    # ``import a.b`` binds ``a``; ``a.b.f(...)`` is ``f`` of ``a.b``. The
    # dotted path used to rebuild the symbol from the head alone and found no
    # head row, so ``pkg`` was minted as a free variable.
    post = _post("import pkg.sub\n\n\ndef f():\n    return pkg.sub.ident(3)\n")
    assert _application(post).name == "call:pkg.sub.ident"
    assert _scoped(post, ()).formula.free_vars == {"out"}


@pytest.mark.parametrize(
    ("source", "reference"),
    [
        ("from idn import CONST\n\n\ndef f():\n    return CONST\n", "ref:idn.CONST"),
        ("import idn\n\n\ndef f():\n    return idn.CONST\n", "ref:idn.CONST"),
        ("import numpy as np\n\n\ndef f():\n    return np.float64\n", "ref:numpy.float64"),
    ],
    ids=["from-import", "module-member", "aliased-module-member"],
)
def test_an_import_member_value_read_is_a_closed_reference(source, reference) -> None:
    post = _post(source)
    value = _value(post)
    assert value.name == reference
    assert value.args == ()
    assert _scoped(post, ()).formula.free_vars == {"out"}


@pytest.mark.parametrize(
    ("source", "symbol"),
    [
        ("import idn\n\n\ndef f():\n    return idn.CONST\n", "python:idn.CONST"),
        (
            "import numpy as np\n\n\ndef f():\n    return np.float64\n",
            "python:numpy.float64",
        ),
        (
            "from pkg import sub as s\n\n\ndef f():\n    return s.CONST\n",
            "python:pkg.sub.CONST",
        ),
    ],
    ids=["module-member", "aliased-module-member", "from-import-head"],
)
def test_a_dotted_member_read_may_raise_and_owes_its_target_symbol(
    source, symbol
) -> None:
    """Truthful: Python can raise at ``module.attr`` (the member may be
    absent), and nothing here holds the module's namespace.  The read is the
    two faces: it completes with the reference only under its own
    ``python:attribute_op.completes`` atom, the complement halts with an
    undetermined raise (no ``AttributeError`` is named), and what is not
    decided here is stated once, by the ``undecided`` member under the import
    table's target symbol."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    outcome = _function_outcome(source)
    (halt,) = outcome.halts()
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.effect.producer_node_owner == "ImportMemberValue.read"
    assert halt.effect.exception_name is None
    assert "python:attribute_op.completes" in repr(halt.guard)
    (completed,) = [face for face in outcome.exits if isinstance(face, Completed)]
    assert "python:attribute_op.completes" in repr(completed.guard)
    owed = owed_calls(outcome)
    assert [call.symbol for call in owed] == [symbol]
    assert owed[0].site is not None


def test_a_name_a_from_import_bound_cannot_raise_at_its_read() -> None:
    """Lying: "every import member read may raise".  ``from idn import CONST``
    ran before the read (an absent member raises there, at the import); the
    read of the name it bound runs nothing.  One completed arm, no halt,
    nothing owed."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    outcome = _function_outcome(
        "from idn import CONST\n\n\ndef f():\n    return CONST\n"
    )
    assert not outcome.halts()
    assert len(outcome.exits) == 1
    assert owed_calls(outcome) == ()


def test_a_member_read_as_an_operand_is_a_reference_not_a_free_variable() -> None:
    post = _post(
        "import numpy as np\n\n\ndef f():\n    return np.array([1], dtype=np.float64)\n"
    )
    application = _application(post)
    assert application.name == "call:numpy.array"
    assert "ref:numpy.float64" in repr(application)
    assert _scoped(post, ()).formula.free_vars == {"out"}


def test_two_reads_of_one_member_are_one_reference() -> None:
    first = _value(_post("import idn\n\n\ndef f():\n    return idn.CONST\n"))
    second = _value(
        _post("from idn import CONST\n\n\ndef g():\n    x = 1\n    return CONST\n")
    )
    assert first == second


def test_a_bare_module_alias_is_not_a_member_and_keeps_its_name() -> None:
    # THE DISCRIMINATION: a module alias read as a value is no import member,
    # so it keeps NameSugar and the scope law still refuses the free name.
    post = _post("import idn\n\n\ndef f():\n    return idn\n")
    with pytest.raises(ConstructionPanic, match="illegal free var.*idn"):
        _scoped(post, ())


def test_an_optional_import_is_not_import_bound() -> None:
    # One law: the strict one. ``try: import pa / except ImportError: pass``
    # joins the import with unbound, so ``pa`` binds nothing -- no row, no
    # closed call; the receiver stays the free name it is.
    post = _post(
        "try:\n    import pyarrow as pa\nexcept ImportError:\n    pass\n\n\n"
        "def f():\n    return pa.array(1)\n"
    )
    assert _application(post).name != "call:pyarrow.array"
    with pytest.raises(ConstructionPanic, match="illegal free var.*pa"):
        _scoped(post, ())


def test_the_call_spelling_is_the_demand_symbol(tmp_path) -> None:
    # The call is spelled by the same speller that writes the kit's demand.
    from sugar_lift_python_source.source_oracle import path_source

    path = tmp_path / "m.py"
    path.write_text("import idn as q\n\n\ndef f():\n    return q.ident(3)\n")
    source, _, cid = path_source(str(path))
    rows, _ = authenticated_import_uses(tmp_path, path, source, cid)
    assert [row["targetSymbol"] for row in rows] == ["python:idn.ident"]
    post = _post("import idn as q\n\n\ndef f():\n    return q.ident(3)\n")
    assert _application(post).name == "call:" + rows[0]["targetSymbol"].removeprefix(
        "python:"
    )
