"""SIN CLUSTER 6 coordinate 4 — manager construction ExitSet recovery.

Control flow must not be driven by substring-matching panic message prose
(``\"ExitSet\" in str(observed)``). Recovery digs ``reduce_source_outcome`` and
discriminates by exact outcome type. If the type does not carry what is
needed, the path returns a typed gap — it does not read the message.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import sugar_lift_python_source.manager_construction as manager_construction
from sugar_lift_python_source.manager_construction import construct_manager_behavior


def test_construct_manager_behavior_has_no_panic_message_substring_match() -> None:
    """Truthful instrument: ExitSet prose substring gate is deleted; typed path remains."""
    src = inspect.getsource(construct_manager_behavior)
    assert 'if "ExitSet" in str(observed):' not in src
    assert "if 'ExitSet' in str(observed):" not in src
    assert '"ExitSet" in str(' not in src
    assert "isinstance(outcome, ExitSet)" in src
    assert "isinstance(outcome, Complete)" in src
    assert "reduce_source_outcome" in src


def test_lying_twin_panic_prose_substring_gate_is_absent() -> None:
    """Lying twin: reintroducing message-driven control must fail this suite."""
    module_src = Path(manager_construction.__file__).read_text(encoding="utf-8")
    forbidden = 'if "ExitSet" in str(observed):'
    assert forbidden not in module_src
    # Also refuse the looser form that matches any str(observed) ExitSet probe.
    assert any(
        line.strip().startswith("if ")
        and "ExitSet" in line
        and "str(observed)" in line
        for line in module_src.splitlines()
    ) is False
