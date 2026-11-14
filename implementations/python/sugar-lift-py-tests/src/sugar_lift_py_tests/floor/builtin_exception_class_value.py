from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Term

from .class_value import ClassValue


@dataclass(frozen=True)
class BuiltinExceptionClassValue(ClassValue):
    """Exact lexical identity for an exception class owned by ``builtins``.

    This is seeded from a static language vocabulary. A same-spelled user binding
    replaces this floor in the temporal scope and therefore cannot inherit builtin
    constructor semantics by leaf-name coincidence.
    """

    def setitem(self, index, value, site, ctx):
        del index, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="BuiltinExceptionClassValue.setitem",
        )

    def delitem(self, index, site, ctx):
        del index, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="BuiltinExceptionClassValue.delitem",
        )

    def setattr(self, name, value, site, ctx):
        del name, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="BuiltinExceptionClassValue.setattr",
        )

    def delattr(self, name, site, ctx):
        del name, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="BuiltinExceptionClassValue.delattr",
        )

    def initialize_instance(self, receiver, arguments, keywords, *, blame, owner):
        """``super().__init__(*arguments, **keywords)`` reaching this class's
        ``__init__`` on ``receiver``, the instance a source subclass's
        ``__init__`` is building.

        BaseException's law (``BaseException_init``, Objects/exceptions.c):
        a keyword actual raises TypeError; otherwise ``args`` becomes the
        positional actuals and the call returns None.  The receiver leaves
        the call carrying ``args`` (a ``ReceiverOwnedMutationResult``, read
        by the constructor as the receiver's state).  A class whose
        constructor is not that law (``SyntaxError``, ``OSError``, the
        ``Unicode*Error`` and group classes), a keyword actual a class may
        read (``ImportError``, ``AttributeError``, ``NameError``), or a
        receiver that is no constructed instance is refused by name."""
        from dataclasses import replace

        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.floor.object_field import ObjectField
        from sugar_lift_py_tests.floor.object_value import ObjectValue
        from sugar_lift_py_tests.floor.receiver_owned_mutation_result import (
            ReceiverOwnedMutationResult,
        )
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            builtin_exception_constructor_is_args_total,
            builtin_exception_constructor_rejects_keywords,
        )

        if keywords and builtin_exception_constructor_rejects_keywords(self.name):
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=blame, owner=f"{owner} {self.name}.__init__")
        if (
            keywords
            or not builtin_exception_constructor_is_args_total(self.name)
            or not isinstance(receiver, ObjectValue)
        ):
            construction_panic_gap(
                owner=f"{owner} {self.name}.__init__",
                blame=blame,
                observed=(
                    f"{type(receiver).__name__} receiver, "
                    f"{len(tuple(keywords))} keyword actuals"
                ),
                requested="BaseException's (*args) __init__ on a constructed instance",
                fix="model this builtin exception's own __init__ or keep the call loud",
            )
        after = replace(
            receiver,
            fields=(
                *receiver.fields,
                ObjectField("args", TupleValue(elements=tuple(arguments))),
            ),
        )
        return ExitSet.completed(
            ReceiverOwnedMutationResult(receiver, after, NoneValue())
        )

    def exception_type_identity(self) -> Term:
        """Same coordinate ``SourceUnit.exception_type_identity`` publishes for builtins."""
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:exception_type_identity",
            [str_const("builtins"), str_const(_canonical(self.name))],
        )

    def exception_type_mro(self) -> tuple[Term, ...]:
        """Closed builtin ancestry, leaf-first, matching the language table."""
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            BUILTIN_EXCEPTION_BASES,
        )

        def identity(name: str) -> Term:
            return ctor(
                "python:exception_type_identity",
                [str_const("builtins"), str_const(name)],
            )

        ordered: list[str] = []
        seen: set[str] = set()

        def walk(name: str) -> None:
            if name in seen:
                return
            seen.add(name)
            ordered.append(name)
            for base in BUILTIN_EXCEPTION_BASES.get(name, ()):
                walk(base)

        walk(_canonical(self.name))
        return tuple(identity(name) for name in ordered)


def _canonical(name: str) -> str:
    from sugar_lift_py_tests.temporal.builtin_name_bindings import (
        canonical_builtin_exception_name,
    )

    return canonical_builtin_exception_name(name)
