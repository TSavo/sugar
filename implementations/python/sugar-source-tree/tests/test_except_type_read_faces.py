"""An ``except`` arm's type read carries every face it has (#7757).

Python evaluates an arm's type expression when a raise reaches the arm.  A
dotted read off an imported module (``except errors.ParserError``) or a
computed type may itself raise there; that raise leaves the ``try`` at that
point (no later arm sees it, the ``finally`` does), beside the face on which
the type completed and matching proceeds on it.  The router never refuses an
arm because its type read has two faces (``TrySugar._route_one_halt``).

Truthful: a two-faced type read gives the try a halt under the read's
complement, carrying the body halt's record, beside the handler's arm under
the read's completes guard, every arm owing the read's member.

Lying: the same arm whose type read is one plain completion gives no such
halt and owes nothing: the halt is the read's, never invented by the router.
"""

from __future__ import annotations

from dataclasses import dataclass
import tempfile
from pathlib import Path

from with_resolution_fixture import source_file_with_preconstruction


_SOURCE = (
    "def A(z):\n"
    "    try:\n"
    "        raise ValueError\n"
    "    except ValueError:\n"
    "        return 1\n"
    "    return z\n"
)


def _try_sugar():
    from sugar_lift_py_tests.sugar.try_sugar import TrySugar

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(_SOURCE)
        path = f.name
    function = next(source_file_with_preconstruction(Path(path)).functions())

    def find(sugar):
        if isinstance(sugar, TrySugar):
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
    """An arm type whose read completes with ``value`` under the read's
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
                occurrence="except-type-read",
                producer_node_owner="test.except-type-read",
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
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )
    from sugar_lift_py_tests.sugar.try_sugar import _route_handlers_over_exits

    node = _try_sugar()
    body = reduce_block_to_exitset(node.body, None)
    (matcher, handler_body, slot_id) = node.handlers[0]
    expected = matcher.desugar(None).completed_value()
    assert expected is not None
    handlers = ((read_of(expected, node.site), handler_body, slot_id),)
    return body, _route_handlers_over_exits(
        body, handlers, node.orelse, site=node.site, ctx=None
    )


def _read_halts(exits):
    from sugar_lift_py_tests.outcome.exit_set import Halted

    return [
        exit_
        for exit_ in exits.exits
        if isinstance(exit_, Halted)
        and getattr(exit_.effect, "producer_node_owner", None)
        == "test.except-type-read"
    ]


def test_a_two_faced_type_read_is_a_halt_of_the_try_beside_the_match():
    from sugar_lift_py_tests.outcome.exit_set import (
        Completed,
        Halted,
        complement_guard,
    )
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    body, routed = _routed(_TwoFacedTypeRead)
    (body_halt,) = body.halts()

    (halt,) = _read_halts(routed)
    assert halt.guard == complement_guard(_read_guard())
    # Raised while matching, where the body halt was: its record.
    assert isinstance(halt.state, _ReducedBlock)
    assert halt.state == body_halt.state

    # On the completed face the arm matched: the body's ValueError never
    # leaves the try, and the handler's arm stands under the read's guard.
    assert not any(
        isinstance(exit_, Halted)
        and getattr(exit_.effect, "exception_name", None) == "ValueError"
        for exit_ in routed.exits
    )
    completed = [exit_ for exit_ in routed.exits if isinstance(exit_, Completed)]
    assert completed
    assert all(exit_.guard == _read_guard() for exit_ in completed)

    # What the read owes stays owed, on every arm.
    assert routed.owed_items()
    assert all(exit_.owed for exit_ in routed.exits)


def test_a_plain_type_read_gives_no_halt_and_owes_nothing():
    from sugar_lift_py_tests.outcome.exit_set import Completed

    _body, routed = _routed(lambda value, _site: _PlainTypeRead(value))

    assert _read_halts(routed) == []
    assert routed.owed_items() == ()
    assert routed.exits
    assert all(isinstance(exit_, Completed) for exit_ in routed.exits)
