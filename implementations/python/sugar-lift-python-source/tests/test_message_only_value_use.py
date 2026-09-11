"""Twins for the message-only reachability slice.

Soundness is one-sided: the classifier may only return True (defer) when the
value-use PROVABLY reaches nothing but a declared message attribute.  Every
decision/effect sink and every unmodelled construct must return False (abort).
"""

from __future__ import annotations

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.message_only_value_use import (
    frame_value_use_is_message_only,
)
from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_source_tree.nodes import Attribute, FunctionDef
from sugar_source_tree.tree import SourceFile


def _frame_and_use(src: str, use_attr: str):
    tree = SourceFile(
        (src, "slice.py", blake3_512_of(src.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    frame = next(n for n in tree.root.walk() if isinstance(n, FunctionDef))
    attr = next(
        n
        for n in tree.root.walk()
        if isinstance(n, Attribute) and n.attr == use_attr
    )
    span = attr.line_col_span()
    return frame, (span.start_line, span.start_col, span.end_line, span.end_col)


def _is_message_only(src: str, use_attr: str) -> bool:
    frame, use = _frame_and_use(src, use_attr)
    return frame_value_use_is_message_only(frame, use)


# --- TRUE (deferrable): value reaches only a declared message attribute --------
def test_local_then_message_attribute_is_message_only() -> None:
    src = (
        "def _check_match(self, cfg, exc):\n"
        "    verbose = cfg.get_verbosity(exc)\n"
        "    self._fail_reason = _diff_text(verbose, exc)\n"
    )
    assert _is_message_only(src, "get_verbosity") is True


def test_direct_message_attribute_assignment_is_message_only() -> None:
    src = (
        "def _check_match(self, cfg):\n"
        "    self._fail_reason = cfg.get_verbosity()\n"
    )
    assert _is_message_only(src, "get_verbosity") is True


# --- FALSE (must abort): every decision / effect / unmodelled sink -------------
def test_returned_value_is_not_message_only() -> None:
    src = "def matches(self, cfg):\n    return cfg.get_verbosity()\n"
    assert _is_message_only(src, "get_verbosity") is False


def test_value_in_if_test_is_not_message_only() -> None:
    src = (
        "def matches(self, cfg):\n"
        "    if cfg.get_verbosity():\n"
        "        self._fail_reason = 'x'\n"
        "    return False\n"
    )
    assert _is_message_only(src, "get_verbosity") is False


def test_raised_operand_is_not_message_only() -> None:
    src = "def __exit__(self, cfg):\n    raise cfg.Error()\n"
    assert _is_message_only(src, "Error") is False


def test_store_to_non_message_self_attr_is_not_message_only() -> None:
    src = (
        "def __exit__(self, cfg):\n"
        "    self.suppress = cfg.decide()\n"
        "    return self.suppress\n"
    )
    assert _is_message_only(src, "decide") is False


def test_tainted_local_flows_to_return_is_not_message_only() -> None:
    src = (
        "def matches(self, cfg):\n"
        "    v = cfg.get_verbosity()\n"
        "    self._fail_reason = str(v)\n"
        "    return v\n"
    )
    assert _is_message_only(src, "get_verbosity") is False


def test_bare_expression_call_is_not_message_only() -> None:
    src = "def __exit__(self, cfg):\n    cfg.side_effect()\n"
    assert _is_message_only(src, "side_effect") is False


def test_unmodelled_with_statement_mentioning_taint_aborts() -> None:
    src = (
        "def __exit__(self, cfg):\n"
        "    v = cfg.get_verbosity()\n"
        "    with open('x') as f:\n"
        "        f.write(v)\n"
    )
    assert _is_message_only(src, "get_verbosity") is False


def test_unmodelled_for_loop_mentioning_taint_aborts() -> None:
    src = (
        "def __exit__(self, cfg):\n"
        "    v = cfg.get_verbosity()\n"
        "    for i in v:\n"
        "        self._fail_reason = i\n"
    )
    assert _is_message_only(src, "get_verbosity") is False


def test_augassign_of_taint_aborts() -> None:
    src = (
        "def __exit__(self, cfg):\n"
        "    self._fail_reason = ''\n"
        "    self._fail_reason += cfg.get_verbosity()\n"
    )
    # AugAssign is unmodelled and mentions the taint -> abort.
    assert _is_message_only(src, "get_verbosity") is False


# --- the seater may pass a COARSER frame than the enclosing function ----------
def test_coarser_class_or_module_frame_descends_to_the_function() -> None:
    from sugar_source_tree.nodes import Attribute, ClassDef
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.tree import SourceFile

    src = (
        "class RaisesExc:\n"
        "    def _check_match(self, cfg):\n"
        "        if isinstance(self.rawmatch, str):\n"
        "            verbose = (cfg.get_verbosity(0) if cfg is not None else 0)\n"
        "            self._fail_reason = str(verbose)\n"
        "            return False\n"
        "        return True\n"
    )
    tree = SourceFile(
        (src, "cls.py", blake3_512_of(src.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    attr = next(
        n for n in tree.root.walk() if isinstance(n, Attribute) and n.attr == "get_verbosity"
    )
    sp = attr.line_col_span()
    use = (sp.start_line, sp.start_col, sp.end_line, sp.end_col)
    cls = next(n for n in tree.root.walk() if isinstance(n, ClassDef))
    # Coarser frames (ClassDef, Module) must descend to _check_match's body.
    assert frame_value_use_is_message_only(cls, use) is True
    assert frame_value_use_is_message_only(tree.root, use) is True


def test_module_level_use_outside_any_function_is_not_message_only() -> None:
    from sugar_source_tree.nodes import Attribute
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.tree import SourceFile

    src = "x = cfg.get_verbosity()\n"
    tree = SourceFile(
        (src, "mod.py", blake3_512_of(src.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    attr = next(
        n for n in tree.root.walk() if isinstance(n, Attribute) and n.attr == "get_verbosity"
    )
    sp = attr.line_col_span()
    use = (sp.start_line, sp.start_col, sp.end_line, sp.end_col)
    # Not inside any function -> not a manager-frame value -> refuse.
    assert frame_value_use_is_message_only(tree.root, use) is False
