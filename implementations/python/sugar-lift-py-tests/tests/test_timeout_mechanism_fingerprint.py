"""#5306 — timeout mechanism fingerprints from engine heartbeats/roles."""

from __future__ import annotations

from sugar_lift_py_tests.idd.timeout_mechanism_fingerprint import (
    MECHANISM_FACTORY_BUILD,
    MECHANISM_MODULE_SEED_CASCADE,
    MECHANISM_RECURSIVE_FUNCTION_CONSTRUCT,
    MECHANISM_REDUCE_BODY,
    classify_stack_roles,
    collapse_role_stack,
    fingerprint_engine_events,
)


def test_classify_stack_roles_top_three_fingerprints() -> None:
    assert (
        classify_stack_roles(
            [
                "file",
                "dig.resolve_value",
                "dig.construct.function",
                "dig.construct.function.factory",
                "statement",
            ]
        )
        == MECHANISM_RECURSIVE_FUNCTION_CONSTRUCT
    )
    assert (
        classify_stack_roles(
            [
                "dig.resolve_value",
                "dig.construct.function",
                "dig.construct.function.seed",
                "dig.module_seed",
            ]
        )
        == MECHANISM_MODULE_SEED_CASCADE
    )
    assert (
        classify_stack_roles(["file", "factory.new.statement", "factory.select"])
        == MECHANISM_FACTORY_BUILD
    )
    assert classify_stack_roles(["file", "statement", "term"]) == MECHANISM_REDUCE_BODY


def test_collapse_role_stack_drops_consecutive_duplicates() -> None:
    assert (
        collapse_role_stack(
            ["file", "statement", "statement", "term", "term", "dig.resolve_value"]
        )
        == "file>statement>term>dig.resolve_value"
    )


def test_fingerprint_engine_events_names_dominant_and_multi_miss() -> None:
    events = [
        {
            "event": "enter",
            "role": "dig.resolve_value",
            "sugar": "pandas._libs.lib",
        },
        {
            "event": "enter",
            "role": "dig.resolve_value",
            "sugar": "pandas._libs.lib",
        },
        {
            "event": "enter",
            "role": "dig.resolve_value",
            "sugar": "pandas._libs.lib",
        },
        {
            "event": "enter",
            "role": "dig.resolve_value.hit",
            "sugar": "typing.cast",
        },
        {
            "event": "enter",
            "role": "dig.construct.function",
            "sugar": "typing.cast",
        },
        {
            "event": "enter",
            "role": "factory.select",
            "sugar": "Name",
        },
        {
            "event": "heartbeat",
            "role": "statement",
            "sugar": "StatementFunctionDefSugar",
            "active_stack": [
                "typing.cast|dig.resolve_value|typing.cast",
                "typing.cast|dig.construct.function|typing.cast",
                "typing.cast|dig.construct.function.factory|typing.cast",
                "StatementFunctionDefSugar|statement|mod.py:1",
            ],
        },
        {
            "event": "heartbeat",
            "role": "statement",
            "sugar": "StatementFunctionDefSugar",
            "active_stack": [
                "typing.cast|dig.resolve_value|typing.cast",
                "typing.cast|dig.construct.function|typing.cast",
                "typing.cast|dig.construct.function.factory|typing.cast",
                "StatementFunctionDefSugar|statement|mod.py:1",
            ],
        },
        {
            "event": "heartbeat",
            "role": "factory.select",
            "sugar": "Name",
            "active_stack": [
                "lift_file_payload|file|mod.py",
                "Name|factory.select|mod.py:2",
            ],
        },
    ]
    report = fingerprint_engine_events(events)
    assert report["schema"] == "sugar.timeout.mechanism.v1"
    assert report["dominant_mechanism"] == MECHANISM_RECURSIVE_FUNCTION_CONSTRUCT
    assert report["mechanism_heartbeat_counts"][MECHANISM_RECURSIVE_FUNCTION_CONSTRUCT] == 2
    assert report["mechanism_heartbeat_counts"][MECHANISM_FACTORY_BUILD] == 1
    assert report["resolve_value_miss"] == 3
    assert report["resolve_value_hit"] == 1
    assert report["wasted_reresolves"] == 2  # 3 misses of same target → 2 waste
    assert report["top_multi_miss_targets"][0]["target"] == "pandas._libs.lib"
    assert report["construct_function_enters"] == 1
    assert report["factory_select_enters"] == 1
    patterns = [row["pattern"] for row in report["stack_role_patterns"]]
    assert any("dig.construct.function" in pattern for pattern in patterns)
