#!/usr/bin/env bash
# Purpose:
#   Bounded demo surface for the cross-proof membrane story: one runnable
#   four-verdict receipt plus the vendor-update arc where an imported vendor
#   proof changes and only the consumer callsites coupled to that formula move.
#   This is the script referenced by docs/how-to/publish-and-inherit-a-proof.md.
#
# Retirement:
#   Retire this shell when the same v1/v2 vendor-update arc is exercised by a
#   CI-gated e2e suite. The current load-bearing seat is
#   implementations/rust/sugar-cli/tests/cross_proof_imported_implications.rs;
#   once that suite, or a successor such as test_inheritance_e2e.py, fully owns
#   the runnable demo receipt, this shell becomes redundant demo sugar.
#
# Cross-proof consumer demo: vendor fact, vendor universe, user fact.
#
# This is intentionally tiny. It mints two minimal vendor `.proof` files that
# expose NumPy-shaped contracts, stages v1 under one unchanged consumer, swaps
# to v2, and then proves the same consumer claims through the shipping Sugar
# CLI:
#
#   v1: np.load(..., encoding="latin1") -> discharges imported vendor pre
#   v2: np.load(..., encoding="latin1") -> violates tightened vendor pre
#   both: np.add(5, 5) == 10            -> discharges via imported vendor universe
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BIN="$("$REPO/bin/sugarbin" --profile release)"
WORK="${SUGAR_NUMPY_CONSUMER_DEMO_WORK:-$(mktemp -d "${TMPDIR:-/tmp}/sugar-numpy-consumer-demo.XXXXXX")}"

export SUGAR_NUMPY_CONSUMER_DEMO_BIN="$BIN"
export SUGAR_NUMPY_CONSUMER_DEMO_REPO="$REPO"
export SUGAR_NUMPY_CONSUMER_DEMO_WORK="$WORK"

python3 <<'PY'
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

bin_path = Path(os.environ["SUGAR_NUMPY_CONSUMER_DEMO_BIN"])
repo = Path(os.environ["SUGAR_NUMPY_CONSUMER_DEMO_REPO"])
work = Path(os.environ["SUGAR_NUMPY_CONSUMER_DEMO_WORK"])
work.mkdir(parents=True, exist_ok=True)

py_tests = repo / "implementations/python/sugar-lift-py-tests/src"
py_source = repo / "implementations/python/sugar-lift-python-source/src"

int_sort = {"kind": "primitive", "name": "Int"}
str_sort = {"kind": "primitive", "name": "String"}


def var(name):
    return {"kind": "var", "name": name}


def string_const(value):
    return {"kind": "const", "value": value, "sort": str_sort}


def eq(left, right):
    return {"kind": "atomic", "name": "=", "args": [left, right]}


def vendor_ir(encodings):
    return [
        {
            "kind": "function-contract",
            "name": "lib._npyio_impl.load",
            "bridgeSourceSymbol": "numpy.load",
            "formals": ["file", "encoding"],
            "formalSorts": [str_sort, str_sort],
            "outBinding": "out",
            "pre": {
                "kind": "or",
                "operands": [
                    eq(var("encoding"), string_const(encoding))
                    for encoding in encodings
                ],
            },
        },
        {
            "kind": "function-contract",
            "name": "numpy.add",
            "bridgeSourceSymbol": "numpy.add",
            "formals": ["a", "b"],
            "formalSorts": [int_sort, int_sort],
            "outBinding": "out",
            "post": eq(
                var("out"),
                {"kind": "ctor", "name": "+", "args": [var("a"), var("b")]},
            ),
        },
    ]


def write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def run(args, *, cwd=None):
    proc = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    return proc


def require_success(proc, label):
    if proc.returncode != 0:
        raise SystemExit(
            f"{label} failed with {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )


def mint_vendor(label: str, encodings) -> tuple[Path, str]:
    vendor = work / label
    out = work / f"{label}-out"
    shutil.rmtree(vendor, ignore_errors=True)
    shutil.rmtree(out, ignore_errors=True)
    (vendor / ".sugar/lift/static-vendor").mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    (vendor / ".sugar/config.toml").write_text(
        """[[plugins]]
name = "static-vendor"
kind = "lift"
surface = "static-vendor"
emit = "ir-document"

[solvers]
default = "z3"
[solvers.z3]
binary = "z3"
flags = ["-smt2", "-in"]
""",
        encoding="utf-8",
    )
    plugin = vendor / "static_vendor.py"
    write_executable(
        plugin,
        f"""#!/usr/bin/env python3
import json
import sys

IR = {json.dumps(vendor_ir(encodings))}

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        result = {{"name": "static-vendor", "protocol_version": "pep/1.7.0", "capabilities": {{}}}}
    elif method in ("lift", "sugar.plugin.lift"):
        result = {{"kind": "ir-document", "ir": IR, "diagnostics": []}}
    elif method == "shutdown":
        print(json.dumps({{"jsonrpc": "2.0", "id": request.get("id"), "result": None}}), flush=True)
        break
    else:
        result = {{"kind": "ir-document", "ir": IR, "diagnostics": []}}
    print(json.dumps({{"jsonrpc": "2.0", "id": request.get("id"), "result": result}}), flush=True)
""",
    )
    (vendor / ".sugar/lift/static-vendor/manifest.toml").write_text(
        f'name = "static-vendor"\ncommand = ["{plugin}"]\nworking_dir = "."\n',
        encoding="utf-8",
    )
    proc = run([bin_path, "mint", "--project", vendor, "--out", out, "--quiet", "--json"])
    require_success(proc, "vendor mint")
    proof = next(out.glob("*.proof"))
    cid = "blake3-512:" + proof.stem.removeprefix("blake3-512_")
    return proof, cid


def install_component(project: Path) -> None:
    component = project / ".sugar/components/python-lift"
    component.mkdir(parents=True, exist_ok=True)
    script = component / "component.sh"
    write_executable(
        script,
        """#!/bin/sh
while IFS= read -r line; do
  case "$line" in
    *'"method":"initialize"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"python-lift-component","protocol_version":"sugar-component/1","capabilities":{}}}'
      ;;
    *'"method":"sugar.component.plan"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"decision":"claim","plugins":[{"name":"python-lift","kind":"lift","surface":"python"}],"diagnostics":[{"level":"info","message":"python lift component planned"}]}}'
      ;;
    *'"method":"shutdown"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
      exit 0
      ;;
  esac
done
""",
    )
    (component / "manifest.toml").write_text(
        f'name = "python-lift-component"\nprotocol_version = "sugar-component/1"\ncommand = ["/bin/sh", "{script}"]\n',
        encoding="utf-8",
    )


def stage_consumer(name: str, source: str, proof: Path) -> Path:
    project = work / name
    shutil.rmtree(project, ignore_errors=True)
    (project / ".sugar/lift/python").mkdir(parents=True, exist_ok=True)
    (project / ".sugar/imports").mkdir(parents=True, exist_ok=True)
    shutil.copy2(proof, project / ".sugar/imports" / proof.name)
    (project / "test_case.py").write_text(source, encoding="utf-8")
    install_component(project)
    (project / ".sugar/config.toml").write_text(
        """[[plugins]]
name = "python-lift"
kind = "lift"
surface = "python"
emit = "ir-document"

[solvers]
default = "z3"
[solvers.z3]
binary = "z3"
flags = ["-smt2", "-in"]
""",
        encoding="utf-8",
    )
    wrapper = work / f"{name}-python-lift.sh"
    write_executable(
        wrapper,
        f"""#!/bin/sh
export PYTHONPATH="{py_tests}:{py_source}${{PYTHONPATH:+:$PYTHONPATH}}"
exec python3 -m sugar_lift_py_tests.lift_rpc --rpc
""",
    )
    (project / ".sugar/lift/python/manifest.toml").write_text(
        f'name = "python-lift"\ncommand = ["{wrapper}"]\nworking_dir = "."\n',
        encoding="utf-8",
    )
    return project


def remove_direct_proofs(project: Path) -> None:
    for proof in project.glob("*.proof"):
        proof.unlink()


def replace_imported_proof(project: Path, proof: Path) -> None:
    imports = project / ".sugar/imports"
    for imported in imports.glob("*.proof"):
        imported.unlink()
    shutil.copy2(proof, imports / proof.name)
    remove_direct_proofs(project)


def lift_report(project: Path):
    report = run([bin_path, "lift", "--report", "--json", project])
    require_success(report, f"{project.name} wall")
    return json.loads(report.stdout)


def mint_and_prove(project: Path):
    remove_direct_proofs(project)
    mint = run([bin_path, "mint", "--project", project, "--out", project, "--quiet", "--json"])
    require_success(mint, f"consumer mint {project.name}")
    prove = run([bin_path, "prove", project, "--json"])
    try:
        report = json.loads(prove.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"prove JSON failed for {project.name}: {exc}\nSTDOUT:\n{prove.stdout}\nSTDERR:\n{prove.stderr}"
        )
    return prove.returncode, report


def row_for(report, *, bridge=None, property_contains=None):
    for row in report.get("rows", []):
        if bridge is not None and row.get("bridge") == bridge:
            return row
        if property_contains is not None and property_contains in row.get("property", ""):
            return row
    raise SystemExit(f"row not found bridge={bridge!r} property={property_contains!r}: {json.dumps(report, indent=2)}")


def edge_for(report, target_symbol):
    return next(e for e in report["callEdges"] if e["targetSymbol"] == target_symbol)


def summarize(label, proof_cid, report, code):
    load = row_for(report, bridge="call:numpy.load")
    add = row_for(report, property_contains="numpy.add#euf#")
    add_linked = add["verification"]["linkedPosts"][0]
    print(f"{label}: proof={proof_cid}")
    print(
        f"  np.load latin1: exit={code} status={load['status']} violations={report.get('violations')}"
    )
    print(
        f"  np.add(5,5)==10: status={add['status']} linked-origin={add_linked['targetProofCid']}"
    )
    return {
        "load": load["status"],
        "add": add["status"],
        "add_origin": add_linked["targetProofCid"],
    }


proof_v1, proof_v1_cid = mint_vendor("vendor-v1", ["ASCII", "latin1", "bytes"])
proof_v2, proof_v2_cid = mint_vendor("vendor-v2", ["ASCII", "bytes"])
print(f"vendor v1 proof: {proof_v1.name} ({proof_v1_cid})")
print(f"vendor v2 proof: {proof_v2.name} ({proof_v2_cid})")

consumer_source = """import numpy as np

def test_load():
    assert np.load("data.npy", encoding="latin1") == "data.npy"

def test_add():
    assert np.add(5, 5) == 10
"""

consumer = stage_consumer("consumer-vendor-update", consumer_source, proof_v1)

v1_wall = lift_report(consumer)
v1_edge = edge_for(v1_wall, "call:numpy.load")
print(
    "v1 wall edge:",
    v1_edge["sourceContract"],
    "->",
    v1_edge["targetSymbol"],
    "->",
    v1_edge["targetContract"],
    "origin",
    v1_edge["targetProofCid"],
)
v1_code, v1_prove = mint_and_prove(consumer)
v1_summary = summarize("v1", proof_v1_cid, v1_prove, v1_code)

replace_imported_proof(consumer, proof_v2)
v2_wall = lift_report(consumer)
v2_edge = edge_for(v2_wall, "call:numpy.load")
print(
    "v2 wall edge:",
    v2_edge["sourceContract"],
    "->",
    v2_edge["targetSymbol"],
    "->",
    v2_edge["targetContract"],
    "origin",
    v2_edge["targetProofCid"],
)
v2_code, v2_prove = mint_and_prove(consumer)
v2_summary = summarize("v2", proof_v2_cid, v2_prove, v2_code)

changed = []
held = []
for key, label in [("load", "np.load latin1"), ("add", "np.add(5,5)==10")]:
    before = v1_summary[key]
    after = v2_summary[key]
    if before == after:
        held.append((label, before, after))
    else:
        changed.append((label, before, after))

print("delta summary: changed={} held={} scanned_files=0".format(len(changed), len(held)))
for label, before, after in changed:
    print(f"  changed: {label}: {before} -> {after}; new vendor proof={proof_v2_cid}")
for label, before, after in held:
    print(f"  held: {label}: {before} -> {after}")

print(f"workdir: {work}")
PY
