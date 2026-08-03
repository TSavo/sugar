"""Same-module ClassDef CM derivation — receipt-less populate door.

Local ``with M():`` has no import receipt. Populate must still derive a
``SourceDerivedContextManagerRefV1`` when ``M`` is a module ClassDef with
``__enter__``/``__exit__``, so With constructs through the L3d require door.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceDerivedContextManagerRefV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_summary_derivation import (
    _install_derivation_gap,
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
    # The consumer roster is explicit so this tooth reaches authentication.
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        source_workspace_root=tmp_path,
        distribution="consumer",
    )
    assert len(context.source_derived_contract_refs) == 1
    gap = next(iter(context.source_derived_contract_refs.values()))
    assert type(gap).__name__ == "ContextManagerResolutionGapV1"
    assert gap.kind == "no-derived-contract"


def test_dependency_authentication_failures_keep_distinct_gap_reasons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absent, ambiguous, and genuinely missing contracts remain distinct."""
    from sugar_lift_python_source import dependency_artifact

    def recorded_authentication_gap(case: str, detail: str):
        case_root = tmp_path / case
        case_root.mkdir()
        source = textwrap.dedent(f"""\
            # distinct authenticated source identity: {case}
            from pkg import M
            def f():
                with M():
                    return 1
            """)
        tree, context, path = _source_file(case_root, source)

        def refuse_authentication(*_args, **_kwargs):
            raise dependency_artifact.DependencyArtifactAuthenticationError(detail)

        monkeypatch.setattr(
            dependency_artifact,
            "authenticate_dependency_top_level",
            refuse_authentication,
        )
        populate_source_derived_resource_refs(
            tree,
            root=case_root,
            path=path,
            source_workspace_root=case_root,
            distribution="consumer",
        )
        gap = next(iter(context.source_derived_contract_refs.values()))
        return tree, context, gap

    absent_tree, absent_context, absent = recorded_authentication_gap(
        "absent",
        "module has no source in the authenticated stdlib root",
    )
    ambiguous_tree, _, ambiguous = recorded_authentication_gap(
        "ambiguous",
        "distribution contains duplicate module seat numpy.__config__",
    )
    genuine_tree, genuine_context, seeded_genuine = recorded_authentication_gap(
        "genuine",
        "seed replaced before construction",
    )

    def observed_reason(tree: SourceFile) -> str:
        with_node = next(n for n in tree.nodes() if isinstance(n, With))
        with pytest.raises(ContextManagerResolutionConstructionGap) as caught:
            with_node.sugar()
        return caught.value.observed

    absent_observed = observed_reason(absent_tree)
    ambiguous_observed = observed_reason(ambiguous_tree)

    # The third arm is a genuine missing-contract row, not another dependency
    # authentication exception. Preserve that existing structural meaning while
    # making the two caught authentication causes independently visible.
    _install_derivation_gap(
        genuine_context,
        seeded_genuine.use_site,
        SimpleNamespace(
            demand={"cid": seeded_genuine.demand_cid},
            use={"cid": "use-cid"},
            target_symbol=seeded_genuine.target_symbol,
        ),
        "no-derived-contract",
    )
    genuine = genuine_context.source_derived_contract_refs[seeded_genuine.use_site]
    genuine_observed = observed_reason(genuine_tree)

    reasons = {
        "absent-package": (absent.kind, absent.detail),
        "ambiguous-graph-authentication": (ambiguous.kind, ambiguous.detail),
        "genuinely-missing-contract": (genuine.kind, genuine.detail),
    }
    assert reasons == {
        "absent-package": (
            "no-derived-contract",
            "module has no source in the authenticated stdlib root",
        ),
        "ambiguous-graph-authentication": (
            "no-derived-contract",
            "distribution contains duplicate module seat numpy.__config__",
        ),
        "genuinely-missing-contract": ("no-derived-contract", None),
    }
    assert len(set(reasons.values())) == 3
    assert len({absent_observed, ambiguous_observed, genuine_observed}) == 3
    assert "module has no source in the authenticated stdlib root" in absent_observed
    assert (
        "distribution contains duplicate module seat numpy.__config__"
        in ambiguous_observed
    )
    assert genuine_observed.endswith("no-derived-contract for manager 'python:pkg.M'")
