from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.idd.guarded_loop_recurrence import (
    scan_guarded_loop_recurrence,
    summarize_guarded_loop_recurrence,
)


def test_instrument_names_each_forbidden_symbolic_loop_shape(tmp_path: Path) -> None:
    source = tmp_path / "nodes.py"
    source.write_text(
        """
def substitution_binding(self, scope):
    return self._make_call(self._make_name(f\"py.fold.{op}\"), (init, self.iter))

def _construct_sugar(self):
    return ForUniversalSugar(target=self.target.id)
"""
    )

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
    source.write_text(
        """
loop_values[target.id] = value
value = node_from_cid(completed_face.state_c_id)
"""
    )

    findings = scan_guarded_loop_recurrence(tmp_path)

    assert {f.code for f in findings} == {
        "ambient-loop-value-map",
        "cid-decoded-into-value",
    }


def test_instrument_reports_numeric_r_and_lawful_projection_is_silent(
    tmp_path: Path,
) -> None:
    (tmp_path / "binding_state.py").write_text(
        """
class LoopProjectedBinding:
    completed_faces: tuple[LoopProjectedCompletedFace, ...]

BindingState = Node | UnboundBinding | GuardedBinding | LoopProjectedBinding
"""
    )
    (tmp_path / "loop_recurrence.py").write_text(
        """
def project_loop_recurrence(loop, scope, trace_builder):
    construction = LoopConstructionV1(...)
    return LoopProjectedBinding(construction.target.target_cid, completed_faces)
"""
    )

    findings = scan_guarded_loop_recurrence(tmp_path)
    summary = summarize_guarded_loop_recurrence(findings)

    assert findings == ()
    assert summary == {
        "instrument": "R_guarded_loop_recurrence",
        "R_guarded_loop_recurrence": 0,
        "offenders": [],
        "replacement": "LoopConstructionV1 plus LoopProjectedBinding",
    }


def test_current_tree_measurement_has_nonempty_denominator() -> None:
    root = Path(__file__).parents[2]
    findings = scan_guarded_loop_recurrence(root / "sugar-source-tree" / "src")

    assert findings
    assert {f.code for f in findings} == {
        "symbolic-loop-fold-substitution",
        "symbolic-loop-universal",
    }
