from __future__ import annotations

from dataclasses import dataclass, field

from .floor_value import FloorValue


@dataclass(frozen=True)
class ObjectMethodValue(FloorValue):
    """A source method of a class's roster, as the one method door binds it
    (``object_value.bind_method_call``): its name, its formals and its frame.
    It carries no body: a call of it is its coordinate and edge
    (``object_value.method_edge_call``, #7757 step 6), and what its body
    does is its own universe's contract, joined at prove."""

    name: str
    parameters: tuple[str, ...]
    source_call_frame_cid: str | None = None
    formal_coordinate_cids: tuple[str, ...] = ()
    source_call_frame: object | None = field(default=None, compare=False, repr=False)
    descriptor_kind: str | None = None
    # Exact lexical owner of this method body.  Inherited methods retain their
    # defining class rather than being rebound to the runtime receiver class;
    # this is the authenticated ``__class__`` cell used by zero-arg super().
    defining_class: object | None = field(default=None, compare=False, repr=False)

    def setitem(self, index, value, site, ctx):
        del index, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="ObjectMethodValue.setitem",
        )

    def delitem(self, index, site, ctx):
        del index, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="ObjectMethodValue.delitem",
        )

    def setattr(self, name, value, site, ctx):
        del value, ctx
        from sugar_lift_py_tests.floor.ground_exit import builtin_attribute_store_exit

        return builtin_attribute_store_exit(
            name, site=site, owner="ObjectMethodValue.setattr"
        )

    def delattr(self, name, site, ctx):
        del ctx
        from sugar_lift_py_tests.floor.ground_exit import builtin_attribute_store_exit

        return builtin_attribute_store_exit(
            name, site=site, owner="ObjectMethodValue.delattr"
        )
