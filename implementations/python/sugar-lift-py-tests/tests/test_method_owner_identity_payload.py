"""Universe identity: distinct bodies with the same surface spelling stay distinct.

#4325 — four `_cmp` bodies (module + date + time + datetime) must not collapse
to one bare-name / one module-stem spelling. When a class is named the same as
its module (`class datetime` in `datetime.py`), class methods must carry the
full `module.class.method` path so they cannot collide with the module-level
function of the same leaf name.

Replacement architecture: class-relative owners are always module-rooted
relative paths; never treat `Class.method` as already-module-qualified just
because `Class` equals the module stem.
"""

from __future__ import annotations

from sugar_lift_py_tests.lift_rpc import audit_lift_file


def test_four_cmp_bodies_keep_distinct_module_rooted_identities() -> None:
    """Instrument for #4325: same surface `_cmp`, four distinct bodies.

    Predicted green shape (module stem `datetime`):
      - module-level  -> datetime._cmp
      - date method   -> datetime.date._cmp
      - time method   -> datetime.time._cmp
      - class method  -> datetime.datetime._cmp   (NOT datetime._cmp)
    """
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
    payload, gaps = audit_lift_file(source, "datetime.py")
    assert gaps == []
    rpc = payload.to_rpc()

    rows = [row for row in rpc["ir"] if row["kind"] == "function-contract"]
    names = {row["name"] for row in rows}
    assert names == {
        "datetime._cmp",
        "datetime.date._cmp",
        "datetime.time._cmp",
        "datetime.datetime._cmp",
    }, (
        "four distinct `_cmp` bodies must render four module-rooted identities; "
        f"got {sorted(names)}. Replacement: class-relative owner is always "
        "prefixed with the module root so class datetime in datetime.py becomes "
        "datetime.datetime._cmp and cannot collide with module-level datetime._cmp."
    )
    assert len(rows) == 4, rows
    assert len(names) == 4, (
        f"identity collision under function-contract name: {sorted(names)}"
    )

    warrants = {
        row["sourceWarrants"][0]["sourceFunctionName"]
        for row in rows
        if row.get("sourceWarrants")
    }
    assert warrants == names

    # Class-named-as-module must not share the module function's spelling.
    assert "datetime._cmp" in names
    assert "datetime.datetime._cmp" in names


def test_nested_class_method_owner_is_lexically_qualified() -> None:
    source = """
class Outer:
    class Inner:
        def value(self):
            return 1
"""
    payload, gaps = audit_lift_file(source, "nested.py")
    assert gaps == []
    names = {
        row["name"]
        for row in payload.to_rpc()["ir"]
        if row["kind"] == "function-contract"
    }
    assert names == {"nested.Outer.Inner.value"}
