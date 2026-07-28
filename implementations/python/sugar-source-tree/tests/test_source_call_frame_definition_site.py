from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
from sugar_source_tree.tree import SourceFile


def test_source_call_frame_rejects_same_source_foreign_definition_site(tmp_path) -> None:
    path = tmp_path / "two_frames.py"
    path.write_text(
        "def left(value):\n"
        "    return value\n"
        "\n"
        "def right(value):\n"
        "    return value\n",
        encoding="utf-8",
    )
    functions = {function.name: function for function in SourceFile.from_path(path).functions()}
    left = functions["left"].source_visible_call_frame()
    right = functions["right"].source_visible_call_frame()
    actual = TermValue(7)

    truthful = left.bind_actuals((actual,), ())
    assert truthful.actuals == (actual,)

    wrong_site = replace(left, definition_site=right.definition_site)
    with pytest.raises(SourceCallBindingGap, match="definition site"):
        wrong_site.bind_actuals((actual,), ())
