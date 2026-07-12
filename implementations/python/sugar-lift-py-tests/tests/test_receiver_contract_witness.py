import ast
from pathlib import Path

from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor.receiver_contract_witness import (
    ReceiverContractWitness,
    cited_same_class_return,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file


def _method(source: str):
    module = ast.parse(source)
    node = next(node for node in ast.walk(module) if isinstance(node, ast.FunctionDef))
    return SourceFragment.from_node(node, "clock.py", source)


def test_same_class_return_witness_is_cited_from_the_method_definition() -> None:
    method = _method("class Clock:\n    def replace(self):\n        return type(self)()\n")
    incoming = ReceiverContractWitness("Clock", make_var("self"))

    returned = cited_same_class_return(method, incoming)

    assert returned is not None
    assert returned.concrete_method_owner == "Clock"
    assert returned.bound_self == make_var("self")
    assert returned.returned_receiver_provenance == method.memento()


def test_direct_constructor_return_does_not_fake_same_class_provenance() -> None:
    method = _method("class Clock:\n    def replace(self):\n        return Clock()\n")
    incoming = ReceiverContractWitness("Clock", make_var("self"))

    assert cited_same_class_return(method, incoming) is None


def test_method_root_carries_owner_through_replace_to_followup_method() -> None:
    source = (
        "class Clock:\n"
        "    def replace(self):\n"
        "        return type(self)()\n"
        "    def utcoffset(self):\n"
        "        return 0\n"
        "    def compare(self):\n"
        "        assert isinstance(self, Clock)\n"
        "        return self.replace().utcoffset()\n"
    )

    payload, gaps = audit_lift_file(source, "clock.py", hold_panic=True)

    assert not [gap for gap in gaps if gap.label.endswith(":6:4")]
    assert any(row.name == "compare" for row in payload.ir)


def test_receiver_witness_strawman_exposes_the_later_branch_join_gap() -> None:
    source = (
        "class Clock:\n"
        "    def replace(self):\n"
        "        return type(self)()\n"
        "    def utcoffset(self):\n"
        "        return 0\n"
        "    def compare(self, other, allow_mixed=False):\n"
        "        assert isinstance(other, Clock)\n"
        "        if self is other:\n"
        "            base_compare = True\n"
        "        else:\n"
        "            left = self.utcoffset()\n"
        "            right = other.utcoffset()\n"
        "            if allow_mixed:\n"
        "                if left != self.replace().utcoffset():\n"
        "                    return 2\n"
        "            base_compare = left == right\n"
        "        if base_compare:\n"
        "            return 0\n"
        "        return 1\n"
    )

    _payload, gaps = audit_lift_file(source, "clock.py", hold_panic=True)

    compare_gap = next(gap for gap in gaps if gap.label.endswith(":6:4"))
    assert "observed=base_compare requested=value" in compare_gap.message


def test_datetime_2141_strawman_and_bad_twin_remain_refused_loud() -> None:
    vendor = (
        Path(__file__).parent / "vendor" / "cpython-3.11" / "datetime.py"
    )
    truthful = vendor.read_text(encoding="utf-8")
    rows = truthful.splitlines(keepends=True)
    tree = ast.parse(truthful, filename=str(vendor))
    assertion = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assert) and node.lineno == 2141
    )
    row = rows[2140]
    rows[2140] = (
        f"{row[:assertion.test.col_offset]}"
        f"not ({row[assertion.test.col_offset:assertion.test.end_col_offset]})"
        f"{row[assertion.test.end_col_offset:]}"
    )
    lying = "".join(rows)

    def coverage(source: str):
        payload, _gaps = audit_lift_file(source, str(vendor), hold_panic=True)
        return account_lift_coverage(
            census_source(source, file=str(vendor)), payload.to_rpc()
        ).to_json()["assertions"]

    truthful_coverage = coverage(truthful)
    lying_coverage = coverage(lying)

    for observed in (truthful_coverage, lying_coverage):
        assert 2141 in {locus["line"] for locus in observed["refused_loci"]}
        assert observed["silently_unaccounted"] == 0
    assert (
        truthful_coverage["lifted_cited"] == lying_coverage["lifted_cited"]
    )
