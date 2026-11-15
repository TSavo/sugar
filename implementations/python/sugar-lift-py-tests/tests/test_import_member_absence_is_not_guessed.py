"""A member read off an imported module may raise, and no absence is guessed (#7757).

The absence rule (#8283, ``ObjectValue._absence_raises``) names
``AttributeError`` only where Python's own lookup decides it: a current
instance whose MRO is source classes and ``object``, no class binding the
name, none binding ``__getattr__``, and ``object``'s ``__getattribute__``.
Every other receiver is not decided.

An imported module is never such a receiver.  An imported name is answered
only by its target symbol and the imported proofs (step 3): no dependency
source refines it (``SourceUnit.seat_import_value_use_resolution``), and a
proof does not list a module's namespace.  So the lifter holds no module's
members, and a member read off an import-bound head is never an
``AttributeError`` the lifter guessed.

It is not a read that cannot halt, either.  Python runs ``getattr`` at
``module.attr`` and can raise there, so the read is the one two-faced
undecided outcome (``ExitSet.two_faced``, ``ImportMemberValue.read_faces``):
it completes with the one closed reference the import table names
(``ref:<target_symbol>``, #7837) only under its own
``python:attribute.completes`` atom, the complement halts with an
undetermined raise, and both arms owe the ``undecided`` member under that
target symbol, so the join can answer it (step 9).  A halt is never dropped;
what is not decided here is stated by the one undecided member.

The pair: a member of a module nothing here sees (truthful), and the corpus
read ``pd.util.foo`` that does raise ``AttributeError`` at run time (lying:
"the lifter decided ``foo`` is absent").  That raise is the ``raise``
statement of ``pandas.util.__getattr__``, a hook the absence rule does not
decide past, so even with that module's source in hand the rule names no
``AttributeError`` there.  Both reads are the same two faces: the run-time
raise is the halting face, unnamed.

The discrimination (a name ``from m import x`` bound is read by name and
cannot raise at the read) is ``test_one_import_door.py``'s.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.import_member_value import ImportMemberValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_lift_py_tests.unanswered_calls import owed_calls

from test_attribute_exceptional_exit_producer import (
    _authenticated_corpus_file,
    _line_attribute,
)


def _the_two_faces_and_no_guessed_absence(outcome, qualified_name: str) -> None:
    """The read completes with the closed reference ``ref:<qualified_name>``
    under its completes atom, or halts with an undetermined raise; no arm
    halts with an ``AttributeError`` the lifter named; the read is owed once,
    under the import table's target symbol."""
    completed = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert len(completed) == 1, outcome
    member = completed[0].value
    assert isinstance(member, ImportMemberValue)
    assert member.qualified_name == qualified_name
    assert member.to_term(owner="test") == ctor(
        f"ref:{qualified_name}", [], symbol_kind="coordinate"
    )
    assert "python:attribute.completes" in repr(completed[0].guard)

    halts = [arm for arm in outcome.exits if isinstance(arm, Halted)]
    assert len(halts) == 1, outcome
    (halt,) = halts
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.effect.producer_node_owner == "ImportMemberValue.read"
    assert halt.effect.exception_name is None
    assert "python:attribute.completes" in repr(halt.guard)
    assert halt.guard != completed[0].guard

    owed = owed_calls(outcome)
    assert [call.symbol for call in owed] == [f"python:{qualified_name}"]
    assert owed[0].site is not None
    assert completed[0].owed == halt.owed == owed


def test_a_member_of_a_module_nothing_here_sees_may_be_absent(tmp_path) -> None:
    """Truthful: ``vendor`` has no source in the project and no staged proof.
    Whether ``vendor.shipped`` exists is not the lifter's to say, so the read
    is the reference its import names under the read's completes atom, or an
    undetermined raise, and the ``undecided`` member is owed."""
    source = "import vendor\n\n\ndef f():\n    return vendor.shipped\n"
    path = tmp_path / "use.py"
    path.write_text(source, encoding="utf-8")
    node = _line_attribute(source, path, line=5, attr="shipped")

    _the_two_faces_and_no_guessed_absence(node.sugar().desugar(None), "vendor.shipped")


def test_a_member_absent_at_run_time_is_not_a_guessed_attribute_error() -> None:
    """Lying: ``pd.util.foo`` raises ``AttributeError`` at run time (the
    corpus test expects it), and the claim "the lifter decided ``foo`` is
    absent" is still false.  ``pandas.util`` binds ``__getattr__``, whose own
    ``raise`` is what runs: the absence rule decides nothing for a receiver
    with that hook, so the read is the same two faces as any other member.
    The run-time raise is the halting face, and it names no exception."""
    use = _authenticated_corpus_file("tests/api/test_api.py")
    source = use.read_text(encoding="utf-8")
    assert (
        'with pytest.raises(AttributeError, match="foo"):\n'
        "            pd.util.foo\n"
    ) in source
    module = _authenticated_corpus_file("util/__init__.py").read_text(
        encoding="utf-8"
    )
    assert ("\n" + module).count("\ndef __getattr__(") == 1
    assert "raise AttributeError(" in module
    node = _line_attribute(source, use, line=491, attr="foo")

    _the_two_faces_and_no_guessed_absence(
        node.sugar().desugar(None), "pandas.util.foo"
    )
