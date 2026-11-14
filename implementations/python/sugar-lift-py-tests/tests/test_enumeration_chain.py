"""The functions level over the wire (the board door's D2): each node
addressed by its sealed memento. The levels below it (call_sites,
assertions) are gone (#7757)."""

from __future__ import annotations

import json
import subprocess
import sys

_SOURCE = (
    'def enc(x):\n    if x == "ccc":\n        return "yyy"\n    return x\n'
    "\n"
    "def A(z):\n    y = f(3)\n    assert y == 7\n    return z\n"
)


class _Server:
    """One persistent RPC server; requests streamed, responses read by id."""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import sys; sys.path[:0]=['src']; "
                "from sugar_lift_py_tests.lift_rpc import main; main()",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        self._next_id = 0

    def call(self, method: str, params: dict) -> dict:
        self._next_id += 1
        msg_id = self._next_id
        self.proc.stdin.write(
            json.dumps(
                {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}
            )
            + "\n"
        )
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise AssertionError("server exited early")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == msg_id:
                return msg.get("result") or msg.get("error")

    def close(self) -> None:
        try:
            self.proc.stdin.write(
                json.dumps({"jsonrpc": "2.0", "id": 99, "method": "shutdown"}) + "\n"
            )
            self.proc.stdin.flush()
        except Exception:
            pass
        self.proc.terminate()


def test_the_dotted_path_end_to_end(tmp_path) -> None:
    (tmp_path / "vendor.py").write_text(_SOURCE, encoding="utf-8")
    ws = str(tmp_path)

    server = _Server()
    try:
        functions = server.call(
            "sugar.enumerate",
            {"level": "functions", "workspace_root": ws, "at": {"file": "vendor.py"}},
        )["nodes"]
        names = [n["memento"].get("source_function_name") for n in functions]
        assert names == ["enc", "A"]  # no duplicate enclosing-only node
        for node in functions:
            assert node["memento"]["source_cid"].startswith("blake3-512:")
    finally:
        server.close()
