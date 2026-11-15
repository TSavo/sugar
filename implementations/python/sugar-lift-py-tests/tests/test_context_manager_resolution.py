from sugar_lift_py_tests import lift_rpc
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1


def test_the_construction_context_holds_no_table():
    """A ``with``'s manager is what its head reduces to (#7757): the context
    carries no table of managers, non-managers, opaque calls, call frames or
    With demand rows.  Nothing outside the tree fills anything a node reads;
    a call applies its own definition's frame."""
    context = TreeConstructionContextV1.for_source_call_construction()
    for name in (
        "contract_refs",
        "source_derived_contract_refs",
        "source_non_manager_heads",
        "opaque_source_call_obligations",
        "source_call_frames",
    ):
        assert not hasattr(context, name), name


def test_the_context_names_only_its_workspace_root(tmp_path):
    """Lying twin: the one thing the context does carry is the workspace."""
    context = lift_rpc.tree_construction_context_for_workspace(tmp_path)
    assert context == TreeConstructionContextV1(workspace_root=str(tmp_path))
    assert context != TreeConstructionContextV1.for_source_call_construction()


def test_no_with_demand_derivation_remains():
    for name in (
        "provisional_contract_refs_from_demands",
        "per_source_provisional_contract_refs",
        "_PerSourceDemandRows",
        "_context_manager_rows_for_paths",
        "_enumerate_contract_refs",
    ):
        assert not hasattr(lift_rpc, name), name


def test_context_manager_edges_is_not_an_enumeration_level(tmp_path, monkeypatch):
    """Python keeps edge construction; the source-agnostic protocol does not."""
    sent = []
    monkeypatch.setattr(lift_rpc, "_send", sent.append)

    lift_rpc._handle_enumerate(
        10,
        {
            "level": "context-manager-edges",
            "workspace_root": str(tmp_path),
            "options": {},
        },
    )

    assert len(sent) == 1
    error = sent[0]["error"]
    assert error == {
        "code": -32602,
        "message": "sugar.enumerate: unknown level 'context-manager-edges'",
    }
