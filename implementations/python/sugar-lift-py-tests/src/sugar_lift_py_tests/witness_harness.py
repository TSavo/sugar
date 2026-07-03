from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Verdict = Literal["sat", "unsat"]

ROOT = Path(__file__).resolve().parents[5]
RUST_WORKSPACE = ROOT / "implementations" / "rust"
PY_TESTS = ROOT / "implementations" / "python" / "sugar-lift-py-tests"
PY_SOURCE = ROOT / "implementations" / "python" / "sugar-lift-python-source"
PY_PYTEST_WITNESS = ROOT / "implementations" / "python" / "sugar-lift-py-pytest-witness"
SUGAR_BIN = RUST_WORKSPACE / "target" / "debug" / "sugar"
_SUGAR_BUILT = False


class WitnessPipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class WitnessPipelineResult:
    lift_doc: dict
    prove_doc: dict

    @property
    def selected_sugars(self) -> tuple[str, ...]:
        walk = self.lift_doc.get("factoryAuditSummary", {}).get("factoryWalk", [])
        audits = self.lift_doc.get("factoryAudits", [])
        selected: list[str] = []
        seen: set[str] = set()
        for row in [*walk, *audits]:
            if not isinstance(row, dict) or not isinstance(row.get("selected"), str):
                continue
            name = row["selected"]
            if name in seen:
                continue
            seen.add(name)
            selected.append(name)
        return tuple(selected)

    @property
    def proofir_emitted(self) -> bool:
        return bool(self.lift_doc.get("ir"))

    @property
    def verdict(self) -> Verdict:
        return prove_verdict(self.prove_doc)


def _pythonpath() -> str:
    return os.pathsep.join(
        str(path / "src") for path in (PY_PYTEST_WITNESS, PY_TESTS, PY_SOURCE)
    )


def _ensure_sugar_bin() -> Path:
    global _SUGAR_BUILT
    if SUGAR_BIN.exists():
        return SUGAR_BIN
    if not _SUGAR_BUILT:
        completed = subprocess.run(
            [
                "cargo",
                "build",
                "--locked",
                "-p",
                "sugar-cli",
                "--bin",
                "sugar",
            ],
            cwd=RUST_WORKSPACE,
            text=True,
            capture_output=True,
            check=False,
            timeout=180,
        )
        if completed.returncode != 0:
            raise WitnessPipelineError(
                "cargo build for target/debug/sugar failed\n"
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        _SUGAR_BUILT = True
    if not SUGAR_BIN.exists():
        raise WitnessPipelineError("cargo build did not produce target/debug/sugar")
    return SUGAR_BIN


def _write_source(project: Path, source: str) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "test_witness.py").write_text(source, encoding="utf-8")


def _stage_cli_project(project: Path, source: str) -> None:
    _write_source(project, source)
    sugar = project / ".sugar"
    (sugar / "lift" / "python").mkdir(parents=True)
    (sugar / "components" / "python-lift").mkdir(parents=True)
    (sugar / "config.toml").write_text(
        """[[plugins]]
name = "python-lift"
kind = "lift"
surface = "python"

[solvers]
default = "z3"

[solvers.dispatch]
linear_arithmetic = "z3"
default = "z3"

[solvers.z3]
binary = "z3"
ir_compiler = "smt-lib-v2.6"
flags = ["-smt2", "-in"]
""",
        encoding="utf-8",
    )
    wrapper = sugar / "lift" / "python" / "proofir-python-lift-wrapper.sh"
    wrapper_py = sugar / "lift" / "python" / "proofir_python_lift_capture"
    capture = sugar / "lift" / "python" / "lift-rpc-capture.jsonl"
    wrapper_py.write_text(
        "from __future__ import annotations\n"
        "\n"
        "import os\n"
        "import subprocess\n"
        "import sys\n"
        "from pathlib import Path\n"
        "\n"
        f"PYTHONPATH = {_pythonpath()!r}\n"
        f"CAPTURE = Path({str(capture)!r})\n"
        "\n"
        "def main() -> int:\n"
        "    env = {**os.environ, 'PYTHONPATH': PYTHONPATH}\n"
        "    proc = subprocess.Popen(\n"
        "        [sys.executable, '-m', 'sugar_lift_py_tests.lift_rpc', *sys.argv[1:]],\n"
        "        stdin=sys.stdin,\n"
        "        stdout=subprocess.PIPE,\n"
        "        stderr=sys.stderr,\n"
        "        text=True,\n"
        "        env=env,\n"
        "    )\n"
        "    assert proc.stdout is not None\n"
        "    CAPTURE.parent.mkdir(parents=True, exist_ok=True)\n"
        "    with CAPTURE.open('a', encoding='utf-8') as out:\n"
        "        for line in proc.stdout:\n"
        "            sys.stdout.write(line)\n"
        "            sys.stdout.flush()\n"
        "            out.write(line)\n"
        "            out.flush()\n"
        "    return proc.wait()\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n",
        encoding="utf-8",
    )
    wrapper.write_text(
        "#!/bin/sh\n"
        'PYTHON="${PYTHON:-python3}"\n'
        f'exec "$PYTHON" "{wrapper_py}" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    (sugar / "lift" / "python" / "manifest.toml").write_text(
        f'name = "python"\ncommand = [{json.dumps(sys.executable)}, "{wrapper_py}", "--rpc"]\nworking_dir = "."\n',
        encoding="utf-8",
    )
    component_script = sugar / "components" / "python-lift" / "component.sh"
    initialize_response = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "name": "python-lift-component",
                "protocol_version": "sugar-component/1",
                "capabilities": {},
            },
        }
    )
    plan_response = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "decision": "claim",
                "plugins": [
                    {"name": "python-lift", "kind": "lift", "surface": "python"}
                ],
                "diagnostics": [
                    {"level": "info", "message": "python lift component planned"}
                ],
            },
        }
    )
    shutdown_response = json.dumps({"jsonrpc": "2.0", "id": 3, "result": None})
    component_script.write_text(
        "while IFS= read -r line; do\n"
        '  case "$line" in\n'
        f"    *'\"method\":\"initialize\"'*) printf '%s\\n' '{initialize_response}' ;;\n"
        f"    *'\"method\":\"sugar.component.plan\"'*) printf '%s\\n' '{plan_response}' ;;\n"
        f"    *'\"method\":\"shutdown\"'*) printf '%s\\n' '{shutdown_response}'; exit 0 ;;\n"
        "  esac\n"
        "done\n",
        encoding="utf-8",
    )
    component_script.chmod(0o755)
    (sugar / "components" / "python-lift" / "manifest.toml").write_text(
        'name = "python-lift-component"\n'
        'protocol_version = "sugar-component/1"\n'
        f'command = ["/bin/sh", "{component_script}"]\n',
        encoding="utf-8",
    )


def run_lift_rpc(project: Path) -> dict:
    env = {**os.environ, "PYTHONPATH": str(PY_TESTS / "src")}
    request = "\n".join(
        json.dumps(message)
        for message in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "lift",
                "params": {"workspace_root": str(project), "source_paths": ["."]},
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-m", "sugar_lift_py_tests.lift_rpc", "--rpc"],
        input=request + "\n",
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        raise WitnessPipelineError(
            "lift RPC failed\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    responses = [
        json.loads(line) for line in completed.stdout.splitlines() if line.strip()
    ]
    response = next(item for item in responses if item.get("id") == 2)
    if "error" in response:
        raise WitnessPipelineError(f"lift RPC returned error: {response['error']!r}")
    return response["result"]


def _run_lift_rpc(project: Path) -> dict:
    return run_lift_rpc(project)


def mint_and_prove(project: Path) -> WitnessPipelineResult:
    sugar = _ensure_sugar_bin()
    capture = project / ".sugar" / "lift" / "python" / "lift-rpc-capture.jsonl"
    capture.unlink(missing_ok=True)
    mint = subprocess.run(
        [str(sugar), "mint", "--out", ".", "--quiet"],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if mint.returncode != 0:
        raise WitnessPipelineError(
            "sugar mint failed\n" f"stdout:\n{mint.stdout}\nstderr:\n{mint.stderr}"
        )
    lift_doc = _captured_lift_document(capture)
    prove = subprocess.run(
        [str(sugar), "prove", ".", "--json", "--z3", "z3"],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if not prove.stdout.strip():
        raise WitnessPipelineError(
            "sugar prove --z3 failed loudly\n"
            f"stdout:\n{prove.stdout}\nstderr:\n{prove.stderr}"
        )
    try:
        prove_doc = json.loads(prove.stdout)
    except json.JSONDecodeError as exc:
        raise WitnessPipelineError(
            "sugar prove --z3 returned malformed JSON\n"
            f"stdout:\n{prove.stdout}\nstderr:\n{prove.stderr}"
        ) from exc
    return WitnessPipelineResult(lift_doc=lift_doc, prove_doc=prove_doc)


def run_source_through_real_solver(project: Path, source: str) -> WitnessPipelineResult:
    _stage_cli_project(project, source)
    return mint_and_prove(project)


def _captured_lift_document(capture: Path) -> dict:
    if not capture.exists():
        raise WitnessPipelineError(f"lift RPC capture missing at {capture}")
    responses = [
        json.loads(line) for line in capture.read_text(encoding="utf-8").splitlines()
    ]
    lift_responses = [
        item for item in responses if item.get("id") == 2 and "result" in item
    ]
    if len(lift_responses) != 1:
        raise WitnessPipelineError(f"expected one lift response, got {responses!r}")
    return lift_responses[0]["result"]


def prove_verdict(prove_doc: dict) -> Verdict:
    rows = prove_doc.get("rows", [])
    if not rows:
        raise WitnessPipelineError(f"sugar prove returned no rows: {prove_doc!r}")
    statuses = [row.get("status") for row in rows if isinstance(row, dict)]
    if "unsatisfied" in statuses:
        return "unsat"
    if statuses and all(status == "discharged" for status in statuses):
        return "sat"
    raise WitnessPipelineError(
        f"sugar prove returned no SAT/UNSAT verdict; statuses={statuses!r}"
    )
