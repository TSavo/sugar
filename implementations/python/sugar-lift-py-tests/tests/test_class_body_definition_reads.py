"""A class body's read of a name an earlier ``def`` in that body binds is the
value the statement bound, never the free name (#7757).

The nine-step lane (main 13e3413ad) refused about 76 pandas and 57 numpy
functions by ``proofir.scope.ScopedFormula`` (``illegal free var(s):
mgr_locs``, ``_get_names, _set_names``, ``coeffs``, ``flat``, ``A, A1, H,
I, T``, ...).  Each is a class body reading the name a ``def`` above it in the
same body bound:

- ``@mgr_locs.setter`` (and ``@freq.setter``, ``@flat.setter``, ...): a
  decorator reading the property the previous ``@property def`` bound;
- ``names = property(fset=_set_names, fget=_get_names)``, ``T =
  property(transpose)``: an argument reading a plain method;
- ``getT = T.fget``, ``c = coef = coefficients = coeffs``: an alias.

The class body's ``def`` bound nothing for the statements after it
(``_local_definition_binding`` answered None: the name is no function local
and no module name a reader is threaded for), so the read stayed the bare
name: the free name the scope law refused the class by, and every method of
it with it.  Python runs a class body as a block and finds the name in the
class namespace first (``LOAD_NAME``): the read is the statement's value
under its evaluation key, as a function-local ``def``'s read is.

THE DISCRIMINATION: a read before the ``def`` is not the class body's
binding (the namespace does not hold it yet), and a class body that never
reads a method's name binds nothing for it.
"""

from __future__ import annotations

from sugar_source_tree.nodes import (
    Attribute,
    ClassDef,
    DecoratedDefinitionRef,
    FunctionDef,
)

from test_module_global_evaluation_reference import _source

ALIAS_OF_A_METHOD = (
    "def _get(self):\n"
    "    return 2\n"
    "\n"
    "\n"
    "class Box:\n"
    "    early = _get\n"
    "\n"
    "    def _get(self):\n"
    "        return 1\n"
    "\n"
    "    late = _get\n"
    "    size = property(_get)\n"
)

PROPERTY_SETTER = (
    "class Box:\n"
    "    @property\n"
    "    def size(self):\n"
    "        return 1\n"
    "\n"
    "    @size.setter\n"
    "    def size(self, value):\n"
    "        pass\n"
)

UNREAD_METHOD = "class Box:\n    def size(self):\n        return 1\n"


def _class(tree, name: str = "Box") -> ClassDef:
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, ClassDef) and node.name == name
    )


def _threaded_body(klass: ClassDef) -> tuple:
    body, _changed = klass._substitute_body(klass.body, {})
    return body


def _assigned(body, name: str):
    """The substituted value of the class-body assignment ``name = <value>``."""
    return next(
        item.value
        for item in body
        if any(
            getattr(target, "id", None) == name
            for target in getattr(item, "targets", ())
        )
    )


def _start_line(node) -> int:
    return node.line_col_span().start_line


def test_a_read_after_a_method_is_the_method_the_body_bound() -> None:
    tree = _source(ALIAS_OF_A_METHOD)
    klass = _class(tree)
    body = _threaded_body(klass)
    read = _assigned(body, "late")
    assert isinstance(read, DecoratedDefinitionRef), read
    # The class body's ``def`` (line 8), never the module's (line 1).
    assert _start_line(getattr(read, "definition")) == 8, read
    assert isinstance(getattr(read, "evaluation", None), str), read
    # ``size = property(_get)`` (line 12): the argument is the same value,
    # whatever statement the threading made of the assignment.
    (statement,) = [item for item in body if _start_line(item) == 12]
    references = [
        node for node in statement.walk() if isinstance(node, DecoratedDefinitionRef)
    ]
    assert references, statement
    assert all(
        _start_line(getattr(node, "definition")) == 8 for node in references
    ), references


def test_a_read_before_the_method_is_not_the_class_body_binding() -> None:
    # THE DISCRIMINATION: ``early = _get`` runs before the class body's
    # ``def``; the namespace does not hold it there.
    tree = _source(ALIAS_OF_A_METHOD)
    early = _assigned(_threaded_body(_class(tree)), "early")
    assert not (
        isinstance(early, DecoratedDefinitionRef)
        and _start_line(getattr(early, "definition")) == 8
    ), early


def test_a_property_setter_decorator_reads_the_property_the_body_bound() -> None:
    tree = _source(PROPERTY_SETTER)
    body = _threaded_body(_class(tree))
    getter, setter = [item for item in body if isinstance(item, FunctionDef)]
    (decorator,) = setter.decorators
    assert isinstance(decorator, Attribute), decorator
    assert decorator.attr == "setter"
    receiver = decorator.value
    assert isinstance(receiver, DecoratedDefinitionRef), receiver
    # The ``@property def size`` above it: the decorators' result under that
    # statement's evaluation key, the key the getter statement binds.
    assert _start_line(getattr(receiver, "definition")) == _start_line(getter)
    bound = getattr(getter, "decorated_value", None)
    assert isinstance(bound, DecoratedDefinitionRef), getter
    assert getattr(receiver, "evaluation") == getattr(bound, "evaluation")


def test_only_a_name_the_class_body_reads_is_bound_there() -> None:
    read = _source(PROPERTY_SETTER)
    unread = _source(UNREAD_METHOD)
    getter = min(
        (
            node
            for node in read.nodes()
            if isinstance(node, FunctionDef) and node.name == "size"
        ),
        key=_start_line,
    )
    (method,) = [node for node in unread.nodes() if isinstance(node, FunctionDef)]
    assert getter.unit.class_body_reads_definition(getter)
    assert not method.unit.class_body_reads_definition(method)
    # A module ``def`` stands in no class body.
    module = _source(ALIAS_OF_A_METHOD)
    module_def = next(
        node
        for node in module.nodes()
        if isinstance(node, FunctionDef) and _start_line(node) == 1
    )
    assert not module_def.unit.class_body_reads_definition(module_def)
