"""Authenticated ``ExceptionGroup`` tree construction for ``except*`` routing.

Produces an immutable ``GroupedRaiseEffect`` whose leaves are the effects their
own raises would halt with: a ``RaiseEffect`` (type coordinate, MRO,
occurrence) read off the value each member's construction made, or an
``UndeterminedRaiseEffect`` where that construction carries no class. Nested
groups stay nested: children are never flattened. Spelling does not grant
group authority — only the Raise construction path that recognized the builtin
group coordinate may mint this sugar.

Group occurrence identity is the sealed ``SourceMemento`` from the typed
``SourceFragment`` construction door — never a fabricated ``filename:line:col``.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import ClassVar

from sugar_lift_py_tests.effect import GroupedRaiseEffect
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_source_tree.fragment import SourceFragment


@dataclass(frozen=True)
class GroupedRaiseSugar(Sugar):
    """Construct one authenticated exception-group tree without flattening it.

    Construction door: ``site`` is a typed ``SourceFragment``. The producer
    (Raise → GroupedRaiseSugar) must pass an enumerated fragment; there is no
    runtime kind-admission membrane over seal/memento.
    """

    group_identity: str
    message: Sugar
    children: tuple[Sugar, ...]
    site: SourceFragment = dataclass_field(compare=False)
    # The class the callee's binding names (builtins ``ExceptionGroup`` or
    # ``BaseExceptionGroup``): what the constructor is asked to build, not
    # the class it builds (``_group``).
    exception_type_coordinate: object | None = None
    # A raise statement binds nothing before any of its halts (a member's
    # construction, the group's raise): its pre-halt record is the block's
    # prefix, as ``RaiseSugar``'s.
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        return ()

    def constructed(self, ctx: object = None) -> ExitSet:
        """The group this raise builds, without raising it: what an enclosing
        group holds as its member, and what ``desugar`` raises.

        The message, then each member in order, is constructed.  A member's
        construction that halts (``OSError(e, 'x')`` may raise before any
        group exists) halts the whole raise; it is never a member.  Each
        completed arm of a member's construction is the member's effect
        (``RaiseSugar.constructed``), whose class was read off the value the
        member's construction made -- undetermined where that construction
        is unanswered, never the callee's.  ``sequence`` carries every arm's
        guard, faces and ``owed`` onto the group built beneath it, so what a
        member's construction owes, the group owes.  The group's own class
        is then its construction's (``_group``), decided by its members as
        CPython decides it, never the callee's by its name."""

        def build(message_value):
            members = ExitSet.completed(())
            for child in self.children:
                members = members.sequence(
                    lambda effects, child=child: child.constructed(ctx).and_then(
                        lambda member, effects=effects: ExitSet.completed(
                            (*effects, member)
                        )
                    )
                )
            # Typed door: site is SourceFragment; seal() returns SourceMemento.
            memento = self.site.seal()
            # Full sealed coordinate — segment cid alone collides across files
            # that share identical span text; file + source_cid pin the
            # authenticated source.
            occurrence = (
                f"{memento.file}:{memento.start}:{memento.end}"
                f":{memento.source_cid}:{memento.cid}"
            )
            return members.sequence(
                lambda effects: self._group(message_value, tuple(effects), occurrence)
            )

        return self.message.desugar(ctx).and_then(build)

    def _group(self, message_value, members, occurrence) -> ExitSet:
        """What the group constructor does once its arguments were
        constructed: CPython's ``BaseExceptionGroup.__new__``
        (Objects/exceptions.c) parses them first (``PyArg_ParseTuple(args,
        "UO")``), so the message's type is read before any member rule
        (``_message``), then the members decide the group
        (``_from_members``)."""
        return self._message(message_value).and_then(
            lambda message: self._from_members(message, members, occurrence)
        )

    def _message(self, message_value) -> ExitSet:
        """The message operand as ``BaseExceptionGroup.__new__`` parses it:
        format ``U`` admits a ``str`` (or a subclass) and raises
        ``TypeError`` for anything else.

        Whether the message is a ``str`` is asked of the one ``isinstance``
        reader (the builtin ``str`` class's ``test_python_type``), never of
        the value's species here.  A decided ``str`` completes with the
        message; a decided non-``str`` is the ``TypeError`` halt.  A message
        whose type that reader retains (``adt.is_python_type(<message>,
        str)``) is the one two-faced outcome (``ExitSet.two_faced``): it
        completes with the message under that type test and raises the
        ``TypeError`` under its complement, both arms owing the read as the
        ``undecided`` member.  Never a guess either way."""
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )
        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            builtin_name_temporal,
        )
        from sugar_source_tree.panic import SugarNotWritten

        owner = "GroupedRaiseSugar.constructed"

        def refused():
            return ground_exceptional_exit(
                exception_name="TypeError", site=self.site, owner=owner
            )

        def decide(verdict):
            if isinstance(verdict, TrueBoolLiteralSugar):
                return ExitSet.completed(message_value)
            if isinstance(verdict, FalseBoolLiteralSugar):
                return refused()
            if isinstance(verdict, PredicateValue):
                (type_error,) = refused().halts()
                return ExitSet.two_faced(
                    message_value,
                    type_error.effect,
                    guard=verdict.formula,
                    site=self.site,
                )
            raise SugarNotWritten(
                blame=self.site,
                owner=owner,
                observed=f"message type test answered {type(verdict).__name__}",
                requested="a decided bool or a retained type-test predicate",
                fix="answer isinstance(message, str) through the one reader",
            )

        str_class = builtin_name_temporal().value_if_bound("str")
        return str_class.test_python_type(message_value, self.site).and_then(decide)

    def _from_members(self, message_value, members, occurrence) -> ExitSet:
        """What the group constructor does with its members, once each was
        constructed and the message parsed: CPython's
        ``BaseExceptionGroup.__new__`` (Objects/exceptions.c), stated by its
        exact rule, since a member is a constructed exception (a raise
        effect), never a ground value the cited fold could hand the pinned
        interpreter.

        - no member: ``ValueError`` (the exceptions must be a non-empty
          sequence);
        - a member that is not an exception instance (``[ValueError]``, a
          class named without calling it): ``ValueError`` ("Item i of second
          argument (exceptions) is not an exception");
        - every member an instance: the class is decided by whether every
          member is an ``Exception``, asked of the one matcher
          (``matches_raise_effect``) over the class each member's
          construction decided.  ``ExceptionGroup`` with a member that is
          not an ``Exception`` is the ``TypeError`` ("Cannot nest
          BaseExceptions in an ExceptionGroup"); ``BaseExceptionGroup``
          whose members are all ``Exception`` constructs an
          ``ExceptionGroup``; otherwise the callee's own class.

        A member whose instance or ``Exception`` question nothing here
        decides (its construction unanswered, its class an import path
        whose ancestry is its own proof's) leaves the group's class
        undecided: the construction is the one two-faced unanswered outcome
        (``ExitSet.two_faced``), completing with a group of no class or
        raising something undetermined, and owing this construction as the
        ``undecided`` member.  Never the callee's class by its name."""
        from sugar_lift_py_tests.floor.ground_exit import (
            _builtin_exception_identity,
            ground_exceptional_exit,
        )

        owner = "GroupedRaiseSugar.constructed"
        if not members:
            return ground_exceptional_exit(
                exception_name="ValueError", site=self.site, owner=owner
            )
        instances = tuple(_is_exception_instance(member) for member in members)
        if any(instance is False for instance in instances):
            return ground_exceptional_exit(
                exception_name="ValueError", site=self.site, owner=owner
            )
        callee = _builtin_group_name(self.exception_type_coordinate)
        if callee is None or any(instance is None for instance in instances):
            return self._undecided_group(message_value, members, occurrence, callee)
        exceptions = tuple(_is_exception(member) for member in members)
        if any(exception is None for exception in exceptions):
            return self._undecided_group(message_value, members, occurrence, callee)
        nested_base_exceptions = not all(exceptions)
        if callee == "ExceptionGroup" and nested_base_exceptions:
            return ground_exceptional_exit(
                exception_name="TypeError", site=self.site, owner=owner
            )
        constructed = (
            "BaseExceptionGroup" if nested_base_exceptions else "ExceptionGroup"
        )
        identity, mro = _builtin_exception_identity(constructed)
        return ExitSet.completed(
            GroupedRaiseEffect(
                self.group_identity,
                message_value,
                members,
                occurrence=occurrence,
                exception_type_coordinate=identity,
                exception_type_mro=mro,
            )
        )

    def _undecided_group(self, message_value, members, occurrence, callee):
        """The group construction nothing here decides: two faces, never a
        guess.  It completes with the group, whose class is undecided, only
        under ``python:exception_group.completes(python:exception_group(
        <callee>, <occurrence>))``, and halts with an
        ``UndeterminedRaiseEffect`` (the ``TypeError`` or ``ValueError`` the
        constructor may raise) under the complement; both arms owe the
        construction (``ExitSet.two_faced``)."""
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.ir import atomic, ctor, str_const
        from sugar_lift_py_tests.occurrence import occurrence_key

        key = occurrence_key(self.site)
        label = callee or "exception_group"
        completes = atomic(
            "python:exception_group.completes",
            [ctor("python:exception_group", (str_const(label), str_const(key)))],
        )
        return ExitSet.two_faced(
            GroupedRaiseEffect(
                self.group_identity,
                message_value,
                members,
                occurrence=occurrence,
            ),
            UndeterminedRaiseEffect(
                blame=str(self.site),
                occurrence=key,
                producer_node_owner=f"ExceptionGroupConstruction:{label}",
            ),
            guard=completes,
            site=self.site,
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        """Raise the group ``constructed`` builds, on each arm it is built."""
        return self.constructed(ctx).and_then(lambda group: ExitSet.halted(group))


def _builtin_group_name(coordinate) -> str | None:
    """``ExceptionGroup`` or ``BaseExceptionGroup`` when ``coordinate`` is
    that builtin class's identity (the callee's binding), else None."""
    args = getattr(coordinate, "args", ())
    if len(args) != 2 or getattr(args[0], "value", None) != "builtins":
        return None
    name = getattr(args[1], "value", None)
    return name if name in ("ExceptionGroup", "BaseExceptionGroup") else None


def _is_exception_instance(member) -> bool | None:
    """Whether a constructed member is an exception instance
    (``PyExceptionInstance_Check``): True, False, or None (not decided here).

    A constructed group is one.  A member whose value is a class operand (a
    class named without calling it, ``AuthenticatedExceptionTypeValue``) is
    not, when its identity names one class (a builtin or a source class); an
    import path may name an instance, so that is not decided here.  A raise
    whose class its construction decided is an instance; a construction that
    decided no class (``UndeterminedRaiseEffect``) is not decided here."""
    from sugar_lift_py_tests.authenticated_exception_matching import (
        _is_canonical_class_identity,
    )
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
        AuthenticatedExceptionTypeValue,
    )

    if isinstance(member, GroupedRaiseEffect):
        return True
    value = getattr(member, "raised_value", None)
    if isinstance(value, AuthenticatedExceptionTypeValue):
        if _is_canonical_class_identity(value.exception_type_identity()):
            return False
        return None
    if isinstance(member, RaiseEffect):
        return True
    return None


def _is_exception(member) -> bool | None:
    """Whether an instance member is an ``Exception``, asked of the one
    matcher ``except`` asks (``matches_raise_effect``) over the class the
    member's construction decided: True, False, or None (a member of no
    class, or a question the matcher retains)."""
    from sugar_lift_py_tests.authenticated_exception_matching import (
        MatchDecided,
        matches_raise_effect,
    )
    from sugar_lift_py_tests.temporal.builtin_name_bindings import (
        builtin_name_temporal,
    )

    if getattr(member, "exception_type_coordinate", None) is None:
        return None
    verdict = matches_raise_effect(
        member, builtin_name_temporal().value_if_bound("Exception")
    )
    return verdict.value if isinstance(verdict, MatchDecided) else None
