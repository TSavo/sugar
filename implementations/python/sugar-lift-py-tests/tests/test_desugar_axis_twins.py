"""The desugar axis (#6243/#6244): four disjoint quantities, exact cardinality.

Every twin here asserts an EXACT count. ``>= 1`` passes with extra incorrect
rows and with a misclassified owner — which is exactly how a second axis starts
reporting a useful-looking number whose denominator is not honest.

The four quantities the door produces, and which twin separates them:

    R_desugar                  typed refusals + typed red effects   (1, 2, 3, 5, 8)
    R_construction             tree construction totality           (4)
    desugarConstructionPanics  construction law during desugar      (6)
    desugarDefects             ordinary + audit/instrument defects  (7, 9)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sugar_lift_py_tests.gap.info import ConstructionGap
from sugar_lift_py_tests.gap.panic import ConstructionPanic

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    path = _SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeSugar:
    """A constructed sugar whose desugar outcome (or panic) is dictated."""

    def __init__(self, *, outcome=None, raises=None) -> None:
        self._outcome = outcome
        self._raises = raises

    def desugar(self, ctx=None):
        del ctx
        if self._raises is not None:
            raise self._raises
        return self._outcome


def _raise_effect(occurrence: str):
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    return RaiseEffect(exception_name="ValueError", occurrence=occurrence)


def _incomplete(occurrence: str):
    from sugar_lift_py_tests.outcome import Incomplete

    return Incomplete(_raise_effect(occurrence))


def _axis():
    from sugar_lift_py_tests.desugar_axis import DesugarAxis

    return DesugarAxis()


# -- 1. one YieldFrom refusal -> EXACTLY one desugar row ---------------------


def test_twin_1_yield_from_refusal_is_exactly_one_desugar_row(tmp_path: Path) -> None:
    module = _load("control_effect_recensus")
    path = tmp_path / "gen.py"
    path.write_text("def f(xs):\n    yield from xs\n", encoding="utf-8")
    row = module._measure_file(path, relative="gen.py", workspace_root=tmp_path)
    assert row["category"] == "completed"
    assert row["functionsClean"] == 1
    assert row["R_desugar"] == 1
    assert row["desugarFamilies"] == {"YieldFromSugar.desugar": 1}


# -- 2. two same-class effects on DIFFERENT sites -> two rows ----------------


def test_twin_2_two_effect_sites_are_two_rows() -> None:
    axis = _axis()
    outcome = (_incomplete("gen.py:2:4"), _incomplete("gen.py:7:4"))
    axis.measure(_FakeSugar(outcome=outcome), where="gen.py:1:0")
    row = axis.row()
    # The defect this bites: keying by the enclosing function's DEFINITION line
    # collapses both raises into one row, because both live in one function.
    assert row["R_desugar"] == 2
    assert row["desugarFamilies"] == {"RaiseEffect": 2}


# -- 3. the SAME occurrence reached twice -> one row -------------------------


def test_twin_3_same_occurrence_twice_is_one_row() -> None:
    axis = _axis()
    shared = _incomplete("gen.py:2:4")
    # Once as a shared object (lawful DAG re-entry), once as an equal-coordinate
    # twin reached down another edge.
    outcome = (shared, shared, _incomplete("gen.py:2:4"))
    axis.measure(_FakeSugar(outcome=outcome), where="gen.py:1:0")
    row = axis.row()
    assert row["R_desugar"] == 1
    assert row["desugarFamilies"] == {"RaiseEffect": 1}


# -- 4. a construction gap changes ONLY R_construction ----------------------


def test_twin_4_construction_gap_moves_only_the_construction_axis(
    tmp_path: Path,
) -> None:
    module = _load("control_effect_recensus")
    path = tmp_path / "coro.py"
    path.write_text("async def h(x):\n    return x\n", encoding="utf-8")
    row = module._measure_file(path, relative="coro.py", workspace_root=tmp_path)
    assert row["functionsClean"] == 0
    # ONE gap occurrence, tallied once (catch + reporter is not two rows).
    assert row["families"] == {"SugarNotWritten": 1}
    assert row["R_desugar"] == 0
    assert row["desugarFamilies"] == {}
    assert row["desugarConstructionPanics"] == []
    assert row["desugarDefects"] == []


# -- 5. a typed desugar refusal changes ONLY R_desugar ----------------------


def test_twin_5_typed_refusal_moves_only_the_desugar_axis(tmp_path: Path) -> None:
    module = _load("control_effect_recensus")
    path = tmp_path / "gen.py"
    path.write_text("def f(xs):\n    yield from xs\n", encoding="utf-8")
    row = module._measure_file(path, relative="gen.py", workspace_root=tmp_path)
    assert row["families"] == {}
    assert row["R_desugar"] == 1
    assert row["desugarConstructionPanics"] == []
    assert row["desugarDefects"] == []


# -- 6. ConstructionPanic -> ONLY desugarConstructionPanics, and RED --------


def test_twin_6_construction_panic_is_its_own_collection_and_red() -> None:
    axis = _axis()
    panic = ConstructionPanic(
        ConstructionGap(
            owner="MissingConstructor",
            blame="gen.py:2:4",
            observed="OpaqueValue",
            requested="constructed value",
            fix="implement the constructor",
        )
    )
    # A BaseException: neither `except SugarNotWritten` nor `except Exception`
    # sees it. Unhandled it escapes the per-function loop and can abort a whole
    # census run with no row at all.
    axis.measure(_FakeSugar(raises=panic), where="gen.py:1:0")
    row = axis.row()
    assert row["R_desugar"] == 0
    assert row["desugarFamilies"] == {}
    assert row["desugarDefects"] == []
    assert len(row["desugarConstructionPanics"]) == 1
    assert row["desugarConstructionPanics"][0]["owner"] == "MissingConstructor"
    assert axis.red is True
    # ...and measurement CONTINUES: the next function is still measured.
    axis.measure(_FakeSugar(outcome=_incomplete("gen.py:9:4")), where="gen.py:8:0")
    assert axis.row()["R_desugar"] == 1


# -- 7. an ordinary Exception -> ONLY desugarDefects, and RED ---------------


def test_twin_7_ordinary_exception_is_a_defect_not_semantic_r() -> None:
    axis = _axis()
    axis.measure(_FakeSugar(raises=KeyError("boom")), where="gen.py:1:0")
    row = axis.row()
    assert row["R_desugar"] == 0
    assert row["desugarFamilies"] == {}
    assert row["desugarConstructionPanics"] == []
    assert len(row["desugarDefects"]) == 1
    assert row["desugarDefects"][0]["kind"] == "desugar-exception"
    assert row["desugarDefects"][0]["detail"].startswith("KeyError")
    assert axis.red is True


# -- 8. depth GREATER than 24 is still fully measured -----------------------


def test_twin_8_no_semantic_depth_cap() -> None:
    from sugar_lift_py_tests.outcome import Complete

    axis = _axis()
    outcome: object = _incomplete("deep.py:40:8")
    for _ in range(40):  # far past the deleted `if depth > 24: return`
        outcome = Complete(outcome)  # type: ignore[arg-type]
    axis.measure(_FakeSugar(outcome=outcome), where="deep.py:1:0")
    row = axis.row()
    assert row["R_desugar"] == 1
    assert row["desugarFamilies"] == {"RaiseEffect": 1}
    assert row["desugarDefects"] == []


# -- 9. cyclic / unsupported outcome traversal -> a LOUD audit defect -------


def test_twin_9_cycle_is_a_named_audit_defect() -> None:
    axis = _axis()
    cycle: list = [_incomplete("gen.py:2:4")]
    cycle.append(cycle)
    axis.measure(_FakeSugar(outcome=cycle), where="gen.py:1:0")
    row = axis.row()
    # The reachable effect is still measured; the cycle is NAMED, never an
    # empty return.
    assert row["R_desugar"] == 1
    assert len(row["desugarDefects"]) == 1
    assert row["desugarDefects"][0]["kind"] == "audit-defect"
    assert row["desugarDefects"][0]["detail"] == "outcome-cycle:list"
    assert axis.red is True


def test_twin_9_unsupported_outcome_envelope_is_a_named_audit_defect() -> None:
    unsupported = type("UnwalkableEnvelope", (), {})
    # In the lift's own domain, so the walk is obliged to descend it — and it
    # is neither a dataclass nor a container.
    unsupported.__module__ = "sugar_lift_py_tests.fake_envelope"
    axis = _axis()
    axis.measure(_FakeSugar(outcome=unsupported()), where="gen.py:1:0")
    row = axis.row()
    assert row["R_desugar"] == 0
    assert len(row["desugarDefects"]) == 1
    assert (
        row["desugarDefects"][0]["detail"]
        == "unsupported-outcome-envelope:UnwalkableEnvelope"
    )
    assert axis.red is True


# -- the instrument gap: an effect that states no occurrence -----------------


def test_effect_without_occurrence_is_an_instrument_gap_not_a_fabricated_key() -> None:
    """No authenticated coordinate => NO row and a named instrument gap.

    The forbidden alternative is substituting the enclosing function's line,
    which silently collapses distinct effects and inflates nothing visibly.
    """
    from sugar_lift_py_tests.effect.source_oracle_effect import SourceOracleEffect
    from sugar_lift_py_tests.outcome import Incomplete

    axis = _axis()
    effect = SourceOracleEffect(reason="source absent")
    axis.measure(
        _FakeSugar(outcome=(Incomplete(effect), Incomplete(effect))),
        where="gen.py:1:0",
    )
    row = axis.row()
    assert row["R_desugar"] == 0
    assert row["desugarFamilies"] == {}
    assert len(row["desugarDefects"]) == 2
    assert {d["kind"] for d in row["desugarDefects"]} == {"instrument-gap"}
    assert {d["detail"] for d in row["desugarDefects"]} == {
        "no-occurrence-coordinate:SourceOracleEffect"
    }
    assert axis.red is True
