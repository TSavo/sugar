"""``value.name`` on a constructed value: the ``py.getattr`` coordinate.

One law, written once, for every value that projects to a term and owns no
field of its own. ``StringValue`` stated it first ("bound methods and fields on
a constructed string stay the py.getattr coordinate -- same EUF vocabulary as
SymbolicValue / CallSiteValue"), and the constructed containers stand in
exactly the same place: a dict/list/tuple/set literal has no field the lift
knows, and its methods have no body here.

The coordinate is not a claim that the attribute EXISTS. It is an opaque
function symbol over the receiver's own term and the attribute's name -- the
same position ``SymbolicValue`` and ``CallSiteValue`` already occupy. Nothing
is invented: no method body, no field value, no sentinel. A call through the
coordinate is still owned by ``call_method_with``, which folds only where the
call site is known.
"""

from __future__ import annotations


def getattr_coordinate(value, name: str, *, owner: str):
    """``Complete(SymbolicValue(py.getattr(<value term>, "<name>")))``."""
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.outcome import Complete

    return Complete(
        SymbolicValue(ctor("py.getattr", [value.to_term(owner=owner), str_const(name)]))
    )
