"""Teeth for tools/nine_step_lift_lane.py: a failed mint names the refusal.

Run 43960179946 listed 46 pandas files whose mint exited 1 with a
``CONSTRUCTION PANIC``; the row kept 400 chars of mint's error line, and the
kit's JSON-RPC error inside it sorts ``blame`` / ``fix`` / ``observed`` ahead
of ``owner``, so no row named the owner. The row now reads the error object
whole and keeps its ``data.diagnostic``.
"""

from __future__ import annotations

import json

import repo_root_test_support  # noqa: F401 -- puts tools/ on sys.path

import nine_step_lift_lane as lane

LONG = "x" * 6000  # past the 4 KB field cap


def kit_error(code: int = -32001) -> dict:
    return {
        "code": code,
        "data": {
            "diagnostic": {
                "blame": "pandas/core/frame.py:512:4",
                "fix": "write more Floor for this Construct " + LONG,
                "observed": "SomeValue",
                "owner": "FloorValue.attribute",
                "requested": "an attribute read",
            },
            "exception_type": "ConstructionPanic",
            "kind": "typed-loud",
            "stage": "dispatch",
        },
        "message": "CONSTRUCTION PANIC: match(Sugar) { Some => cite_or_effect, None => panic!() }\nboom",
    }


def mint_stderr(error: dict) -> str:
    # The shape mint prints: the transport's wrapping, then the error object
    # compact on the same line (serde_json's Display, keys sorted).
    return (
        "\x1b[1m\x1b[31merror\x1b[39m\x1b[0m: kit transform failed: lift plugin diagnostic "
        "kind=path_execution frontend=sugar-cli::lift_plugin "
        "input_format=lift-plugin-json-rpc-v1 path=lift.path: tree enumeration failed: "
        "enumeration kit `python` unavailable: lift plugin returned error: "
        + json.dumps(error, separators=(",", ":"), sort_keys=True)
        + "\n"
    )


def test_the_owner_is_past_the_error_line_cut() -> None:
    text = mint_stderr(kit_error())
    assert "FloorValue.attribute" not in lane.last_line(text)


def test_the_kit_refusal_is_read_whole_and_structured() -> None:
    got = lane.mint_diagnostic(mint_stderr(kit_error()))
    assert got is not None
    assert got["owner"] == "FloorValue.attribute"
    assert got["blame"] == "pandas/core/frame.py:512:4"
    assert got["observed"] == "SomeValue"
    assert got["exceptionType"] == "ConstructionPanic"
    assert got["code"] == -32001
    assert got["message"].startswith("CONSTRUCTION PANIC")
    # Small: each field is bounded.
    assert len(got["fix"]) == lane.DIAGNOSTIC_FIELD_CHARS


def test_an_exception_that_is_not_a_refusal_keeps_its_traceback_tail() -> None:
    error = {
        "code": -32603,
        "message": "maximum recursion depth exceeded",
        "data": "Traceback (most recent call last):\n" + LONG + "\nRecursionError: deep",
    }
    got = lane.mint_diagnostic(mint_stderr(error))
    assert got is not None
    assert got["code"] == -32603
    assert got["traceback"].endswith("RecursionError: deep")
    assert len(got["traceback"]) == lane.DIAGNOSTIC_FIELD_CHARS


def test_a_fatal_factory_panic_diagnostic_is_read_bare() -> None:
    text = (
        "error: fatal lift plugin FactoryPanic code=-32603 stage=dispatch: boom diagnostic="
        + json.dumps({"owner": "Factory.build", "blame": "a.py:1:0", "observed": "x"})
    )
    got = lane.mint_diagnostic(text)
    assert got == {"owner": "Factory.build", "blame": "a.py:1:0", "observed": "x"}


def test_no_error_object_is_none() -> None:
    assert lane.mint_diagnostic("error: lift plugin transport stalled at stage=read_line.enter") is None


def test_the_refusal_listing_carries_the_diagnostic(tmp_path) -> None:
    seat = tmp_path / "seat"
    seat.mkdir()
    diagnostic = lane.mint_diagnostic(mint_stderr(kit_error()))
    row = {
        "file": "core/frame.py",
        "defs": 3,
        "mint": {"rc": 1, "seconds": 3.4, "error": "cut", "diagnostic": diagnostic},
        "minted": False,
        "refusals": [
            {
                "owner": "mint-exit-1",
                "symbol": None,
                "isDef": False,
                "file": "core/frame.py",
                "line": None,
                "observed": "FloorValue.attribute at pandas/core/frame.py:512:4: SomeValue",
                "diagnostic": diagnostic,
            }
        ],
        "status": "refused",
    }
    (seat / "rows.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    out = tmp_path / "summary.json"
    refusals = tmp_path / "refusals.json"
    assert (
        lane.main(["--join", str(seat), "--label", "pandas", "--out", str(out), "--refusals", str(refusals)])
        == 0
    )
    listing = json.loads(refusals.read_text(encoding="utf-8"))["refusals"]
    (site,) = listing[0]["sites"]
    assert listing[0]["owner"] == "mint-exit-1"
    assert site["diagnostic"]["owner"] == "FloorValue.attribute"
    assert site["diagnostic"]["blame"] == "pandas/core/frame.py:512:4"
