"""The minority report as the RPC wire payload -- the roll call served over the
wire so `sugar lift --report --visual` can render present (Blue) / absent
(Yellow). Pure: source in, partition out; no factory, no Rust."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sugar_lift_py_tests.tree_enumerate import minority_report_payload


def _payload(src: str) -> dict:
    d = tempfile.mkdtemp()
    p = Path(d) / "m.py"
    p.write_text(src)
    return minority_report_payload(p, "m.py")


def test_payload_partitions_every_node_present_or_absent() -> None:
    payload = _payload("def a(z):\n    return z\ndef b(xs):\n    del xs\n")
    assert payload["file"] == "m.py"
    answers = {r["answer"] for r in payload["rows"]}
    assert answers == {"present", "absent"}
    # a's body desugared -> present; the unwritten Delete -> absent (minority).
    kinds = {(r["kind"], r["answer"]) for r in payload["rows"]}
    assert ("Return", "present") in kinds
    assert ("Delete", "absent") in kinds


def test_R_is_the_size_of_the_minority() -> None:
    payload = _payload("def a(z):\n    return z\ndef b(xs):\n    del xs\n")
    absent = [r for r in payload["rows"] if r["answer"] == "absent"]
    assert payload["R"] == len(absent)


def test_every_row_is_cid_keyed_and_located() -> None:
    payload = _payload("def a(z):\n    return z\n")
    cids = [r["cid"] for r in payload["rows"]]
    assert len(cids) == len(set(cids))  # unique by CID
    assert all(r["cid"].startswith("blake3-512:") for r in payload["rows"])
    assert all("start_line" in r["span"] for r in payload["rows"])


if __name__ == "__main__":
    test_payload_partitions_every_node_present_or_absent()
    test_R_is_the_size_of_the_minority()
    test_every_row_is_cid_keyed_and_located()
    print("ok")
