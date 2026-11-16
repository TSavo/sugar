from __future__ import annotations

from dataclasses import dataclass

from sugar_source_tree.fragment import SourceMemento

from .floor_value import FloorValue


@dataclass(frozen=True)
class MutableGlobalValue(FloorValue):
    """A mutable module binding authenticated at its defining target."""

    name: str
    kind: str
    pin_source_cid: str
    binding_memento: SourceMemento

    def __post_init__(self) -> None:
        if not isinstance(self.binding_memento, SourceMemento):
            raise TypeError("MutableGlobalValue binding_memento must be SourceMemento")
        if self.binding_memento.source_cid != self.pin_source_cid:
            raise ValueError(
                "MutableGlobalValue requires its exact binding SourceMemento/source CID"
            )

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, num, str_const

        return ctor(
            "python:mutable_global_pin",
            [
                str_const(self.name),
                str_const(self.kind),
                str_const(self.binding_memento.file),
                str_const(self.binding_memento.source_cid),
                str_const(self.binding_memento.cid),
                num(self.binding_memento.start),
                num(self.binding_memento.end),
            ],
        )

    def denotes_value(self) -> bool:
        return True

    def runtime_type_is_decided(self) -> bool:
        """Only dict pins decide membership/lookup structure; other kinds stay undecided."""
        return self.kind == "dict"

    def attribute(self, name, site, ctx):
        """Mutable pin has no field layout at lift — undecided, not missing Floor.attribute."""
        del ctx
        from sugar_lift_py_tests.floor.floor_value import undecided_attribute_result

        return undecided_attribute_result(
            self, name, site, owner="MutableGlobalValue.attribute"
        )

    def subscript(self, index, site):
        from sugar_lift_py_tests.floor.floor_value import index_type_undecided

        # A key whose type nothing here decides -- a parameter's, an opaque
        # call result's -- may raise anything from its ``__hash__`` or
        # ``__eq__``, not only ``KeyError``: the one undecided read, its halt
        # kept (#7757).
        if self.kind != "dict" or index_type_undecided(index):
            return self.undecided_subscript(
                index, site, owner="MutableGlobalValue.subscript"
            )
        if getattr(site, "source_cid", None) != self.pin_source_cid:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                blame=site,
                owner="MutableGlobalValue.subscript",
                observed="foreign source for mutable-global lookup occurrence",
                requested="an authenticated lookup site from the pin's SourceUnit",
                fix="carry the binding-owned pin into same-source module temporal state",
            )

        from sugar_lift_py_tests.floor.ground_exit import ground_raise_effect
        from sugar_lift_py_tests.ir import atomic
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.outcome.exit_set import complement_guard

        raises = atomic(
            "python.mutable_dict_lookup_raises_key_error",
            [
                self.to_term(owner="mutable global lookup"),
                index.to_term(owner="mutable global lookup"),
            ],
        )
        coordinate = self.py_subscript_coordinate(index, site)
        effect = ground_raise_effect(
            exception_name="KeyError",
            site=site,
            owner="MutableGlobalValue.subscript",
        )
        # Whether the dict holds the key is not decided here, so the lookup
        # is the one two-faced outcome (``ExitSet.two_faced``): it completes
        # with the coordinate where the lookup does not raise and halts with
        # ``KeyError`` under the complement, and both arms owe the
        # ``undecided`` member at this site.  The pair is built beneath every
        # completed arm of the coordinate: each arm's guard, faces and
        # ``owed`` ride onto both, and a halt of the coordinate stands.
        return coordinate.and_then(
            lambda value: ExitSet.two_faced(
                value, effect, guard=complement_guard(raises), site=site
            )
        )

    def contains(self, item, site):
        """``item in <mutable global>``: the floor's one undecided membership.

        The pin names the binding, not its members: another function may
        have changed them, so which keys it holds is not decided here.  A
        dict probes by hash and compares a colliding key with ``==``, which
        may run a stored key's ``__eq__``; any other kind's ``__contains__``
        is not decided at all.  Either way ``item in self`` may raise:
        two faces, the halt kept, owed (#7757 H10) -- never a bare
        ``py.in``.  It reads no member, so the site's source is not asked."""
        return self.undecided_contains(item, site, owner="MutableGlobalValue.contains")
