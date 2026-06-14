from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .canonical import cid_of_json
from .value_pins import ValuePin, scan_module_value_pins
from .ir import (
    Json,
    bool_const,
    ctor,
    fold_seq,
    function_contract,
    int_const,
    none_const,
    pass_stmt,
    source_unit_contract,
    str_const,
    substrate_ctor,
    true_formula,
    var,
)

PANIC_FREEDOM_EFFECT_KIND = "panic-freedom"
RUNTIME_FAILURE_SITE_CONCEPT = "concept:panic-freedom.leaf.runtime-failure-site"
CLASS_SHAPE_ASSUMPTIONS = [
    "presence-guaranteed-assuming-standard-construction-via-__init__",
    "not-robust-to-__new__-or-pickle-bypass",
    "not-robust-to-cross-module-monkey-patch-or-delete",
]
SLOT_PRESENCE_NOTE = "slot-membership alone does not discharge presence"


@dataclass
class LiftResult:
    ir: list[Json] = field(default_factory=list)
    diagnostics: list[Json] = field(default_factory=list)
    opacity_report: list[Json] = field(default_factory=list)
    refusals: list[Json] = field(default_factory=list)


@dataclass(frozen=True)
class _FunctionInfo:
    node: ast.AST
    qualname: str
    fn_name: str


@dataclass(frozen=True)
class _ClassInfo:
    node: ast.ClassDef
    qualname: str
    class_name: str


@dataclass(frozen=True)
class _AttributeReceiverContext:
    class_name: str
    class_qualname: str
    receiver_name: str


class _UnsupportedSyntax(Exception):
    def __init__(
        self,
        node: ast.AST,
        reason: str,
        kind: str = "unhandled-syntax",
    ):
        self.node = node
        self.reason = reason
        self.kind = kind
        super().__init__(reason)


class _EffectSet:
    def __init__(self) -> None:
        self._effects: list[Json] = []
        self._seen: set[tuple[str, str]] = set()

    def add_reads(self, target: str) -> None:
        self._add(("reads", target), {"kind": "reads", "target": target})

    def add_writes(self, target: str) -> None:
        self._add(("writes", target), {"kind": "writes", "target": target})

    def add_io(self) -> None:
        self._add(("io", ""), {"kind": "io"})

    def add_panics(self) -> None:
        self._add(("panics", ""), {"kind": "panics"})

    def add_unresolved_call(self, name: str) -> None:
        self._add(("unresolved_call", name), {"kind": "unresolved_call", "name": name})

    def add_opaque_loop(self, loop_term: Json) -> None:
        loop_cid = cid_of_json(loop_term)
        self._add(
            ("opaque_loop", loop_cid),
            {"kind": "opaque_loop", "loopCid": loop_cid},
        )

    def sorted(self) -> list[Json]:
        return sorted(self._effects, key=_effect_sort_key)

    def _add(self, key: tuple[str, str], effect: Json) -> None:
        if key in self._seen:
            return
        self._seen.add(key)
        self._effects.append(effect)


def lift_source(source: str, source_path: str) -> LiftResult:
    result = LiftResult()
    try:
        tree = ast.parse(source, filename=source_path)
    except SyntaxError as exc:
        result.refusals.append(
            _refusal(
                "syntax-error",
                None,
                exc.lineno,
                exc.msg,
            )
        )
        result.ir.append(
            source_unit_contract(
                source_path=source_path,
                source=source,
                operational_term=pass_stmt(),
            )
        )
        return result

    module_path = _module_path(source_path)
    module_globals = _module_global_names(tree)
    pin_scan = scan_module_value_pins(tree)
    result.refusals.extend(pin_scan.refusals)
    class_shapes = _lift_class_shapes(tree, module_path)
    collector = _DefinitionCollector(module_path)
    collector.visit(tree)
    receiver_contexts = _receiver_contexts_by_method(class_shapes)

    body_terms: list[Json] = []
    contracts: list[Json] = []
    for info in collector.definitions:
        contract = _lift_function(
            info,
            source_path,
            module_globals,
            result,
            receiver_context=receiver_contexts.get(info.qualname),
            value_pins=pin_scan.pins,
        )
        if contract is None:
            continue
        body_terms.append(contract["post"]["args"][1])
        contracts.append(contract)

    result.ir.append(
        source_unit_contract(
            source_path=source_path,
            source=source,
            operational_term=fold_seq(body_terms),
            class_shapes=class_shapes if class_shapes else None,
        )
    )
    result.ir.extend(contracts)
    return result


def lift_paths(workspace_root: str, source_paths: Iterable[str]) -> LiftResult:
    result = LiftResult()
    root = Path(workspace_root or ".").resolve()
    for requested in source_paths:
        path = Path(requested)
        full = path if path.is_absolute() else root / path
        try:
            resolved = full.resolve()
        except OSError as exc:
            result.refusals.append(
                _refusal(
                    "io-error",
                    None,
                    None,
                    f"cannot resolve path '{requested}': {exc}",
                )
            )
            continue
        if not _is_relative_to(resolved, root):
            result.refusals.append(
                _refusal(
                    "path-traversal",
                    None,
                    None,
                    f"path '{requested}' escapes workspace root '{root}'",
                )
            )
            continue
        for file_path in _iter_python_files(resolved):
            try:
                source = file_path.read_text(encoding="utf-8")
            except OSError as exc:
                result.refusals.append(
                    _refusal(
                        "io-error",
                        None,
                        None,
                        f"cannot read '{file_path}': {exc}",
                    )
                )
                continue
            display_path = os.path.relpath(file_path, root)
            file_result = lift_source(source, display_path)
            result.ir.extend(file_result.ir)
            result.diagnostics.extend(file_result.diagnostics)
            result.opacity_report.extend(file_result.opacity_report)
            result.refusals.extend(file_result.refusals)
    return result


class _DefinitionCollector(ast.NodeVisitor):
    def __init__(self, module_path: str):
        self.module_path = module_path
        self.scope: list[tuple[str, str]] = []
        self.definitions: list[_FunctionInfo] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self.scope.append(("class", node.name))
        for stmt in node.body:
            self.visit(stmt)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._record_function(node)
        self.scope.append(("function", node.name))
        for stmt in node.body:
            self.visit(stmt)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._record_function(node)
        self.scope.append(("function", node.name))
        for stmt in node.body:
            self.visit(stmt)
        self.scope.pop()

    def _record_function(self, node: ast.AST) -> None:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        qualname = _qualname(self.scope, node.name)
        self.definitions.append(
            _FunctionInfo(
                node=node,
                qualname=qualname,
                fn_name=f"{self.module_path}.{qualname}",
            )
        )


class _ClassCollector(ast.NodeVisitor):
    def __init__(self, module_path: str):
        self.module_path = module_path
        self.scope: list[tuple[str, str]] = []
        self.classes: list[_ClassInfo] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        qualname = _qualname(self.scope, node.name)
        self.classes.append(
            _ClassInfo(
                node=node,
                qualname=qualname,
                class_name=f"{self.module_path}.{qualname}",
            )
        )
        self.scope.append(("class", node.name))
        for stmt in node.body:
            self.visit(stmt)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self.scope.append(("function", node.name))
        for stmt in node.body:
            self.visit(stmt)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self.scope.append(("function", node.name))
        for stmt in node.body:
            self.visit(stmt)
        self.scope.pop()


class _MethodAttributeScanner(ast.NodeVisitor):
    def __init__(
        self,
        *,
        method_name: str,
        method_kind: str,
        instance_receiver: str | None,
    ) -> None:
        self.method_name = method_name
        self.method_kind = method_kind
        self.instance_receiver = instance_receiver
        self.guaranteed: dict[str, list[Json]] = {}
        self.open_attrs: dict[str, dict[str, object]] = {}
        self.open_reasons: set[str] = set()
        self.deleted_attrs: set[str] = set()
        self._conditional_depth = 0
        self._nested_depth = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_nested_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_nested_scope(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._nested_depth += 1
        try:
            self.visit(node.body)
        finally:
            self._nested_depth -= 1

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_nested_scope(node)

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        self._visit_conditionally([*node.body, *node.orelse])

    def visit_For(self, node: ast.For) -> None:
        self.visit(node.iter)
        self._visit_conditionally([node.target, *node.body, *node.orelse])

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit(node.iter)
        self._visit_conditionally([node.target, *node.body, *node.orelse])

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        self._visit_conditionally([*node.body, *node.orelse])

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.visit(item.optional_vars)
        self._visit_conditionally(node.body)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.visit(item.optional_vars)
        self._visit_conditionally(node.body)

    def visit_Try(self, node: ast.Try) -> None:
        self._visit_conditionally([*node.body, *node.orelse, *node.finalbody])
        for handler in node.handlers:
            self._visit_conditionally(handler.body)

    def visit_Match(self, node: ast.Match) -> None:
        self.visit(node.subject)
        for case in node.cases:
            if case.guard is not None:
                self.visit(case.guard)
            self._visit_conditionally(case.body)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._record_assignment_target(target, node)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.visit(node.annotation)
        if node.value is None:
            return
        self._record_assignment_target(node.target, node)
        self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        attr = self._instance_attr_name(node.target)
        if attr is not None:
            self._record_open_attr(
                attr,
                "read-modify-instance-attribute",
                node,
            )
        self.visit(node.value)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            attr = self._instance_attr_name(target)
            if attr is not None:
                self._record_deleted_attr(attr, node)
            else:
                self.visit(target)

    def visit_Call(self, node: ast.Call) -> None:
        name = _decorator_name(node.func)
        if name in {"setattr", "builtins.setattr"} and node.args:
            attr = self._literal_attr_arg(node, index=1)
            if self._is_instance_receiver(node.args[0]):
                self.open_reasons.add("dynamic-setattr")
                if attr is not None:
                    self._record_open_attr(attr, "dynamic-setattr", node)
        elif name in {"delattr", "builtins.delattr"} and node.args:
            attr = self._literal_attr_arg(node, index=1)
            if self._is_instance_receiver(node.args[0]):
                self.open_reasons.add("dynamic-delattr")
                if attr is not None:
                    self._record_deleted_attr(attr, node, reason="deleted-in-method")
        elif name in {"object.__setattr__", "super.__setattr__"} and node.args:
            attr = self._literal_attr_arg(node, index=1)
            if self._is_instance_receiver(node.args[0]):
                self.open_reasons.add("dynamic-setattr")
                if attr is not None:
                    self._record_open_attr(attr, "dynamic-setattr", node)
        elif name in {"object.__delattr__", "super.__delattr__"} and node.args:
            attr = self._literal_attr_arg(node, index=1)
            if self._is_instance_receiver(node.args[0]):
                self.open_reasons.add("dynamic-delattr")
                if attr is not None:
                    self._record_deleted_attr(attr, node, reason="deleted-in-method")
        self.generic_visit(node)

    def _visit_nested_scope(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    ) -> None:
        self._nested_depth += 1
        try:
            for child in ast.iter_child_nodes(node):
                self.visit(child)
        finally:
            self._nested_depth -= 1

    def _visit_conditionally(self, nodes: Iterable[ast.AST]) -> None:
        self._conditional_depth += 1
        try:
            for node in nodes:
                self.visit(node)
        finally:
            self._conditional_depth -= 1

    def _record_assignment_target(self, target: ast.AST, source_node: ast.AST) -> None:
        attr = self._instance_attr_name(target)
        if attr is None:
            self.visit(target)
            return
        if (
            self.method_name == "__init__"
            and self.method_kind == "instance"
            and self._conditional_depth == 0
            and self._nested_depth == 0
        ):
            self.guaranteed.setdefault(attr, []).append(
                _shape_source(
                    "unconditional-init-assignment",
                    source_node,
                    method=self.method_name,
                )
            )
            return
        if self._nested_depth > 0:
            reason = "nested-instance-attribute"
        elif self.method_name == "__init__":
            reason = "conditional-init-attribute"
        else:
            reason = "late-instance-attribute"
        self._record_open_attr(attr, reason, source_node)

    def _record_deleted_attr(
        self,
        attr: str,
        source_node: ast.AST,
        *,
        reason: str = "deleted-in-method",
    ) -> None:
        self.deleted_attrs.add(attr)
        self.open_reasons.add("deleted-instance-attribute")
        self._record_open_attr(attr, reason, source_node)

    def _record_open_attr(self, attr: str, reason: str, source_node: ast.AST) -> None:
        self.open_reasons.add(reason)
        entry = self.open_attrs.setdefault(
            attr,
            {
                "name": attr,
                "memberKind": "instance-attribute",
                "presence": "open",
                "reasons": [],
                "sources": [],
            },
        )
        reasons = entry["reasons"]
        assert isinstance(reasons, list)
        if reason not in reasons:
            reasons.append(reason)
        sources = entry["sources"]
        assert isinstance(sources, list)
        sources.append(_shape_source(reason, source_node, method=self.method_name))

    def _instance_attr_name(self, target: ast.AST) -> str | None:
        if not isinstance(target, ast.Attribute):
            return None
        if not self._is_instance_receiver(target.value):
            return None
        return target.attr

    def _is_instance_receiver(self, node: ast.AST) -> bool:
        return (
            self.instance_receiver is not None
            and isinstance(node, ast.Name)
            and node.id == self.instance_receiver
        )

    def _literal_attr_arg(self, node: ast.Call, *, index: int) -> str | None:
        if len(node.args) <= index:
            return None
        arg = node.args[index]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        return None


class _ClassBodyPoisonScanner(ast.NodeVisitor):
    def __init__(self) -> None:
        self.open_reasons: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Call(self, node: ast.Call) -> None:
        name = _decorator_name(node.func)
        if name in {"setattr", "builtins.setattr", "object.__setattr__", "super.__setattr__"}:
            self.open_reasons.add("dynamic-setattr")
        if name in {"delattr", "builtins.delattr", "object.__delattr__", "super.__delattr__"}:
            self.open_reasons.add("dynamic-delattr")
        self.generic_visit(node)

    def visit_Delete(self, node: ast.Delete) -> None:
        self.open_reasons.add("dynamic-class-delete")
        self.generic_visit(node)


class _LocalCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)


class _Emitter:
    def __init__(
        self,
        *,
        fn_name: str,
        locals_: set[str],
        module_globals: set[str],
        effects: _EffectSet,
        source_path: str,
        panic_loci: list[Json],
        attribute_receiver: _AttributeReceiverContext | None = None,
        value_pins: dict[str, ValuePin] | None = None,
    ) -> None:
        self.fn_name = fn_name
        self.locals = set(locals_)
        self.module_globals = module_globals
        self.effects = effects
        self.source_path = source_path
        self.panic_loci = panic_loci
        self.attribute_receiver = attribute_receiver
        self.value_pins = value_pins or {}

    def statements(self, statements: list[ast.stmt]) -> Json:
        emitted: list[Json] = []
        for statement in statements:
            if _is_docstring_stmt(statement):
                continue
            emitted.append(self.statement(statement))
        return fold_seq(emitted)

    def statements_with_extra_locals(self, statements: list[ast.stmt], extra_locals: set[str]) -> Json:
        previous = self.locals
        self.locals = self.locals | extra_locals
        try:
            return self.statements(statements)
        finally:
            self.locals = previous

    def statement(self, node: ast.stmt) -> Json:
        if isinstance(node, ast.Return):
            value = none_const() if node.value is None else self.expr(node.value)
            return ctor("python:return", value)
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1:
                raise _UnsupportedSyntax(node, "multiple-target assignment is refused")
            target_node = node.targets[0]
            if isinstance(target_node, (ast.Tuple, ast.List)):
                value = self.expr(node.value)
                term = self.unpack_assign(target_node, value)
                self.effects.add_panics()
                self.panic_loci.append(
                    self.runtime_failure_locus(
                        target_node,
                        term,
                        subkind="iter-unpack",
                    )
                )
                return term
            target = self.assign_target(target_node)
            self._record_write_if_nonlocal(target_node)
            return ctor("python:assign", target, self.expr(node.value))
        if isinstance(node, ast.AugAssign):
            op = _BINOPS.get(type(node.op))
            if op is None:
                raise _UnsupportedSyntax(node, f"unsupported binary operator: {type(node.op).__name__}")
            target = self.augassign_target(node.target)
            self._record_write_if_nonlocal(node.target)
            return ctor("python:aug_assign", target, str_const(op), self.expr(node.value))
        if isinstance(node, ast.AnnAssign):
            annotation = self.annotation_expr(node.annotation)
            if node.value is None:
                target = self.annassign_target_without_value(node.target)
                value = ctor("python:no_value")
            else:
                target = self.assign_target(node.target)
                self._record_write_if_nonlocal(node.target)
                value = self.expr(node.value)
            return ctor("python:ann_assign", target, annotation, value)
        if isinstance(node, ast.If):
            condition = self.expr(node.test)
            then_branch = self.statements(node.body)
            else_branch = self.statements(node.orelse) if node.orelse else pass_stmt()
            guarded = self.none_guarded_if(node.test, condition, then_branch, else_branch)
            if guarded is not None:
                return guarded
            attribute_guarded = self.attribute_presence_guarded_if(
                node.test,
                condition,
                then_branch,
                else_branch,
            )
            if attribute_guarded is not None:
                return attribute_guarded
            return ctor(
                "python:if",
                condition,
                then_branch,
                else_branch,
            )
        if isinstance(node, ast.Try):
            handlers = [
                self.except_handler(handler)
                for handler in node.handlers
            ]
            return ctor(
                "python:try",
                self.statements(node.body),
                ctor("python:except_handlers", *handlers),
                self.statements(node.orelse) if node.orelse else pass_stmt(),
                self.statements(node.finalbody) if node.finalbody else pass_stmt(),
            )
        if isinstance(node, ast.With):
            raise _UnsupportedSyntax(node, "with statements are refused")
        if isinstance(node, ast.While):
            if node.orelse:
                raise _UnsupportedSyntax(node, "while/else is refused")
            term = ctor("python:while", self.expr(node.test), self.statements(node.body))
            self.effects.add_opaque_loop(term)
            return term
        if isinstance(node, ast.For):
            if node.orelse:
                raise _UnsupportedSyntax(node, "for/else is refused")
            target = self.target(node.target)
            self._record_write_if_nonlocal(node.target)
            term = ctor(
                "python:for",
                target,
                self.expr(node.iter),
                self.statements(node.body),
            )
            self.effects.add_opaque_loop(term)
            return term
        if isinstance(node, ast.Expr):
            return ctor("python:expr", self.expr(node.value))
        if isinstance(node, ast.Pass):
            return pass_stmt()
        if isinstance(node, ast.Break):
            return ctor("python:break", none_const())
        if isinstance(node, ast.Continue):
            return ctor("python:continue", none_const())
        if isinstance(node, ast.Raise):
            self.effects.add_panics()
            value = none_const() if node.exc is None else self.expr(node.exc)
            self.panic_loci.append(
                self.runtime_failure_locus(
                    node,
                    value,
                    subkind="explicit-raise",
                    exception_class=_exception_class(node.exc),
                )
            )
            return ctor("python:raise", value)
        raise _UnsupportedSyntax(node, f"unhandled statement kind: {type(node).__name__}")

    def except_handler(self, node: ast.ExceptHandler) -> Json:
        exception_type = none_const() if node.type is None else self.expr(node.type)
        name = none_const() if node.name is None else str_const(node.name)
        body = (
            self.statements_with_extra_locals(node.body, {node.name})
            if node.name is not None
            else self.statements(node.body)
        )
        return ctor(
            "python:except_handler",
            exception_type,
            name,
            body,
        )

    def runtime_failure_locus(
        self,
        node: ast.AST,
        arg_term: Json,
        *,
        subkind: str,
        exception_class: str | None = None,
    ) -> Json:
        locus = {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": subkind,
            "argTerm": arg_term,
            "file": self.source_path,
            "line": int(getattr(node, "lineno", 0) or 0),
            "col": int(getattr(node, "col_offset", 0) or 0),
        }
        if exception_class:
            locus["exceptionClass"] = exception_class
        return locus

    def attribute_runtime_failure_locus(
        self,
        node: ast.Attribute,
        arg_term: Json,
        *,
        subkind: str,
        exception_class: str | None = None,
    ) -> Json:
        locus = self.runtime_failure_locus(
            node,
            arg_term,
            subkind=subkind,
            exception_class=exception_class,
        )
        if subkind == "attribute-access":
            safety = self.attribute_safety_obligation(node)
            if safety is not None:
                locus["attributeSafety"] = safety
        return locus

    def target(self, node: ast.expr) -> Json:
        if isinstance(node, ast.Name):
            return var(node.id)
        if isinstance(node, ast.Attribute):
            term = ctor(
                "python:attribute",
                self.expr(node.value),
                str_const(node.attr),
            )
            self.effects.add_panics()
            self.panic_loci.append(
                self.attribute_runtime_failure_locus(
                    node,
                    term,
                    subkind="attribute-write",
                    exception_class="AttributeError",
                )
            )
            return term
        if isinstance(node, ast.Subscript):
            term = ctor(
                "python:subscript",
                self.expr(node.value),
                self.subscript_index(node),
            )
            self.effects.add_panics()
            self.panic_loci.append(
                self.runtime_failure_locus(
                    node,
                    term,
                    subkind="subscript-write",
                )
            )
            return term
        raise _UnsupportedSyntax(node, f"unsupported assignment target: {type(node).__name__}")

    def assign_target(self, node: ast.expr) -> Json:
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            term = ctor(
                "python:subscript",
                self.expr(node.value),
                self.slice_index(node.slice),
            )
            self.effects.add_panics()
            self.panic_loci.append(
                self.runtime_failure_locus(
                    node,
                    term,
                    subkind="subscript-write",
                )
            )
            return term
        return self.target(node)

    def unpack_assign(self, node: ast.expr, value: Json) -> Json:
        if isinstance(node, ast.Tuple):
            kind = "tuple"
        elif isinstance(node, ast.List):
            kind = "list"
        else:
            raise _UnsupportedSyntax(node, f"unsupported assignment target: {type(node).__name__}")
        if not node.elts:
            raise _UnsupportedSyntax(node, f"unsupported assignment target: {type(node).__name__}")
        targets: list[Json] = []
        for element in node.elts:
            if not isinstance(element, ast.Name):
                raise _UnsupportedSyntax(node, f"unsupported assignment target: {type(node).__name__}")
            targets.append(var(element.id))
        return ctor(
            "python:unpack_assign",
            str_const(kind),
            ctor("python:unpack_targets", *targets),
            value,
        )

    def augassign_target(self, node: ast.expr) -> Json:
        if isinstance(node, ast.Name):
            return var(node.id)
        if isinstance(node, ast.Attribute):
            term = ctor("python:attribute", self.expr(node.value), str_const(node.attr))
            self.effects.add_panics()
            self.panic_loci.append(
                self.attribute_runtime_failure_locus(
                    node,
                    term,
                    subkind="attribute-access",
                    exception_class="AttributeError",
                )
            )
            self.panic_loci.append(
                self.attribute_runtime_failure_locus(
                    node,
                    term,
                    subkind="attribute-write",
                    exception_class="AttributeError",
                )
            )
            return term
        if isinstance(node, ast.Subscript):
            receiver = self.expr(node.value)
            index = self.slice_index(node.slice) if isinstance(node.slice, ast.Slice) else self.subscript_index(node)
            term = ctor("python:subscript", receiver, index)
            self.effects.add_panics()
            self.panic_loci.append(
                self.runtime_failure_locus(
                    node,
                    term,
                    subkind="subscript-access",
                )
            )
            self.panic_loci.append(
                self.runtime_failure_locus(
                    node,
                    term,
                    subkind="subscript-write",
                )
            )
            return term
        raise _UnsupportedSyntax(node, f"unsupported augmented assignment target: {type(node).__name__}")

    def annassign_target_without_value(self, node: ast.expr) -> Json:
        if isinstance(node, ast.Name):
            return var(node.id)
        if isinstance(node, ast.Attribute):
            return ctor(
                "python:attribute",
                self.expr(node.value),
                str_const(node.attr),
            )
        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Slice):
                return ctor(
                    "python:subscript",
                    self.expr(node.value),
                    self.slice_index(node.slice),
                )
            return ctor(
                "python:subscript",
                self.expr(node.value),
                self.subscript_index(node),
            )
        raise _UnsupportedSyntax(node, f"unsupported annotated assignment target: {type(node).__name__}")

    def annotation_expr(self, node: ast.expr) -> Json:
        if isinstance(node, ast.Constant):
            return self.constant(node)
        if isinstance(node, ast.Name):
            return var(node.id)
        if isinstance(node, ast.Attribute):
            return ctor(
                "python:attribute",
                self.annotation_expr(node.value),
                str_const(node.attr),
            )
        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Slice):
                raise _UnsupportedSyntax(node.slice, "slice annotations are refused")
            return ctor(
                "python:subscript",
                self.annotation_expr(node.value),
                self.annotation_expr(node.slice),
            )
        raise _UnsupportedSyntax(node, f"unsupported annotation expression: {type(node).__name__}")

    def expr(self, node: ast.expr) -> Json:
        if isinstance(node, ast.Constant):
            return self.constant(node)
        if isinstance(node, ast.Name):
            if node.id not in self.locals:
                pin = self.value_pins.get(node.id)
                if pin is not None:
                    # The name resolved to a sworn immutable value: the term
                    # IS the value, and no mutable-global read effect exists.
                    return pin.term
            self._record_read_if_global(node.id)
            return var(node.id)
        if isinstance(node, ast.BinOp):
            op = _BINOPS.get(type(node.op))
            if op is None:
                raise _UnsupportedSyntax(node, f"unsupported binary operator: {type(node.op).__name__}")
            return ctor(op, self.expr(node.left), self.expr(node.right))
        if isinstance(node, ast.UnaryOp):
            op = _UNARYOPS.get(type(node.op))
            if op is None:
                raise _UnsupportedSyntax(node, f"unsupported unary operator: {type(node.op).__name__}")
            return ctor(op, self.expr(node.operand))
        if isinstance(node, ast.BoolOp):
            op = "python:and" if isinstance(node.op, ast.And) else "python:or"
            if len(node.values) < 2:
                raise _UnsupportedSyntax(node, "boolean operation without two operands")
            values = [self.expr(value) for value in node.values]
            result = ctor(op, values[0], values[1])
            for value in values[2:]:
                result = ctor(op, result, value)
            return result
        if isinstance(node, ast.Compare):
            return self.compare(node)
        if isinstance(node, ast.Call):
            return self.call(node)
        if isinstance(node, ast.Attribute):
            if (
                isinstance(node.value, ast.Name)
                and node.value.id not in self.locals
            ):
                pin = self.value_pins.get(f"{node.value.id}.{node.attr}")
                if pin is not None:
                    # A pinned IntEnum/StrEnum member: the term IS the value
                    # (those kinds compare as their values), and no panic
                    # locus is emitted -- Enum's metaclass forbids member
                    # reassignment, and the pin's scan refuses on any
                    # syntactic puncture, so the presence claim rides the
                    # pin's premise rather than a per-access AttributeError
                    # site.
                    return pin.term
            term = ctor("python:attribute", self.expr(node.value), str_const(node.attr))
            self.effects.add_panics()
            self.panic_loci.append(
                self.attribute_runtime_failure_locus(
                    node,
                    term,
                    subkind="attribute-access",
                    exception_class="AttributeError",
                )
            )
            return term
        if isinstance(node, ast.Subscript):
            receiver = self.expr(node.value)
            index = self.slice_index(node.slice) if isinstance(node.slice, ast.Slice) else self.subscript_index(node)
            term = ctor("python:subscript", receiver, index)
            self.effects.add_panics()
            self.panic_loci.append(
                self.runtime_failure_locus(
                    node,
                    term,
                    subkind="subscript-access",
                )
            )
            return term
        if isinstance(node, ast.Tuple):
            return ctor("python:tuple", *[self.expr(element) for element in node.elts])
        if isinstance(node, ast.List):
            return ctor("python:list", *[self.expr(element) for element in node.elts])
        if isinstance(node, ast.NamedExpr):
            if not isinstance(node.target, ast.Name):
                raise _UnsupportedSyntax(
                    node.target,
                    f"unsupported walrus target: {type(node.target).__name__}",
                )
            return ctor("python:walrus", var(node.target.id), self.expr(node.value))
        raise _UnsupportedSyntax(node, f"unhandled expression kind: {type(node).__name__}")

    def constant(self, node: ast.Constant) -> Json:
        value = node.value
        if isinstance(value, bool):
            return bool_const(value)
        if isinstance(value, int):
            return int_const(value)
        if isinstance(value, str):
            return str_const(value)
        if value is None:
            return none_const()
        raise _UnsupportedSyntax(node, f"unsupported constant: {type(value).__name__}")

    def compare(self, node: ast.Compare) -> Json:
        if not node.ops or len(node.ops) != len(node.comparators):
            raise _UnsupportedSyntax(node, "malformed comparison expression")
        operands: list[ast.expr] = [node.left, *node.comparators]
        comparisons: list[Json] = []
        for index, raw_op in enumerate(node.ops):
            op = _CMPOPS.get(type(raw_op))
            if op is None:
                raise _UnsupportedSyntax(
                    node,
                    f"unsupported comparison operator: {type(raw_op).__name__}",
                )
            comparisons.append(
                ctor(
                    "python:compare",
                    str_const(op),
                    self.expr(operands[index]),
                    self.expr(operands[index + 1]),
                )
            )
        result = comparisons[0]
        for comparison in comparisons[1:]:
            result = ctor("python:and", result, comparison)
        return result

    def call(self, node: ast.Call) -> Json:
        for arg in node.args:
            if isinstance(arg, ast.Starred):
                raise _UnsupportedSyntax(arg, "starred call arguments are refused")
        for keyword in node.keywords:
            if keyword.arg is None:
                raise _UnsupportedSyntax(keyword, "starred call arguments are refused")
        if isinstance(node.func, ast.Attribute):
            self.expr(node.func)
        callee = _callee_name(node.func)
        if callee == "print":
            self.effects.add_io()
        else:
            self.effects.add_unresolved_call(callee)
        args = [self.expr(arg) for arg in node.args]
        args.extend(
            ctor("python:kwarg", str_const(str(keyword.arg)), self.expr(keyword.value))
            for keyword in node.keywords
        )
        return ctor("python:call", str_const(callee), *args)

    def subscript_index(self, node: ast.Subscript) -> Json:
        if isinstance(node.slice, ast.Slice):
            raise _UnsupportedSyntax(node.slice, "slice subscripts are refused")
        return self.expr(node.slice)

    def slice_index(self, node: ast.Slice) -> Json:
        lower = none_const() if node.lower is None else self.expr(node.lower)
        upper = none_const() if node.upper is None else self.expr(node.upper)
        step = none_const() if node.step is None else self.expr(node.step)
        return ctor("python:slice", lower, upper, step)

    def none_guarded_if(
        self,
        test: ast.expr,
        condition: Json,
        then_branch: Json,
        else_branch: Json,
    ) -> Json | None:
        guard = self.none_guard(test, condition)
        if guard is None:
            return None
        then_head, else_head, receiver = guard
        return substrate_ctor(
            "cf_ite",
            condition,
            substrate_ctor("cf_guarded", substrate_ctor(then_head, receiver), then_branch),
            substrate_ctor("cf_guarded", substrate_ctor(else_head, receiver), else_branch),
        )

    def attribute_presence_guarded_if(
        self,
        test: ast.expr,
        condition: Json,
        then_branch: Json,
        else_branch: Json,
    ) -> Json | None:
        guard = self.attribute_presence_guard(test)
        if guard is None:
            return None
        receiver, attr = guard
        return substrate_ctor(
            "cf_ite",
            condition,
            substrate_ctor(
                "cf_guarded",
                substrate_ctor("attribute_present", receiver, str_const(attr)),
                then_branch,
            ),
            else_branch,
        )

    def attribute_presence_guard(self, test: ast.expr) -> tuple[Json, str] | None:
        if self.attribute_receiver is None:
            return None
        if not isinstance(test, ast.Call):
            return None
        if _callee_name(test.func) not in {"hasattr", "builtins.hasattr"}:
            return None
        if len(test.args) != 2 or test.keywords:
            return None
        receiver_node, attr_node = test.args
        if (
            not isinstance(receiver_node, ast.Name)
            or receiver_node.id != self.attribute_receiver.receiver_name
        ):
            return None
        if not isinstance(attr_node, ast.Constant) or not isinstance(attr_node.value, str):
            return None
        return var(receiver_node.id), attr_node.value

    def none_guard(self, test: ast.expr, condition: Json) -> tuple[str, str, Json] | None:
        if not isinstance(test, ast.Compare):
            return None
        if len(test.ops) != 1 or len(test.comparators) != 1:
            return None
        if (
            not isinstance(condition, dict)
            or condition.get("kind") != "ctor"
            or condition.get("name") != "python:compare"
        ):
            return None
        condition_args = condition.get("args")
        if not isinstance(condition_args, list) or len(condition_args) != 3:
            return None
        raw_op = test.ops[0]
        if not isinstance(raw_op, (ast.Is, ast.IsNot)):
            return None
        lhs = test.left
        rhs = test.comparators[0]
        if _is_none_literal(rhs) and not _is_none_literal(lhs):
            receiver = condition_args[1]
        elif _is_none_literal(lhs) and not _is_none_literal(rhs):
            receiver = condition_args[2]
        else:
            return None
        if isinstance(raw_op, ast.Is):
            return "is_none", "is_some", receiver
        return "is_some", "is_none", receiver

    def _record_read_if_global(self, name: str) -> None:
        if name in self.module_globals and name not in self.locals:
            self.effects.add_reads(name)

    def _record_write_if_nonlocal(self, node: ast.expr) -> None:
        if isinstance(node, ast.Attribute):
            self.effects.add_writes(_target_text(node))
        elif isinstance(node, ast.Subscript):
            self.effects.add_writes(_target_text(node))

    def attribute_safety_obligation(self, node: ast.Attribute) -> Json | None:
        if self.attribute_receiver is None:
            return None
        if (
            not isinstance(node.value, ast.Name)
            or node.value.id != self.attribute_receiver.receiver_name
        ):
            return None
        return {
            "schemaVersion": "1",
            "kind": "python:attribute-safety-obligation",
            "receiverClass": self.attribute_receiver.class_name,
            "receiverQualname": self.attribute_receiver.class_qualname,
            "receiverName": self.attribute_receiver.receiver_name,
            "attribute": node.attr,
        }


def _lift_function(
    info: _FunctionInfo,
    source_path: str,
    module_globals: set[str],
    result: LiftResult,
    *,
    receiver_context: _AttributeReceiverContext | None = None,
    value_pins: dict[str, ValuePin] | None = None,
) -> Json | None:
    node = info.node
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    try:
        if isinstance(node, ast.AsyncFunctionDef):
            raise _UnsupportedSyntax(node, "async functions are refused")
        # Verify-facing AUTHORING decorators (@sugar.boundary / @boundary /
        # @sugar.sugar / @sugar) are declarative metadata, not behavioral
        # wrappers, so they do NOT make a function "decorated" for lift
        # purposes -- the body underneath is lifted (mirrors Go stripping the
        # //sugar: pragma). Any OTHER decorator still refuses.
        from .authoring import is_authoring_decorator

        non_authoring = [d for d in node.decorator_list if not is_authoring_decorator(d)]
        if non_authoring:
            raise _UnsupportedSyntax(node, "decorated functions are refused")
        formals, parameter_shape = _parameter_shape(node)
        refused = _contains_refused_control(node)
        if refused is not None:
            raise refused

        locals_ = _function_locals(node, formals)
        if receiver_context is not None and _receiver_name_reassigned(
            node,
            receiver_context.receiver_name,
        ):
            receiver_context = None
        effects = _EffectSet()
        panic_loci: list[Json] = []
        precondition = _lift_function_precondition(node, info.fn_name, source_path, result)
        emitter = _Emitter(
            fn_name=info.fn_name,
            locals_=locals_,
            module_globals=module_globals,
            effects=effects,
            source_path=source_path,
            panic_loci=panic_loci,
            attribute_receiver=receiver_context,
            value_pins=value_pins,
        )
        body = emitter.statements(node.body)
        return function_contract(
            fn_name=info.fn_name,
            formals=formals,
            body_term=body,
            effects=effects.sorted(),
            source_path=source_path,
            line=node.lineno,
            precondition=precondition,
            panic_loci=panic_loci,
            parameter_shape=(
                parameter_shape
                if _has_nontrivial_parameter_shape(parameter_shape)
                else None
            ),
        )
    except _UnsupportedSyntax as exc:
        result.refusals.append(
            _refusal(
                exc.kind,
                info.fn_name,
                getattr(exc.node, "lineno", getattr(node, "lineno", None)),
                exc.reason,
            )
        )
        return None


def _lift_class_shapes(tree: ast.Module, module_path: str) -> list[Json]:
    collector = _ClassCollector(module_path)
    collector.visit(tree)
    shapes: list[Json] = []
    shapes_by_name: dict[str, Json] = {}
    setattr_override_by_name: dict[str, bool] = {}

    for info in collector.classes:
        shape, setattr_override_in_mro = _build_class_shape(
            info,
            shapes_by_name=shapes_by_name,
            setattr_override_by_name=setattr_override_by_name,
        )
        shapes.append(shape)
        shapes_by_name[info.node.name] = shape
        setattr_override_by_name[info.node.name] = setattr_override_in_mro
    return shapes


def _receiver_contexts_by_method(class_shapes: list[Json]) -> dict[str, _AttributeReceiverContext]:
    contexts: dict[str, _AttributeReceiverContext] = {}
    for shape in class_shapes:
        class_name = shape.get("className")
        class_qualname = shape.get("qualname")
        methods = shape.get("methods", [])
        if not isinstance(class_name, str) or not isinstance(class_qualname, str):
            continue
        if not isinstance(methods, list):
            continue
        for method in methods:
            if not isinstance(method, dict):
                continue
            if method.get("methodKind") != "instance":
                continue
            qualname = method.get("qualname")
            receiver = method.get("instanceReceiver")
            if not isinstance(qualname, str) or not isinstance(receiver, str) or not receiver:
                continue
            contexts[qualname] = _AttributeReceiverContext(
                class_name=class_name,
                class_qualname=class_qualname,
                receiver_name=receiver,
            )
    return contexts


def _receiver_name_reassigned(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    receiver_name: str,
) -> bool:
    class _ReceiverReassignmentScanner(ast.NodeVisitor):
        def __init__(self) -> None:
            self.reassigned = False
            self._nested_depth = 0

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if self._nested_depth > 0:
                return
            self._nested_depth += 1
            try:
                for stmt in node.body:
                    self.visit(stmt)
            finally:
                self._nested_depth -= 1

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            if self._nested_depth > 0:
                return
            self._nested_depth += 1
            try:
                for stmt in node.body:
                    self.visit(stmt)
            finally:
                self._nested_depth -= 1

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            return

        def visit_Lambda(self, node: ast.Lambda) -> None:
            return

        def visit_Name(self, node: ast.Name) -> None:
            if node.id == receiver_name and isinstance(node.ctx, (ast.Store, ast.Del)):
                self.reassigned = True

    scanner = _ReceiverReassignmentScanner()
    scanner.visit(node)
    return scanner.reassigned


def _build_class_shape(
    info: _ClassInfo,
    *,
    shapes_by_name: dict[str, Json],
    setattr_override_by_name: dict[str, bool],
) -> tuple[Json, bool]:
    node = info.node
    open_reasons: set[str] = set()
    attributes: dict[str, Json] = {}
    open_attrs: dict[str, Json] = {}
    methods: list[Json] = []
    permitted: dict[str, Json] = {}
    bases: list[Json] = []

    if node.decorator_list:
        open_reasons.add("class-decorator")
    if node.keywords:
        open_reasons.add("metaclass")

    own_setattr_override = _class_overrides_setattr(node)
    visible_setattr_override = own_setattr_override

    for base in node.bases:
        base_name = _base_name(base)
        base_record: Json = {"name": base_name, "resolution": "non-local"}
        if isinstance(base, ast.Name) and base.id in shapes_by_name:
            base_shape = shapes_by_name[base.id]
            if base_shape.get("status") == "closed":
                base_record["resolution"] = "local-closed"
            else:
                base_record["resolution"] = "local-open"
                open_reasons.add("non-local-base")
            if setattr_override_by_name.get(base.id, False):
                visible_setattr_override = True
        else:
            open_reasons.add("non-local-base")
        bases.append(base_record)

    if visible_setattr_override:
        open_reasons.add("setattr-override-in-mro")

    body_scanner = _ClassBodyPoisonScanner()
    for stmt in node.body:
        body_scanner.visit(stmt)
    open_reasons.update(body_scanner.open_reasons)

    slot_names: set[str] = set()
    for stmt in node.body:
        slot_entries, dynamic_slots = _slot_entries(stmt)
        if dynamic_slots:
            open_reasons.add("dynamic-slots")
        for entry in slot_entries:
            slot_names.add(str(entry["name"]))
            permitted[str(entry["name"])] = entry

        for attr_name, source in _class_body_attribute_sources(stmt):
            if attr_name == "__slots__":
                continue
            attributes[attr_name] = {
                "name": attr_name,
                "memberKind": "class-attribute",
                "presence": "guaranteed",
                "presenceSource": source["kind"],
                "sources": [source],
            }

        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            method = _method_shape(stmt, info.qualname)
            methods.append(method)
            method_kind = str(method["methodKind"])
            if method_kind == "property":
                open_reasons.add("property-descriptor")
                _merge_open_attr(
                    open_attrs,
                    stmt.name,
                    member_kind="property",
                    reason="property-descriptor",
                    source=_shape_source("property-descriptor", stmt, method=stmt.name),
                )
            if _method_has_unknown_decorator(stmt):
                open_reasons.add("method-decorator")

            scanner = _MethodAttributeScanner(
                method_name=stmt.name,
                method_kind=method_kind,
                instance_receiver=(
                    str(method["instanceReceiver"])
                    if method.get("instanceReceiver") is not None
                    else None
                ),
            )
            for body_stmt in stmt.body:
                scanner.visit(body_stmt)
            open_reasons.update(scanner.open_reasons)

            for attr_name, sources in scanner.guaranteed.items():
                existing = attributes.get(attr_name)
                if existing is not None and existing.get("memberKind") == "class-attribute":
                    sources = [*existing.get("sources", []), *sources]
                attributes[attr_name] = {
                    "name": attr_name,
                    "memberKind": "instance-attribute",
                    "presence": "guaranteed",
                    "presenceSource": "unconditional-init-assignment",
                    "slotBacked": attr_name in slot_names,
                    "sources": list(sources),
                }

            for attr_name, entry in scanner.open_attrs.items():
                _merge_open_attr_entry(open_attrs, attr_name, entry)
            for attr_name in scanner.deleted_attrs:
                attributes.pop(attr_name, None)

    for attr_name, entry in open_attrs.items():
        if attr_name in attributes and "deleted-in-method" in entry.get("reasons", []):
            attributes.pop(attr_name, None)

    status = "open" if open_reasons else "closed"
    return (
        {
            "schemaVersion": "1",
            "kind": "python:class-shape",
            "name": node.name,
            "qualname": info.qualname,
            "className": info.class_name,
            "status": status,
            "attributes": _sorted_json_entries(attributes.values()),
            "permittedAttributes": _sorted_json_entries(permitted.values()),
            "openAttributes": _sorted_json_entries(open_attrs.values()),
            "methods": _sorted_json_entries(methods),
            "bases": bases,
            "openReasons": sorted(open_reasons),
            "assumptions": list(CLASS_SHAPE_ASSUMPTIONS),
            "locus": {
                "line": int(getattr(node, "lineno", 0) or 0),
                "col": int(getattr(node, "col_offset", 0) or 0),
            },
        },
        visible_setattr_override,
    )


def _method_shape(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    owner_qualname: str,
) -> Json:
    method_kind = _method_kind(node)
    first_arg = _first_parameter_name(node)
    shape: Json = {
        "name": node.name,
        "qualname": f"{owner_qualname}.{node.name}",
        "methodKind": method_kind,
        "instanceReceiver": first_arg if method_kind == "instance" else None,
        "line": int(getattr(node, "lineno", 0) or 0),
    }
    if method_kind == "classmethod":
        shape["classReceiver"] = first_arg
    return shape


def _method_kind(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    names = {_decorator_name(decorator) for decorator in node.decorator_list}
    names.discard(None)
    if "classmethod" in names or "builtins.classmethod" in names:
        return "classmethod"
    if "staticmethod" in names or "builtins.staticmethod" in names:
        return "staticmethod"
    if "property" in names or "builtins.property" in names:
        return "property"
    if any(name and (name.endswith(".setter") or name.endswith(".deleter")) for name in names):
        return "property"
    return "instance"


def _method_has_unknown_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    known = {
        "classmethod",
        "builtins.classmethod",
        "staticmethod",
        "builtins.staticmethod",
        "property",
        "builtins.property",
    }
    for decorator in node.decorator_list:
        name = _decorator_name(decorator)
        if name in known:
            continue
        if name and (name.endswith(".setter") or name.endswith(".deleter")):
            continue
        return True
    return False


def _first_parameter_name(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    positional = [*node.args.posonlyargs, *node.args.args]
    if not positional:
        return None
    return positional[0].arg


def _class_overrides_setattr(node: ast.ClassDef) -> bool:
    return any(
        isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
        and stmt.name in {"__setattr__", "__delattr__"}
        for stmt in node.body
    )


def _slot_entries(stmt: ast.stmt) -> tuple[list[Json], bool]:
    if not isinstance(stmt, ast.Assign):
        return [], False
    if not any(isinstance(target, ast.Name) and target.id == "__slots__" for target in stmt.targets):
        return [], False
    slots = _literal_slots(stmt.value)
    if slots is None:
        return [], True
    return [
        {
            "name": slot,
            "memberKind": "slot",
            "presence": "permitted-only",
            "guaranteesPresence": False,
            "note": SLOT_PRESENCE_NOTE,
            "sources": [_shape_source("slot-declaration", stmt)],
        }
        for slot in slots
    ], False


def _literal_slots(node: ast.expr) -> list[str] | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        slots: list[str] = []
        for element in node.elts:
            if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
                return None
            slots.append(element.value)
        return slots
    return None


def _class_body_attribute_sources(stmt: ast.stmt) -> list[tuple[str, Json]]:
    if isinstance(stmt, ast.Assign):
        sources: list[tuple[str, Json]] = []
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                sources.append(
                    (
                        target.id,
                        _shape_source("class-body-assignment", stmt),
                    )
                )
        return sources
    if isinstance(stmt, ast.AnnAssign) and stmt.value is not None and isinstance(stmt.target, ast.Name):
        return [
            (
                stmt.target.id,
                _shape_source("class-body-assignment", stmt),
            )
        ]
    if isinstance(stmt, ast.ClassDef):
        return [
            (
                stmt.name,
                _shape_source("nested-class-definition", stmt),
            )
        ]
    return []


def _merge_open_attr(
    open_attrs: dict[str, Json],
    attr_name: str,
    *,
    member_kind: str,
    reason: str,
    source: Json,
) -> None:
    entry = open_attrs.setdefault(
        attr_name,
        {
            "name": attr_name,
            "memberKind": member_kind,
            "presence": "open",
            "reasons": [],
            "sources": [],
        },
    )
    reasons = entry["reasons"]
    assert isinstance(reasons, list)
    if reason not in reasons:
        reasons.append(reason)
    sources = entry["sources"]
    assert isinstance(sources, list)
    sources.append(source)


def _merge_open_attr_entry(
    open_attrs: dict[str, Json],
    attr_name: str,
    entry: dict[str, object],
) -> None:
    reasons = entry.get("reasons", [])
    sources = entry.get("sources", [])
    if not isinstance(reasons, list):
        reasons = []
    if not isinstance(sources, list):
        sources = []
    for reason in reasons:
        _merge_open_attr(
            open_attrs,
            attr_name,
            member_kind=str(entry.get("memberKind", "instance-attribute")),
            reason=str(reason),
            source=sources[0] if sources and isinstance(sources[0], dict) else {},
        )
    if not reasons and sources and isinstance(sources[0], dict):
        _merge_open_attr(
            open_attrs,
            attr_name,
            member_kind=str(entry.get("memberKind", "instance-attribute")),
            reason="open",
            source=sources[0],
        )
    target = open_attrs.get(attr_name)
    if target is None:
        return
    target_sources = target["sources"]
    assert isinstance(target_sources, list)
    for source in sources[1:]:
        if isinstance(source, dict):
            target_sources.append(source)


def _shape_source(kind: str, node: ast.AST, *, method: str | None = None) -> Json:
    source: Json = {
        "kind": kind,
        "line": int(getattr(node, "lineno", 0) or 0),
        "col": int(getattr(node, "col_offset", 0) or 0),
    }
    if method is not None:
        source["method"] = method
    return source


def _base_name(node: ast.expr) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__


def _decorator_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _decorator_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _sorted_json_entries(entries: Iterable[Json]) -> list[Json]:
    return sorted(
        (dict(entry) for entry in entries),
        key=lambda entry: (str(entry.get("name", "")), str(entry.get("qualname", ""))),
    )


def _parameter_shape(node: ast.FunctionDef) -> tuple[list[str], list[Json]]:
    formals: list[str] = []
    shape: list[Json] = []
    positional = [*node.args.posonlyargs, *node.args.args]
    defaults = list(node.args.defaults)
    default_offset = len(positional) - len(defaults)
    default_by_index = {
        index + default_offset: default
        for index, default in enumerate(defaults)
    }

    for index, arg in enumerate(node.args.posonlyargs):
        entry: Json = {"name": arg.arg, "kind": "positional-only"}
        if index in default_by_index:
            entry["default"] = _literal_default(default_by_index[index])
        formals.append(arg.arg)
        shape.append(entry)

    for local_index, arg in enumerate(node.args.args):
        index = len(node.args.posonlyargs) + local_index
        entry = {"name": arg.arg, "kind": "positional-or-keyword"}
        if index in default_by_index:
            entry["default"] = _literal_default(default_by_index[index])
        formals.append(arg.arg)
        shape.append(entry)

    if node.args.vararg is not None:
        formals.append(node.args.vararg.arg)
        shape.append({"name": node.args.vararg.arg, "kind": "vararg"})

    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True):
        entry = {"name": arg.arg, "kind": "keyword-only"}
        if default is not None:
            entry["default"] = _literal_default(default)
        formals.append(arg.arg)
        shape.append(entry)

    if node.args.kwarg is not None:
        formals.append(node.args.kwarg.arg)
        shape.append({"name": node.args.kwarg.arg, "kind": "kwarg"})

    return formals, shape


def _has_nontrivial_parameter_shape(shape: list[Json]) -> bool:
    return any(
        entry.get("kind") != "positional-or-keyword" or "default" in entry
        for entry in shape
    )


def _literal_default(node: ast.expr) -> Json:
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool):
            return bool_const(value)
        if isinstance(value, int):
            return int_const(value)
        if isinstance(value, str):
            return str_const(value)
        if value is None:
            return none_const()
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = node.operand
        if isinstance(operand, ast.Constant) and type(operand.value) is int:
            value = operand.value
            if isinstance(node.op, ast.USub):
                value = -value
            return int_const(value)
    if isinstance(node, ast.Tuple):
        return ctor("python:tuple", *[_literal_default(element) for element in node.elts])
    if isinstance(node, ast.List):
        return ctor("python:list", *[_literal_default(element) for element in node.elts])
    raise _UnsupportedSyntax(node, "non-literal default parameter values are refused")


def _refusal(
    kind: str,
    function: str | None,
    line: int | None,
    reason: str,
) -> Json:
    return {
        "kind": kind,
        "function": function,
        "line": line,
        "reason": reason,
    }


def _contains_refused_control(fn: ast.FunctionDef) -> _UnsupportedSyntax | None:
    for child in ast.walk(fn):
        if child is fn:
            continue
        if isinstance(child, (ast.Global, ast.Nonlocal)):
            return _UnsupportedSyntax(child, "global/nonlocal declarations are refused")
        if isinstance(child, (ast.Yield, ast.YieldFrom)):
            return _UnsupportedSyntax(child, "generators are refused")
        if isinstance(child, ast.Await):
            return _UnsupportedSyntax(child, "await expressions are refused")
    return None


def _function_locals(fn: ast.FunctionDef, formals: list[str]) -> set[str]:
    collector = _LocalCollector()
    for statement in fn.body:
        collector.visit(statement)
    return set(formals) | collector.names


def _lift_function_precondition(
    fn: ast.FunctionDef,
    fn_name: str,
    source_path: str,
    result: LiftResult,
) -> Json:
    parts: list[Json] = []
    for statement in fn.body:
        if _is_docstring_stmt(statement):
            continue
        lifted, residual = _lift_precondition_guard_statement(statement)
        if residual is not None:
            result.diagnostics.append(
                {
                    "kind": "precondition-guard-skipped",
                    "path": source_path,
                    "function": fn_name,
                    "line": int(getattr(statement, "lineno", 0) or 0),
                    "message": residual,
                }
            )
            return true_formula()
        if lifted is not None:
            parts.append(lifted)
            continue
        break
    return _simplify_conjunction(parts)


def _lift_precondition_guard_statement(statement: ast.stmt) -> tuple[Json | None, str | None]:
    if not isinstance(statement, ast.If):
        return None, None
    if statement.orelse or not _body_only_raises(statement.body):
        return None, None
    condition = _lift_guard_formula(statement.test)
    if condition is None:
        return None, "non-flat if-raise guard condition is a precondition residual"
    return _negate_formula(condition), None


def _body_only_raises(body: list[ast.stmt]) -> bool:
    statements = [stmt for stmt in body if not _is_docstring_stmt(stmt)]
    return len(statements) == 1 and isinstance(statements[0], ast.Raise)


def _lift_guard_formula(node: ast.expr) -> Json | None:
    if isinstance(node, ast.BoolOp):
        if len(node.values) < 2:
            return None
        operands = [_lift_guard_formula(value) for value in node.values]
        if any(operand is None for operand in operands):
            return None
        kind = "and" if isinstance(node.op, ast.And) else "or"
        return _fold_connective(kind, [operand for operand in operands if operand is not None])
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = _lift_guard_formula(node.operand)
        return None if inner is None else _negate_formula(inner)
    if isinstance(node, ast.Compare):
        return _lift_guard_compare(node)
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return _atomic("true" if node.value else "false", [])
    return None


def _lift_guard_compare(node: ast.Compare) -> Json | None:
    if not node.ops or len(node.ops) != len(node.comparators):
        return None
    operands: list[ast.expr] = [node.left, *node.comparators]
    atoms: list[Json] = []
    for index, op_node in enumerate(node.ops):
        op = _GUARD_CMP_OPS.get(type(op_node))
        if op is None:
            return None
        left = _lift_guard_term(operands[index])
        right = _lift_guard_term(operands[index + 1])
        if left is None or right is None:
            return None
        atoms.append(_atomic(op, [left, right]))
    return _simplify_conjunction(atoms)


def _lift_guard_term(node: ast.expr) -> Json | None:
    if isinstance(node, ast.Name):
        return var(node.id)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return bool_const(node.value)
        if isinstance(node.value, int):
            return int_const(node.value)
        return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = node.operand
        if isinstance(operand, ast.Constant) and type(operand.value) is int:
            value = operand.value
            if isinstance(node.op, ast.USub):
                value = -value
            return int_const(value)
    return None


def _atomic(name: str, args: list[Json]) -> Json:
    return {"kind": "atomic", "name": name, "args": args}


def _simplify_conjunction(parts: list[Json]) -> Json:
    if not parts:
        return true_formula()
    if len(parts) == 1:
        return parts[0]
    return {"kind": "and", "operands": parts}


def _fold_connective(kind: str, operands: list[Json]) -> Json:
    if not operands:
        return true_formula()
    if len(operands) == 1:
        return operands[0]
    return {"kind": kind, "operands": operands}


def _negate_formula(formula: Json) -> Json:
    kind = formula.get("kind")
    if kind == "atomic":
        name = str(formula.get("name", ""))
        flipped = _NEGATED_ATOMIC.get(name)
        if flipped is not None:
            return _atomic(flipped, list(formula.get("args", [])))
        return {"kind": "not", "operands": [formula]}
    if kind == "not":
        operands = formula.get("operands")
        if isinstance(operands, list) and len(operands) == 1 and isinstance(operands[0], dict):
            return operands[0]
    if kind == "and":
        operands = formula.get("operands")
        if isinstance(operands, list):
            return _fold_connective(
                "or",
                [_negate_formula(operand) for operand in operands if isinstance(operand, dict)],
            )
    if kind == "or":
        operands = formula.get("operands")
        if isinstance(operands, list):
            return _fold_connective(
                "and",
                [_negate_formula(operand) for operand in operands if isinstance(operand, dict)],
            )
    return {"kind": "not", "operands": [formula]}


def _module_global_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(stmt.name)
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                names.update(_stored_names(target))
        elif isinstance(stmt, ast.AnnAssign):
            names.update(_stored_names(stmt.target))
    return names


def _stored_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for elt in node.elts:
            names.update(_stored_names(elt))
        return names
    return set()


def _module_path(source_path: str) -> str:
    path = Path(source_path)
    without_suffix = path.with_suffix("")
    parts = [part for part in without_suffix.parts if part not in {"", "."}]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    cleaned = [_clean_identifier_part(part) for part in parts]
    return ".".join(cleaned) if cleaned else "__main__"


def _clean_identifier_part(part: str) -> str:
    out = "".join(ch if ch.isidentifier() or ch.isdigit() else "_" for ch in part)
    if not out or out[0].isdigit():
        out = "_" + out
    return out


def _qualname(scope: list[tuple[str, str]], name: str) -> str:
    parts: list[str] = []
    for kind, scope_name in scope:
        if kind == "class":
            parts.append(scope_name)
        elif kind == "function":
            parts.extend([scope_name, "<locals>"])
    parts.append(name)
    return ".".join(parts)


def _is_docstring_stmt(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _is_none_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _callee_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _callee_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    raise _UnsupportedSyntax(node, f"unsupported callee kind: {type(node).__name__}")


def _exception_class(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    try:
        if isinstance(node, ast.Call):
            return _callee_name(node.func)
        if isinstance(node, (ast.Name, ast.Attribute)):
            return _callee_name(node)
    except _UnsupportedSyntax:
        return None
    return None


def _target_text(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__


def _iter_python_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        if path.suffix == ".py":
            yield path
        return
    if not path.is_dir():
        return
    ignored = {".git", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache"}
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [dirname for dirname in dirnames if dirname not in ignored]
        for filename in filenames:
            if filename.endswith(".py"):
                yield Path(dirpath) / filename


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _effect_sort_key(effect: Json) -> str:
    kind = effect.get("kind")
    if kind == "reads":
        return f"0:reads:{effect.get('target', '')}"
    if kind == "writes":
        return f"1:writes:{effect.get('target', '')}"
    if kind == "io":
        return "2:io"
    if kind == "unsafe":
        return "3:unsafe"
    if kind == "panics":
        return "4:panics"
    if kind == "unresolved_call":
        return f"5:unresolved:{effect.get('name', '')}"
    if kind == "opaque_loop":
        return f"6:opaque_loop:{effect.get('loopCid', '')}"
    return f"99:{kind}"


_BINOPS: dict[type[ast.operator], str] = {
    ast.Add: "python:add",
    ast.Sub: "python:sub",
    ast.Mult: "python:mul",
    ast.Div: "python:div",
    ast.FloorDiv: "python:floordiv",
    ast.Mod: "python:mod",
    ast.Pow: "python:pow",
    ast.LShift: "python:lshift",
    ast.RShift: "python:rshift",
    ast.BitAnd: "python:bitand",
    ast.BitOr: "python:bitor",
    ast.BitXor: "python:bitxor",
}

_UNARYOPS: dict[type[ast.unaryop], str] = {
    ast.USub: "python:neg",
    ast.UAdd: "python:pos",
    ast.Not: "python:not",
    ast.Invert: "python:bitnot",
}

_CMPOPS: dict[type[ast.cmpop], str] = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Is: "is",
    ast.IsNot: "is not",
    ast.In: "in",
    ast.NotIn: "not in",
}

_GUARD_CMP_OPS: dict[type[ast.cmpop], str] = {
    ast.Eq: "=",
    ast.NotEq: "≠",
    ast.Lt: "<",
    ast.LtE: "≤",
    ast.Gt: ">",
    ast.GtE: "≥",
}

_NEGATED_ATOMIC: dict[str, str] = {
    "=": "≠",
    "≠": "=",
    "<": "≥",
    "≤": ">",
    ">": "≤",
    "≥": "<",
    "true": "false",
    "false": "true",
}
