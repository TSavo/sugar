"""The dotted path over the wire: source_files -> functions -> call_sites ->
assertions, each level a projection of the collapse, each node addressed by
its sealed memento. Kit::sourceFiles[0].functions()[0].assertions[0], literal."""

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

        a_memento = next(
            n["memento"]
            for n in functions
            if n["memento"].get("source_function_name") == "A"
        )
        sites = server.call(
            "sugar.enumerate",
            {"level": "call_sites", "workspace_root": ws, "at": a_memento},
        )["nodes"]
        assert len(sites) == 1
        assert sites[0]["memento"]["span"]["start_line"] == 8  # the assert's line

        assertion = server.call(
            "sugar.enumerate",
            {
                "level": "assertions",
                "workspace_root": ws,
                "at": sites[0]["memento"],
                "seek": True,
            },
        )["nodes"]
        assert len(assertion) == 1
        assert assertion[0]["memento"]["source_cid"].startswith("blake3-512:")
    finally:
        server.close()
