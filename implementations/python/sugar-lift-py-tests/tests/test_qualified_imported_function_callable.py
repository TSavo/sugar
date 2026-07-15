from __future__ import annotations

import ast
import importlib.machinery
import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import CallSiteValue, ImportAliasValue, TermValue
from sugar_lift_py_tests.lift_rpc import _module_import_temporal
from sugar_lift_py_tests.outcome import complete_value


def _write_module(root: Path, qualified: str, source: str) -> None:
    parts = qualified.split(".")
    package = root
    for part in parts[:-1]:
        package /= part
        package.mkdir(exist_ok=True)
        init = package / "__init__.py"
        if not init.exists():
            init.write_text('raise RuntimeError("package must not execute")\n')
    (package / f"{parts[-1]}.py").write_text(source)


def _consumer_call(source: str, call: str, filename: str = "consumer.py"):
    catalog = default_catalog()
    root = SourceFragment.from_source(source, filename)
    module = root.statements()[0]
    temporal = _module_import_temporal(module, catalog)
    ctx = FactoryBuildContext(
        filename=filename,
        catalog=catalog,
        temporal=temporal,
        module_temporal=temporal,
    )
    node = ast.parse(call, filename=filename).body[0].value
    return (
        complete_value(
            build_node(
                node, filename=filename, role=SugarRole.TERM, ctx=ctx
            ).sugar.desugar(ctx),
            owner="qualified imported function fixture",
        ),
        temporal,
    )


def test_direct_extension_symbol_emits_qualified_bodyless_bridge_without_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extension = tmp_path / f"fixture_native{importlib.machinery.EXTENSION_SUFFIXES[0]}"
    extension.write_bytes(b"not a loadable extension")
    monkeypatch.syspath_prepend(str(tmp_path))

    callsite, temporal = _consumer_call(
        "from fixture_native import exact as chosen\n", "chosen(7)"
    )

    alias = temporal.value_for("chosen")
    assert isinstance(alias, ImportAliasValue)
    assert alias.import_target == "fixture_native.exact"
    assert alias.resolved_value is not None
    assert isinstance(callsite, CallSiteValue)
    assert callsite.target_name == "fixture_native.exact"
    assert callsite.arg_values == (TermValue(7),)
    assert callsite.body is None
    assert callsite.term.name == "call:fixture_native.exact"
    assert "fixture_native" not in sys.modules


def test_reexported_extension_symbol_keeps_ultimate_native_coordinate_without_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "fixture_native_reexport"
    package.mkdir()
    (package / "__init__.py").write_text(
        'raise RuntimeError("package must not execute")\n'
    )
    (package / "api.py").write_text(
        'raise RuntimeError("api must not execute")\n'
        "from .native import exact as exported\n"
    )
    extension = package / f"native{importlib.machinery.EXTENSION_SUFFIXES[0]}"
    extension.write_bytes(b"not a loadable extension")
    monkeypatch.syspath_prepend(str(tmp_path))

    callsite, temporal = _consumer_call(
        "from fixture_native_reexport.api import exported as chosen\n", "chosen(7)"
    )

    alias = temporal.value_for("chosen")
    assert isinstance(alias, ImportAliasValue)
    assert alias.import_target == "fixture_native_reexport.api.exported"
    assert alias.resolved_value is not None
    assert isinstance(callsite, CallSiteValue)
    assert callsite.target_name == "fixture_native_reexport.native.exact"
    assert callsite.arg_values == (TermValue(7),)
    assert callsite.body is None
    assert callsite.term.name == "call:fixture_native_reexport.native.exact"
    assert not any(name.startswith("fixture_native_reexport") for name in sys.modules)


def test_literal_all_star_reexport_reaches_exact_function_without_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_module(
        tmp_path,
        "fixture_star.impl",
        'raise RuntimeError("impl must not execute")\n'
        '__all__ = ["exact"]\n'
        "def exact(value=7):\n"
        "    return value\n",
    )
    _write_module(
        tmp_path,
        "fixture_star.api",
        'raise RuntimeError("api must not execute")\n' "from .impl import *\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    callsite, temporal = _consumer_call(
        "from fixture_star.api import exact as chosen\n", "chosen()"
    )

    alias = temporal.value_for("chosen")
    assert isinstance(alias, ImportAliasValue)
    assert alias.import_target == "fixture_star.api.exact"
    assert alias.resolved_value is not None
    assert isinstance(callsite, CallSiteValue)
    assert callsite.target_name == "fixture_star.impl.exact"
    assert callsite.parameters == ("value",)
    assert callsite.arg_values == (TermValue(7),)
    assert callsite.body is not None
    assert not any(name.startswith("fixture_star") for name in sys.modules)


def test_dynamic_all_star_reexport_stays_named_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_module(
        tmp_path,
        "fixture_dynamic_star.impl",
        "def exported_names():\n"
        '    return ["exact"]\n'
        "__all__ = exported_names()\n"
        "def exact():\n"
        "    return 7\n",
    )
    _write_module(
        tmp_path,
        "fixture_dynamic_star.api",
        'raise RuntimeError("api must not execute")\n' "from .impl import *\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(FactoryPanic) as raised:
        _consumer_call("from fixture_dynamic_star.api import exact\n", "exact()")

    assert raised.value.info.owner == "CallSugar"
    assert raised.value.info.observed == "fixture_dynamic_star.api.exact"
    assert not any(name.startswith("fixture_dynamic_star") for name in sys.modules)


def test_two_literal_all_star_routes_stay_named_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for module, value in (("left", 1), ("right", 2)):
        _write_module(
            tmp_path,
            f"fixture_ambiguous_star.{module}",
            '__all__ = ["exact"]\n' f"def exact():\n    return {value}\n",
        )
    _write_module(
        tmp_path,
        "fixture_ambiguous_star.api",
        'raise RuntimeError("api must not execute")\n'
        "from .left import *\n"
        "from .right import *\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(FactoryPanic) as raised:
        _consumer_call("from fixture_ambiguous_star.api import exact\n", "exact()")

    assert raised.value.info.owner == "install_source_dig"
    assert raised.value.info.observed == "fixture_ambiguous_star.api.exact"
    assert "one exact manifest-witnessed star re-export route" in (
        raised.value.info.requested
    )
    assert not any(name.startswith("fixture_ambiguous_star") for name in sys.modules)


def test_reexported_qualified_function_reaches_function_callable_binder_without_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_module(
        tmp_path,
        "fixture_alpha.impl",
        'raise RuntimeError("impl must not execute")\n'
        "def exact(value=7):\n"
        "    return value\n",
    )
    _write_module(
        tmp_path,
        "fixture_alpha.api",
        'raise RuntimeError("api must not execute")\n'
        "from .impl import exact as exported\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    callsite, temporal = _consumer_call(
        "from fixture_alpha.api import exported as chosen\n", "chosen()"
    )

    alias = temporal.value_for("chosen")
    assert isinstance(alias, ImportAliasValue)
    assert alias.import_target == "fixture_alpha.api.exported"
    assert alias.resolved_value is not None
    assert isinstance(callsite, CallSiteValue)
    assert callsite.target_name == "fixture_alpha.impl.exact"
    assert callsite.parameters == ("value",)
    assert callsite.arg_values == (TermValue(7),)
    assert callsite.body is not None
    assert callsite.force_floor(
        FactoryBuildContext(filename="consumer.py", catalog=default_catalog()),
        owner="reexport fixture",
        project_callsite=False,
    ) == TermValue(7)
    assert not any(name.startswith("fixture_alpha") for name in sys.modules)


def test_same_leaf_modules_bind_their_own_exact_reexported_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for package, value in (("fixture_left", 11), ("fixture_right", 22)):
        _write_module(
            tmp_path,
            f"{package}.shared",
            'raise RuntimeError("shared must not execute")\n'
            f"def exact():\n    return {value}\n",
        )
        _write_module(
            tmp_path,
            f"{package}.api",
            'raise RuntimeError("api must not execute")\n'
            "from .shared import exact as exported\n",
        )
    monkeypatch.syspath_prepend(str(tmp_path))

    left, _ = _consumer_call(
        "from fixture_left.api import exported as chosen\n", "chosen()", "left.py"
    )
    right, _ = _consumer_call(
        "from fixture_right.api import exported as chosen\n", "chosen()", "right.py"
    )
    force_ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())
    assert left.force_floor(
        force_ctx, owner="left", project_callsite=False
    ) == TermValue(11)
    assert right.force_floor(
        force_ctx, owner="right", project_callsite=False
    ) == TermValue(22)
    assert not any(
        name.startswith(("fixture_left", "fixture_right")) for name in sys.modules
    )


def test_missing_qualified_imported_function_stays_named_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_module(
        tmp_path,
        "fixture_missing.api",
        'raise RuntimeError("api must not execute")\nTOKEN = 1\n',
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(FactoryPanic) as raised:
        _consumer_call("from fixture_missing.api import absent\n", "absent()")

    assert raised.value.info.owner == "CallSugar"
    assert raised.value.info.observed == "fixture_missing.api.absent"
    assert "exact installed-source FunctionDef" in raised.value.info.requested
    assert not any(name.startswith("fixture_missing") for name in sys.modules)


def test_ambiguous_same_qualified_definition_stays_named_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_module(
        tmp_path,
        "fixture_ambiguous.api",
        'raise RuntimeError("api must not execute")\n'
        "def chosen():\n    return 1\n"
        "def chosen():\n    return 2\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(FactoryPanic) as raised:
        _consumer_call("from fixture_ambiguous.api import chosen\n", "chosen()")

    assert raised.value.info.owner == "install_source_dig"
    assert raised.value.info.observed == "fixture_ambiguous.api.chosen"
    assert "unique top-level FunctionDef" in raised.value.info.requested
    assert not any(name.startswith("fixture_ambiguous") for name in sys.modules)


def test_overload_declarations_do_not_compete_with_the_runtime_definition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_module(
        tmp_path,
        "fixture_overloaded.api",
        'raise RuntimeError("api must not execute")\n'
        "from typing import overload\n"
        "@overload\n"
        "def chosen(value: int) -> int: ...\n"
        "@overload\n"
        "def chosen(value: str) -> str: ...\n"
        "def chosen(value):\n"
        "    return value\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    callsite, _ = _consumer_call(
        "from fixture_overloaded.api import chosen\n", "chosen(7)"
    )

    assert isinstance(callsite, CallSiteValue)
    assert callsite.target_name == "fixture_overloaded.api.chosen"
    assert callsite.parameters == ("value",)
    assert callsite.body is not None
    assert callsite.force_floor(
        FactoryBuildContext(filename="consumer.py", catalog=default_catalog()),
        owner="overload fixture",
        project_callsite=False,
    ) == TermValue(7)
    assert not any(name.startswith("fixture_overloaded") for name in sys.modules)


def test_ambiguous_reexport_route_stays_named_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for module, value in (("left", 1), ("right", 2)):
        _write_module(
            tmp_path,
            f"fixture_reexport_ambiguous.{module}",
            f"def exact():\n    return {value}\n",
        )
    _write_module(
        tmp_path,
        "fixture_reexport_ambiguous.api",
        'raise RuntimeError("api must not execute")\n'
        "from .left import exact as chosen\n"
        "from .right import exact as chosen\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(FactoryPanic) as raised:
        _consumer_call(
            "from fixture_reexport_ambiguous.api import chosen\n", "chosen()"
        )

    assert raised.value.info.owner == "install_source_dig"
    assert raised.value.info.observed == "fixture_reexport_ambiguous.api.chosen"
    assert "one exact qualified re-export route" in raised.value.info.requested
    assert not any(
        name.startswith("fixture_reexport_ambiguous") for name in sys.modules
    )


def test_reexported_qualified_function_signature_mismatch_stays_named_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_module(
        tmp_path,
        "fixture_signature.impl",
        "def exact(required):\n    return required\n",
    )
    _write_module(
        tmp_path,
        "fixture_signature.api",
        'raise RuntimeError("api must not execute")\n'
        "from .impl import exact as chosen\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(FactoryPanic) as raised:
        _consumer_call("from fixture_signature.api import chosen\n", "chosen()")

    assert raised.value.info.owner == "FunctionCallable"
    assert raised.value.info.observed == ("positional",)
    assert raised.value.info.requested == "bind call arguments to a function signature"
    assert not any(name.startswith("fixture_signature") for name in sys.modules)
