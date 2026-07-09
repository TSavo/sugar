"""Open dig orientation: factory_walk support rows without ambient EUF poison.

Ambient for total strip stays closed ¬suffix-of. Open dig may record the
nested tower in factory_walk (status=support, no emitted_formula warrant).
"""

from __future__ import annotations

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


def test_base64_encode_ambient_still_no_suffix_with_orientation_walk() -> None:
    src = (
        "import itsdangerous.encoding as enc\n"
        "\n"
        "def test_no_pad():\n"
        '    assert enc.base64_encode(b"provekit") == b"cHJvdmVraXQ"\n'
    )
    report = build_literal_call_report(
        source=src,
        filename="test_token_padding.py",
        memento_file="test_token_padding.py",
    )
    assert report is not None
    contracts = [
        row.to_rpc()
        for row in report.payload.ir
        if hasattr(row, "to_rpc") and row.to_rpc().get("kind") == "function-contract"
    ]
    outer = next(
        c
        for c in contracts
        if c.get("bridgeSourceSymbol")
        == "call:itsdangerous.encoding.base64_encode"
    )
    post = outer["post"]
    assert post["kind"] == "not"
    assert post["operands"][0]["name"] == "suffix-of"
    assert "call:rstrip" not in str(post)

    walks = [w.to_rpc() if hasattr(w, "to_rpc") else w for w in report.payload.factory_walk]
    orientation = [
        w
        for w in walks
        if isinstance(w, dict)
        and (
            w.get("selected") == "python.open-dig-orientation"
            or (w.get("reason") or "").startswith("open dig orientation")
        )
    ]
    # Orientation is best-effort; when nested dig can finish, tower is visible.
    if orientation:
        blob = str(orientation)
        assert orientation[0].get("status") == "support"
        assert orientation[0].get("emittedFormula") is None or orientation[0].get(
            "emitted_formula"
        ) is None
        assert "call:rstrip" in blob or "rstrip" in blob
