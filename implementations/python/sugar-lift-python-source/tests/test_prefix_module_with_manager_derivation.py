"""The export prefix door derives the managers of the withs a module runs.

pandas ``io/pytables.py:227`` runs ``with config.config_prefix("io.hdf"):`` at
import, before ``class HDFStore``.  A module lift seats a manager derivation
for that with; the export-prefix door (``_module_prefix_outcome``) built its
own SourceFile and never derived one.  So the with refused as "no
context-manager derivation", and every export after it became
``dynamic-export``.

Law: the prefix door executes the module's statements, so a with the module
runs at import is constructed through the same derivation a module lift
seats.  A with inside a def is not run at import, so it is not selected.
Twin: a with whose body raises past a non-suppressing exit still keeps the
prefix from falling through.
"""

from __future__ import annotations

import ast

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import AuthenticatedModuleSourceV1
from sugar_lift_python_source.manager_construction import (
    prefix_has_completed_fallthrough,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession

_EXPORT = "class HDFStore:\n    pass\n"


def _outcome(source: str):
    module = AuthenticatedModuleSourceV1(
        module_name="prefix_module_with",
        source_seat="prefix_module_with.py",
        source_cid=blake3_512_of(source.encode()),
        source=source,
    )
    locus = ast.parse(source).body[-1]
    return prefix_has_completed_fallthrough(
        module, locus, session=SourceResolutionSession(enrolled_distributions=frozenset())
    )


def test_module_level_with_over_imported_manager_constructs():
    source = (
        "import contextlib\nwith contextlib.suppress(Exception):\n    x = 1\n" + _EXPORT
    )
    assert _outcome(source).kind == "completed"


def test_module_level_with_over_same_module_manager_constructs():
    source = (
        "class C:\n    def __enter__(self):\n        return self\n"
        "    def __exit__(self, *a):\n        return False\n"
        "with C():\n    x = 1\n" + _EXPORT
    )
    assert _outcome(source).kind == "completed"


def test_module_level_with_whose_body_raises_does_not_fall_through():
    source = (
        "class C:\n    def __enter__(self):\n        return self\n"
        "    def __exit__(self, *a):\n        return False\n"
        "with C():\n    raise ValueError\n" + _EXPORT
    )
    assert _outcome(source).kind == "ordinary-non-fallthrough"
