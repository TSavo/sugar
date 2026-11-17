"""A caller's contract takes the ``global:`` inputs of every same-file
contract its calls by name are the edge to (#7757 step 5, "Edge, join at
prove"), not only a module ``def``'s.

A call of a module class is the edge to the ``def`` stating its
constructor (``ClassDefinitionValue._constructor_edge_call``), and a call
of a plain ``def`` a module ``if`` binds on one route is the edge to that
``def`` (the function value the route bound).  Each edge supplies every
``global:`` input of its callee's contract (``py.global``).  The caller's
contract took none of them, so the edge supplied a variable no contract
binds, and ``ScopedFormula`` refused the caller by it (``illegal free
var(s): undecided:global:pa@...``: pandas ``core/arrays/arrow/array.py``'s
lambdas calling ``cast_for_truediv`` under ``if HAS_PYARROW:``,
``core/computation/scope.py::ensure_scope`` calling ``Scope(...)``; numpy
``_utils/_pep440.py::parse`` calling ``Version(...)``,
``ctypeslib/_ctypeslib.py::_ctype_from_dtype`` under ``else:``).
"""

from __future__ import annotations


def _tree(tmp_path, source):
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    producer = tmp_path / "producer.py"
    producer.write_text(source)
    return open_source_file_for_construction(producer, root=tmp_path)


def _function(tree, name):
    (found,) = [fn for fn in tree.functions() if fn.name == name]
    return found


_CLASS_CALL = (
    "X = 1\n\n\n"
    "class Box:\n"
    "    def __init__(self):\n"
    "        self.v = X\n\n\n"
    "def make():\n"
    "    return Box()\n\n\n"
    "def outer():\n"
    "    return make()\n"
)

_CONDITIONAL_DEF_CALL = (
    "import idn\n\n"
    "LIMIT = 3\n\n"
    "if idn.FLAG:\n\n"
    "    def helper():\n"
    "        return LIMIT\n\n\n"
    "def caller():\n"
    "    return helper()\n"
)


def test_a_class_call_takes_the_constructor_s_global_inputs(tmp_path):
    from sugar_source_tree.nodes import _global_input_names

    tree = _tree(tmp_path, _CLASS_CALL)
    init = _function(tree, "__init__")
    make = _function(tree, "make")
    outer = _function(tree, "outer")

    assert make.unit.definitions_a_call_joins(make.body[0].value.func) == (init,)
    assert _global_input_names(init) == frozenset({"X"})
    # ``Box()`` supplies ``py.global("X", ...)`` to ``__init__``'s contract:
    # ``make`` takes it, and so does its caller, read off ``make``'s.
    assert _global_input_names(make) == frozenset({"X"})
    assert _global_input_names(outer) == frozenset({"X"})


def test_a_class_with_no_source_constructor_joins_no_def(tmp_path):
    from sugar_source_tree.nodes import _global_input_names

    tree = _tree(
        tmp_path,
        "X = 1\n\n\nclass Box:\n    pass\n\n\ndef make():\n    return Box()\n",
    )
    make = _function(tree, "make")

    # No source ``def`` states the call's signature: the edge supplies no
    # ``global:`` input, and the class is a definition, never an input.
    assert make.unit.definitions_a_call_joins(make.body[0].value.func) == ()
    assert _global_input_names(make) == frozenset()


def test_a_call_of_a_def_bound_on_one_route_takes_its_global_inputs(tmp_path):
    from sugar_source_tree.nodes import _global_input_names

    tree = _tree(tmp_path, _CONDITIONAL_DEF_CALL)
    helper = _function(tree, "helper")
    caller = _function(tree, "caller")

    assert caller.unit.definitions_a_call_joins(caller.body[0].value.func) == (
        helper,
    )
    assert _global_input_names(caller) == frozenset({"LIMIT"})


def test_a_local_name_of_the_same_spelling_joins_no_module_def(tmp_path):
    from sugar_source_tree.nodes import _global_input_names

    tree = _tree(
        tmp_path,
        _CONDITIONAL_DEF_CALL
        + "\n\ndef shadow():\n"
        "    def helper():\n"
        "        return 0\n"
        "    return helper()\n",
    )
    shadow = _function(tree, "shadow")
    call = shadow.body[1].value

    # The read is ``shadow``'s own local: the call is the local ``def``'s,
    # whose reads are ``shadow``'s own, never the module ``helper``'s.
    assert shadow.unit.definitions_a_call_joins(call.func) == ()
    assert _global_input_names(shadow) == frozenset()
