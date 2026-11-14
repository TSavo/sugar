"""Mechanical context-manager consumption of GeneratorConstructionV1."""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.generator_construction import (
    GeneratorConstructionV1,
    GeneratorTerminationV1,
    GeneratorTransitionGapV1,
    YieldEffect,
)
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class GeneratorWithSugar(Sugar):
    manager: Sugar
    body: tuple[Sugar, ...]
    enter_slot_id: str | None
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ExitSet",
            reason="generator manager mechanics route already-constructed body faces",
        )

    def desugar(self, ctx=None) -> ExitSet:
        from sugar_lift_py_tests.outcome.resource_bindings import (
            EnterResultBinding,
            prepend_facts_to_exitset,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _ReducedBlock,
            reduce_block_to_exitset,
        )

        manager_es = self.manager.desugar(ctx)
        if not manager_es.exits:
            # No manager face is reachable: the statement completes with an
            # empty record and its tail is unreachable.
            return ExitSet.completed(_ReducedBlock((), False, ()))

        def enter(machine):
            if not isinstance(machine, GeneratorConstructionV1):
                self._loud(
                    "manager did not construct GeneratorConstructionV1",
                    "opaque generator transition",
                )
            return self._consume_enter_outcome(machine.resume(), machine, ctx)

        # Everything the enter and the body produce runs beneath its manager
        # face (``ExitSet.sequence``): its guard and faces, and what the
        # manager expression owes. The with's own faces: a halt stays a halted
        # arm (#7826).
        return manager_es.sequence(enter)

    def _consume_enter_outcome(self, entered, machine, ctx):
        """Route first-resume of a generator manager, including open enter faces.

        A halted step is the enter's own halt; a completed step continues the
        enter beneath itself (``ExitSet.sequence``).
        """
        from sugar_lift_py_tests.outcome.resource_bindings import (
            EnterResultBinding,
            prepend_facts_to_exitset,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        if isinstance(entered, ExitSet):
            return entered.sequence(
                lambda value: self._consume_enter_outcome(value, machine, ctx)
            )
        if isinstance(entered, GeneratorConstructionV1):
            # A step completed and left the machine runnable: run on to the
            # first suspension.
            return self._consume_enter_outcome(entered.resume(), machine, ctx)
        if isinstance(entered, GeneratorTerminationV1):
            return self._entry_refusal_exit(machine, entered)
        if isinstance(entered, GeneratorTransitionGapV1):
            self._loud(entered.observed, "opaque generator transition")
        if not isinstance(entered, YieldEffect):
            self._loud(type(entered).__name__, "opaque generator transition")

        from sugar_lift_py_tests.context_manager_contract import (
            NeverSuppressesDispositionV1,
        )
        from sugar_lift_py_tests.generator_manager_exit import (
            generator_manager_exit,
            is_exception_effect,
        )
        # The generator-backed manager's __exit__ per body exit: an
        # exception is thrown in at the yield, anything else resumes it.
        body_es = reduce_block_to_exitset(self.body, ctx)
        exits = []
        for body_exit in body_es.exits:
            exit_es = generator_manager_exit(
                entered.machine, body_exit, blame=str(self.site)
            )
            if isinstance(body_exit, Halted) and not is_exception_effect(
                body_exit.effect
            ):
                # Return/break/continue are not exceptions: __exit__(None, ...)
                # runs and its result is ignored; the body's own exit stands.
                routed = ExitSet((body_exit,)).and_exit(
                    exit_es, disposition=NeverSuppressesDispositionV1()
                )
            else:
                routed = ExitSet((body_exit,)).and_exit_truthiness(
                    exit_es, site=self.site
                )
            exits.extend(routed.exits)
        result = ExitSet(tuple(exits)).normalize()
        facts = ()
        if self.enter_slot_id is not None:
            facts = EnterResultBinding(self.enter_slot_id, entered.value).to_facts(
                site=self.site
            )
        return prepend_facts_to_exitset(result, facts)

    @staticmethod
    def _entry_refusal_exit(machine, termination: GeneratorTerminationV1):
        """Turn first-resume termination into the authenticated raise ExitSet arm.

        Observation lives in ``generator_entry_refusal`` (vendor conversion).
        This consumer only asks for it — no vendor module name here
        (``generator_construction_law``). The manager face's guard, faces and
        ``owed`` are the composition's (``ExitSet.sequence`` in ``desugar``).
        """
        from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
        from sugar_lift_py_tests.generator_entry_refusal import observed_entry_refusal

        refusal = observed_entry_refusal()
        blame = str(machine.instance_coordinate)
        effect = RaiseEffect.for_builtin(
            refusal.exception_name,
            occurrence=f"generator-entry-refusal:{blame}",
            blame=blame,
            raised_value=refusal.message,
        )
        return ExitSet.halted(effect, state=termination)

    def _loud(self, observed: str, label: str):
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            blame=self.site,
            owner="GeneratorWithSugar.desugar",
            observed=f"{label}: {observed}",
            requested="an exhaustive GeneratorConstructionV1 transition",
            fix="construct the transition or retain this typed loud boundary",
        )


@dataclass(frozen=True)
class GeneratorObjectWithSugar(Sugar):
    """``with g():`` where ``g`` is an undecorated generator function.

    The call returns a generator object and runs none of its body; a
    generator object is not a context manager, so the ``with`` statement
    itself raises -- after the manager expression, before any enter and
    before the body. Each completed manager face therefore halts with the
    interpreter's own observed refusal (``generator_object_with_refusal``),
    carrying the constructed generator as its state; each halted manager face
    (the call's own binding errors) stands. The body is never reached, so it
    is never constructed. Nothing here is a manager: no enter, no exit, no
    suppression.
    """

    manager: Sugar
    site: object = field(compare=False)
    # ``"generator"`` for a ``def`` generator function, ``"async_generator"``
    # for an ``async def`` one: each object's refusal is observed separately.
    object_kind: str = "generator"

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ExitSet",
            reason="a generator object at a with head halts before any body face",
        )

    def desugar(self, ctx=None) -> ExitSet:
        from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
        from sugar_lift_py_tests.generator_object_with_refusal import (
            observed_generator_object_with_refusal,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

        refusal = observed_generator_object_with_refusal(self.object_kind)
        blame = str(self.site)
        manager_es = self.manager.desugar(ctx)
        exits = []
        for manager_exit in manager_es.exits:
            if isinstance(manager_exit, Halted):
                exits.append(manager_exit)
                continue
            if not isinstance(manager_exit.value, GeneratorConstructionV1):
                from sugar_source_tree.panic import SugarNotWritten

                raise SugarNotWritten(
                    blame=self.site,
                    owner="GeneratorObjectWithSugar.desugar",
                    observed=(
                        "generator-function call completed with "
                        f"{type(manager_exit.value).__name__}"
                    ),
                    requested="GeneratorConstructionV1 (the generator object)",
                    fix="construct the generator object or keep the with loud",
                )
            effect = RaiseEffect.for_builtin(
                refusal.exception_name,
                occurrence=f"generator-object-with-refusal:{blame}",
                blame=blame,
                raised_value=refusal.message,
                producer_node_owner="GeneratorObjectWithSugar",
            )
            # The with halts at its head: nothing was reached inside the
            # statement, so its state is the empty record the block reducer
            # splices its prefix onto.
            exits.append(
                Halted(
                    manager_exit.guard,
                    effect,
                    _ReducedBlock((), True, ()),
                    manager_exit.faces,
                    manager_exit.owed,
                )
            )
        return ExitSet(tuple(exits)).normalize()


@dataclass(frozen=True)
class NonManagerObjectWithSugar(Sugar):
    """``with C(...):`` where ``C``'s MRO is proven to lack the protocol.

    The head is evaluated (construction runs, and may raise); then, because
    ``type(head)`` has no ``__enter__`` (or has ``__enter__`` but no
    ``__exit__``), the ``with`` statement itself raises the interpreter's own
    observed ``TypeError`` -- before any enter and before the body.  Each
    completed head face halts with that refusal, carrying the constructed
    value as its state; each halted head face stands.  Nothing is a manager.
    """

    manager: Sugar
    site: object = field(compare=False)
    type_name: str = ""
    has_enter: bool = False
    has_exit: bool = False

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ExitSet",
            reason="a non-manager object at a with head halts before any body face",
        )

    def desugar(self, ctx=None) -> ExitSet:
        from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
        from sugar_lift_py_tests.manager_protocol_absence_refusal import (
            observed_non_manager_with_refusal,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

        refusal = observed_non_manager_with_refusal(
            self.type_name, has_enter=self.has_enter, has_exit=self.has_exit
        )
        blame = str(self.site)
        manager_es = self.manager.desugar(ctx)
        exits = []
        for manager_exit in manager_es.exits:
            if isinstance(manager_exit, Halted):
                exits.append(manager_exit)
                continue
            effect = RaiseEffect.for_builtin(
                refusal.exception_name,
                occurrence=f"non-manager-with-refusal:{blame}",
                blame=blame,
                raised_value=refusal.message,
                producer_node_owner="NonManagerObjectWithSugar",
            )
            # Halted at the head: the empty record the reducer splices onto.
            exits.append(
                Halted(
                    manager_exit.guard,
                    effect,
                    _ReducedBlock((), True, ()),
                    manager_exit.faces,
                    manager_exit.owed,
                )
            )
        return ExitSet(tuple(exits)).normalize()
