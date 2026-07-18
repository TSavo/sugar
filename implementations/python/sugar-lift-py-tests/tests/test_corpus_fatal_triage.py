from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from corpus_fatal_triage import _child_payload  # noqa: E402


def test_factory_panic_routes_through_audit_membrane_as_loud_child_row(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unsupported.py"
    source.write_text("def broken():\n    type T = int\n", encoding="utf-8")

    testimony, returncode = _child_payload(source, "demo/unsupported.py")

    assert returncode == 3
    assert testimony["outcome"] == "factory-panic"
    assert testimony["exception_type"] == "FactoryPanic"
    assert testimony["file"] == "demo/unsupported.py"
    assert testimony["gap"]["owner"] == "python.factory"
    assert testimony["gap"]["observed"] == "TypeAlias"


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
