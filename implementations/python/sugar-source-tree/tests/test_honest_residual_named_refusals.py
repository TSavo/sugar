"""Honest residuals refuse specifically (C3) — never TypeError backend-defect.

After the 159 lies, 10 seal files remain honest:
  E=5 CM resolution gap (already named ContextManagerResolutionConstructionGap)
  H=3 recursion → ConstructionRecursionGap via roll_call
  L=1 multi-face LoopProjectedBinding read → SugarNotWritten
  Λ=1 Lambda body testimony → SugarNotWritten

These must name the artifact they cannot see, not abort as raw TypeError.
"""

from __future__ import annotations

from types import SimpleNamespace

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.binding_state import (
    LoopProjectedBinding,
    LoopProjectedCompletedFace,
    UnboundBinding,
    binding_state_read_node,
)
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def test_multi_face_loop_projected_binding_read_is_sugar_not_written() -> None:
    """L-class: multi-face LoopProjectedBinding refuses by name, not TypeError."""
    target = "blake3-512:" + "ab" * 32
    guard = "blake3-512:" + "cd" * 32
    faces = (
        LoopProjectedCompletedFace(
            target_cid=target,
            completion_kind="NormalExhaustion",
            guard_formula_cid=guard,
            state=UnboundBinding("x", "then"),
            guard_formula=None,
            exit_partition_arity=1,
        ),
        LoopProjectedCompletedFace(
            target_cid=target,
            completion_kind="BreakExit",
            guard_formula_cid=guard,
            state=UnboundBinding("x", "break"),
            guard_formula=None,
            exit_partition_arity=1,
        ),
    )
    state = LoopProjectedBinding(target_cid=target, completed_faces=faces)

    def make_read(_s):
        raise AssertionError("make_read should not run for multi-face")

    try:
        binding_state_read_node(state, make_read=make_read)
        raise AssertionError("expected SugarNotWritten")
    except SugarNotWritten as gap:
        assert "LoopProjectedBinding" in gap.observed
        assert "multi-face" in gap.observed.lower() or "faces" in gap.observed
        assert "do not raise TypeError" in gap.fix
    except TypeError as te:
        raise AssertionError(
            f"TypeError is the old lie: {te!r}; want SugarNotWritten"
        ) from te


def test_lambda_body_cid_mismatch_is_sugar_not_written() -> None:
    """Λ-class: body fragment mismatch refuses as SNW, not TypeError."""
    from sugar_lift_py_tests.sugar.lambda_sugar import LambdaSugar
    from sugar_lift_py_tests.sugar.name_sugar import NameSugar

    site_src = "lambda x: x"
    sf = SourceFile(
        (site_src + "\n", "lam.py", blake3_512_of((site_src + "\n").encode()))
    )
    body = NameSugar(name="x", site=sf.root.fragment)
    frame = SimpleNamespace(
        parameters=("x",),
        formal_coordinates=(SimpleNamespace(cid="blake3-512:" + "11" * 32),),
        # Match site so the formal/frame checks pass and body is the failure.
        definition_fragment_cid=sf.root.fragment.seal().cid,
    )
    try:
        LambdaSugar(
            formals=("x",),
            body=body,
            source_call_frame=frame,
            formal_coordinate_cids=("blake3-512:" + "11" * 32,),
            body_fragment_cid="blake3-512:" + "22" * 32,  # force body mismatch
            site=sf.root.fragment,
        )
        raise AssertionError("expected SugarNotWritten")
    except SugarNotWritten as gap:
        assert "body" in gap.owner.lower() or "body" in gap.observed.lower()
        assert gap.fix and (
            "fragment" in gap.fix.lower() or "body" in gap.fix.lower()
        )
    except TypeError as te:
        raise AssertionError(
            f"TypeError is the old lie: {te!r}; want SugarNotWritten"
        ) from te


def test_classify_honest_residual_recognizes_e_h_l_lambda() -> None:
    from recensus_enumerate_consumer import _classify_honest_residual
    from sugar_source_tree.panic import ContextManagerResolutionConstructionGap

    # E — already a named CM resolution gap at the source.
    e = ContextManagerResolutionConstructionGap(
        kind="runtime-selected",
        demand_cid="blake3-512:" + "aa" * 32,
        candidate_member_cids=(),
        blame="with-site",
        owner="With._construct_sugar",
        observed="authenticated preconstruction resolution gap: runtime-selected",
        requested="one resolved authenticated ContextManagerContractRefV1",
        fix="publish or resolve the exact typed CM contract",
    )
    t, m, honest = _classify_honest_residual(e)
    assert honest and "ContextManager" in t

    # H — raw RecursionError reclassified as ConstructionRecursionGap.
    t, m, honest = _classify_honest_residual(
        RecursionError("maximum recursion depth exceeded")
    )
    assert honest and t == "ConstructionRecursionGap"

    # L — legacy TypeError(type(state)) still classified honest by message.
    t, m, honest = _classify_honest_residual(
        TypeError("<class 'sugar_source_tree.binding_state.LoopProjectedBinding'>")
    )
    assert honest and "LoopProjected" in t

    # Λ — legacy TypeError body message still classified honest.
    t, m, honest = _classify_honest_residual(
        TypeError("LambdaSugar body requires its exact source body testimony")
    )
    assert honest and "Lambda" in t

    # Dishonest residual stays backend-defect territory.
    t, m, honest = _classify_honest_residual(
        AttributeError("'X' object has no attribute 'y'")
    )
    assert not honest


def test_roll_call_recursion_reports_construction_recursion_gap() -> None:
    """H-class: RecursionError during sugar() becomes a named gap on the report."""
    from sugar_source_tree import roll_call
    from sugar_source_tree.panic import SugarNotWritten

    class _FakeFragment:
        def __str__(self) -> str:
            return "fake-fragment"

    class _FakeReporter:
        def __init__(self) -> None:
            self.gaps: list[tuple[object, object]] = []

        def report_gap(self, node: object, panic: object) -> None:
            self.gaps.append((node, panic))

    class _FakeUnit:
        filename = "deep.py"

    class _FakeNode:
        kind = "FunctionDef"

        def __init__(self) -> None:
            self.fragment = _FakeFragment()

        def line_col_span(self):
            return SimpleNamespace(start_line=1, start_col=0)

        def sugar(self):
            raise RecursionError("maximum recursion depth exceeded")

    class _FakeSourceFile:
        def __init__(self) -> None:
            self.reporter = _FakeReporter()
            self.unit = _FakeUnit()
            self.root = _FakeNode()
            self.root.kind = "Module"

            def _mod_ok():
                return None

            # Module root succeeds; the function root is the recursion site.
            self.root.sugar = _mod_ok  # type: ignore[method-assign]
            self._fn = _FakeNode()

        def nodes(self):
            return ()

        def functions(self):
            return (self._fn,)

    sf = _FakeSourceFile()
    report = roll_call.discharge(sf)
    assert report is not None
    assert len(sf.reporter.gaps) == 1
    _node, gap = sf.reporter.gaps[0]
    assert isinstance(gap, SugarNotWritten)
    assert getattr(gap, "kind", None) == "ConstructionRecursionGap"
    assert "RecursionError" in gap.observed
    assert "ConstructionRecursionGap" in gap.fix
