from __future__ import annotations

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def test_renamed_function_expansion_exhaustion_stays_typed_loud(monkeypatch) -> None:
    import sugar_source_tree.nodes as nodes

    source = "def arbitrary(value):\n    assigned = value\n    return assigned\n"
    tree = SourceFile((source, "arbitrary_module.py", blake3_512_of(source.encode())))
    function = next(iter(tree.functions()))
    monkeypatch.setattr(nodes, "_FUNCTION_CONSTRUCTION_NODE_LIMIT", 4)

    with pytest.raises(SugarNotWritten, match="expansion bound"):
        function.sugar()
