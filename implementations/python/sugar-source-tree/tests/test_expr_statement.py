"""`<expr>` in statement position states nothing; effects ride."""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.outcome import Completed
from sugar_source_tree.tree import SourceFile


def _outcome(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions()).sugar().desugar()


def _val(src):
    return _outcome(src).completed_value()


def test_docstring_and_bare_call_are_inert():
    # ``z.validate()`` on a formal is an unanswered call: it completes or
    # raises, so the body completes only under the call's completion, its
    # halt kept beside it (#7757).  The completed face states nothing and
    # lifts through both statements.
    outcome = _outcome('def A(z):\n    """doc."""\n    z.validate()\n    return z\n')
    assert outcome.halts(), outcome.exits
    completed = [
        exit_ for exit_ in outcome.normalize().exits if isinstance(exit_, Completed)
    ]
    assert len(completed) == 1, outcome.exits
    v = completed[0].value
    assert v.invs() == ()
    assert v.post().args[1].name == "z"  # the function lifts through them


def test_bare_int_is_inert():
    v = _val("def A(z):\n    42\n    return z\n")
    assert v.invs() == () and v.post().args[1].name == "z"


if __name__ == "__main__":
    test_docstring_and_bare_call_are_inert()
    test_bare_int_is_inert()
    print("ok: expression statements inert; effects ride")
