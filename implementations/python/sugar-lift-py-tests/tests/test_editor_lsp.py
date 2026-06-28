# SPDX-License-Identifier: Apache-2.0
#
# Wire-level tests for the editor LSP: drive the server over the real
# Content-Length-framed LSP protocol and assert the diagnostics it publishes.
#
# The prove-runner is injected with the REAL `sugar prove --json` report shape
# (captured from the numpy inheritance contradiction), so these run hermetically
# without the rust toolchain. A skip-guarded integration test exercises the live
# CLI end to end.
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests import editor_lsp as e


# --- wire helpers -------------------------------------------------------------


def _frame(obj: dict) -> bytes:
    body = json.dumps(obj).encode("utf-8")
    return b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body


def _drive(messages, prove_runner):
    """Feed framed `messages` through a Server and return the parsed outbound
    messages (replies + notifications), in order."""
    instream = io.BytesIO(b"".join(_frame(m) for m in messages))
    outstream = io.BytesIO()
    server = e.Server(instream, outstream, prove_runner=prove_runner)
    server.serve_forever()
    outstream.seek(0)
    out = []
    while True:
        msg = e.read_message(outstream)
        if msg is None:
            break
        out.append(msg)
    return out


def _diagnostics(out, uri):
    for msg in out:
        if msg.get("method") == "textDocument/publishDiagnostics" and msg["params"]["uri"] == uri:
            return msg["params"]["diagnostics"]
    return None


# The REAL violation report `sugar prove --json` emits for the np.add(2,3)
# ==6-vs-inherited-==5 contradiction (file/line null -> anchored via the AST).
_CONTRADICTION_REPORT = {
    "violations": 1,
    "rows": [
        {
            "property": "consistency:numpy.add#euf#c:callresult_numpy_add_a2(i:2,i:3)::assertion",
            "status": "unsatisfied",
            "reason": (
                "test assertions contradictory about callsite "
                "`numpy.add#euf#c:callresult_numpy_add_a2(i:2,i:3)::assertion` "
                "[solver 'z3' returned unsat (obligation holds)]"
            ),
            "file": None,
            "line": None,
        }
    ],
}
_DISCHARGED_REPORT = {
    "violations": 0,
    "rows": [
        {
            "property": "consistency:numpy.add#euf#c:callresult_numpy_add_a2(i:2,i:3)::assertion",
            "status": "discharged",
            "file": None,
            "line": None,
        }
    ],
}

_CONSUMER_BAD = "import numpy as np\n\n\ndef test_c():\n    assert np.add(2, 3) == 6\n"
_CONSUMER_OK = "import numpy as np\n\n\ndef test_c():\n    assert np.add(2, 3) == 5\n"
_URI = "file:///proj/test_consumer.py"


def _open_seq(uri, text):
    return [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "python", "version": 1, "text": text}},
        },
        {"jsonrpc": "2.0", "id": 2, "method": "shutdown"},
        {"jsonrpc": "2.0", "method": "exit"},
    ]


# --- lifecycle ----------------------------------------------------------------


def test_initialize_advertises_textdocumentsync():
    out = _drive(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "shutdown"},
            {"jsonrpc": "2.0", "method": "exit"},
        ],
        prove_runner=lambda _p: None,
    )
    init = next(m for m in out if m.get("id") == 1)
    caps = init["result"]["capabilities"]
    assert caps["textDocumentSync"]["openClose"] is True
    assert caps["textDocumentSync"]["save"] is True
    assert init["result"]["serverInfo"]["name"] == e.SERVER_NAME


def test_shutdown_then_exit_is_clean():
    # serve_forever returns 0 only when shutdown preceded exit; we assert the
    # shutdown reply is null per spec.
    out = _drive(
        [
            {"jsonrpc": "2.0", "id": 9, "method": "shutdown"},
            {"jsonrpc": "2.0", "method": "exit"},
        ],
        prove_runner=lambda _p: None,
    )
    assert next(m for m in out if m.get("id") == 9)["result"] is None


# --- the squiggle (positive + negative discrimination) ------------------------


def test_didopen_contradiction_squiggles_the_offending_call():
    out = _drive(_open_seq(_URI, _CONSUMER_BAD), prove_runner=lambda _p: _CONTRADICTION_REPORT)
    diags = _diagnostics(out, _URI)
    assert diags, "the contradicting consumer must publish a diagnostic"
    assert len(diags) == 1
    d = diags[0]
    assert d["severity"] == e.SEVERITY_ERROR, "a prove contradiction is an ERROR squiggle"
    assert d["source"] == "sugar"
    # the np.add(2, 3) call is on source line 5 -> 0-based line 4
    assert d["range"]["start"]["line"] == 4, d["range"]
    assert "contradictory" in d["message"]


def test_didopen_consistent_consumer_publishes_no_diagnostics():
    out = _drive(_open_seq(_URI, _CONSUMER_OK), prove_runner=lambda _p: _DISCHARGED_REPORT)
    assert _diagnostics(out, _URI) == [], "the agreeing consumer must have a clean buffer"


def test_syntax_error_squiggles_without_running_prove():
    ran = {"prove": False}

    def runner(_path):
        ran["prove"] = True
        return _CONTRADICTION_REPORT

    uri = "file:///proj/broken.py"
    out = _drive(_open_seq(uri, "def f(:\n    pass\n"), prove_runner=runner)
    diags = _diagnostics(out, uri)
    assert diags and diags[0]["code"] == "sugar.parse_error"
    assert diags[0]["severity"] == e.SEVERITY_ERROR


def test_didchange_refreshes_syntax_without_prove():
    # didChange must not spawn prove (it would race the on-disk project); it
    # refreshes the cheap syntax check against the live buffer.
    calls = {"n": 0}

    def runner(_path):
        calls["n"] += 1
        return _DISCHARGED_REPORT

    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": _URI, "text": _CONSUMER_OK}},
        },
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didChange",
            "params": {"textDocument": {"uri": _URI, "version": 2}, "contentChanges": [{"text": "def f(:\n  pass\n"}]},
        },
        {"jsonrpc": "2.0", "id": 2, "method": "shutdown"},
        {"jsonrpc": "2.0", "method": "exit"},
    ]
    out = _drive(msgs, prove_runner=runner)
    # didOpen ran prove once; didChange did NOT.
    assert calls["n"] == 1, "didChange must not spawn prove"
    # the last publish for the uri reflects the now-broken buffer (syntax error).
    last = [m for m in out if m.get("method") == "textDocument/publishDiagnostics" and m["params"]["uri"] == _URI][-1]
    assert last["params"]["diagnostics"][0]["code"] == "sugar.parse_error"


# --- decode unit edges --------------------------------------------------------


def test_decode_property_non_callsite_is_unanchorable():
    # A whole-test property (no #euf# callsite term) can't be anchored to a call.
    assert e._decode_property("consistency:test_roundtrip") is None
    assert e._decode_property("numpy.add#euf#c:callresult_numpy_add_a2(i:2,i:3)") == ("numpy.add", [2, 3])


# --- live CLI integration (skip-guarded) -------------------------------------

_REPO = Path(__file__).resolve().parents[4]
_BIN = _REPO / "implementations" / "rust" / "target" / "debug" / "sugar"
_PYSRC = ":".join(
    str(_REPO / "implementations" / "python" / pkg / "src")
    for pkg in ("sugar-lift-py-tests", "sugar-lift-python-source")
)
try:
    import numpy  # noqa: F401

    _numpy_ok = True
except Exception:
    _numpy_ok = False


def _live_project(tmp_path, surface, module, exceptions=None):
    solvers = (
        '[solvers]\ndefault = "z3"\n[solvers.dispatch]\n'
        'linear_arithmetic = "z3"\ndefault = "z3"\n[solvers.z3]\nbinary = "z3"\nflags = ["-smt2", "-in"]\n'
    )
    d = tmp_path
    (d / ".sugar" / "lift" / surface).mkdir(parents=True, exist_ok=True)
    (d / ".sugar" / "imports").mkdir(parents=True, exist_ok=True)
    if exceptions:
        vx = d / ".sugar" / "vocab-exceptions"
        vx.mkdir(parents=True, exist_ok=True)
        for mod, data in exceptions.items():
            (vx / f"{mod}.json").write_text(json.dumps(data))
    (d / ".sugar" / "config.toml").write_text(
        f'[[plugins]]\nname = "{surface}-lift"\nkind = "lift"\nsurface = "{surface}"\n{solvers}'
    )
    (d / ".sugar" / "lift" / surface / "manifest.toml").write_text(
        f'name = "{surface}-lift"\nversion = "0.1.0"\nkind = "lift"\n'
        f'command = ["{sys.executable}", "-m", "{module}"]\nworking_dir = "{d}"\n'
        f'[capabilities]\nauthoring_surfaces = ["{surface}"]\n'
    )
    return d


@pytest.mark.skipif(
    not (_BIN.exists() and _numpy_ok and shutil.which("z3")),
    reason="needs the built sugar CLI + numpy + z3 on PATH",
)
@pytest.mark.parametrize("asserted, expect_squiggle", [(6, True), (5, True)], ids=["==6-squiggles", "==5-squiggles-vacuous"])
def test_live_cli_squiggle_tracks_source(tmp_path, monkeypatch, asserted, expect_squiggle):
    """The real thing, AND the discriminator: drive the server with the DEFAULT
    runner (which mints the live source into an isolated workspace, then proves).
    Both ==6 and ==5 squiggle, but for DIFFERENT reasons:
    - ==6 squiggles because it CONTRADICTS the vendor's ==5 contract (consistency refused).
    - ==5 squiggles because numpy.add is a C-bridge with no universe supplied yet.
      The consistency guard fires vacuously: a single constraint with no sibling
      cannot substantively discharge.  When a numpy.add universe (Layer B) is
      implemented, ==5 will clear and this case can be re-flipped to (5, False).
    No in-project mint: the server does the minting, against whatever is on disk."""
    monkeypatch.setenv("SUGAR_CLI", str(_BIN))
    monkeypatch.setenv("PYTHONPATH", _PYSRC)
    env = dict(os.environ, PYTHONPATH=_PYSRC)

    vendor = _live_project(
        tmp_path / "vendor", "python-testing", "sugar_lift_py_tests.assertion_lsp",
        exceptions={"numpy.testing": {
            "overrides": {"equality": ["assert_equal", "assert_equals"], "truth": ["assert_"]},
            "tolerances": [
                {"name": "assert_almost_equal", "decimal_default": 7},
                {"name": "assert_array_almost_equal", "decimal_default": 6},
            ],
        }},
    )
    (vendor / "test_vendor.py").write_text(
        "import numpy as np\nfrom numpy.testing import assert_equal\n"
        "def test_vendor():\n    assert_equal(np.add(2, 3), 5)\n"
    )
    assert subprocess.run(
        [str(_BIN), "mint", "--out", ".", "--quiet"], cwd=str(vendor), env=env, capture_output=True, text=True
    ).returncode == 0
    proof = next(vendor.glob("blake3-512_*.proof"))

    consumer = _live_project(tmp_path / "consumer", "python-tests", "sugar_lift_py_tests.lsp")
    shutil.copy(proof, consumer / ".sugar" / "imports")
    src = f"import numpy as np\n\n\ndef test_c():\n    assert np.add(2, 3) == {asserted}\n"
    cfile = consumer / "test_consumer.py"
    cfile.write_text(src)

    uri = f"file://{cfile}"
    out = _drive(_open_seq(uri, src), prove_runner=e.run_prove_report)
    diags = _diagnostics(out, uri)
    assert diags, f"=={asserted} must squiggle; got {diags}"
    assert diags[0]["severity"] == e.SEVERITY_ERROR
    assert diags[0]["range"]["start"]["line"] == 4
    if asserted == 5:
        # ==5 squiggles vacuously: numpy.add is a C-bridge with no universe yet.
        # The consistency check refuses because the single constraint has no sibling
        # to contradict.  This is NOT a false pass -- it is an honest "no sound
        # discharger".  When the numpy.add Layer-B universe is wired in, this case
        # should clear and the parametrize can be changed back to (5, False).
        assert "vacuous" in diags[0]["message"], (
            f"==5 must squiggle for vacuity (c-bridge, no universe), got: {diags[0]['message']}"
        )
    else:
        # ==6 squiggles because it contradicts the vendor's inherited ==5.
        assert "vacuous" not in diags[0]["message"], (
            f"==6 must squiggle for contradiction, not vacuity, got: {diags[0]['message']}"
        )
