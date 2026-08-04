"""Full-tree universe mint must not downgrade product panics to gaps.

The targeted ``seek=true`` universe door may retain an abstract gap while it
tries an applied call-site construction (``test_dig_with_args`` owns that
composition law).  The full-tree ``seek=false`` mint has no such second
construction: converting ``SugarNotWritten`` to a gap lets Rust turn it into a
diagnostic and seal an incomplete ``ir-document``.  This tooth pins the other
arm at the real JSON-RPC membrane.
"""

from __future__ import annotations

from types import SimpleNamespace

from sugar_lift_py_tests import lift_rpc, tree_enumerate
from sugar_source_tree.panic import SugarNotWritten


def test_full_tree_universe_scan_preserves_sugar_not_written_as_typed_loud(
    tmp_path, monkeypatch
) -> None:
    """Removing the no-seek rethrow must recreate a successful empty result."""

    subject = tmp_path / "subject.py"
    subject.write_text("def subject():\n    return 1\n", encoding="utf-8")
    panic = SugarNotWritten(
        blame=SimpleNamespace(filename="subject.py", line=2, col=4),
        owner="CallSiteValue.attribute",
        observed="undecided receiver runtime type or member semantics: CallSiteValue.bytes",
        requested="a source-authenticated attribute success or exceptional exit",
        fix=(
            "carry receiver-type and member testimony to the attribute floor; "
            "do not guess AttributeError or invent a completed projection"
        ),
    )

    def refuse_contract_rows(_fn, _file_rel):
        raise panic

    request = {
        "jsonrpc": "2.0",
        "id": 17,
        "method": "sugar.enumerate",
        "params": {
            "level": "universe",
            "workspace_root": str(tmp_path),
            "at": {"file": subject.name},
            "seek": False,
        },
    }
    requests = iter([request])
    sent = []
    monkeypatch.setattr(lift_rpc, "_BOUND_CONTRACT_REFS", None)
    monkeypatch.setattr(lift_rpc, "_BOUND_CALL_CONTRACT_REFS", None)
    monkeypatch.setattr(tree_enumerate, "function_contract_rows", refuse_contract_rows)
    monkeypatch.setattr(lift_rpc, "_recv", lambda: next(requests, None))
    monkeypatch.setattr(lift_rpc, "_send", sent.append)

    lift_rpc._serve()

    assert len(sent) == 1, sent
    response = sent[0]
    assert "result" not in response, response
    assert response["error"]["code"] == -32001
    assert response["error"]["data"] == {
        "kind": "typed-loud",
        "exception_type": "SugarNotWritten",
        "stage": "dispatch",
        "diagnostic": {
            "owner": panic.owner,
            "observed": panic.observed,
            "requested": panic.requested,
            "fix": panic.fix,
        },
    }
    assert "subject.py:2:4" in response["error"]["message"]
