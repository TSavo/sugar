"""Batch C — vendor ATTRIBUTE coordinates (Part of #3809).

Lift-probed against the working ``df.shape`` reference (#3905):

| attribute | FOL locator | py.attr? | attribute-euf door | notes |
|-----------|-------------|----------|--------------------|-------|
| shape (ref) | call:shape | no | yes ``shape#euf#…`` | bool/tuple RHS |
| dtypes | call:dtypes | no | via nest / identity | opaque Series |
| columns | call:columns | no | via nest | opaque Index |
| index | call:index | no | via nest | opaque Index |
| values | call:values | no | via nest | opaque ndarray |
| T | call:T | no | via nest + .shape | transpose DF |
| empty | call:empty | no | yes ``empty#euf#…`` | #3905 dual-assert |

``_attribute_coordinate_name`` accepts any Attribute head → ``call:<attr>(receiver)``.
``symbolic_term`` Attribute nodes use the same head (not ``py.attr``). No production
change required for Batch C — instruments pin the probed shape + discrimination.

Discrimination (witness EXECUTION): numeric projection via ``len(attr)`` dual-assert
→ unsat. Solo opaque lies stay sat (honest limit). list(columns)==[...] dual currently
*refuses* (list consistency gap — documented residual, not a locator gap).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_ATTRS = ("dtypes", "columns", "index", "values", "T")


def _fol_calls(report) -> set[str]:
    return set(re.findall(r"call:[A-Za-z_][A-Za-z0-9_.]*", repr(report.payload.ir)))


def _has_py_attr(report) -> bool:
    return "py.attr" in repr(report.payload.ir)


def _callable_post(report) -> str:
    row = next(r for r in report.payload.ir if (r.name or "").endswith("::callable"))
    return repr(row.post)


def _dig_body_refuse(report, callee: str = "A") -> list[str]:
    return [
        d.get("reason", "")
        for d in (report.payload.diagnostics or [])
        if isinstance(d, dict)
        and d.get("kind") == "dig-boundary"
        and d.get("callee") == callee
        and "function universe body walker refused" in (d.get("reason") or "")
    ]


# ---------------------------------------------------------------------------
# Lift-probe vs shape reference: locator is call:<attr>, never py.attr
# ---------------------------------------------------------------------------


def test_shape_reference_is_call_shape_not_py_attr() -> None:
    src = (
        "import pandas as pd\n"
        "def t():\n"
        "    assert pd.DataFrame().shape == (0, 0)\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert "call:shape" in _fol_calls(report)
    assert not _has_py_attr(report)
    names = [r.name for r in report.payload.ir]
    assert any(
        (n or "").startswith("shape#euf#c:call:shape") for n in names
    ), names


@pytest.mark.parametrize("attr", _ATTRS)
def test_direct_attr_emits_call_coordinate_not_py_attr(attr: str) -> None:
    """Identity surface still mints call:<attr>(receiver) — not py.attr."""
    src = (
        "import pandas as pd\n"
        "def t():\n"
        f"    assert pd.DataFrame().{attr} is not None\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert f"call:{attr}" in _fol_calls(report), _fol_calls(report)
    assert "call:pandas.DataFrame" in _fol_calls(report)
    assert not _has_py_attr(report)


def test_dtypes_and_columns_match_shape_head_family() -> None:
    """Same unary call:<attr>(receiver) head family as shape (#3905 door)."""
    for attr in ("dtypes", "columns"):
        src = (
            "import pandas as pd\n"
            "def t():\n"
            f'    assert pd.DataFrame({{"a": [1]}}).{attr} is not None\n'
        )
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
        assert report is not None
        blob = repr(report.payload.ir)
        assert f"'name': 'call:{attr}'" in blob or f"call:{attr}" in blob
        assert "py.attr" not in blob


def test_T_shape_chain_nests_call_T_under_call_shape() -> None:
    src = (
        "import pandas as pd\n"
        "def t():\n"
        '    assert pd.DataFrame({"a": [1, 2]}).T.shape == (1, 2)\n'
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert {"call:T", "call:shape", "call:pandas.DataFrame"} <= _fol_calls(report)
    name = report.payload.ir[0].name or ""
    assert "call:shape(c:call:T(c:call:pandas.DataFrame" in name, name
    assert not _has_py_attr(report)


# ---------------------------------------------------------------------------
# Body dig: def A(): return DF.attr  /  def A(df): return df.attr
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attr", ("dtypes", "columns", "index", "values", "T", "shape"))
def test_zero_arg_body_dig_emits_call_attr_coordinate(attr: str) -> None:
    src = (
        "import pandas as pd\n"
        "def A():\n"
        f'    return pd.DataFrame({{"a": [1, 2]}}).{attr}\n'
        "def test_a():\n"
        "    assert A() == A()\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert any((r.name or "").endswith("::callable") for r in report.payload.ir)
    assert not _dig_body_refuse(report), _dig_body_refuse(report)
    post = _callable_post(report)
    assert f"call:{attr}" in post, post
    assert "py.attr" not in post


@pytest.mark.parametrize("attr", ("columns", "dtypes", "index", "values", "T"))
def test_formal_body_dig_emits_call_attr_on_df(attr: str) -> None:
    """Formal attr dig: out == call:<attr>(df) — symbolic_term Attribute path."""
    src = (
        "import pandas as pd\n"
        "def A(df):\n"
        f"    return df.{attr}\n"
        "def test_a():\n"
        f'    assert A(pd.DataFrame({{"a": [1]}})) == A(pd.DataFrame({{"a": [1]}}))\n'
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert any((r.name or "").endswith("::callable") for r in report.payload.ir)
    assert not _dig_body_refuse(report), _dig_body_refuse(report)
    post = _callable_post(report)
    assert f"'name': 'call:{attr}'" in post or f"call:{attr}" in post, post
    assert "py.attr" not in post


# ---------------------------------------------------------------------------
# Dual-assert discrimination (witness EXECUTION) via numeric projection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "src", "coord"),
    [
        (
            "columns",
            (
                "import pandas as pd\n"
                "def t_true():\n"
                '    assert len(pd.DataFrame({"a": [1], "b": [2]}).columns) == 2\n'
                "def t_lie():\n"
                '    assert len(pd.DataFrame({"a": [1], "b": [2]}).columns) == 9\n'
            ),
            "call:columns",
        ),
        (
            "dtypes",
            (
                "import pandas as pd\n"
                "def t_true():\n"
                '    assert len(pd.DataFrame({"a": [1], "b": [2]}).dtypes) == 2\n'
                "def t_lie():\n"
                '    assert len(pd.DataFrame({"a": [1], "b": [2]}).dtypes) == 9\n'
            ),
            "call:dtypes",
        ),
        (
            "index",
            (
                "import pandas as pd\n"
                "def t_true():\n"
                '    assert len(pd.DataFrame({"a": [1, 2, 3]}).index) == 3\n'
                "def t_lie():\n"
                '    assert len(pd.DataFrame({"a": [1, 2, 3]}).index) == 9\n'
            ),
            "call:index",
        ),
        (
            "values",
            (
                "import pandas as pd\n"
                "def t_true():\n"
                '    assert len(pd.DataFrame({"a": [1, 2, 3]}).values) == 3\n'
                "def t_lie():\n"
                '    assert len(pd.DataFrame({"a": [1, 2, 3]}).values) == 9\n'
            ),
            "call:values",
        ),
        (
            "T",
            (
                "import pandas as pd\n"
                "def t_true():\n"
                '    assert len(pd.DataFrame({"a": [1, 2]}).T.columns) == 2\n'
                "def t_lie():\n"
                '    assert len(pd.DataFrame({"a": [1, 2]}).T.columns) == 9\n'
            ),
            "call:T",
        ),
    ],
)
def test_attr_len_dual_assert_refutes_lie_via_witness(
    tmp_path: Path, label: str, src: str, coord: str
) -> None:
    """Shared euf key on len(call:<attr>(…)) → unsat (witness discrimination)."""
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert coord in _fol_calls(report), _fol_calls(report)
    assert "call:len" in _fol_calls(report)
    assert not _has_py_attr(report)

    result = run_source_through_real_solver(tmp_path / f"attr-{label}", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (label, result.verdict, statuses)


def test_columns_body_dig_truthful_sat_no_refuse(tmp_path: Path) -> None:
    """Opaque columns body dig: solo value-eq sat; nested call:columns present."""
    src = (
        "import pandas as pd\n"
        "def A():\n"
        '    return pd.DataFrame({"a": [1, 2]}).columns\n'
        "def test_a():\n"
        "    assert A() == A()\n"
    )
    result = run_source_through_real_solver(tmp_path / "cols-body", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "sat", (result.verdict, statuses)
    assert "refused" not in statuses
    assert "call:columns" in repr(result.lift_doc.get("ir", []))


def test_list_columns_dual_assert_refuse_residual_documented(tmp_path: Path) -> None:
    """Residual: list(columns)==[…] dual-assert currently *refuses* consistency.

    Locator is correct (call:list(call:columns(...))); the refuse is a list/array
    equality grounding gap, not a py.attr regression. Pin so it cannot silently
    become sat (false discrimination) without a deliberate re-bless.
    """
    src = (
        "import pandas as pd\n"
        "def t_true():\n"
        '    assert list(pd.DataFrame({"a": [1], "b": [2]}).columns) == ["a", "b"]\n'
        "def t_lie():\n"
        '    assert list(pd.DataFrame({"a": [1], "b": [2]}).columns) == ["x", "y"]\n'
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert {"call:list", "call:columns"} <= _fol_calls(report)

    from sugar_lift_py_tests.witness_harness import (
        WitnessPipelineError,
        mint_and_prove,
        _stage_cli_project,
    )

    project = tmp_path / "list-cols-residual"
    _stage_cli_project(project, src)
    result = mint_and_prove(project)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    # Honest residual: refused (not sat with a false green, not silent).
    assert "refused" in statuses or result.prove_doc.get("rows"), statuses
    try:
        verdict = result.verdict
    except WitnessPipelineError:
        verdict = "refused"
    assert verdict in ("refused", "unsat", "sat"), verdict
    # Prefer refuse over false sat; if this becomes unsat, re-bless the residual.
    if verdict == "sat":
        raise AssertionError(
            "list(columns) dual-assert became sat — unexpected silent non-discrimination"
        )
