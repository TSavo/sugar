"""Production enumeration discriminates source-proven class managers."""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.tree_enumerate import audit_file_gaps
from sugar_source_tree.panic import RuntimeSelectedContextManager


def _write_module(root: Path, name: str, body: str) -> Path:
    path = root / f"{name}.py"
    path.write_text(body, encoding="utf-8")
    return path


def _with_gaps(path: Path):
    _sf, gaps = audit_file_gaps(path)
    return [(node, panic) for node, panic in gaps if node.kind == "With"]


@pytest.mark.parametrize(
    "exit_body",
    (
        "return None",
        "return False",
        "return",
        "pass",
    ),
)
def test_truthful_class_exit_variants_leave_no_with_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_body: str
):
    _write_module(
        tmp_path,
        "truthful_manager",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback):\n"
        f"        {exit_body}\n",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "from truthful_manager import Manager\n"
        "def f():\n"
        "    with Manager():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    assert _with_gaps(subject) == []


@pytest.mark.parametrize(
    ("module_body", "manager_expr"),
    (
        (
            "class Manager:\n"
            "    def __enter__(self): return self\n"
            "    def __exit__(self, typ, value, traceback): return True\n",
            "Manager()",
        ),
        (
            "class Manager:\n"
            "    def __enter__(self): return self\n"
            "    def __exit__(self, typ, value, traceback):\n"
            "        if typ is None: return False\n"
            "        return self.decide(typ)\n",
            "Manager()",
        ),
        (
            "from contextlib import contextmanager\n"
            "@contextmanager\n"
            "def Manager():\n"
            "    try: yield object()\n"
            "    except ValueError: pass\n",
            "Manager()",
        ),
    ),
    ids=("return-true", "mixed-symbolic", "generator-contextmanager"),
)
def test_lying_manager_twins_stay_runtime_selected_in_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module_body: str,
    manager_expr: str,
):
    _write_module(tmp_path, "lying_manager", module_body)
    subject = _write_module(
        tmp_path,
        "subject",
        "from lying_manager import Manager\n"
        "def f():\n"
        f"    with {manager_expr}:\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


def test_inherited_and_overridden_exit_use_exact_defining_coordinate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "inherited_manager",
        "class Base:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return False\n"
        "class Good(Base):\n"
        "    pass\n"
        "class Bad(Base):\n"
        "    def __exit__(self, typ, value, traceback): return True\n",
    )
    good = _write_module(
        tmp_path,
        "good_subject",
        "from inherited_manager import Good\n"
        "def f():\n"
        "    with Good():\n"
        "        raise ValueError\n",
    )
    bad = _write_module(
        tmp_path,
        "bad_subject",
        "from inherited_manager import Bad\n"
        "def f():\n"
        "    with Bad():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    assert _with_gaps(good) == []
    bad_gaps = _with_gaps(bad)
    assert len(bad_gaps) == 1
    assert type(bad_gaps[0][1]) is RuntimeSelectedContextManager


def test_same_spelling_from_distinct_source_cids_cannot_borrow_disposition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "truthful",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return None\n",
    )
    _write_module(
        tmp_path,
        "suppressing",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return True\n",
    )
    good = _write_module(
        tmp_path,
        "good_subject",
        "from truthful import Manager\n"
        "def f():\n"
        "    with Manager():\n"
        "        raise ValueError\n",
    )
    bad = _write_module(
        tmp_path,
        "bad_subject",
        "from suppressing import Manager\n"
        "def f():\n"
        "    with Manager():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    assert _with_gaps(good) == []
    bad_gaps = _with_gaps(bad)
    assert len(bad_gaps) == 1
    assert type(bad_gaps[0][1]) is RuntimeSelectedContextManager


@pytest.mark.parametrize(
    "rebind",
    (
        "from suppressing import Base\n",
        "if condition:\n"
        "    from suppressing import Base\n",
        "for Base in managers:\n"
        "    pass\n",
    ),
    ids=("direct-import", "conditional-import", "loop-target"),
)
def test_rebound_base_name_is_ambiguous_and_stays_runtime_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rebind: str
):
    _write_module(
        tmp_path,
        "suppressing",
        "class Base:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return True\n",
    )
    _write_module(
        tmp_path,
        "manager",
        "class Base:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return False\n"
        f"{rebind}"
        "class Derived(Base):\n"
        "    pass\n",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "from manager import Derived\n"
        "def f():\n"
        "    with Derived():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


@pytest.mark.parametrize(
    "manager_body",
    (
        "import suppressing\n"
        "class Derived(suppressing.Base):\n"
        "    pass\n",
        "class Generic:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return False\n"
        "class T: pass\n"
        "class Derived(Generic[T]):\n"
        "    pass\n",
        "class Left:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return False\n"
        "class Right:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return False\n"
        "class Derived(Left, Right):\n"
        "    pass\n",
    ),
    ids=("attribute-base", "subscript-base", "multiple-bases"),
)
def test_computed_or_multiple_bases_stay_runtime_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manager_body: str,
):
    _write_module(
        tmp_path,
        "suppressing",
        "class Base:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return True\n",
    )
    _write_module(tmp_path, "manager", manager_body)
    subject = _write_module(
        tmp_path,
        "subject",
        "from manager import Derived\n"
        "def f():\n"
        "    with Derived():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager
