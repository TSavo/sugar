"""The universe scan records a function's refusal as its one refused member.

Step 8 (the owner, 2026-11-12): the ``.proof`` has ONE member kind for "not
decided here, and why". Every refusal by name raised constructing or
reducing one function (``SugarNotWritten``, a free variable outside its
declared scope, any ``LifterRefusal`` but ``BackendDefect``) is that
function's ``undecided`` row, with the refusal's name and reason; the file is
served and the proof never silently lacks the function. A ``BackendDefect``
is not a function's refusal: it leaves by name through the typed-loud
JSON-RPC membrane. These teeth pin both at the real JSON-RPC door.
"""

from __future__ import annotations

from types import SimpleNamespace

from sugar_lift_py_tests import lift_rpc, tree_enumerate
from sugar_source_tree.panic import BackendDefect, SugarNotWritten


def _serve_universe(tmp_path, monkeypatch, refusal) -> dict:
    subject = tmp_path / "subject.py"
    subject.write_text("def subject():\n    return 1\n", encoding="utf-8")

    def refuse_contract_rows(_fn, _file_rel):
        raise refusal

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
    monkeypatch.setattr(tree_enumerate, "function_contract_rows", refuse_contract_rows)
    monkeypatch.setattr(lift_rpc, "_recv", lambda: next(requests, None))
    monkeypatch.setattr(lift_rpc, "_send", sent.append)

    lift_rpc._serve()

    assert len(sent) == 1, sent
    return sent[0]


def test_sugar_not_written_is_the_functions_refused_member(
    tmp_path, monkeypatch
) -> None:
    """A by-name refusal of one function is its `undecided` row, not the file's error."""

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

    response = _serve_universe(tmp_path, monkeypatch, panic)

    assert "error" not in response, response
    nodes = response["result"]["nodes"]
    assert response["result"]["gaps"] == []
    assert len(nodes) == 1, nodes
    node = nodes[0]
    assert node["memento"]["source_function_name"] == "subject"
    audit = node["audit"]
    assert audit["kind"] == "undecided"
    assert audit["symbol"] == "python:subject.subject"
    assert audit["site"]["file"] == "subject.py"
    assert audit["reason"] == {
        "refused": {"owner": panic.owner, "observed": panic.observed}
    }


def test_backend_defect_leaves_by_name_as_typed_loud(tmp_path, monkeypatch) -> None:
    """A broken backend is never recorded as a function's refusal."""

    defect = BackendDefect(
        blame=SimpleNamespace(filename="subject.py", line=1, col=0),
        owner="test.backend",
        observed="a degenerate span",
        requested="a span inside the source",
        fix="repair the adapter",
    )

    response = _serve_universe(tmp_path, monkeypatch, defect)

    assert "result" not in response, response
    assert response["error"]["code"] == -32001
    assert response["error"]["data"] == {
        "kind": "typed-loud",
        "exception_type": "BackendDefect",
        "stage": "dispatch",
        "diagnostic": {
            "owner": defect.owner,
            "blame": "subject.py:1:0",
            "observed": defect.observed,
            "requested": defect.requested,
            "fix": defect.fix,
        },
    }


def _overlapping_face():
    """Two completed arms nothing proves exclusive: no carried partition,
    guards of two unrelated atoms."""
    from sugar_lift_py_tests.ir import atomic, make_var
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet

    def guard(name):
        return atomic(name, [make_var("state")])

    return ExitSet((Completed(guard("p"), "one"), Completed(guard("q"), "two")))


def test_the_factoring_refusal_is_the_functions_refused_member(
    tmp_path, monkeypatch
) -> None:
    """``ExitSet.factor_completed``'s refusal is a refusal by name (#7757).

    It was a ``ValueError``: a function whose reduction met it was not its
    own refused member; the error went past the scan's one refusal rule and
    ended the whole file's mint (the lane's ``mint-exit-1``: 50 pandas files
    on d5dcbab5c).  Now the function states it, by its owner, and the file is
    served.  The refusal here is the real one, raised by the real admission."""
    from sugar_lift_py_tests.outcome.exit_set import ExitSetFactoringGap
    from sugar_source_tree.panic import LifterRefusal

    try:
        _overlapping_face().factor_completed()
    except ExitSetFactoringGap as raised:
        gap = raised
    else:  # pragma: no cover - the admission must refuse
        raise AssertionError("overlapping arms were factored")
    assert isinstance(gap, LifterRefusal)

    response = _serve_universe(tmp_path, monkeypatch, gap)

    assert "error" not in response, response
    (node,) = response["result"]["nodes"]
    audit = node["audit"]
    assert audit["kind"] == "undecided"
    assert audit["symbol"] == "python:subject.subject"
    assert audit["reason"]["refused"]["owner"] == "ExitSet.factor_completed"
    assert "not provably exclusive" in audit["reason"]["refused"]["observed"]


def test_the_joined_key_asks_the_admission_and_never_holds_the_refusal() -> None:
    """``if_sugar._joined_evaluation`` reads two values on one path as a key
    not bound: it asks ``completed_face_factors``, the one admission
    ``factor_completed`` refuses by, instead of catching the refusal."""
    import inspect

    from sugar_lift_py_tests.ir import atomic, make_var, not_
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet
    from sugar_lift_py_tests.sugar import if_sugar

    assert _overlapping_face().completed_face_factors() is False
    guard = atomic("p", [make_var("state")])
    partition = ExitSet((Completed(guard, "one"), Completed(not_(guard), "two")))
    assert partition.completed_face_factors() is True
    assert len(partition.factor_completed().exits) == 1
    assert "except" not in inspect.getsource(if_sugar._joined_evaluation)
