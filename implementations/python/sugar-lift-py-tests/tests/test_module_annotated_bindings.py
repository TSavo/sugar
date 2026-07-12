from __future__ import annotations

from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import BoundVar
from sugar_lift_py_tests.lift_rpc import _module_import_temporal, audit_lift_file


def _temporal(source: str):
    module = SourceFragment.from_source(source, "shared_docs.py")
    return _module_import_temporal(module, default_catalog())


def test_valued_module_annassign_seeds_shared_docs_binding() -> None:
    temporal = _temporal("_shared_docs: dict[str, str] = {}\n")

    binding = temporal.value_for("_shared_docs")
    assert isinstance(binding, BoundVar)
    assert binding.name == "_shared_docs"
    assert binding.source.site.observed == "Dict"


def test_annotation_only_module_name_stays_loudly_unbound() -> None:
    source = "registry: dict[str, str]\n\ndef read():\n    return registry\n"
    _payload, gaps = audit_lift_file(source, "annotation_only.py")

    gap = next(gap for gap in gaps if gap.label.endswith(":3:0"))
    assert "owner=TemporalContext" in gap.message
    assert "observed=registry requested=value" in gap.message


def test_module_annassign_uses_factory_boundvar_not_parallel_coordinate() -> None:
    temporal = _temporal("registry: dict[str, str] = {}\n")
    binding = temporal.value_for("registry")

    assert type(binding) is BoundVar
    assert "python:module" not in repr(binding)
