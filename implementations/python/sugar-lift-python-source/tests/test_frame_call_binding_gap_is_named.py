"""A frame body whose call cannot bind its actuals is a named refusal (#7665).

Projecting ``get_handle``'s callees reached ``_get_filepath_or_buffer``, whose
``return IOArgs(filepath_or_buffer=..., ...)`` binds keyword actuals to a
dataclass's class frame.  The ``SourceCallBindingGap`` escaped the frame
projection and failed the whole file's enumeration.  It is the same
``call-binding`` refusal the runtime-entry binding already gives.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_source_tree.panic import SourceTreePanic

from test_contextmanager_generator_protocol import _function_rows, _imported

_IMPL = (
    "class Args:\n"
    "    pass\n"
    "def helper(flag):\n"
    "    if flag:\n"
    "        return Args(a=1)\n"
    "    return None\n"
    "class M:\n"
    "    def __enter__(self):\n"
    "        return 1\n"
    "    def __exit__(self, *exc):\n"
    "        return False\n"
    "def cm():\n"
    "    helper(True)\n"
    "    return M()\n"
)


def test_unbindable_call_in_a_frame_is_a_call_binding_refusal(tmp_path: Path) -> None:
    with pytest.raises(SourceTreePanic, match="call-binding"):
        tree, with_node = _imported(tmp_path, _IMPL, "pass", contextlib_enrolled=False)
        _function_rows(tree, with_node)


def test_the_frame_resolver_reads_the_module_binding_gap_class() -> None:
    # A function-local import of SourceCallBindingGap made the name local to
    # the whole resolver, so the imported-callee ``except`` above it raised
    # UnboundLocalError and failed pinned pandas io/html.py,
    # tests/io/json/test_compression.py and tests/io/sas/test_xport.py.
    from sugar_lift_python_source import manager_construction

    code = manager_construction._resolve_source_visible_frame_uncached.__code__
    assert "SourceCallBindingGap" not in code.co_varnames
