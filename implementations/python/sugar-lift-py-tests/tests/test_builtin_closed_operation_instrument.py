"""Teeth for builtin_closed_operation_instrument — structural, not substring.

Cluster 5 shapes (exception_name / matcher.name / importorskip / type_name in)
and vendor CM coordinates beyond the old {pytest.raises, contextlib.suppress}
substring list. Lying twins plant arms the substring matcher missed.
"""

from __future__ import annotations

from pathlib import Path


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_is_vendor_cm_coordinate_spelling_is_structural_not_substring() -> None:
    from sugar_lift_py_tests.idd.builtin_closed_operation_instrument import (
        is_vendor_cm_coordinate_spelling,
    )

    assert is_vendor_cm_coordinate_spelling("pytest.raises")
    assert is_vendor_cm_coordinate_spelling("pytest.warns")
    assert is_vendor_cm_coordinate_spelling("contextlib.suppress")
    assert is_vendor_cm_coordinate_spelling("contextlib.nullcontext")
    assert is_vendor_cm_coordinate_spelling("unittest.mock.patch")
    assert is_vendor_cm_coordinate_spelling("warnings.catch_warnings")

    assert not is_vendor_cm_coordinate_spelling("xpytest.raisesy")
    assert not is_vendor_cm_coordinate_spelling("not pytest.raises")
    assert not is_vendor_cm_coordinate_spelling("pytest")
    assert not is_vendor_cm_coordinate_spelling("numpy.array")
    assert not is_vendor_cm_coordinate_spelling("")


def test_instrument_names_forbidden_side_doors_and_replacement(tmp_path: Path) -> None:
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


def test_instrument_truthful_floor_shape_is_zero(tmp_path: Path) -> None:
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


def test_instrument_structurally_sees_spelling_gates_of_cluster_five(tmp_path: Path) -> None:
    """Sin cluster 5 shapes: name gates outside authenticated coordinates.

    The instrument must catch each by AST shape, not by the legacy
    ``pytest.raises`` / ``contextlib.suppress`` substring filter.
    """
    from sugar_lift_py_tests.idd.builtin_closed_operation_instrument import (
        collect_builtin_closed_operation_report,
    )

    _write(
        tmp_path,
        "loop_recurrence_sugar.py",
        "def _advance(effect):\n"
        "    if effect.exception_name == 'StopIteration':\n"
        "        return 'finish'\n"
        "    return effect\n",
    )
    _write(
        tmp_path,
        "exit_disposition.py",
        "def _resource_verdict(name, matcher):\n"
        "    if name == matcher.name:\n"
        "        return 'suppress'\n"
        "    return 'restore'\n",
    )
    _write(
        tmp_path,
        "import_binding.py",
        "def _importorskip_module(func):\n"
        "    if func.id == 'importorskip':\n"
        "        return 'mod'\n"
        "    if func.value.id == 'pytest':\n"
        "        return 'mod'\n"
        "    return None\n",
    )
    _write(
        tmp_path,
        "class_value.py",
        "def python_isinstance(type_name):\n"
        "    if type_name in {'tuple', 'list', 'dict'}:\n"
        "        return False\n"
        "    return None\n",
    )
    # Residual shell after Suppresses was fixed: name-keyed ExitSuppressionContract.
    _write(
        tmp_path,
        "call_site_value.py",
        "class ExitSuppressionContract:\n"
        "    exception_names = frozenset()\n"
        "    def suppresses_exception(self, exception_name):\n"
        "        return exception_name in self.exception_names\n",
    )

    report = collect_builtin_closed_operation_report(tmp_path)
    gates = [row for row in report.offenders if row.axis == "name_or_vendor_gates"]
    observed = {row.observed for row in gates}

    assert report.r["name_or_vendor_gates"] >= 5
    assert any("exception_name" in text for text in observed)
    assert any("matcher.name" in text for text in observed)
    assert any("importorskip" in text for text in observed)
    assert any("type_name in" in text for text in observed)
    assert any("suppresses_exception" in text for text in observed)
    assert any("exception_names" in text for text in observed)


def test_instrument_fixed_cluster_five_production_sites_are_zero() -> None:
    """After the coordinate fix, the named production files have no name gates."""
    from sugar_lift_py_tests.idd.builtin_closed_operation_instrument import (
        collect_builtin_closed_operation_report,
    )

    root = Path(__file__).resolve().parents[1] / "src"
    report = collect_builtin_closed_operation_report(root)
    targets = {
        "sugar_lift_py_tests/sugar/loop_recurrence_sugar.py",
        "sugar_lift_py_tests/outcome/exit_disposition.py",
        "sugar_lift_py_tests/import_binding.py",
        "sugar_lift_py_tests/floor/class_value.py",
        "sugar_lift_py_tests/floor/call_site_value.py",
    }
    hits = [
        row
        for row in report.offenders
        if row.path in targets and row.axis == "name_or_vendor_gates"
    ]
    assert hits == [], "cluster-5 production sites still gate on spelling:\n" + "\n".join(
        f"{row.path}:{row.line}: {row.observed}" for row in hits
    )


def test_instrument_lying_twin_name_suppress_shell_is_red(tmp_path: Path) -> None:
    """Planting suppresses_exception / exception_names must be detected (teeth)."""
    from sugar_lift_py_tests.idd.builtin_closed_operation_instrument import (
        collect_builtin_closed_operation_report,
    )

    _write(
        tmp_path,
        "residual.py",
        "def decide(effect, disposition):\n"
        "    name = effect.exception_name\n"
        "    return disposition.suppresses_exception(name)\n",
    )
    report = collect_builtin_closed_operation_report(tmp_path)
    gates = [row for row in report.offenders if row.axis == "name_or_vendor_gates"]
    assert any("suppresses_exception" in row.observed for row in gates), gates
    assert any(
        "exception_name" in row.observed or "suppresses_exception" in row.observed
        for row in gates
    )


def test_lying_twin_pytest_warns_compare_is_detected(tmp_path: Path) -> None:
    """Lying twin: vendor arm the old substring list did not name.

    Old: ``"pytest.raises" in value or "contextlib.suppress" in value``
    left ``provider_name == "pytest.warns"`` silent.
    """
    from sugar_lift_py_tests.idd.builtin_closed_operation_instrument import (
        collect_builtin_closed_operation_report,
    )

    _write(
        tmp_path,
        "src/warns_gate.py",
        "def derive(provider_name):\n"
        "    if provider_name == 'pytest.warns':\n"
        "        return 'side-door'\n"
        "    return 'floor'\n",
    )
    report = collect_builtin_closed_operation_report(tmp_path)
    assert report.r["name_or_vendor_gates"] >= 1
    assert report.r["construction_side_doors"] >= 1
    assert any("pytest.warns" in row.observed for row in report.offenders)


def test_lying_twin_match_case_vendor_arm_is_detected(tmp_path: Path) -> None:
    """Lying twin: match/case vendor arm is not a Compare — substring visitor missed it."""
    from sugar_lift_py_tests.idd.builtin_closed_operation_instrument import (
        collect_builtin_closed_operation_report,
    )

    _write(
        tmp_path,
        "src/match_gate.py",
        "def derive(provider_name):\n"
        "    match provider_name:\n"
        "        case 'contextlib.nullcontext':\n"
        "            return 'side-door'\n"
        "        case _:\n"
        "            return 'floor'\n",
    )
    report = collect_builtin_closed_operation_report(tmp_path)
    assert report.r["name_or_vendor_gates"] >= 1
    assert any("contextlib.nullcontext" in row.observed for row in report.offenders)


def test_lying_twin_attribute_chain_gate_is_detected(tmp_path: Path) -> None:
    """Lying twin: compare to pytest.raises as Attribute, no string Constant."""
    from sugar_lift_py_tests.idd.builtin_closed_operation_instrument import (
        collect_builtin_closed_operation_report,
    )

    _write(
        tmp_path,
        "src/attr_gate.py",
        "import pytest\n"
        "\n"
        "def derive(provider):\n"
        "    if provider is pytest.raises:\n"
        "        return 'side-door'\n"
        "    return 'floor'\n",
    )
    report = collect_builtin_closed_operation_report(tmp_path)
    assert report.r["name_or_vendor_gates"] >= 1
    assert any("pytest.raises" in row.observed for row in report.offenders)


def test_lying_twin_dict_logo_dispatch_is_detected(tmp_path: Path) -> None:
    """Lying twin: vendor spelling as dict key (relocated from Compare)."""
    from sugar_lift_py_tests.idd.builtin_closed_operation_instrument import (
        collect_builtin_closed_operation_report,
    )

    _write(
        tmp_path,
        "src/dict_gate.py",
        "def derive(provider_name):\n"
        "    table = {'unittest.mock.patch': 'side-door'}\n"
        "    return table.get(provider_name, 'floor')\n",
    )
    report = collect_builtin_closed_operation_report(tmp_path)
    assert report.r["name_or_vendor_gates"] >= 1
    assert any("unittest.mock.patch" in row.observed for row in report.offenders)


def test_substring_false_positive_is_not_a_gate(tmp_path: Path) -> None:
    """Truthful: superstring that only contains the old needles is not a coordinate."""
    from sugar_lift_py_tests.idd.builtin_closed_operation_instrument import (
        collect_builtin_closed_operation_report,
    )

    _write(
        tmp_path,
        "src/doc.py",
        "def note(msg):\n"
        "    if msg == 'see docs for xpytest.raisesy examples':\n"
        "        return True\n"
        "    return False\n",
    )
    report = collect_builtin_closed_operation_report(tmp_path)
    assert report.r["name_or_vendor_gates"] == 0
    assert report.offenders == ()


def test_generic_verdict_is_exact_name_not_substring(tmp_path: Path) -> None:
    from sugar_lift_py_tests.idd.builtin_closed_operation_instrument import (
        collect_builtin_closed_operation_report,
    )

    _write(
        tmp_path,
        "src/verdict.py",
        "def a(builtin_result):\n"
        "    return builtin_result is True\n"
        "\n"
        "def b(my_builtin_result_flag):\n"
        "    return my_builtin_result_flag is True\n",
    )
    report = collect_builtin_closed_operation_report(tmp_path)
    assert report.r["generic_builtin_verdicts"] == 1


def test_instrument_does_not_scan_idd_or_plant_self(tmp_path: Path) -> None:
    """No self-fabrication: idd lane is skipped; instrument never inserts callers."""
    from sugar_lift_py_tests.idd.builtin_closed_operation_instrument import (
        collect_builtin_closed_operation_report,
    )

    _write(
        tmp_path,
        "sugar_lift_py_tests/idd/planted_sin.py",
        "def derive(provider_name):\n"
        "    if provider_name == 'pytest.raises':\n"
        "        return True\n"
        "    return False\n",
    )
    _write(
        tmp_path,
        "sugar_lift_py_tests/floor/ok.py",
        "def apply(receiver, operation):\n"
        "    return receiver.callable_application_with(operation, None)\n",
    )
    report = collect_builtin_closed_operation_report(tmp_path)
    assert report.offenders == ()
