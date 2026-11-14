# SPDX-License-Identifier: MIT OR Apache-2.0
"""The one test helper that builds a frame-fresh ``list``/``dict``/``set``.

A ``ListValue``/``DictValue``/``SetValue`` and an ``ObjectValue`` (an
instance of a source class) have no default ``allocation``
(``sugar_lift_py_tests.floor.object_identity``): every construction names
it.  A test that stands a container up directly, as if a display in the
frame reading it had made it, names that here, explicitly, through
``fresh``; a test that stands an instance up as if a class call in the
frame reading it had made it passes ``allocation=FRAME_FRESH``.  A test
that means an object that arrived (not current) builds it with
``allocation=None`` itself.
"""

from __future__ import annotations

# The ``allocation`` of a container or an instance a test made as if in the
# frame reading it.  Every such object shares it, so two are never decided
# distinct by ``is``.
FRAME_FRESH = "test:allocation:frame-fresh"


def fresh(kind, contents):
    """``kind(contents)`` made in the frame reading it: current contents.

    A test parametrized over sequence kinds may hand ``TupleValue``, which
    has no ``allocation`` (an immutable value has no currency): it is built
    as it is."""
    if "allocation" not in getattr(kind, "__dataclass_fields__", {}):
        return kind(contents)
    return kind(contents, allocation=FRAME_FRESH)
