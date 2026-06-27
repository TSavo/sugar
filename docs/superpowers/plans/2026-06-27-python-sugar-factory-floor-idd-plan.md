# Python Sugar/Factory/Floor IDD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python sugar/factory/floor migration around a self-instrumenting IDD loop: run the numpy and pandas lifts, catch construction panics in audit-only mode, and drive `R` to zero observed sugar/floor panics.

**Architecture:** The first deliverable is not a migrated recognizer. It is a red instrument and construction-law kernel: construction exits as `Complete(FloorValue)`, `Incomplete(actual Effect)`, or a stop-the-world sugar/floor panic that names the missing owner, blame site, and fix. Factory gaps and floor gaps are `NoReturn` panic paths, incomplete reductions are only real effects, and `R` is measured from the machine's own audit-only numpy/pandas lift panic records. The Python kit is migrated wholesale to a Rust-inspired factory/sugar/floor spine; old code is copied only when it fits the new law.

**Tech Stack:** Python 3.10+ package code in `implementations/python/sugar-lift-py-tests`, `pytest`, existing Sugar JSON-RPC lifter protocol, existing source memento/source oracle machinery, and the repo's `sugar lift --report --visual` path.

## Global Constraints

- Read `AGENTS.md` and `docs/sugar-invariants.md` before implementation.
- IDD comes first: create the red instrument before broad migration.
- The machine self-instruments. The instrument runs the actual numpy and pandas lift path in audit-only mode, catches construction panics, groups them by target/role/owner/fix, and reports current `R`.
- `R` is the observed panic vector for numpy and pandas: `numpy_sugar_panics`, `numpy_floor_panics`, `pandas_sugar_panics`, `pandas_floor_panics`, and `unexpected_panics`. Scaffold-readiness checks are diagnostics, not `R`.
- The Python kit is written in Python and owns all Pythonisms. The Rust CLI is written in Rust and must stay language-blind.
- The new factory is first. All selected Python AST traffic goes through it immediately. With no sugar it screams `write more Sugar for this AST`; after sugar claims a shape, missing completed values, floor operations, or ProofIR emitters scream `write more Floor for this AST` or `write more Floor for this construction`.
- The Python kit is done only when a user literally runs `sugar lift` on numpy and pandas projects with no config/manifest, Python claims the project through discovery, and Rust still only transports ProofIR, plans solver work, recomputes witnesses, and verifies.
- Vendor unit tests emit callsite facts. Callsite facts trigger digs for their constraint universes. The Python kit walks the dug AST source, constructs shape-owned sugar post-order (deepest/last child first, then the parent with typed child bodies), calls `desugar` on the already-built chain, emits ProofIR from completed values/floors, and reaches only `Complete(FloorValue)`, `Incomplete(Effect)`, or a loud construction-gap panic.
- Temporal rewriting is upstream completed-value production: by the time a sugar operates on a source name or fluent receiver, the current program-point meaning must be a semantic value such as `TermValue`, `ArrayLiteral`, or `BuilderState`, not raw AST. Unknown temporal receiver mutation is a real effect or a loud floor gap; it never emits fake predicates.
- Constraints are discovered by Python source shape during that AST walk, not by framework adapter. The Python catalog asks for a role; shape-owned sugars volunteer, build typed child bodies into completed values, and emit universe predicates, preconditions, effects, and ProofIR.
- The Python kit emits the ProofIR for Python facts and universes. The Rust CLI must not lower Python floors into ProofIR.
- Do not copy `lift_pydantic_model` as the architecture. Pydantic-style facts must enter as source-shape sugars such as `Field(..., ge=1)` call keywords or `Annotated[...]` subscript metadata after Python name resolution.
- Construction has exactly three exits: `Complete(FloorValue)` because all work was done, `Incomplete(Effect)` because the source has an actual effect, or panic because construction is missing sugar/floor support.
- Every Python builtin that contributes semantics is a sugar. It must have a `SugarClaim`, typed floor/effect behavior, factory audit rows, and SAT/UNSAT z3 proof fixtures.
- Every sugar, including builtin sugars and sugars that copy old helper logic, must ship SAT and UNSAT fixtures showing the exact Python source lifted by `sugar lift` and proven through z3.
- Normal mode panics on the first construction gap. Audit-only mode catches construction-gap panics, records all gaps with owner/blame/observed/fix metadata, and does not emit semantic outcomes for those gaps.
- A factory miss or pure-but-untranslated shape is a construction gap, not an `Effect`.
- A floor miss or missing floor operation is a construction gap, not a generic dict, `None`, legacy fallback, or `Effect`.
- All floor operations go through sugar-owned operation objects and duck-typed completed values. `Protocol`s may document capabilities, but runtime dispatch is an explicit method call such as `receiver.map_with(MapOperation(...), ctx)`. Missing methods are floor construction gaps. Sugars must not inspect completed-value internals by shape.
- Sugar construction gaps must raise a loud panic-style exception whose message starts with `write more Sugar for this AST`.
- AST-warranted floor construction gaps must raise a loud panic-style exception whose message starts with `write more Floor for this AST`.
- Lower-level floor construction gaps must start with `write more Floor for this construction`.
- Every gap message must name the owner, blame site, requested role or floor, observed AST/value, and a concrete fix such as a sugar module or floor operation to add.
- Gap helpers are typed `NoReturn` and raise directly; they are not exception factories and not `Outcome` constructors.
- Every lawful non-panicking reduction returns exactly `Complete(FloorValue)` or `Incomplete(Effect)`.
- No code may model construction gaps as return values, `None`, `Unresolved`, empty predicate lists, generic dicts, or catch-and-continue exceptions.
- Do not keep old Python tests alive as a second contract. Migrate tests wholesale into new factory/sugar/floor fixtures, copying only useful source snippets, expected facts, or source-oracle evidence.
- A parent sugar must not turn a child effect into a different effect.
- A parent sugar is constructed with typed child bodies; it must not hold raw child AST and reopen the factory during `desugar`.
- Raw AST may be kept for provenance and source mementos, but not as a deferred semantic child body.
- Reports must be reproducible from proof/memento/source-oracle resolution, not side-door source text.
- Config and manifests are overrides. Component discovery is the default path.
- The new kit RPC entrypoint is protocol plumbing only. Do not name or design the architecture around the old transport file.
- Build lots of small, well organized type hierarchies with dumb classes. A class mostly carries typed fields plus one tiny operation.
- One file per class. A sugar class, completed-value/floor class, effect class, operation class, factory audit class, proof fixture class, report class, or source-oracle class gets its own module. Package `__init__.py` files may re-export names, and small enums/constants may live with their sole owner.

---

## File Structure

- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd/`
  - `lift_target.py`, `command_result.py`, `panic_record.py`, `panic_vector.py`, `panic_audit_report.py`, `extract_panic_records.py`, `collect_panic_audit.py`, `render_panic_audit.py`, `cli.py`: self-instrumenting numpy/pandas panic audit classes and report functions split by concept.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/gaps/`
  - `construction_gap_info.py`, `construction_gap_panic.py`, `sugar_construction_gap.py`, `floor_construction_gap.py`: structured panic metadata and loud exception classes.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/`
  - `floor_value.py`, `floor_mismatch.py`, `floor_gap.py`, `term_value.py`, `predicate_value.py`, `assertion_fact.py`, `callsite_fact.py`, `body_universe.py`, `precondition_value.py`, `literal_value.py`, `array_literal.py`, `builder_state.py`, `tuple_components.py`, `class_shape.py`, `runtime_value.py`, `support_value.py`: one dumb completed-value/floor class or helper per file.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/operations/`
  - `map_operation.py`, `add_operation.py`, `materialize_operation.py`, `perform_operation.py`, `supports_map.py`, `supports_add.py`, `supports_materialize.py`: one operation object, dispatch helper, or optional capability protocol per file.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/context/`
  - `factory_build_context.py`, `reduce_context.py`: explicit build/reduce context objects.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/temporal/`
  - `temporal_context.py`, `temporal_binding.py`, `temporal_rewrite_step.py`: current program-point floor bindings and replay records.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar_body/`
  - `sugar_body.py`: typed child-body carrier used by parent sugars.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect/`
  - `effect.py`, `effect_kind.py`: typed effects and effect disposition names.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/outcome/`
  - `complete.py`, `incomplete.py`, `complete_floor.py`, `outcome.py`: terminal reduction states and readers.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/claim/`
  - `sugar_role.py`, `sugar.py`, `sugar_claim.py`, `sugar_candidate.py`: claim metadata and recognizer protocols.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/factory/`
  - `build.py`, `matching_candidates.py`, `sugar_gap.py`, `blame_site.py`, `audit_row.py`, `audit_summary.py`: dispatch, candidate selection, and audit accounting.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/audit_only/`
  - `audit_only_gap.py`, `collect_construction_gaps.py`: gap inventory without semantic outcomes.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/proof_fixture/`
  - `sugar_proof_pair.py`, `validate_sugar_proof_pairs.py`: per-sugar SAT/UNSAT proof fixture metadata and validation helpers.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/proofir_emit/`
  - `contract_emitter.py`, `formula_emitter.py`: Python-owned ProofIR `ContractDecl`/formula emission from completed floors.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/kit_rpc/`
  - `component_plan_result.py`, `server.py`, `source_oracle_routes.py`, `report_payload.py`: JSON-RPC kit protocol, component roll call, source oracle routes, and report payload plumbing only.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/constraint_flow/`
  - `constraint_dig_request.py`, `callsite_constraint_fact.py`, `constraint_universe.py`, `dig_constraint_universe.py`: Python-owned constraint discovery -> fact -> dig -> universe handoff.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/__init__.py`
  - Package marker and registry aggregation point.
- Create `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/translate_universe/`
  - `translate_universe_sugar.py`, `recognize_translate_universe.py`, `translate_universe_claim.py`: first native sugar port for translate/rstrip body-universe logic; copy old code only where it obeys the new law.
- Retire or bypass old transport semantics after the `kit_rpc/` package owns the JSON-RPC path.
- Modify `implementations/python/sugar-lift-py-tests/pyproject.toml`
  - Add a console script for the IDD instrument if needed.
- Create `.sugar/components/python-test-assertions/manifest.toml`
  - Registers Python component discovery from the repo root.
- Create tests:
  - `implementations/python/sugar-lift-py-tests/tests/test_numpy_pandas_panic_audit.py`
  - `implementations/python/sugar-lift-py-tests/tests/test_floor_kernel.py`
  - `implementations/python/sugar-lift-py-tests/tests/test_factory_kernel.py`
  - `implementations/python/sugar-lift-py-tests/tests/test_audit_only_gaps.py`
  - `implementations/python/sugar-lift-py-tests/tests/test_sugar_proof_obligations.py`
  - `implementations/python/sugar-lift-py-tests/tests/test_constraint_flow.py`
  - `implementations/python/sugar-lift-py-tests/tests/test_python_component_plan.py`
  - `implementations/python/sugar-lift-py-tests/tests/test_translate_universe_sugar.py`

## Task 1: Build The Self-Instrumenting Panic Audit First

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd/__init__.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd/lift_target.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd/command_result.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd/panic_record.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd/panic_vector.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd/panic_audit_report.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd/extract_panic_records.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd/collect_panic_audit.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd/render_panic_audit.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd/cli.py`
- Create: `implementations/python/sugar-lift-py-tests/tests/test_numpy_pandas_panic_audit.py`
- Modify: `implementations/python/sugar-lift-py-tests/pyproject.toml`

**Interfaces:**
- Produces: `LiftTarget`, `CommandResult`, `PanicRecord`, `PanicVector`, `PanicAuditReport`, `collect_panic_audit(root: Path, run_command: RunCommand | None = None) -> PanicAuditReport`, `render_text(report: PanicAuditReport) -> str`, `main(argv: list[str] | None = None) -> int`
- Consumes: the actual `sugar lift` command path. In tests the command runner is injected so the instrument proves the shape of `R` before the real audit-only flag exists.

- [ ] **Step 1: Write the failing self-instrumentation tests**

Add this test file:

```python
from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.idd import (
    CommandResult,
    collect_panic_audit,
    main,
    render_text,
)


ROOT = Path(__file__).resolve().parents[4]


def test_numpy_pandas_r_is_measured_from_observed_panics():
    calls: list[list[str]] = []

    def fake_runner(command: list[str], cwd: Path) -> CommandResult:
        calls.append(command)
        target = command[-1]
        if target.endswith("examples/numpy-showcase"):
            return CommandResult(
                returncode=1,
                stdout=(
                    "write more Sugar for this AST: owner=factory blame=numpy.py:1:0 "
                    "observed=Call requested=Term fix=create sugar_lift_py_tests.sugar.call.call_sugar\n"
                    "write more Floor for this AST: owner=numpy.reshape blame=numpy.py:2:4 "
                    "observed=Call requested=SequenceFloor fix=add SequenceFloor visitor for numpy.reshape\n"
                ),
                stderr="",
            )
        if target.endswith("examples/pandas-showcase"):
            return CommandResult(
                returncode=1,
                stdout=(
                    "write more Floor for this construction: owner=pandas.frame.sum blame=pandas.py:3:8 "
                    "observed=DataFrame requested=BodyUniverseFloor fix=add BodyUniverseFloor for pandas sum\n"
                ),
                stderr="",
            )
        raise AssertionError(target)

    report = collect_panic_audit(ROOT, run_command=fake_runner)

    assert report.r.values == {
        "numpy_sugar_panics": 1,
        "numpy_floor_panics": 1,
        "pandas_sugar_panics": 0,
        "pandas_floor_panics": 1,
        "unexpected_panics": 0,
    }
    assert len(report.records) == 3
    assert all("--audit-only" in command for command in calls)
    assert all(command[:2] == ["sugar", "lift"] for command in calls)

    text = render_text(report)
    assert "python numpy/pandas lift panic audit" in text
    assert "R:" in text
    assert "write more Sugar for this AST" in text
    assert "write more Floor for this AST" in text
    assert "fix=create sugar_lift_py_tests.sugar.call.call_sugar" in text


def test_cli_exits_red_until_numpy_pandas_have_zero_panics(monkeypatch, capsys):
    from sugar_lift_py_tests.idd import cli

    def fake_collect(root: Path):
        return collect_panic_audit(
            root,
            run_command=lambda command, cwd: CommandResult(
                returncode=1,
                stdout=(
                    "write more Sugar for this AST: owner=factory blame=x.py:1:0 "
                    "observed=Call requested=Term fix=create sugar_lift_py_tests.sugar.call.call_sugar\n"
                ),
                stderr="",
            ),
        )

    monkeypatch.setattr(cli, "collect_panic_audit", fake_collect)

    exit_code = main(["--root", str(ROOT)])
    stdout = capsys.readouterr().out
    assert exit_code == 1
    assert "numpy_sugar_panics" in stdout
    assert "fix:" in stdout


def test_failed_lift_without_gap_records_counts_as_unexpected():
    def failing_runner(command: list[str], cwd: Path) -> CommandResult:
        return CommandResult(returncode=2, stdout="", stderr="error: unknown option --audit-only\n")

    report = collect_panic_audit(ROOT, run_command=failing_runner)

    assert report.r.values["unexpected_panics"] == 2
    assert not report.is_zero
    assert all(record.kind == "unexpected" for record in report.records)
```

- [ ] **Step 2: Run the focused test to see it fail**

Run:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_numpy_pandas_panic_audit.py
```

Expected: `ModuleNotFoundError: No module named 'sugar_lift_py_tests.idd'`.

- [ ] **Step 3: Add the IDD package exports**

Create `idd/__init__.py`:

```python
from __future__ import annotations

from .cli import main
from .collect_panic_audit import collect_panic_audit
from .command_result import CommandResult
from .lift_target import LiftTarget
from .panic_audit_report import PanicAuditReport
from .panic_record import PanicRecord
from .panic_vector import PanicVector
from .render_panic_audit import render_text

__all__ = [
    "CommandResult",
    "LiftTarget",
    "PanicAuditReport",
    "PanicRecord",
    "PanicVector",
    "collect_panic_audit",
    "main",
    "render_text",
]
```

- [ ] **Step 4: Add one dumb class per file**

Create `idd/lift_target.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LiftTarget:
    name: str
    path: Path
```

Create `idd/command_result.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
```

Create `idd/panic_record.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PanicKind = Literal["sugar", "floor", "unexpected"]


@dataclass(frozen=True)
class PanicRecord:
    target: str
    kind: PanicKind
    owner: str
    blame: str
    observed: str
    requested: str
    fix: str
    message: str

    def to_json(self) -> dict[str, str]:
        return {
            "target": self.target,
            "kind": self.kind,
            "owner": self.owner,
            "blame": self.blame,
            "observed": self.observed,
            "requested": self.requested,
            "fix": self.fix,
            "message": self.message,
        }
```

Create `idd/panic_vector.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from .panic_record import PanicRecord


PANIC_AXES = (
    "numpy_sugar_panics",
    "numpy_floor_panics",
    "pandas_sugar_panics",
    "pandas_floor_panics",
    "unexpected_panics",
)


@dataclass(frozen=True)
class PanicVector:
    values: dict[str, int]

    @classmethod
    def from_records(cls, records: list[PanicRecord]) -> "PanicVector":
        values = {axis: 0 for axis in PANIC_AXES}
        for record in records:
            if record.kind == "unexpected":
                values["unexpected_panics"] += 1
                continue
            if record.target not in {"numpy", "pandas"}:
                values["unexpected_panics"] += 1
                continue
            values[f"{record.target}_{record.kind}_panics"] += 1
        return cls(values)

    @property
    def is_zero(self) -> bool:
        return all(value == 0 for value in self.values.values())
```

Create `idd/panic_audit_report.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

from .lift_target import LiftTarget
from .panic_record import PanicRecord
from .panic_vector import PanicVector


@dataclass(frozen=True)
class PanicAuditReport:
    targets: tuple[LiftTarget, ...]
    records: list[PanicRecord]
    diagnostics: list[str] = field(default_factory=list)

    @property
    def r(self) -> PanicVector:
        return PanicVector.from_records(self.records)

    @property
    def is_zero(self) -> bool:
        return self.r.is_zero and not self.diagnostics

    def to_json(self) -> dict:
        return {
            "kind": "python-numpy-pandas-panic-audit",
            "r": dict(self.r.values),
            "diagnostics": list(self.diagnostics),
            "records": [record.to_json() for record in self.records],
            "targets": [{"name": target.name, "path": str(target.path)} for target in self.targets],
        }
```

- [ ] **Step 5: Parse the machine's panic output**

Create `idd/extract_panic_records.py`:

```python
from __future__ import annotations

import re

from .lift_target import LiftTarget
from .panic_record import PanicRecord


_FIELD = re.compile(r"(owner|blame|observed|requested|fix)=([^=]+?)(?=\s(?:owner|blame|observed|requested|fix)=|$)")


def extract_panic_records(target: LiftTarget, stdout: str, stderr: str) -> list[PanicRecord]:
    records: list[PanicRecord] = []
    for line in (stdout + "\n" + stderr).splitlines():
        kind = _panic_kind(line)
        if kind is None:
            continue
        fields = {key: value.strip() for key, value in _FIELD.findall(line)}
        records.append(
            PanicRecord(
                target=target.name,
                kind=kind,
                owner=fields.get("owner", "unknown"),
                blame=fields.get("blame", "unknown"),
                observed=fields.get("observed", "unknown"),
                requested=fields.get("requested", "unknown"),
                fix=fields.get("fix", "write the missing sugar or floor"),
                message=line,
            )
        )
    return records


def _panic_kind(line: str):
    if line.startswith("write more Sugar for this AST"):
        return "sugar"
    if line.startswith("write more Floor for this AST") or line.startswith("write more Floor for this construction"):
        return "floor"
    if "panicked" in line and "write more " not in line:
        return "unexpected"
    return None
```

- [ ] **Step 6: Collect `R` by running numpy and pandas lifts**

Create `idd/collect_panic_audit.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from .command_result import CommandResult
from .extract_panic_records import extract_panic_records
from .lift_target import LiftTarget
from .panic_audit_report import PanicAuditReport
from .panic_record import PanicRecord


RunCommand = Callable[[list[str], Path], CommandResult]


def collect_panic_audit(root: Path, run_command: RunCommand | None = None) -> PanicAuditReport:
    root = root.resolve()
    runner = run_command or _run_command
    targets = (
        LiftTarget("numpy", root / "examples/numpy-showcase"),
        LiftTarget("pandas", root / "examples/pandas-showcase"),
    )
    diagnostics: list[str] = []
    records = []
    for target in targets:
        if not target.path.exists():
            message = f"missing target: {target.path}"
            diagnostics.append(message)
            records.append(
                PanicRecord(
                    target=target.name,
                    kind="unexpected",
                    owner="idd.collect_panic_audit",
                    blame=str(target.path),
                    observed="missing-target",
                    requested="audit target",
                    fix="create the numpy/pandas target or point the audit at the real target",
                    message=message,
                )
            )
            continue
        command = ["sugar", "lift", "--report", "--visual", "--audit-only", str(target.path)]
        result = runner(command, root)
        target_records = extract_panic_records(target, result.stdout, result.stderr)
        records.extend(target_records)
        if result.returncode != 0 and not target_records:
            message = f"{target.name} lift exited {result.returncode} without construction panic records"
            diagnostics.append(message)
            records.append(
                PanicRecord(
                    target=target.name,
                    kind="unexpected",
                    owner="idd.collect_panic_audit",
                    blame=str(target.path),
                    observed=f"exit={result.returncode}",
                    requested="construction-panic-records",
                    fix="make audit-only emit structured construction panic records",
                    message=message,
                )
            )
    return PanicAuditReport(targets=targets, records=records, diagnostics=diagnostics)


def _run_command(command: list[str], cwd: Path) -> CommandResult:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)
```

- [ ] **Step 7: Render the report**

Create `idd/render_panic_audit.py`:

```python
from __future__ import annotations

from .panic_audit_report import PanicAuditReport


def render_text(report: PanicAuditReport) -> str:
    lines = ["python numpy/pandas lift panic audit", "R:"]
    for axis, value in report.r.values.items():
        lines.append(f"  {axis}: {value}")
    if report.diagnostics:
        lines.append("diagnostics:")
        for diagnostic in report.diagnostics:
            lines.append(f"  - {diagnostic}")
    if report.records:
        lines.append("construction panics:")
        for record in report.records:
            lines.append(f"  - {record.target} {record.kind}: {record.message}")
            lines.append(f"    fix: {record.fix}")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 8: Add the CLI**

Create `idd/cli.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .collect_panic_audit import collect_panic_audit
from .render_panic_audit import render_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = collect_panic_audit(Path(args.root))
    if args.json:
        print(json.dumps(report.to_json(), sort_keys=True, indent=2))
    else:
        print(render_text(report), end="")
    return 0 if report.is_zero else 1
```

- [ ] **Step 9: Add the console entry**

In `pyproject.toml`, under `[project.scripts]`, add:

```toml
sugar-python-factory-floor-idd = "sugar_lift_py_tests.idd.cli:main"
```

- [ ] **Step 10: Verify the instrument test passes and the instrument itself is red**

Run:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_numpy_pandas_panic_audit.py
```

Expected: `3 passed`.

Run:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src python -m sugar_lift_py_tests.idd.cli --root . --json
```

Expected: exit code `1` until the numpy and pandas lift targets produce zero observed construction panics.

- [ ] **Step 11: Commit**

```bash
git add implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd implementations/python/sugar-lift-py-tests/tests/test_numpy_pandas_panic_audit.py implementations/python/sugar-lift-py-tests/pyproject.toml
git commit -m "Add Python numpy pandas panic audit"
```

## Task 2: Add The Construction-Law Kernel With Completed Values

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/gaps/`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/operations/`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect/`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/outcome/`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_floor_kernel.py`

**Interfaces:**
- Consumes: `idd.collect_panic_audit`
- Produces: `ConstructionGapInfo`, `ConstructionGapPanic`, `FloorValue`, `TermValue`, `PredicateValue`, `BodyUniverse`, `PreconditionValue`, `ArrayLiteral`, `BuilderState`, `RuntimeValue`, `Effect`, `Complete`, `Incomplete`, `complete_value`, `MapOperation`, `AddOperation`, `MaterializeOperation`, `perform_operation`, `SugarConstructionGap`, `FloorConstructionGap`, `FloorMismatch`

- [ ] **Step 1: Write the failing kernel tests**

Create `test_floor_kernel.py`:

```python
from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect import Effect
from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    BodyUniverse,
    FloorConstructionGap,
    RuntimeValue,
    TermValue,
    floor_gap,
)
from sugar_lift_py_tests.operations import AddOperation, MapOperation, MaterializeOperation, perform_operation
from sugar_lift_py_tests.outcome import Complete, Incomplete, complete_value


def test_complete_contains_completed_value_not_effect_or_gap():
    term = TermValue(term={"kind": "var", "name": "x"})
    outcome = Complete(term)

    assert complete_value(outcome, owner="python-test") is term


def test_incomplete_is_only_typed_effect():
    effect = Effect(kind="RuntimeDispatch", boundary={"file": "x.py", "line": 3}, reason="runtime dispatch")
    outcome = Incomplete(effect)

    assert outcome.effect is effect


def test_complete_value_refuses_to_read_incomplete_effect():
    effect = Effect(kind="RuntimeValue", boundary={"file": "x.py", "line": 3}, reason="unknown runtime value")

    with pytest.raises(RuntimeError, match="map receiver cannot read completed value from incomplete effect"):
        complete_value(Incomplete(effect), owner="map receiver")


def test_array_literal_performs_operation_by_duck_typed_method():
    receiver = ArrayLiteral(items=(TermValue.literal(1), TermValue.literal(2), TermValue.literal(3)))
    operation = MapOperation(
        mapper=lambda item: TermValue.literal(item.literal_value + 2),
        owner="MapSugar",
        blame="x.py:1:0",
    )

    outcome = perform_operation(
        owner="MapSugar",
        blame="x.py:1:0",
        receiver=receiver,
        method_name="map_with",
        operation=operation,
        ctx=None,
    )

    mapped = complete_value(outcome, owner="map result")
    assert isinstance(mapped, ArrayLiteral)
    assert [item.literal_value for item in mapped.items] == [3, 4, 5]


def test_missing_operation_is_a_loud_floor_gap():
    receiver = RuntimeValue(reason="opaque iterator")

    with pytest.raises(FloorConstructionGap) as exc:
        perform_operation(
            owner="MapSugar",
            blame="x.py:1:0",
            receiver=receiver,
            method_name="map_with",
            operation=MapOperation(mapper=lambda item: item, owner="MapSugar", blame="x.py:1:0"),
            ctx=None,
        )

    message = str(exc.value)
    assert message.startswith("write more Floor for this construction")
    assert "owner=MapSugar" in message
    assert "observed=RuntimeValue" in message
    assert "requested=map_with" in message
    assert "fix=add map_with to RuntimeValue or emit a real effect" in message


def test_floor_gap_names_ast_or_construction_fix():
    with pytest.raises(FloorConstructionGap) as exc:
        floor_gap(
            owner="python-test",
            blame="x.py:4:2",
            ast_kind="ListComp",
            requested="BodyUniverse",
            fix="add BodyUniverse construction for ListComp",
        )

    message = str(exc.value)
    assert message.startswith("write more Floor for this AST")
    assert "owner=python-test" in message
    assert "blame=x.py:4:2" in message
    assert "observed=ListComp" in message
    assert "requested=BodyUniverse" in message
    assert "fix=add BodyUniverse construction for ListComp" in message
    assert exc.value.info.owner == "python-test"
    assert exc.value.info.fix == "add BodyUniverse construction for ListComp"
```

- [ ] **Step 2: Run the focused test to see it fail**

Run:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_floor_kernel.py
```

Expected: import failure for `sugar_lift_py_tests.floor` or
`sugar_lift_py_tests.operations`.

- [ ] **Step 3: Implement structured construction-gap metadata**

Add the `gaps/` package. The snippet below shows the API shape; implement it as
one class per file: `construction_gap_info.py`, `construction_gap_panic.py`,
`floor_construction_gap.py`, and `sugar_construction_gap.py`, then re-export
from `gaps/__init__.py`.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


GapKind = Literal["sugar", "floor"]


@dataclass(frozen=True)
class ConstructionGapInfo:
    kind: GapKind
    owner: str
    blame: str
    observed: str
    requested: str
    fix: str

    def to_json(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "owner": self.owner,
            "blame": self.blame,
            "observed": self.observed,
            "requested": self.requested,
            "fix": self.fix,
        }


class ConstructionGapPanic(RuntimeError):
    def __init__(self, prefix: str, info: ConstructionGapInfo) -> None:
        self.info = info
        super().__init__(
            f"{prefix}: owner={info.owner} blame={info.blame} "
            f"observed={info.observed} requested={info.requested} fix={info.fix}"
        )
```

- [ ] **Step 4: Implement completed-value floors**

Add the `floor/` package. Implement every class/helper in its own file, then
re-export from `floor/__init__.py`.

The important shape is:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NoReturn

from sugar_lift_py_tests.gaps import ConstructionGapInfo, ConstructionGapPanic


class FloorMismatch(RuntimeError):
    pass


class FloorConstructionGap(ConstructionGapPanic):
    pass


class FloorValue:
    pass


@dataclass(frozen=True)
class TermValue(FloorValue):
    term: dict[str, Any]
    literal_value: Any | None = None

    @staticmethod
    def literal(value: Any) -> "TermValue":
        return TermValue(term={"kind": "literal", "value": value}, literal_value=value)


@dataclass(frozen=True)
class PredicateValue(FloorValue):
    formula: dict[str, Any]


@dataclass(frozen=True)
class BodyUniverse(FloorValue):
    predicates: list[dict[str, Any]]
    source_memento: dict[str, Any]


@dataclass(frozen=True)
class PreconditionValue(FloorValue):
    formula: dict[str, Any]
    source_memento: dict[str, Any] | None = None


@dataclass(frozen=True)
class RuntimeValue(FloorValue):
    reason: str


@dataclass(frozen=True)
class ArrayLiteral(FloorValue):
    items: tuple[FloorValue, ...]

    def map_with(self, operation: Any, ctx: Any) -> Any:
        return operation.map_array(self, ctx)

    def add_with(self, operation: Any, ctx: Any) -> Any:
        return operation.add_array(self, ctx)

    def materialize_with(self, operation: Any, ctx: Any) -> Any:
        return operation.materialize_array(self, ctx)


@dataclass(frozen=True)
class BuilderState(FloorValue):
    current: FloorValue

    def map_with(self, operation: Any, ctx: Any) -> Any:
        return operation.map_builder(self, ctx)

    def add_with(self, operation: Any, ctx: Any) -> Any:
        return operation.add_builder(self, ctx)

    def materialize_with(self, operation: Any, ctx: Any) -> Any:
        return operation.materialize_builder(self, ctx)


@dataclass(frozen=True)
class TupleComponents(FloorValue):
    parts: tuple[FloorValue, ...]


@dataclass(frozen=True)
class ClassShape(FloorValue):
    shape: dict[str, Any]


@dataclass(frozen=True)
class SupportValue(FloorValue):
    reason: str


def floor_gap(
    *,
    owner: str,
    blame: str,
    requested: str,
    fix: str,
    ast_kind: str | None = None,
    observed: str | None = None,
) -> NoReturn:
    if ast_kind is not None:
        raise FloorConstructionGap(
            "write more Floor for this AST",
            ConstructionGapInfo(
                kind="floor",
                owner=owner,
                blame=blame,
                observed=ast_kind,
                requested=requested,
                fix=fix,
            ),
        )
    if observed is None:
        raise ValueError("floor_gap requires ast_kind or observed construction context")
    raise FloorConstructionGap(
        "write more Floor for this construction",
        ConstructionGapInfo(
            kind="floor",
            owner=owner,
            blame=blame,
            observed=observed,
            requested=requested,
            fix=fix,
        ),
    )
```

- [ ] **Step 5: Implement sugar-owned operation objects and dispatch**

Add the `operations/` package. Keep one operation/Protocol/helper per file.
`Protocol`s are documentation/static shape only; the runtime gate is the
shared dispatcher.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, NoReturn, Protocol

from sugar_lift_py_tests.floor import ArrayLiteral, BuilderState, FloorValue, TermValue, floor_gap
from sugar_lift_py_tests.outcome import Complete, Outcome


class SupportsMap(Protocol):
    def map_with(self, operation: "MapOperation", ctx: Any) -> Outcome: ...


@dataclass(frozen=True)
class MapOperation:
    mapper: Callable[[FloorValue], FloorValue]
    owner: str
    blame: str

    def map_array(self, receiver: ArrayLiteral, ctx: Any) -> Outcome:
        return Complete(ArrayLiteral(tuple(self.mapper(item) for item in receiver.items)))

    def map_builder(self, receiver: BuilderState, ctx: Any) -> Outcome:
        return Complete(BuilderState(complete_value(receiver.current.map_with(self, ctx), owner=self.owner)))


@dataclass(frozen=True)
class AddOperation:
    operand: TermValue
    owner: str
    blame: str

    def add_array(self, receiver: ArrayLiteral, ctx: Any) -> Outcome:
        return Complete(
            ArrayLiteral(
                tuple(
                    TermValue.literal(item.literal_value + self.operand.literal_value)
                    for item in receiver.items
                )
            )
        )

    def add_builder(self, receiver: BuilderState, ctx: Any) -> Outcome:
        return Complete(BuilderState(complete_value(receiver.current.add_with(self, ctx), owner=self.owner)))


@dataclass(frozen=True)
class MaterializeOperation:
    owner: str
    blame: str

    def materialize_array(self, receiver: ArrayLiteral, ctx: Any) -> Outcome:
        return Complete(receiver)

    def materialize_builder(self, receiver: BuilderState, ctx: Any) -> Outcome:
        return complete_value(receiver.current.materialize_with(self, ctx), owner=self.owner)


def perform_operation(
    *,
    owner: str,
    blame: str,
    receiver: FloorValue,
    method_name: str,
    operation: object,
    ctx: Any,
) -> Outcome:
    method = getattr(receiver, method_name, None)
    if method is None:
        floor_gap(
            owner=owner,
            blame=blame,
            observed=type(receiver).__name__,
            requested=method_name,
            fix=f"add {method_name} to {type(receiver).__name__} or emit a real effect",
        )
    return method(operation, ctx)
```

- [ ] **Step 6: Implement typed effects**

Add the `effect/` package. Keep `Effect` in `effect/effect.py` and the allowed
kind set in `effect/effect_kind.py`.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


EARNED_EFFECT_KINDS = {
    "RuntimeValue",
    "RuntimeDispatch",
    "Mutation",
    "DynamicAttribute",
    "Io",
    "Environment",
    "Nondeterminism",
    "ExceptionFlow",
    "ContextManager",
    "GeneratorOrCoroutine",
    "ImportRuntime",
    "OpenClassShape",
}


@dataclass(frozen=True)
class Effect:
    kind: str
    boundary: dict[str, Any]
    reason: str

    def __post_init__(self) -> None:
        if self.kind not in EARNED_EFFECT_KINDS:
            raise ValueError(
                f"unknown effect kind {self.kind!r}; pure unsupported shapes are construction gaps"
            )
        if not self.reason:
            raise ValueError("effect reason must be non-empty")
```

- [ ] **Step 7: Implement total outcomes**

Add the `outcome/` package. Keep `Complete`, `Incomplete`, and `complete_value`
in separate files and re-export them from `outcome/__init__.py`.

```python
from __future__ import annotations

from dataclasses import dataclass

from .effect import Effect
from .floor import FloorValue


@dataclass(frozen=True)
class Complete:
    value: FloorValue


@dataclass(frozen=True)
class Incomplete:
    effect: Effect


Outcome = Complete | Incomplete


def complete_value(outcome: Outcome, *, owner: str) -> FloorValue:
    if isinstance(outcome, Incomplete):
        raise RuntimeError(
            f"{owner} cannot read completed value from incomplete effect: {outcome.effect.reason}"
        )
    return outcome.value
```

- [ ] **Step 8: Run the panic audit to confirm the kernel does not redefine `R`**

Run the instrument again and verify it still reports only numpy/pandas panic
axes. Kernel module creation may remove diagnostics later, but it must not add
scaffold counters to `R`.

Command:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src python -m sugar_lift_py_tests.idd.cli --root . --json
```

Expected: exit code `1` until numpy and pandas lift with zero construction panics. The JSON `r` object contains only `numpy_sugar_panics`, `numpy_floor_panics`, `pandas_sugar_panics`, `pandas_floor_panics`, and `unexpected_panics`.

- [ ] **Step 9: Run focused tests**

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_floor_kernel.py implementations/python/sugar-lift-py-tests/tests/test_numpy_pandas_panic_audit.py
```

Expected: all tests pass. The standalone IDD command remains red until stable zero.

- [ ] **Step 10: Commit**

```bash
git add implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/gaps implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/operations implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/effect implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/outcome implementations/python/sugar-lift-py-tests/tests/test_floor_kernel.py
git commit -m "Add Python completed-value construction law"
```

## Task 3: Add Temporal Context And Forward Rewrite Kernel

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/context/`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/temporal/`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar_body/`
- Extend: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/factory/`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_temporal_forward_rewrite.py`

**Interfaces:**
- Consumes: `FloorValue`, `TermValue`, `ArrayLiteral`, `BuilderState`, `RuntimeValue`, `Complete`, `Incomplete`, `complete_value`, `MapOperation`, `AddOperation`, `MaterializeOperation`, `perform_operation`
- Produces: `FactoryBuildContext`, `ReduceContext`, `TemporalContext`, `TemporalBinding`, `TemporalRewriteStep`, `SugarBody`, and the first temporal red/green instrument.

- [ ] **Step 1: Write the fluent-builder red instrument**

Create a focused test around exact Python source:

```python
n = 10
n += 1
out = Builder([1, 2, 3]).map(lambda x: x + 2).add(n).to_list()
assert out == [14, 15, 16]
```

The test must assert the construction/reduction law, not just final numbers:

- factory construction is inside-out: `ListLiteralSugar -> BuilderCtorSugar -> LambdaSugar/BinOpSugar -> MapSugar -> NameSugar(n) -> AddSugar -> ToListSugar`;
- every parent sugar is constructed with `SugarBody` children;
- calling `desugar` on the outer `ToListSugar` rewrites forward through current completed values;
- `NameSugar("n")` reads the current temporal value `TermValue(11)`, never raw `ast.Name`;
- `.map(...)` calls `perform_operation(..., method_name="map_with", operation=MapOperation(...))`;
- `.add(n)` consumes `TermValue(11)` and calls `perform_operation(..., method_name="add_with", operation=AddOperation(...))`;
- `.to_list()` calls `perform_operation(..., method_name="materialize_with", operation=MaterializeOperation(...))`;
- the final ProofIR/FOL-facing value is timeless: `len(out)=3`, `out[0]=14`, `out[1]=15`, `out[2]=16`;
- an unknown fluent receiver mutation emits a real temporal effect or a loud floor gap, never fake predicates.

- [ ] **Step 2: Add explicit context objects**

Add one small class per file:

- `FactoryBuildContext`: source oracle handle, temporal context, expected role, name resolver, audit sink.
- `ReduceContext`: temporal context at the reduction point, source oracle, proof/report sinks, and factory audit sink.
- `TemporalContext`: immutable/forkable current bindings. It answers “what completed value does this name/receiver mean at this source point?”
- `TemporalRewriteStep`: record of a replayed assignment, fluent receiver update, loop replay, or red temporal boundary.

The context API must make temporal rewriting upstream of sugar/completed-value
consumption:

```python
ctx.temporal.value_for("n")       # -> TermValue(11)
ctx.temporal.receiver_for("out")  # -> current receiver value, if bound
ctx.temporal.bind_value("x", value)
ctx.temporal.apply_step(step)
```

- [ ] **Step 3: Add `SugarBody` as the post-order carrier**

`SugarBody` is the Python equivalent of Rust's typed child body. It wraps an
already-built child sugar and the requested semantic role. Parent sugars store
`SugarBody`, not raw child AST, except for provenance/source mementos.

Reduction shape:

```python
outcome = body.reduce(ctx)
receiver = complete_value(outcome, owner="MapSugar receiver")
return perform_operation(
    owner="MapSugar",
    blame=self.blame,
    receiver=receiver,
    method_name="map_with",
    operation=MapOperation(mapper=self.mapper, owner="MapSugar", blame=self.blame),
    ctx=ctx,
)
```

A missing operation is a floor construction panic, not a silent `None`.

- [ ] **Step 4: State the FOL handoff invariant**

After temporal rewriting and operation dispatch, the solver-facing output has no
program time left. Time has become one of:

- stable completed terms, such as `TermValue(11)`;
- finite rewritten values, such as `ArrayLiteral((14, 15, 16))`;
- occurrence-pinned runtime symbols where source is visible enough to name but
  not reduce;
- a real temporal effect;
- a loud construction/floor gap.

The fluent-builder test should assert the no-time-left result directly.

- [ ] **Step 5: Verify the focused temporal test is red, then green**

Run:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_temporal_forward_rewrite.py
```

Expected first failure: missing `FactoryBuildContext` / `TemporalContext` /
`SugarBody` modules. Expected green result after the task: the fluent-builder
forward rewrite produces the timeless array/list facts and the unknown mutation
twin reports the red boundary as an effect or named floor gap.

- [ ] **Step 6: Commit**

```bash
git add implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/context implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/temporal implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar_body implementations/python/sugar-lift-py-tests/tests/test_temporal_forward_rewrite.py
git commit -m "Add Python temporal forward rewrite kernel"
```

## Task 4: Add Factory Claims And Loud Construction Gaps

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/claim/`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/factory/`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_factory_kernel.py`

**Interfaces:**
- Consumes: `Outcome`, `Complete`, `Incomplete`, floor values
- Produces: `SugarRole`, `SugarClaim`, `SugarCandidate`, `SugarConstructionGap`, `build(node, role, ctx, claims) -> Sugar`

- [ ] **Step 1: Write factory tests that demand loud gaps**

Create `test_factory_kernel.py`:

```python
from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory import SugarConstructionGap, build
from sugar_lift_py_tests.floor import TermFloor
from sugar_lift_py_tests.outcome import Complete


class LiteralOneSugar:
    def reduce(self, ctx):
        return Complete(TermFloor(term={"kind": "int", "value": 1}))


def recognize_literal_one(node, ctx):
    if isinstance(node, ast.Constant) and node.value == 1:
        return LiteralOneSugar()
    return None


def test_factory_gap_names_the_fix():
    node = ast.parse("x + 1", mode="eval").body

    with pytest.raises(SugarConstructionGap) as exc:
        build(node, SugarRole.Term, ctx=None, claims=[])

    message = str(exc.value)
    assert message.startswith("write more Sugar for this AST")
    assert "owner=factory" in message
    assert "blame=1:0" in message
    assert "observed=BinOp" in message
    assert "requested=Term" in message
    assert "fix=create sugar_lift_py_tests.sugar.binop" in message
    assert exc.value.info.owner == "factory"
    assert exc.value.info.observed == "BinOp"
    assert exc.value.info.requested == "Term"


def test_factory_constructs_matching_claim():
    node = ast.parse("1", mode="eval").body
    claim = SugarClaim("literal-one", SugarRole.Term, recognize_literal_one)

    sugar = build(node, SugarRole.Term, ctx=None, claims=[claim])

    assert isinstance(sugar.reduce(None), Complete)
```

- [ ] **Step 2: Run the focused test to see it fail**

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_factory_kernel.py
```

Expected: import failure for `sugar_lift_py_tests.claim`.

- [ ] **Step 3: Implement claim metadata**

Create the `claim/` package. The snippet below shows the API shape; implement
`SugarRole`, `Sugar`, `SugarClaim`, and `SugarCandidate` in separate files and
re-export them from `claim/__init__.py`.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol


class SugarRole(Enum):
    Term = "Term"
    Predicate = "Predicate"
    AssertionSurface = "AssertionSurface"
    CallsiteFact = "CallsiteFact"
    BodyUniverse = "BodyUniverse"
    Precondition = "Precondition"
    LiteralValue = "LiteralValue"
    Sequence = "Sequence"
    TupleProducer = "TupleProducer"
    ClassShape = "ClassShape"
    Support = "Support"
    EffectSite = "EffectSite"


class Sugar(Protocol):
    def reduce(self, ctx: Any) -> Any:
        ...


Recognizer = Callable[[Any, Any], Sugar | None]


@dataclass(frozen=True)
class SugarClaim:
    name: str
    role: SugarRole
    recognize: Recognizer
    comes_before: tuple[str, ...] = ()
    fallback_well: bool = False


@dataclass(frozen=True)
class SugarCandidate:
    claim: SugarClaim
    sugar: Sugar
```

- [ ] **Step 4: Implement factory gap panics**

Create the factory dispatch files. Keep `build`, `matching_candidates`,
`sugar_gap`, `blame_site`, `FactoryAuditRow`, and `summarize_factory_audits` in
separate files under `factory/`, then re-export from `factory/__init__.py`.

```python
from __future__ import annotations

import ast
from typing import Any, Iterable, NoReturn

from sugar_lift_py_tests.claim import Sugar, SugarCandidate, SugarClaim, SugarRole
from sugar_lift_py_tests.gaps import ConstructionGapInfo, ConstructionGapPanic


class SugarConstructionGap(ConstructionGapPanic):
    pass


def build(
    node: ast.AST,
    role: SugarRole,
    *,
    ctx: Any,
    claims: Iterable[SugarClaim],
) -> Sugar:
    candidates = matching_candidates(node, role, ctx=ctx, claims=claims)
    if not candidates:
        sugar_gap(node, role)
    if len(candidates) > 1:
        names = ", ".join(candidate.claim.name for candidate in candidates)
        raise SugarConstructionGap(
            "write more Sugar ordering for this AST",
            ConstructionGapInfo(
                kind="sugar",
                owner="factory",
                blame=blame_site(node),
                observed=f"{type(node).__name__} candidates=[{names}]",
                requested=role.value,
                fix="declare comes_before or split the role",
            ),
        )
    return candidates[0].sugar


def matching_candidates(
    node: ast.AST,
    role: SugarRole,
    *,
    ctx: Any,
    claims: Iterable[SugarClaim],
) -> list[SugarCandidate]:
    out: list[SugarCandidate] = []
    for claim in claims:
        if claim.role is not role:
            continue
        sugar = claim.recognize(node, ctx)
        if sugar is not None:
            out.append(SugarCandidate(claim=claim, sugar=sugar))
    return out


def sugar_gap(node: ast.AST, role: SugarRole) -> NoReturn:
    ast_name = type(node).__name__
    module = ast_name.lower()
    raise SugarConstructionGap(
        "write more Sugar for this AST",
        ConstructionGapInfo(
            kind="sugar",
            owner="factory",
            blame=blame_site(node),
            observed=ast_name,
            requested=role.value,
            fix=f"create sugar_lift_py_tests.sugar.{module}",
        ),
    )


def blame_site(node: ast.AST) -> str:
    return f"{getattr(node, 'lineno', '?')}:{getattr(node, 'col_offset', '?')}"
```

- [ ] **Step 5: Add audit row data**

Create `factory/audit_row.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FactoryAuditRow:
    ast_kind: str
    requested_role: str
    selected: str | None
    candidates: tuple[str, ...]
    disposition: str
    output: str
    reason: str | None = None
    source_memento: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "factory-audit-row",
            "astKind": self.ast_kind,
            "requestedRole": self.requested_role,
            "selected": self.selected,
            "candidates": list(self.candidates),
            "disposition": self.disposition,
            "output": self.output,
            "reason": self.reason,
            "sourceMemento": self.source_memento,
        }
```

- [ ] **Step 6: Verify focused tests and IDD movement**

Run:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_factory_kernel.py implementations/python/sugar-lift-py-tests/tests/test_floor_kernel.py implementations/python/sugar-lift-py-tests/tests/test_numpy_pandas_panic_audit.py
```

Expected: all tests pass. The standalone IDD command still exits `1` until the numpy and pandas panic vector reaches zero.

- [ ] **Step 7: Commit**

```bash
git add implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/claim implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/factory implementations/python/sugar-lift-py-tests/tests/test_factory_kernel.py
git commit -m "Add Python sugar factory construction gaps"
```

## Task 5: Add Audit-Only Gap Inventory

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/audit_only/__init__.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/audit_only/audit_only_gap.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/audit_only/collect_construction_gaps.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_audit_only_gaps.py`

**Interfaces:**
- Consumes: `ConstructionGapPanic`, `ConstructionGapInfo`, `sugar_gap`, `floor_gap`
- Produces: `AuditOnlyGap`, `collect_construction_gaps(walkers: Iterable[AuditWalker]) -> list[AuditOnlyGap]`

- [ ] **Step 1: Write the failing audit-only test**

Create `test_audit_only_gaps.py`:

```python
from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.audit_only import collect_construction_gaps
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import SugarConstructionGap, sugar_gap
from sugar_lift_py_tests.floor import floor_gap


def test_audit_only_collects_multiple_construction_gaps():
    def missing_sugar():
        sugar_gap(ast.parse("x + 1", mode="eval").body, SugarRole.Term)

    def missing_floor():
        floor_gap(
            owner="python-test",
            blame="fixture.py:3:4",
            ast_kind="ListComp",
            required_floor="SequenceFloor",
            fix="add SequenceFloor construction for ListComp",
        )

    gaps = collect_construction_gaps(
        [
            ("missing-sugar", missing_sugar),
            ("missing-floor", missing_floor),
        ]
    )

    assert [gap.label for gap in gaps] == ["missing-sugar", "missing-floor"]
    assert gaps[0].info.kind == "sugar"
    assert gaps[0].info.fix == "create sugar_lift_py_tests.sugar.binop"
    assert gaps[1].info.kind == "floor"
    assert gaps[1].info.fix == "add SequenceFloor construction for ListComp"
    assert all(gap.to_json()["message"].startswith("write more ") for gap in gaps)


def test_normal_mode_still_panics_immediately():
    with pytest.raises(SugarConstructionGap):
        sugar_gap(ast.parse("x + 1", mode="eval").body, SugarRole.Term)
```

- [ ] **Step 2: Run the focused test to see it fail**

Run:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_audit_only_gaps.py
```

Expected: import failure for `sugar_lift_py_tests.audit_only`.

- [ ] **Step 3: Implement audit-only collection**

Create `audit_only/audit_only_gap.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.gaps import ConstructionGapInfo


@dataclass(frozen=True)
class AuditOnlyGap:
    label: str
    info: ConstructionGapInfo
    message: str

    def to_json(self) -> dict:
        return {
            "kind": "audit-only-construction-gap",
            "label": self.label,
            "message": self.message,
            "gap": self.info.to_json(),
        }
```

Create `audit_only/collect_construction_gaps.py`:

```python
from __future__ import annotations

from typing import Callable, Iterable, TypeAlias

from sugar_lift_py_tests.gaps import ConstructionGapPanic

from .audit_only_gap import AuditOnlyGap


AuditWalker: TypeAlias = tuple[str, Callable[[], object]]


def collect_construction_gaps(walkers: Iterable[AuditWalker]) -> list[AuditOnlyGap]:
    gaps: list[AuditOnlyGap] = []
    for label, walker in walkers:
        try:
            walker()
        except ConstructionGapPanic as exc:
            gaps.append(AuditOnlyGap(label=label, info=exc.info, message=str(exc)))
    return gaps
```

Create `audit_only/__init__.py`:

```python
from __future__ import annotations

from .audit_only_gap import AuditOnlyGap
from .collect_construction_gaps import collect_construction_gaps

__all__ = ["AuditOnlyGap", "collect_construction_gaps"]
```

- [ ] **Step 4: Verify audit-only and normal panic behavior**

Run:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_audit_only_gaps.py implementations/python/sugar-lift-py-tests/tests/test_factory_kernel.py implementations/python/sugar-lift-py-tests/tests/test_floor_kernel.py
```

Expected: all tests pass. Audit-only reports both gaps; normal mode still raises on the first gap.

- [ ] **Step 5: Verify IDD movement**

Run:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src python -m sugar_lift_py_tests.idd.cli --root . --json
```

Expected: exit code `1` until numpy and pandas produce zero observed construction panics. Audit-only readiness may appear in diagnostics, but it is not an `R` axis.

- [ ] **Step 6: Commit**

```bash
git add implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/audit_only implementations/python/sugar-lift-py-tests/tests/test_audit_only_gaps.py
git commit -m "Add Python audit-only construction gap inventory"
```

## Task 6: Add Callsite Fact To Post-Order Constraint Universe Flow

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/constraint_flow/__init__.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/constraint_flow/constraint_dig_request.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/constraint_flow/callsite_constraint_fact.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/constraint_flow/constraint_universe.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/constraint_flow/recognize_callsite_fact.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/constraint_flow/dig_constraint_universe.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_constraint_flow.py`

**Interfaces:**
- Consumes: Python `ast`, callsite source mementos, body source mementos, optional name-resolution facts
- Produces: `CallsiteConstraintFact`, `ConstraintDigRequest`, `ConstraintUniverse`, `recognize_callsite_fact`, `walk_constraint_universe`

- [ ] **Step 1: Write the failing source-shape constraint tests**

Create `test_constraint_flow.py`:

```python
from __future__ import annotations

import ast

from sugar_lift_py_tests.constraint_flow import (
    ConstraintDigRequest,
    recognize_callsite_fact,
    walk_constraint_universe,
)


def test_vendor_callsite_fact_triggers_dig_and_body_universe_walk():
    test_tree = ast.parse("def test_age():\n    assert User(age=21).age >= 18\n")
    assert_stmt = test_tree.body[0].body[0]

    fact = recognize_callsite_fact(
        assert_stmt,
        source_memento={"file": "test_model.py", "line": 2, "col": 4},
    )

    assert fact is not None
    assert fact.sugar_name == "python.vendor-test.callsite-assert"
    assert fact.callsite == "User(age=21)"
    assert fact.subject == "User.age"
    assert fact.fact == {
        "kind": "atomic",
        "name": ">=",
        "args": [
            {"kind": "field", "owner": "User", "name": "age"},
            {"kind": "int", "value": 18},
        ],
    }
    assert fact.source_memento["file"] == "test_model.py"

    dig = fact.trigger_dig()
    assert isinstance(dig, ConstraintDigRequest)
    assert dig.fact_subject == "User.age"
    assert dig.target_symbol == "User"
    assert dig.reason == "vendor callsite fact warrants constraint-universe dig for User"

    body_tree = ast.parse("class User:\n    age: int = Field(..., ge=18)\n")
    universe = walk_constraint_universe(
        body_tree,
        dig,
        source_memento={"file": "model.py", "line": 1, "col": 0},
        resolved_names={"Field": "pydantic.Field"},
    )

    assert universe.sugar_chain == [
        "python.term.int-literal",
        "python.constraint.field-keyword",
        "python.body-universe.class",
    ]
    assert universe.predicates == [fact.fact]
    assert universe.proofir == [
        {
            "kind": "contract",
            "name": "User.age::universe",
            "post": fact.fact,
            "source": {"file": "model.py", "line": 1, "col": 0},
        }
    ]
    assert universe.source_memento["file"] == "model.py"


def test_model_class_without_constraint_shape_emits_no_universe_predicates():
    tree = ast.parse("class User(BaseModel):\n    age: int\n")
    dig = ConstraintDigRequest(
        fact_subject="User.age",
        target_symbol="User",
        source_memento={"file": "test_model.py", "line": 2, "col": 4},
        reason="vendor callsite fact warrants constraint-universe dig for User",
    )

    universe = walk_constraint_universe(
        tree,
        dig,
        source_memento={"file": "model.py", "line": 1, "col": 0},
        resolved_names={"BaseModel": "pydantic.BaseModel"},
    )

    assert universe.predicates == []
    assert universe.proofir == []
    assert universe.effects == []
```

- [ ] **Step 2: Run the focused test to see it fail**

Run:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_constraint_flow.py
```

Expected: import failure for `sugar_lift_py_tests.constraint_flow`.

- [ ] **Step 3: Implement callsite fact and post-order shape-owned universe flow**

Create the `constraint_flow/` package. The snippet below shows the API shape;
implement each class in its own file and keep each function in its own named
module, then re-export from `constraint_flow/__init__.py`.

```python
from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConstraintDigRequest:
    fact_subject: str
    target_symbol: str
    source_memento: dict[str, Any]
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "constraint-dig-request",
            "factSubject": self.fact_subject,
            "targetSymbol": self.target_symbol,
            "sourceMemento": dict(self.source_memento),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CallsiteConstraintFact:
    sugar_name: str
    callsite: str
    subject: str
    fact: dict[str, Any]
    source_memento: dict[str, Any]
    target_symbol: str

    def trigger_dig(self) -> ConstraintDigRequest:
        return ConstraintDigRequest(
            fact_subject=self.subject,
            target_symbol=self.target_symbol,
            source_memento=self.source_memento,
            reason=f"vendor callsite fact warrants constraint-universe dig for {self.target_symbol}",
        )


@dataclass(frozen=True)
class ConstraintUniverse:
    predicates: list[dict[str, Any]]
    proofir: list[dict[str, Any]]
    effects: list[dict[str, Any]]
    source_memento: dict[str, Any]
    sugar_chain: list[str]


def recognize_callsite_fact(
    node: ast.AST,
    *,
    source_memento: dict[str, Any],
) -> CallsiteConstraintFact | None:
    if not isinstance(node, ast.Assert):
        return None
    compare = node.test
    if not (
        isinstance(compare, ast.Compare)
        and len(compare.ops) == 1
        and isinstance(compare.ops[0], ast.GtE)
        and len(compare.comparators) == 1
    ):
        return None
    left = compare.left
    right = compare.comparators[0]
    if not (
        isinstance(left, ast.Attribute)
        and isinstance(left.value, ast.Call)
        and isinstance(left.value.func, ast.Name)
        and isinstance(right, ast.Constant)
        and isinstance(right.value, int)
    ):
        return None
    owner = left.value.func.id
    field = left.attr
    return CallsiteConstraintFact(
        sugar_name="python.vendor-test.callsite-assert",
        callsite=ast.unparse(left.value),
        subject=f"{owner}.{field}",
        fact=_ge_field_fact(owner, field, int(right.value)),
        source_memento=dict(source_memento),
        target_symbol=owner,
    )


def walk_constraint_universe(
    tree: ast.Module,
    dig: ConstraintDigRequest,
    *,
    source_memento: dict[str, Any],
    resolved_names: dict[str, str],
) -> ConstraintUniverse:
    """Walk source AST into a universe. This is post-order construction in miniature."""
    predicates: list[dict[str, Any]] = []
    proofir: list[dict[str, Any]] = []
    sugar_chain: list[str] = []
    owner, _, field = dig.fact_subject.partition(".")
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id != field:
            continue
        predicate, child_chain = _field_keyword_predicate(node, owner, resolved_names)
        if predicate is not None:
            sugar_chain.extend(child_chain)
            predicates.append(predicate)
            proofir.append(
                {
                    "kind": "contract",
                    "name": f"{owner}.{field}::universe",
                    "post": predicate,
                    "source": dict(source_memento),
                }
            )
    if sugar_chain:
        sugar_chain.append("python.body-universe.class")
    return ConstraintUniverse(
        predicates=predicates,
        proofir=proofir,
        effects=[],
        source_memento=dict(source_memento),
        sugar_chain=sugar_chain,
    )


def _field_keyword_predicate(
    node: ast.AnnAssign,
    owner: str,
    resolved_names: dict[str, str],
) -> tuple[dict[str, Any] | None, list[str]]:
    call = node.value
    if not isinstance(call, ast.Call):
        return None, []
    callee = _callee_name(call.func)
    if resolved_names.get(callee, callee) != "pydantic.Field":
        return None, []
    for keyword in call.keywords:
        if keyword.arg == "ge" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, int):
            field = node.target.id
            return (
                _ge_field_fact(owner, field, int(keyword.value.value)),
                ["python.term.int-literal", "python.constraint.field-keyword"],
            )
    return None, []


def _ge_field_fact(owner: str, field: str, value: int) -> dict[str, Any]:
    return {
        "kind": "atomic",
        "name": ">=",
        "args": [
            {"kind": "field", "owner": owner, "name": field},
            {"kind": "int", "value": value},
        ],
    }


def _callee_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _callee_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""
```

- [ ] **Step 4: Verify shape tests**

Run:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_constraint_flow.py
```

Expected: `2 passed`. The implementation imports `ast`; it does not import `pydantic`, inspect a model object, or synthesize preconditions outside the callsite fact -> dig -> universe path.

- [ ] **Step 5: Verify IDD movement**

Run:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src python -m sugar_lift_py_tests.idd.cli --root . --json
```

Expected: exit code `1` until numpy and pandas produce zero observed construction panics. Constraint-flow readiness may appear in diagnostics, but it is not an `R` axis.

- [ ] **Step 6: Commit**

```bash
git add implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/constraint_flow implementations/python/sugar-lift-py-tests/tests/test_constraint_flow.py implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd
git commit -m "Add Python source-shape constraint flow"
```

## Task 7: Wire Component Discovery Before More Migration

**Files:**
- Create: `.sugar/components/python-test-assertions/manifest.toml`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/kit_rpc/component_plan_result.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/kit_rpc/server.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/kit_rpc/__init__.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_python_component_plan.py`

**Interfaces:**
- Consumes: existing Sugar JSON-RPC request shape
- Produces: `sugar.component.plan` response for `.py` projects

- [ ] **Step 1: Write component-plan tests**

Create `test_python_component_plan.py`:

```python
from __future__ import annotations

from sugar_lift_py_tests.kit_rpc import component_plan_result


def test_python_component_declines_without_py_evidence(tmp_path):
    result = component_plan_result(
        {
            "workspace_root": str(tmp_path),
            "project_forensics": {"items": []},
        }
    )

    assert result["decision"] == "decline"


def test_python_component_claims_py_file(tmp_path):
    (tmp_path / "test_sample.py").write_text("def test_x():\n    assert 1 == 1\n", encoding="utf-8")
    result = component_plan_result(
        {
            "workspace_root": str(tmp_path),
            "project_forensics": {
                "items": [
                    {
                        "kind": "source",
                        "path": "test_sample.py",
                        "language_hint": "python",
                    }
                ]
            },
        }
    )

    assert result["decision"] == "claim"
    surfaces = {plugin["surface"] for plugin in result["plugins"]}
    assert "python" in surfaces
    assert any(manifest["phase"] == "consumer" for manifest in result["lift_manifests"])
```

- [ ] **Step 2: Run the focused test to see it fail**

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_python_component_plan.py
```

Expected: import error for `component_plan_result`.

- [ ] **Step 3: Add `sugar.component.plan` handling in `kit_rpc`**

Create `kit_rpc/component_plan_result.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


KIT_ID = "python"
KIT_VERSION = "0.1.0"
COMPONENT_PLAN_RPC_METHOD = "sugar.component.plan"
COMPONENT_PROTOCOL_VERSION = "sugar-component/1"


def component_plan_result(params: dict[str, Any]) -> dict[str, Any]:
    workspace_root = Path(str(params.get("workspace_root", ".")))
    items = (
        params.get("project_forensics", {}).get("items")
        or params.get("workspace_evidence", {}).get("items")
        or []
    )
    has_py = any(
        str(item.get("path", "")).endswith(".py")
        or item.get("language_hint") == "python"
        or item.get("languageHint") == "python"
        for item in items
        if isinstance(item, dict)
    )
    has_py = has_py or any(workspace_root.rglob("*.py"))
    if not has_py:
        return {"decision": "decline", "reason": "no Python source evidence"}
    command = [sys.executable, "-m", "sugar_lift_py_tests.kit_rpc.server", "--rpc"]
    return {
        "decision": "claim",
        "claims": [{"item": "language:python", "role": "assertion-lifter", "surface": KIT_ID}],
        "plugins": [{"name": "python-lift", "kind": "lift", "surface": KIT_ID, "emit": "ir-document"}],
        "lift_manifests": [
            {
                "surface": KIT_ID,
                "name": "python-lift",
                "version": KIT_VERSION,
                "protocol_version": COMPONENT_PROTOCOL_VERSION,
                "kind": "lift",
                "command": command,
                "working_dir": ".",
                "phase": "consumer",
            }
        ],
        "diagnostics": [],
    }
```

Create `kit_rpc/__init__.py`:

```python
from __future__ import annotations

from .component_plan_result import COMPONENT_PLAN_RPC_METHOD, component_plan_result

__all__ = ["COMPONENT_PLAN_RPC_METHOD", "component_plan_result"]
```

Create `kit_rpc/server.py` as protocol plumbing only. It routes
`sugar.component.plan` to `component_plan_result`; it does not own Python
semantics.

- [ ] **Step 4: Add component manifest**

Create `.sugar/components/python-test-assertions/manifest.toml`:

```toml
# SPDX-License-Identifier: Apache-2.0

name = "python-test-assertions"
version = "0.1.0"
protocol_version = "sugar-component/1"
command = ["python3", "-m", "sugar_lift_py_tests.kit_rpc.server", "--rpc"]
working_dir = "../../.."
```

- [ ] **Step 5: Verify component test**

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_python_component_plan.py
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add .sugar/components/python-test-assertions/manifest.toml implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/kit_rpc implementations/python/sugar-lift-py-tests/tests/test_python_component_plan.py
git commit -m "Add Python component discovery plan"
```

## Task 8: Port One Existing Family As Native Python Sugar

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/__init__.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/translate_universe/__init__.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/translate_universe/translate_universe_sugar.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/translate_universe/recognize_translate_universe.py`
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/translate_universe/translate_universe_claim.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_translate_universe_sugar.py`

**Interfaces:**
- Consumes: Python source-oracle body-universe responses
- Produces: `TRANSLATE_UNIVERSE_CLAIM`, a native `BodyUniverseFloor` sugar

- [ ] **Step 1: Write the native sugar test**

Create `test_translate_universe_sugar.py`:

```python
from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import build
from sugar_lift_py_tests.floor import BodyUniverseFloor
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.translate_universe import TRANSLATE_UNIVERSE_CLAIM


class FakeSourceOracle:
    def has_body_universe(self, callee: str) -> bool:
        return callee == "vendor.urlsafe"

    def body_universe_for(self, callee: str) -> dict:
        assert callee == "vendor.urlsafe"
        return {
            "predicates": [
                {
                    "kind": "atomic",
                    "name": "str.chars-not-in-set",
                    "args": [{"kind": "var", "name": "out"}, {"kind": "string", "value": "+/="}],
                }
            ],
            "source_memento": {
                "kind": "python-source-memento",
                "file": "vendor.py",
                "line": 7,
                "col": 4,
                "source_cid": "blake3-512:test",
            },
        }


class FakeCtx:
    source_oracle = FakeSourceOracle()


def test_translate_universe_claim_reduces_to_body_universe():
    ctx = FakeCtx()
    node = ast.parse("vendor.urlsafe", mode="eval").body
    sugar = build(node, SugarRole.BodyUniverse, ctx=ctx, claims=[TRANSLATE_UNIVERSE_CLAIM])
    outcome = sugar.reduce(None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.floor, BodyUniverseFloor)
    assert outcome.floor.predicates[0]["name"] == "str.chars-not-in-set"
    assert outcome.floor.source_memento["file"] == "vendor.py"
```

- [ ] **Step 2: Run the focused test to see it fail**

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_translate_universe_sugar.py
```

Expected: import failure for `sugar_lift_py_tests.sugar`.

- [ ] **Step 3: Add sugar package marker**

Create `sugar/__init__.py`:

```python
"""Python Sugar modules.

Each module owns a source shape and exports explicit SugarClaim values.
"""
```

- [ ] **Step 4: Add native translate universe sugar**

Create `sugar/translate_universe/translate_universe_sugar.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.floor import BodyUniverseFloor
from sugar_lift_py_tests.outcome import Complete


@dataclass(frozen=True)
class TranslateUniverseSugar:
    callee: str

    def reduce(self, ctx: Any):
        universe = ctx.source_oracle.body_universe_for(self.callee)
        predicate = {
            "kind": "atomic",
            "name": "str.chars-not-in-set",
            "args": universe["predicates"][0]["args"],
        }
        return Complete(
            BodyUniverseFloor(
                predicates=[predicate],
                source_memento=dict(universe["source_memento"]),
            )
        )
```

Create `sugar/translate_universe/recognize_translate_universe.py`:

```python
from __future__ import annotations

import ast
from typing import Any

from .translate_universe_sugar import TranslateUniverseSugar


def recognize_translate_universe(node: ast.AST, ctx: Any):
    callee = _static_name(node)
    if not callee:
        return None
    if not ctx.source_oracle.has_body_universe(callee):
        return None
    return TranslateUniverseSugar(callee)


def _static_name(node: ast.AST) -> str:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=value, attr=attr):
            prefix = _static_name(value)
            return f"{prefix}.{attr}" if prefix else attr
        case _:
            return ""
```

Create `sugar/translate_universe/translate_universe_claim.py`:

```python
from __future__ import annotations

from sugar_lift_py_tests.claim import SugarClaim, SugarRole

from .recognize_translate_universe import recognize_translate_universe


TRANSLATE_UNIVERSE_CLAIM = SugarClaim(
    "python.translate-universe",
    SugarRole.BodyUniverse,
    recognize_translate_universe,
)
```

Create `sugar/translate_universe/__init__.py`:

```python
from __future__ import annotations

from .translate_universe_claim import TRANSLATE_UNIVERSE_CLAIM
from .translate_universe_sugar import TranslateUniverseSugar

__all__ = ["TRANSLATE_UNIVERSE_CLAIM", "TranslateUniverseSugar"]
```

- [ ] **Step 5: Verify native sugar test**

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_translate_universe_sugar.py
```

Expected: test passes.

- [ ] **Step 6: Verify the panic audit observes movement only by rerunning lifts**

Do not hand-edit `R`. Rerun the panic audit; movement exists only if the numpy
or pandas lift no longer observes a construction panic because this sugar now
claims a real source shape.

Run:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src python -m sugar_lift_py_tests.idd.cli --root . --json
```

Expected: exit code `1` until the observed numpy/pandas panic vector is zero.
If this sugar covers an observed panic, `Delta R` is read from the changed
panic count between the previous run and this run.

- [ ] **Step 7: Commit**

```bash
git add implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar implementations/python/sugar-lift-py-tests/tests/test_translate_universe_sugar.py
git commit -m "Add native Python translate universe sugar"
```

## Task 9: Attach Factory Accounting To Lift Reports

**Files:**
- Create: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/kit_rpc/report_payload.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/factory/audit_summary.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_kit_rpc_report_payload.py`

**Interfaces:**
- Consumes: `FactoryAuditRow`
- Produces: `factoryAuditSummary` and `factoryAudits` in Python lift RPC responses

- [ ] **Step 1: Add a kit-RPC report assertion**

Create `test_kit_rpc_report_payload.py` with a lift response test asserting
Python report payloads include real factory rows:

```python
assert "factoryAuditSummary" in result
assert "statusCounts" in result["factoryAuditSummary"]
assert "factoryWalk" in result["factoryAuditSummary"]
assert result["factoryAudits"]
assert result["factoryAuditSummary"]["emittedRows"] == len(result["factoryAudits"])
```

- [ ] **Step 2: Run the focused test to see it fail**

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_kit_rpc_report_payload.py
```

Expected: assertion failure because Python RPC does not yet emit factory audit summary.

- [ ] **Step 3: Add summary helpers**

In `factory/audit_summary.py`, add:

```python
def summarize_factory_audits(rows: list[FactoryAuditRow]) -> dict:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.disposition] = counts.get(row.disposition, 0) + 1
    return {
        "kind": "factory-audit-summary",
        "statusCounts": counts,
        "emittedRows": len(rows),
        "constructionGaps": [row.to_json() for row in rows if row.disposition == "construction-gap"],
        "factoryWalk": [row.to_json() for row in rows],
    }
```

- [ ] **Step 4: Emit real factory rows from `kit_rpc/report_payload.py`**

`report_payload.py` must consume the factory walk rows produced by the lift, not
invent an empty placeholder:

```python
def report_payload(factory_rows: list[FactoryAuditRow], base: dict) -> dict:
    rows = [row.to_json() for row in factory_rows]
    return {
        **base,
        "factoryAudits": rows,
        "factoryAuditSummary": summarize_factory_audits(factory_rows),
    }
```

If the lift traversed Python AST and produced zero rows, that is a construction
or routing gap and must be reported by the panic audit.

- [ ] **Step 5: Verify focused protocol tests**

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src pytest -q implementations/python/sugar-lift-py-tests/tests/test_kit_rpc_report_payload.py
```

Expected: test passes.

- [ ] **Step 6: Commit**

```bash
git add implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/kit_rpc/report_payload.py implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/factory/audit_summary.py implementations/python/sugar-lift-py-tests/tests/test_kit_rpc_report_payload.py
git commit -m "Expose Python factory audit summary"
```

## Task 10: Prove The First No-Config Python Report Loop

**Files:**
- Create or reuse: a smallest Python example under `examples/python-urlsafe-seam/good` or a new focused `examples/python-factory-floor-good`
- Modify: example run script only if needed
- Test: focused shell command captured in PR notes

**Interfaces:**
- Consumes: component plan, factory audit, source oracle, native translate sugar
- Produces: no-config `sugar lift --report --visual` evidence

- [ ] **Step 1: Remove local config from the chosen focused example in the worktree only**

Pick the smallest Python example that exercises a unit-test fact plus a body universe. Prefer an existing `python-urlsafe-seam/good` style example if it can run without pulling in broad package accounting.

- [ ] **Step 2: Run no-config visual lift**

Run:

```bash
implementations/rust/target/debug/sugar lift examples/python-urlsafe-seam/good --report --visual
```

Expected before the task is done: either component discovery fails to find Python or the report lacks factory/source details. Keep that failure as the instrumented target.

- [ ] **Step 3: Fix only the missing report plumbing for the selected example**

Patch only the Python component/report path necessary to show:

- plan roll call includes Python;
- unit-test fact source memento resolves through the Python source oracle;
- body universe source memento resolves through the Python source oracle;
- factory audit summary is present;
- panic audit vector is still red if numpy or pandas construction panics remain.

- [ ] **Step 4: Verify no-config visual report**

Run:

```bash
implementations/rust/target/debug/sugar lift examples/python-urlsafe-seam/good --report --visual > /tmp/python-factory-floor-report.txt
```

Expected:

```text
plan: component-discovery
Python assertion lifter
source oracle
factory report
unit test
body universe
```

Also verify:

```bash
rg -n "source not present|body universe|factory report|python" /tmp/python-factory-floor-report.txt
```

Expected: the relevant report sections are present. If source is present, the source oracle should resolve it; if source is absent, the report must show pinned file/line/col/CID rather than failing.

- [ ] **Step 5: Record `R`, `Delta R`, and `Epsilon R` in PR notes**

Use the IDD instrument:

```bash
PYTHONPATH=implementations/python/sugar-lift-py-tests/src python -m sugar_lift_py_tests.idd.cli --root . --json > /tmp/python-factory-floor-r.json
```

PR note must include:

```text
R: paste the current JSON vector from /tmp/python-factory-floor-r.json
Delta R: paste the observed movement in numpy/pandas construction panic counts from the previous run
Epsilon R: expected next slice removes the named observed panic family by adding its sugar or floor
Floors preserved: source text absent from proof, pure unsupported remains construction gap, effects are typed
```

- [ ] **Step 6: Commit**

```bash
git add .sugar/components/python-test-assertions/manifest.toml implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/kit_rpc implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/factory examples/python-urlsafe-seam
git commit -m "Report Python factory floor discovery"
```

## Self-Review Checklist

- [ ] Every task begins with an instrument or focused test.
- [ ] The first implementation task makes the machine measure `R` by running numpy and pandas audit-only lifts.
- [ ] Factory gaps panic with `write more Sugar for this AST`.
- [ ] Floor gaps panic with `write more Floor for this AST` or `write more Floor for this construction`.
- [ ] Pure unsupported shapes are not represented as effects.
- [ ] Construction gaps are never modeled as `Outcome`, `None`, `Unresolved`, empty predicates, or generic dicts.
- [ ] `Outcome` has only `Complete` and `Incomplete`.
- [ ] The plan ports source oracle and implication capability through the new protocol instead of preserving old files as architecture.
- [ ] The plan produces a no-config report path before broad recognizer rewrites.
- [ ] Every command has a clear expected signal.

## Execution Options

1. **Subagent-Driven (recommended)** - one subagent per task, review after each task, and keep the IDD vector visible between shots.
2. **Inline Execution** - execute tasks in this session with checkpoints after each task.

Recommended first shot: Task 1 only. It pins the migration as executable telemetry and gives every later agent the red compass instead of another paragraph to remember.
