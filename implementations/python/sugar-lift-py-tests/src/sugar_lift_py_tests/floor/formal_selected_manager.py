"""A ``with`` whose manager is reached from a parameter (or ``self``).

``with monkeypatch.context() as m:`` and ``with self.buffer:`` select their
manager from a formal: the type of the object the caller passes decides which
``__enter__``/``__exit__`` run.  Inside the frame nothing about that object is
known, so the With refused (``runtime-selected``).  It is not refused here and
it never completes totally: the manager is opaque and keyed on its site.

* Evaluating the head (attribute reads and calls on the formal) completes with
  an opaque manager under ``python:formal_manager.constructs`` or halts with an
  ``UndeterminedRaiseEffect``.
* ``type(mgr).__enter__`` and ``type(mgr).__exit__`` are each two-faced
  (``python:formal_manager.slot_completes``) with opaque results.
* Suppression is ``py.truthy`` of the opaque exit result: never assumed False,
  never assumed True.

Every partition atom is keyed on the With's own site.  The head is recognized only when evaluating it has no effect other
than these faces (a chain of attribute reads and calls with constant
arguments, rooted at a parameter the function never rebinds), so not
evaluating its parts separately loses nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class FormalSelectedManagerValue(FloorValue):
    """The opaque manager a formal-rooted ``with`` head evaluates to."""

    head: str
    site: str

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor(
            "python:formal_manager", (str_const(self.head), str_const(self.site))
        )


@dataclass(frozen=True)
class FormalSelectedSlotResultValue(FloorValue):
    """The opaque result of ``__enter__`` or ``__exit__`` on that manager."""

    head: str
    slot: str
    site: str

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor(
            "python:formal_manager.slot_result",
            (str_const(self.head), str_const(self.slot), str_const(self.site)),
        )

    def truth(self, site):
        """Truth is the undecided ``py.truthy`` of this exact opaque result."""
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_truthy
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            PredicateValue(py_truthy(self.to_term(owner="truth")), site)
        )


def _sugar_base():
    from sugar_lift_py_tests.sugar.sugar_base import Sugar

    return Sugar


@dataclass(frozen=True)
class FormalSelectedManagerHeadSugar(_sugar_base()):
    """The With head, standing for the opaque manager; its faces are the protocol's."""

    head: str
    site: str
    # The manager-producing call's own operands, in source order.  Python
    # selects the callee (attribute reads on the formal), then evaluates these,
    # then calls; so a head with operands is a two-faced ``select`` step,
    # these operands' own outcomes, and only then the opaque value whose
    # construction the protocol's ``construct`` step owns.
    operands: tuple = ()

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.outcome import ExitSet

        value = FormalSelectedManagerValue(self.head, self.site)
        if not self.operands:
            return ExitSet.completed(value)
        protocol = FormalSelectedManagerProtocol(self.head, self.site)
        outcome = ExitSet.two_faced(
            None,
            protocol.step_raise("select"),
            guard=protocol.step_completes("select"),
        )
        for operand in self.operands:
            outcome = outcome.and_then(
                lambda _previous, operand=operand: operand.desugar(ctx)
            )
        return outcome.and_then(lambda _last: ExitSet.completed(value))


@dataclass(frozen=True)
class FormalSelectedManagerProtocol:
    """Construction, enter and exit are two-faced; exit truth decides suppression."""

    head: str
    site: str

    def head_sugar(self):
        return FormalSelectedManagerHeadSugar(self.head, self.site)

    def step_completes(self, step: str):
        """The site-keyed atom under which ``step`` completes."""
        from sugar_lift_py_tests.ir import atomic, ctor, str_const

        name = (
            "python:formal_manager.constructs"
            if step == "construct"
            else "python:formal_manager.selects"
            if step == "select"
            else "python:formal_manager.slot_completes"
        )
        call = ctor(
            "python:formal_manager.step",
            (str_const(self.head), str_const(step), str_const(self.site)),
        )
        return atomic(name, [call])

    def step_raise(self, step: str):
        """What ``step`` raises under the complement: nothing named."""
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

        return UndeterminedRaiseEffect(
            blame=self.site,
            occurrence=f"{self.site}#{step}",
            producer_node_owner=f"FormalSelectedManager:{self.head}.{step}",
        )

    def construct_manager(self, receiver, ctx=None):
        del ctx
        from sugar_lift_py_tests.outcome import ExitSet

        self._receiver(receiver)
        return ExitSet.two_faced(
            receiver,
            self.step_raise("construct"),
            guard=self.step_completes("construct"),
        )

    def enter_resource_outcome_for(self, receiver, ctx=None):
        del ctx
        from sugar_lift_py_tests.floor.entered_manager_state_value import (
            EnteredManagerStateValue,
        )
        from sugar_lift_py_tests.outcome import ExitSet

        manager = self._receiver(receiver)
        return ExitSet.two_faced(
            EnteredManagerStateValue(
                enter_value=FormalSelectedSlotResultValue(
                    self.head, "__enter__", self.site
                ),
                receiver_state=manager,
            ),
            self.step_raise("__enter__"),
            guard=self.step_completes("__enter__"),
        )

    def exit_outcome_for(self, entered, ctx=None):
        del ctx
        from sugar_lift_py_tests.outcome import ExitSet

        self._receiver(entered.receiver_state)
        return ExitSet.two_faced(
            FormalSelectedSlotResultValue(self.head, "__exit__", self.site),
            self.step_raise("__exit__"),
            guard=self.step_completes("__exit__"),
        )

    def _receiver(self, receiver):
        from sugar_source_tree.panic import SugarNotWritten

        if (
            isinstance(receiver, FormalSelectedManagerValue)
            and receiver.head == self.head
            and receiver.site == self.site
        ):
            return receiver
        raise SugarNotWritten(
            blame=self.site,
            owner="FormalSelectedManagerProtocol",
            observed=f"{type(receiver).__name__} is not this With's formal manager",
            requested=f"FormalSelectedManagerValue({self.head!r}, {self.site!r})",
            fix="never run a formal-selected protocol over another manager",
        )
