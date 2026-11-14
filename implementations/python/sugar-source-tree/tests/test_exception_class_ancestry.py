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
    # The raise carries the import coordinate of E's target symbol ...
    identity = unit.exception_type_identity(raised)
    assert identity == VENDOR_E
    # ... and nothing at the consumer's lift testifies to E's bases,
    assert unit.exception_type_mro(raised) is None

    class _RaiseE:
        exception_type_coordinate = identity
        exception_type_mro = unit.exception_type_mro(raised)

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
    # J's only base is import-bound: J states `is(J, json.JSONDecodeError)`,
    # and the base's own ancestry is its defining proof's to state. Plain
    # classes are not exception classes. A decorator decides what
    # `Decorated` is bound to, not its header.
    assert set(rows) == {
        "python:vendor.B" + EXCEPTION_ANCESTRY_SUFFIX,
        E_ROW,
        "python:vendor.J" + EXCEPTION_ANCESTRY_SUFFIX,
    }
    assert _facts(rows["python:vendor.J" + EXCEPTION_ANCESTRY_SUFFIX]) == [
        (_identity("import", "vendor.J"), _identity("import", "json.JSONDecodeError"))
    ]
    facts = set(_facts(rows[E_ROW]))
    assert (VENDOR_E, _identity("import", "vendor.B")) in facts
    assert (VENDOR_E, _identity("builtins", "KeyError")) in facts
    assert (VENDOR_E, _identity("builtins", "LookupError")) in facts
    assert (VENDOR_E, _identity("builtins", "BaseException")) in facts


# ── Closed across proofs: the base is imported from a third module ──
#
#     # third.py                      # vendor.py
#     class Base(ValueError):         from third import Base
#         pass
#                                     class E(Base):
#                                         pass
#
# The consumer imports `E` and catches `ValueError` around `raise E`. The
# vendor's proof states `is(E, Base)` with Base's coordinate from the one
# import table; third's states `is(Base, ValueError)`. Prove closes the chain
# across the two staged proofs (``except_twin_imported_base_closes_across_
# proofs`` in ``consistency.rs``). Here: each link is stated, and the links
# meet on the same coordinate.

THIRD = "class Base(ValueError):\n    pass\n"
VENDOR_OF_IMPORTED_BASE = "from third import Base\n\nclass E(Base):\n    pass\n"
THIRD_BASE = _identity("import", "third.Base")


def test_an_imported_base_is_stated_and_its_proof_closes_the_chain() -> None:
    vendor_rows = _rows_by_name(
        _source_file("vendor.py", VENDOR_OF_IMPORTED_BASE), "vendor.py"
    )
    assert list(vendor_rows) == [E_ROW]
    assert _facts(vendor_rows[E_ROW]) == [(VENDOR_E, THIRD_BASE)]

    third_rows = _rows_by_name(_source_file("third.py", THIRD), "third.py")
    third_row = third_rows["python:third.Base" + EXCEPTION_ANCESTRY_SUFFIX]
    third_facts = set(_facts(third_row))
    # The vendor's ancestor is the subject of third's own row ...
    assert (THIRD_BASE, _identity("builtins", "ValueError")) in third_facts
    # ... so `is(E, Base)` and `is(Base, ValueError)` answer the consumer's
    # open `is(E, ValueError)` (``test_the_consumer_question_is_about_the_
    # stated_coordinates``).


# ── A re-exported class ──
#
#     # vendor/errors.py              # vendor/__init__.py
#     class E(ValueError):            from .errors import E
#         pass
#
# The consumer's `from vendor import E` names `vendor.E`; the defining
# module's row names `vendor.errors.E`. The package states the edge between
# the two, and prove follows it into the defining proof
# (``except_twin_reexported_class_closes_through_the_package``).


def _workspace_source_file(root: Path, relative: str):
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    return open_source_file_for_construction(
        root / relative,
        root=root,
        construction_context=TreeConstructionContextV1.for_source_call_construction(
            workspace_root=str(root)
        ),
    )


def _write_package(root: Path, package_dir: str) -> tuple:
    """``errors.py`` and a re-exporting ``__init__.py`` in ``package_dir``,
    both written before either is opened."""
    files = {
        f"{package_dir}/errors.py": VENDOR,
        f"{package_dir}/__init__.py": "from .errors import E\n",
    }
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return tuple(_workspace_source_file(root, relative) for relative in files)


def test_a_package_states_the_edge_to_the_class_it_re_exports(tmp_path) -> None:
    errors, package = _write_package(tmp_path, "vendor")
    package_rows = _rows_by_name(package, "vendor/__init__.py")
    assert list(package_rows) == [E_ROW]
    defined = _identity("import", "vendor.errors.E")
    assert _facts(package_rows[E_ROW]) == [(VENDOR_E, defined)]

    errors_rows = _rows_by_name(errors, "vendor/errors.py")
    errors_facts = set(
        _facts(errors_rows["python:vendor.errors.E" + EXCEPTION_ANCESTRY_SUFFIX])
    )
    # The package's ancestor is the subject of the defining module's row.
    assert (defined, _identity("builtins", "ValueError")) in errors_facts


def test_a_src_layout_names_the_module_a_consumer_imports(tmp_path) -> None:
    # `src/vendor/...` is installed as `vendor`: both rows name the symbols a
    # consumer's `from vendor import E` and `from vendor.errors import E` reach.
    errors, package = _write_package(tmp_path, "src/vendor")
    assert list(_rows_by_name(package, "src/vendor/__init__.py")) == [E_ROW]
    assert list(_rows_by_name(errors, "src/vendor/errors.py")) == [
        "python:vendor.errors.E" + EXCEPTION_ANCESTRY_SUFFIX
    ]


def test_a_plain_module_import_states_no_re_export() -> None:
    # Only a package's ``__init__`` re-exports: a consumer's own import is
    # not a statement about the imported class.
    assert _rows_by_name(_source_file("consumer.py", CONSUMER), "consumer.py") == {}
