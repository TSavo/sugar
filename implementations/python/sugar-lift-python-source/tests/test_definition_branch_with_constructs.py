"""A definition's branch-suite ``with`` constructs when the definition is accounted (#7699).

#7697 carries a ``with`` of an ``if`` suite as ``BranchSuiteWithV1``, built when
its suite is reduced.  The census accounts a file through
``roll_call.discharge``, which constructs every definition and reduces none,
so no suite was ever selected and the ``with`` was never demanded: a file
ended ``completed`` with its ``with`` unconstructed
(``pandas/plotting/_matplotlib/__init__.py:67``).  An undecided guard leaves
its suite reachable, so the discharge constructs the ``with`` with its
definition: built when its manager has a contract, refused by the same named
``With`` refusal when it has none.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_source_tree.nodes import FunctionDef, With
from sugar_source_tree.panic import SourceTreePanic
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
    assert type(with_node.sugar()) is WithSourceResourceSugar


def _with_refusals(source_file):
    return [
        str(panic)
        for node, panic in source_file.reporter.gaps
        if isinstance(node, With)
    ]


def test_a_reachable_branch_with_without_a_contract_is_refused(tmp_path):
    # The lying twin: before #7699 this discharge answered clean while the
    # ``with`` under the undecided ``if c:`` was never constructed.
    source_file = _open(tmp_path, _guarded("unknown_manager()"))
    f = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    f.sugar()  # constructing the definition alone defers the with ...
    assert _with_refusals(source_file) == []
    report = discharge(source_file)  # ... accounting it refuses it, by name
    (refusal,) = _with_refusals(source_file)
    assert "CONTEXT MANAGER RESOLUTION GAP" in refusal
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    line = with_node.line_col_span().start_line
    assert not [e for e in report.present if e.kind == "With" and e.start_line == line]
    with pytest.raises(SourceTreePanic, match="CONTEXT MANAGER RESOLUTION GAP"):
        with_node.sugar()


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


def _discharged_branch_with(tmp_path):
    source_file = _open(tmp_path, _guarded("cm()"))
    report = discharge(source_file)
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    line = with_node.line_col_span().start_line
    assert [e for e in report.present if e.kind == "With" and e.start_line == line]
    value = with_node.sugar()
    assert type(value) is WithSourceResourceSugar
    return value


def test_a_branch_with_over_a_defaulted_signature_canonicalizes(tmp_path):
    # #7730: ``pandas/core/series.py:3345`` -- ``with np.errstate(all=
    # "ignore"):`` under ``if isinstance(other, Series):``.  The discharge
    # builds the branch ``with`` and the census reporter content-addresses
    # the presented value, whose summary carries the manager's signature.
    # Each default is a sealed, CID-owning term, so the value canonicalizes.
    from dataclasses import replace

    from sugar_lift_py_tests.context_manager_contract import (
        ImportSignatureV2,
        LiteralDefaultV1,
    )
    from sugar_lift_py_tests.ir import PrimitiveSort
    from sugar_source_tree.binding_state import constructed_value_cid_v2

    value = _discharged_branch_with(tmp_path)
    errstate_shaped = replace(
        value,
        summary=replace(value.summary, import_signature=_errstate_signature()),
    )
    assert isinstance(constructed_value_cid_v2(errstate_shaped), str)
    # The defaults are content: a different default is a different value.
    other = _errstate_signature()
    other_parameters = list(other.parameters)
    other_parameters[1] = replace(
        other_parameters[1],
        sort=PrimitiveSort("Int"),
        default=LiteralDefaultV1(
            {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
        ),
    )
    differently_defaulted = replace(
        value,
        summary=replace(
            value.summary, import_signature=ImportSignatureV2(tuple(other_parameters))
        ),
    )
    assert constructed_value_cid_v2(differently_defaulted) != constructed_value_cid_v2(
        errstate_shaped
    )


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
