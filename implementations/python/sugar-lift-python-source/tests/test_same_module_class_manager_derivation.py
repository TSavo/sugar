"""Same-module ClassDef CM derivation — receipt-less populate door.

Local ``with M():`` has no import receipt. Populate must still derive a
``SourceDerivedContextManagerRefV1`` when ``M`` is a module ClassDef with
``__enter__``/``__exit__``, so With constructs through the L3d require door.
"""

from __future__ import annotations

import csv
import importlib.metadata
import textwrap
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceDerivedContextManagerRefV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_summary_derivation import (
    populate_source_derived_resource_refs,
)
from sugar_source_tree.nodes import With
from sugar_source_tree.panic import ContextManagerResolutionConstructionGap
from sugar_source_tree.tree import SourceFile


def _source_file(
    tmp_path: Path, source: str
) -> tuple[SourceFile, TreeConstructionContextV1, Path]:
    path = tmp_path / "consumer.py"
    path.write_text(source, encoding="utf-8")
    cid = blake3_512_of(source.encode())
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile((source, str(path), cid), construction_context=context)
    return tree, context, path


def _installed_distribution(
    root: Path,
    *,
    package: str,
    source: str,
    duplicate_module_seat: bool = False,
) -> importlib.metadata.Distribution:
    package_dir = root / package
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text(source, encoding="utf-8")
    recorded = [f"{package}/__init__.py"]
    if duplicate_module_seat:
        (root / f"{package}.py").write_text(source, encoding="utf-8")
        recorded.append(f"{package}.py")
    metadata = root / f"{package}_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {package}-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text(f"{package}\n", encoding="utf-8")
    recorded.extend(
        (
            f"{package}_dist-1.0.dist-info/METADATA",
            f"{package}_dist-1.0.dist-info/top_level.txt",
            f"{package}_dist-1.0.dist-info/RECORD",
        )
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for seat in recorded:
            writer.writerow((seat, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _imported_manager_gap(
    tmp_path: Path,
    *,
    package: str,
    distribution: importlib.metadata.Distribution | None = None,
):
    source = textwrap.dedent(f"""\
        from {package} import M
        def f():
            with M():
                return 1
        """)
    tree, context, path = _source_file(tmp_path, source)
    distribution_index = None if distribution is None else {package: distribution}
    enrolled_distribution = (
        "consumer" if distribution is None else distribution.metadata["Name"]
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index=distribution_index,
        distribution=enrolled_distribution,
    )
    assert len(context.source_derived_contract_refs) == 1
    gap = next(iter(context.source_derived_contract_refs.values()))
    assert type(gap).__name__ == "ContextManagerResolutionGapV1"
    with_node = next(node for node in tree.nodes() if isinstance(node, With))
    with pytest.raises(ContextManagerResolutionConstructionGap) as caught:
        with_node.sugar()
    return gap, caught.value.observed


def test_local_classdef_cm_derives_and_constructs(tmp_path: Path):
    """Visible same-module ClassDef CM: populate derives; With constructs."""
    source = textwrap.dedent("""\
        class M:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        def f():
            with M():
                return 1
        """)
    tree, context, path = _source_file(tmp_path, source)
    populate_source_derived_resource_refs(tree, root=tmp_path, path=path)

    assert len(context.source_derived_contract_refs) == 1
    ref = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(ref, SourceDerivedContextManagerRefV1)

    with_node = next(n for n in tree.nodes() if isinstance(n, With))
    sugar = with_node.sugar()
    assert isinstance(sugar, WithSourceResourceSugar)


def test_local_classdef_without_protocol_installs_gap(tmp_path: Path):
    """ClassDef without __enter__/__exit__: gap row; With panics named."""
    source = textwrap.dedent("""\
        class NotCM:
            def run(self):
                return 1
        def f():
            with NotCM():
                return 1
        """)
    tree, context, path = _source_file(tmp_path, source)
    populate_source_derived_resource_refs(tree, root=tmp_path, path=path)

    assert len(context.source_derived_contract_refs) == 1
    gap = next(iter(context.source_derived_contract_refs.values()))
    assert type(gap).__name__ == "ContextManagerResolutionGapV1"
    assert gap.target_symbol == "python:local:NotCM"

    with_node = next(n for n in tree.nodes() if isinstance(n, With))
    with pytest.raises(ContextManagerResolutionConstructionGap) as caught:
        with_node.sugar()
    assert caught.value.owner == "With._construct_sugar"


def test_install_gap_never_attribute_errors_on_import_auth_fail(tmp_path: Path):
    """Import CM without dist: gap installs; no AttributeError on deleted ground mint."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text(
        textwrap.dedent("""\
            class M:
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    return False
            """),
        encoding="utf-8",
    )
    source = textwrap.dedent("""\
        from pkg import M
        def f():
            with M():
                return 1
        """)
    tree, context, path = _source_file(tmp_path, source)
    # No distribution_index → authenticate fails → no-derived-contract gap.
    populate_source_derived_resource_refs(tree, root=tmp_path, path=path)
    assert len(context.source_derived_contract_refs) == 1
    gap = next(iter(context.source_derived_contract_refs.values()))
    assert type(gap).__name__ == "ContextManagerResolutionGapV1"
    assert gap.kind == "no-derived-contract"


def test_manager_derivation_reasons_distinguish_dependency_failure_causes(
    tmp_path: Path,
) -> None:
    """Absent, ambiguous, and contract-missing are distinct receipt reasons."""
    absent_root = tmp_path / "absent"
    absent_root.mkdir()
    absent, absent_observed = _imported_manager_gap(
        absent_root, package="absent_manager_pkg"
    )

    ambiguous_root = tmp_path / "ambiguous"
    ambiguous_root.mkdir()
    ambiguous_distribution = _installed_distribution(
        ambiguous_root,
        package="ambiguous_manager_pkg",
        source="class M:\n    pass\n",
        duplicate_module_seat=True,
    )
    ambiguous, ambiguous_observed = _imported_manager_gap(
        ambiguous_root,
        package="ambiguous_manager_pkg",
        distribution=ambiguous_distribution,
    )

    missing_contract_root = tmp_path / "missing_contract"
    missing_contract_root.mkdir()
    missing_contract_distribution = _installed_distribution(
        missing_contract_root,
        package="missing_contract_pkg",
        source="class M:\n    pass\n",
    )
    missing_contract, missing_contract_observed = _imported_manager_gap(
        missing_contract_root,
        package="missing_contract_pkg",
        distribution=missing_contract_distribution,
    )

    reasons = {
        "absent": (absent.kind, absent.detail),
        "ambiguous": (ambiguous.kind, ambiguous.detail),
        "missing-contract": (missing_contract.kind, missing_contract.detail),
    }
    assert len(set(reasons.values())) == 3, reasons
    assert "absent_manager_pkg" in (absent.detail or "")
    assert "authenticated stdlib root" in (absent.detail or "")
    assert "ambiguous_manager_pkg" in (ambiguous.detail or "")
    assert "duplicate module seat" in (ambiguous.detail or "")
    assert missing_contract.kind == "enter-missing"
    assert missing_contract.detail == "source-visible method"
    observed_reasons = {
        absent_observed,
        ambiguous_observed,
        missing_contract_observed,
    }
    assert len(observed_reasons) == 3, observed_reasons
    assert absent.detail in absent_observed
    assert ambiguous.detail in ambiguous_observed
    assert missing_contract.detail in missing_contract_observed
