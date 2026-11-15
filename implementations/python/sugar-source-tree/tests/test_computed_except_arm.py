"""An ``except`` type with no lexical identity is a computed arm (#7757).

``except excs_to_catch:`` (``io/pickle.py:229``, ``excs_to_catch`` a local
bound to a tuple of builtin classes) and ``except (TypeError,
pa.ArrowInvalid):`` (``io/orc.py:128``, ``pa`` a call's result) name no class
through an import, a builtin or a class statement.  The ``try`` was refused
at construction (``typed except handler lacks authenticated exception
identity``).  CPython evaluates the arm's type only when an exception
reaches it and matches the class, or tuple of classes, it holds: the arm is
``ComputedExceptionTypeSugar``, as ``except tuple(types):`` already was, and
a value with no authenticated identity is refused by name there.
"""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def _report(source: str):
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(source)
    f.close()
    return discharge(
        SourceFile(
            path_source(f.name),
            reporter=CollectingReporter(),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )


@pytest.mark.parametrize(
    "source",
    [
        "def f(d, k):\n"
        "    excs = (KeyError, TypeError)\n"
        "    try:\n"
        "        return d[k]\n"
        "    except excs:\n"
        "        return 0\n",
        "def f(load, g):\n"
        "    pa = load()\n"
        "    try:\n"
        "        return g()\n"
        "    except (TypeError, pa.ArrowInvalid):\n"
        "        return 0\n",
    ],
)
def test_an_arm_with_no_lexical_identity_is_computed(source):
    report = _report(source)
    observed = [
        str(getattr(panic, "observed", "")) for _node, panic in report.reporter.gaps
    ]
    assert not any(
        "typed except handler lacks authenticated exception identity" in text
        for text in observed
    )
