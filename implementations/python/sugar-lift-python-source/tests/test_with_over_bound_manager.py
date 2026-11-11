"""``ctx = cm(); with ctx:`` and ``ctx`` bound in the arms of an ``if``.

Python evaluates the binding's call where it is written, once, and the
``with`` enters the manager that call returned.  The derived manager frame is
therefore seated on that call's own coordinate, and a ``with`` whose head is
the phi of the arms' calls is the owning ``if``'s own selection: under the
same branch result, each arm enters its own call's manager.
"""

from __future__ import annotations

from pathlib import Path

import pytest

IMPL = """class M:
    def __enter__(self):
        return 1
    def __exit__(self, *exc):
        return False
class N:
    def __enter__(self):
        raise KeyError(1)
    def __exit__(self, *exc):
        return False
def cm():
    return M()
def cn():
    return N()
"""

_WITH = "    with ctx:\n        pass\n    return 7\n"


def _populated(tmp_path: Path, consumer: str):
    from test_returned_resource_with_construction import _distribution

    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_python_source.manager_summary_derivation import (
        populate_source_derived_resource_refs,
    )
    from sugar_lift_python_source.resolution_session import SourceResolutionSession
    from sugar_source_tree.tree import SourceFile

    dist = _distribution(tmp_path, IMPL, exported="cm")
    (tmp_path / "arbitrary" / "__init__.py").write_text(
        "from arbitrary.manager import cm, cn\n", encoding="utf-8"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": dist},
        artifact_graph_cache=None,
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({dist.metadata["Name"]})
        ),
    )
    return tree


def _exits(tree):
    from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset
    from sugar_source_tree.nodes import FunctionDef

    function = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    return sorted(
        type(face).__name__
        for face in outcome_to_exitset(function.sugar().desugar()).exits
    )


def test_single_bound_manager_enters_the_assigned_call(tmp_path):
    consumer = "from arbitrary import cm\ndef f():\n    ctx = cm()\n" + _WITH
    assert _exits(_populated(tmp_path, consumer)) == ["Completed"]


def test_single_bound_manager_matches_the_direct_with(tmp_path):
    direct = "from arbitrary import cm\ndef f():\n    with cm():\n        pass\n    return 7\n"
    assert _exits(_populated(tmp_path, direct)) == ["Completed"]


def test_branch_bound_manager_selects_under_the_owning_branch(tmp_path):
    consumer = (
        "import os\nfrom arbitrary import cm\ndef f():\n"
        '    if os.environ.get("X"):\n        ctx = cm()\n'
        "    else:\n        ctx = cm()\n" + _WITH
    )
    tree = _populated(tmp_path, consumer)
    from sugar_lift_py_tests.sugar.if_sugar import IfSugar
    from sugar_source_tree.nodes import FunctionDef, With

    function = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    projected = next(n for n in function.substitute({}).walk() if isinstance(n, With))
    assert isinstance(projected.sugar(), IfSugar)
    # The unresolved ``os.environ.get`` may raise; both arms complete.
    assert _exits(tree) == ["Completed", "Halted"]


def test_ground_branch_never_demands_the_unselected_manager(tmp_path):
    # ``cn``'s enter may raise, which this contract refuses at ``cn()``; a
    # ground condition never runs that arm, so its refusal is not demanded.
    consumer = (
        "from arbitrary import cm, cn\ndef f():\n"
        "    if True:\n        ctx = cm()\n    else:\n        ctx = cn()\n" + _WITH
    )
    assert _exits(_populated(tmp_path, consumer)) == ["Completed"]


def test_symbolic_branch_refuses_at_the_arm_call_it_cannot_enter(tmp_path):
    from sugar_source_tree.panic import ContextManagerResolutionConstructionGap

    consumer = (
        "import os\nfrom arbitrary import cm, cn\ndef f():\n"
        '    if os.environ.get("X"):\n        ctx = cn()\n'
        "    else:\n        ctx = cm()\n" + _WITH
    )
    with pytest.raises(ContextManagerResolutionConstructionGap) as raised:
        _exits(_populated(tmp_path, consumer))
    # Blamed at ``cn()`` (line 5), the arm's own call -- the same refusal a
    # direct ``with cn():`` receives -- never at the ``with ctx`` name.
    assert "start_line=5, start_col=14" in str(raised.value)
