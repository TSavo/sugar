from __future__ import annotations

from sugar_lift_py_tests.lift_rpc import audit_lift_file


def test_datetime_native_star_import_advances_to_next_loud_front(
    cpython_311_datetime_path,
) -> None:
    source = cpython_311_datetime_path.read_text(encoding="utf-8")
    recovered = audit_lift_file(
        source,
        str(cpython_311_datetime_path),
        recover_panics=True,
    )

    assert all(
        not (
            panic.gap["observed"] == "ImportFrom"
            and panic.gap["blame"].endswith(":2829:4")
        )
        for panic in recovered.panics
    )
    assert any(
        panic.gap["observed"] == "Delete" and panic.gap["blame"].endswith(":2834:4")
        for panic in recovered.panics
    )
