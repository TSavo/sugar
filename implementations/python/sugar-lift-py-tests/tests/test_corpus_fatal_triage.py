from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from corpus_fatal_triage import _child_payload  # noqa: E402


def test_completed_child_preserves_typed_effect_testimony() -> None:
    import pandas

    root = Path(pandas.__file__).resolve().parent
    relative = "tests/arrays/masked/test_arithmetic.py"
    testimony, returncode = _child_payload(root / relative, f"pandas/{relative}")

    assert returncode == 0
    assert testimony["outcome"] == "completed"
    effects = testimony["effects"]
    assert effects
    assert all(
        set(effect) == {"effect", "name", "status", "reason"} for effect in effects
    )
    assert any(
        effect["effect"] == "SequenceRepetitionRuntimeEffect"
        and effect["status"] == "runtime-effect"
        and "runtime __index__/length semantics" in effect["reason"]
        for effect in effects
    )
