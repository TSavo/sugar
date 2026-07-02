# Design-Crimes Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate every audited path that quietly fails to panic, kill the verifier false-green, and close the floor-dispatch and factory-bypass side doors — instrument first, then drain, so every fix is held by a red-by-design audit that can never silently regress.

**Architecture:** IDD (instrument-driven development). We build the instruments FIRST: a gap-swallow frontier auditor (new) and extensions to the temporal-dispatch auditor, both red on the current codebase with a named R vector. Then we drain the vector: verifier false-green, `attribute_sugar` gap laundering, the `literal_call_report` digger's silent refusals, the `floor_to_term` isinstance ladder, and the `array_map_report` factory bypass. Each drain slice turns audit rows green and ratchets. The panic is sacred: when this codebase meets something it doesn't own, the only honest outputs are a loud `FactoryGap` naming owner/blame/fix, an explicit `Incomplete(effect)`, or a *recorded* refusal that the instrument counts.

**Tech Stack:** Python 3 (stdlib `ast` for auditors), pytest, existing `idd/` collector pattern, existing `FactoryGap`/`FactoryGapInfo` machinery.

## Global Constraints

- Working directory for all commands: `/Users/tsavo/provekit-wt/fresh-main-20260701/implementations/python/sugar-lift-py-tests`
- Test command shape: `PYTHONPATH=src python3 -m pytest -q tests/<file>` (this is how every existing gate test runs).
- Black formatting is gated (`tests/test_black_format_gate.py`): run `python3 -m black src tests` before every commit.
- Commit identity: `T Savo <evilgenius@nefariousplan.com>`.
- Every new auditor follows the existing `idd/` collector shape: a `collect_*` module returning a frozen report dataclass with an `is_zero`/`total` property, a `tests/test_*.py` gate, and a CLI flag on `sugar_lift_py_tests.idd.cli` that exits 1 while the frontier is non-empty. **Red is honest. Never suppress the floor.**
- Full-suite check before each commit: `PYTHONPATH=src python3 -m pytest -q tests/` (baseline as of #2978: ~582+ passed, 3 skipped — the exact count moves with main; the invariant is zero NEW failures except audits that are red by design and asserted red in their own gate tests).
- One branch per task group, PRs to `TSavo/sugar` main. Task 1–2 = branch `gap-kind-structured`; Task 3 = `gap-swallow-frontier`; Task 4 = `verifier-false-green`; Task 5 = `attribute-sugar-drain`; Task 6 = `digger-refusal-ledger`; Task 7 = `floor-to-term-ownership`; Task 8 = `array-map-factory-bypass`; Task 9 = `boundary-borderlines`.

---

## Why this order

1. **Structured gap kinds first (Task 1)** — everything downstream that must *discriminate* gaps (attribute_sugar, the swallow auditor's allowlist reasoning) currently sniffs message strings because `to_json()` erases `gap_kind`. Fix the data model first so no later task builds on string-sniffing.
2. **Instruments before drains (Tasks 2–3)** — the gap-swallow frontier auditor goes in RED, naming every current offender. Then each drain task turns its rows green. If a drain is incomplete, the instrument says so; nothing can silently regress after merge because the gate pins the frontier list exactly (a NEW swallow anywhere in `src/` fails CI loudly).
3. **Worst false-green first among drains (Task 4)** — `verifier.py` lies at the verifier boundary itself; it outranks everything.
4. **Structural refactors last (Tasks 7–8)** — they're bigger diffs; they ride on top of a codebase whose quiet-failure surface is already instrumented, so any gap they expose panics loudly instead of vanishing.

---

### Task 1: Structured gap kinds survive `to_json()`; constructor gaps get a real kind

The discriminator `attribute_sugar._is_constructor_gap` sniffs `"constructor" in requested` because `FactoryGapInfo.to_json()` (`src/sugar_lift_py_tests/factory/factory_gap_info.py:25-32`) drops `gap_kind` and `gap_locus`. Make the structured fields survive serialization and introduce `gap_kind="Constructor"` at the raise sites that mint constructor gaps.

**Files:**
- Modify: `src/sugar_lift_py_tests/factory/factory_gap_info.py`
- Modify: every raise site that mints a constructor-flavored gap (found by the grep step below)
- Test: `tests/test_factory_gap_info.py` (new)

**Interfaces:**
- Produces: `FactoryGap.info["gap_kind"]` and `.info["gap_locus"]` are always present (strings). Constructor gaps carry `gap_kind == "Constructor"`. Task 5 consumes this.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_gap_info.py
from sugar_lift_py_tests.factory.factory_gap_info import FactoryGapInfo


def test_to_json_carries_gap_kind_and_locus():
    info = FactoryGapInfo(
        owner="o", blame="b", observed="x", requested="r", fix="f",
        gap_kind="Floor", gap_locus="Reduce",
    )
    data = info.to_json()
    assert data["gap_kind"] == "Floor"
    assert data["gap_locus"] == "Reduce"


def test_to_json_defaults_present():
    info = FactoryGapInfo(owner="o", blame="b", observed="x", requested="r", fix="f")
    data = info.to_json()
    assert data["gap_kind"] == "Sugar"
    assert data["gap_locus"] == "AST"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest -q tests/test_factory_gap_info.py`
Expected: FAIL with `KeyError: 'gap_kind'`

- [ ] **Step 3: Extend `to_json`**

In `src/sugar_lift_py_tests/factory/factory_gap_info.py`, replace the `to_json` method:

```python
    def to_json(self) -> Dict[str, str]:
        return {
            "owner": self.owner,
            "blame": self.blame,
            "observed": self.observed,
            "requested": self.requested,
            "fix": self.fix,
            "gap_kind": self.gap_kind,
            "gap_locus": self.gap_locus,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python3 -m pytest -q tests/test_factory_gap_info.py`
Expected: 2 passed

- [ ] **Step 5: Find the constructor-gap raise sites**

Run: `rg -n "constructor|construction|__set_name__" src/sugar_lift_py_tests --type py -g '!*test*' -l` then inspect each hit that constructs a `FactoryGapInfo`. Expected shape: sites whose `requested=` or `fix=` text mentions constructor/construction/`__set_name__` (these are exactly what `attribute_sugar._is_constructor_gap` sniffs today). For each such `FactoryGapInfo(...)` construction, add `gap_kind="Constructor"`. Do NOT change the message text (downstream tests may assert on it).

- [ ] **Step 6: Add a kind-assertion test per converted site**

For each converted raise site, add a test in `tests/test_factory_gap_info.py` that triggers it (or, where triggering is heavyweight, a direct unit test on the helper that constructs the info) and asserts `gap.info["gap_kind"] == "Constructor"`. Example shape:

```python
def test_constructor_gap_sites_carry_structured_kind():
    # one assertion per site converted in Step 5; adjust to the real helpers found
    ...
    assert gap.info["gap_kind"] == "Constructor"
```

- [ ] **Step 7: Full suite, format, commit**

Run: `PYTHONPATH=src python3 -m pytest -q tests/` — expected: no new failures.
Run: `python3 -m black src tests`

```bash
git checkout -b gap-kind-structured
git add -A
git commit -m "fix(factory): gap_kind/gap_locus survive FactoryGapInfo.to_json; constructor gaps carry structured kind"
```

---

### Task 2: `IncompleteDischargeError` — a loud protocol error type for the verifier boundary

Small prerequisite for Tasks 4 and 9: a dedicated exception so callers can distinguish "the verifier protocol broke" from "verification failed."

**Files:**
- Modify: `src/sugar_lift_py_tests/verifier.py` (add exception class next to `VerifierNotFoundError`)
- Test: covered by Task 4's tests (this task is fold-in scaffolding; no separate commit — Task 4 commits it)

**Interfaces:**
- Produces: `class VerifierProtocolError(RuntimeError)` in `sugar_lift_py_tests.verifier`, raised with the raw stdout attached as `.stdout`.

- [ ] **Step 1: Add the exception class** (top of `verifier.py`, near the existing `VerifierNotFoundError`):

```python
class VerifierProtocolError(RuntimeError):
    """The sugar CLI replied, but not in the wire format we own.

    A verdict is never inferred from an unparseable reply: protocol drift
    must surface loudly, because a fabricated pass is a false-green at the
    verifier boundary itself.
    """

    def __init__(self, message: str, *, stdout: str, stderr: str) -> None:
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(message)
```

(No standalone test/commit — proceed directly into Task 4 on the same branch as Task 4.)

---

### Task 3: The gap-swallow frontier instrument (RED by design)

A new `idd/` auditor that AST-scans all of `src/` for `except` handlers that catch `FactoryGap` (directly, or via `RuntimeError`/`Exception` which are its bases) and do not re-raise. Every current offender is named in the R vector. The CLI exits 1 while the frontier is non-empty. Sanctioned recorders (handlers that convert the gap into a loud record or error response) are allowlisted **by exact file+behavior, never by directory**.

**Files:**
- Create: `src/sugar_lift_py_tests/idd/gap_swallow_vector.py`
- Create: `src/sugar_lift_py_tests/idd/collect_gap_swallow_frontier.py`
- Modify: `src/sugar_lift_py_tests/idd/cli.py` (add `--gap-swallow-frontier` flag, same pattern as `--dunder-frontier`)
- Test: `tests/test_gap_swallow_frontier_audit.py`

**Interfaces:**
- Produces: `collect_gap_swallow_frontier(root: str) -> GapSwallowReport` where `GapSwallowReport` has `offenders: tuple[GapSwallowSite, ...]`, `total: int`, `is_zero: bool`, `to_json()`. `GapSwallowSite` has `file: str`, `line: int`, `caught: str` (the exception expression source), `disposition: str` (`"returns-default" | "continues" | "passes"`). Tasks 5, 6, 9 consume this by shrinking the expected-offender list in the gate test (the ratchet).

- [ ] **Step 1: Write the vector dataclass**

```python
# src/sugar_lift_py_tests/idd/gap_swallow_vector.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class GapSwallowSite:
    file: str
    line: int
    caught: str
    disposition: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "caught": self.caught,
            "disposition": self.disposition,
        }


@dataclass(frozen=True)
class GapSwallowReport:
    offenders: Tuple[GapSwallowSite, ...]

    @property
    def total(self) -> int:
        return len(self.offenders)

    @property
    def is_zero(self) -> bool:
        return not self.offenders

    def to_json(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "is_zero": self.is_zero,
            "offenders": [site.to_json() for site in self.offenders],
        }
```

- [ ] **Step 2: Write the failing gate test — pinning today's exact frontier**

The gate has two halves: (a) the auditor finds exactly the known offenders (no more, no fewer — a NEW swallow fails loudly, a drained swallow must be removed from this list in the same PR that drains it: the ratchet); (b) the audit CLI exits 1 while non-empty.

```python
# tests/test_gap_swallow_frontier_audit.py
from pathlib import Path

from sugar_lift_py_tests.idd.collect_gap_swallow_frontier import (
    collect_gap_swallow_frontier,
)

SRC = str(Path(__file__).resolve().parent.parent / "src" / "sugar_lift_py_tests")

# The ratchet: every entry here is a named crime awaiting its drain task.
# Drain a site -> delete its row here in the same PR. Add a swallow -> this
# test fails and CI stays red until you either panic or record loudly.
EXPECTED_FRONTIER = {
    ("sugar/attribute_sugar.py", "FactoryGap"),
    ("sugar/attribute_sugar.py", "TypeError"),
    ("sugar/truthy_assertion_sugar.py", "(FactoryGap, TypeError)"),
    ("factory/literal_call_report.py", "(TypeError, ValueError, FactoryGap)"),
    # literal_call_report has multiple sites with this tuple; the auditor
    # reports each line separately -- assert on the multiset below.
}


def test_frontier_matches_known_offenders_exactly():
    report = collect_gap_swallow_frontier(SRC)
    observed = {(site.file, site.caught) for site in report.offenders}
    assert observed == {
        (file, caught) for (file, caught) in EXPECTED_FRONTIER
    }, report.to_json()


def test_frontier_is_red():
    report = collect_gap_swallow_frontier(SRC)
    assert not report.is_zero  # red by design until every drain task lands


def test_sanctioned_recorders_are_not_offenders():
    report = collect_gap_swallow_frontier(SRC)
    files = {site.file for site in report.offenders}
    # These convert gaps into loud records/error responses -- verified by eye
    # in the audit, held here so a refactor cannot silently reclassify them.
    assert "lift_rpc.py" not in files
    assert "audit_only/collect_construction_gaps.py" not in files
```

NOTE to implementer: before finalizing `EXPECTED_FRONTIER`, run the collector once and copy its actual output into the test verbatim (file, line, caught) — the audit that motivated this plan found offenders at `factory/literal_call_report.py` lines 760, 940, 994, 1082, 1206, 1239 and getsource fallbacks near 1503–1514, `sugar/attribute_sugar.py:48-53`, `sugar/truthy_assertion_sugar.py:76`, `lift/pydantic.py:302` (bare `Exception`), `constraint_flow/dig_constraint_universe.py:26` (TypeError-only: include it — see Step 3 scope rule). Line numbers will drift with main; the collector output is the source of truth. **Do not shrink the list to make the test pass — every observed site goes in.**

- [ ] **Step 3: Write the collector**

Scope rule (what counts as an offender): an `except` handler in `src/**` counts when **all** of:
1. Its type expression names `FactoryGap`, `RuntimeError`, `Exception`, or a tuple containing one of them, **or** it names `TypeError`/`ValueError`/`AttributeError`/`KeyError` AND the `try` body contains a `.reduce(` or `build_body(` call (a reduce-path swallow — TypeErrors around reduction launder floor bugs).
2. The handler body does not `raise` (bare or otherwise) on every path. A handler that conditionally re-raises (like `attribute_sugar`'s constructor branch) still counts — partial swallows are swallows.
3. The handler body does not call a sanctioned recorder. Sanctioned recorders, checked structurally (a call whose attribute/function name is in this set inside the handler): `{"record_gap", "gap_record", "append"}` **only when** the handler also references the caught exception variable (i.e. the gap object itself flows into the record — swallowing the gap while appending something else does not sanction).

Exclusions: `tests/**`, `idd/**` collectors' own `PanicRecord` conversion paths (they reference the caught exception into a record — covered by rule 3), and the top-level RPC boundary `lift_rpc.py` handlers that build error responses referencing the exception (also covered by rule 3 via the response constructor call carrying the exception — if rule 3's structural check misses them, extend the sanctioned-call set with the actual function names found there, e.g. the `-32603` response builder; never allowlist by bare filename).

```python
# src/sugar_lift_py_tests/idd/collect_gap_swallow_frontier.py
from __future__ import annotations

import ast
from pathlib import Path
from typing import List

from .gap_swallow_vector import GapSwallowReport, GapSwallowSite

_LOUD_BASES = {"FactoryGap", "RuntimeError", "Exception"}
_REDUCE_ADJACENT = {"TypeError", "ValueError", "AttributeError", "KeyError"}


def _names_in_type(node: ast.expr | None) -> set[str]:
    if node is None:
        return {"<bare>"}
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            names.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            names.add(sub.attr)
    return names


def _try_body_touches_reduction(try_node: ast.Try) -> bool:
    for stmt in try_node.body:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Call):
                fn = sub.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name in {"reduce", "build_body"}:
                    return True
    return False


def _handler_reraises_all_paths(handler: ast.ExceptHandler) -> bool:
    # Conservative: only an unconditional top-level raise counts as loud.
    return any(isinstance(stmt, ast.Raise) for stmt in handler.body) and all(
        not isinstance(stmt, (ast.Return, ast.Continue, ast.Break, ast.Pass))
        for stmt in handler.body
    )


def _handler_records_the_gap(handler: ast.ExceptHandler) -> bool:
    gap_name = handler.name
    if gap_name is None:
        return False
    for stmt in handler.body:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Call):
                arg_names = {
                    a.id for a in ast.walk(sub) if isinstance(a, ast.Name)
                }
                if gap_name in arg_names:
                    return True
    return False


def _disposition(handler: ast.ExceptHandler) -> str:
    for stmt in handler.body:
        if isinstance(stmt, ast.Return):
            return "returns-default"
        if isinstance(stmt, ast.Continue):
            return "continues"
    return "passes"


def collect_gap_swallow_frontier(root: str) -> GapSwallowReport:
    offenders: List[GapSwallowSite] = []
    root_path = Path(root)
    for path in sorted(root_path.rglob("*.py")):
        rel = str(path.relative_to(root_path))
        if rel.startswith("tests/") or "__pycache__" in rel:
            continue
        tree = ast.parse(path.read_text(), filename=rel)  # unparseable file = loud crash, never a skip
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            reduction_adjacent = _try_body_touches_reduction(node)
            for handler in node.handlers:
                names = _names_in_type(handler.type)
                loud = bool(names & _LOUD_BASES) or names == {"<bare>"}
                adjacent = bool(names & _REDUCE_ADJACENT) and reduction_adjacent
                if not (loud or adjacent):
                    continue
                if _handler_reraises_all_paths(handler):
                    continue
                if _handler_records_the_gap(handler):
                    continue
                offenders.append(
                    GapSwallowSite(
                        file=rel,
                        line=handler.lineno,
                        caught=ast.unparse(handler.type) if handler.type else "<bare>",
                        disposition=_disposition(handler),
                    )
                )
    return GapSwallowReport(offenders=tuple(offenders))
```

- [ ] **Step 4: Run the collector by hand; reconcile the gate test**

Run: `PYTHONPATH=src python3 -c "import json; from sugar_lift_py_tests.idd.collect_gap_swallow_frontier import collect_gap_swallow_frontier; print(json.dumps(collect_gap_swallow_frontier('src/sugar_lift_py_tests').to_json(), indent=2))"`

Read every offender it reports. For each: is it a true swallow (goes in `EXPECTED_FRONTIER`) or a sanctioned recorder the structural check missed (extend rule 3's structural check — never a filename allowlist)? Also verify it FINDS the known crimes: if `attribute_sugar.py:48` or the `literal_call_report.py` sites are missing, the collector is wrong — fix the collector, do not celebrate a small list. **An auditor that undercounts is a quiet-failure amplifier; when in doubt, over-report.**

- [ ] **Step 5: Run the gate test**

Run: `PYTHONPATH=src python3 -m pytest -q tests/test_gap_swallow_frontier_audit.py`
Expected: 3 passed (the frontier matches, is red, sanctioned files absent)

- [ ] **Step 6: Wire the CLI flag**

In `src/sugar_lift_py_tests/idd/cli.py`, mirror the existing `--dunder-frontier` flag exactly (same argparse/report/exit-code pattern — read that handler and copy its shape): add `--gap-swallow-frontier`, print `report.to_json()` as JSON, `sys.exit(0 if report.is_zero else 1)`.

Run: `PYTHONPATH=src python3 -m sugar_lift_py_tests.idd.cli --root ../.. --gap-swallow-frontier; echo "exit=$?"`
Expected: JSON report, `exit=1` (red by design).

- [ ] **Step 7: Full suite, format, commit**

Run: `PYTHONPATH=src python3 -m pytest -q tests/` — expected: no new failures.
Run: `python3 -m black src tests`

```bash
git checkout -b gap-swallow-frontier
git add -A
git commit -m "feat(idd): gap-swallow frontier audit -- every quiet failure-to-panic is now a named red row"
```

---

### Task 4: Kill the verifier false-green (`verifier.py`)

`verify_project` (`src/sugar_lift_py_tests/verifier.py:94-106`) and `prove_contract` (`:136-148`) fabricate an all-pass `HandshakeReport` when the CLI exits 0 but stdout is not JSON. Protocol drift must raise `VerifierProtocolError` (Task 2), never infer a verdict.

**Files:**
- Modify: `src/sugar_lift_py_tests/verifier.py:94-116` and `:136-157`
- Test: `tests/test_verifier_protocol.py` (new)

**Interfaces:**
- Consumes: `VerifierProtocolError` from Task 2.
- Produces: `verify_project`/`prove_contract` raise `VerifierProtocolError` on unparseable zero-exit stdout. Callers that previously received the fabricated pass now crash loudly — that is the point.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_verifier_protocol.py
import json
import subprocess
from types import SimpleNamespace

import pytest

from sugar_lift_py_tests import verifier
from sugar_lift_py_tests.verifier import VerifierProtocolError


def _fake_run(stdout: str, returncode: int = 0, stderr: str = ""):
    def run(cmd, capture_output, text, check):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return run


def test_verify_project_raises_on_unparseable_stdout(monkeypatch):
    monkeypatch.setattr(verifier, "find_sugar_cli", lambda: "/usr/bin/sugar")
    monkeypatch.setattr(subprocess, "run", _fake_run("all good, trust me"))
    with pytest.raises(VerifierProtocolError) as exc:
        verifier.verify_project("/tmp/nowhere")
    assert "all good, trust me" in exc.value.stdout


def test_prove_contract_raises_on_unparseable_stdout(monkeypatch):
    monkeypatch.setattr(verifier, "find_sugar_cli", lambda: "/usr/bin/sugar")
    monkeypatch.setattr(subprocess, "run", _fake_run("looks fine"))
    with pytest.raises(VerifierProtocolError):
        verifier.prove_contract("/tmp/contract.json")


def test_verify_project_still_parses_real_reports(monkeypatch):
    payload = json.dumps(
        {
            "success": True,
            "tier1_discharge_fraction": 0.5,
            "tier2_discharge_fraction": 0.25,
            "tier3_remaining": 3,
            "violations": [],
            "summary": "partial",
        }
    )
    monkeypatch.setattr(verifier, "find_sugar_cli", lambda: "/usr/bin/sugar")
    monkeypatch.setattr(subprocess, "run", _fake_run(payload))
    report = verifier.verify_project("/tmp/nowhere")
    assert report.tier1_discharge_fraction == 0.5  # verdict read, never fabricated
```

NOTE: if `HandshakeReport.from_json` uses different field names, read the dataclass at the top of `verifier.py` and match the payload keys to it exactly.

- [ ] **Step 2: Run tests to verify the first two fail**

Run: `PYTHONPATH=src python3 -m pytest -q tests/test_verifier_protocol.py`
Expected: 2 FAIL (no `VerifierProtocolError` raised — fabricated pass returned instead), 1 PASS

- [ ] **Step 3: Replace both fabrication blocks**

In `verify_project`, replace lines 94–106 with:

```python
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise VerifierProtocolError(
                "sugar verify exited 0 but stdout is not the JSON report format; "
                "refusing to fabricate a verdict (owner=python verifier delegate, "
                "blame=sugar CLI stdout, fix=run/parse --json and keep formats in lockstep)",
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return HandshakeReport.from_json(data)
```

In `prove_contract`, replace lines 136–148 with the identical shape (message says `sugar prove`).

- [ ] **Step 4: Run tests to verify all pass**

Run: `PYTHONPATH=src python3 -m pytest -q tests/test_verifier_protocol.py`
Expected: 3 passed

- [ ] **Step 5: Full suite — hunt callers that depended on the lie**

Run: `PYTHONPATH=src python3 -m pytest -q tests/`
If anything fails, it was consuming the fabricated pass. Fix the caller to handle `VerifierProtocolError` explicitly (surface it — do not catch-and-default, which would re-commit the crime and re-redden Task 3's audit).

- [ ] **Step 6: Format, commit**

```bash
python3 -m black src tests
git checkout -b verifier-false-green
git add -A
git commit -m "fix(verifier): unparseable CLI reply raises VerifierProtocolError -- a verdict is never fabricated"
```

---

### Task 5: Drain `attribute_sugar` — structured discrimination, no laundering

`desugar` (`src/sugar_lift_py_tests/sugar/attribute_sugar.py:46-53`) swallows every non-"constructor" `FactoryGap` and every `TypeError` into `Complete(SymbolicValue(...))`, gated by substring-sniffing (`_is_constructor_gap`, lines 76–86). Additionally lines 57–60 pre-empt `perform_operation`'s gap panic with a `hasattr` soft path.

The honest semantics: `AttributeSugar.owns`/`build` decide up front (via `_projectable_receiver`) whether the receiver is projectable; if it is, a gap during its reduction is REAL and must propagate. The symbolic fallback is legitimate only for the `receiver is None` path (recognition refused projection — an explicit, recorded decision at build time).

**Files:**
- Modify: `src/sugar_lift_py_tests/sugar/attribute_sugar.py`
- Modify: `tests/test_gap_swallow_frontier_audit.py` (ratchet: delete both `attribute_sugar` rows)
- Test: `tests/test_attribute_sugar_gaps.py` (new)

**Interfaces:**
- Consumes: `gap.info["gap_kind"]` (Task 1), gap-swallow frontier gate (Task 3).
- Produces: `AttributeSugar.desugar` propagates all gaps; the `hasattr` guard is removed in favor of `perform_operation`'s own `FactoryGap`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_attribute_sugar_gaps.py
import pytest

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditRow
from sugar_lift_py_tests.factory.factory_gap_info import FactoryGapInfo
from sugar_lift_py_tests.ir import str_const
from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar


class _GapBody:
    """A SugarBody stand-in whose reduce raises a non-constructor floor gap."""

    def reduce(self, ctx):
        raise FactoryGap(
            FactoryGapInfo(
                owner="test", blame="t.py:1", observed="Call",
                requested="reduce a receiver", fix="write more Floor",
                gap_kind="Floor", gap_locus="Reduce",
            ),
            FactoryAuditRow(status="floor-gap"),
        )


def test_desugar_propagates_floor_gaps():
    sugar = AttributeSugar(
        term=str_const("t"), receiver=_GapBody(), name="x", blame="t.py:1"
    )
    with pytest.raises(FactoryGap):
        sugar.desugar(ctx=None)


def test_desugar_propagates_type_errors():
    class _Boom:
        def reduce(self, ctx):
            raise TypeError("a reduce bug, not a recognition miss")

    sugar = AttributeSugar(
        term=str_const("t"), receiver=_Boom(), name="x", blame="t.py:1"
    )
    with pytest.raises(TypeError):
        sugar.desugar(ctx=None)
```

NOTE: check `FactoryAuditRow`'s actual constructor signature (`src/sugar_lift_py_tests/factory/factory_audit_row.py`) and match it; the audit found `FactoryAuditRow(status="floor-gap"...)` used in `perform_operation`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest -q tests/test_attribute_sugar_gaps.py`
Expected: both FAIL — desugar returns `Complete(SymbolicValue(...))` instead of raising.

- [ ] **Step 3: Rewrite `desugar` — delete the swallows and the hasattr pre-emption**

Replace `desugar` (lines 43–73) with:

```python
    def desugar(self, ctx) -> Outcome:
        if self.receiver is None:
            # Recognition refused projection at build time -- the one honest
            # symbolic fallback. Everything past this line owns the receiver.
            return Complete(SymbolicValue(self.term))
        receiver_outcome = self.receiver.reduce(ctx)
        if isinstance(receiver_outcome, Incomplete):
            return receiver_outcome
        receiver = receiver_outcome.value
        if isinstance(receiver, SymbolicValue):
            # A symbolic receiver reduces honestly to a symbolic attribute.
            return Complete(SymbolicValue(self.term))
        operation = AttributeLookupOperation(
            name=self.name,
            owner="AttributeSugar",
            blame=self.blame,
        )
        return perform_operation(
            owner="AttributeSugar",
            blame=self.blame,
            receiver=receiver,
            method_name="attribute_with",
            operation=operation,
            ctx=ctx,
        )
```

Delete `_is_constructor_gap` entirely (its only caller is gone; the structured `gap_kind` from Task 1 means any future discriminator reads `gap.info["gap_kind"]`, never message text). Note the `hasattr(receiver, "attribute_with")` guard is gone: a floor value without `attribute_with` now reaches `perform_operation`, which raises the proper `FactoryGap("floor-gap")` naming the missing method — that is the design working.

- [ ] **Step 4: Run the new tests**

Run: `PYTHONPATH=src python3 -m pytest -q tests/test_attribute_sugar_gaps.py`
Expected: 2 passed

- [ ] **Step 5: Full suite — triage every newly-red test as a genuine finding**

Run: `PYTHONPATH=src python3 -m pytest -q tests/ 2>&1 | tee /tmp/attr-drain.log`

Every failure is a case the swallow was hiding. For each, classify:
- **Receiver should never have been projectable** → tighten `_projectable_receiver` (recognition refusing at build time is honest), OR
- **A floor value legitimately lacks `attribute_with`** → write the floor method (write more Floor), OR
- **A construct genuinely can't be owned yet** → leave the test red and record it: the failure IS the instrument. Do not re-add the swallow. If the count is large, split the leftover into its own frontier slice PR — but the swallow does not come back.

- [ ] **Step 6: Ratchet the gap-swallow gate**

In `tests/test_gap_swallow_frontier_audit.py`, delete the two `attribute_sugar` rows from `EXPECTED_FRONTIER`. Run: `PYTHONPATH=src python3 -m pytest -q tests/test_gap_swallow_frontier_audit.py` — expected: passed (frontier shrank by exactly two).

- [ ] **Step 7: Format, commit**

```bash
python3 -m black src tests
git checkout -b attribute-sugar-drain
git add -A
git commit -m "fix(sugar): attribute desugar propagates gaps -- no more laundering unknown constructs into SymbolicValue"
```

---

### Task 6: The digger stops swallowing — every refusal becomes a recorded row

`literal_call_report.py`'s transitive digger catches `(TypeError, ValueError, FactoryGap)` at ~940 (`return None`) and ~994 (`continue`), plus siblings at ~760, ~1082, ~1206, ~1239 and getsource fallbacks ~1503–1514. Design intent ("leave the bridge as an axiom") is a legitimate *refusal* — the crime is that the refusal is invisible. Fix: keep the refusal semantics, make every refusal a recorded `DigRefusal` row that flows into the factory audit, and drop `FactoryGap` from the tuple only where the gap is NOT a refusal (a gap during the TOP-arg build at 940 means the caller's own expression is unowned — that must propagate).

**Files:**
- Create: `src/sugar_lift_py_tests/factory/dig_refusal.py`
- Modify: `src/sugar_lift_py_tests/factory/literal_call_report.py` (all catch sites)
- Modify: `src/sugar_lift_py_tests/idd/collect_gap_swallow_frontier.py` — no change needed if Task 3's rule 3 recognizes the recorder (the caught exception flows into `DigRefusal`); verify.
- Modify: `tests/test_gap_swallow_frontier_audit.py` (ratchet: remove `literal_call_report` rows)
- Test: `tests/test_dig_refusal_ledger.py` (new)

**Interfaces:**
- Produces: `DigRefusal(callee: str, blame: str, caught: str, reason: str)` with `to_json()`; `literal_call_report` gains a module-level entry point change: the report function's return value now includes `dig_refusals: list[DigRefusal]` alongside its facts (find the function that aggregates `facts` and thread the list up to whatever DTO/row the report already emits — follow the existing `facts` plumbing exactly; the RPC surface must carry the refusals so the Rust side and the audit CLIs can see them: **MCP/RPC rows return full data, never stripped**).

- [ ] **Step 1: Write `DigRefusal`**

```python
# src/sugar_lift_py_tests/factory/dig_refusal.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class DigRefusal:
    """A tower the digger declined to climb -- refused, loudly, on the record.

    A refusal is honest (the bridge stays an axiom; the vendor's word stands).
    An UNRECORDED refusal is a quiet failure: transitive coverage shrinks and
    no instrument sees it. Every catch in the digger constructs one of these.
    """

    callee: str
    blame: str
    caught: str
    reason: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "kind": "dig-refusal",
            "callee": self.callee,
            "blame": self.blame,
            "caught": self.caught,
            "reason": self.reason,
        }
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_dig_refusal_ledger.py
import textwrap

# Adjust import to the actual public entry point of literal_call_report --
# find the function the factory walk calls (rg -n "def .*report" src/sugar_lift_py_tests/factory/literal_call_report.py)
from sugar_lift_py_tests.factory import literal_call_report


def test_unpeelable_callee_body_yields_a_recorded_refusal(tmp_path):
    # f's body contains a construct the catalog cannot peel transitively
    # (a lambda with default args is exotic enough today; if the catalog
    # learns it, swap in a construct from the current dunder frontier).
    source = textwrap.dedent(
        """
        def f(x):
            g = lambda y=[]: y
            return g(x)

        def caller():
            assert f(1) == 1
        """
    )
    path = tmp_path / "mod.py"
    path.write_text(source)
    result = literal_call_report.<ENTRY_POINT>(str(path))
    refusals = [r for r in result.dig_refusals]
    assert refusals, "an unpeelable tower must be refused ON THE RECORD"
    assert refusals[0].callee == "f"
```

NOTE: `<ENTRY_POINT>` is a plan-time unknown — resolve it in Step 2 by reading the function that currently constructs and returns the facts list (the audit located the worklist loop at lines ~950–1030; walk up to its enclosing `def`). Fix the test to call it the way `lift_rpc`/the factory walk calls it. If the entry point returns a plain list of `LiftResult`, change it to return a small result object `(facts, dig_refusals)` and update its callers (rg for the function name; the audit indicates callers live in `lift_rpc.py` and the factory walk).

- [ ] **Step 3: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest -q tests/test_dig_refusal_ledger.py`
Expected: FAIL (`dig_refusals` attribute does not exist)

- [ ] **Step 4: Convert every catch site**

At each site, the pattern converts from swallow to record-and-refuse. Site ~994 becomes:

```python
        try:
            outcome = build_ctx.build_body(
                Block.of(callee.node.body), SugarRole.STATEMENT
            ).reduce(reduce_ctx)
        except (TypeError, ValueError, FactoryGap) as exc:
            dig_refusals.append(
                DigRefusal(
                    callee=cn,
                    blame=callee.blame,
                    caught=type(exc).__name__,
                    reason=str(exc),
                )
            )
            continue  # bridge stays an axiom -- refused, on the record
```

Site ~940 (TOP-arg build) is different — the top arg belongs to the CALLER's own assertion, not a transitive tower. A `FactoryGap` there means the caller's expression is unowned and must propagate:

```python
    try:
        top = build_ctx.build_body(callsite.call_args()[0], SugarRole.TERM).reduce(
            ReduceContext(temporal=TemporalContext.empty())
        )
    except (TypeError, ValueError) as exc:
        dig_refusals.append(
            DigRefusal(
                callee=callee_name,
                blame=callsite.blame,
                caught=type(exc).__name__,
                reason=f"top arg did not slam to a concrete value: {exc}",
            )
        )
        return None
```

(`FactoryGap` removed from the tuple: it now propagates. Run the suite; if propagation breaks a legitimate defer-to-symbolic case, that case is a genuine finding — the symbolic universe path must OWN the construct via recognition, not catch the panic.)

Apply the record-and-refuse conversion to the remaining sites (~760, ~1082, ~1206, ~1239, ~1503–1514) — read each in place; the getsource fallbacks record `caught="OSError"`-style refusals for unreadable source. Thread one `dig_refusals: list[DigRefusal]` through the enclosing function signatures to the entry point's return value.

- [ ] **Step 5: Run the new test, then the full suite**

Run: `PYTHONPATH=src python3 -m pytest -q tests/test_dig_refusal_ledger.py` — expected: PASS.
Run: `PYTHONPATH=src python3 -m pytest -q tests/` — triage any failure from the 940 `FactoryGap` propagation per Step 4's note.

- [ ] **Step 6: Verify the swallow auditor now sanctions these sites, and ratchet**

Run the collector by hand (Task 3 Step 4 command). The converted sites must no longer appear (rule 3: the caught exception flows into `DigRefusal(...)`). Delete the `literal_call_report` rows from `EXPECTED_FRONTIER`. If the auditor still flags a converted site, the recorder-recognition rule is too narrow — fix the AUDITOR only if the site genuinely records the gap object; never widen the rule beyond "the caught exception reaches a constructor/append."

Run: `PYTHONPATH=src python3 -m pytest -q tests/test_gap_swallow_frontier_audit.py` — expected: PASS with shrunken frontier.

- [ ] **Step 7: Format, commit**

```bash
python3 -m black src tests
git checkout -b digger-refusal-ledger
git add -A
git commit -m "fix(factory): every dig refusal is a recorded row -- transitive coverage cannot shrink invisibly"
```

---

### Task 7: `floor_to_term` becomes floor-owned; the duplicate dies; a gate holds the door

`sugar/floor_terms.py:20-49` is a 7-way isinstance ladder over FloorValue subtypes, duplicated at `factory/literal_call_report.py:688-707`. The projection belongs to each floor value. Single dispatch via a `to_term` method on the `FloorValue` base (base implementation gap-panics "write more Floor") — adding a new FloorValue forces the method or panics loudly at first projection. This is right-sized: a pure projection needs value-ownership, not the full `perform_operation` operation-object machinery (there is no operation logic to vary — reserve `perform_operation` for semantic ops).

**Files:**
- Modify: `src/sugar_lift_py_tests/floor/floor_value.py` (base `to_term` that gap-panics)
- Modify: each floor value module that appears in the ladder: `floor/term_value.py`, `floor/bool_value.py`, `floor/string_value.py`, `floor/symbolic_value.py`, `floor/bv32_value.py`, `floor/call_site_value.py`, `floor/object_value.py`, `floor/array_literal.py`, `floor/tuple_literal_value.py`, `floor/slice_value.py` (exact filenames: confirm with `ls src/sugar_lift_py_tests/floor/`)
- Modify: `src/sugar_lift_py_tests/sugar/floor_terms.py` (becomes a thin delegator, kept so callers don't churn)
- Modify: `src/sugar_lift_py_tests/factory/literal_call_report.py` (delete `_floor_to_term` at 688–707; import `floor_to_term`)
- Create: `tests/test_floor_projection_gate.py` (behavior + door-holding gate)

**Interfaces:**
- Produces: `FloorValue.to_term(self, *, owner: str) -> Term`; `floor_to_term(value, *, owner)` delegates to it. The gate test forbids new isinstance-ladders over FloorValue subtypes outside `floor/` and `operations/`.

- [ ] **Step 1: Write the failing behavior tests**

```python
# tests/test_floor_projection_gate.py
import ast
from pathlib import Path

import pytest

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.floor import BoolValue, FloorValue, TermValue
from sugar_lift_py_tests.ir import bool_const, num
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term


def test_term_value_projects_via_ownership():
    assert TermValue(3).to_term(owner="test") == num(3)
    assert floor_to_term(TermValue(3), owner="test") == num(3)


def test_bool_value_projects_via_ownership():
    assert BoolValue(True).to_term(owner="test") == bool_const(True)


def test_unprojectable_floor_value_gap_panics():
    class NewFloor(FloorValue):
        pass

    with pytest.raises(FactoryGap) as exc:
        NewFloor().to_term(owner="test")
    assert exc.value.info["gap_kind"] == "Floor"
```

NOTE: `TermValue(3)`/`BoolValue(True)` constructor shapes: confirm against the dataclass definitions before finalizing; `TermValue` carries `.value` per `floor/term_value.py:10`.

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python3 -m pytest -q tests/test_floor_projection_gate.py`
Expected: FAIL (`FloorValue` has no `to_term`)

- [ ] **Step 3: Implement — base gap-panic plus one method per floor value**

Base, in `floor/floor_value.py`:

```python
    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.factory import FactoryGap
        from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditRow
        from sugar_lift_py_tests.factory.factory_gap_info import FactoryGapInfo

        raise FactoryGap(
            FactoryGapInfo(
                owner=owner,
                blame=type(self).__name__,
                observed=type(self).__name__,
                requested="project this floor value to a term",
                fix=f"write more Floor: implement {type(self).__name__}.to_term",
                gap_kind="Floor",
                gap_locus="Projection",
            ),
            FactoryAuditRow(status="floor-gap"),
        )
```

(Local imports break the floor→factory circular dependency; `perform_operation` already imports `FactoryGap` — mirror however it does it. Confirm `FactoryAuditRow(status=...)` signature as in Task 5.)

Then move each ladder branch onto its class — the bodies are the existing branches from `floor_terms.py:21-46` verbatim, e.g. in `floor/term_value.py`:

```python
    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import num

        return num(self.value)
```

`ObjectValue.to_term` gets the `py.object.identity` ctor branch; `ArrayLiteral`/`TupleLiteralValue` recurse via `item.to_term(owner=owner)`; `SliceValue` keeps the optional-handling (move `_optional_slice_term` logic into its method: `ctor("None", []) if part is None else part.to_term(owner=owner)`); `SymbolicValue`/`Bv32Value`/`CallSiteValue` return `self.term` (three one-liners, one per class — no shared mixin unless those classes already share a base).

Rewrite `sugar/floor_terms.py` as the thin delegator:

```python
from __future__ import annotations

from typing import Any

from sugar_lift_py_tests.ir import Term


def floor_to_term(value: Any, *, owner: str) -> Term:
    return value.to_term(owner=owner)
```

In `factory/literal_call_report.py`: delete `_floor_to_term` (lines 688–707), add `from sugar_lift_py_tests.sugar.floor_terms import floor_to_term`, and replace every `_floor_to_term(x)` with `floor_to_term(x, owner="literal_call_report")` (rg for `_floor_to_term(` to catch all call sites).

- [ ] **Step 4: Run behavior tests, then full suite**

Run: `PYTHONPATH=src python3 -m pytest -q tests/test_floor_projection_gate.py` — expected: 3 passed.
Run: `PYTHONPATH=src python3 -m pytest -q tests/` — the ladder was total over its known types, so parity is expected; any failure means a `to_term` body diverged from its ladder branch — diff against the original `floor_terms.py` branch verbatim.

- [ ] **Step 5: Add the door-holding gate to the same test file**

```python
_FLOOR_TYPES = {
    "TermValue", "BoolValue", "StringValue", "SymbolicValue", "Bv32Value",
    "CallSiteValue", "ObjectValue", "ArrayLiteral", "TupleLiteralValue",
    "SliceValue", "BoundVar", "BuilderState", "BlockValue", "ReturnValue",
    "RaiseValue", "PredicateValue",
}
_ALLOWED_DIRS = ("floor/", "operations/")
_LADDER_THRESHOLD = 3  # >=3 isinstance checks on floor types in one function = a ladder


def test_no_floorvalue_isinstance_ladders_outside_the_floor():
    src = Path(__file__).resolve().parent.parent / "src" / "sugar_lift_py_tests"
    offenders = []
    for path in sorted(src.rglob("*.py")):
        rel = str(path.relative_to(src))
        if rel.startswith(_ALLOWED_DIRS) or "__pycache__" in rel:
            continue
        tree = ast.parse(path.read_text(), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            hits = 0
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == "isinstance"
                    and len(sub.args) == 2
                ):
                    type_names = {
                        n.id for n in ast.walk(sub.args[1]) if isinstance(n, ast.Name)
                    }
                    if type_names & _FLOOR_TYPES:
                        hits += 1
            if hits >= _LADDER_THRESHOLD:
                offenders.append(f"{rel}:{node.lineno} {node.name} ({hits} checks)")
    assert not offenders, (
        "FloorValue projection ladders outside floor/+operations/ -- "
        "the value owns its projection; write to_term/a floor method instead:\n"
        + "\n".join(offenders)
    )
```

Run it. Known borderline from the audit: `sugar/block_sugar.py:59-85` (5-type ladder — block sequencing, arguably the block reducer's inherent job). If it trips the gate, make the call: either sequencing types (`BoundVar/ReturnValue/RaiseValue/BlockValue/SupportValue`) get excluded from `_FLOOR_TYPES` as *sequencing* values (document why in a comment), or `block_sugar` is added to a named-with-reason ratchet list in the test that new code cannot join. Prefer the ratchet list — it keeps the pressure visible. Same decision for `membership_assertion_sugar.py:76-84` if it hits the threshold.

- [ ] **Step 6: Format, commit**

```bash
python3 -m black src tests
git checkout -b floor-to-term-ownership
git add -A
git commit -m "refactor(floor): floor values own their term projection -- ladder deleted, duplicate deleted, gate holds the door"
```

---

### Task 8: Close the factory bypass in `array_map_report` + give root contexts a front door

Two crimes in `factory/array_map_report.py`: line 166 hand-picks `MapSugar.build(call, factory_ctx)` instead of factory dispatch, and line 174 hand-threads `ReduceContext(temporal=factory_ctx.temporal)`. Plus the temporal auditor is blind to raw `ReduceContext(temporal=...)` minting anywhere. Fix the bypass, add a sanctioned named constructor for root reduce contexts, and teach the auditor to flag raw minting.

**Files:**
- Modify: `src/sugar_lift_py_tests/context/reduce_context.py` (add `root()` classmethod — confirm exact path with `rg -n "class ReduceContext" src/`)
- Modify: `src/sugar_lift_py_tests/factory/array_map_report.py:161-176`
- Modify: `src/sugar_lift_py_tests/factory/literal_call_report.py:938,980` (use the front door)
- Modify: `src/sugar_lift_py_tests/idd/collect_temporal_dispatch_frontier.py` + `idd/temporal_dispatch_vector.py` (new offender kind)
- Test: `tests/test_reduce_context_root.py` (new) + extend `tests/test_temporal_dispatch_frontier.py`

**Interfaces:**
- Produces: `ReduceContext.root(*, owner: str, dig_sink=None) -> ReduceContext` (fresh empty temporal — THE sanctioned way to mint a root reduction environment) and `ReduceContext.derived(factory_ctx, *, owner: str) -> ReduceContext` (carries an existing temporal forward). New auditor offender field `direct_context_minting: tuple[str, ...]`.

- [ ] **Step 1: Write the failing test for the front door**

```python
# tests/test_reduce_context_root.py
from sugar_lift_py_tests.context.reduce_context import ReduceContext


def test_root_mints_empty_temporal():
    ctx = ReduceContext.root(owner="test")
    assert ctx.temporal.bindings == ()


def test_derived_carries_temporal_forward():
    base = ReduceContext.root(owner="test")
    from sugar_lift_py_tests.temporal import bind_temporal

    bound = bind_temporal(base, "x", object(), owner="test", blame="t:1")
    derived = ReduceContext.derived(bound, owner="test")
    assert derived.temporal is bound.temporal
```

NOTE: adjust the import path and `derived`'s parameter (it takes anything exposing `.temporal` — factory build contexts and reduce contexts both qualify; read `ReduceContext`'s fields first and preserve `dig_sink`/other fields in `derived` by copying them from the source context where present).

- [ ] **Step 2: Run to verify failure, implement the two classmethods**

Run: `PYTHONPATH=src python3 -m pytest -q tests/test_reduce_context_root.py` — expected: FAIL (no attribute `root`).

In `context/reduce_context.py` (match the actual dataclass fields — `temporal`, `dig_sink`, and whatever else exists):

```python
    @classmethod
    def root(cls, *, owner: str, dig_sink=None) -> "ReduceContext":
        """THE front door for a fresh reduction environment.

        Raw ReduceContext(temporal=...) construction outside context/ and
        temporal/ is a side door the temporal auditor flags: a hand-built
        context can thread a stale temporal past scope capture.
        """
        from sugar_lift_py_tests.temporal import TemporalContext

        return cls(temporal=TemporalContext.empty(), dig_sink=dig_sink)

    @classmethod
    def derived(cls, source, *, owner: str) -> "ReduceContext":
        return cls(
            temporal=source.temporal,
            dig_sink=getattr(source, "dig_sink", None),
        )
```

Run the test again — expected: 2 passed.

- [ ] **Step 3: Convert the raw minting sites**

- `factory/literal_call_report.py:938` → `ReduceContext.root(owner="literal_call_report.top_arg")`
- `factory/literal_call_report.py:980` → `ReduceContext.root(owner="literal_call_report.tower", dig_sink=sink)`
- `factory/array_map_report.py:174` → `ReduceContext.derived(factory_ctx, owner="array_map_report")`
- Sweep the rest: `rg -n "ReduceContext\(" src/ --type py` — convert every hit outside `context/`, `temporal/`, and the classmethods themselves.

- [ ] **Step 4: Close the `MapSugar.build` bypass**

In `factory/array_map_report.py:166`, replace:

```python
    map_sugar = MapSugar.build(call, factory_ctx)
```

with factory dispatch (the receiver two lines up already goes through `factory_ctx.build_body` — same door):

```python
    map_body = factory_ctx.build_body(call, SugarRole.TERM)
```

and replace the subsequent `map_sugar.desugar(reduce_ctx)` with `map_body.reduce(reduce_ctx)` (line ~175). If the factory dispatches `call` to a different sugar than `MapSugar`, that is a recognition finding: either `MapSugar.owns` is too narrow (fix `owns`) or this report was force-feeding constructs `MapSugar` never claimed (the bypass was hiding a recognition lie — fix whichever is true, guided by which sugar `owns()` actually selects; add `comes_before` ordering only if genuine ambiguity exists). Check `expected_sugar` at line ~176 for the same pattern and convert it identically.

- [ ] **Step 5: Extend the temporal auditor with the new offender kind**

In `idd/temporal_dispatch_vector.py`, add field `direct_context_minting: tuple[str, ...]` to the vector (mirror the three existing offender-kind fields exactly, including `to_json` and the total). In `idd/collect_temporal_dispatch_frontier.py`, flag any `ast.Call` whose func resolves to name `ReduceContext` with a `temporal=` keyword, outside `context/` and `temporal/`:

```python
def _is_direct_context_minting(node: ast.Call) -> bool:
    name = (
        node.func.attr if isinstance(node.func, ast.Attribute)
        else getattr(node.func, "id", "")
    )
    if name != "ReduceContext":
        return False
    return any(kw.arg == "temporal" for kw in node.keywords)
```

(`ReduceContext.root(...)`/`.derived(...)` don't match: their func is an `ast.Attribute` with `attr in {"root", "derived"}` — exclude attribute-calls whose `attr` is not `ReduceContext`, i.e. the check above already only matches a call *named* `ReduceContext`.) Extend `tests/test_temporal_dispatch_frontier.py`: assert the frontier is STILL zero after Step 3's conversions, and add a unit test feeding the collector a synthetic source string containing `ReduceContext(temporal=TemporalContext.empty())` and asserting it is flagged (discrimination test: the positive case).

- [ ] **Step 6: Full suite, format, commit**

Run: `PYTHONPATH=src python3 -m pytest -q tests/` — expected: no new failures (temporal frontier still zero, array-map tests green through the factory door).

```bash
python3 -m black src tests
git checkout -b array-map-factory-bypass
git add -A
git commit -m "fix(factory): array-map goes through the factory door; root reduce contexts get a named front door the auditor watches"
```

---

### Task 9: Boundary borderlines — RPC parse errors, DTO defaults, truthy pre-build, Rust-side verdict confirmation

Four smaller drains, one commit each on one branch.

**Files:**
- Modify: `src/sugar_lift_py_tests/lift_rpc.py:37-45` (+ main loop)
- Modify: `src/sugar_lift_py_tests/kit_rpc/factory_walk_row_dto.py:35-42`
- Modify: `src/sugar_lift_py_tests/sugar/truthy_assertion_sugar.py:73-77`
- Modify: `tests/test_gap_swallow_frontier_audit.py` (ratchet as rows drain)
- Test: `tests/test_lift_rpc_parse_error.py`, `tests/test_factory_walk_row_dto.py` (extend or create), `tests/test_truthy_assertion_gaps.py`

**9a — `_recv` stops conflating garbage with EOF.**

- [ ] **Step 1: Failing test**

```python
# tests/test_lift_rpc_parse_error.py
import io
import json
import sys

import pytest

from sugar_lift_py_tests import lift_rpc


def test_recv_distinguishes_garbage_from_eof(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("this is not json\n"))
    result = lift_rpc._recv()
    assert result is lift_rpc.PARSE_ERROR  # sentinel, not None
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert lift_rpc._recv() is None  # EOF is still None
```

- [ ] **Step 2: Implement** — add a module-level sentinel and return it on decode failure; in the main loop (~line 553), on `PARSE_ERROR` send a JSON-RPC `-32700` error response and `continue` (do not break); only `None` (true EOF) breaks:

```python
PARSE_ERROR = object()


def _recv():
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return PARSE_ERROR
    return value if isinstance(value, dict) else PARSE_ERROR
```

Main loop change (read the actual loop first; shape):

```python
        msg = _recv()
        if msg is None:
            break
        if msg is PARSE_ERROR:
            _send({"jsonrpc": "2.0", "id": None,
                   "error": {"code": -32700, "message": "parse error: line was not a JSON-RPC object"}})
            continue
```

- [ ] **Step 3:** Run `PYTHONPATH=src python3 -m pytest -q tests/test_lift_rpc_parse_error.py` (PASS), full suite, black, commit: `fix(rpc): a garbage line answers -32700 and the server lives; only EOF terminates`.

**9b — unknown walk-row status panics instead of defaulting.**

- [ ] **Step 1: Failing test** (in `tests/test_factory_walk_row_dto.py`):

```python
import pytest

from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import FactoryWalkRowDto


def test_unknown_status_panics_instead_of_defaulting(minimal_row_kwargs=None):
    row = FactoryWalkRowDto(
        file="f.py", line=1, requested_role="TERM", ast_kind="Call",
        selected=None, status="brand-new-status", output=None, source_memento={},
    )
    with pytest.raises(ValueError, match="brand-new-status"):
        row.to_rpc()
```

- [ ] **Step 2: Implement** — in `to_rpc()` replace the `.get(status, "incomplete")` at line 36–41:

```python
        verdict_by_status = {
            "warranted": "complete",
            "support": "complete",
            "refused": "incomplete",
            "unresolved": "gap",
        }
        if status not in verdict_by_status:
            raise ValueError(
                f"unowned factory walk status {status!r}: add it to verdict_by_status "
                "deliberately -- a defaulted verdict is a quiet failure"
            )
        verdict = verdict_by_status[status]
```

- [ ] **Step 3:** Test PASS, full suite (any failure = a status value the default was hiding: add it deliberately with the correct verdict), black, commit: `fix(kit_rpc): unknown walk status raises -- verdicts are never defaulted`.

**9c — truthy pre-build swallow records instead of silently opaquing.**

Design decision embedded here: falling back to the opaque `py.truthy` atomic IS legitimate (the assertion stays sound — it's just weaker), but a `FactoryGap` during pre-build must not vanish. Since `build` runs at walk time with the factory audit in reach, convert the swallow into a recorded refusal via the factory walk row's `reason` field. Minimal honest version:

- [ ] **Step 1: Failing test** (`tests/test_truthy_assertion_gaps.py`): assert that when `_projectable_truth_body`'s build gaps, the constructed sugar carries `term_body is None` AND `degraded_reason` naming the gap:

```python
from sugar_lift_py_tests.sugar.truthy_assertion_sugar import TruthyAssertionSugar
# build a site whose assert_test triggers a FactoryGap (use a construct off
# the current dunder frontier, e.g. one of the open attribute_descriptor slots)
# then:
# assert sugar.term_body is None and sugar.degraded_reason.startswith("write more")
```

- [ ] **Step 2: Implement** — `_projectable_truth_body` returns `tuple[SugarBody | None, str | None]`:

```python
def _projectable_truth_body(site, ctx):
    try:
        return ctx.build_body(site.assert_test(), SugarRole.TERM), None
    except FactoryGap as gap:
        return None, gap.info["fix"]
    except TypeError as exc:
        return None, f"pre-build type error: {exc}"
```

Add field `degraded_reason: str | None` to the dataclass; `build` unpacks the tuple. Where the factory walk row for this assertion is emitted, thread `degraded_reason` into the row's `reason` field (rg for where truthy assertion rows are built). Keep `desugar` unchanged (it already re-raises `FactoryGap` at reduce time — but note its `except TypeError: return self.assertion_formula()` at line 56 stays on the swallow frontier from Task 3 pinned as a named row; drain it here too if the suite allows: delete the TypeError catch, triage failures the same way as Task 5 Step 5).

- [ ] **Step 3:** Test PASS, full suite, ratchet `EXPECTED_FRONTIER` (remove the `truthy_assertion_sugar` row(s) now sanctioned/drained), black, commit: `fix(sugar): truthy pre-build degradation is recorded, never silent`.

**9d — confirm the Rust verifier never trusts `verdict: "holds"`.**

- [ ] **Step 1:** From repo root: `rg -n '"verdict"|\bverdict\b' implementations/rust/ --type rust -l` then read each hit. Question to answer: does any Rust code path read the envelope's `verdict` field as an INPUT to discharge (crime — the memcmp/recompute must be the only verdict source), or is it only ever WRITTEN/echoed?
- [ ] **Step 2:** If read-as-input anywhere: STOP, report the finding — that is a new crime outside this plan's scope (Rust-side fix, soundness-critical, own PR).
- [ ] **Step 3:** If write-only: add the one-line doc note at the `claim_envelope.py` minting sites (465, 556, 636): `# authoring-time claim only: the substrate verifier recomputes; it never reads this field (verified 2026-07: rust verify path)` and a comment-free conscience: nothing further. Commit with 9c: `docs(claim): pin the verdict-is-write-only invariant`.

---

## Follow-ups deliberately OUT of scope (named so they aren't quietly dropped)

- `lift/pydantic.py:302` `except Exception: return False` on `is_required()` — best-effort native-surface lift with loss records; wants the loss-record treatment (record the dropped `≠ None` precondition), not a panic. Own slice after Task 3 pins it as a named frontier row.
- `constraint_flow/dig_constraint_universe.py:26-29` `except TypeError: continue` — pinned by Task 3's frontier; drain shape = record-and-refuse like Task 6.
- Async operations wrapping `TypeError` into `Incomplete(RuntimeEffect)` (`operations/await_operation.py:30` et al.) — needs a design call on distinguishing "genuinely opaque callsite" from "dunder-reduction bug"; the structured `gap_kind` from Task 1 is the tool. Own slice.
- The `literal_call_report.py` mini-interpreter (`_ctx_with_prior_assignments`, `Block.of(callee.node.body)` re-walks) — a second reduction engine parallel to the factory. Task 6 makes its refusals loud; DELETING it in favor of factory-owned transitive digging is a bigger architectural slice (touches the tower-digging design). Flag for the architect: this is the largest remaining structural debt in the file.
- `XSugar.build`-bypass gate (generalizing Task 8 Step 4 into an auditor that flags any direct `SomeSugar.build(`/`.desugar(` call outside `factory/build.py` + tests) — natural successor instrument once Task 8 proves the pattern.

## Self-review notes

- Every task's audit-facing change ends with the gap-swallow gate green on a SHRUNKEN frontier — the ratchet is the review.
- Line numbers cited are from main @ `678b4a116` (#2978); they will drift — every step that edits code anchors on the quoted code shape, not the line number.
- Plan-time unknowns are named in-place with the exact command to resolve them (Task 6 `<ENTRY_POINT>`, Task 1 Step 5 grep, constructor signatures for `FactoryAuditRow`) rather than guessed.
