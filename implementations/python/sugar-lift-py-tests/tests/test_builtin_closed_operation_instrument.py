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


def test_instrument_structurally_sees_spelling_gates_of_cluster_five(tmp_path):
    """Sin cluster 5 shapes: name gates outside authenticated coordinates.

    Before the production fixes these four patterns lived at the named
    coordinates. The instrument must catch each by AST shape, not by the
    legacy ``pytest.raises`` / ``contextlib.suppress`` substring filter.
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
    assert any("pytest" in text for text in observed)
    assert any("type_name in" in text for text in observed)
    assert any("suppresses_exception" in text for text in observed)
    assert any("exception_names" in text for text in observed)


def test_instrument_fixed_cluster_five_production_sites_are_zero():
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


def test_instrument_lying_twin_name_suppress_shell_is_red(tmp_path):
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
    # effect.exception_name attr compare / load in residual decision path
    assert any(
        "exception_name" in row.observed or "suppresses_exception" in row.observed
        for row in gates
    )
