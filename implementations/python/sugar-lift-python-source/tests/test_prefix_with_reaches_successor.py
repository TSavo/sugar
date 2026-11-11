"""A module-level ``with`` reaches the next statement or aborts the import.

pandas ``io/pytables.py:227`` runs ``with config.config_prefix("io.hdf"):``
before ``class HDFStore`` (line 497).  The export door asks whether every
successful import reaches the export's binding.  It had no arm for ``with``,
so it fell back to executing the prefix.  That execution refused inside
``config_prefix``'s generator (a ``global`` rebinding), and ``HDFStore``
became ``dynamic-export``: board file ``tests/io/pytables/test_subclass.py``
(Part of #7664).

Law: a successful import passes a with in one of two ways.  Either the body
completes and ``__exit__`` returns, or the body raises and the manager
suppresses it.  Both continue at the statement after the with; a raise out of
``__enter__`` or ``__exit__`` aborts the import.  So a with whose body reaches
its own end reaches its successor.  The twin: a body that always raises
reaches the successor only if the manager suppresses, which nothing
testified, so it is not admitted.
"""

from __future__ import annotations

import ast

from sugar_lift_python_source.dependency_export_adapter import (
    _prefix_reaches_locus_or_aborts,
)


def _reaches(source: str) -> bool:
    tree = ast.parse(source)
    return _prefix_reaches_locus_or_aborts(tree.body, tree.body[-1])


def test_module_level_with_reaches_the_export():
    assert _reaches(
        "from m import config\n"
        "with config.config_prefix('io.hdf'):\n"
        "    config.register_option('x', 1)\n"
        "class HDFStore:\n    pass\n"
    )


def test_nested_with_reaches_the_export():
    assert _reaches(
        "import m\nwith m.a():\n    with m.b():\n        x = 1\nclass E:\n    pass\n"
    )


def test_a_with_body_that_always_raises_is_not_admitted():
    # The body never reaches its end: only a suppressing manager would let
    # the import continue, and nothing testified to suppression.
    assert not _reaches(
        "import m\nwith m.a():\n    raise ValueError\nclass E:\n    pass\n"
    )
