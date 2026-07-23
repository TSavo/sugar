from pathlib import Path


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_instrument_names_forbidden_side_doors_and_replacement(tmp_path):
    from sugar_lift_py_tests.idd.builtin_closed_operation_instrument import (
        collect_builtin_closed_operation_report,
    )

    _write(
        tmp_path,
        "src/bad.py",
        "def derive(provider_name, builtin_result):\n"
        "    try:\n"
        "        if provider_name == 'pytest.raises':\n"
        "            return builtin_result is True\n"
        "    except ConstructionPanic:\n"
        "        return False\n",
    )
    report = collect_builtin_closed_operation_report(tmp_path)

    assert report.r == {
        "construction_side_doors": 1,
        "generic_builtin_verdicts": 1,
        "name_or_vendor_gates": 1,
        "panic_catches": 1,
    }
    assert all("floor" in row.replacement.lower() for row in report.offenders)


def test_instrument_truthful_floor_shape_is_zero(tmp_path):
    from sugar_lift_py_tests.idd.builtin_closed_operation_instrument import (
        collect_builtin_closed_operation_report,
    )

    _write(
        tmp_path,
        "src/good.py",
        "def apply_closed_operation(receiver, operation):\n"
        "    return receiver.callable_application_with(operation, None)\n",
    )

    report = collect_builtin_closed_operation_report(tmp_path)

    assert report.r == {
        "construction_side_doors": 0,
        "generic_builtin_verdicts": 0,
        "name_or_vendor_gates": 0,
        "panic_catches": 0,
    }
    assert report.offenders == ()
