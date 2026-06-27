from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
PYTHON_COMPONENT_MANIFEST = ROOT / ".sugar/components/python/manifest.toml"
COMPONENT_PLAN_METHOD = "sugar.component.plan"


def _component_command() -> tuple[list[str], Path | None]:
    manifest = tomllib.loads(PYTHON_COMPONENT_MANIFEST.read_text(encoding="utf-8"))
    command = list(manifest["command"])
    working_dir = manifest.get("working_dir")
    resolved_working_dir = None
    if working_dir is not None:
        resolved_working_dir = (PYTHON_COMPONENT_MANIFEST.parent / working_dir).resolve()
    return command, resolved_working_dir


def _run_component(messages: list[dict]) -> list[dict]:
    command, working_dir = _component_command()
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        command,
        input="\n".join(json.dumps(message) for message in messages) + "\n",
        text=True,
        capture_output=True,
        check=False,
        cwd=working_dir,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def test_python_component_manifest_registers_cli_rendezvous_transport() -> None:
    command, working_dir = _component_command()

    assert working_dir == ROOT
    assert command[:2] == [
        "python3",
        "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/lift_rpc.py",
    ]
    assert command[2:] == ["--rpc"]


def test_python_component_plan_claims_py_evidence_with_lift_manifest(tmp_path) -> None:
    source = tmp_path / "encoder.py"
    source.write_text("def encode_len(data):\n    return len(data)\n", encoding="utf-8")
    responses = _run_component(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocol_version": "sugar-component/1"},
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": COMPONENT_PLAN_METHOD,
                "params": {
                    "workspace_root": str(tmp_path),
                    "project_forensics": {
                        "items": [
                            {
                                "id": "file:encoder.py",
                                "kind": "source",
                                "path": "encoder.py",
                                "language_hint": "python",
                                "reason": "extension .py",
                            }
                        ]
                    },
                    "workspace_evidence": {
                        "languages": [
                            {
                                "language": "python",
                                "path": "encoder.py",
                                "reason": "extension .py",
                            }
                        ],
                        "items": [],
                    },
                    "intent": "lift",
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
        ]
    )

    plan = next(response for response in responses if response.get("id") == 2)["result"]
    assert plan["decision"] == "claim"
    assert plan["claims"] == [
        {
            "item": "file:encoder.py",
            "role": "source-lifter",
            "surface": "python",
        }
    ]
    assert plan["plugins"] == [
        {
            "name": "python-lift",
            "kind": "lift",
            "surface": "python",
            "emit": "ir-document",
        }
    ]
    assert len(plan["lift_manifests"]) == 1
    lift_manifest = plan["lift_manifests"][0]
    assert lift_manifest["surface"] == "python"
    assert lift_manifest["name"] == "python-lift"
    assert lift_manifest["version"] == "0.1.0"
    assert lift_manifest["protocol_version"] == "pep/1.7.0"
    assert lift_manifest["kind"] == "lift"
    assert Path(lift_manifest["command"][1]) == (
        ROOT / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/lift_rpc.py"
    )
    assert lift_manifest["command"][2:] == ["--rpc"]
    assert lift_manifest["working_dir"] == "."
    assert plan["diagnostics"] == []


def test_python_component_plan_declines_when_forensics_have_no_python(tmp_path) -> None:
    (tmp_path / "Cargo.toml").write_text(
        "[package]\nname = 'demo'\nversion = '0.1.0'\n",
        encoding="utf-8",
    )
    responses = _run_component(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": COMPONENT_PLAN_METHOD,
                "params": {
                    "workspace_root": str(tmp_path),
                    "project_forensics": {
                        "items": [
                            {
                                "id": "file:Cargo.toml",
                                "kind": "manifest",
                                "path": "Cargo.toml",
                                "language_hint": "rust",
                                "reason": "Cargo.toml",
                            }
                        ]
                    },
                    "workspace_evidence": {"languages": [], "items": []},
                    "intent": "lift",
                },
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
        ]
    )

    plan = next(response for response in responses if response.get("id") == 2)["result"]
    assert plan == {
        "decision": "decline",
        "reason": "no Python source evidence",
    }
