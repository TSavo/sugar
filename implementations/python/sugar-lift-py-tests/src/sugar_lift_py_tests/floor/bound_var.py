from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class BoundVar(FloorValue):
    """A bound variable: a name ALIASING an expression.

    `let x = y()` binds x to the SOURCE `y()` (a composed body), not to y()'s
    collapsed value -- so y() stays recoverable. A reference to x recomposes the
    source: x genuinely IS y(), reached through the alias x. A later pass recovers the
    original expression from `.source` -- the map element under a lambda param, the
    curried argument, the definition a temporal rewrite has to hoist. Collapsing the
    binding to a value (the old BindingValue) made all of that impossible: once `y()`
    is a number you cannot get `y()` back.

    The block threads a BoundVar as a scope effect (a let); it is not itself a return.
    """

    name: str
    source: object  # the rhs's composed body (a SugarBody): recoverable + recomposable
    # The DEFINITION scope -- the ctx as it stood when this binding was made, where the
    # name still holds its OLD value. A reference recomposes `source` against THIS, not
    # the current scope, so a self-referential rebind (`x = x + 1`) reads the old x and
    # terminates instead of recomposing against itself forever.
    scope: object = None
