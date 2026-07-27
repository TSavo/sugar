from __future__ import annotations

from importlib.machinery import ModuleSpec
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from sugar_lift_py_tests.authenticated_pytest import (
    ExecutionEnvironmentMismatch,
    activate_checkout_import_roots,
    authenticate_distribution,
    authenticate_lift,
    corpus_manifest_cid,
    interpreter_identity,
    main,
)


def fake_module(name: str, version: str, path: Path) -> ModuleType:
    module = ModuleType(name)
    module.__version__ = version
    module.__file__ = str(path)
    module.__spec__ = ModuleSpec(name, loader=None, origin=str(path))
    return module


def test_truthful_distribution_inside_own_site_packages_is_accepted(tmp_path) -> None:
    purelib = tmp_path / "venv/lib/python3.12/site-packages"
    module = fake_module("pandas", "3.0.3", purelib / "pandas/__init__.py")

    identity = authenticate_distribution(
        name="pandas",
        module=module,
        expected_version="3.0.3",
        metadata_version="3.0.3",
        metadata_location=purelib,
        purelib=purelib,
    )

    assert identity.version == "3.0.3"
    assert identity.loaded_from == (purelib / "pandas/__init__.py").resolve()


def test_lying_233_distribution_is_refused_loudly(tmp_path) -> None:
    purelib = tmp_path / "venv/lib/python3.12/site-packages"
    module = fake_module("pandas", "2.3.3", purelib / "pandas/__init__.py")

    with pytest.raises(ExecutionEnvironmentMismatch, match=r"pandas.*2\.3\.3.*3\.0\.3"):
        authenticate_distribution(
            name="pandas",
            module=module,
            expected_version="3.0.3",
            metadata_version="2.3.3",
            metadata_location=purelib,
            purelib=purelib,
        )


def test_leaking_distribution_outside_own_site_packages_is_refused(tmp_path) -> None:
    purelib = tmp_path / "managed/lib/python3.12/site-packages"
    foreign = tmp_path / "ambient/lib/python3.12/site-packages"
    module = fake_module("pandas", "3.0.3", foreign / "pandas/__init__.py")

    with pytest.raises(
        ExecutionEnvironmentMismatch,
        match="outside this interpreter's own site-packages",
    ):
        authenticate_distribution(
            name="pandas",
            module=module,
            expected_version="3.0.3",
            metadata_version="3.0.3",
            metadata_location=foreign,
            purelib=purelib,
        )


def test_dist_info_disagreement_is_refused(tmp_path) -> None:
    purelib = tmp_path / "venv/lib/python3.12/site-packages"
    module = fake_module("pandas", "3.0.3", purelib / "pandas/__init__.py")

    with pytest.raises(ExecutionEnvironmentMismatch, match="dist-info records 3.0.5"):
        authenticate_distribution(
            name="pandas",
            module=module,
            expected_version="3.0.3",
            metadata_version="3.0.5",
            metadata_location=purelib,
            purelib=purelib,
        )


def test_same_version_foreign_dist_info_is_refused(tmp_path) -> None:
    purelib = tmp_path / "managed/lib/python3.12/site-packages"
    foreign = tmp_path / "ambient/lib/python3.12/site-packages"
    module = fake_module("pandas", "3.0.3", purelib / "pandas/__init__.py")

    with pytest.raises(
        ExecutionEnvironmentMismatch,
        match="dist-info loaded from.*outside this interpreter's own site-packages",
    ):
        authenticate_distribution(
            name="pandas",
            module=module,
            expected_version="3.0.3",
            metadata_version="3.0.3",
            metadata_location=foreign,
            purelib=purelib,
        )


def test_lift_must_resolve_from_the_synced_checkout(tmp_path) -> None:
    repo = tmp_path / "sugar"
    expected = repo / "implementations/python/sugar-lift-py-tests/src"
    truthful = fake_module(
        "sugar_lift_py_tests", "0.1.0", expected / "sugar_lift_py_tests/__init__.py"
    )
    foreign = fake_module(
        "sugar_lift_py_tests",
        "0.1.0",
        tmp_path / "ambient/site-packages/sugar_lift_py_tests/__init__.py",
    )

    assert authenticate_lift(truthful, repo).loaded_from.is_relative_to(expected)
    with pytest.raises(
        ExecutionEnvironmentMismatch, match="lift import escaped the synced checkout"
    ):
        authenticate_lift(foreign, repo)


def test_manifest_cid_is_order_independent_and_path_bound() -> None:
    assert corpus_manifest_cid(["pandas/b.py", "pandas/a.py"]) == (
        "sha256:194cbd45be1fdf143d4ed8dca52fb946dc88b5a15198dbef26426ef514503ca6"
    )
    assert corpus_manifest_cid(["pandas/a.py"]) != corpus_manifest_cid(["pandas/b.py"])


def test_selected_interpreter_identity_is_named() -> None:
    identity = interpreter_identity()

    assert identity.implementation == sys.implementation.name
    assert identity.version == (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    assert identity.executable == Path(sys.executable).absolute()


def test_checkout_import_roots_come_from_the_managed_closure_declaration(
    tmp_path,
) -> None:
    repo = tmp_path / "sugar"
    declared = repo / "implementations/python/sugar-source-tree/src"
    declared.mkdir(parents=True)
    dockerfile = repo / "tools/sugar-build/Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text(
        "ENV PYTHONPATH=/workspace/sugar/implementations/python/sugar-source-tree/src\n",
        encoding="utf-8",
    )
    path = ["ambient"]

    activate_checkout_import_roots(repo, path)

    assert path == [str(declared.resolve()), "ambient"]


def test_launcher_refuses_before_pytest_on_environment_mismatch(
    monkeypatch, capsys
) -> None:
    import sugar_lift_py_tests.authenticated_pytest as launcher

    def refuse():
        raise ExecutionEnvironmentMismatch(
            "pandas corpus mismatch: imported 2.3.3; required exact 3.0.3"
        )

    invoked = False

    def forbidden_pytest_main(args):
        nonlocal invoked
        invoked = True
        return 0

    monkeypatch.setattr(launcher, "authenticate_environment", refuse)
    monkeypatch.setattr(pytest, "main", forbidden_pytest_main)

    assert main(["-q"]) == 78
    assert invoked is False
    stderr = capsys.readouterr().err
    assert "BATTLEAXE EXECUTION ENVIRONMENT REFUSED" in stderr
    assert "imported 2.3.3; required exact 3.0.3" in stderr


def test_bpytest_wrapper_contract_is_collected_by_pytest() -> None:
    repo = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        ["bash", str(repo / "tests/bpytest_authenticated_wrapper.sh"), str(repo)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "PASS: authenticated bpytest wrapper" in completed.stdout
