"""Value-correctness twins for the Phase-3 resume (the gate the merge was
missing): a resolved conditional candidate must contribute its CARRIED value's
post, not vanish to an implicit None. Each asserts the ACTUAL post formula."""

import os, tempfile, dataclasses
import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.caller_parameter_contract import (
    ContractConditionalConstructionV1,
    ParameterContractResolutionSetV1,
    resume_apply_resolutions,
    resume_project,
    ResumeStalePanic,
    _cid,
)
from sugar_lift_py_tests.ir import (
    atomic as _atomic,
    ctor as _ctor,
    make_var,
    num,
    eq as _eq,
)


def _universe_and_unit(src):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "m.py")
    open(p, "w").write(src)
    fn = list(SourceFile(path_source(p)).functions())[0]
    universe = fn.sugar().desugar(None).value
    from sugar_lift_py_tests import tree_enumerate as _tree

    memento = _tree.function_def_memento(fn, "m.py").to_rpc()
    unit = universe.link_unit_projection(memento)
    return universe, unit


def _self_declared_set(unit):
    cand = unit.candidates[0]
    pre = {
        "kind": "parameter-contract-resolution",
        "schemaVersion": "1",
        "demandCid": cand.demand.demand_cid,
        "candidateCid": cand.candidate_cid,
        "contractCid": unit.parameter_owned_contract.contract_cid,
        "basis": "declared-demand",
        "callerUniverseCid": None,
    }
    res = {**pre, "resolutionCid": _cid(pre)}
    return ParameterContractResolutionSetV1.mint(
        link_unit_cid=unit.link_unit_cid, resolutions=(res,)
    )


def test_twin_a_resolved_subscript_projects_carried_value():
    # (a) resolved `return items[0]` produces out == py.subscript(items, 0),
    # NOT the implicit-None fall-through the bug produced.
    universe, unit = _universe_and_unit("def transform(items):\n    return items[0]\n")
    rset = _self_declared_set(unit)
    accepted = resume_apply_resolutions(unit, rset)
    resolved = resume_project(universe, accepted)
    post = resolved.post()
    expected = _eq(make_var("out"), _ctor("py.subscript", [make_var("items"), num(0)]))
    assert post == expected, f"post was {post!r}, expected {expected!r}"


def test_twin_b_lying_candidate_is_rejected():
    # (b) a resolution naming a DIFFERENT candidate than the one enrolled must be
    # rejected -- a lying post can never project.
    universe, unit = _universe_and_unit("def transform(items):\n    return items[0]\n")
    cand = unit.candidates[0]
    pre = {
        "kind": "parameter-contract-resolution",
        "schemaVersion": "1",
        "demandCid": cand.demand.demand_cid,
        "candidateCid": "blake3-512:" + "b" * 128,  # LIE
        "contractCid": unit.parameter_owned_contract.contract_cid,
        "basis": "declared-demand",
        "callerUniverseCid": None,
    }
    res = {**pre, "resolutionCid": _cid(pre)}
    rset = ParameterContractResolutionSetV1.mint(
        link_unit_cid=unit.link_unit_cid, resolutions=(res,)
    )
    with pytest.raises(ResumeStalePanic, match="wrong candidate"):
        resume_apply_resolutions(unit, rset)


def test_twin_c_missing_resolution_still_panics():
    # (c) with the candidate left unresolved, post() still panics -- resume is the
    # sole projection path.
    universe, unit = _universe_and_unit("def transform(items):\n    return items[0]\n")
    from sugar_source_tree.panic import SugarNotWritten

    # empty accepted -> replacement leaves the CCC standing -> post() panics.
    resolved = resume_project(universe, {})
    with pytest.raises(BaseException):
        resolved.post()


def test_twin_d_retained_value_identity_unchanged():
    # (d) replacement reuses the retained .value object -- occurrence identity is
    # byte-identical, not a reconstruction.
    universe, unit = _universe_and_unit("def transform(items):\n    return items[0]\n")
    ccc = next(
        e
        for e in universe.record.statements
        if isinstance(e, ContractConditionalConstructionV1)
    )
    retained_value_id = id(ccc.value)
    rset = _self_declared_set(unit)
    accepted = resume_apply_resolutions(unit, rset)
    resolved = resume_project(universe, accepted)
    replaced = resolved.record.statements[0]
    assert id(replaced) == retained_value_id


def test_report_declared_demand_basis_grounded():
    # #2: the ACTUAL emitted link unit carries the exact pending demand CID in
    # declaredDemandCids (that is why Rust selects DeclaredDemand).
    universe, unit = _universe_and_unit("def transform(items):\n    return items[0]\n")
    demand_cid = unit.candidates[0].demand.demand_cid
    declared = unit.parameter_owned_contract.declared_demand_cids
    assert demand_cid in declared, "pending demand must be self-declared"
    assert (
        len(declared) >= 1
    ), "declaredDemandCids is NON-empty (the prior claim was false)"
