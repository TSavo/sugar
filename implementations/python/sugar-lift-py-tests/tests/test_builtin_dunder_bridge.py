from __future__ import annotations

import ast

import pytest
from factory_reduce import fol

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.factory import factory_panic
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, make_var, num, str_const
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.temporal import TemporalContext


def _ctx_for_module(
    source: str,
    *,
    import_aliases: dict[str, str] | None = None,
    from_imports: dict[str, tuple[str, str]] | None = None,
) -> FactoryBuildContext:
    module = ast.parse(source)
    resolver = {
        stmt.name: stmt
        for stmt in module.body
        if isinstance(stmt, (ast.FunctionDef, ast.ClassDef))
    }
    return FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        name_resolver=resolver,
        import_aliases=import_aliases or {},
        from_imports=from_imports or {},
    )


def _reduce_expr(
    source: str,
    expr: str,
    *,
    import_aliases: dict[str, str] | None = None,
    from_imports: dict[str, tuple[str, str]] | None = None,
):
    ctx = _ctx_for_module(
        source,
        import_aliases=import_aliases,
        from_imports=from_imports,
    )
    node = ast.parse(expr, mode="eval").body
    return complete_value(
        _reduce_outcome(
            source,
            expr,
            import_aliases=import_aliases,
            from_imports=from_imports,
        ),
        owner="builtin dunder bridge",
    )


def _reduce_outcome(
    source: str,
    expr: str,
    *,
    import_aliases: dict[str, str] | None = None,
    from_imports: dict[str, tuple[str, str]] | None = None,
    binds: dict[str, object] | None = None,
):
    ctx = _ctx_for_module(
        source,
        import_aliases=import_aliases,
        from_imports=from_imports,
    )
    if binds:
        temporal = TemporalContext.empty()
        for name, value in binds.items():
            temporal = temporal.bind_value(name, value)
        ctx = ctx.with_temporal(temporal)
    node = ast.parse(expr, mode="eval").body
    return ctx.build_body(node, SugarRole.TERM).reduce(ctx)


def _object_identity(class_name: str, blame: str):
    return ctor("py.object.identity", [str_const(class_name), str_const(blame)])


def test_len_builtin_projects_to_dunder_method_bridge() -> None:
    source = """\
class Box:
    def __len__(self):
        return 1
"""

    value = _reduce_expr(source, "len(Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__len__"
    assert fol(floor_to_term(value, owner="len dunder bridge")) == fol(
        ctor("call:Box.__len__", [_object_identity("Box", "t.py:1:4")])
    )


def test_len_builtin_dunder_can_drive_array_index_value_demand() -> None:
    source = """\
class Box:
    def __len__(self):
        return 1
"""

    value = _reduce_expr(source, "[10, 20, 30][len(Box())]")

    assert value == TermValue(20)


def test_getattr_builtin_literal_name_matches_attribute_lookup() -> None:
    source = """\
class Box:
    def __init__(self):
        self.value = 2
"""

    via_getattr = _reduce_expr(source, "getattr(Box(), 'value')")
    via_attribute = _reduce_expr(source, "Box().value")

    assert via_getattr == via_attribute == TermValue(2)


def test_getattr_builtin_literal_name_bad_twin_uses_requested_attribute() -> None:
    source = """\
class Box:
    def __init__(self):
        self.left = 1
        self.right = 2
"""

    left = _reduce_expr(source, "getattr(Box(), 'left')")
    right = _reduce_expr(source, "getattr(Box(), 'right')")

    assert left == TermValue(1)
    assert right == TermValue(2)


def test_getattr_builtin_runtime_name_is_typed_runtime_effect() -> None:
    outcome = _reduce_outcome(
        "",
        "getattr(obj, 'setall_' + sfx)",
        binds={
            "obj": SymbolicValue(make_var("obj")),
            "sfx": SymbolicValue(make_var("sfx")),
        },
    )

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "getattr runtime boundary" in outcome.effect.reason
    assert "attribute name expression" in outcome.effect.reason


def test_getattr_builtin_opaque_receiver_is_typed_runtime_effect() -> None:
    outcome = _reduce_outcome(
        "",
        "getattr(obj, 'value')",
        binds={"obj": SymbolicValue(make_var("obj"))},
    )

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "getattr runtime boundary" in outcome.effect.reason
    assert "receiver reduced to SymbolicValue" in outcome.effect.reason


def test_getattr_builtin_as_callee_propagates_runtime_effect() -> None:
    outcome = _reduce_outcome(
        "",
        "getattr(obj, 'setall_' + sfx)(1)",
        binds={
            "obj": SymbolicValue(make_var("obj")),
            "sfx": SymbolicValue(make_var("sfx")),
        },
    )

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "getattr runtime boundary" in outcome.effect.reason


def test_hash_builtin_projects_to_dunder_method_bridge() -> None:
    source = """\
class Box:
    def __hash__(self):
        return 1
"""

    value = _reduce_expr(source, "hash(Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__hash__"
    assert fol(floor_to_term(value, owner="hash dunder bridge")) == fol(
        ctor("call:Box.__hash__", [_object_identity("Box", "t.py:1:5")])
    )


def test_divmod_builtin_projects_left_object_to_dunder_method_bridge() -> None:
    source = """\
class Box:
    def __divmod__(self, other):
        return 1
"""

    value = _reduce_expr(source, "divmod(Box(), 2)")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__divmod__"
    assert fol(floor_to_term(value, owner="divmod dunder bridge")) == fol(
        ctor(
            "call:Box.__divmod__",
            [
                _object_identity("Box", "t.py:1:7"),
                num(2),
            ],
        )
    )


def test_divmod_builtin_projects_right_object_to_reflected_dunder_method_bridge() -> (
    None
):
    source = """\
class Box:
    def __rdivmod__(self, other):
        return 1
"""

    value = _reduce_expr(source, "divmod(2, Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__rdivmod__"
    assert fol(floor_to_term(value, owner="reflected divmod dunder bridge")) == fol(
        ctor(
            "call:Box.__rdivmod__",
            [
                _object_identity("Box", "t.py:1:10"),
                num(2),
            ],
        )
    )


@pytest.mark.parametrize(
    ("builtin_name", "method_name"),
    [
        ("abs", "__abs__"),
        ("round", "__round__"),
        ("floor", "__floor__"),
        ("ceil", "__ceil__"),
        ("trunc", "__trunc__"),
    ],
)
def test_unary_numeric_builtin_projects_to_dunder_method_bridge(
    builtin_name: str, method_name: str
) -> None:
    source = f"""\
class Box:
    def {method_name}(self):
        return 1
"""

    value = _reduce_expr(source, f"{builtin_name}(Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == f"Box.{method_name}"
    assert len(value.arg_values) == 1


@pytest.mark.parametrize(
    ("builtin_name", "method_name"),
    [
        ("abs", "__abs__"),
        ("round", "__round__"),
        ("floor", "__floor__"),
        ("ceil", "__ceil__"),
        ("trunc", "__trunc__"),
    ],
)
def test_unary_numeric_builtin_dunder_can_drive_array_index_value_demand(
    builtin_name: str, method_name: str
) -> None:
    source = f"""\
class Box:
    def {method_name}(self):
        return 1
"""

    value = _reduce_expr(source, f"[10, 20, 30][{builtin_name}(Box())]")

    assert value == TermValue(20)


def test_imported_math_floor_stays_external_bridge() -> None:
    source = """\
class Box:
    def __floor__(self):
        return 1
"""

    value = _reduce_expr(
        source,
        "floor(Box())",
        from_imports={"floor": ("math", "floor")},
    )

    assert isinstance(value, SymbolicValue)
    assert fol(value.term) == fol(
        ctor("call:math.floor", [_object_identity("Box", "t.py:1:6")])
    )


@pytest.mark.parametrize(
    ("call_expr", "method_name", "object_blame", "import_aliases"),
    [
        ("int(Box())", "__int__", "t.py:1:4", None),
        ("float(Box())", "__float__", "t.py:1:6", None),
        ("complex(Box())", "__complex__", "t.py:1:8", None),
        ("operator.index(Box())", "__index__", "t.py:1:15", {"operator": "operator"}),
    ],
)
def test_numeric_conversion_builtin_projects_to_dunder_method_bridge(
    call_expr: str,
    method_name: str,
    object_blame: str,
    import_aliases: dict[str, str] | None,
) -> None:
    import_prefix = "import operator\n\n" if import_aliases else ""
    source = f"""\
{import_prefix}\
class Box:
    def {method_name}(self):
        return 1
"""

    value = _reduce_expr(source, call_expr, import_aliases=import_aliases)

    assert isinstance(value, CallSiteValue)
    assert value.target_name == f"Box.{method_name}"
    assert fol(
        floor_to_term(value, owner=f"{method_name} numeric conversion bridge")
    ) == fol(ctor(f"call:Box.{method_name}", [_object_identity("Box", object_blame)]))


@pytest.mark.parametrize(
    ("call_expr", "method_name", "import_aliases"),
    [
        ("int(Box())", "__int__", None),
        ("operator.index(Box())", "__index__", {"operator": "operator"}),
    ],
)
def test_numeric_conversion_dunder_can_drive_array_index_value_demand(
    call_expr: str,
    method_name: str,
    import_aliases: dict[str, str] | None,
) -> None:
    import_prefix = "import operator\n\n" if import_aliases else ""
    source = f"""\
{import_prefix}\
class Box:
    def {method_name}(self):
        return 1
"""

    value = _reduce_expr(
        source,
        f"[10, 20, 30][{call_expr}]",
        import_aliases=import_aliases,
    )

    assert value == TermValue(20)


def test_imported_builtin_like_call_stays_external_bridge() -> None:
    source = """\
class Box:
    def __len__(self):
        return 1
"""

    value = _reduce_expr(
        source,
        "external_len(Box())",
        from_imports={"external_len": ("vendor", "len")},
    )

    assert isinstance(value, SymbolicValue)
    assert fol(value.term) == fol(
        ctor("call:vendor.len", [_object_identity("Box", "t.py:1:13")])
    )


def test_imported_builtin_like_same_name_call_stays_external_bridge() -> None:
    source = """\
class Box:
    def __len__(self):
        return 1
"""

    value = _reduce_expr(
        source,
        "len(Box())",
        from_imports={"len": ("vendor", "len")},
    )

    assert isinstance(value, SymbolicValue)
    assert fol(value.term) == fol(
        ctor("call:vendor.len", [_object_identity("Box", "t.py:1:4")])
    )
