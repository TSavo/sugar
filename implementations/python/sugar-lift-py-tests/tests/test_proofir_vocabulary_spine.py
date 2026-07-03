from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from sugar_lift_py_tests.factory.literal_call_report import euf_callsite_name
from sugar_lift_py_tests.factory.factory_gap import FactoryGap
from sugar_lift_py_tests.ir import (
    Bool,
    Int,
    eq,
    make_var,
    num,
)
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.idd.proofir_vocab_instruments import (
    collect_proofir_vocabulary_frontier,
)
from sugar_lift_py_tests.proofir import (
    CallTerm,
    ConstTerm,
    ConstructionSite,
    Derived,
    Eq,
    EqualityFact,
    FunctionContract,
    BoolSort,
    IntSort,
    PostCondition,
    ProofIRNode,
    Provenance,
    REGISTERED_PROOFIR_NODE_CLASSES,
    RefusalRecord,
    Stated,
    VarTerm,
    canonical_euf_callsite_name,
    merge_equality_facts,
)


ROOT = Path(__file__).resolve().parents[4]
RUST_WORKSPACE = ROOT / "implementations" / "rust"
PY_TESTS = ROOT / "implementations" / "python" / "sugar-lift-py-tests"
PY_SOURCE = ROOT / "implementations" / "python" / "sugar-lift-python-source"
PY_PYTEST_WITNESS = ROOT / "implementations" / "python" / "sugar-lift-py-pytest-witness"
SUGAR_BIN = RUST_WORKSPACE / "target" / "debug" / "sugar"
_SUGAR_BUILT = False


def _construction_site() -> ConstructionSite:
    return ConstructionSite(path="tests/proofir_spine.py", line=7, column=3)


def _stated_provenance(node_class: str) -> Provenance:
    return Provenance(
        node_class=node_class,
        construction_site=_construction_site(),
        warrant=Stated(locus=_construction_site()),
    )


def _derived_provenance(node_class: str) -> Provenance:
    return Provenance(
        node_class=node_class,
        construction_site=_construction_site(),
        warrant=Derived(floor_chain=("CallSiteValue.force_floor",)),
    )


def _two_warrant_provenance(node_class: str) -> Provenance:
    return Provenance(
        node_class=node_class,
        construction_site=_construction_site(),
        warrant=(
            Stated(locus=_construction_site()),
            Derived(floor_chain=("CallSiteValue.force_floor",)),
        ),
    )


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
            ["cargo", "build", "--locked", "-p", "sugar-cli", "--bin", "sugar"],
            cwd=RUST_WORKSPACE,
            text=True,
            capture_output=True,
            check=False,
            timeout=180,
        )
        assert completed.returncode == 0, completed.stderr
        _SUGAR_BUILT = True
    assert SUGAR_BIN.exists(), "cargo build did not produce target/debug/sugar"
    return SUGAR_BIN


def _write_source(project: Path, source: str) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "test_witness.py").write_text(source, encoding="utf-8")


def _stage_cli_project(project: Path, source: str) -> None:
    _write_source(project, source)
    sugar = project / ".sugar"
    (sugar / "lift" / "python").mkdir(parents=True)
    (sugar / "components" / "python-lift").mkdir(parents=True)
    (sugar / "ir-compilers" / "smt-lib").mkdir(parents=True)
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
        f'name = "python"\ncommand = ["{wrapper}", "--rpc"]\nworking_dir = "."\n',
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
        f'    *\'"method":"initialize"\'*) printf \'%s\\n\' \'{initialize_response}\' ;;\n'
        f'    *\'"method":"sugar.component.plan"\'*) printf \'%s\\n\' \'{plan_response}\' ;;\n'
        f'    *\'"method":"shutdown"\'*) printf \'%s\\n\' \'{shutdown_response}\'; exit 0 ;;\n'
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
    (sugar / "ir-compilers" / "smt-lib" / "manifest.toml").write_text(
        'name = "smt-lib-reference"\n'
        'version = "0.1.0"\n'
        'protocol_version = "sugar-ir-compiler/1"\n'
        'command = ["cargo", "run", "--locked", "-p", '
        '"sugar-ir-compiler-smt-lib", "--bin", "sugar-ir-smt-lib", "--quiet", "--"]\n'
        f'working_dir = "{RUST_WORKSPACE}"\n'
        'dialects = ["smt-lib-v2.6"]\n',
        encoding="utf-8",
    )


def _mint_and_prove(project: Path) -> tuple[dict, dict]:
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
    assert mint.returncode == 0, f"stdout:\n{mint.stdout}\nstderr:\n{mint.stderr}"
    lift_doc = _captured_lift_document(capture)
    prove = subprocess.run(
        [str(sugar), "prove", ".", "--json", "--z3", "z3"],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert prove.stdout.strip(), prove.stderr
    return lift_doc, json.loads(prove.stdout)


def _captured_lift_document(capture: Path) -> dict:
    assert capture.exists(), f"lift RPC capture missing at {capture}"
    responses = [
        json.loads(line) for line in capture.read_text(encoding="utf-8").splitlines()
    ]
    lift_responses = [
        item for item in responses if item.get("id") == 2 and "result" in item
    ]
    assert len(lift_responses) == 1, responses
    return lift_responses[0]["result"]


def _run_witness_case(case, tmp_path: Path) -> str:
    if case.expected == "construction-refusal":
        assert case.construct is not None
        with pytest.raises((FactoryGap, TypeError)):
            case.construct()
        return "construction-refusal"
    if case.construct is not None:
        constructed = case.construct()
        if isinstance(constructed, RefusalRecord):
            assert constructed.denotation() is None
    assert case.source, f"{case.name} must be driven by a source witness"
    cli_project = tmp_path / case.name / "cli"
    _stage_cli_project(cli_project, case.source)
    lift_doc, prove = _mint_and_prove(cli_project)
    _assert_expected_sugar_fired(lift_doc, case)
    _assert_lift_doc_contains_node_class(lift_doc, case)
    _assert_real_verdict(prove, case)
    return case.expected


def _assert_expected_sugar_fired(doc: dict, case) -> None:
    assert case.expected_sugar, f"{case.name} must name its recognizer"
    roles = {
        warrant.get("role")
        for row in doc.get("ir", [])
        for warrant in row.get("sourceWarrants", [])
        if isinstance(warrant, dict)
    }
    assert case.expected_sugar in roles, (case.expected_sugar, roles, doc)


def _assert_lift_doc_contains_node_class(doc: dict, case) -> None:
    # S4+ moves this from shape/provenance-diagnostic inspection to reading the
    # emitted ProofIR node-class provenance field directly.
    if case.node_class == "EqualityFact":
        assert _has_equality_fact(doc), doc
        assert "EqualityFact" in _proofir_provenance_classes(doc)
    elif case.node_class == "FunctionContract":
        assert _has_function_contract(doc), doc
        assert "FunctionContract" in _proofir_provenance_classes(doc)
    elif case.node_class == "RefusalRecord":
        assert any(d.get("kind") == "dig-refusal" for d in doc.get("diagnostics", []))
        assert not _has_function_contract(doc), doc
    else:
        raise AssertionError(f"unknown witness node class: {case.node_class!r}")


def _has_equality_fact(doc: dict) -> bool:
    return any(row.get("inv") and "#euf#" in row.get("name", "") for row in doc["ir"])


def _has_function_contract(doc: dict) -> bool:
    return any(
        row.get("kind") == "function-contract" and row.get("post")
        for row in doc["ir"]
    )


def _proofir_provenance_classes(doc: dict) -> set[str]:
    classes: set[str] = set()
    for row in doc.get("ir", []):
        provenance = row.get("proofirProvenance")
        if isinstance(provenance, dict):
            node_class = provenance.get("nodeClass")
            if isinstance(node_class, str):
                classes.add(node_class)
    for diagnostic in doc.get("diagnostics", []):
        if diagnostic.get("kind") != "proofir-formula-provenance":
            continue
        for missing in diagnostic.get("missing", []):
            node_class = missing.get("nodeClass")
            if isinstance(node_class, str):
                classes.add(node_class)
    return classes


def _assert_real_verdict(prove: dict, case) -> None:
    row = _first_euf_row(prove)
    if case.refusal_absence:
        assert row["status"] == "discharged", prove
        assert row["verification"]["linkedPosts"] == []
        return
    expected_status = {"sat": "discharged", "unsat": "unsatisfied"}[case.expected]
    assert row["status"] == expected_status, prove


def _first_euf_row(prove: dict) -> dict:
    rows = prove.get("rows", [])
    assert rows, prove
    return next(row for row in rows if "#euf#" in row.get("property", ""))


@pytest.mark.parametrize("node_class", REGISTERED_PROOFIR_NODE_CLASSES)
def test_registered_proofir_witnesses_are_source_programs(node_class) -> None:
    pair = node_class.verdict_witnesses()

    assert pair.truthful.source
    assert pair.truthful.expected_sugar
    if pair.lying.expected != "construction-refusal":
        assert pair.lying.source
        assert pair.lying.expected_sugar


@pytest.mark.parametrize("node_class", REGISTERED_PROOFIR_NODE_CLASSES)
def test_registered_proofir_witnesses_are_solver_checked(
    node_class,
    tmp_path: Path,
) -> None:
    pair = node_class.verdict_witnesses()

    assert _run_witness_case(pair.truthful, tmp_path) == pair.truthful.expected
    assert _run_witness_case(pair.lying, tmp_path) == pair.lying.expected


def test_instrument_c_registers_the_three_spine_witness_classes() -> None:
    report = collect_proofir_vocabulary_frontier(ROOT)

    assert report.proofir_classes_without_verdict_witnesses == 4
    assert report.verdict_witnesses.missing_classes == [
        "CallEdgeDecl",
        "AuditMemento",
        "UniverseMint",
        "VendorConjoin",
    ]


def test_equality_fact_truthful_and_lying_witnesses_hit_real_solver(
    tmp_path: Path,
) -> None:
    pair = EqualityFact.verdict_witnesses()

    assert _run_witness_case(pair.truthful, tmp_path) == "sat"
    assert _run_witness_case(pair.lying, tmp_path) == "unsat"


def test_equality_fact_semantic_merge_collapses_stated_and_derived_warrants() -> None:
    call_term = CallTerm("h", (ConstTerm(5, sort=IntSort()),), sort=IntSort())
    stated = EqualityFact(
        call_term=call_term,
        rhs_term=ConstTerm(6, sort=IntSort()),
        provenance=_stated_provenance("EqualityFact"),
    )
    derived = EqualityFact(
        call_term=call_term,
        rhs_term=ConstTerm(6, sort=IntSort()),
        provenance=_derived_provenance("EqualityFact"),
    )

    assert stated.cid() != derived.cid()
    assert stated.semantic_cid() == derived.semantic_cid()
    merged = merge_equality_facts(stated, derived)

    assert merged.semantic_cid() == stated.semantic_cid()
    assert len(merged.provenance().warrants) == 2
    merged_wire = json.loads(merged.to_proof_ir())
    assert "sourceWarrants" not in merged_wire
    assert merged_wire["proofirProvenance"]["nodeClass"] == "EqualityFact"
    assert {
        warrant["kind"]
        for warrant in merged_wire["proofirProvenance"]["warrants"]
    } == {"Derived", "Stated"}
    assert merge_equality_facts(stated, stated) == stated
    assert merge_equality_facts(merged, stated) == merged


def test_equality_fact_semantic_merge_refuses_lying_pair() -> None:
    call_term = CallTerm("h", (), sort=IntSort())
    stated_lie = EqualityFact(
        call_term=call_term,
        rhs_term=ConstTerm(7, sort=IntSort()),
        provenance=_stated_provenance("EqualityFact"),
    )
    derived_truth = EqualityFact(
        call_term=call_term,
        rhs_term=ConstTerm(6, sort=IntSort()),
        provenance=_derived_provenance("EqualityFact"),
    )

    assert stated_lie.semantic_cid() != derived_truth.semantic_cid()
    with pytest.raises(FactoryGap, match="semantic_cid"):
        merge_equality_facts(stated_lie, derived_truth)


def test_equality_fact_constructor_invariants_are_loud() -> None:
    call_term = CallTerm("h", (ConstTerm(5, sort=IntSort()),), sort=IntSort())
    good_key = canonical_euf_callsite_name(call_term)
    assert good_key == euf_callsite_name("h", call_term.ir_term, suffix="::assertion")

    fact = EqualityFact(
        call_term=call_term,
        rhs_term=ConstTerm(5, sort=IntSort()),
        provenance=_two_warrant_provenance("EqualityFact"),
    )
    assert fact.euf_key == good_key
    assert fact.denotation() == eq(call_term.ir_term, num(5))
    assert len(fact.provenance().warrants) == 2
    assert fact.cid().startswith("blake3-512:")

    with pytest.raises(TypeError, match="euf_key"):
        EqualityFact(
            euf_key="free-typed-key",
            call_term=call_term,
            rhs_term=ConstTerm(5, sort=IntSort()),
            provenance=_stated_provenance("EqualityFact"),
        )
    with pytest.raises(FactoryGap, match="typed ProofIR Term"):
        EqualityFact(
            call_term=call_term,
            rhs_term={"kind": "const"},
            provenance=_stated_provenance("EqualityFact"),
        )


def test_function_contract_witnesses_and_builder_invariants(tmp_path: Path) -> None:
    pair = FunctionContract.verdict_witnesses()

    assert _run_witness_case(pair.truthful, tmp_path) == "sat"
    assert _run_witness_case(pair.lying, tmp_path) == "unsat"

    contract = (
        FunctionContract.builder(
            symbol="module::f::callable",
            out_binding="out",
            out_sort=Int(),
            provenance=_derived_provenance("FunctionContract"),
        )
        .formal("x", Int())
        .post(
            PostCondition(
                formula=Eq(
                    VarTerm("out", sort=IntSort()),
                    VarTerm("x", sort=IntSort()),
                ),
                out_binding="out",
                out_sort=IntSort(),
                formals={"x": IntSort()},
            )
        )
        .build()
    )
    assert contract.denotation() is not None
    assert contract.cid().startswith("blake3-512:")

    with pytest.raises(FactoryGap, match="post"):
        (
            FunctionContract.builder(
                symbol="module::missing::callable",
                out_binding="out",
                out_sort=Int(),
                provenance=_derived_provenance("FunctionContract"),
            )
            .formal("x", Int())
            .build()
        )
    with pytest.raises(TypeError, match="PostCondition"):
        (
            FunctionContract.builder(
                symbol="module::dict::callable",
                out_binding="out",
                out_sort=Int(),
                provenance=_derived_provenance("FunctionContract"),
            )
            .post({"kind": "atomic"})
        )


def test_refusal_record_has_no_formula_and_fact_plus_refusal_is_unconstructible(
    tmp_path: Path,
) -> None:
    pair = RefusalRecord.verdict_witnesses()
    assert _run_witness_case(pair.truthful, tmp_path) == "sat"
    assert pair.lying.expected == "construction-refusal"

    record = RefusalRecord.from_incomplete(
        Incomplete(RuntimeEffect("opaque runtime effect")),
        provenance=_derived_provenance("RefusalRecord"),
    )
    assert RefusalRecord.__module__.endswith(".proofir.nodes.refusal_record")
    assert not isinstance(record, ProofIRNode)
    assert record.denotation() is None
    assert record.cid().startswith("blake3-512:")

    with pytest.raises(TypeError, match="formula"):
        RefusalRecord.from_incomplete(
            Incomplete(RuntimeEffect("opaque runtime effect")),
            provenance=_derived_provenance("RefusalRecord"),
            formula=eq(make_var("call"), num(0)),
        )


def test_function_contract_rejects_wrong_formula_and_declaration_shapes() -> None:
    with pytest.raises(FactoryGap, match="post mentioning 'result'"):
        (
            FunctionContract.builder(
                symbol="module::bad::callable",
                out_binding="result",
                out_sort=Bool(),
                provenance=_derived_provenance("FunctionContract"),
            )
            .post(
                PostCondition(
                    formula=Eq(
                        VarTerm("out", sort=BoolSort()),
                        ConstTerm(True, sort=BoolSort()),
                    ),
                    out_binding="result",
                    out_sort=BoolSort(),
                    formals={},
                )
            )
            .build()
        )
