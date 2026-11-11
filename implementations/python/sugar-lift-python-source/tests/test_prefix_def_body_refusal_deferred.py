"""A ``def`` body does not run at import: its refusal is not prefix testimony.

pandas ``io/pytables.py`` defines ``to_hdf`` (whose body does
``with HDFStore(...) as store:``) before ``class HDFStore``.  The export prefix
door threaded every prefix def's BODY, met the body's With with no manager
derivation, and reported ``construction-refusal`` for the whole prefix.  So
``HDFStore`` became ``dynamic-export`` because of a statement that only binds
a function.

Law: a def statement binds a function object; its body runs when something
calls the function.  A refusal inside the body is deferred to that call,
where the caller's frame substitutes the body again.  It is never testimony
about the prefix that merely defined the function.  The twin: when the
prefix DOES call the function or method, the refusal is still testimony.
A method in a class body is the same: the class statement runs, the method
body does not.
"""

from __future__ import annotations

import ast

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import AuthenticatedModuleSourceV1
from sugar_lift_python_source.manager_construction import (
    prefix_has_completed_fallthrough,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession

_HEAD = "try:\n    import zzz_absent\nexcept ImportError:\n    zzz_absent = None\n"
_TO_HDF = "def to_hdf(path, key):\n    with HDFStore(path) as store:\n        store.put(key)\n"
_METHOD = (
    "class Writer:\n    def write(self, path):\n"
    "        with HDFStore(path) as store:\n            store.put(1)\n"
)
_EXPORT = "class HDFStore:\n    pass\n"


def _outcome(source: str):
    module = AuthenticatedModuleSourceV1(
        module_name="prefix_def_body",
        source_seat="prefix_def_body.py",
        source_cid=blake3_512_of(source.encode()),
        source=source,
    )
    locus = ast.parse(source).body[-1]
    return prefix_has_completed_fallthrough(
        module, locus, session=SourceResolutionSession(enrolled_distributions=frozenset())
    )


@pytest.mark.parametrize("definition", [_TO_HDF, _METHOD], ids=["function", "method"])
def test_uncalled_definition_body_refusal_is_not_prefix_testimony(definition):
    assert _outcome(_HEAD + definition + _EXPORT).kind == "completed"


def test_called_definition_body_refusal_is_prefix_testimony():
    outcome = _outcome(_HEAD + _TO_HDF + "to_hdf(1, 2)\n" + _EXPORT)
    assert outcome.kind == "construction-refusal"
    assert "With._construct_sugar" in outcome.detail


@pytest.mark.parametrize("call", ["Writer().write(1)\n", "Writer.write(None, 1)\n"])
def test_called_method_body_refusal_is_prefix_testimony(call):
    outcome = _outcome(_HEAD + _METHOD + call + _EXPORT)
    assert outcome.kind == "construction-refusal"
    assert "With._construct_sugar" in outcome.detail
