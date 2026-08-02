"""With.sugar admits NeverSuppresses only via authenticated CM contract refs.

No raw-AST reparse of foreign ``__exit__``. Unauthenticated managers stay
honest loud (``ContextManagerResolutionConstructionGap`` /
``RuntimeSelectedContextManager``).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile
from with_resolution_fixture import source_file_with_preconstruction


def _fn(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write("import pytest\nimport contextlib\n" + src)
        path = f.name
    return next(source_file_with_preconstruction(Path(path)).functions())


def test_errstate_without_published_cm_contract_stays_loud():
    """Twin: np.errstate is not greened by re-parsing numpy's __exit__."""
    with pytest.raises(SugarNotWritten) as caught:
        _fn(
            "import numpy as np\n"
            "def A(z):\n"
            "    with np.errstate(all='ignore'):\n"
            "        z = z\n"
            "    return z\n"
        ).sugar()
    # Honest residual — never WithResourceSugar / NeverSuppresses without a ref.
    assert type(caught.value).__name__ == "SugarNotWritten"
    assert caught.value.kind == "unresolved-symbol"
    assert "NeverSuppresses" not in type(caught.value).__name__


def test_option_context_without_provider_contract_is_typed_loud():
    """Twin: generator CM is not greened by raw-AST return walks either."""
    with pytest.raises(SugarNotWritten) as caught:
        _fn(
            "from pandas import option_context\n"
            "def A(z):\n"
            "    with option_context('display.max_rows', 10):\n"
            "        z = z\n"
            "    return z\n"
        ).sugar()
    assert type(caught.value).__name__ == "SugarNotWritten"


def test_open_still_runtime_selected():
    """Builtin open stays loud — no fabricated NeverSuppresses from stdlib AST."""
    with pytest.raises(SugarNotWritten) as caught:
        _fn("def A(f):\n    with open(f):\n        pass\n    return f\n").sugar()
    assert type(caught.value).__name__ in (
        "SugarNotWritten",
        "RuntimeSelectedContextManager",
    )


def test_pytest_raises_without_provider_contract_is_typed_loud():
    with pytest.raises(SugarNotWritten) as caught:
        _fn(
            "def A(z):\n"
            "    with pytest.raises(ValueError):\n"
            "        raise ValueError\n"
            "    return z\n"
        ).sugar()
    assert type(caught.value).__name__ == "SugarNotWritten"
