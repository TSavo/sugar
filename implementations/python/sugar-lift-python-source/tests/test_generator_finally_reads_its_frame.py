"""A generator ``finally`` runs in the generator's own frame.

numpy's ``printoptions(*args, **kwargs)`` is ``token = _set_printoptions(
*args, **kwargs); try: yield get_printoptions(); finally:
format_options.reset(token)``.  Substitution inlines ``token``'s RHS into the
cleanup.  The cleanup was reduced with no context at all, so that inlined
call met ``*args``/``**kwargs`` as unspecialized formals and the whole
``with`` refused.  The cleanup now reduces under the generator's frame
context: the formal Floors the caller bound, and each assignment step's
completed value, so the inlined RHS answers with the value the step completed
with (#7600) instead of being evaluated a second time.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.nodes import FunctionDef

from test_numpy_errstate_construction import _corpus, _open

PRINTOPTIONS = (
    "import numpy as np\n"
    "def f():\n"
    "    with np.printoptions(precision=3):\n"
    "        return 1\n"
)


def _exits(tmp_path):
    root = _corpus(tmp_path, **{"e.py": PRINTOPTIONS})
    source_file = _open(
        root,
        "e.py",
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({"tiny-corpus", "numpy"})
        ),
    )
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    return outcome_to_exitset(func.sugar().desugar()).exits


def test_printoptions_cleanup_reads_the_frame(tmp_path):
    exits = _exits(tmp_path)
    returned = [
        statement.value
        for face in exits
        if isinstance(face, Completed)
        for statement in face.value.record.statements
        if isinstance(statement, ReturnValue)
    ]
    assert returned == [TermValue(1)]
    owners = [
        face.effect.producer_node_owner
        for face in exits
        if isinstance(face, Halted) and isinstance(face.effect, UndeterminedRaiseEffect)
    ]
    # ``_set_printoptions(*args, **kwargs)`` splats the decided ``()`` and
    # ``{'precision': 3}``, so its source body runs, once (its faces are the
    # enter's): ``format_options.get() | new_opt`` is one undecided ``|``.
    # The cleanup's reset of the token it returned is its own two faces.
    assert owners.count("UnprojectedSpreadCall:_set_printoptions") == 0
    assert owners.count("UndecidedBinary:|") == 1
    assert owners.count("ContextVarReset:format_options") == 1

