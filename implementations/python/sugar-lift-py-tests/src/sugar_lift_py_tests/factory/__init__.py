from __future__ import annotations

# Lazy re-exports. Eager imports here re-enter context/floor/temporal while those
# packages are still initializing (sugar_body → factory.audit_row → factory/__init__
# → build → context), which is a circular import under Python 3.14.

__all__ = [
    "FactoryAuditRow",
    "FactoryBuildContext",
    "FactoryBuildResult",
    "FactoryGap",
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
    "FactoryGap": (".factory_gap", "FactoryGap"),
    "FactoryGapInfo": (".factory_gap_info", "FactoryGapInfo"),
    "GapKind": (".factory_gap_info", "GapKind"),
    "GapLocus": (".factory_gap_info", "GapLocus"),
    "SourceFragment": (".source_fragment", "SourceFragment"),
    "SourceFragmentStack": (".source_fragment_stack", "SourceFragmentStack"),
    "build_next": (".build", "build_next"),
    "build_node": (".build", "build_node"),
    "default_catalog": (".build", "default_catalog"),
}


def __getattr__(name: str):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    from importlib import import_module

    value = getattr(import_module(module_name, __name__), attr)
    globals()[name] = value
    return value
