"""The universe door must not downgrade a refusal to a gap.

Neither the full-tree ``seek=false`` mint nor the targeted ``seek=true``
door converts ``SugarNotWritten`` into an enumeration gap: a gap lets Rust
turn it into a diagnostic and seal an incomplete ``ir-document``.  The
refusal leaves by name.  This tooth pins that at the real JSON-RPC membrane.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests import lift_rpc, tree_enumerate
from sugar_source_tree.panic import SugarNotWritten


@pytest.mark.parametrize("seek", (False, True))
def test_universe_door_preserves_sugar_not_written_as_typed_loud(
    tmp_path, monkeypatch, seek
) -> None:
    """A catch of the refusal must recreate a successful result with a gap."""

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
            "seek": seek,
        },
    }
    requests = iter([request])
    sent = []
    monkeypatch.setattr(lift_rpc, "_BOUND_CONTRACT_REFS", None)
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
