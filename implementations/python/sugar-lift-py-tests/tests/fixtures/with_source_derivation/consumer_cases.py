"""Consumers for the source-derived context-manager acceptance truth-set."""

from __future__ import annotations

import arbitrary_manager_module as m
import arbitrary_native_module as n


def normal():
    with m.some_manager(m.ExpectedError):
        pass


def raised_unsuppressed():
    with m.some_manager(m.ExpectedError):
        raise m.OtherError("other")


def raised_suppressed():
    with m.some_manager(m.ExpectedError) as observation_slot:
        assert observation_slot.label == "matched-exception"
        raise m.ExpectedError("expected")


def exit_fails():
    with m.some_manager(m.ExpectedError, fail_exit=True):
        raise m.ExpectedError("body failure")


def enter_fails(body_observation):
    with m.some_manager(m.ExpectedError, fail_enter=True):
        body_observation.append("entered")


def returns_from_body():
    with m.some_manager(m.ExpectedError):
        return "body return"


def breaks_from_body():
    for _ in range(1):
        with m.some_manager(m.ExpectedError):
            break


def continues_from_body():
    for _ in range(1):
        with m.some_manager(m.ExpectedError):
            continue


def manager_evaluated_once():
    with m.some_manager(m.ExpectedError):
        raise m.ExpectedError("expected")


def protocol_resource():
    with m.some_resource() as resource:
        return resource


def protocol_resource_does_not_suppress():
    with m.some_resource():
        raise m.OtherError("resource body failure")


def lying_claim_does_not_suppress():
    with m.lying_manager():
        raise m.ExpectedError("claim must not grant suppression")


def opaque_native():
    with n.some_manager():
        pass
