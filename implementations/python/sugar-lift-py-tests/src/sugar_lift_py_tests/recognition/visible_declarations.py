"""Source-order testimony shared by import-authenticated recognizers."""

from __future__ import annotations

import ast
import symtable

from sugar_lift_python_source.source_tables import locate_parsed_node, parsed_parents


def visible_declarations(statement):
    """Return declarations visible before ``statement`` and shadowing parameters."""

    source = getattr(statement, "source", None)
    if not source:
        return (), frozenset()
    parsed = parsed_parents(source)
    if parsed is None:
        return (), frozenset()
    tree, parents = parsed
    del tree
    target = locate_parsed_node(
        source, type(statement.node), statement.line, statement.col
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
                if not isinstance(sibling, ast.stmt):
                    continue
                for declaration in _visible_recognition_declarations(
                    sibling, tuple(declarations)
                ):
                    declarations.append(
                        SourceFragment.from_node(
                            declaration,
                            statement.filename or "",
                            source=source,
                        )
                    )
            break
    return tuple(declarations), frozenset(shadowed)


def _visible_recognition_declarations(
    statement: ast.stmt, prior_declarations
) -> tuple[ast.stmt, ...]:
    """Expose imports whose success is required to reach a later statement."""

    if not isinstance(statement, ast.Try):
        return (statement,)
    if statement.orelse or statement.finalbody or not statement.body:
        return (statement,)
    if not statement.handlers or not all(
        handler.body and all(isinstance(item, ast.Pass) for item in handler.body)
        for handler in statement.handlers
    ):
        return (statement,)
    guarded_names: set[str] = set()
    for declaration in statement.body:
        if not isinstance(declaration, (ast.Import, ast.ImportFrom)):
            return (statement,)
        guarded_names.update(
            alias.asname or alias.name.split(".", 1)[0] for alias in declaration.names
        )
    if guarded_names & {
        name
        for declaration in prior_declarations
        for name in _bound_declaration_names(declaration)
    }:
        return (statement,)
    return tuple(statement.body)


def _bound_declaration_names(declaration) -> tuple[str, ...]:
    if declaration.observed == "Import":
        return tuple(
            alias or name.split(".", 1)[0] for name, alias in declaration.import_names()
        )
    if declaration.observed == "ImportFrom":
        return tuple(alias or name for name, alias in declaration.importfrom_names())
    if declaration.observed == "ClassDef":
        return (declaration.class_name(),)
    if declaration.observed in {"FunctionDef", "AsyncFunctionDef"}:
        return (declaration.function_name(),)
    return tuple(declaration.stored_or_deleted_names())


def lexical_function_bindings(statement) -> frozenset[str]:
    """Names local to the exact Python symbol-table scope containing the site."""

    path = _source_path(statement)
    if path is None:
        return frozenset()
    source = statement.source
    table = symtable.symtable(source, statement.filename or "", "exec")
    table_parent = path[0]
    for scope in _symbol_table_scopes(path):
        if isinstance(scope, (ast.ListComp, ast.SetComp, ast.DictComp)):
            # Python 3.12 inlines these comprehensions (PEP 709); their
            # bindings are represented in the containing table.
            continue
        identity = _scope_identity(scope)
        ast_matches = [
            candidate
            for candidate in _direct_symbol_scopes(table_parent)
            if _scope_identity(candidate) == identity
        ]
        table_matches = [
            candidate
            for candidate in table.get_children()
            if (
                candidate.get_type(),
                candidate.get_name(),
                candidate.get_lineno(),
            )
            == identity
        ]
        occurrence = next(
            (
                index
                for index, candidate in enumerate(ast_matches)
                if candidate is scope
            ),
            -1,
        )
        if occurrence < 0 or occurrence >= len(table_matches):
            return frozenset()
        table = table_matches[occurrence]
        table_parent = scope
    return frozenset(
        symbol.get_name()
        for symbol in table.get_symbols()
        if symbol.is_local() or symbol.is_parameter() or symbol.is_imported()
    )


def declaration_is_function_local(statement, declaration) -> bool:
    """Whether a visible declaration belongs to the site's binding scope.

    Function-body declarations match the enclosing ``FunctionDef``. Module-level
    sites share module scope with module-level imports, so a later free-variable
    rebinding law does not revoke the import that established the name.
    Nested lambda/comprehension scopes never own outer declarations.
    """

    return declarations_are_function_local(statement, (declaration,))[0]


def declarations_are_function_local(statement, declarations) -> tuple[bool, ...]:
    """Classify declarations against one shared source-path lookup."""

    path = _source_path(statement)
    if path is None:
        return tuple(False for _ in declarations)
    innermost = next(iter(reversed(_symbol_table_scopes(path))), None)
    if isinstance(
        innermost,
        (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp),
    ):
        return tuple(False for _ in declarations)
    function = next(
        (
            node
            for node in reversed(path)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ),
        None,
    )
    if function is None:
        # Module-level site: ``visible_declarations`` already filters to
        # preceding module statements, which share this scope.
        return tuple(True for _ in declarations)
    end_line = getattr(function, "end_lineno", function.lineno)
    return tuple(
        function.lineno < declaration.line <= end_line for declaration in declarations
    )


def _source_path(statement):
    source = getattr(statement, "source", None)
    if not source:
        return None
    parsed = parsed_parents(source)
    if parsed is None:
        return None
    _tree, parents = parsed
    target = locate_parsed_node(
        source, type(statement.node), statement.line, statement.col
    )
    if target is None:
        return None
    path = [target]
    while path[-1] in parents:
        path.append(parents[path[-1]])
    path.reverse()
    return tuple(path)


def _symbol_table_scopes(path):
    return tuple(
        node
        for node in path
        if isinstance(
            node,
            (
                ast.ClassDef,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.Lambda,
                ast.ListComp,
                ast.SetComp,
                ast.DictComp,
                ast.GeneratorExp,
            ),
        )
    )


def _scope_identity(scope) -> tuple[str, str, int]:
    if isinstance(scope, ast.ClassDef):
        return ("class", scope.name, scope.lineno)
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return ("function", scope.name, scope.lineno)
    if isinstance(scope, ast.Lambda):
        return ("function", "lambda", scope.lineno)
    names = {
        ast.ListComp: "listcomp",
        ast.SetComp: "setcomp",
        ast.DictComp: "dictcomp",
        ast.GeneratorExp: "genexpr",
    }
    return ("function", names[type(scope)], scope.lineno)


def _direct_symbol_scopes(parent):
    scopes = []

    def visit(node) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child,
                (
                    ast.ClassDef,
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.Lambda,
                    ast.GeneratorExp,
                ),
            ):
                scopes.append(child)
                continue
            # List/set/dict comprehensions are inlined on the required 3.12
            # interpreter, so table-bearing lambdas beneath them remain direct
            # children of the containing symbol table.
            visit(child)

    visit(parent)
    return tuple(scopes)


__all__ = [
    "declaration_is_function_local",
    "declarations_are_function_local",
    "lexical_function_bindings",
    "visible_declarations",
]
