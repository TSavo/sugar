"""Value-pin admission for module-level bindings.

A value participates in lifted FOL only if it is "inside the house":
immutable by construction, or confessed by the author. Names never pin;
values do. The pinned term is the value at the use site, byte-identical
to the same literal written inline; the binding name is provenance only.

Admission, not detection: an inadmissible candidate produces NO pin plus
a loud refusal record -- never a wrong row, never a silent drop. Totality
holds by construction: candidates == admitted + refused.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Iterator

from .ir import (
    Json,
    bool_const,
    bytes_const,
    complex_const,
    ctor,
    ellipsis_const,
    float_const,
    int_const,
    none_const,
    str_const,
)

VALUE_PIN_REFUSAL_KIND = "value-pin-refused"
ENUM_PIN_REFUSAL_KIND = "enum-pin-refused"
FINAL_CONFESSION = "typing.Final"

# Scope boundaries: bindings inside these do not bind module names.
# (Plain assignment in a function is a local; `global`-declaring functions
# are handled separately and conservatively below.)
_SCOPE_BOUNDARY_NODES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)

_TRY_NODES: tuple = (ast.Try, ast.TryStar) if hasattr(ast, "TryStar") else (ast.Try,)
_TYPE_ALIAS_NODE = getattr(ast, "TypeAlias", None)


@dataclass(frozen=True)
class ValuePin:
    name: str
    term: Json
    line: int
    confession: str | None


@dataclass(frozen=True)
class MutableGlobalPin:
    name: str
    kind: str
    term: Json
    line: int
    col: int


@dataclass
class ValuePinScan:
    pins: dict[str, ValuePin] = field(default_factory=dict)
    refusals: list[Json] = field(default_factory=list)
    mutable_global_pins: list[MutableGlobalPin] = field(default_factory=list)
    candidates: int = 0

    def totality_holds(self) -> bool:
        return self.candidates == len(self.pins) + len(self.refusals)


class _NotAdmissible(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class _BindingEvent:
    name: str
    line: int
    description: str


@dataclass(frozen=True)
class _Candidate:
    name: str
    value: ast.expr
    line: int
    confession: str | None
    col: int = 0


def scan_module_value_pins(tree: ast.Module) -> ValuePinScan:
    scan = ValuePinScan()
    candidates = _collect_candidates(tree)
    events = list(_binding_events(tree))
    global_decls = _global_declarations(tree)
    events_by_name: dict[str, list[_BindingEvent]] = {}
    for event in events:
        events_by_name.setdefault(event.name, []).append(event)

    scan.candidates = len(candidates)
    for candidate in candidates.values():
        refusal_reason = _admission_failure(
            candidate,
            events_by_name.get(candidate.name, []),
            global_decls.get(candidate.name),
        )
        if refusal_reason is not None:
            scan.refusals.append(_pin_refusal(candidate, refusal_reason))
            continue
        try:
            term = _render_value_term(candidate.value)
        except _NotAdmissible as exc:
            scan.refusals.append(_pin_refusal(candidate, exc.reason))
            mutable_kind = _direct_mutable_kind(candidate.value)
            if mutable_kind is not None:
                scan.mutable_global_pins.append(
                    MutableGlobalPin(
                        name=candidate.name,
                        kind=mutable_kind,
                        term=mutable_global_pin_term(candidate.name, mutable_kind),
                        line=candidate.line,
                        col=candidate.col,
                    )
                )
            continue
        scan.pins[candidate.name] = ValuePin(
            name=candidate.name,
            term=term,
            line=candidate.line,
            confession=candidate.confession,
        )
    _scan_enum_member_pins(tree, scan)
    assert scan.totality_holds()
    return scan


_VALUE_ENUM_BASES = ("IntEnum", "StrEnum")
_PLAIN_ENUM_BASES = ("Enum", "Flag", "IntFlag")


def _enum_base_kind(node: ast.ClassDef) -> Optional[str]:
    for base in node.bases:
        name = None
        if isinstance(base, ast.Name):
            name = base.id
        elif isinstance(base, ast.Attribute):
            name = base.attr
        if name in _VALUE_ENUM_BASES:
            return "value"
        if name in _PLAIN_ENUM_BASES:
            return "plain"
    return None


def _scan_enum_member_pins(tree: ast.Module, scan: ValuePinScan) -> None:
    """Class-attribute pins for enum members, keyed 'ClassName.MEMBER'.

    The == dispatch gate decides the scope: a plain Enum member is NOT
    equal to its value (Color.RED == 1 is False), so pinning it to the
    literal would be a wrong term -- plain-Enum members REFUSE by name.
    IntEnum/StrEnum members compare as their values, so they pin. Enum's
    metaclass forbids member reassignment at runtime, making these the
    strongest pins in the language; the scan still refuses on any
    syntactic write to ClassName.MEMBER or cls.MEMBER in the module
    (belt and suspenders)."""
    attr_writes = _class_attr_writes(tree)
    for stmt in tree.body:
        if not isinstance(stmt, ast.ClassDef):
            continue
        kind = _enum_base_kind(stmt)
        if kind is None:
            continue
        for class_stmt in stmt.body:
            if not (
                isinstance(class_stmt, ast.Assign)
                and len(class_stmt.targets) == 1
                and isinstance(class_stmt.targets[0], ast.Name)
            ):
                continue
            member = class_stmt.targets[0].id
            if member.startswith("_"):
                continue
            dotted = f"{stmt.name}.{member}"
            candidate = _Candidate(
                name=dotted,
                value=class_stmt.value,
                line=class_stmt.lineno,
                confession=f"enum.{kind}",
            )
            scan.candidates += 1
            if stmt.decorator_list:
                # A decorated ClassDef is NOT the runtime class: the name
                # binds whatever the decorator returns (caught live
                # 2026-06-12: a class decorator swapping the enum ran
                # Color.RED == 99 while the scan pinned 1 — a wrong term
                # byte-identical to an inline literal). Refuse by name.
                scan.refusals.append(
                    _pin_refusal(
                        candidate,
                        f"class decorator on {stmt.name}: the ClassDef is "
                        "not the runtime class; member values cannot be "
                        "read from the body",
                    )
                )
                continue
            rebound = dotted in attr_writes or f"cls.{member}" in attr_writes
            if kind == "plain":
                scan.refusals.append(
                    _pin_refusal(
                        candidate,
                        "plain Enum member: use IntEnum or StrEnum for value pinning",
                        kind=ENUM_PIN_REFUSAL_KIND,
                    )
                )
            elif rebound:
                scan.refusals.append(
                    _pin_refusal(
                        candidate,
                        f"rebound: attribute write to {dotted} at line "
                        f"{attr_writes.get(dotted, attr_writes.get(f'cls.{member}'))}",
                    )
                )
            else:
                try:
                    term = _render_value_term(class_stmt.value)
                except _NotAdmissible as exc:
                    scan.refusals.append(_pin_refusal(candidate, exc.reason))
                else:
                    scan.pins[dotted] = ValuePin(
                        name=dotted,
                        term=term,
                        line=class_stmt.lineno,
                        confession=f"enum.{kind}",
                    )
            # `.value` is a stable attribute access on ANY Enum member,
            # regardless of dispatch flavor: it always returns the
            # underlying literal, byte-identical to what was written after
            # `=`. The == dispatch gate that forces plain-Enum members to
            # refuse at the bare member name does not apply to `.value` --
            # so this pins even for plain Enum/Flag members, as long as the
            # member itself was not rebound.
            value_dotted = f"{dotted}.value"
            value_candidate = _Candidate(
                name=value_dotted,
                value=class_stmt.value,
                line=class_stmt.lineno,
                confession=f"enum.{kind}.value",
            )
            scan.candidates += 1
            if rebound:
                scan.refusals.append(
                    _pin_refusal(
                        value_candidate,
                        f"rebound: attribute write to {dotted} at line "
                        f"{attr_writes.get(dotted, attr_writes.get(f'cls.{member}'))}",
                    )
                )
                continue
            try:
                value_term = _render_value_term(class_stmt.value)
            except _NotAdmissible as exc:
                scan.refusals.append(_pin_refusal(value_candidate, exc.reason))
                continue
            scan.pins[value_dotted] = ValuePin(
                name=value_dotted,
                term=value_term,
                line=class_stmt.lineno,
                confession=f"enum.{kind}.value",
            )


def _class_attr_writes(tree: ast.Module) -> dict:
    """Every syntactic write target of the shape <Name>.<attr> anywhere in
    the module (assignment, augmented assignment, deletion), keyed
    'Name.attr' -> first line. Covers ClassName.MEMBER = ... and
    cls.MEMBER = ... punctures."""
    writes: dict = {}
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        elif isinstance(node, ast.Delete):
            targets = node.targets
        for t in targets:
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name):
                writes.setdefault(f"{t.value.id}.{t.attr}", node.lineno)
    return writes


def _pin_refusal(
    candidate: _Candidate, reason: str, *, kind: str = VALUE_PIN_REFUSAL_KIND
) -> Json:
    if candidate.confession is not None and _is_rebinding_reason(reason):
        reason = (
            f"vendor contradicted their own {candidate.confession} "
            f"confession: {reason}"
        )
    return {
        "kind": kind,
        "function": None,
        "line": candidate.line,
        "name": candidate.name,
        "reason": reason,
    }


def mutable_global_pin_term(name: str, kind: str) -> Json:
    return ctor("python:mutable_global_pin", str_const(name), str_const(kind))


def mutable_global_pin_opacity_entry(
    pin: MutableGlobalPin, *, source_path: str
) -> Json:
    return {
        "file": source_path,
        "line": pin.line,
        "col": pin.col,
        "name": pin.name,
        "kind": pin.kind,
        "term": pin.term,
    }


def _is_rebinding_reason(reason: str) -> bool:
    return (
        reason.startswith("rebound")
        or reason.startswith("deleted")
        or reason.startswith("global declaration")
    )


def _admission_failure(
    candidate: _Candidate,
    events: list[_BindingEvent],
    global_decl_line: int | None,
) -> str | None:
    if global_decl_line is not None:
        return (
            "global declaration in nested scope at line "
            f"{global_decl_line} can rebind the name at runtime"
        )
    binding_events = [
        e for e in events if e.line != candidate.line or e.description != "assignment"
    ]
    own_events = [
        e for e in events if e.line == candidate.line and e.description == "assignment"
    ]
    if len(own_events) != 1:
        # The candidate's own binding statement must be exactly one plain
        # assignment event; anything else is a scan bookkeeping failure and
        # must refuse rather than guess.
        return "rebound: binding site is not a single plain assignment"
    if binding_events:
        first = binding_events[0]
        return f"rebound: {first.description} at line {first.line}"
    return None


def _collect_candidates(tree: ast.Module) -> dict[str, _Candidate]:
    candidates: dict[str, _Candidate] = {}
    duplicate_names: set[str] = set()
    for stmt in tree.body:
        name_node: ast.Name | None = None
        value: ast.expr | None = None
        confession: str | None = None
        if isinstance(stmt, ast.Assign):
            if len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                name_node = stmt.targets[0]
                value = stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, ast.Name) and stmt.value is not None:
                name_node = stmt.target
                value = stmt.value
                if _is_final_annotation(stmt.annotation):
                    confession = FINAL_CONFESSION
        if name_node is None or value is None:
            continue
        if not _is_literal_shaped(value):
            # Not constructed from written literals: never a candidate.
            # No row was ever possible, so no refusal is owed.
            continue
        if name_node.id in candidates:
            duplicate_names.add(name_node.id)
            continue
        candidates[name_node.id] = _Candidate(
            name=name_node.id,
            value=value,
            line=stmt.lineno,
            confession=confession,
            col=name_node.col_offset,
        )
    # A duplicated candidate name surfaces through the binding-event scan
    # (two assignment events), so the first occurrence remains the candidate
    # and the rebinding refuses it.
    _ = duplicate_names
    return candidates


def _is_final_annotation(annotation: ast.expr) -> bool:
    target = annotation
    if isinstance(target, ast.Subscript):
        target = target.value
    if isinstance(target, ast.Name):
        return target.id == "Final"
    if isinstance(target, ast.Attribute):
        return target.attr == "Final"
    return False


def _is_literal_shaped(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return isinstance(node.operand, ast.Constant)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_literal_shaped(element) for element in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            key is not None and _is_literal_shaped(key) and _is_literal_shaped(val)
            for key, val in zip(node.keys, node.values)
        )
    return False


def _direct_mutable_kind(node: ast.expr) -> str | None:
    if isinstance(node, ast.List):
        return "list"
    if isinstance(node, ast.Dict):
        return "dict"
    if isinstance(node, ast.Set):
        return "set"
    return None


def _render_value_term(node: ast.expr) -> Json:
    """Render an admissible immutable literal to the same term shape the
    emitter produces for the literal written inline. That identity IS the
    pin: a pinned name is indistinguishable from its value."""
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool):
            return bool_const(value)
        if isinstance(value, int):
            return int_const(value)
        if isinstance(value, str):
            return str_const(value)
        if isinstance(value, float):
            return float_const(value)
        if isinstance(value, bytes):
            return bytes_const(value)
        if isinstance(value, complex):
            return complex_const(value.real, value.imag)
        if value is Ellipsis:
            return ellipsis_const()
        if value is None:
            return none_const()
        raise _NotAdmissible(f"no IR term shape for {type(value).__name__} constants")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = node.operand
        if isinstance(operand, ast.Constant) and type(operand.value) is int:
            value = operand.value
            if isinstance(node.op, ast.USub):
                value = -value
            return int_const(value)
        raise _NotAdmissible("unsupported unary literal")
    if isinstance(node, ast.Tuple):
        return ctor(
            "python:tuple",
            *[_render_value_term(element) for element in node.elts],
        )
    if isinstance(node, (ast.List, ast.Set, ast.Dict)):
        kind = type(node).__name__.lower()
        raise _NotAdmissible(f"mutable value ({kind}) cannot pin")
    raise _NotAdmissible(f"unsupported value shape: {type(node).__name__}")


def _binding_events(tree: ast.Module) -> Iterator[_BindingEvent]:
    """Every module-scope binding event, exhaustively.

    Walks the module statement tree, recursing through compound statements
    (if/for/while/try/with/match bodies bind module names directly) but
    stopping at scope boundaries (function/class/lambda/comprehension
    bindings are not module bindings)."""
    for stmt in _iter_module_scope_statements(tree.body):
        yield from _statement_binding_events(stmt)


def _iter_module_scope_statements(stmts: list[ast.stmt]) -> Iterator[ast.stmt]:
    for stmt in stmts:
        yield stmt
        if isinstance(stmt, _SCOPE_BOUNDARY_NODES):
            continue
        for child_list in _child_statement_lists(stmt):
            yield from _iter_module_scope_statements(child_list)


def _child_statement_lists(stmt: ast.stmt) -> Iterator[list[ast.stmt]]:
    for field_name, value in ast.iter_fields(stmt):
        if isinstance(value, list):
            statements = [item for item in value if isinstance(item, ast.stmt)]
            if statements:
                yield statements
            for item in value:
                if isinstance(item, ast.ExceptHandler):
                    yield item.body
                if isinstance(item, ast.match_case):
                    yield item.body


def _statement_binding_events(stmt: ast.stmt) -> Iterator[_BindingEvent]:
    if isinstance(stmt, ast.Assign):
        for target in stmt.targets:
            for name, line in _target_names(target):
                yield _BindingEvent(name, line, "assignment")
    elif isinstance(stmt, ast.AnnAssign):
        if stmt.value is not None:
            for name, line in _target_names(stmt.target):
                yield _BindingEvent(name, line, "assignment")
    elif isinstance(stmt, ast.AugAssign):
        for name, line in _target_names(stmt.target):
            yield _BindingEvent(name, line, "augmented assignment")
    elif isinstance(stmt, ast.Delete):
        for target in stmt.targets:
            for name, line in _target_names(target):
                yield _BindingEvent(name, line, "deletion")
    elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
        for alias in stmt.names:
            bound = alias.asname or alias.name.split(".")[0]
            yield _BindingEvent(bound, stmt.lineno, "import rebinding")
    elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
        yield _BindingEvent(stmt.name, stmt.lineno, "function definition")
    elif isinstance(stmt, ast.ClassDef):
        yield _BindingEvent(stmt.name, stmt.lineno, "class definition")
    elif isinstance(stmt, (ast.For, ast.AsyncFor)):
        for name, line in _target_names(stmt.target):
            yield _BindingEvent(name, line, "for-loop target binding")
    elif isinstance(stmt, (ast.With, ast.AsyncWith)):
        for item in stmt.items:
            if item.optional_vars is not None:
                for name, line in _target_names(item.optional_vars):
                    yield _BindingEvent(name, line, "with-as binding")
    elif isinstance(stmt, _TRY_NODES):
        for handler in stmt.handlers:
            if handler.name:
                yield _BindingEvent(handler.name, handler.lineno, "except-as binding")
    elif isinstance(stmt, ast.Match):
        for case in stmt.cases:
            yield from _match_pattern_bindings(case.pattern)
    elif _TYPE_ALIAS_NODE is not None and isinstance(stmt, _TYPE_ALIAS_NODE):
        if isinstance(stmt.name, ast.Name):
            yield _BindingEvent(stmt.name.id, stmt.lineno, "type-alias definition")
    # Walrus targets anywhere in this statement's expressions, outside
    # nested scopes, bind module names.
    yield from _walrus_bindings(stmt)


def _match_pattern_bindings(pattern: ast.pattern) -> Iterator[_BindingEvent]:
    if isinstance(pattern, ast.MatchAs) and pattern.name:
        yield _BindingEvent(pattern.name, pattern.lineno, "match capture binding")
    if isinstance(pattern, ast.MatchStar) and pattern.name:
        yield _BindingEvent(pattern.name, pattern.lineno, "match capture binding")
    if isinstance(pattern, ast.MatchMapping) and pattern.rest:
        yield _BindingEvent(pattern.rest, pattern.lineno, "match capture binding")
    for child in ast.iter_child_nodes(pattern):
        if isinstance(child, ast.pattern):
            yield from _match_pattern_bindings(child)


def _walrus_bindings(stmt: ast.stmt) -> Iterator[_BindingEvent]:
    stack: list[ast.AST] = [stmt]
    while stack:
        node = stack.pop()
        if node is not stmt and isinstance(node, _SCOPE_BOUNDARY_NODES):
            continue
        if isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            yield _BindingEvent(node.target.id, node.lineno, "walrus rebinding")
        # Child statements are visited by the scope iterator themselves;
        # descending into them here would double-count their walrus events.
        stack.extend(
            child
            for child in ast.iter_child_nodes(node)
            if not isinstance(child, ast.stmt)
        )


def _target_names(target: ast.expr) -> Iterator[tuple[str, int]]:
    if isinstance(target, ast.Name):
        yield target.id, target.lineno
    elif isinstance(target, ast.Starred):
        yield from _target_names(target.value)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            yield from _target_names(element)
    # Attribute/Subscript targets mutate objects, not module name bindings.


def _global_declarations(tree: ast.Module) -> dict[str, int]:
    declarations: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            for name in node.names:
                declarations.setdefault(name, node.lineno)
    return declarations


# ── THE STRUCTURAL FLOOR ─────────────────────────────────────────────────
# The binding-event scan must be TOTAL over this interpreter's statement
# grammar, and the totality must be readable off the module rather than
# sworn by the sweep: ast.NodeVisitor's generic_visit is an asserted
# silence in structural costume. Every ast.stmt subclass the running
# interpreter knows is classified below as either BINDING-HANDLED
# (produces events in _statement_binding_events) or DECLARED-NONBINDING
# (cannot bind a module name directly; compound bodies are recursed
# structurally by the field-generic _child_statement_lists, and walrus
# expressions are scanned for EVERY statement kind regardless). A
# statement kind in NEITHER set -- a new grammar node in a future Python
# -- fails the IMPORT of this module, loudly, before any pin can be
# admitted. The audit of silence terminates here, in exhaustion ("there
# are no more nodes"), not in another oath ("we believe we got them all").


def _grammar_classes(base: type) -> frozenset:
    return frozenset(
        cls
        for name in dir(ast)
        if isinstance(cls := getattr(ast, name), type)
        and issubclass(cls, base)
        and cls is not base
    )


_BINDING_HANDLED_STMT = frozenset(
    cls
    for cls in (
        ast.Assign,
        ast.AnnAssign,
        ast.AugAssign,
        ast.Delete,
        ast.Import,
        ast.ImportFrom,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.For,
        ast.AsyncFor,
        ast.With,
        ast.AsyncWith,
        ast.Try,
        ast.Match,
        getattr(ast, "TryStar", None),
        _TYPE_ALIAS_NODE,
    )
    if cls is not None
)

_DECLARED_NONBINDING_STMT = frozenset(
    (
        ast.Expr,
        ast.Return,
        ast.Raise,
        ast.Assert,
        ast.Pass,
        ast.Break,
        ast.Continue,
        ast.If,
        ast.While,
        # Global/Nonlocal do not bind at module scope themselves; Global is
        # consumed by the dedicated _global_declarations puncture scan.
        ast.Global,
        ast.Nonlocal,
    )
)

_BINDING_HANDLED_PATTERN = frozenset((ast.MatchAs, ast.MatchStar, ast.MatchMapping))

_DECLARED_NONBINDING_PATTERN = frozenset(
    # Children are recursed generically in _match_pattern_bindings via
    # iter_child_nodes; these kinds carry no name binding of their own.
    (ast.MatchValue, ast.MatchSingleton, ast.MatchSequence, ast.MatchClass, ast.MatchOr)
)


def _unaccounted_grammar() -> dict[str, list[str]]:
    """Every grammar class the interpreter knows that the scan neither
    handles nor declares non-binding. Empty dicts are the floor holding;
    anything else is a hole that must be classified before pins can be
    trusted."""
    unaccounted: dict[str, list[str]] = {}
    stmt_holes = (
        _grammar_classes(ast.stmt) - _BINDING_HANDLED_STMT - _DECLARED_NONBINDING_STMT
    )
    if stmt_holes:
        unaccounted["stmt"] = sorted(c.__name__ for c in stmt_holes)
    pattern_holes = (
        _grammar_classes(ast.pattern)
        - _BINDING_HANDLED_PATTERN
        - _DECLARED_NONBINDING_PATTERN
    )
    if pattern_holes:
        unaccounted["pattern"] = sorted(c.__name__ for c in pattern_holes)
    return unaccounted


_FLOOR_HOLES = _unaccounted_grammar()
if _FLOOR_HOLES:
    raise RuntimeError(
        "value_pins binding scan is not total over this interpreter's ast "
        f"grammar: unaccounted node kinds {_FLOOR_HOLES}. Classify each as "
        "binding-handled or declared-nonbinding before any pin is admissible; "
        "a best-effort total is an asserted silence and is inadmissible."
    )
del _FLOOR_HOLES
