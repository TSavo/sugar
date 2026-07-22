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


def test_definition_default_rebinding_base_stays_runtime_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
        "from suppressing import Base as SuppressingBase\n"
        "class Base:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return False\n"
        "def marker(value=(Base := SuppressingBase)):\n"
        "    pass\n"
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


def test_conditional_duplicate_target_class_stays_runtime_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "manager",
        "if condition:\n"
        "    class Manager:\n"
        "        def __enter__(self): return self\n"
        "        def __exit__(self, typ, value, traceback): return False\n"
        "else:\n"
        "    class Manager:\n"
        "        def __enter__(self): return self\n"
        "        def __exit__(self, typ, value, traceback): return True\n",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "from manager import Manager\n"
        "def f():\n"
        "    with Manager():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


def test_conditional_facade_reexports_stay_runtime_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "never_suppressing",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return False\n",
    )
    _write_module(
        tmp_path,
        "suppressing",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return True\n",
    )
    _write_module(
        tmp_path,
        "facade",
        "if FLAG:\n"
        "    from never_suppressing import Manager\n"
        "else:\n"
        "    from suppressing import Manager\n",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "from facade import Manager\n"
        "def f():\n"
        "    with Manager():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


def test_subject_manager_head_rebinding_stays_runtime_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "never_suppressing",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return False\n",
    )
    _write_module(
        tmp_path,
        "suppressing",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return True\n",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "from never_suppressing import Manager\n"
        "from suppressing import Manager as SuppressingManager\n"
        "Manager = SuppressingManager\n"
        "def f():\n"
        "    with Manager():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


def test_unauthenticated_intermediate_package_attribute_stays_runtime_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "suppressing",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return True\n"
        "class Holder:\n"
        "    Manager = Manager\n",
    )
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from suppressing import Holder as sub\n", encoding="utf-8"
    )
    (package / "sub.py").write_text(
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return False\n",
        encoding="utf-8",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "import pkg\n"
        "def f():\n"
        "    with pkg.sub.Manager():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


def test_parameter_shadowed_manager_stays_runtime_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "never_suppressing",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return False\n",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "from never_suppressing import Manager\n"
        "def f(Manager):\n"
        "    with Manager():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


def test_captured_local_manager_stays_runtime_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "never_suppressing",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return False\n",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "from never_suppressing import Manager\n"
        "def outer(Manager):\n"
        "    def g():\n"
        "        nonlocal Manager\n"
        "        with Manager():\n"
        "            raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


def test_conditional_class_body_binding_stays_runtime_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "never_suppressing",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return False\n",
    )
    _write_module(
        tmp_path,
        "suppressing",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return True\n",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "from never_suppressing import Manager\n"
        "from suppressing import Manager as BadManager\n"
        "class C:\n"
        "    if FLAG:\n"
        "        Manager = BadManager\n"
        "    with Manager():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


def test_custom_prepare_class_body_manager_stays_runtime_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "never_suppressing",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return False\n",
    )
    _write_module(
        tmp_path,
        "suppressing",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return True\n",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "from never_suppressing import Manager\n"
        "from suppressing import Manager as BadManager\n"
        "class Meta(type):\n"
        "    @classmethod\n"
        "    def __prepare__(mcls, name, bases):\n"
        "        return {'Manager': BadManager}\n"
        "class C(metaclass=Meta):\n"
        "    with Manager():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


def test_method_manager_uses_unshadowed_module_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "never_suppressing",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return False\n",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "from never_suppressing import Manager\n"
        "class C:\n"
        "    def method(self):\n"
        "        with Manager():\n"
        "            raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    assert _with_gaps(subject) == []


@pytest.mark.parametrize(
    ("manager_body", "subject_tail"),
    (
        (
            "def transform(cls): return cls\n"
            "@transform\n"
            "class Manager:\n"
            "    def __enter__(self): return self\n"
            "    def __exit__(self, typ, value, traceback): return None\n",
            "",
        ),
        (
            "class Meta(type): pass\n"
            "class Manager(metaclass=Meta):\n"
            "    def __enter__(self): return self\n"
            "    def __exit__(self, typ, value, traceback): return None\n",
            "",
        ),
        (
            "def _suppress(self, typ, value, traceback): return True\n"
            "class Base:\n"
            "    def __init_subclass__(cls): cls.__exit__ = _suppress\n"
            "    def __enter__(self): return self\n"
            "    def __exit__(self, typ, value, traceback): return None\n"
            "class Manager(Base): pass\n",
            "",
        ),
        (
            "def transform(cls): return cls\n"
            "@transform\n"
            "class Base:\n"
            "    def __enter__(self): return self\n"
            "    def __exit__(self, typ, value, traceback): return None\n"
            "class Manager(Base): pass\n",
            "",
        ),
        (
            "class Base:\n"
            "    def __enter__(self): return self\n"
            "    def __exit__(self, typ, value, traceback): return None\n"
            "class Manager(Base[int]): pass\n",
            "",
        ),
        (
            "class Manager:\n"
            "    def __enter__(self): return self\n"
            "    def __exit__(self, typ, value, traceback): return None\n",
            "del Manager.__exit__\n",
        ),
        (
            "class Manager:\n"
            "    def __enter__(self): return self\n"
            "    def __exit__(self, typ, value, traceback): return None\n"
            "delattr(Manager, '__exit__')\n",
            "",
        ),
        (
            "class Manager:\n"
            "    def __enter__(self): return self\n"
            "    def __exit__(self, typ, value, traceback): return None\n"
            "Manager.__dict__['__exit__'] = lambda *args: True\n",
            "",
        ),
        (
            "class Manager:\n"
            "    def __enter__(self): return self\n"
            "    def __exit__(self, typ, value, traceback): return None\n",
            "def _suppress(self, typ, value, traceback): return True\n"
            "Manager.__exit__ = _suppress\n",
        ),
        (
            "def _suppress(self, typ, value, traceback): return True\n"
            "class Manager:\n"
            "    def __enter__(self): return self\n"
            "    def __exit__(self, typ, value, traceback): return None\n"
            "setattr(Manager, '__exit__', _suppress)\n",
            "",
        ),
    ),
    ids=(
        "decorator",
        "custom-metaclass",
        "base-init-subclass",
        "decorated-base",
        "generic-subscript-base",
        "subject-attribute-delete",
        "defining-module-delattr",
        "defining-module-dict-store",
        "subject-attribute-store",
        "defining-module-setattr",
    ),
)
def test_transformed_manager_classes_stay_runtime_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manager_body: str,
    subject_tail: str,
):
    _write_module(tmp_path, "manager", manager_body)
    subject = _write_module(
        tmp_path,
        "subject",
        "from manager import Manager\n"
        f"{subject_tail}"
        "def f():\n"
        "    with Manager():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


def test_plain_untransformed_manager_still_proves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "manager",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return None\n",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "from manager import Manager\n"
        "def f():\n"
        "    with Manager():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    assert _with_gaps(subject) == []


@pytest.mark.parametrize(
    "mutation",
    (
        "manager.Manager.__exit__ = lambda self, *args: True\n",
        "def _suppress(self, *args): return True\n"
        "setattr(manager.Manager, '__exit__', _suppress)\n",
    ),
    ids=("qualified-attribute-store", "qualified-setattr"),
)
def test_module_qualified_manager_mutation_stays_runtime_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
):
    _write_module(
        tmp_path,
        "manager",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return None\n",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "import manager\n"
        f"{mutation}"
        "def f():\n"
        "    with manager.Manager():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


def test_simple_alias_manager_mutation_stays_runtime_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "manager",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return None\n",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "from manager import Manager\n"
        "def _suppress(self, *args): return True\n"
        "Alias = Manager\n"
        "Alias.__exit__ = _suppress\n"
        "def f():\n"
        "    with Manager():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


def test_inherited_manager_bases_mutation_stays_runtime_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "manager",
        "class Base:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return None\n"
        "class Derived(Base): pass\n"
        "class Suppressing:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return True\n",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "from manager import Derived, Suppressing\n"
        "Derived.__bases__ = (Suppressing,)\n"
        "def f():\n"
        "    with Derived():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


def test_manager_class_passed_to_call_stays_runtime_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "manager",
        "class Manager:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return None\n",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "from manager import Manager\n"
        "def patch(cls): pass\n"
        "patch(Manager)\n"
        "def f():\n"
        "    with Manager():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


@pytest.mark.parametrize(
    "subject_body",
    (
        "from manager import Derived, Base\n"
        "def _suppress(self, *args): return True\n"
        "Base.__exit__ = _suppress\n"
        "def f():\n"
        "    with Derived():\n"
        "        raise ValueError\n",
        "import manager\n"
        "def _suppress(self, *args): return True\n"
        "manager.Base.__exit__ = _suppress\n"
        "def f():\n"
        "    with manager.Derived():\n"
        "        raise ValueError\n",
        "from manager import Derived, Base\n"
        "def patch(cls): pass\n"
        "patch(Base)\n"
        "def f():\n"
        "    with Derived():\n"
        "        raise ValueError\n",
    ),
    ids=("base-store", "qualified-base-store", "base-call-argument"),
)
def test_inherited_disposition_base_use_stays_runtime_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    subject_body: str,
):
    _write_module(
        tmp_path,
        "manager",
        "class Base:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return None\n"
        "class Derived(Base): pass\n",
    )
    subject = _write_module(tmp_path, "subject", subject_body)
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


def test_untouched_inherited_disposition_still_proves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "manager",
        "class Base:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return None\n"
        "class Derived(Base): pass\n",
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

    assert _with_gaps(subject) == []


@pytest.mark.parametrize(
    ("manager_body", "facade_body", "manager_name"),
    (
        (
            "class Base:\n"
            "    def __enter__(self): return self\n"
            "    def __exit__(self, typ, value, traceback): return None\n"
            "class Derived(Base): pass\n",
            "from manager import Derived\n"
            "from manager import Base as Other\n",
            "Derived",
        ),
        (
            "class Manager:\n"
            "    def __enter__(self): return self\n"
            "    def __exit__(self, typ, value, traceback): return None\n",
            "from manager import Manager\n"
            "from manager import Manager as Other\n",
            "Manager",
        ),
    ),
    ids=("inherited-sibling-export", "direct-sibling-export"),
)
def test_sibling_reexport_mutation_stays_runtime_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manager_body: str,
    facade_body: str,
    manager_name: str,
):
    _write_module(tmp_path, "manager", manager_body)
    _write_module(tmp_path, "facade", facade_body)
    subject = _write_module(
        tmp_path,
        "subject",
        "import facade\n"
        "def _suppress(self, *args): return True\n"
        "facade.Other.__exit__ = _suppress\n"
        "def f():\n"
        f"    with facade.{manager_name}():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    gaps = _with_gaps(subject)
    assert len(gaps) == 1
    assert type(gaps[0][1]) is RuntimeSelectedContextManager


def test_untouched_sibling_reexport_still_proves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_module(
        tmp_path,
        "manager",
        "class Base:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, typ, value, traceback): return None\n"
        "class Derived(Base): pass\n",
    )
    _write_module(
        tmp_path,
        "facade",
        "from manager import Derived\n"
        "from manager import Base as Other\n",
    )
    subject = _write_module(
        tmp_path,
        "subject",
        "import facade\n"
        "def f():\n"
        "    with facade.Derived():\n"
        "        raise ValueError\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    assert _with_gaps(subject) == []
