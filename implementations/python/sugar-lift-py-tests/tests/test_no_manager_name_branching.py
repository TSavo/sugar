"""No code branches on a manager's name.

A context manager is identified by its binding -- the authenticated
definition its call resolves to -- never by how the manager or its package is
spelled. Renaming a manager, importing it under an alias, or publishing an
unrelated manager with the same shape must reach the same construction, so no
module that seats, constructs or runs a manager may hold a manager's name as a
string to compare against, and none may re-parse source to look one up.

This law was held by ``test_renamed_generator_manager_publication.py``
(deleted with the generator-backed ref in #8021); it is restored here over the
modules that handle managers today.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

# Every module that seats, constructs, enters, exits or runs a manager.
_MANAGER_MODULES = (
    "sugar_lift_python_source.manager_summary_derivation",
    "sugar_lift_python_source.manager_protocol_construction",
    "sugar_lift_python_source.manager_construction",
    "sugar_lift_python_source.manager_protocol_absence",
    "sugar_lift_python_source.formal_selected_manager",
    "sugar_lift_py_tests.context_manager_contract",
    "sugar_lift_py_tests.context_manager_resolution",
    "sugar_lift_py_tests.generator_construction",
    "sugar_lift_py_tests.generator_manager_exit",
    "sugar_lift_py_tests.sugar.generator_with_sugar",
    "sugar_lift_py_tests.sugar.with_formal_manager_sugar",
    "sugar_lift_py_tests.sugar.with_opaque_cited_manager_sugar",
    "sugar_lift_py_tests.sugar.with_resource_sugar",
    "sugar_lift_py_tests.sugar.with_source_resource_sugar",
    "sugar_source_tree.formal_manager_head",
)

# Manager and package spellings a name-dispatch arm would compare against:
# real-world managers, the helper class contextlib hides behind
# ``@contextmanager``, and unrelated managers of the same shape with an alias.
_FORBIDDEN_NAMES = frozenset(
    {
        "option_context",
        "pd.option_context",
        "ensure_clean",
        "catch_warnings",
        "temporary_state",
        "_GeneratorContextManager",
        "contextmanager",
        "contextlib.py",
        "set_config",
        "filter_warnings",
        "hold_state",
        "apply_settings",
        "cfg_setter_pkg",
        "warn_filter_pkg",
        "temp_state_pkg",
    }
)


def _module_source(name: str) -> str:
    spec = importlib.util.find_spec(name)
    assert spec is not None and spec.origin, f"{name} is not importable"
    return Path(spec.origin).read_text(encoding="utf-8")


@pytest.mark.parametrize("module_name", _MANAGER_MODULES)
def test_manager_module_holds_no_manager_name(module_name: str):
    source = _module_source(module_name)
    literals = {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert literals.isdisjoint(_FORBIDDEN_NAMES), (
        f"{module_name} names a manager: {sorted(literals & _FORBIDDEN_NAMES)}"
    )


@pytest.mark.parametrize("module_name", _MANAGER_MODULES)
def test_manager_module_does_not_reparse_source(module_name: str):
    source = _module_source(module_name)
    assert "ast.parse" not in source, f"{module_name} re-parses source"
    assert "ast.walk" not in source, f"{module_name} walks a re-parsed tree"
