from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.idd.guarded_loop_recurrence import (
    scan_guarded_loop_recurrence,
    summarize_guarded_loop_recurrence,
)


def test_instrument_names_each_forbidden_symbolic_loop_shape(tmp_path: Path) -> None:
    source = tmp_path / "nodes.py"
    source.write_text("""
def substitution_binding(self, scope):
    return self._make_call(self._make_name(f\"py.fold.{op}\"), (init, self.iter))

def _construct_sugar(self):
    return ForUniversalSugar(target=self.target.id)
""")

    findings = scan_guarded_loop_recurrence(tmp_path)

    assert [(f.code, f.replacement) for f in findings] == [
        (
            "symbolic-loop-fold-substitution",
            "LoopConstructionV1 plus LoopProjectedBinding",
        ),
        (
            "symbolic-loop-universal",
            "LoopConstructionV1 guarded recurrence",
        ),
    ]


def test_instrument_rejects_ambient_map_and_cid_value_fabrication(
    tmp_path: Path,
) -> None:
    source = tmp_path / "loop_recurrence.py"
    source.write_text("""
loop_values[target.id] = value
value = node_from_cid(completed_face.state_c_id)
""")

    findings = scan_guarded_loop_recurrence(tmp_path)

    assert {f.code for f in findings} == {
        "ambient-loop-value-map",
        "cid-decoded-into-value",
    }


def test_instrument_names_typed_loud_live_loop_face_teeth(tmp_path: Path) -> None:
    (tmp_path / "live_loop_construction.py").write_text("""
raise BindingStateWireGap("live loop else requires exhaustion-path body state production")
raise BindingStateWireGap("live loop outward halted face requires path-state production")
""")

    findings = scan_guarded_loop_recurrence(tmp_path)

    assert {finding.code for finding in findings} == {
        "missing-loop-else-exhaustion-state",
        "missing-loop-outward-halted-state",
    }


def test_instrument_reports_numeric_r_and_lawful_projection_is_silent(
    tmp_path: Path,
) -> None:
    (tmp_path / "binding_state.py").write_text("""
class LoopProjectedBinding:
    completed_faces: tuple[LoopProjectedCompletedFace, ...]

BindingState = Node | UnboundBinding | GuardedBinding | LoopProjectedBinding
""")
    (tmp_path / "loop_recurrence.py").write_text("""
def project_loop_recurrence(loop, scope, trace_builder):
    construction = LoopConstructionV1(...)
    return LoopProjectedBinding(construction.target.target_cid, completed_faces)
""")

    findings = scan_guarded_loop_recurrence(tmp_path)
    summary = summarize_guarded_loop_recurrence(findings)

    assert findings == ()
    assert summary == {
        "instrument": "R_guarded_loop_recurrence",
        "R_guarded_loop_recurrence": 0,
        "offenders": [],
        "replacement": "LoopConstructionV1 plus LoopProjectedBinding",
    }


def test_instrument_names_legacy_single_generator_comprehension(tmp_path: Path):
    (tmp_path / "comprehension_sugar.py").write_text("""
class ComprehensionSugar:
    target: str
    iterable: object
""")

    findings = scan_guarded_loop_recurrence(tmp_path)

    assert [(finding.code, finding.replacement) for finding in findings] == [
        (
            "single-generator-comprehension-transform",
            "nested guarded flat-map recurrence with explicit exhaustion",
        )
    ]


def test_current_tree_measurement_is_stable_zero() -> None:
    root = Path(__file__).parents[2]
    findings = scan_guarded_loop_recurrence(root)

    assert findings == ()
    assert summarize_guarded_loop_recurrence(findings)["R_guarded_loop_recurrence"] == 0
