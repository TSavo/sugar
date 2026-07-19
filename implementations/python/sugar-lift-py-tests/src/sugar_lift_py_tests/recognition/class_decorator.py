from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from sugar_lift_py_tests.recognition.native_shape import (
    NativeShape,
    recognize_native_call,
    recognize_native_class_decorator,
    recognize_native_fixture_decorator,
    recognize_native_instance_class_decorator,
)
from sugar_lift_py_tests.recognition.visible_declarations import (
    visible_declarations,
)

if TYPE_CHECKING:
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment


def class_decorators_preserve_identity(statement) -> bool:
    """Authenticate identity-preserving class decorators from source coordinates."""
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    try:
        root = SourceFragment.from_source(statement.source, statement.filename or "")
    except (SyntaxError, TypeError):
        return False
    del root

    imported: dict[str, str] = {}
    constructed: dict[str, NativeShape] = {}
    declarations, shadowed_parameters = visible_declarations(statement)
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
            fixture_shape = _fixture_parameter_native_shape(statement, head)
            if fixture_shape is None or not separator:
                return False
            decorator_shape = recognize_native_instance_class_decorator(
                fixture_shape, tail
            )
            if decorator_shape is not NativeShape.CLASS_IDENTITY_DECORATOR:
                return False
            continue
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


def _fixture_parameter_native_shape(statement, parameter: str) -> NativeShape | None:
    """Authenticate an injected fixture through its source-declared provider."""
    from sugar_lift_python_source.source_tables import parsed_parents

    parsed = parsed_parents(getattr(statement, "source", "") or "")
    if parsed is None:
        return None
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
        return None
    path = [target]
    while path[-1] in parents:
        path.append(parents[path[-1]])
    function = next(
        (
            node
            for node in path
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ),
        None,
    )
    owner = next((node for node in path[1:] if isinstance(node, ast.ClassDef)), None)
    if (
        function is None
        or owner is None
        or parameter not in _function_parameter_names(function)
    ):
        return None

    imports = _module_imports(tree)
    local_classes = {
        node.name: node for node in tree.body if isinstance(node, ast.ClassDef)
    }
    from sugar_lift_py_tests.sugar.install_source_dig import (
        resolve_install_source_class_method,
    )

    for qualified_base in _qualified_class_bases(
        owner, imports, local_classes, frozenset()
    ):
        provider = resolve_install_source_class_method(qualified_base, parameter)
        if provider is None:
            continue
        shape = _fixture_provider_native_shape(provider)
        if shape is not None:
            return shape
    return None


def _fixture_provider_native_shape(provider) -> NativeShape | None:
    """Read the provider body only at the already-resolved source seat.

    Match by exact module + line/col (content seat), never by bare method name
    across the module — two classes can declare identically named fixtures.
    """
    from sugar_lift_python_source.source_oracle import installed_module_source

    module_name = getattr(provider.node, "_sugar_defining_module", None)
    if not module_name:
        return None
    installed = installed_module_source(module_name)
    if installed is None:
        return None
    source, _, _ = installed
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    imports = _module_imports(tree, module_name)
    function = _function_at_provider_seat(tree, provider)
    if function is None or not _is_authenticated_fixture(
        function, imports, tree=tree
    ):
        return None
    constructed: dict[str, NativeShape] = {}
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            shape = _ast_call_native_shape(node.value, imports)
            if shape is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constructed[target.id] = shape
        elif isinstance(node, (ast.Yield, ast.Return)):
            value = node.value
            if isinstance(value, ast.Name) and value.id in constructed:
                return constructed[value.id]
            shape = _ast_call_native_shape(value, imports)
            if shape is not None:
                return shape
    return None


def _function_at_provider_seat(
    tree: ast.Module, provider
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Locate the FunctionDef at the provider's exact source seat.

    Seat identity: function name + lineno + col_offset from the already-resolved
    provider fragment. Name-only search is illegal (mismatched class fixtures).
    """
    target_name = provider.function_name()
    target_line = getattr(provider, "line", None)
    target_col = getattr(provider, "col", None)
    if target_name is None or target_line is None or target_col is None:
        return None
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if function.name != target_name:
            continue
        if getattr(function, "lineno", None) != target_line:
            continue
        if getattr(function, "col_offset", None) != target_col:
            continue
        return function
    return None


def _is_authenticated_fixture(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: dict[str, str],
    *,
    tree: ast.Module | None = None,
) -> bool:
    """True when a decorator is a registered fixture protocol shape.

    Resolves the decorator through the module import map (rebinding revokes
    warrants) and refuses class-body shadows of the decorator head. Lookup is
    only in the kit-loaded fixture protocol table — never a vendor-name string
    Compare in this module (R_vendor_special_case floor).
    """
    class_shadows = (
        _enclosing_class_stored_names(function, tree) if tree is not None else frozenset()
    )
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        dotted = _ast_dotted_name(target)
        if dotted is None:
            continue
        head, _sep, _tail = dotted.partition(".")
        if head in class_shadows:
            # Class-body rebind of the import head revokes the module warrant
            # (methods' decorators evaluate in the class body namespace).
            continue
        qualified = _qualified_ast_name(target, imports)
        if (
            recognize_native_fixture_decorator(qualified)
            is NativeShape.FIXTURE_DECORATOR
        ):
            return True
    return False


def _enclosing_class_stored_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    tree: ast.Module,
) -> frozenset[str]:
    """Names stored on the enclosing class body before ``function`` (shadows)."""
    owner = _enclosing_class_for_function(function, tree)
    if owner is None:
        return frozenset()
    names: list[str] = []
    for statement in owner.body:
        if statement is function:
            break
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Nested defs/classes bind their name but do not replace an import
            # used as a decorator head in the typical fixture pattern; skip.
            continue
        names.extend(_top_level_stored_names(statement))
    return frozenset(names)


def _enclosing_class_for_function(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    tree: ast.Module,
) -> ast.ClassDef | None:
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if child is function:
                return node
    # Nested / multi-level: walk
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if child is function:
                return node
    return None


def _ast_call_native_shape(
    node: ast.AST | None, imports: dict[str, str]
) -> NativeShape | None:
    if not isinstance(node, ast.Call):
        return None
    return recognize_native_call(_qualified_ast_name(node.func, imports))


def _qualified_ast_name(node: ast.AST, imports: dict[str, str]) -> str | None:
    dotted = _ast_dotted_name(node)
    if dotted is None:
        return None
    head, separator, tail = dotted.partition(".")
    origin = imports.get(head)
    if origin is None:
        return None
    return f"{origin}.{tail}" if separator else origin


def _ast_dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    cursor = node
    while isinstance(cursor, ast.Attribute):
        parts.append(cursor.attr)
        cursor = cursor.value
    if not isinstance(cursor, ast.Name):
        return None
    parts.append(cursor.id)
    return ".".join(reversed(parts))


def _module_imports(tree: ast.Module, module_name: str | None = None) -> dict[str, str]:
    """Module-level import map with later rebinds revoking import warrants.

    Sequential Assign / AnnAssign / FunctionDef / ClassDef / For / With that
    store names clear those bindings so a later ``config = ...`` cannot keep
    the earlier import warrant (lying twin).
    """
    imported: dict[str, str] = {}
    for declaration in tree.body:
        if isinstance(declaration, ast.Import):
            for alias in declaration.names:
                bound = alias.asname or alias.name.split(".", 1)[0]
                imported[bound] = alias.name if alias.asname else bound
            continue
        if isinstance(declaration, ast.ImportFrom):
            module = _absolute_import_module(
                module_name, declaration.module, declaration.level
            )
            if module is None:
                continue
            for alias in declaration.names:
                if alias.name != "*":
                    imported[alias.asname or alias.name] = f"{module}.{alias.name}"
            continue
        for bound in _top_level_stored_names(declaration):
            imported.pop(bound, None)
    return imported


def _top_level_stored_names(declaration: ast.AST) -> frozenset[str]:
    if isinstance(declaration, ast.Assign):
        names: list[str] = []
        for target in declaration.targets:
            names.extend(_ast_store_names(target))
        return frozenset(names)
    if isinstance(declaration, ast.AnnAssign) and isinstance(
        declaration.target, ast.Name
    ):
        return frozenset((declaration.target.id,))
    if isinstance(declaration, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return frozenset((declaration.name,))
    if isinstance(declaration, (ast.For, ast.AsyncFor)):
        return frozenset(_ast_store_names(declaration.target))
    if isinstance(declaration, (ast.With, ast.AsyncWith)):
        names = []
        for item in declaration.items:
            if item.optional_vars is not None:
                names.extend(_ast_store_names(item.optional_vars))
        return frozenset(names)
    return frozenset()


def _ast_store_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in target.elts:
            names.extend(_ast_store_names(elt))
        return names
    return []


def _absolute_import_module(
    defining_module: str | None, imported: str | None, level: int
) -> str | None:
    if level == 0:
        return imported
    if defining_module is None:
        return None
    package = defining_module.split(".")[:-1]
    if level > len(package):
        return None
    prefix = package[: len(package) - level + 1]
    if imported:
        prefix.extend(imported.split("."))
    return ".".join(prefix)


def _qualified_class_bases(
    owner: ast.ClassDef,
    imports: dict[str, str],
    local_classes: dict[str, ast.ClassDef],
    resolving: frozenset[str],
) -> tuple[str, ...]:
    resolved: list[str] = []
    for base in owner.bases:
        dotted = _ast_dotted_name(base)
        if dotted is None:
            continue
        head, separator, tail = dotted.partition(".")
        origin = imports.get(head)
        if origin is not None:
            resolved.append(f"{origin}.{tail}" if separator else origin)
            continue
        local = local_classes.get(head) if not separator else None
        if local is not None and head not in resolving:
            resolved.extend(
                _qualified_class_bases(
                    local,
                    imports,
                    local_classes,
                    resolving | frozenset((head,)),
                )
            )
    return tuple(resolved)


def _function_parameter_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> frozenset[str]:
    args = function.args
    names = [arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
    if args.vararg is not None:
        names.append(args.vararg.arg)
    if args.kwarg is not None:
        names.append(args.kwarg.arg)
    return frozenset(names)


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
