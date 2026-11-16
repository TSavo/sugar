"""A generator expression made in one place and pulled in another.

Python runs a generator expression's body lazily.  Where it is made, only
its outermost iterable is evaluated and ``iter`` runs on it; each ``next`` of
that iterator, each later generator's iterable, each condition and each
element expression run when a consumer pulls a member (``list(g)``, ``for x
in g``, ``sum(g)``, ``next(g)``).  A halt of the pull therefore leaves at the
consumer, inside whatever ``try`` is around it, and a generator never pulled
halts nowhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor.floor_value import FloorValue


@dataclass(frozen=True)
class GeneratorValue(FloorValue):
    """A generator object whose pull may halt or owes a read
    (``ComprehensionSugar._generator``).

    ``pulled`` is the one pull of a member, reduced where the generator was
    made over its symbolic member (``iterator_operation.stepped`` and the
    fold): its halts (the iterator's ``next``, an element's or a condition's
    raise) and what it owes.  It is stated where the generator is pulled,
    never where it is made: ``next_with`` hands it to the consumer's one
    iterator path.  ``term`` is the generator expression's own coordinate
    (``py.generatorexp(<occurrence>, <evaluation key>)``,
    ``ComprehensionSugar._own_coordinate``).

    Every consumer that iterates pulls through ``next_with``, the one
    iterator path (``iterator_operation.stepped``): a ``for``, a
    comprehension, ``str.join`` (``string_value._joined``).  A builtin that
    does not pull through ``iter``/``next`` reads a value whose iteration
    is not decided here (it is no builtin container,
    ``source_call_resolution._builtin_container``): it is the one unanswered
    call, whose undetermined raise owes its member
    (``builtin_dunder_call``), so no halt of the pull is dropped there
    either.
    """

    term: object
    pulled: object = field(compare=False)
    site: object = field(default=None, compare=False)

    def denotes_value(self) -> bool:
        """A generator object is a Python value; its type's iteration is
        what is not decided here."""
        return True

    def to_term(self, *, owner: str):
        del owner
        return self.term

    def iter_with(self, operation, ctx):
        """``iter(g)``: a generator is its own iterator; CPython's
        ``__iter__`` of one returns it and cannot raise."""
        del operation, ctx
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(self)

    def pull(self, follow):
        """The one door the pull is stated through (``next_with``): every
        face of ``pulled`` is the consumer's (its halts and what it owes), and
        ``follow()`` runs on each face it completes on."""
        return self.pulled.and_then(lambda _member: follow())

    def next_with(self, operation, ctx):
        """``next(g)``: the pull runs here (``pull``).  On each face it
        completes on, the member it yields -- or the ``StopIteration`` that
        ends it -- is the one two-faced undecided read
        (``FloorValue.undecided_next``), since how many members it yields is
        not decided here."""
        del ctx
        return self.pull(
            lambda: self.undecided_next(operation.blame, owner="GeneratorValue.next")
        )

    def project_sequence_with(self, operation, ctx):
        """``a, b = g``: ``UNPACK_SEQUENCE`` iterates the generator, so the
        pull runs here (``pull``): its halts and what it owes are the
        unpack's.  On each face it completes on, how many members it yields
        is not decided here, so the unpack is the runtime unpack's two faces
        over the generator's own coordinate (``project_symbolic``): each name
        its position's projection under the unpack's completes atom, the
        undetermined raise under its complement.  Never a member made up,
        never the count assumed."""
        return self.pull(lambda: operation.project_symbolic(self, ctx))
