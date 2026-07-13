from __future__ import annotations

from sugar_lift_py_tests.lift_rpc import audit_lift_file


def test_class_method_owner_is_emitted_in_contract_and_audit_mementos() -> None:
    source = """
def _cmp(a, b):
    return a == b

class date:
    def _cmp(self, other):
        return self == other

class time:
    def _cmp(self, other):
        return self == other

class datetime:
    def _cmp(self, other):
        return self == other
"""
    payload, gaps = audit_lift_file(source, "datetime.py", hold_panic=True)
    assert gaps == []
    rpc = payload.to_rpc()

    names = {row["name"] for row in rpc["ir"] if row["kind"] == "function-contract"}
    assert names == {"_cmp", "date._cmp", "time._cmp", "datetime._cmp"}

    warrants = {
        row["sourceWarrants"][0]["sourceFunctionName"]
        for row in rpc["ir"]
        if row["kind"] == "function-contract"
    }
    assert warrants == names

    audit_owners = {
        row["sourceMemento"].get("sourceFunctionName")
        for row in rpc["factoryAuditSummary"]["factoryWalk"]
        if row.get("sourceMemento", {}).get("sourceFunctionName")
    }
    assert {"date._cmp", "time._cmp", "datetime._cmp"} <= audit_owners


def test_nested_class_method_owner_is_lexically_qualified() -> None:
    source = """
class Outer:
    class Inner:
        def value(self):
            return 1
"""
    payload, gaps = audit_lift_file(source, "nested.py", hold_panic=True)
    assert gaps == []
    names = {
        row["name"]
        for row in payload.to_rpc()["ir"]
        if row["kind"] == "function-contract"
    }
    assert names == {"Outer.Inner.value"}
