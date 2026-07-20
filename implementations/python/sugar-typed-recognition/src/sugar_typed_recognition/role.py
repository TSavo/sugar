"""The role a claim answers for. The FIRST dispatch axis.

Roles mirror the existing ``sugar_lift_py_tests.claim.SugarRole`` vocabulary
by name so a later migration is a rename, not a re-derivation. Declared here
rather than imported because this package is greenfield: it imports the
membrane and nothing else from the tree (#5940).

A role is not a node shape. ``Call`` appears as a TERM; ``Assert`` appears as
a STATEMENT; the same node class could legitimately be claimed under two
roles by two different claims, and that is not ambiguity — the caller asks
for one role at a time.
"""

from __future__ import annotations

from enum import Enum


class Role(Enum):
    TERM = "term"
    STATEMENT = "statement"
    DEFINITION = "definition"
