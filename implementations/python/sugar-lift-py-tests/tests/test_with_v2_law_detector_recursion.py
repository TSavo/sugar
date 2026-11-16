"""The With-v2 law detector's interpreter never re-enters a callee on its stack.

The detector abstract-interprets source; a recursive call chain in that source
once re-entered every callee whose abstract arguments had grown, until the C
stack overflowed (suite-shard exit 139 in
``test_no_consumer_enrollment_production_is_zero``).  A re-entry is now
answered by the live frame's summary, and the live frame is re-evaluated under
the re-entry's arguments until the summaries settle, so the cut keeps the law's
answer an over-approximation.
"""

from pathlib import Path

from with_v2_law_detector import Interpreter, ModuleGraph

# ``ping`` reaches the admission lookup only through the re-entry ``pong``
# makes with the semantic table: the outer frame's own table is ordinary.  A
# cut that answered the re-entry with "nothing" would report zero rows.
MUTUALLY_RECURSIVE_PAIR = """
class ProtocolResource:
    pass


class Sugar:
    pass


class WithResourceSugar(Sugar):
    pass


def make_payload():
    return ProtocolResource()


doors = {"anything": make_payload}


def ping(table, key):
    if key:
        return pong(key)
    builder = table[key]
    return WithResourceSugar(builder())


def pong(key):
    return ping(doors, key)


def demand(key):
    return ping(key, key)
"""


class StackRecordingInterpreter(Interpreter):
    """Records every callee whose body the interpreter is inside."""

    def __init__(self, graph: ModuleGraph):
        self.open_bodies: list[str] = []
        self.reentered: list[tuple[str, ...]] = []
        super().__init__(graph)

    def exec_block(self, module, body, env, chain, *, sink_slice):
        callee = chain[-1]
        if callee in self.open_bodies:
            self.reentered.append((*self.open_bodies, callee))
        self.open_bodies.append(callee)
        try:
            return super().exec_block(module, body, env, chain, sink_slice=sink_slice)
        finally:
            self.open_bodies.pop()


def _pair_graph(tmp_path: Path) -> ModuleGraph:
    source = tmp_path / "recursive_pair.py"
    source.write_text(MUTUALLY_RECURSIVE_PAIR, encoding="utf-8")
    return ModuleGraph.from_paths([source])


def test_mutually_recursive_pair_never_reenters_a_callee(tmp_path):
    interpreter = StackRecordingInterpreter(_pair_graph(tmp_path))
    interpreter.enrollment_rows()
    assert interpreter.reentered == []
    assert interpreter.active == {}


def test_recursion_cut_keeps_the_law_an_over_approximation(tmp_path):
    rows = StackRecordingInterpreter(_pair_graph(tmp_path)).enrollment_rows()
    sinks = {row.sink_site.line for row in rows}
    demand_line = MUTUALLY_RECURSIVE_PAIR.splitlines().index("def demand(key):") + 1
    assert demand_line in sinks, rows
    assert all(row.canonical == "recursive_pair.ProtocolResource" for row in rows)
    assert all(
        row.reason in {"consumer-spelling-enrollment", "consumer-enrollment-rpc-lane"}
        for row in rows
    )
