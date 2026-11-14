"""A module's own exception classes state their ancestry in its proof (#7757).

The twin::

    # vendor.py
    class E(ValueError):
        pass

    # consumer.py
    from vendor import E

    def f():
        try:
            raise E
        except ValueError:
            return 1

Nothing at the consumer's lift testifies to the bases of an imported class, so
its match leaves as ``adt.is_python_type(<E>, <ValueError>)``
(``authenticated_exception_matching``). The vendor's lift reads ``E``'s bases
off the vendor's own source, so the vendor's proof states
``adt.is_python_type(<E>, <ValueError>)``, and the ancestry the language
states above ``ValueError``, over the SAME coordinates, in one row named by
``E``'s target symbol (``python:vendor.E::exception-ancestry``).

Prove joins the two by that symbol and the solver decides the match: with the
vendor proof staged, ``except ValueError`` catches ``E`` and never misses it.
That half is the twin in ``sugar-verifier/src/consistency.rs``
(``except_twin_staged_decides_the_match``). Here: the vendor states the facts,
and the consumer's open question names exactly the coordinates they are about.
"""

import tempfile
from pathlib import Path

from sugar_lift_py_tests.authenticated_exception_matching import (
    MatchRetained,
    matches_raise_effect,
)
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.tree_enumerate import (
    EXCEPTION_ANCESTRY_SUFFIX,
    exception_ancestry_rows,
)
from sugar_source_tree.nodes import Name, exception_type_identity_of_symbol
from with_resolution_fixture import source_file_with_preconstruction

VENDOR = "class E(ValueError):\n    pass\n"

CONSUMER = (
    "from vendor import E\n"
    "\n"
    "def f():\n"
    "    try:\n"
    "        raise E\n"
    "    except ValueError:\n"
    "        return 1\n"
)


def _source_file(name: str, source: str):
    directory = Path(tempfile.mkdtemp(prefix="sugar-exception-ancestry-"))
    path = directory / name
    path.write_text(source, encoding="utf-8")
    return source_file_with_preconstruction(path)


def _identity(tag: str, name: str):
    return ctor("python:exception_type_identity", [str_const(tag), str_const(name)])


VENDOR_E = _identity("import", "vendor.E")
E_ROW = "python:vendor.E" + EXCEPTION_ANCESTRY_SUFFIX


def _rows_by_name(source_file, file_rel: str) -> dict:
    rows = exception_ancestry_rows(source_file, file_rel)
    return {row.name: row for _memento, row in rows}


def _facts(row) -> list:
    """The ``(class, ancestor)`` pairs the row's ``inv`` states."""
    formula = row.inv.ir_formula
    atoms = tuple(getattr(formula, "operands", None) or (formula,))
    assert all(atom.name == "adt.is_python_type" for atom in atoms), atoms
    return [tuple(atom.args) for atom in atoms]


def test_the_vendor_proof_states_its_exception_class_ancestry() -> None:
    rows = _rows_by_name(_source_file("vendor.py", VENDOR), "vendor.py")
    assert list(rows) == [E_ROW]
    row = rows[E_ROW]
    assert row.kind == "contract"
    assert exception_type_identity_of_symbol("python:vendor.E") == VENDOR_E
    assert set(_facts(row)) == {
        (VENDOR_E, _identity("builtins", "ValueError")),
        (VENDOR_E, _identity("builtins", "Exception")),
        (VENDOR_E, _identity("builtins", "BaseException")),
    }


def test_the_consumer_question_is_about_the_stated_coordinates() -> None:
    vendor_rows = _rows_by_name(_source_file("vendor.py", VENDOR), "vendor.py")
    vendor_row = vendor_rows[E_ROW]
    consumer = _source_file("consumer.py", CONSUMER)
    function = next(consumer.functions())
    raised = next(
        node for node in function.walk() if isinstance(node, Name) and node.id == "E"
    )
    unit = function.unit
    # Nothing at the consumer's lift testifies to E's bases ...
    assert unit.exception_type_identity(raised) is None
    # ... so the raise carries the import coordinate of E's target symbol,
    identity = unit.imported_exception_type_identity(raised)
    assert identity == VENDOR_E

    class _RaiseE:
        exception_type_coordinate = identity
        exception_type_mro = unit._builtin_exception_ancestry(identity)

    class _ExceptValueError:
        @staticmethod
        def exception_type_identity():
            return _identity("builtins", "ValueError")

    # ... and the match stays an open question over the two coordinates,
    verdict = matches_raise_effect(_RaiseE(), _ExceptValueError())
    assert isinstance(verdict, MatchRetained)
    assert verdict.obligation.name == "adt.is_python_type"
    # which is exactly one of the facts the vendor's proof states.
    assert tuple(verdict.obligation.args) in _facts(vendor_row)


def test_ancestry_follows_sibling_classes_and_states_nothing_untestified() -> None:
    source = (
        "import json\n"
        "\n"
        "class B(KeyError):\n"
        "    pass\n"
        "\n"
        "class E(B):\n"
        "    pass\n"
        "\n"
        "class J(json.JSONDecodeError):\n"
        "    pass\n"
        "\n"
        "class Plain:\n"
        "    pass\n"
        "\n"
        "class NotAnError(Plain):\n"
        "    pass\n"
        "\n"
        "@decorate\n"
        "class Decorated(ValueError):\n"
        "    pass\n"
    )
    rows = _rows_by_name(_source_file("vendor.py", source), "vendor.py")
    # J's only base is import-bound: its ancestry is its own proof's to
    # state. Plain classes are not exception classes. A decorator decides
    # what `Decorated` is bound to, not its header.
    assert set(rows) == {"python:vendor.B" + EXCEPTION_ANCESTRY_SUFFIX, E_ROW}
    facts = set(_facts(rows[E_ROW]))
    assert (VENDOR_E, _identity("import", "vendor.B")) in facts
    assert (VENDOR_E, _identity("builtins", "KeyError")) in facts
    assert (VENDOR_E, _identity("builtins", "LookupError")) in facts
    assert (VENDOR_E, _identity("builtins", "BaseException")) in facts
