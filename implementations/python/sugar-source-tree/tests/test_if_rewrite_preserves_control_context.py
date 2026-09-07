"""If's branch-result rewrite must preserve control_context (loop + except).

A bare ``raise`` re-raises the in-flight exception; construction requires an
enclosing except handler's effect slot (ControlConstructionContextV1). ``If``
rewrites itself to carry its branch-result slot, and _rewrite_with_slot
materialized the rewritten node WITHOUT control_context (unlike ``rewrite``),
so a slot-rewritten ``if`` inside an ``except`` lost the exception slot and a
bare ``raise`` in one of its branches refused -- the exact shape of
contextlib._GeneratorContextManager.__exit__ (``if exc is not value: raise``),
which blocked every @contextmanager generator manager (option_context et al.).
"""

from __future__ import annotations

import json
from pathlib import Path

from sugar_lift_py_tests.corpus_pin import pin_corpus
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.sugar.function_universe_sugar import FunctionUniverseSugar
from sugar_source_tree.reporter import CollectingReporter


def _fn(tmp_path: Path, body: str, name: str = "f"):
    root = tmp_path / "c"
    root.mkdir()
    (root / "m.py").write_text(body, encoding="utf-8")
    (tmp_path / "c.identity.json").write_text(
        json.dumps({"distribution": "tiny-corpus", "version": "0.0.1"}), encoding="utf-8"
    )
    pin_corpus(root, distribution="tiny-corpus", version="0.0.1")
    source_file = open_source_file_for_construction(
        root / "m.py", root=root, reporter=CollectingReporter(),
        distribution="tiny-corpus", source_workspace_root=root,
    )
    return next(n for n in source_file.functions() if n.name == name)


def test_bare_raise_in_if_in_except_constructs(tmp_path) -> None:
    """Truthful: the contextlib __exit__ shape constructs; the slot survives."""
    fn = _fn(
        tmp_path,
        "def f(x, value):\n"
        "    try:\n"
        "        return x.do()\n"
        "    except BaseException as exc:\n"
        "        if exc is not value:\n"
        "            raise\n"
        "        return False\n",
    )
    assert isinstance(fn.sugar(), FunctionUniverseSugar)


def test_bare_raise_outside_any_except_still_refuses(tmp_path) -> None:
    """Lying twin: a bare raise with no enclosing except is still loud -- the
    fix preserves the slot, it does not fabricate one."""
    import pytest
    from sugar_source_tree.panic import SugarNotWritten

    fn = _fn(
        tmp_path,
        "def f(cond):\n"
        "    if cond:\n"
        "        raise\n"
        "    return 1\n",
    )
    with pytest.raises(SugarNotWritten, match="in-flight exception slot"):
        fn.sugar()
