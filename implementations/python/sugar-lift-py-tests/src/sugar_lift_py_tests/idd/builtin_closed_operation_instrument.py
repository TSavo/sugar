"""R_builtin_closed_operation — structural floor for name/vendor construction doors.

Closed semantic operations are minted on the Python floor via
``callable_application_with`` and content-addressed witnesses. Construction
must not decide builtin / effect-boundary meaning by matching display
spellings or generic bool verdict names.

## Detection predicate (what the instrument inspects)

Let *T* be the AST of each production ``*.py`` under *root*, excluding paths
whose first segment after ``sugar_lift_py_tests`` is in
``{audit_only, idd, kit_rpc}`` and excluding ``lift_rpc.py``.

### Vendor CM coordinate spelling

A string *s* is a vendor CM coordinate iff:

    split(s, ".") = (p0, …, pk)  with  k ≥ 1
    ∧  every pi is a Python identifier
    ∧  p0 ∈ VENDOR_CM_ROOTS

where ``VENDOR_CM_ROOTS = {pytest, contextlib, unittest, warnings}``.

This is **identity of a dotted identifier path**, not substring membership.
So ``"pytest.warns"`` matches; ``"xpytest.raisesy"`` does not.

### name_or_vendor_gates

An ``ast.Compare`` is an offender iff any of the following holds (structural):

1. **Vendor CM coordinate** — left or any comparator is a string Constant that
   is a vendor CM coordinate, **or** a ``Name``/``Attribute`` chain whose
   qualified name is a vendor CM coordinate.
2. **type_name membership** — op is ``In``/``NotIn`` and left is ``Name(id='type_name')``.
3. **exception_name attribute** — any compare operand is ``Attribute(..., attr='exception_name')``.
4. **unbound lexical ``.id`` vs string** — any operand is ``Attribute(..., attr='id')``
   and any operand is a string Constant (``func.id == "importorskip"``).
5. **name vs matcher.name** — one operand is ``Name(id='name')`` (or multiple
   ``.name`` attrs) and another is ``Attribute(..., attr='name')``.

Additionally (non-Compare logo tables / match):

6. ``ast.Match`` case whose pattern is ``MatchValue`` of a vendor CM coordinate
   (Constant or Attribute/Name chain), including ``MatchOr`` / nested ``MatchAs``.
7. ``ast.Dict`` key / ``ast.Set`` element that is a vendor CM coordinate.
8. ``ast.Tuple`` / ``ast.List`` whose **every** element is a vendor CM coordinate
   (dispatch seed tables).

### construction_side_doors

One offender per function (sync/async) that contains ≥1 ``name_or_vendor_gates``
offender in its body.

### generic_builtin_verdicts

``ast.Compare`` that mentions a ``Name`` whose ``id`` is **exactly**
``builtin_result`` or ``builtin_verdict`` **and** a bool Constant.
(Not substring on the name.)

### panic_catches

``ast.ExceptHandler`` whose exception type AST names (``Name.id`` or trailing
``Attribute.attr``, including tuple arms) include exact ``ConstructionPanic``
or a name ending with ``Panic``. Not ``"Panic" in ast.unparse(...)``.

## What the instrument cannot detect

- Runtime-built strings / non-constant f-strings.
- Vendor tables loaded from JSON outside the AST.
- True floor routing that never spells a name gate (invisible by design).

## Ladder / retirement

Type system cannot ban open vendor string grammar. Construction does not yet
have one door that refuses name gates. Panic is for runtime gaps. This auditor
is larval.

**Delete this shell when** name/vendor construction gates are unrepresentable
(typed BuiltinCoordinate / sole floor application path) and residual R is
stable zero.

SCOREBOARD_AUTHORITY = False
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


VENDOR_CM_ROOTS: frozenset[str] = frozenset(
    {
        "pytest",
        "contextlib",
        "unittest",
        "warnings",
    }
)

_GENERIC_BUILTIN_VERDICT_NAMES: frozenset[str] = frozenset(
    {
        "builtin_result",
        "builtin_verdict",
    }
)

_SKIP_LANES: frozenset[str] = frozenset({"audit_only", "idd", "kit_rpc"})


@dataclass(frozen=True)
class BuiltinClosedOperationOffender:
    axis: str
    path: str
    line: int
    observed: str
    replacement: str


@dataclass(frozen=True)
class BuiltinClosedOperationReport:
    offenders: tuple[BuiltinClosedOperationOffender, ...]

    @property
    def r(self) -> dict[str, int]:
        axes = (
            "construction_side_doors",
            "generic_builtin_verdicts",
            "name_or_vendor_gates",
            "panic_catches",
        )
        return {axis: sum(row.axis == axis for row in self.offenders) for axis in axes}


def is_vendor_cm_coordinate_spelling(value: str) -> bool:
    """True iff *value* is a dotted identifier path under VENDOR_CM_ROOTS.

    Structural identity — not substring.
    """
    if not isinstance(value, str) or not value:
        return False
    parts = value.split(".")
    if len(parts) < 2:
        return False
    if not all(part.isidentifier() for part in parts):
        return False
    return parts[0] in VENDOR_CM_ROOTS


def qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = qualified_name(node.value)
        if prefix is None:
            return None
        return f"{prefix}.{node.attr}"
    return None


def exception_type_names(type_node: ast.AST | None) -> frozenset[str]:
    if type_node is None:
        return frozenset({"<bare>"})
    names: set[str] = set()

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                walk(elt)

    walk(type_node)
    return frozenset(names)


def is_panic_type_name(name: str) -> bool:
    return name == "ConstructionPanic" or (
        name != "<bare>" and name.endswith("Panic")
    )


def collect_builtin_closed_operation_report(
    root: Path,
) -> BuiltinClosedOperationReport:
    offenders: list[BuiltinClosedOperationOffender] = []
    for path in sorted(root.rglob("*.py")):
        relative_path = path.relative_to(root)
        parts = relative_path.parts
        if "sugar_lift_py_tests" in parts:
            package_index = parts.index("sugar_lift_py_tests")
            lane = parts[package_index + 1 : package_index + 2]
            if lane and lane[0] in _SKIP_LANES:
                continue
            if relative_path.name == "lift_rpc.py":
                continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        relative = str(relative_path)
        visitor = _Visitor(relative)
        visitor.visit(tree)
        offenders.extend(visitor.offenders)
    return BuiltinClosedOperationReport(tuple(offenders))


class _Visitor(ast.NodeVisitor):
    """Structural detector for spelling-gates outside authenticated coordinates."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.offenders: list[BuiltinClosedOperationOffender] = []
        self._function_stack: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        self._side_door_functions: set[int] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Name-keyed suppress API is itself the residual shell (method body may
        # only mention self.exception_names; the method *name* is the crime).
        if node.name == "suppresses_exception":
            self._add(
                "name_or_vendor_gates",
                node,
                f"def {node.name}",
                "match exception_type_coordinate against ExitSuppressionContract "
                "coordinates minted at the suppresses() door; never suppress by name",
            )
        self._function_stack.append(node)
        self.generic_visit(node)
        self._function_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Residual after cluster-5 Suppresses fix: ExitSuppressionContract still
        # decided suppress via suppresses_exception(str) / exception_names.
        # Those shells are deleted; any reintroduction is a name_or_vendor_gate.
        # Retirement of this detector arm: when no production Attribute load of
        # either name remains AND the type system forbids constructing a
        # name-keyed suppress contract (coordinates-only field), delete this arm.
        if node.attr in {"suppresses_exception", "exception_names"}:
            self._add(
                "name_or_vendor_gates",
                node,
                ast.unparse(node),
                "match exception_type_coordinate against ExitSuppressionContract "
                "coordinates minted at the suppresses() door; never suppress by name",
            )
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        rendered = ast.unparse(node)
        if self._is_spelling_gate_compare(node):
            self._flag_vendor_gate(node, rendered)
        if self._compare_is_generic_builtin_verdict(node):
            self._add(
                "generic_builtin_verdicts",
                node,
                rendered,
                "construct the closed semantic operation and result on the Python floor",
            )
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        for case in node.cases:
            if self._pattern_is_vendor_coordinate(case.pattern):
                self._flag_vendor_gate(
                    case.pattern,
                    f"match-case {ast.unparse(case.pattern)}",
                )
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key in node.keys:
            if key is not None and self._node_is_vendor_coordinate(key):
                self._flag_vendor_gate(key, f"dict-key {ast.unparse(key)}")
        self.generic_visit(node)

    def visit_Set(self, node: ast.Set) -> None:
        for elt in node.elts:
            if self._node_is_vendor_coordinate(elt):
                self._flag_vendor_gate(elt, f"set-elt {ast.unparse(elt)}")
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple) -> None:
        if node.elts and all(self._node_is_vendor_coordinate(elt) for elt in node.elts):
            for elt in node.elts:
                self._flag_vendor_gate(elt, f"tuple-elt {ast.unparse(elt)}")
        self.generic_visit(node)

    def visit_List(self, node: ast.List) -> None:
        if node.elts and all(self._node_is_vendor_coordinate(elt) for elt in node.elts):
            for elt in node.elts:
                self._flag_vendor_gate(elt, f"list-elt {ast.unparse(elt)}")
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        for name in exception_type_names(node.type):
            if is_panic_type_name(name):
                self._add(
                    "panic_catches",
                    node,
                    name,
                    "leave unsupported floor construction loud; never catch its panic",
                )
                break
        self.generic_visit(node)

    def _flag_vendor_gate(self, node: ast.AST, observed: str) -> None:
        self._add(
            "name_or_vendor_gates",
            node,
            observed,
            "route the authenticated builtin coordinate through the Python floor",
        )
        if self._function_stack:
            function = self._function_stack[-1]
            key = id(function)
            if key not in self._side_door_functions:
                self._side_door_functions.add(key)
                self._add(
                    "construction_side_doors",
                    function,
                    function.name,
                    "use the sole floor callable_application_with construction path",
                )

    def _node_is_vendor_coordinate(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return is_vendor_cm_coordinate_spelling(node.value)
        qn = qualified_name(node)
        return qn is not None and is_vendor_cm_coordinate_spelling(qn)

    def _is_spelling_gate_compare(self, node: ast.Compare) -> bool:
        """True when this compare decides by display spelling, not a coordinate."""
        operands = (node.left, *node.comparators)

        # Vendor CM coordinates (structural path identity — NOT substring).
        if any(self._node_is_vendor_coordinate(operand) for operand in operands):
            return True

        # type_name in {…} / type_name in SOME_FROZENSET — builtin shadowing lie.
        if any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            if isinstance(node.left, ast.Name) and node.left.id == "type_name":
                return True

        attr_names = {
            operand.attr
            for operand in operands
            if isinstance(operand, ast.Attribute)
        }
        has_str_constant = any(
            isinstance(operand, ast.Constant) and isinstance(operand.value, str)
            for operand in operands
        )

        # effect.exception_name == "StopIteration" (and any == on that attr).
        if "exception_name" in attr_names:
            return True

        # func.id == "importorskip" — unbound lexical text vs string.
        if "id" in attr_names and has_str_constant:
            return True

        # name == matcher.name — spelling equality of names.
        name_attrs = [
            operand
            for operand in operands
            if isinstance(operand, ast.Attribute) and operand.attr == "name"
        ]
        name_names = [
            operand
            for operand in operands
            if isinstance(operand, ast.Name) and operand.id == "name"
        ]
        if name_attrs and (name_names or len(name_attrs) >= 2):
            return True

        return False

    def _pattern_is_vendor_coordinate(self, pattern: ast.pattern) -> bool:
        if isinstance(pattern, ast.MatchValue):
            return self._node_is_vendor_coordinate(pattern.value)
        if isinstance(pattern, ast.MatchOr):
            return any(self._pattern_is_vendor_coordinate(p) for p in pattern.patterns)
        if isinstance(pattern, ast.MatchAs) and pattern.pattern is not None:
            return self._pattern_is_vendor_coordinate(pattern.pattern)
        if isinstance(pattern, ast.MatchSequence):
            return any(self._pattern_is_vendor_coordinate(p) for p in pattern.patterns)
        if isinstance(pattern, ast.MatchMapping):
            return any(
                isinstance(k, ast.Constant)
                and isinstance(k.value, str)
                and is_vendor_cm_coordinate_spelling(k.value)
                for k in pattern.keys
            )
        return False

    def _compare_is_generic_builtin_verdict(self, node: ast.Compare) -> bool:
        names = {
            child.id for child in ast.walk(node) if isinstance(child, ast.Name)
        }
        if not (names & _GENERIC_BUILTIN_VERDICT_NAMES):
            return False
        bools = {
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant) and type(child.value) is bool
        }
        return bool(bools)

    def _add(self, axis: str, node: ast.AST, observed: str, replacement: str) -> None:
        self.offenders.append(
            BuiltinClosedOperationOffender(
                axis=axis,
                path=self.path,
                line=getattr(node, "lineno", 0),
                observed=observed,
                replacement=replacement,
            )
        )
