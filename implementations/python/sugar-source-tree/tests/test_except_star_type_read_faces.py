"""An ``except*`` handler's type read carries every face it has (#7757).

Python reads an ``except*`` handler's types when a group reaches the
handler.  That read may itself raise; the raise leaves the ``try*`` there (no
later handler sees it, the ``finally`` does), beside the face on which the
types completed and the group is partitioned over them.  The router never
refuses a handler because its type read has two faces (it used to refuse it
by name: ``symbolic except* type``).

Truthful: a two-faced type read gives the try* a halt under the read's
complement, beside the handled arm under the read's completes guard, every
arm owing the read's member.

Lying: the same handler whose type read is one plain completion gives no such
halt and owes nothing: the halt is the read's, never invented by the router.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import tempfile
from pathlib import Path

from with_resolution_fixture import source_file_with_preconstruction

_READ_OWNER = "test.except-star-type-read"

_SOURCE = (
    "def A(z):\n"
    "    try:\n"
    "        raise ValueError\n"
    "    except* ValueError:\n"
    "        pass\n"
    "    return z\n"
)


def _try_star_sugar():
    from sugar_lift_py_tests.sugar.try_star_sugar import TryStarSugar

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(_SOURCE)
        path = f.name
    function = next(source_file_with_preconstruction(Path(path)).functions())

    def find(sugar):
        if isinstance(sugar, TryStarSugar):
            return sugar
        for name in getattr(sugar, "__dataclass_fields__", {}):
            value = getattr(sugar, name)
            for item in value if isinstance(value, tuple) else (value,):
                if hasattr(item, "__dataclass_fields__"):
                    found = find(item)
                    if found is not None:
                        return found
        return None

    node = find(function.sugar())
    assert node is not None
    return node


def _read_guard():
    from sugar_lift_py_tests.ir import atomic, ctor, str_const

    return atomic(
        "python:attribute.completes",
        [ctor("python:attribute", (str_const("errors"), str_const("ValueError")))],
    )


@dataclass(frozen=True)
class _TwoFacedTypeRead:
    """A handler type whose read completes with ``value`` under the read's
    completes guard and halts, undetermined, under its complement: the shape
    every undecided read takes (``ExitSet.two_faced``)."""

    value: object
    site: object

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.two_faced(
            self.value,
            UndeterminedRaiseEffect(
                blame=str(self.site),
                occurrence="except-star-type-read",
                producer_node_owner=_READ_OWNER,
                site=self.site,
            ),
            guard=_read_guard(),
            site=self.site,
        )


@dataclass(frozen=True)
class _PlainTypeRead:
    value: object

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(self.value)


def _routed(read_of):
    node = _try_star_sugar()
    ((matchers, handler_body, slot_id),) = node.handlers
    (matcher,) = matchers
    expected = matcher.desugar(None).completed_value()
    assert expected is not None
    handlers = (((read_of(expected, node.site),), handler_body, slot_id),)
    return replace(node, handlers=handlers).desugar(None)


def _read_halts(exits):
    from sugar_lift_py_tests.outcome.exit_set import Halted

    return [
        exit_
        for exit_ in exits.exits
        if isinstance(exit_, Halted)
        and getattr(exit_.effect, "producer_node_owner", None) == _READ_OWNER
    ]


def test_a_two_faced_except_star_type_read_is_a_halt_of_the_try_star():
    from sugar_lift_py_tests.outcome.exit_set import (
        Completed,
        Halted,
        complement_guard,
    )

    routed = _routed(_TwoFacedTypeRead)

    (halt,) = _read_halts(routed)
    assert halt.guard == complement_guard(_read_guard())
    # Raised while reading the handler's types, where the group was.
    assert halt.state is not None

    # On the completed face the handler matched: the body's ValueError never
    # leaves the try*, and the handled arm stands under the read's guard.
    assert not any(
        isinstance(exit_, Halted)
        and getattr(exit_.effect, "producer_node_owner", None) != _READ_OWNER
        for exit_ in routed.exits
    )
    completed = [exit_ for exit_ in routed.exits if isinstance(exit_, Completed)]
    assert completed
    assert all(exit_.guard == _read_guard() for exit_ in completed)

    # What the read owes stays owed, on every arm.
    assert routed.owed_items()
    assert all(exit_.owed for exit_ in routed.exits)


def test_a_plain_except_star_type_read_gives_no_halt_and_owes_nothing():
    from sugar_lift_py_tests.outcome.exit_set import Completed

    routed = _routed(lambda value, _site: _PlainTypeRead(value))

    assert _read_halts(routed) == []
    assert routed.owed_items() == ()
    assert routed.exits
    assert all(isinstance(exit_, Completed) for exit_ in routed.exits)
