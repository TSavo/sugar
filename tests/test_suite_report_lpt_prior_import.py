"""Teeth: LPT prior must not kill suite-report; degrade must be loud.

A NameError / any exception in pytest_sessionfinish after tests pass still
killed suite-report.json (#7040 Path without import). The prior is a cost
optimisation; the suite report is testimony — testimony must not be hostage.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from sugar_lift_py_tests.repo_root import resolve_repo_root

ROOT = resolve_repo_root()
PLUGIN = ROOT / "tools" / "python_package_suite_report.py"
TOOLS = ROOT / "tools"


def _load_suite_report():
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(
        "python_package_suite_report_tooth", PLUGIN
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_suite_report_imports_pathlib_path() -> None:
    src = PLUGIN.read_text(encoding="utf-8")
    tree = ast.parse(src)
    has_path = False
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "pathlib":
            names = {a.name for a in node.names}
            if "Path" in names:
                has_path = True
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "pathlib":
                    has_path = True
    assert has_path, (
        "tools/python_package_suite_report.py must import Path from pathlib — "
        "_write_lpt_prior uses Path at sessionfinish; missing import kills "
        "suite-report.json after a green test run"
    )


def test_write_lpt_prior_name_is_defined_with_path() -> None:
    src = PLUGIN.read_text(encoding="utf-8")
    assert "def _write_lpt_prior" in src
    assert "Path(self.config.rootpath)" in src
    mod = _load_suite_report()
    assert hasattr(mod.SuiteReporter, "_write_lpt_prior")


def test_enabled_lpt_prior_writes_content_addressed_cost(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """An enabled shelf persists a duration under the measured file's CID."""
    mod = _load_suite_report()
    prior_root = tmp_path / "prior"
    monkeypatch.setenv("SUGAR_LPT_PRIOR_DIR", str(prior_root))
    test_path = tmp_path / "pkg" / "tests" / "test_x.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_one():\n    pass\n", encoding="utf-8")
    identity_path = tmp_path / "environment-identity.json"
    identity_path.write_text(
        json.dumps(
            {
                "environmentIdentityHash": "a" * 64,
                "sourceStamp": {"value": "stamp"},
                "dependencyAuthority": {"testExtraInputHash": "b" * 64},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    reporter = mod.SuiteReporter(
        _FakeConfig(
            {
                "suite_identity": str(identity_path),
                "suite_commit": "c" * 40,
            },
            rootpath=tmp_path,
        )
    )
    reporter._file_duration_s = {"pkg/tests/test_x.py": 1.25}
    reporter._write_lpt_prior()

    from lpt_file_shards import ContentAddressedCostPrior

    hit = ContentAddressedCostPrior(prior_root).get_for_path(test_path)
    assert hit is not None, "enabled LPT shelf must write the measured file's CID"
    assert hit.cost_s == 1.25
    assert hit.source == "suite-pytest-call-duration"
    assert len(list(prior_root.glob("*.json"))) == 1
    output = capsys.readouterr().out
    assert "status=ok" in output
    assert "files_written=1" in output
    assert "files_measured=1" in output
    assert "unresolved_paths=0" in output


class _FakeConfig:
    def __init__(self, options: dict, *, rootpath: Path):
        self._options = options
        self.rootpath = rootpath

    def getoption(self, name: str):
        key = name.lstrip("-").replace("-", "_")
        return self._options.get(key)


def test_sessionfinish_writes_suite_report_when_lpt_prior_raises(
    tmp_path: Path, monkeypatch
) -> None:
    """Shell: sessionfinish LPT prior can fail closed for report — unrepresentable.

    Plant an exception in the prior writer; suite-report.json must still land.
    """
    mod = _load_suite_report()
    identity_path = tmp_path / "environment-identity.json"
    identity_path.write_text(
        json.dumps(
            {
                "environmentIdentityHash": "a" * 64,
                "sourceStamp": {"value": "stamp"},
                "dependencyAuthority": {"testExtraInputHash": "b" * 64},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "suite-report.json"
    config = _FakeConfig(
        {
            "suite_identity": str(identity_path),
            "suite_commit": "deadbeef" * 5,
            "suite_report": str(report_path),
            "suite_order": "canonical",
            "suite_label": "tooth",
            "suite_shuffle_seed": None,
            "suite_binary_stamp": None,
            "suite_shard_index": 0,
            "suite_shard_count": 8,
        },
        rootpath=tmp_path,
    )
    reporter = mod.SuiteReporter(config)
    reporter.collected = ["pkg/tests/test_x.py::test_one"]
    reporter.executed_order = list(reporter.collected)
    reporter.passed = list(reporter.collected)
    reporter._seen_outcome = set(reporter.collected)
    reporter._file_duration_s = {"pkg/tests/test_x.py": 1.25}

    def _boom(self) -> None:
        raise RuntimeError("planted LPT prior failure")

    monkeypatch.setattr(mod.SuiteReporter, "_write_lpt_prior", _boom)
    # sessionfinish must not raise; report must exist
    reporter.pytest_sessionfinish(SimpleNamespace(), exitstatus=0)
    assert report_path.is_file(), (
        "suite-report.json must be written even when _write_lpt_prior raises — "
        "cost optimisation must never destroy measurement testimony"
    )
    body = json.loads(report_path.read_text(encoding="utf-8"))
    assert body["measuredCommit"] == "deadbeef" * 5
    assert body["counts"]["passed"] == 1
    assert body["passedNodeIds"] == ["pkg/tests/test_x.py::test_one"]


def test_write_lpt_prior_announces_disabled_shelf(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Silent no-op when prior disabled is forbidden — must name the mode."""
    mod = _load_suite_report()
    monkeypatch.setenv("SUGAR_LPT_PRIOR_DIR", "off")
    identity_path = tmp_path / "environment-identity.json"
    identity_path.write_text(
        json.dumps(
            {
                "environmentIdentityHash": "a" * 64,
                "sourceStamp": {"value": "stamp"},
                "dependencyAuthority": {"testExtraInputHash": "b" * 64},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config = _FakeConfig(
        {
            "suite_identity": str(identity_path),
            "suite_commit": "c" * 40,
            "suite_report": None,
            "suite_order": "canonical",
            "suite_label": None,
            "suite_shuffle_seed": None,
            "suite_binary_stamp": None,
            "suite_shard_index": None,
            "suite_shard_count": None,
        },
        rootpath=tmp_path,
    )
    reporter = mod.SuiteReporter(config)
    reporter._file_duration_s = {"x.py": 0.5}
    reporter._write_lpt_prior()
    combined = capsys.readouterr().out + capsys.readouterr().err
    assert "lpt-prior-write" in combined
    assert "prior-disabled" in combined or "degraded=equal-count" in combined
