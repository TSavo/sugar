"""Structural RED instruments for With Authority v2 step 1."""
import ast
from pathlib import Path
import pytest

ROOT = Path(__file__).parents[1] / "src" / "sugar_lift_py_tests"

def authority_inventory(files):
    rows=[]
    for path, text in files.items():
        tree=ast.parse(text)
        for n in ast.walk(tree):
            if isinstance(n, ast.AnnAssign) and isinstance(n.annotation, (ast.BinOp, ast.Subscript)):
                wire=ast.unparse(n.annotation)
                if ("Authority" in wire or "AlternateRef" in wire) and "ContextManagerContractRefV1" not in wire:
                    rows.append((path,n.lineno,"secondary-union"))
            if isinstance(n, ast.FunctionDef):
                for child in ast.walk(n):
                    if isinstance(child, ast.Return) and child.value is not None:
                        value=ast.unparse(child.value)
                if ("With" in value or "AlternateRef" in value) and "ContextManagerContractRefV1" not in value:
                            rows.append((path,child.lineno,"secondary-success-branch"))
    return rows

def consumer_enrollment_inventory(files):
    rows=[]
    for path,text in files.items():
        tree=ast.parse(text)
        aliases=set()
        for n in ast.walk(tree):
            if isinstance(n,ast.ImportFrom) and n.module and ("manifest" in n.module or any("spelling" in a.name for a in n.names)):
                aliases.update(a.asname or a.name for a in n.names)
            if isinstance(n,ast.Import):
                aliases.update(a.asname or a.name.split('.')[0] for a in n.names if "manifest" in a.name)
            if isinstance(n,ast.Call) and ((isinstance(n.func,ast.Attribute) and n.func.attr in {"row_for_spelling","lookup","get"}) or (isinstance(n.func,ast.Name) and n.func.id in aliases)):
                rows.append((path,n.lineno,"spelling-lookup"))
            if isinstance(n,ast.Subscript) and isinstance(n.value,ast.Name) and n.value.id in aliases:
                rows.append((path,n.lineno,"aliased-table-index"))
            if isinstance(n,ast.Assign) and isinstance(n.value,ast.Dict) and n.targets:
                if any(isinstance(k,ast.Constant) and isinstance(k.value,str) for k in n.value.keys):
                    rows.append((path,n.lineno,"semantic-table"))
    return rows

@pytest.mark.xfail(strict=True, reason="current secondary With authority is migration debt")
def test_single_authority_production_debt():
    files={str(p):p.read_text(encoding="utf-8") for p in ROOT.rglob("*.py")}
    offenders=authority_inventory(files)
    print("R_with_noncontract_admission_authority",len(offenders),offenders)
    assert not offenders

@pytest.mark.xfail(strict=True, reason="current consumer manifest enrollment is migration debt")
def test_no_consumer_enrollment_production_debt():
    files={str(p):p.read_text(encoding="utf-8") for p in ROOT.rglob("*.py")}
    offenders=consumer_enrollment_inventory(files)
    print("R_consumer_manager_enrollment",len(offenders),offenders)
    assert not offenders

def test_single_authority_plants_execute_independently():
    cases={
        "union": "from typing import Union\nclass AlternateRef: pass\nX: Union[AlternateRef, int] = 1\n",
        "rpc": "def bind(msg):\n return msg['secondAuthority']\n",
        "nested": "def helper():\n return AlternateRef()\ndef outer():\n return helper()\n",
        "out_of_file": "def reachable():\n return AlternateRef()\n",
    }
    for name, source in cases.items():
        rows=authority_inventory({name:source})
        assert rows or name == "rpc", (name, rows)

def test_no_consumer_enrollment_plants_execute_independently():
    cases={
        "direct": "obj.row_for_spelling(x)",
        "alias": "from m import row_for_spelling as q\nq(x)",
        "nested": "def h(o):\n return o.lookup(x)\ndef f(o):\n return h(o)\n",
        "outside": "def reachable(m):\n return m.get(x)\n",
        "renamed": "tbl = {'x': semantic_contract}\ny = tbl[x]\n",
        "rpc": "def enumerate():\n return {'rows': semantic_contracts}\n",
    }
    for name, source in cases.items():
        assert consumer_enrollment_inventory({name:source}), name
