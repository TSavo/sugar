from __future__ import annotations

from sugar_lift_py_tests.lift_rpc import audit_lift_file


def test_mixed_tuple_unpack_unrolls_name_and_attribute_stores_in_order() -> None:
    source = "def f(obj):\n" "    a, obj.field = (3, 4)\n" "    return a\n"
    _payload, gaps = audit_lift_file(source, "mixed.py", hold_panic=True)
    assert not [gap for gap in gaps if gap.info.get("observed") == "Assign"]
    assert not [gap for gap in gaps if gap.info.get("observed") == "a"]


def test_loop_carried_named_subscript_cell_is_curry_state() -> None:
    source = (
        "def f(xs):\n"
        "    i = 0\n"
        "    for k in range(0, 3):\n"
        "        xs[k] = i\n"
        "        i += 1\n"
        "        if i > 2:\n"
        "            break\n"
        "    return xs\n"
    )
    _payload, gaps = audit_lift_file(source, "loop.py", hold_panic=True)
    assert not [gap for gap in gaps if gap.info.get("observed") == "nonlocal mutation"]
