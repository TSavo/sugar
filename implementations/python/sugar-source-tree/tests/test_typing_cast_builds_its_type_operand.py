"""``typing.cast(T, v)`` builds ``T``: Python evaluates it at the call (#7757).

``cast`` returns ``v`` unchanged, but it is an ordinary call and its type
argument is an ordinary argument: ``cast(Missing, v)`` raises ``NameError``
where the call runs.  The call constructed as ``v`` alone, so ``T`` was a
dropped evaluation that never answered the roll (the board's ``Name`` first
absentees ``core/sorting.py:115:27`` ``cast(bool, ascending)``,
``core/arrays/_mixins.py:91:16`` ``cast(F, method)``).  It now builds both,
every face of ``T`` the call's (``TypingCastSugar``).
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.sugar.typing_cast_sugar import TypingCastSugar
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def test_the_cast_witnesses_are_a_truthful_and_a_lying_twin():
    pair = TypingCastSugar.witnesses()
    assert pair.truthful.expected == "sat"
    assert pair.lying.expected == "unsat"


def test_the_type_operand_of_a_cast_answers():
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(
        "from typing import cast\n"
        "\n"
        "\n"
        "def f(a):\n"
        "    return cast(bool, a)\n"
    )
    f.close()
    report = discharge(
        SourceFile(
            path_source(f.name),
            reporter=CollectingReporter(),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )
    absent = {(e.kind, e.start_line, e.start_col) for e in report.minority}
    assert ("Name", 5, 16) not in absent
    present = {(e.kind, e.start_line, e.start_col) for e in report.present}
    assert ("Name", 5, 16) in present
