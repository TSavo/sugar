"""A class an interpreter-owned C module exports (``_io.TextIOWrapper``).

The class has no authenticated source. It is not a C function (the C-function
rule keys on ``builtin_function_or_method``); this is the separate type rule:

- Calling it constructs an instance under one opaque partition atom,
  ``python:c_type.constructs(python:c_type.construct(module, name, site))``.
  Completed carries an instance keyed on that site; the complement halts with
  an ``UndeterminedRaiseEffect``, because native ``__new__``/``__init__`` may
  raise anything.
- ``isinstance(x, T)`` is decided True only when ``x`` is an instance this lift
  saw constructed from exactly ``T`` at a known site: CPython's
  ``PyObject_IsInstance`` answers ``Py_IS_TYPE(inst, cls)`` first, without a
  lookup that could raise.  Missing knowledge never decides False.  Otherwise
  the test stays undecided and two-faced, because the fallback reads
  ``x.__class__``, which arbitrary objects may make raise.
"""

from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue
from .language_owned_contextvar import LanguageOwnedCExtensionResultValue


def _site_of(operation):
    return getattr(operation, "blame", None) or getattr(operation, "site", None)


@dataclass(frozen=True)
class LanguageOwnedCInstanceValue(LanguageOwnedCExtensionResultValue):
    """An instance of a C class, constructed at one known site."""

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor(
            "python:c_type.instance",
            (
                str_const(self.module_name),
                str_const(self.exported_name),
                str_const(self.occurrence or str(self.site)),
            ),
        )


@dataclass(frozen=True)
class LanguageOwnedCTypeValue(FloorValue):
    """The C class object ``module.name`` itself."""

    module_name: str
    type_name: str
    site: object = None

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor(
            "python:c_type", (str_const(self.module_name), str_const(self.type_name))
        )

    def _two_faced(self, completes, value, owner_suffix, site, key):
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.outcome.exit_set import (
            Completed,
            ExitSet,
            Halted,
            complement_guard,
        )

        return ExitSet(
            (
                Completed(completes, value),
                Halted(
                    complement_guard(completes),
                    UndeterminedRaiseEffect(
                        blame=str(site) if site is not None else None,
                        occurrence=key if site is not None else None,
                        producer_node_owner=(
                            f"{owner_suffix}:{self.module_name}.{self.type_name}"
                        ),
                    ),
                    None,
                ),
            )
        ).normalize()

    def callable_application_with(self, operation, ctx):
        del ctx
        from sugar_lift_py_tests.ir import atomic, ctor, str_const
        from sugar_lift_py_tests.occurrence import occurrence_key

        site = _site_of(operation)
        key = occurrence_key(site)
        construct = ctor(
            "python:c_type.construct",
            (str_const(self.module_name), str_const(self.type_name), str_const(key)),
        )
        return self._two_faced(
            atomic("python:c_type.constructs", [construct]),
            LanguageOwnedCInstanceValue(
                module_name=self.module_name,
                exported_name=self.type_name,
                site=site,
                occurrence=key,
            ),
            "LanguageOwnedCType",
            site,
            key,
        )

    def subscript_with(self, operation, ctx):
        """``T[k]`` on a cited C class: the #7587 opaque-subscript law.

        The class has no authenticated source, so its ``__class_getitem__`` /
        metaclass ``__getitem__`` is cited, never looked inside.  A symbolic
        ``py.subscript`` over the class's term completes only under
        ``python:subscript.completes(python:subscript(<term>, <site>))``, keyed
        on the exact subscript site; the complement halts with an
        ``UndeterminedRaiseEffect``.  No alias type, member or exception class
        is invented.
        """
        from sugar_lift_py_tests.floor.call_site_value import _opaque_subscript_faces
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        outcome = operation.submit(
            SymbolicValue(self.to_term(owner=f"{operation.owner} C type subscript")),
            ctx,
        )
        return _opaque_subscript_faces(
            outcome,
            getattr(operation, "blame", None),
            producer=f"LanguageOwnedCType.subscript:{self.module_name}.{self.type_name}",
        )

    def test_python_type(self, value, site):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import atomic, ctor, str_const
        from sugar_lift_py_tests.occurrence import occurrence_key
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if (
            type(value) is LanguageOwnedCInstanceValue
            and value.module_name == self.module_name
            and value.exported_name == self.type_name
            and value.site is not None
        ):
            return Complete(TrueBoolLiteralSugar(site=site))
        key = occurrence_key(site)
        value_term = value.to_term(owner="LanguageOwnedCTypeValue.isinstance")
        type_term = self.to_term(owner="LanguageOwnedCTypeValue.isinstance")
        test = ctor("python:c_type.isinstance", (value_term, type_term, str_const(key)))
        return self._two_faced(
            atomic("python:c_type.isinstance_completes", [test]),
            PredicateValue(atomic("python:c_type.is_instance", [test]), site=site),
            "UndecidedIsinstance",
            site,
            key,
        )
