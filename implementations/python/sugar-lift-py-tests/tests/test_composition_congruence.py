"""Composition threads: outer call:<op> over a body-dug callsite coordinate.

The coordinate work (len/str/methods/attributes as call:<op>(...)) exists so a
dug function body can hand a coordinate to an outer operator and the twin
refute still fires. This is the PyCon composition seed:

    def make():
        return [1, 2, 3]
    def A():
        return len(make())   # call:len(call:make()) in A's universe
    assert A() == 3          # sat
    assert A() == 2          # unsat (derived twin from dig)

Requires CallSiteValue.call_method_with so len(make()) digs make's floor
instead of construction-gapping.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_COMPOSE_TRUE = (
    "def make():\n"
    "    return [1, 2, 3]\n"
    "\n"
    "def A():\n"
    "    return len(make())\n"
    "\n"
    "def test_a():\n"
    "    assert A() == 3\n"
)

_COMPOSE_LIE = (
    "def make():\n"
    "    return [1, 2, 3]\n"
    "\n"
    "def A():\n"
    "    return len(make())\n"
    "\n"
    "def test_a():\n"
    "    assert A() == 2\n"
)

_NESTED_STR_TRUE = (
    "def A():\n"
    "    return str(str(12))\n"
    "\n"
    "def test_a():\n"
    "    assert A() == \"12\"\n"
)

_NESTED_STR_LIE = (
    "def A():\n"
    "    return str(str(12))\n"
    "\n"
    "def test_a():\n"
    "    assert A() == \"xx\"\n"
)


def test_composition_len_over_make_lifts_nested_coordinates() -> None:
    report = build_literal_call_report(
        source=_COMPOSE_TRUE,
        filename="compose.py",
        memento_file="compose.py",
    )
    assert report is not None
    names = [row.name for row in report.payload.ir]
    assert any((n or "").endswith("A::callable") for n in names), names
    assert any((n or "").endswith("make::callable") for n in names), names
    a_callable = next(r for r in report.payload.ir if (r.name or "").endswith("A::callable"))
    post = repr(a_callable.post)
    assert "call:len" in post, post
    assert "call:make" in post, post
    # Outer len over the make coordinate — composition, not collapsed scalar-only.
    assert "call:len" in post and "call:make" in post


def test_composition_len_over_make_truthful_sat_lying_unsat(tmp_path: Path) -> None:
    """Witness-path discrimination: dig derives A()==3; lie A()==2 refutes."""
    truthful = run_source_through_real_solver(tmp_path / "true", _COMPOSE_TRUE)
    lying = run_source_through_real_solver(tmp_path / "lie", _COMPOSE_LIE)

    t_statuses = [row.get("status") for row in truthful.prove_doc.get("rows", [])]
    l_statuses = [row.get("status") for row in lying.prove_doc.get("rows", [])]

    assert truthful.verdict == "sat", (truthful.verdict, t_statuses)
    assert "refused" not in t_statuses
    assert lying.verdict == "unsat", (lying.verdict, l_statuses)
    assert "refused" not in l_statuses
    assert any(s == "unsatisfied" for s in l_statuses)


def test_nested_str_coordinate_composition_sat_unsat(tmp_path: Path) -> None:
    """Nested call:str(call:str(12)) threads; fold companion refutes the lie."""
    report = build_literal_call_report(
        source=_NESTED_STR_TRUE,
        filename="nest.py",
        memento_file="nest.py",
    )
    assert report is not None
    blob = repr([row.post for row in report.payload.ir] + [row.inv for row in report.payload.ir])
    assert "call:str" in blob

    truthful = run_source_through_real_solver(tmp_path / "str-true", _NESTED_STR_TRUE)
    lying = run_source_through_real_solver(tmp_path / "str-lie", _NESTED_STR_LIE)
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
