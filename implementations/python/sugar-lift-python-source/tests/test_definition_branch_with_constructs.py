"""A definition's branch-suite ``with`` is built with the definition (#7699, #7757).

The board accounts a file through ``roll_call.discharge``, which constructs
every definition (``node.sugar()``, step 5) and reduces none.  An ``if``
builds both of its suites, every statement of them, when it is constructed:
a ``with`` in a suite is built, its manager what its head reduces to.
Nothing waits on a reduction to build it, so the board counts the tree built
or refused by name (``pandas/plotting/_matplotlib/__init__.py:67`` once ended
``completed`` with its ``with`` unconstructed).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithReducedManagerSugar
from sugar_source_tree.nodes import With
from sugar_source_tree.roll_call import discharge

import test_contextlib_suppress_source_exit_faces as opener
from test_contextlib_suppress_source_exit_faces import _corpus


_LOCAL_MANAGER = (
    "from contextlib import contextmanager\n"
    "@contextmanager\n"
    "def cm():\n"
    "    yield 1\n"
)


def _guarded(manager_head: str) -> str:
    return (
        f"{_LOCAL_MANAGER}"
        "def f(c):\n"
        "    if c:\n"
        f"        with {manager_head}:\n"
        "            pass\n"
        "    return 7\n"
    )


def _open(tmp_path: Path, source: str):
    return opener._open(_corpus(tmp_path, source))


def test_a_reachable_branch_with_is_constructed_by_the_discharge(tmp_path):
    source_file = _open(tmp_path, _guarded("cm()"))
    report = discharge(source_file)
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    line = with_node.line_col_span().start_line
    assert [e for e in report.present if e.kind == "With" and e.start_line == line]
    assert type(with_node.sugar()) is GeneratorWithSugar


def test_a_branch_with_over_an_unread_manager_is_constructed(tmp_path):
    # The lying twin of a refusal: before #7699 the ``with`` under the
    # undecided ``if c:`` was never constructed.  Building the definition
    # builds the ``with``; its manager is what the head reduces to (#7757),
    # here a manager nothing decides.
    source_file = _open(tmp_path, _guarded("unknown_manager()"))
    report = discharge(source_file)
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    line = with_node.line_col_span().start_line
    assert [e for e in report.present if e.kind == "With" and e.start_line == line]
    assert type(with_node.sugar()) is WithReducedManagerSugar


def _errstate_signature():
    """``np.errstate.__init__``'s signature exactly as the census derives it.

    ``(self, *, call=_Unspecified, all=None, divide=None, over=None,
    under=None, invalid=None)``: one constructed default (a module sentinel)
    and five literal ``None`` defaults, each a JSON term carrying a list.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        CallParameterV1,
        ConstructedDefaultV1,
        ImportSignatureV2,
        KeywordOnlyV1,
        LiteralDefaultV1,
    )
    from sugar_lift_py_tests.ir import PrimitiveSort

    none = {"kind": "ctor", "name": "None", "args": []}
    return ImportSignatureV2(
        (
            CallParameterV1(
                "call",
                PrimitiveSort("Value"),
                KeywordOnlyV1(),
                False,
                ConstructedDefaultV1({"kind": "var", "name": "_Unspecified"}),
            ),
            *(
                CallParameterV1(
                    name,
                    PrimitiveSort("Value"),
                    KeywordOnlyV1(),
                    False,
                    LiteralDefaultV1(dict(none, args=[])),
                )
                for name in ("all", "divide", "over", "under", "invalid")
            ),
        )
    )


def test_a_signature_with_sealed_defaults_canonicalizes():
    # #7730: ``np.errstate.__init__``'s signature.  Each default is a sealed,
    # CID-owning term, so the signature canonicalizes, and a different default
    # is a different value.
    from dataclasses import replace

    from sugar_lift_py_tests.context_manager_contract import (
        ImportSignatureV2,
        LiteralDefaultV1,
    )
    from sugar_lift_py_tests.ir import PrimitiveSort
    from sugar_source_tree.binding_state import constructed_value_cid_v2

    signature = _errstate_signature()
    assert isinstance(constructed_value_cid_v2(signature), str)
    other_parameters = list(signature.parameters)
    other_parameters[1] = replace(
        other_parameters[1],
        sort=PrimitiveSort("Int"),
        default=LiteralDefaultV1(
            {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
        ),
    )
    assert constructed_value_cid_v2(
        ImportSignatureV2(tuple(other_parameters))
    ) != constructed_value_cid_v2(signature)


def test_a_raw_json_term_still_has_no_category(tmp_path):
    # The lying twin: the category is the sealed default, not JSON lists.  A
    # term carried raw (never sealed by its CID) is still refused, by name.
    from dataclasses import dataclass

    from sugar_source_tree.binding_state import (
        ConstructedValueCategoryGap,
        constructed_value_cid_v2,
    )

    @dataclass(frozen=True)
    class RawTermDefault:
        value: dict

    raw = RawTermDefault({"kind": "ctor", "name": "None", "args": []})
    with pytest.raises(ConstructedValueCategoryGap, match="builtins.list is a MUTABLE"):
        constructed_value_cid_v2(raw)


def test_a_default_term_changed_after_sealing_is_refused():
    # The seal is checked, not trusted: a term edited after its default was
    # minted no longer reproduces the CID, so it is walked -- and its list is
    # refused by name instead of being re-authenticated as a new moment.
    from sugar_lift_py_tests.context_manager_contract import ConstructedDefaultV1
    from sugar_source_tree.binding_state import (
        ConstructedValueCategoryGap,
        constructed_value_cid_v2,
    )

    default = ConstructedDefaultV1(
        {"kind": "ctor", "name": "sealed_then_edited_7730", "args": []}
    )
    default.value["args"].append({"kind": "var", "name": "late"})
    with pytest.raises(ConstructedValueCategoryGap, match="builtins.list is a MUTABLE"):
        constructed_value_cid_v2(default)
