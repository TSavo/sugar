from __future__ import annotations

import ast

from sugar_lift_python_source.source_tables import parsed_parents

from sugar_lift_py_tests.recognition.native_shape import (
    NativeShape,
    recognize_native_call,
    recognize_native_class_decorator,
    recognize_native_instance_class_decorator,
)


def class_decorators_preserve_identity(statement) -> bool:
    """Authenticate identity-preserving class decorators from source coordinates."""
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    try:
        root = SourceFragment.from_source(statement.source, statement.filename or "")
    except (SyntaxError, TypeError):
        return False

    imported: dict[str, str] = {}
    constructed: dict[str, NativeShape] = {}
    declarations, shadowed_parameters = _visible_declarations(statement)
    for declaration in declarations:
        if declaration.observed == "ImportFrom":
            module = declaration.importfrom_module()
            if module is None:
                continue
            for name, alias in declaration.importfrom_names():
                bound = alias or name
                imported[bound] = f"{module}.{name}"
                constructed.pop(bound, None)
            continue
        if declaration.observed == "Import":
            for name, alias in declaration.import_names():
                bound = alias or name.split(".", 1)[0]
                imported[bound] = name if alias is not None else bound
                constructed.pop(bound, None)
            continue

        if declaration.observed == "ClassDef":
            assigned = (declaration.class_name(),)
        elif declaration.observed in {"FunctionDef", "AsyncFunctionDef"}:
            assigned = (declaration.function_name(),)
        else:
            assigned = declaration.stored_or_deleted_names()
        constructed_shape = _constructed_native_shape(declaration, imported)
        for bound in assigned:
            imported.pop(bound, None)
            constructed.pop(bound, None)
            if constructed_shape is not None:
                constructed[bound] = constructed_shape

    for decorator in statement.class_decorators():
        receiver = decorator.call_func() if decorator.observed == "Call" else decorator
        if receiver is None:
            return False
        dotted = receiver.dotted_expr_name()
        if dotted is None:
            return False
        head, separator, tail = dotted.partition(".")
        if head in shadowed_parameters:
            return False
        if head in constructed:
            if not separator:
                return False
            decorator_shape = recognize_native_instance_class_decorator(
                constructed[head], tail
            )
        else:
            origin = imported.get(head)
            qualified = (
                origin
                if not separator and origin is not None
                else f"{origin}.{tail}" if separator and origin is not None else None
            )
            decorator_shape = recognize_native_class_decorator(qualified)
        if decorator_shape is not NativeShape.CLASS_IDENTITY_DECORATOR:
            return False
    return True


def _constructed_native_shape(declaration, imported) -> NativeShape | None:
    if declaration.observed != "Assign":
        return None
    value = declaration.assign_value()
    if value.observed != "Call":
        return None
    receiver = value.call_func()
    if receiver is None:
        return None
    dotted = receiver.dotted_expr_name()
    if dotted is None:
        return None
    head, separator, tail = dotted.partition(".")
    origin = imported.get(head)
    qualified = (
        origin
        if not separator and origin is not None
        else f"{origin}.{tail}" if separator and origin is not None else None
    )
    return recognize_native_call(qualified)


def _visible_declarations(statement):
    source = getattr(statement, "source", None)
    if not source:
        return (), frozenset()
    parsed = parsed_parents(source)
    if parsed is None:
        return (), frozenset()
    tree, parents = parsed
    target = next(
        (
            node
            for node in ast.walk(tree)
            if type(node) is type(statement.node)
            and getattr(node, "lineno", None) == statement.line
            and getattr(node, "col_offset", None) == statement.col
        ),
        None,
    )
    if target is None:
        return (), frozenset()
    path = [target]
    while path[-1] in parents:
        path.append(parents[path[-1]])
    path.reverse()

    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    declarations = []
    shadowed: set[str] = set()
    for ancestor, child in zip(path, path[1:]):
        if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = ancestor.args
            shadowed.update(arg.arg for arg in args.posonlyargs)
            shadowed.update(arg.arg for arg in args.args)
            shadowed.update(arg.arg for arg in args.kwonlyargs)
            if args.vararg is not None:
                shadowed.add(args.vararg.arg)
            if args.kwarg is not None:
                shadowed.add(args.kwarg.arg)
        for _, value in ast.iter_fields(ancestor):
            if not isinstance(value, list) or child not in value:
                continue
            for sibling in value[: value.index(child)]:
                if isinstance(sibling, ast.stmt):
                    declarations.append(
                        SourceFragment.from_node(
                            sibling,
                            statement.filename or "",
                            source=source,
                        )
                    )
            break
    return tuple(declarations), frozenset(shadowed)
