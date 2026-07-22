from __future__ import annotations

# Lazy re-exports. Eager imports here re-enter context/floor/temporal while those
# packages are still initializing (circular import under Python 3.14).
#
# build_node / default_catalog / FactoryBuildResult / SourceFragmentStack were
# deleted with the factory construction path; only gap/audit/source_fragment
# remnants remain until the concept migrations land.

__all__ = [
    "FactoryAuditRow",
    "factory_panic",
    "factory_panic_gap",
    "dig_boundary_panic",
    "FactoryPanic",
    "FactoryGapInfo",
    "GapKind",
    "GapLocus",
    "SourceFragment",
]

_LAZY: dict[str, tuple[str, str]] = {
    "FactoryAuditRow": (".factory_audit_row", "FactoryAuditRow"),
    "factory_panic": (".factory_gap", "factory_panic"),
    "factory_panic_gap": (".factory_gap", "factory_panic_gap"),
    "dig_boundary_panic": (".factory_gap", "dig_boundary_panic"),
    "FactoryPanic": (".factory_gap", "FactoryPanic"),
    "FactoryGapInfo": (".factory_gap_info", "FactoryGapInfo"),
    "GapKind": (".factory_gap_info", "GapKind"),
    "GapLocus": (".factory_gap_info", "GapLocus"),
    "SourceFragment": (".source_fragment", "SourceFragment"),
}


def _import_relative_submodule(module_name: str):
    """Import one of this package's own relative submodules, by literal name.

    Every branch below passes a *literal* ``".foo"`` string with ``__name__``
    as the package argument -- the mechanical self-import proof
    ``R_source_via_execution`` requires (#5930).
    """
    from importlib import import_module

    if module_name == ".factory_audit_row":
        return import_module(".factory_audit_row", __name__)
    if module_name == ".factory_gap":
        return import_module(".factory_gap", __name__)
    if module_name == ".factory_gap_info":
        return import_module(".factory_gap_info", __name__)
    if module_name == ".source_fragment":
        return import_module(".source_fragment", __name__)
    raise AttributeError(
        f"module {__name__!r} has no relative submodule {module_name!r}"
    )


def __getattr__(name: str):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    value = getattr(_import_relative_submodule(module_name), attr)
    globals()[name] = value
    return value
