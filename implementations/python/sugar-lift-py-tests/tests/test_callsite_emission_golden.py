"""BYTE-IDENTITY RATCHET for the callsite/#euf# emission (CALLSUGAR_REFACTOR_GOAL.md, Step 0).

The CallSugar/BridgeStrategy refactor changes DISPATCH, never emitted bytes. The `#euf#`
contract names are the join keys: a single drifted byte means facts land in different
universes, the contradiction is never computed, and you get a green proof that lies. The
unit kit cannot see that. THIS test can: it re-lifts a curated set of callsite sources and
asserts the emitted slots (name/inv/pre/post/kind/formals/...) are byte-identical to the
pinned golden.

If a `name` here changes, you broke the join. If a `pre` appears on an assertion, you fell
off the conjoin path. Either way: STOP, and re-pin only if the change is DELIBERATE.
"""
from __future__ import annotations

import json
from pathlib import Path

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report

_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "callsite_emission_golden.json"

# Same curated sources as the golden capture -- the callsite/#euf#/dig emission paths the
# refactor touches. Keep in sync with the fixture; a mismatch is the point.
SOURCES = {
    "unresolved_array_arg": "def t():\n    assert aggregate([1, 2, 3]) == 6\n",
    "unresolved_int_arg": "def t():\n    assert make_value_xc(5) == 1\n",
    "unresolved_int_arg_b": "def t():\n    assert make_value_xc(5) == 2\n",
    "unresolved_str_arg": 'def t():\n    assert parse_int("42") == 42\n',
    "resolved_literal_body": "def h():\n    return 42\ndef t():\n    assert h() == 42\n",
    "two_calls_same_callee": "def t():\n    assert make_value_xc(5) == 1\n    assert make_value_xc(5) == 1\n",    "resolved_dig_universe": "def f(x):\n    if x > 0:\n        return 1\n    return 0\ndef t():\n    assert f(5) == 1\n",
}
_FIELDS = ("name", "kind", "inv", "pre", "post", "formals", "out_binding", "bridge_source_symbol")


def _capture(src: str) -> dict:
    try:
        rep = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
        contracts = sorted(
            ({f: repr(getattr(c, f, None)) for f in _FIELDS} for c in rep.payload.ir),
            key=lambda d: d["name"],
        )
        return {"contracts": contracts}
    except FactoryGap as g:
        return {"panic": {"observed": g.info.get("observed"), "fix": g.info.get("fix")}}
    except Exception as e:  # noqa: BLE001 -- a captured error is part of the golden behavior
        return {"error": f"{type(e).__name__}: {e}"}


def test_callsite_emission_is_byte_identical_to_the_golden():
    golden = json.loads(_GOLDEN.read_text())
    current = {key: _capture(src) for key, src in SOURCES.items()}
    # Per-source diff so a break names the exact callsite that drifted.
    for key in sorted(set(golden) | set(current)):
        assert current.get(key) == golden.get(key), (
            f"callsite emission drift at {key!r}:\n"
            f"  golden : {json.dumps(golden.get(key), indent=2)}\n"
            f"  current: {json.dumps(current.get(key), indent=2)}\n"
            "If this change is DELIBERATE, re-pin fixtures/callsite_emission_golden.json; "
            "otherwise you broke the #euf# join."
        )
