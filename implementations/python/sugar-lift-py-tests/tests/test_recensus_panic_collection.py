from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests.gap.info import ConstructionGap
from sugar_lift_py_tests.gap.panic import ConstructionPanic


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_SCRIPTS = sugar_lift_py_tests_package_root() / "scripts"


def _load(name: str):
    path = _SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec.loader.exec_module(module)
    return module


CONSUMER = _load("recensus_enumerate_consumer")


def test_recensus_projects_construction_panic_as_a_loud_counted_terminal(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "fixture.py"
    path.write_text("def a():\n    return 1\n", encoding="utf-8")

    def boom(*_a, **_k):
        raise ConstructionPanic(
            ConstructionGap(
                owner="renamed-constructor",
                blame="fixture.py:1:0",
                observed="OpaqueValue",
                requested="constructed value",
                fix="implement the constructor",
            )
        )

    import sugar_source_tree.tree as tree_mod

    monkeypatch.setattr(tree_mod.SourceFile, "__init__", boom)
    row = CONSUMER.measure_file_via_enumerate(
        workspace_root=tmp_path,
        file_rel="fixture.py",
    )

    assert row["category"] == "panic"
    assert row["terminalKind"] == "construction-panic"
    assert row["blocking_terminal_count"] == 1
    assert row["panic"]["observedEventType"].endswith(".ConstructionPanic")
    assert len(row["constructionPanics"]) == 1


def test_contract_ref_fallback_panic_stays_loud_after_roster_bank(
    tmp_path: Path, monkeypatch
) -> None:
    """Fallback derivation follows roster banking and never absorbs its panic."""
    path = tmp_path / "fixture.py"
    path.write_text("def a():\n    return 1\n", encoding="utf-8")
    calls: list[str] = []

    def roster(**_kwargs):
        calls.append("roster")
        return ([{"kind": "function-memento"}], [])

    def fallback(_root):
        calls.append("fallback")
        raise ConstructionPanic(
            ConstructionGap(
                owner="fallback-demand-table-panic",
                blame="fixture.py:1:0",
                observed="fallback demand-table construction",
                requested="authenticated contract refs",
                fix="keep fallback failure loud after the per-file roster bank",
            )
        )

    import sugar_lift_py_tests.lift_rpc as lift_rpc

    monkeypatch.setattr(CONSUMER, "demand_function_roster", roster)
    monkeypatch.setattr(lift_rpc, "provisional_contract_refs_from_demands", fallback)

    with pytest.raises(ConstructionPanic) as raised:
        CONSUMER.measure_file_via_enumerate(
            workspace_root=tmp_path,
            file_rel="fixture.py",
        )

    assert raised.value.info.owner == "fallback-demand-table-panic"
    assert calls == ["roster", "fallback"]


def test_mid_file_construction_panic_does_not_shrink_function_denominator(
    tmp_path: Path, monkeypatch
) -> None:
    """Lying twin: a ConstructionPanic mid-loop must not bank a partial total.

    Truthful: functionsTotal is the declared population, materialized before the
    walk. A panic that escapes still leaves the full denominator on the row so
    the board never computes Clean% over a silently shrunken set.
    """
    path = tmp_path / "multi.py"
    path.write_text(
        "def a():\n    return 1\n\ndef b():\n    return 2\n\ndef c():\n    return 3\n",
        encoding="utf-8",
    )

    calls = {"n": 0}
    original_sugar = None

    def flaky_sugar(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ConstructionPanic(
                ConstructionGap(
                    owner="mid-file-panic",
                    blame="multi.py:b",
                    observed="second function",
                    requested="constructed sugar",
                    fix="keep the panic loud without shrinking the denominator",
                )
            )
        return original_sugar(self, *args, **kwargs)

    # D2 materializes the complete roster before D3 constructs any function.
    import sugar_source_tree.nodes as nodes_mod

    # D3 reaches FunctionDef.sugar through sugar.enumerate facts/auditFrontier.
    # No skip hatch: if FunctionDef is missing the tooth must fail, not vanish.
    target = nodes_mod.FunctionDef
    original_sugar = target.sugar

    monkeypatch.setattr(target, "sugar", flaky_sugar)
    row = CONSUMER.measure_file_via_enumerate(
        workspace_root=tmp_path,
        file_rel="multi.py",
    )

    assert calls["n"] == 2
    assert row["category"] == "panic"
    assert row["functionsTotal"] == 3
    assert row["functionsEnumerated"] == 3
    assert row["functionsNotEnumerated"] == 0
    assert row["functionsEnumerationComplete"] is True
    assert row["panic"]["owner"] == "mid-file-panic"


def test_control_effect_recensus_enumerates_one_file(tmp_path: Path) -> None:
    path = tmp_path / "clean.py"
    path.write_text("def a(z):\n    return z\n", encoding="utf-8")
    row = CONSUMER.measure_file_via_enumerate(
        workspace_root=tmp_path,
        file_rel="clean.py",
    )

    assert row["category"] == "completed"
    assert row["terminalKind"] == "constructed"
    assert row["enumerateSource"] is True
    assert row["functionsTotal"] == 1
    assert row["functionsClean"] == 1


def test_unresolved_with_is_typed_gap_on_enum_path(tmp_path: Path) -> None:
    path = tmp_path / "consumer.py"
    path.write_text(
        "def use_resource(manager):\n" "    with manager:\n" "        pass\n",
        encoding="utf-8",
    )
    row = CONSUMER.measure_file_via_enumerate(
        workspace_root=tmp_path,
        file_rel="consumer.py",
    )

    # The current door carries both the preconstruction resolution and its loud
    # construction terminal; neither is reconstructed from a family label.
    assert row["category"] == "panic"
    assert row["terminalKind"] == "construction-panic"
    assert row["functionsTotal"] == 1
    events = row["contextManagerResolutionEvents"]
    assert len(events) == 1
    assert events[0]["outcome"] == "unconstructed"
    assert events[0]["observedEventType"].endswith(".ContextManagerResolutionGapV1")
    assert row["panic"]["observedEventType"].endswith(
        ".ContextManagerResolutionConstructionGap"
    )


def test_with_census_injects_construction_context(tmp_path: Path) -> None:
    """Instrument law: census must not call bare SourceFile without context."""
    path = tmp_path / "with_open.py"
    path.write_text(
        "def use():\n" "    with open('x') as f:\n" "        pass\n",
        encoding="utf-8",
    )
    row = CONSUMER.measure_file_via_enumerate(
        workspace_root=tmp_path,
        file_rel="with_open.py",
    )

    # open is not authenticated by the provisional table. The injected context
    # therefore carries one explicit unconstructed resolution into the terminal;
    # a bare SourceFile would have no resolution event at all.
    events = row["contextManagerResolutionEvents"]
    assert len(events) == 1
    assert events[0]["outcome"] == "unconstructed"
    assert events[0]["observedEventType"].endswith(".ContextManagerResolutionGapV1")
    assert row["panic"]["observedEventType"].endswith(
        ".ContextManagerResolutionConstructionGap"
    )


def test_construction_gap_occurrence_counted_once(tmp_path: Path) -> None:
    """Reporter+throw must not double-tally (392 vs 196 class of defect).

    A With that reports then raises is ONE occurrence. Terminal panic count
    equals distinct physical With coordinates, not 2x.
    """
    path = tmp_path / "with_param.py"
    path.write_text(
        "def use(manager):\n" "    with manager:\n" "        pass\n",
        encoding="utf-8",
    )
    row = CONSUMER.measure_file_via_enumerate(
        workspace_root=tmp_path,
        file_rel="with_param.py",
    )

    # One physical With coordinate produces one terminal occurrence. The
    # reporter and the thrown panic must not produce two copies of that locus.
    panics = row["constructionPanics"]
    assert len(panics) == 1
    assert len({panic["coordinate"] for panic in panics}) == 1
    assert row["blocking_terminal_count"] == 1
    assert len(row["contextManagerResolutionEvents"]) == 1


def test_backend_defect_keys_split_cm_and_call_demand() -> None:
    """Demand/resolution BackendDefects are hygiene axes, not construction R."""
    module = _load("control_effect_recensus")
    cm = module._backend_defect_key(
        "BackendDefect: enrolled context-manager demand missing from resolution table"
    )
    call = module._backend_defect_key(
        "BackendDefect: enrolled call demand missing from resolution table"
    )
    other = module._backend_defect_key("BackendDefect: something else")
    assert cm == "BackendDefect:cm-demand-missing-from-resolution"
    assert call == "BackendDefect:call-demand-missing-from-resolution"
    assert cm != call
    assert other.startswith("BackendDefect:")
    assert other not in {cm, call}
