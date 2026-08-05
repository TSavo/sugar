"""Attribute/mixed unpack is not a binding pattern — do not raise foreign-target.

G class from black seal (24 files): shapes like
  self.a, self.b = ...
  out, codes[-1] = ...
  columns[name], buf = ...

These are intentionally NOT enrolled as lexical binding patterns. Asking
``require_target_pattern`` for them was a hierarchy lie: non-binding unpack
dressed as foreign-target-occurrence, aborting the whole file.
"""

from __future__ import annotations

from pathlib import Path

from sugar_source_tree.nodes import Assign
from sugar_source_tree.reporter import NULL_REPORTER
from sugar_source_tree.tree import SourceFile


def _open(tmp_path: Path, name: str, source: str) -> SourceFile:
    path = tmp_path / name
    path.write_text(source)
    # Use path-based open so unit binds module + target patterns.
    from sugar_lift_python_source.source_oracle import workspace_path_source

    identity = workspace_path_source(str(path), root=str(tmp_path))
    return SourceFile(identity, reporter=NULL_REPORTER)


def test_attribute_only_unpack_substitution_binding_does_not_raise(
    tmp_path: Path,
) -> None:
    """``self.a, self.b = f()`` — no binding pattern, no foreign-target raise."""
    sf = _open(
        tmp_path,
        "attr_unpack.py",
        "class H:\n"
        "    def install(self, left, right):\n"
        "        self.left, self.right = left, right\n",
    )
    assignment = next(n for n in sf.nodes() if isinstance(n, Assign))
    assert (
        assignment.target_pattern_enrollment.reason
        == "consumer-shape-not-enrolled"
    )
    # The hierarchy door: substitution_binding must not raise.
    binding = assignment.substitution_binding({})
    assert binding is None or binding == {}


def test_mixed_name_subscript_unpack_does_not_raise_foreign_target(
    tmp_path: Path,
) -> None:
    """``out, codes[-1] = a, b`` — mixed Name+Subscript, not a pure Name pattern."""
    sf = _open(
        tmp_path,
        "mixed_unpack.py",
        "def f(out, codes, a, b):\n" "    out, codes[-1] = a, b\n" "    return out\n",
    )
    assignment = next(n for n in sf.nodes() if isinstance(n, Assign))
    # May or may not enroll depending on _is_binding_target_pattern (mixed = no).
    assert (
        assignment.target_pattern_enrollment.reason == "consumer-shape-not-enrolled"
    )
    binding = assignment.substitution_binding({})
    # Must not raise TargetPatternConstructionGapV1
    assert binding is None or isinstance(binding, dict)


def test_pure_name_unpack_still_has_pattern_and_binds(tmp_path: Path) -> None:
    """``root, leaf = split(key)`` remains a real lexical binding pattern."""
    sf = _open(
        tmp_path,
        "name_unpack.py",
        "def f(key):\n" "    root, leaf = split(key)\n" "    return root\n",
    )
    assignment = next(n for n in sf.nodes() if isinstance(n, Assign))
    assert len(assignment.require_target_patterns()) == 1
    # require still works for enrolled patterns
    pattern = sf.unit.require_target_pattern(assignment, assignment.targets[0])
    assert pattern is assignment.require_target_patterns()[0]
