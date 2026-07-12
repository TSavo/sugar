from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import FunctionCallable
from sugar_lift_py_tests.lift_rpc import (
    _module_import_temporal,
    audit_lift_file,
)
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment


def test_function_calls_module_sibling_defined_later() -> None:
    source = (
        "def first(x):\n"
        "    return later(x)\n"
        "\n"
        "def later(x):\n"
        "    return x\n"
    )
    _payload, gaps = audit_lift_file(source, "siblings.py", hold_panic=True)
    assert not [gap for gap in gaps if gap.info.get("observed") == "later"]


def test_module_temporal_binds_all_defs_before_root_reduction() -> None:
    source = "def first():\n    return second()\ndef second():\n    return 2\n"
    module = SourceFragment.from_source(source, "siblings.py").statements()[0]
    temporal = _module_import_temporal(module, default_catalog())
    assert isinstance(temporal.value_for("first"), FunctionCallable)
    assert isinstance(temporal.value_for("second"), FunctionCallable)


def test_truly_undefined_sibling_still_panics() -> None:
    source = "def first():\n    return never_defined\n"
    with pytest.raises(FactoryPanic, match="never_defined"):
        audit_lift_file(source, "undefined.py", hold_panic=False)
