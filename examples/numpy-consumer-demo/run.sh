#!/usr/bin/env bash
# Cross-proof consumer demo: vendor fact, vendor universe, user fact.
#
# This is intentionally tiny. It mints a minimal vendor `.proof` that exposes
# two NumPy-shaped contracts, stages that proof under each consumer's
# `.sugar/imports/`, and then proves four consumer claims through the shipping
# Sugar CLI:
#
#   np.load(..., encoding="latin1")  -> discharges imported vendor pre
#   np.load(..., encoding="wrong")   -> violates imported vendor pre
#   np.add(5, 5) == 10               -> discharges via imported vendor universe
#   np.add(5, 5) == 11               -> refutes via imported vendor universe
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


vendor_ir = [
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
                eq(var("encoding"), string_const("ASCII")),
                eq(var("encoding"), string_const("latin1")),
                eq(var("encoding"), string_const("bytes")),
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


def mint_vendor() -> tuple[Path, str]:
    vendor = work / "vendor"
    out = work / "vendor-out"
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

IR = {json.dumps(vendor_ir)}

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


def mint_and_prove(project: Path):
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


proof, proof_cid = mint_vendor()
print(f"vendor proof: {proof.name} ({proof_cid})")

cases = {
    "load-good": """import numpy as np

def test_load():
    assert np.load("data.npy", encoding="latin1") == "data.npy"
""",
    "load-bad": """import numpy as np

def test_load():
    assert np.load("data.npy", encoding="wrong") == "data.npy"
""",
    "add-good": """import numpy as np

def test_add():
    assert np.add(5, 5) == 10
""",
    "add-bad": """import numpy as np

def test_add():
    assert np.add(5, 5) == 11
""",
}

projects = {name: stage_consumer(name, source, proof) for name, source in cases.items()}

wall = run([bin_path, "lift", "--report", "--json", projects["load-good"]])
require_success(wall, "load-good wall")
wall_report = json.loads(wall.stdout)
edge = next(e for e in wall_report["callEdges"] if e["targetSymbol"] == "call:numpy.load")
print(
    "wall edge:",
    edge["sourceContract"],
    "->",
    edge["targetSymbol"],
    "->",
    edge["targetContract"],
    "origin",
    edge["targetProofCid"],
)

for name in ["load-good", "load-bad", "add-good", "add-bad"]:
    code, report = mint_and_prove(projects[name])
    if name.startswith("load"):
        row = row_for(report, bridge="call:numpy.load")
    else:
        row = row_for(report, property_contains="numpy.add#euf#")
    print(
        f"{name}: exit={code} status={row['status']} violations={report.get('violations')}"
    )
    if name.startswith("add"):
        linked = row["verification"]["linkedPosts"][0]
        print(
            "  linked post:",
            linked["sourceSymbol"],
            "origin",
            linked["targetProofCid"],
            "call",
            linked["call"]["name"],
        )

print(f"workdir: {work}")
PY
