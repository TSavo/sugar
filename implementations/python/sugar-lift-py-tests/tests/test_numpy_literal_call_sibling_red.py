from __future__ import annotations

import json
from pathlib import Path

from sugar_lift_py_tests.witness_harness import (
    WitnessPipelineError,
    run_source_through_real_solver,
)


def test_numpy_add_literal_call_reduces_to_sibling_fact(tmp_path: Path) -> None:
    """Computable integer ufuncs need a reduced-value sibling fact.

    Boundary: this pins only literal integer arithmetic. Floating/transcendental
    or analysis-heavy operations such as np.sin, np.sqrt, and np.fft remain
    opaque EUF until a deliberate numeric semantics slice teaches them.
    """

    observed = {
        "truthful": _verdict_or_error(
            tmp_path / "truthful",
            "import numpy as np\n"
            "\n"
            "def test_np_add_truthful():\n"
            "    assert np.add(2, 3) == 5\n",
        ),
        "lying": _verdict_or_error(
            tmp_path / "lying",
            "import numpy as np\n"
            "\n"
            "def test_np_add_lying():\n"
            "    assert np.add(2, 3) == 6\n",
        ),
    }
    print(json.dumps(observed, indent=2, sort_keys=True))

    assert observed == {"truthful": "sat", "lying": "unsat"}


def _verdict_or_error(project: Path, source: str) -> str:
    try:
        return run_source_through_real_solver(project, source).verdict
    except WitnessPipelineError as exc:
        return f"error: {exc}"
