"""An import-bound exception-type operand is read through the one dotted read
(#7757, follow-up to #8494 and #8504).

``except mod.Err:``, a bare ``raise mod.Err`` and a warning category
``mod.Warn`` run ``getattr`` on what the import bound where they are read; the
lifter holds no module's namespace, so that read may raise and is not decided.
``AuthenticatedExceptionTypeSugar`` reads the operand through
``ImportMemberSugar`` (``ImportMemberValue.read_faces``): its completing face
holds the same authenticated identity value as before, under the read's
completes atom; its halting face is the read's undetermined halt under the
complement; both owe the ``undecided`` member under the import's target
symbol.

Truthful: a dotted operand is the two-faced read, and a ``try`` or a bare
``raise`` over it carries the read's halt and its debt.

Lying: a name a ``from`` import bound is read by name; nothing runs at the
read, so it is one completed arm and owes nothing.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile

_READ_OWNER = "ImportMemberValue.read"


def _tree(tmp_path: Path, name: str, source: str) -> SourceFile:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return SourceFile(path_source(str(path)))


def _function(tmp_path: Path, name: str, source: str):
    from with_resolution_fixture import source_file_with_preconstruction

    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return next(source_file_with_preconstruction(path).functions())


def _operand_read(tree: SourceFile, node):
    from sugar_lift_py_tests.sugar.authenticated_exception_type_sugar import (
        AuthenticatedExceptionTypeSugar,
    )

    identity = tree.unit.exception_type_identity(node)
    assert identity is not None
    sugar = AuthenticatedExceptionTypeSugar(
        node.sugar(), identity, tree.unit.exception_type_mro(node), node.fragment
    )
    return identity, sugar.desugar()


def _halt_effects(outcome):
    """Every halt effect ``outcome`` leaves by: its halted arms, and the
    all-halting entries a completed arm's record carries."""
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    effects = []
    for face in outcome.exits:
        if isinstance(face, Halted):
            effects.append(face.effect)
        elif isinstance(face, Completed):
            record = getattr(face.value, "record", None)
            for entry in getattr(record, "statements", ()):
                if isinstance(entry, ExitSet):
                    effects.extend(halt.effect for halt in entry.halts())
    return effects


def _owed_symbols(outcome):
    """The symbols of every unanswered item ``outcome`` owes, on its arms and
    on the all-halting entries a completed arm's record carries."""
    from sugar_lift_py_tests.outcome import Completed, ExitSet
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    items = list(owed_calls(outcome))
    for face in outcome.exits:
        if not isinstance(face, Completed):
            continue
        record = getattr(face.value, "record", None)
        for entry in getattr(record, "statements", ()):
            if isinstance(entry, ExitSet):
                items.extend(owed_calls(entry))
    return {item.symbol for item in items}


def _read_halts(outcome):
    return [
        effect
        for effect in _halt_effects(outcome)
        if getattr(effect, "producer_node_owner", None) == _READ_OWNER
    ]


_DOTTED_EXCEPT = (
    "import re\n"
    "def f(g):\n"
    "    try:\n"
    "        return g()\n"
    "    except re.error:\n"
    "        return None\n"
)

_FROM_EXCEPT = (
    "from re import error\n"
    "def f(g):\n"
    "    try:\n"
    "        return g()\n"
    "    except error:\n"
    "        return None\n"
)


def test_dotted_exception_type_operand_is_the_two_faced_read(tmp_path):
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
        AuthenticatedExceptionTypeValue,
    )
    from sugar_lift_py_tests.floor.exception_class_value import ExceptionClassValue
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.outcome.exit_set import complement_guard
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    tree = _tree(tmp_path, "dotted.py", _DOTTED_EXCEPT)
    node = next(
        n for n in tree.nodes() if n.kind == "Attribute" and n.attr == "error"
    )
    identity, read = _operand_read(tree, node)

    (face,) = [exit_ for exit_ in read.exits if isinstance(exit_, Completed)]
    (halt,) = [exit_ for exit_ in read.exits if isinstance(exit_, Halted)]
    # The completing face is the same identity value matching reads.
    assert isinstance(face.value, AuthenticatedExceptionTypeValue)
    assert face.value.exception_type_identity() == identity
    assert face.value.class_value == ExceptionClassValue("re.error")
    # The halting face is the read's own, under the complement.
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == _READ_OWNER
    assert halt.guard == complement_guard(face.guard)
    # Both faces owe the member under the import's target symbol.
    assert face.owed and halt.owed
    assert {item.symbol for item in owed_calls(read)} == {"python:re.error"}


def test_from_imported_exception_type_operand_is_one_plain_arm(tmp_path):
    from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
        AuthenticatedExceptionTypeValue,
    )

    tree = _tree(tmp_path, "from.py", _FROM_EXCEPT)
    node = next(
        n
        for n in tree.nodes()
        if n.kind == "Name"
        and n.id == "error"
        and n.line_col_span().start_line == 5
    )
    identity, read = _operand_read(tree, node)

    value = read.completed_value()
    assert isinstance(value, AuthenticatedExceptionTypeValue)
    assert value.exception_type_identity() == identity
    assert not read.halts()
    assert read.owed_items() == ()


def test_except_over_a_dotted_type_carries_the_read_halt_and_owes(tmp_path):
    outcome = _function(tmp_path, "except_dotted.py", _DOTTED_EXCEPT).sugar().desugar()
    assert _read_halts(outcome)
    assert "python:re.error" in _owed_symbols(outcome)


def test_except_over_a_from_imported_type_has_no_read_halt(tmp_path):
    outcome = _function(tmp_path, "except_from.py", _FROM_EXCEPT).sugar().desugar()
    assert _read_halts(outcome) == []
    assert "python:re.error" not in _owed_symbols(outcome)


def test_bare_raise_of_a_dotted_type_carries_the_read_halt_and_owes(tmp_path):
    outcome = (
        _function(tmp_path, "raise_dotted.py", "import re\ndef f():\n    raise re.error\n")
        .sugar()
        .desugar()
    )
    assert _read_halts(outcome)
    assert "python:re.error" in _owed_symbols(outcome)


def test_bare_raise_of_a_from_imported_type_has_no_read_halt(tmp_path):
    outcome = (
        _function(
            tmp_path, "raise_from.py", "from re import error\ndef f():\n    raise error\n"
        )
        .sugar()
        .desugar()
    )
    assert _read_halts(outcome) == []
    assert "python:re.error" not in _owed_symbols(outcome)
