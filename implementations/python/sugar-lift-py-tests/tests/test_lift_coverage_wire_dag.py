from pathlib import Path

from sugar_lift_py_tests.lift_rpc import _build_lift_coverage, lift_file_payload


def test_coverage_projection_uses_the_payload_term_table_door(tmp_path: Path) -> None:
    source = "def f(x):\n    assert x == 1\n    return x\n"
    path = tmp_path / "demo.py"
    path.write_text(source, encoding="utf-8")
    payload = lift_file_payload(source, "demo.py")

    payload_rpc = payload.to_rpc()
    coverage = _build_lift_coverage(
        root=tmp_path, paths=[path], payload_rpc=payload_rpc
    )

    assert coverage["totals"]["stated"] == 1
