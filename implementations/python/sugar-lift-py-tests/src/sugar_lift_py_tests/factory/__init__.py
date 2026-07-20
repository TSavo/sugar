from __future__ import annotations

# Lazy re-exports. Eager imports here re-enter context/floor/temporal while those
# packages are still initializing (sugar_body → factory.audit_row → factory/__init__
# → build → context), which is a circular import under Python 3.14.

__all__ = [
    "FactoryAuditRow",
    "FactoryBuildContext",
    "FactoryBuildResult",
    "factory_panic",
    "factory_panic_gap",
    "dig_boundary_panic",
    "FactoryPanic",
    "FactoryGapInfo",
    "GapKind",
    "GapLocus",
    "SourceFragment",
    "SourceFragmentStack",
    "build_next",
    "build_node",
    "default_catalog",
]

_LAZY: dict[str, tuple[str, str]] = {
    "FactoryAuditRow": (".factory_audit_row", "FactoryAuditRow"),
    "FactoryBuildContext": (".factory_build_context", "FactoryBuildContext"),
    "FactoryBuildResult": (".factory_build_result", "FactoryBuildResult"),
    "factory_panic": (".factory_gap", "factory_panic"),
    "factory_panic_gap": (".factory_gap", "factory_panic_gap"),
    "dig_boundary_panic": (".factory_gap", "dig_boundary_panic"),
    "FactoryPanic": (".factory_gap", "FactoryPanic"),
    "FactoryGapInfo": (".factory_gap_info", "FactoryGapInfo"),
    "GapKind": (".factory_gap_info", "GapKind"),
    "GapLocus": (".factory_gap_info", "GapLocus"),
    "SourceFragment": (".source_fragment", "SourceFragment"),
    "SourceFragmentStack": (".source_fragment_stack", "SourceFragmentStack"),
    "build_next": (".build", "build_next"),
    "build_node": (".build", "build_node"),
    "default_catalog": (".build", "default_catalog"),
}


def _import_relative_submodule(module_name: str):
    """Import one of this package's own relative submodules, by literal name.

    Every branch below passes a *literal* ``".foo"`` string with ``__name__``
    as the package argument -- the mechanical self-import proof
    ``R_source_via_execution`` requires (#5930): a leading ``.`` resolved
    against this module's own ``__name__`` cannot spell a third-party
    module, so it is provable by the call-site shape itself, not by a
    dict lookup the auditor cannot see through. Add a branch here, never a
    dynamic dispatch, when a new lazy submodule is added.
    """
    from importlib import import_module

    if module_name == ".factory_audit_row":
        return import_module(".factory_audit_row", __name__)
    if module_name == ".factory_build_context":
        return import_module(".factory_build_context", __name__)
    if module_name == ".factory_build_result":
        return import_module(".factory_build_result", __name__)
    if module_name == ".factory_gap":
        return import_module(".factory_gap", __name__)
    if module_name == ".factory_gap_info":
        return import_module(".factory_gap_info", __name__)
    if module_name == ".source_fragment":
        return import_module(".source_fragment", __name__)
    if module_name == ".source_fragment_stack":
        return import_module(".source_fragment_stack", __name__)
    if module_name == ".build":
        return import_module(".build", __name__)
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
