from importlib import metadata
from pathlib import Path

import pytest


def test_real_pandas_plain_halt_advances_to_typed_exit_gap():
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_source_tree.panic import ContextManagerResolutionConstructionGap

    pandas_distribution = metadata.distribution("pandas")
    install_root = Path(pandas_distribution.locate_file("")).resolve()
    pandas_root = install_root / "pandas"
    path = pandas_root / "tests/test_errors.py"
    assert path.is_file()

    source_file = open_source_file_for_construction(
        path,
        root=install_root,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=True,
    )
    function = next(
        function
        for function in source_file.functions()
        if function.name == "test_catch_undefined_variable_error"
    )

    with pytest.raises(ContextManagerResolutionConstructionGap) as raised:
        function.sugar().desugar()

    gap = raised.value
    assert gap.kind == "exit-may-halt"
    assert gap.coordinate.start_line == 84
    assert gap.coordinate.start_col == 9
    assert "attribute:ObjectValue" in gap.observed
