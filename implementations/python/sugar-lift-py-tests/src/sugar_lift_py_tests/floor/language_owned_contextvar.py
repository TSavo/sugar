"""Language-owned ``contextvars.ContextVar.set`` / ``reset`` (plan Cut 2).

``contextvars.ContextVar`` is reexported from the C module ``_contextvars``,
which has no authenticated source. Recognition keys on runtime identity of an
``artifact-module-absent`` export (the class, an instance, or another C-floor
callable), never on a use-site spelling. ``set`` returns a token; ``reset``
returns ``None``. This does not invent bodies for other C-extension members.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from .floor_value import FloorValue


_TOKEN_IDS = itertools.count(1)


@dataclass(frozen=True)
class LanguageOwnedContextVarType(FloorValue):
    """The language-owned ``ContextVar`` class."""

    site: object = None

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        del owner
        return ctor("python:contextvars.ContextVar.type", ())

    def callable_application_with(self, operation, ctx):
        del ctx
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.outcome import Complete
        from sugar_source_tree.panic import SugarNotWritten

        if operation.keyword_names or len(operation.arguments) != 1:
            raise SugarNotWritten(
                blame=getattr(operation, "blame", None),
                owner="LanguageOwnedContextVarType.callable_application_with",
                observed=(len(operation.arguments), operation.keyword_names),
                requested="ContextVar(name) with a concrete string name",
                fix="keep a default or a non-string name loud; do not invent a ContextVar",
            )
        name = operation.arguments[0]
        if not isinstance(name, StringValue):
            raise SugarNotWritten(
                blame=getattr(operation, "blame", None),
                owner="LanguageOwnedContextVarType.callable_application_with",
                observed=type(name).__name__,
                requested="ContextVar(name) with a concrete string name",
                fix="keep a non-string name loud; do not invent a ContextVar",
            )
        return Complete(
            LanguageOwnedContextVarValue(
                name=name.value, site=getattr(operation, "blame", None)
            )
        )


@dataclass(frozen=True)
class LanguageOwnedContextVarValue(FloorValue):
    """One constructed ``ContextVar`` instance."""

    name: str
    site: object = None

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor("python:contextvars.ContextVar", (str_const(self.name),))

    def attribute(self, name, site):
        if name in {"set", "reset"}:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(
                LanguageOwnedContextVarMethodValue(
                    variable=self, method=name, site=site
                )
            )
        return super().attribute(name, site)

    def call_method_with(self, operation, ctx):
        del ctx
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.outcome import Complete

        if operation.name == "set" and not operation.keyword_names and len(operation.arguments) == 1:
            return Complete(
                LanguageOwnedContextVarToken(
                    variable_name=self.name,
                    token_id=next(_TOKEN_IDS),
                    site=getattr(operation, "blame", None),
                )
            )
        if operation.name == "reset" and not operation.keyword_names and len(operation.arguments) == 1:
            token = operation.arguments[0]
            if (
                isinstance(token, LanguageOwnedContextVarToken)
                and token.variable_name == self.name
            ):
                return Complete(NoneValue())
        return super().call_method_with(operation, ctx)


@dataclass(frozen=True)
class LanguageOwnedContextVarToken(FloorValue):
    """A token produced by ``ContextVar.set`` and consumed by ``reset``."""

    variable_name: str
    token_id: int
    site: object = None

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, int_const, str_const

        del owner
        return ctor(
            "python:contextvars.Token",
            (str_const(self.variable_name), int_const(self.token_id)),
        )



@dataclass(frozen=True)
class LanguageOwnedContextVarMethodValue(FloorValue):
    """A bound ``ContextVar.set`` or ``reset`` method."""

    variable: LanguageOwnedContextVarValue
    method: str
    site: object = None

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor(
            "python:contextvars.ContextVar.method",
            (str_const(self.variable.name), str_const(self.method)),
        )

    def callable_application_with(self, operation, ctx):
        from types import SimpleNamespace

        method_op = SimpleNamespace(
            name=self.method,
            arguments=getattr(operation, "arguments", ()),
            keyword_names=getattr(operation, "keyword_names", ()),
            blame=getattr(operation, "blame", None) or self.site,
        )
        return self.variable.call_method_with(method_op, ctx)


@dataclass(frozen=True)
class LanguageOwnedCExtensionCallableValue(FloorValue):
    """A C-extension function whose body is not authenticated source.

    A call has two faces under one opaque partition atom,
    ``python:c_extension.call_completes(module, name, site)``. Completed carries
    an opaque result, and its complement is Halted with an UndeterminedRaiseEffect,
    because native code may raise any exception (os.chdir raises
    FileNotFoundError on a missing path). Neither face invents the vendor's
    semantics, and a caller that needs the call to be total sees the halt.
    """

    module_name: str
    exported_name: str
    site: object = None

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor(
            "python:c_extension.callable",
            (str_const(self.module_name), str_const(self.exported_name)),
        )

    def callable_application_with(self, operation, ctx):
        del ctx
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.ir import atomic, ctor, str_const
        from sugar_lift_py_tests.outcome.exit_set import (
            Completed,
            ExitSet,
            Halted,
            complement_guard,
        )

        site = getattr(operation, "blame", None) or getattr(operation, "site", None)
        call = ctor(
            "python:c_extension.call",
            (
                str_const(self.module_name),
                str_const(self.exported_name),
                str_const(str(site)),
            ),
        )
        completes = atomic("python:c_extension.call_completes", [call])
        return (
            ExitSet(
                (
                    Completed(
                        completes,
                        LanguageOwnedCExtensionResultValue(
                            module_name=self.module_name,
                            exported_name=self.exported_name,
                            site=site,
                        ),
                    ),
                    Halted(
                        complement_guard(completes),
                        UndeterminedRaiseEffect(
                            blame=str(site) if site is not None else None,
                            occurrence=str(site) if site is not None else None,
                            producer_node_owner=(
                                "LanguageOwnedCExtensionCallableValue"
                                f":{self.module_name}.{self.exported_name}"
                            ),
                        ),
                        None,
                    ),
                )
            ).normalize()
        )


@dataclass(frozen=True)
class LanguageOwnedCExtensionResultValue(FloorValue):
    """An opaque result of a C-extension call with no authenticated body."""

    module_name: str
    exported_name: str
    site: object = None

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor(
            "python:c_extension.result",
            (str_const(self.module_name), str_const(self.exported_name)),
        )
