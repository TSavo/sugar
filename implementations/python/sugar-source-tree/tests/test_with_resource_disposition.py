"""With.sugar routes source-proven NeverSuppresses through WithResourceSugar."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile
from with_authority_fixture import source_file_with_preconstruction


def _fn(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write("import pytest\nimport contextlib\n" + src)
        path = f.name
    return next(source_file_with_preconstruction(Path(path)).functions())


def test_errstate_without_published_cm_contract_stays_loud():
    with pytest.raises(SugarNotWritten) as caught:
        _fn(
            "import numpy as np\n"
            "def A(z):\n"
            "    with np.errstate(all='ignore'):\n"
            "        z = z\n"
            "    return z\n"
        ).sugar()
    assert type(caught.value).__name__ == "ContextManagerResolutionConstructionGap"
    assert caught.value.kind == "runtime-selected"


@pytest.mark.xfail(
    reason="option_context is a generator @contextmanager, not a class __exit__. "
    "This cut proves class __exit__ only (static, no importlib/execution). The "
    "generator never-suppresses proof is a separate, soundness-sensitive cut: "
    "proving it wrong would unsoundly dissolve a suppressing manager. Deferred "
    "to the generator-@contextmanager proof; routed to the architect.",
    strict=True,
)
def test_option_context_routes_to_with_resource_sugar():
    sugar = _fn(
        "from pandas import option_context\n"
        "def A(z):\n"
        "    with option_context('display.max_rows', 10):\n"
        "        z = z\n"
        "    return z\n"
    ).sugar()
    from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar
    from sugar_lift_py_tests.context_manager_contract import NeverSuppresses

    with_s = next(s for s in sugar.statements if isinstance(s, WithResourceSugar))
    assert isinstance(with_s.disposition, NeverSuppresses)


def test_open_still_runtime_selected():
    with pytest.raises(SugarNotWritten):
        _fn("def A(f):\n    with open(f):\n        pass\n    return f\n").sugar()


def test_pytest_raises_still_assertion_contract():
    sugar = _fn(
        "def A(z):\n"
        "    with pytest.raises(ValueError):\n"
        "        raise ValueError\n"
        "    return z\n"
    ).sugar()
    from sugar_lift_py_tests.sugar.with_contract_sugar import WithContractSugar

    assert any(isinstance(s, WithContractSugar) for s in sugar.statements)
