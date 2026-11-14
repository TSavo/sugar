"""Language-owned ``contextvars.ContextVar.set`` / ``reset`` (plan Cut 2).

``contextvars.ContextVar`` is reexported from the C module ``_contextvars``,
which has no authenticated source. Recognition keys on runtime identity of an
``artifact-module-absent`` export (the class, an instance, or another C-floor
callable), never on a use-site spelling. ``set`` returns a token; ``reset``
returns ``None``. This does not invent bodies for other C-extension members.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .floor_value import FloorValue


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

        # A refusal needs a real coordinate: CallableApplication carries its
        # call site as ``site``, not ``blame``.
        site = getattr(operation, "blame", None) or getattr(operation, "site", None)
        from sugar_lift_py_tests.outcome import Complete
        from sugar_source_tree.panic import SugarNotWritten

        # ``ContextVar(name, *, default=...)``: ``default`` is keyword-only and
        # changes only what ``get()`` returns with no value set; ``set`` and
        # ``reset`` (the members this floor carries) do not read it.
        if operation.keyword_names not in ((), ("default",)) or len(
            operation.arguments
        ) != 1 + len(operation.keyword_names):
            raise SugarNotWritten(
                blame=site,
                owner="LanguageOwnedContextVarType.callable_application_with",
                observed=(len(operation.arguments), operation.keyword_names),
                requested="ContextVar(name[, default=...]) with a concrete string name",
                fix="keep another keyword or a non-string name loud; do not invent a ContextVar",
            )
        name = operation.arguments[0]
        if not isinstance(name, StringValue):
            raise SugarNotWritten(
                blame=site,
                owner="LanguageOwnedContextVarType.callable_application_with",
                observed=type(name).__name__,
                requested="ContextVar(name) with a concrete string name",
                fix="keep a non-string name loud; do not invent a ContextVar",
            )
        return Complete(
            LanguageOwnedContextVarValue(
                name=name.value,
                site=getattr(operation, "blame", None),
                has_default=bool(operation.keyword_names),
            )
        )


@dataclass(frozen=True)
class LanguageOwnedContextVarValue(FloorValue):
    """One constructed ``ContextVar`` instance."""

    name: str
    site: object = None
    # ``ContextVar(name, default=...)``: ``get()`` never raises LookupError.
    has_default: bool = False

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor("python:contextvars.ContextVar", (str_const(self.name),))

    def attribute(self, name, site):
        if name in {"set", "reset"} or (name == "get" and self.has_default):
            from sugar_lift_py_tests.outcome import Complete

            return Complete(
                LanguageOwnedContextVarMethodValue(
                    variable=self, method=name, site=site
                )
            )
        return super().attribute(name, site)

    def call_named_method(
        self, name, arguments, *, owner, blame, ctx=None, keywords=()
    ):
        """``v.name(...)`` written as a method call on this ContextVar.

        The source method call reaches the same law as the floored
        ``v.get`` / ``v.set`` / ``v.reset`` value: ``set``, ``reset``, and
        ``get`` with a default are decided here; every other method (and
        ``get`` with no default, which may raise LookupError) refuses by name.
        """
        from types import SimpleNamespace

        return self.call_method_with(
            SimpleNamespace(
                name=name,
                arguments=(*arguments, *(value for _, value in keywords)),
                keyword_names=tuple(key for key, _ in keywords),
                owner=owner,
                blame=blame,
            ),
            ctx,
        )

    def call_method_with(self, operation, ctx):
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.outcome import Complete

        if operation.name == "set" and not operation.keyword_names and len(operation.arguments) == 1:
            # The token is the ``set`` at this occurrence: keyed by where it
            # happens, exactly as a ``get`` read is, never by a process draw.
            from sugar_lift_py_tests.occurrence import occurrence_key

            site = getattr(operation, "blame", None)
            if site is None:
                from sugar_source_tree.panic import SugarNotWritten

                raise SugarNotWritten(
                    blame=f"python:contextvars.ContextVar({self.name!r}).set",
                    owner="LanguageOwnedContextVarValue.set",
                    observed="ContextVar.set() with no call site",
                    requested="the call site that keys this token's occurrence",
                    fix="carry the call site onto the method application",
                )
            return Complete(
                LanguageOwnedContextVarToken(
                    variable_name=self.name,
                    occurrence=occurrence_key(site),
                    site=site,
                )
            )
        if (
            operation.name == "get"
            and self.has_default
            and not operation.keyword_names
            and not operation.arguments
        ):
            # The value set in the CURRENT context, or the default: which one
            # is a property of the running context, not of this source.
            from sugar_lift_py_tests.occurrence import occurrence_key

            site = getattr(operation, "blame", None)
            if site is None:
                # The read is keyed by where it happens; with no site two
                # reads would share one term and be claimed equal.
                from sugar_source_tree.panic import SugarNotWritten

                raise SugarNotWritten(
                    blame=f"python:contextvars.ContextVar({self.name!r}).get",
                    owner="LanguageOwnedContextVarValue.get",
                    observed="ContextVar.get() with no call site",
                    requested="the call site that keys this read's occurrence",
                    fix="carry the call site onto the method application",
                )
            return Complete(
                LanguageOwnedContextVarReadValue(
                    variable_name=self.name,
                    site=site,
                    occurrence=occurrence_key(site),
                )
            )
        if operation.name == "reset" and not operation.keyword_names and len(operation.arguments) == 1:
            token = operation.arguments[0]
            if (
                isinstance(token, LanguageOwnedContextVarToken)
                and token.variable_name == self.name
            ):
                return Complete(NoneValue())
            site = getattr(operation, "blame", None)
            if site is not None and not isinstance(
                token, LanguageOwnedContextVarToken
            ):
                return _undecided_reset_faces(self.name, site)
        return super().call_method_with(operation, ctx)


@dataclass(frozen=True)
class LanguageOwnedContextVarReadValue(FloorValue):
    """The value ``ContextVar.get()`` returned at one occurrence.

    It is whatever the running context holds (the last ``set`` or the
    default); nothing in source decides which, so two reads are never forced
    equal and nothing about the value is claimed.
    """

    variable_name: str
    site: object = None
    occurrence: str | None = None

    def denotes_value(self) -> bool:
        """The read is a Python value: whatever the running context holds."""
        return True

    def runtime_type_is_decided(self) -> bool:
        """Undecided: a ``set`` anywhere may have stored any type."""
        return False

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor(
            "python:contextvars.ContextVar.get",
            (str_const(self.variable_name), str_const(self.occurrence or "")),
        )


@dataclass(frozen=True)
class LanguageOwnedContextVarToken(FloorValue):
    """A token produced by ``ContextVar.set`` and consumed by ``reset``.

    ``occurrence`` is the ``set`` call's occurrence key (site plus occurrence
    path): one token per evaluation of that ``set``, the same in every process.
    """

    variable_name: str
    occurrence: str
    site: object = None

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor(
            "python:contextvars.Token",
            (str_const(self.variable_name), str_const(self.occurrence)),
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
            # A CallableApplication carries its call site as ``site``.
            blame=getattr(operation, "blame", None)
            or getattr(operation, "site", None)
            or self.site,
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
    # The interpreter's own ``warnings.warn`` (keyed by runtime identity in
    # ``floor_artifact_module_absent_export``): its completed face carries the
    # warning its operands authenticate, read through CPython's fixed
    # ``warn(message, category=...)`` signature.
    warning_occurrence: bool = False

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

        from sugar_lift_py_tests.occurrence import occurrence_key

        # A refusal needs a real coordinate: CallableApplication carries its
        # call site as ``site``, not ``blame``.
        site = getattr(operation, "blame", None) or getattr(operation, "site", None)
        key = occurrence_key(site)
        call = ctor(
            "python:c_extension.call",
            (
                str_const(self.module_name),
                str_const(self.exported_name),
                str_const(key),
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
                            occurrence=key,
                            warning_observation=self._warning_observation(
                                operation, site
                            ),
                        ),
                    ),
                    Halted(
                        complement_guard(completes),
                        UndeterminedRaiseEffect(
                            blame=str(site) if site is not None else None,
                            occurrence=key if site is not None else None,
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


    def _warning_observation(self, operation, site):
        """The warning a completed ``warnings.warn`` call emitted, if typed.

        The halted complement stays an undetermined raise: a warnings filter
        set to ``error`` (or a malformed operand) makes the same call raise.
        """
        if not self.warning_occurrence:
            return None
        from sugar_lift_py_tests.sugar.warning_observation_producer import (
            warning_observation_from_operands,
        )

        arguments = getattr(operation, "arguments", None)
        keyword_names = getattr(operation, "keyword_names", None)
        if arguments is None or keyword_names is None:
            return None
        return warning_observation_from_operands(arguments, keyword_names, site)


@dataclass(frozen=True)
class LanguageOwnedCExtensionResultValue(FloorValue):
    """An opaque result of a C-extension call with no authenticated body.

    The term is keyed on the call site, exactly like the call's own
    ``python:c_extension.call(module, name, site)`` completion atom: two calls
    of the same C function return results nobody testified to be equal, so
    their terms are never forced to agree.
    """

    module_name: str
    exported_name: str
    site: object = None
    # The dynamic occurrence of the call that produced this result
    # (``occurrence.occurrence_key``): two iterations of one call site return
    # two results nobody testified to be equal.
    occurrence: str | None = None
    # Statement-position testimony of the interpreter's ``warnings.warn``
    # (``project_warning_observation`` reads it); not part of the result term.
    warning_observation: object = field(default=None, compare=False)

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor(
            "python:c_extension.result",
            (
                str_const(self.module_name),
                str_const(self.exported_name),
                str_const(self.occurrence or str(self.site)),
            ),
        )

    def guarded(self, formula):
        """An opaque C result rides under a guard unchanged.

        Like ``CallSiteValue``: the site-keyed result term is the value. It is
        not a return or an inv that becomes an implication, and it states no
        fact; the enclosing ExitSet (whose Completed face already sits under
        ``python:c_extension.call_completes``) owns the control guard. A bare
        C call as an expression statement inside ``try`` reaches this.
        """
        del formula
        return self

    def _opaque_faces(self, step, site, value, owner):
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.ir import atomic, ctor, str_const
        from sugar_lift_py_tests.occurrence import occurrence_key
        from sugar_lift_py_tests.outcome.exit_set import (
            Completed,
            ExitSet,
            Halted,
            complement_guard,
        )

        key = occurrence_key(site)
        completes = atomic(
            f"python:c_extension.result_{step}_completes",
            [
                ctor(
                    f"python:c_extension.result_{step}",
                    (self.to_term(owner=owner), str_const(key)),
                )
            ],
        )
        return ExitSet(
            (
                Completed(completes, value(key)),
                Halted(
                    complement_guard(completes),
                    UndeterminedRaiseEffect(
                        blame=str(site) if site is not None else None,
                        occurrence=key if site is not None else None,
                        producer_node_owner=owner,
                    ),
                    None,
                ),
            )
        ).normalize()

    def attribute(self, name, site):
        """``r.x`` on an opaque C result: two faces, never a guess (#7585).

        Nothing testified to the native type's members or descriptors, so the
        read may raise anything.  It completes only under
        ``python:c_extension.result_attribute_completes`` keyed on this read's
        occurrence, with the opaque ``python:attribute_result`` value.
        """
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor, str_const

        owner = f"CResultAttribute:{self.module_name}.{self.exported_name}.{name}"
        return self._opaque_faces(
            "attribute",
            site,
            lambda key: SymbolicValue(
                ctor(
                    "python:attribute_result",
                    (self.to_term(owner=owner), str_const(name), str_const(key)),
                )
            ),
            owner,
        )

    def callable_application_with(self, operation, ctx):
        """``r(...)`` on an opaque C result: native ``__call__``, two faces."""
        del ctx
        site = getattr(operation, "blame", None) or getattr(operation, "site", None)
        owner = f"CResultCall:{self.module_name}.{self.exported_name}"
        return self._opaque_faces(
            "call",
            site,
            lambda key: LanguageOwnedCExtensionResultValue(
                module_name=self.module_name,
                exported_name=f"{self.exported_name}()",
                site=site,
                occurrence=key,
            ),
            owner,
        )

    def subscript_with(self, operation, ctx):
        """``c_call()[k]`` may raise: the #7587 opaque-subscript law.

        Nothing testified to the result's runtime type or ``__getitem__``. A
        symbolic ``py.subscript`` over this result's term completes only under
        ``python:subscript.completes(python:subscript(<term>, <site>))``, keyed
        on the exact subscript site; the complement halts with an
        ``UndeterminedRaiseEffect``. No exception class or member is invented.
        """
        from sugar_lift_py_tests.floor.call_site_value import _opaque_subscript_faces
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        outcome = operation.submit(
            SymbolicValue(self.to_term(owner=f"{operation.owner} C result subscript")),
            ctx,
        )
        return _opaque_subscript_faces(
            outcome,
            getattr(operation, "blame", None),
            producer="LanguageOwnedCExtensionResultValue.subscript",
        )


def _undecided_reset_faces(variable_name: str, site):
    """``var.reset(token)`` with a token the lift did not see ``var.set`` mint.

    CPython raises ``TypeError`` for a non-Token, ``ValueError`` for a token
    another ContextVar or Context created, and ``RuntimeError`` for one
    already used; nothing here decides which token this is (an opaque call
    result, say), so the reset completes with ``None`` only under
    ``python:contextvar_reset.completes(python:contextvar_reset(<name>,
    <occurrence>))`` and halts with an ``UndeterminedRaiseEffect`` (owner
    ``ContextVarReset:<name>``) under the complement -- the #7585 law.
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.ir import atomic, ctor, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome.exit_set import (
        Completed,
        ExitSet,
        Halted,
        complement_guard,
    )

    key = occurrence_key(site)
    completes = atomic(
        "python:contextvar_reset.completes",
        [
            ctor(
                "python:contextvar_reset",
                (str_const(variable_name), str_const(key)),
            )
        ],
    )
    return ExitSet(
        (
            Completed(completes, NoneValue()),
            Halted(
                complement_guard(completes),
                UndeterminedRaiseEffect(
                    blame=str(site),
                    occurrence=key,
                    producer_node_owner=f"ContextVarReset:{variable_name}",
                ),
                None,
            ),
        )
    ).normalize()
