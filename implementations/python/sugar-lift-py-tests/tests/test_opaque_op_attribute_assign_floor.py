"""OpaqueOpCallsite.attribute_assign_with — construction gap drain (Part of #3809).

Lift-probe (before):

    s = pd.Series([1, 2, 3]).copy()
    s.name = \"x\"

Refuse: FactoryGap · AttributeAssignSugar · observed=OpaqueOpCallsite
· requested=attribute_assign_with.

Mechanism: mutation of opaque vendor identity — not a missing coordinate mint.
SymbolicValue already returns RuntimeEffect for attribute assign. Opaque must
match: typed red, never fabricate a mutated call:copy(...).

After: statement reduces to RuntimeEffect (no FactoryGap construction panic).
"""

from __future__ import annotations

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


def test_opaque_copy_name_assign_is_runtime_effect_not_construction_gap() -> None:
    src = (
        "import pandas as pd\n"
        "def t():\n"
        "    s = pd.Series([1, 2, 3]).copy()\n"
        "    s.name = \"x\"\n"
        "    assert s.name == \"x\"\n"
    )
    # Must not factory_panic(project/attribute_assign construction).
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    blob = repr(report.payload)
    assert "requested=attribute_assign_with" not in blob
    # Runtime effect may leave no euf assertion or a dig boundary — either is
    # honest; construction floor-gap spelling must not reappear.
    assert "add attribute_assign_with to OpaqueOpCallsite" not in blob


def test_opaque_cumsum_name_assign_no_construction_gap() -> None:
    src = (
        "import pandas as pd\n"
        "def t():\n"
        "    s = pd.Series([1.0, 2.0]).cumsum()\n"
        "    s.name = \"c\"\n"
        "    assert True\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert "requested=attribute_assign_with" not in repr(report.payload)
