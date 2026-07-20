#!/usr/bin/env python3
"""check_node_kind.py -- print the ast-derived NodeKind vocabulary for the
running interpreter, mirroring the class-selection logic of
node_kind.py:_ast_class_names() (concrete/leaf ast.AST subclasses only,
abstract grouping bases like expr/stmt excluded). Used to diff the
vocabulary between host python3.12.3 and the 3.12.13 container per #5940
("NodeKind survives as the wire/CID projection... generated from dir(ast)
on whatever CPython is running").
"""

import ast
import sys


def ast_class_names() -> list[str]:
    classes = {
        value
        for name, value in vars(ast).items()
        if not name.startswith("_")
        and isinstance(value, type)
        and issubclass(value, ast.AST)
        and value is not ast.AST
    }
    return sorted(
        cls.__name__
        for cls in classes
        if not any(other is not cls and issubclass(other, cls) for other in classes)
    )


if __name__ == "__main__":
    print(f"# python {sys.version}")
    for name in ast_class_names():
        print(name)
