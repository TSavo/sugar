"""Arbitrarily renamed context managers for source-derivation acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ExpectedError(Exception):
    pass


class OtherError(Exception):
    pass


class ExpectationNotMet(Exception):
    pass


class EnterFailure(Exception):
    pass


class ExitFailure(Exception):
    pass


@dataclass(frozen=True)
class ObservationSlot:
    label: str


events: list[tuple[Any, ...]] = []
manager_evaluations = 0


def reset_observations() -> None:
    global manager_evaluations
    events.clear()
    manager_evaluations = 0


class SomeGuard:
    """An expectation boundary whose behavior is entirely visible in source."""

    def __init__(
        self,
        expected_exception: type[BaseException],
        *,
        fail_enter: bool = False,
        fail_exit: bool = False,
    ) -> None:
        self.expected_exception = expected_exception
        self.fail_enter = fail_enter
        self.fail_exit = fail_exit
        self.observation = ObservationSlot("matched-exception")

    def __enter__(self) -> ObservationSlot:
        events.append(("enter", self.expected_exception))
        if self.fail_enter:
            raise EnterFailure("enter failed")
        return self.observation

    def __exit__(self, effect_type, effect, traceback) -> bool:
        events.append(("exit", effect_type, effect, traceback))
        if self.fail_exit:
            raise ExitFailure("exit failed")
        if effect_type is None:
            raise ExpectationNotMet("expected effect was absent")
        return issubclass(effect_type, self.expected_exception)


def some_manager(
    expected_exception: type[BaseException],
    *,
    fail_enter: bool = False,
    fail_exit: bool = False,
) -> SomeGuard:
    global manager_evaluations
    manager_evaluations += 1
    events.append(("manager", expected_exception))
    return SomeGuard(
        expected_exception,
        fail_enter=fail_enter,
        fail_exit=fail_exit,
    )


class SomeResource:
    """A source-visible ProtocolResource which never suppresses effects."""

    def __init__(self) -> None:
        self.value = ObservationSlot("resource-value")

    def __enter__(self) -> ObservationSlot:
        events.append(("resource-enter",))
        return self.value

    def __exit__(self, effect_type, effect, traceback) -> bool:
        events.append(("resource-exit", effect_type, effect, traceback))
        return False


def some_resource() -> SomeResource:
    events.append(("resource-manager",))
    return SomeResource()


class ImplicitNoneResource:
    """A renamed resource whose multi-statement exit falls through to None."""

    def __enter__(self) -> ObservationSlot:
        return ObservationSlot("implicit-none-value")

    def __exit__(self, effect_type, effect, traceback) -> None:
        first_marker = 1
        second_marker = 2


def implicit_none_resource() -> ImplicitNoneResource:
    return ImplicitNoneResource()


class LyingGuard:
    """A claim cannot override the source-visible NeverSuppresses behavior."""

    claimed_suppression = True

    def __enter__(self) -> ObservationSlot:
        events.append(("lying-enter",))
        return ObservationSlot("lying-value")

    def __exit__(self, effect_type, effect, traceback) -> bool:
        events.append(("lying-exit", effect_type, effect, traceback))
        return False


def lying_manager() -> LyingGuard:
    return LyingGuard()
