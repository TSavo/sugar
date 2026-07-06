#!/usr/bin/env bash
# Purpose:
#   Bounded demo surface for the cross-proof membrane story, pandas edition:
#   vendor fact, vendor universe, user fact. The vendor surface is the same
#   Series.sum equality shipped by examples/pandas-showcase/test_pandas_sum.py,
#   staged as an importable zero-formal vendor universe so the consumer proof
#   path exercises .sugar/imports, bridgeSourceSymbol, conjunction, and
#   implication linking.
#
# Retirement:
#   Retire this shell when the pandas consumer import arc is wholly owned by a
#   CI-gated e2e suite. The current load-bearing seat is
#   implementations/rust/sugar-cli/tests/cross_proof_imported_implications.rs.
#
# The current pandas-showcase proof has no PRE-bearing pandas contract. This
# demo therefore ships the conjunction case only; the precondition case joins
# when the guard-preconditions lane mints a real pandas PRE surface.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BIN="$("$REPO/bin/sugarbin" --profile release)"
WORK="${SUGAR_PANDAS_CONSUMER_DEMO_WORK:-$(mktemp -d "${TMPDIR:-/tmp}/sugar-pandas-consumer-demo.XXXXXX")}"

# The Python lift process imports the kit and may import pandas while resolving
# pandas-shaped source. Keep the public example self-contained like
# pandas-showcase.
VENV="${PANDAS_WITNESS_VENV:-/tmp/pandas-witness-venv}"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q pandas pytest pynacl blake3 cbor2
fi

export SUGAR_PANDAS_CONSUMER_DEMO_BIN="$BIN"
export SUGAR_PANDAS_CONSUMER_DEMO_REPO="$REPO"
export SUGAR_PANDAS_CONSUMER_DEMO_WORK="$WORK"
export SUGAR_PANDAS_CONSUMER_DEMO_PYTHON="$VENV/bin/python"

python3 <<'PY'
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

bin_path = Path(os.environ["SUGAR_PANDAS_CONSUMER_DEMO_BIN"])
repo = Path(os.environ["SUGAR_PANDAS_CONSUMER_DEMO_REPO"])
work = Path(os.environ["SUGAR_PANDAS_CONSUMER_DEMO_WORK"])
python = Path(os.environ["SUGAR_PANDAS_CONSUMER_DEMO_PYTHON"])
work.mkdir(parents=True, exist_ok=True)

py_tests = repo / "implementations/python/sugar-lift-py-tests/src"
py_source = repo / "implementations/python/sugar-lift-python-source/src"

int_sort = {"kind": "primitive", "name": "Int"}


def var(name):
    return {"kind": "var", "name": name}


def int_const(value):
    return {"kind": "const", "value": value, "sort": int_sort}


def eq(left, right):
    return {"kind": "atomic", "name": "=", "args": [left, right]}


def pandas_sum_vendor_ir():
    return [
        {
            "kind": "function-contract",
            "name": "pandas.Series.sum",
            "bridgeSourceSymbol": "call:sum",
            "formals": [],
            "formalSorts": [],
            "outBinding": "out",
            "post": eq(var("out"), int_const(6)),
        }
    ]


def write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def run(args, *, cwd=None):
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
    )


def require_success(proc, label):
    if proc.returncode != 0:
        raise SystemExit(
            f"{label} failed with {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )


def mint_vendor() -> tuple[Path, str]:
    vendor = work / "vendor"
    out = work / "vendor-out"
    shutil.rmtree(vendor, ignore_errors=True)
    shutil.rmtree(out, ignore_errors=True)
    (vendor / ".sugar/lift/static-pandas-vendor").mkdir(parents=True)
    out.mkdir(parents=True)
    (vendor / "test_pandas_sum.py").write_text(
        """import pandas as pd


def test_column_sum_is_six():
    df = pd.DataFrame({"a": [1, 2, 3]})
    total = df["a"].sum()
    assert total == 6
""",
        encoding="utf-8",
    )
    (vendor / ".sugar/config.toml").write_text(
        """[[plugins]]
name = "static-pandas-vendor"
kind = "lift"
surface = "static-pandas-vendor"
emit = "ir-document"

[solvers]
default = "z3"
[solvers.z3]
binary = "z3"
flags = ["-smt2", "-in"]
""",
        encoding="utf-8",
    )
    plugin = vendor / "static_pandas_vendor.py"
    write_executable(
        plugin,
        f"""#!/usr/bin/env python3
import json
import sys

IR = {json.dumps(pandas_sum_vendor_ir())}

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        result = {{"name": "static-pandas-vendor", "protocol_version": "pep/1.7.0", "capabilities": {{}}}}
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
    (vendor / ".sugar/lift/static-pandas-vendor/manifest.toml").write_text(
        f'name = "static-pandas-vendor"\ncommand = ["{plugin}"]\nworking_dir = "."\n',
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


def stage_consumer(name: str, expected: int, proof: Path) -> Path:
    project = work / name
    shutil.rmtree(project, ignore_errors=True)
    (project / ".sugar/lift/python").mkdir(parents=True)
    (project / ".sugar/imports").mkdir(parents=True)
    shutil.copy2(proof, project / ".sugar/imports" / proof.name)
    (project / "test_case.py").write_text(
        f"""import pandas as pd


def test_sum():
    df = pd.DataFrame({{"a": [1, 2, 3]}})
    total = df["a"].sum()
    assert total == {expected}
""",
        encoding="utf-8",
    )
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
exec {python} -m sugar_lift_py_tests.lift_rpc --rpc
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


def row_for(report, property_contains):
    for row in report.get("rows", []):
        if property_contains in row.get("property", ""):
            return row
    raise SystemExit(f"row not found property={property_contains!r}: {json.dumps(report, indent=2)}")


def edge_for(report, target_symbol):
    return next(e for e in report["callEdges"] if e["targetSymbol"] == target_symbol)


proof, proof_cid = mint_vendor()
print(f"vendor proof: {proof.name} ({proof_cid})")
print("vendor surface: pandas-showcase Series.sum fact; no PRE-bearing pandas contract minted yet")

good = stage_consumer("consumer-good", 6, proof)
good_wall = lift_report(good)
good_edge = edge_for(good_wall, "call:sum")
print(
    "good wall edge:",
    good_edge["sourceContract"],
    "->",
    good_edge["targetSymbol"],
    "->",
    good_edge["targetContract"],
    "origin",
    good_edge["targetProofCid"],
)
good_code, good_prove = mint_and_prove(good)
good_row = row_for(good_prove, "sum#euf#")
good_post = good_row["verification"]["linkedPosts"][0]
print(
    f"good consumer: exit={good_code} status={good_row['status']} linked-origin={good_post['targetProofCid']}"
)

bad = stage_consumer("consumer-bad", 7, proof)
bad_wall = lift_report(bad)
bad_edge = edge_for(bad_wall, "call:sum")
print(
    "bad wall edge:",
    bad_edge["sourceContract"],
    "->",
    bad_edge["targetSymbol"],
    "->",
    bad_edge["targetContract"],
    "origin",
    bad_edge["targetProofCid"],
)
bad_code, bad_prove = mint_and_prove(bad)
bad_row = row_for(bad_prove, "sum#euf#")
bad_post = bad_row["verification"]["linkedPosts"][0]
print(
    f"bad consumer: exit={bad_code} status={bad_row['status']} linked-origin={bad_post['targetProofCid']}"
)

if good_code != 0 or good_row["status"] != "discharged":
    raise SystemExit(f"good consumer must discharge through imported pandas proof: {good_prove}")
if bad_code == 0 or bad_row["status"] != "unsatisfied":
    raise SystemExit(f"bad consumer must stay red through imported pandas proof: {bad_prove}")
if good_post["targetProofCid"] != proof_cid or bad_post["targetProofCid"] != proof_cid:
    raise SystemExit("linked post did not target the imported pandas vendor proof")

print("precondition case: not present; waiting on pandas guard-precondition contract surface")
print(f"workdir: {work}")
PY
