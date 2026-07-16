from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Literal

from sugar_lift_py_tests.sugar_binary import (
    SugarBinaryResolutionError,
    resolve_sugar_binary,
)

Verdict = Literal["sat", "unsat", "refused", "solver-timeout"]

ROOT = Path(__file__).resolve().parents[5]
PY_TESTS = ROOT / "implementations" / "python" / "sugar-lift-py-tests"
PY_SOURCE = ROOT / "implementations" / "python" / "sugar-lift-python-source"
PY_PYTEST_WITNESS = ROOT / "implementations" / "python" / "sugar-lift-py-pytest-witness"
_SUGAR_BUILD_LOCK = Lock()
_RESOLVED_SUGAR_BIN: Path | None = None


class WitnessPipelineError(RuntimeError):
    pass


class ProofObligationPanic(WitnessPipelineError):
    """Terminal prove row that has no lawful aggregate verdict."""

    def __init__(self, row: object):
        self.row = row
        rendered = json.dumps(row, sort_keys=True, separators=(",", ":"))
        super().__init__(f"PROOF OBLIGATION PANIC: {rendered}")


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
    global _RESOLVED_SUGAR_BIN
    if _RESOLVED_SUGAR_BIN is not None:
        return _RESOLVED_SUGAR_BIN
    with _SUGAR_BUILD_LOCK:
        if _RESOLVED_SUGAR_BIN is not None:
            return _RESOLVED_SUGAR_BIN
        try:
            _RESOLVED_SUGAR_BIN = resolve_sugar_binary(profile="debug")
        except SugarBinaryResolutionError as exc:
            raise WitnessPipelineError(str(exc)) from exc
        return _RESOLVED_SUGAR_BIN


def ensure_sugar_bin() -> Path:
    return _ensure_sugar_bin()


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
portfolio = ["z3", "maude", "coq"]
mode = "first-wins"

[solvers.z3]
binary = "z3"
ir_compiler = "smt-lib-v2.6"
flags = ["-smt2", "-in"]
timeout_seconds = 10

[solvers.maude]
binary = "maude"
ir_compiler = "maude"
timeout_seconds = 10

[solvers.coq]
binary = "coqc"
ir_compiler = "coq"
timeout_seconds = 10
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


def hermetic_sugar_env(
    project: Path, *, base: dict[str, str] | None = None
) -> dict[str, str]:
    """Point the sugar binary at this project's staged `.sugar` only.

    `SUGAR_HOME` is the exclusive component-discovery door (see
    `component_roots` in sugar-cli). Setting it to `project/.sugar` keeps
    mint/prove/lift from reading the binary's repo-root kit tree or any
    ancestor `.sugar` — the pre-existing non-hermeticity that made aggregate
    witness runs lie. **One door; no dual path.** Every suite invocation of
    the sugar binary against a project must go through this env (via
    `run_sugar_cli` or an equivalent that calls this function).
    """
    env = dict(os.environ if base is None else base)
    # Pure env builder: do not mkdir. Callers that need a staged project
    # (run_sugar_cli / mint) create `.sugar` themselves; verifying a missing
    # project must not silently create one.
    env["SUGAR_HOME"] = str((project / ".sugar").resolve())
    # Drop any ambient component path the host shell may carry; the staged
    # project is the sole authority for this invocation.
    env.pop("SUGAR_COMPONENT_PATH", None)
    return env


# Back-compat alias used by early hermeticity patches.
_hermetic_sugar_env = hermetic_sugar_env


def clear_stale_project_proofs(project: Path) -> None:
    """Remove content-addressed proof catalogs that would alias across runs.

    Mint writes `*.proof` under the project root; prove may also write under
    `.sugar/runs`. A reused project directory would otherwise load sibling
    catalogs into the same pool.
    """
    for stale in project.glob("*.proof"):
        stale.unlink(missing_ok=True)
    runs = project / ".sugar" / "runs"
    if runs.is_dir():
        for stale in runs.glob("*.proof"):
            stale.unlink(missing_ok=True)


def run_sugar_cli(
    project: Path,
    args: list[str],
    *,
    timeout: float | None = 120,
    sugar_bin: Path | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """THE one door: invoke the sugar binary hermetically against `project`.

    Always sets `SUGAR_HOME=project/.sugar` and drops ambient
    `SUGAR_COMPONENT_PATH`. Callers that shell out to mint/prove/lift without
    going through this (or `hermetic_sugar_env`) are a hermeticity bug.
    """
    sugar = sugar_bin if sugar_bin is not None else _ensure_sugar_bin()
    project = project.resolve()
    project.mkdir(parents=True, exist_ok=True)
    (project / ".sugar").mkdir(parents=True, exist_ok=True)
    env = hermetic_sugar_env(project)
    return subprocess.run(
        [str(sugar), *args],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
        env=env,
        input=input_text,
    )


def mint_project(
    project: Path, *, sugar_bin: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Hermetic `sugar mint --out . --quiet` against a staged project."""
    clear_stale_project_proofs(project)
    capture = project / ".sugar" / "lift" / "python" / "lift-rpc-capture.jsonl"
    capture.unlink(missing_ok=True)
    return run_sugar_cli(
        project,
        ["mint", "--out", ".", "--quiet"],
        sugar_bin=sugar_bin,
    )


def mint_and_prove(project: Path) -> WitnessPipelineResult:
    sugar = _ensure_sugar_bin()
    mint = mint_project(project, sugar_bin=sugar)
    if mint.returncode != 0:
        raise WitnessPipelineError(
            "sugar mint failed\n" f"stdout:\n{mint.stdout}\nstderr:\n{mint.stderr}"
        )
    capture = project / ".sugar" / "lift" / "python" / "lift-rpc-capture.jsonl"
    lift_doc = _captured_lift_document(capture)
    prove = run_sugar_cli(
        project,
        ["prove", ".", "--json", "--z3", "z3"],
        sugar_bin=sugar,
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
    primary_lift_responses = [
        item
        for item in lift_responses
        if isinstance(item.get("result"), dict) and item["result"].get("ir")
    ]
    if len(primary_lift_responses) != 1:
        raise WitnessPipelineError(
            f"expected one primary lift response, got {responses!r}"
        )
    return primary_lift_responses[0]["result"]


def prove_verdict(prove_doc: dict) -> Verdict:
    rows = prove_doc.get("rows", [])
    if not rows:
        raise WitnessPipelineError(f"sugar prove returned no rows: {prove_doc!r}")
    for row in rows:
        if not isinstance(row, dict):
            raise ProofObligationPanic(row)
    statuses = [row.get("status") for row in rows]
    if "unsatisfied" in statuses:
        return "unsat"
    if statuses and all(status == "discharged" for status in statuses):
        return "sat"
    if statuses and all(status == "refused" for status in statuses):
        for row in rows:
            invocations = row.get("verification", {}).get("solverInvocations", [])
            if not invocations or any(
                invocation.get("verdict") not in {"refused", "undecidable"}
                for invocation in invocations
            ):
                raise ProofObligationPanic(row)
        return "refused"
    terminal = next(
        (
            row
            for row in rows
            if row.get("status") not in {"discharged", "unsatisfied", "solver-timeout"}
        ),
        None,
    )
    if terminal is not None:
        raise ProofObligationPanic(terminal)
    if "solver-timeout" in statuses:
        return "solver-timeout"
    raise ProofObligationPanic(prove_doc)
