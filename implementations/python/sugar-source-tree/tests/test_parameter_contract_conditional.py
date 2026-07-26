from __future__ import annotations

import tempfile

from sugar_lift_py_tests.caller_parameter_contract import (
    ContractConditionalConstructionV1,
)
from sugar_lift_py_tests.floor import UniverseValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.gap.panic import ConstructionPanic
import pytest
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _out(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path)).functions()).sugar().desugar()


def test_symbolic_parameter_subscript_constructs_one_pending_candidate(
    monkeypatch,
) -> None:
    from sugar_source_tree.nodes import Subscript

    original = Subscript._construct_sugar
    calls = 0

    def counted(self):
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(Subscript, "_construct_sugar", counted)
    out = _out("def transform(items):\n return items[0]\n")

    assert isinstance(out, Complete)
    assert isinstance(out.value, UniverseValue)
    pending = [
        row
        for row in out.value.record.statements
        if isinstance(row, ContractConditionalConstructionV1)
    ]
    assert len(pending) == 1
    conditional = pending[0]
    assert conditional.sole_demand().formal_coordinate_cid
    assert conditional.sole_demand().candidate_cid == conditional.candidate_cid
    assert conditional.sole_demand().demand_cid
    assert calls == 1
    with pytest.raises(ConstructionPanic, match="ParameterContractResolutionV1"):
        out.value.post()
