"""A context manager constructed by a language-owned C-extension call.

``with _decimal.localcontext() as ctx:`` has no source on any side: the
constructor is a builtin function of an interpreter C module, so its result is
the opaque ``LanguageOwnedCExtensionResultValue`` of a two-faced C call. Python's
``with`` law still holds over that object, and it is the only thing asserted:

* ``type(mgr).__enter__`` is looked up and called. That completes with an
  opaque result, or halts with an ``UndeterminedRaiseEffect`` (a missing slot is
  a ``TypeError``, a native raise is anything).
* ``type(mgr).__exit__`` runs over every body edge. It completes with an opaque
  result, or halts with an ``UndeterminedRaiseEffect`` that supersedes the body.
* Suppression is decided only by ``py.truthy`` of that opaque exit result. It is
  never assumed ``False`` and never assumed ``True``.

Nothing reads the C implementation's behaviour from a pure-Python twin such as
``_pydecimal``: that is a different implementation, not this one's testimony.
Every partition atom carries the With's own manager site, so two ``with``
statements never share an enter or exit outcome.

Recognition keys on runtime identity: the constructor must be a
``builtin_function_or_method`` whose ``__self__`` is the very module object the
export resolved to, and that module must be interpreter-owned (built in, or an
extension file under the stdlib ``lib-dynload``). The result's type is not
checked, because finding it would mean executing the constructor at lift time;
the protocol therefore claims nothing about that type beyond the ``with`` law
above. Like every language-owned C call, the enter and exit calls are not
modelled as writing lifted Python state.
"""

from __future__ import annotations

from dataclasses import dataclass

from .closed_operation_witness import PythonRuntimeIdentity
from .floor_value import FloorValue


@dataclass(frozen=True)
class LanguageOwnedCSlotResultValue(FloorValue):
    """The opaque result of ``__enter__`` or ``__exit__`` on a C-call manager."""

    module_name: str
    exported_name: str
    slot: str
    site: str

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor(
            "python:c_extension.slot_result",
            (
                str_const(self.module_name),
                str_const(self.exported_name),
                str_const(self.slot),
                str_const(self.site),
            ),
        )

    def truth(self, site):
        """Truth is the undecided ``py.truthy`` of this exact opaque result."""
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_truthy
        from sugar_lift_py_tests.outcome import Complete

        return Complete(PredicateValue(py_truthy(self.to_term(owner="truth")), site))


@dataclass(frozen=True)
class LanguageOwnedCManagerProtocol:
    """Enter and exit are two-faced C slot calls; exit truth decides suppression."""

    module_name: str
    exported_name: str
    runtime: PythonRuntimeIdentity

    def _receiver(self, receiver):
        from sugar_lift_py_tests.floor.language_owned_contextvar import (
            LanguageOwnedCExtensionResultValue,
        )
        from sugar_source_tree.panic import SugarNotWritten

        if (
            isinstance(receiver, LanguageOwnedCExtensionResultValue)
            and receiver.module_name == self.module_name
            and receiver.exported_name == self.exported_name
        ):
            return receiver
        raise SugarNotWritten(
            blame=getattr(receiver, "site", None),
            owner="LanguageOwnedCManagerProtocol",
            observed=(
                f"{type(receiver).__name__} is not the result of the C call "
                f"{self.module_name}.{self.exported_name}"
            ),
            requested=(
                "LanguageOwnedCExtensionResultValue("
                f"{self.module_name}.{self.exported_name})"
            ),
            fix="never run a C-owned protocol over a receiver its constructor did not produce",
        )

    def construct_manager(self, receiver, ctx=None):
        """The With head's own call is the two-faced C call that builds it.

        The resolution that seated this protocol is keyed on the head's call
        coordinate, so a ``CallSiteValue`` there is that call, not a stand-in:
        it completes with the opaque C result or halts with its
        ``UndeterminedRaiseEffect`` before ``__enter__`` is ever looked up.
        """
        from types import SimpleNamespace

        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.language_owned_contextvar import (
            LanguageOwnedCExtensionCallableValue,
        )
        from sugar_lift_py_tests.outcome.exit_set import ExitSet

        if isinstance(receiver, CallSiteValue):
            return LanguageOwnedCExtensionCallableValue(
                module_name=self.module_name, exported_name=self.exported_name
            ).callable_application_with(
                SimpleNamespace(
                    blame=receiver.site,
                    arguments=tuple(receiver.arg_values),
                    keyword_names=(),
                ),
                ctx,
            )
        return ExitSet.completed(self._receiver(receiver))

    def _slot_call(self, receiver, slot: str, completed_value):
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.ir import atomic, ctor, str_const
        from sugar_lift_py_tests.outcome.exit_set import (
            Completed,
            ExitSet,
            Halted,
            complement_guard,
        )

        site = str(receiver.site)
        call = ctor(
            "python:c_extension.slot_call",
            (
                str_const(self.module_name),
                str_const(self.exported_name),
                str_const(slot),
                str_const(site),
            ),
        )
        completes = atomic("python:c_extension.slot_call_completes", [call])
        return ExitSet(
            (
                Completed(completes, completed_value),
                Halted(
                    complement_guard(completes),
                    UndeterminedRaiseEffect(
                        blame=site,
                        occurrence=f"{site}#{slot}",
                        producer_node_owner=(
                            "LanguageOwnedCManagerProtocol"
                            f":{self.module_name}.{self.exported_name}.{slot}"
                        ),
                    ),
                    None,
                ),
            )
        ).normalize()

    def _slot_result(self, receiver, slot: str):
        return LanguageOwnedCSlotResultValue(
            module_name=self.module_name,
            exported_name=self.exported_name,
            slot=slot,
            site=str(receiver.site),
        )

    def enter_resource_outcome_for(self, receiver, ctx=None):
        del ctx
        from sugar_lift_py_tests.floor.entered_manager_state_value import (
            EnteredManagerStateValue,
        )

        manager = self._receiver(receiver)
        return self._slot_call(
            manager,
            "__enter__",
            EnteredManagerStateValue(
                enter_value=self._slot_result(manager, "__enter__"),
                receiver_state=manager,
            ),
        )

    def exit_outcome_for(self, entered, ctx=None):
        del ctx
        manager = self._receiver(entered.receiver_state)
        return self._slot_call(
            manager, "__exit__", self._slot_result(manager, "__exit__")
        )
