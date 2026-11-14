"""One import door (#7837): every import-bound reference reads one table.

The lexical import pass keys the target symbol of every import-bound
reference -- a Name, or a ``Name.attr...`` chain whose head is import-bound --
by that reference's own coordinate, under ONE law (the strict one). Every call
with a target symbol is spelled by it (``call:<target_symbol>``), never by the
local alias, whatever the callee's shape; every import-member value read is a
closed reference ``ref:<target_symbol>``, never a free variable. A bare module
alias is not a member and keeps its name.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.import_binding import authenticated_import_uses

from test_import_bound_callee_is_closed import _application, _post, _scoped


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
        # the rewrite substitutes the bound alias for ``m``: the chain has no
        # source coordinate of its own, its head Name still has its row.
        "import idn\n\n\ndef f():\n    m = idn\n    return m.ident(3)\n",
        "from idn import ident\n\n\ndef f():\n    g = ident\n    return g(3)\n",
    ],
    ids=["from-import", "from-import-alias", "module", "module-alias", "alias-var", "member-var"],
)
def test_every_import_bound_call_is_spelled_by_its_target_symbol(source) -> None:
    post = _post(source)
    assert _application(post).name == "call:idn.ident"
    assert _scoped(post, ()).formula.free_vars == {"out"}


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
