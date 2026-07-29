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

    def subscript(self, index, site):
        if self.kind != "dict":
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
        from sugar_lift_py_tests.outcome.exit_set import (
            Completed,
            Halted,
            complement_guard,
            partition,
        )

        raises = atomic(
            "python.mutable_dict_lookup_raises_key_error",
            [self.to_term(owner="mutable global lookup"), index.to_term(owner="mutable global lookup")],
        )
        halted_face, completed_face = partition(
            ("mutable-global-dict-subscript", _occurrence_key(site))
        )
        completed = self.py_subscript_coordinate(index, site).value
        effect = ground_raise_effect(
            exception_name="KeyError",
            site=site,
            owner="MutableGlobalValue.subscript",
        )
        return ExitSet(
            (
                Halted(raises, effect, faces=frozenset({halted_face})),
                Completed(
                    complement_guard(raises),
                    completed,
                    frozenset({completed_face}),
                ),
            )
        ).normalize()

    def contains(self, item, site):
        if self.kind != "dict":
            return super().contains(item, site)
        if getattr(site, "source_cid", None) != self.pin_source_cid:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                blame=site,
                owner="MutableGlobalValue.contains",
                observed="foreign source for mutable-global membership occurrence",
                requested="authenticated same-source membership occurrence",
                fix="carry the binding-owned pin into same-source module temporal state",
            )

        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import atomic
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            PredicateValue(
                atomic(
                    "py.in",
                    [
                        item.to_term(owner="python.mutable_dict.contains key"),
                        self.to_term(owner="python.mutable_dict.contains dict"),
                    ],
                ),
                site,
                operand_callsites=(*item.callsites(), *self.callsites()),
            )
        )


def _occurrence_key(site: object) -> tuple[object, object, object, object]:
    fragment = getattr(site, "fragment", site)
    span = getattr(fragment, "span", None)
    return (
        getattr(fragment, "filename", None),
        getattr(fragment, "source_cid", None),
        getattr(span, "start", None),
        getattr(span, "end", None),
    )
