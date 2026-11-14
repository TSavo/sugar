"""A ``**kwargs`` entry is the ``variadic-keyword`` projection of its formal.

``def m(*args, **kwargs): t = g(*args, **kwargs)`` reads each collected
keyword through ``formal.project("variadic-keyword", i)`` -- the coordinate
``bind_node_actuals`` seats on the entry's actual Node, in collection order.
``bind_actuals`` paired ``*args`` elements with their ``variadic`` projections
but never paired ``**kwargs`` entries, so a generator frame read of one found
no Floor and refused ``unspecialized source-call formal``
(``np.printoptions(precision=3)``).  Each entry is now paired with the
caller's own Floor, and the bound-actuals and generator-roster checks admit
exactly that projection.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import DictValue, StringValue, TermValue, TupleValue
from sugar_lift_py_tests.source_call_frame import (
    BoundSourceCallActualsV1,
    SourceCallBindingGap,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


def _frame(source: str, filename: str):
    tree = SourceFile(
        (source, filename, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function.source_visible_call_frame()


def _kwargs_frame(filename: str = "bound_kwargs_coordinates.py"):
    return _frame("def helper(first, *rest, **named):\n    return named\n", filename)


def test_each_collected_keyword_is_paired_with_its_variadic_keyword_projection():
    frame = _kwargs_frame()
    first, extra, precision, legacy = (TermValue(v) for v in (1, 2, 3, 4))

    bound = frame.bind_actuals(
        (first, extra), (("precision", precision), ("legacy", legacy))
    )

    rest_root, named_root = frame.formal_coordinates[1], frame.formal_coordinates[2]
    assert bound.actuals[1] == TupleValue((extra,))
    assert bound.actuals[2] == fresh(
        DictValue,
        ((StringValue("precision"), precision), (StringValue("legacy"), legacy)),
    )
    assert tuple(pair.coordinate for pair in bound.projected_pairs) == (
        rest_root.project("variadic", 0),
        named_root.project("variadic-keyword", 0),
        named_root.project("variadic-keyword", 1),
    )
    pairs = bound.projected_pairs
    assert pairs[0].actual is extra
    assert pairs[1].actual is precision and pairs[2].actual is legacy


def test_a_double_star_expansion_entry_is_projected_too():
    frame = _kwargs_frame()
    precision = TermValue(3)
    bound = frame.bind_actuals(
        (TermValue(1),),
        (("**", fresh(DictValue, ((StringValue("precision"), precision),))),),
    )
    (pair,) = bound.projected_pairs
    assert pair.coordinate == frame.formal_coordinates[2].project("variadic-keyword", 0)
    assert pair.actual is precision


def test_a_named_formal_takes_its_keyword_before_kwargs_collects():
    frame = _kwargs_frame()
    first = TermValue(1)
    bound = frame.bind_actuals((), (("first", first),))
    assert bound.actuals[0] is first
    assert bound.actuals[2] == fresh(DictValue, ())
    assert bound.projected_pairs == ()


@pytest.mark.parametrize("variant", ("wrong-entry", "wrong-kind", "foreign-root"))
def test_a_cross_wired_keyword_projection_is_refused(variant):
    frame = _kwargs_frame()
    foreign = _kwargs_frame(filename="foreign_kwargs_coordinates.py")
    truthful = frame.bind_actuals((TermValue(1),), (("precision", TermValue(3)),))
    (child,) = truthful.projected_pairs
    coordinate = {
        "wrong-entry": frame.formal_coordinates[2].project("variadic-keyword", 1),
        "wrong-kind": frame.formal_coordinates[2].project("variadic", 0),
        "foreign-root": foreign.formal_coordinates[2].project("variadic-keyword", 0),
    }[variant]
    with pytest.raises(SourceCallBindingGap, match="projected formal coordinate"):
        BoundSourceCallActualsV1(
            truthful.actuals,
            truthful.formal_coordinates,
            truthful.native_formal_coordinates,
            (replace(child, coordinate=coordinate),),
        )


def test_printoptions_reads_its_keyword_through_kwargs(tmp_path):
    """``np.printoptions(precision=3)`` binds ``kwargs`` and enters its body.

    It used to refuse at ``**kwargs`` (``unspecialized source-call formal``);
    now ``precision=3`` and ``printoptions()`` reach the same point inside
    ``_set_printoptions``.
    """
    from sugar_lift_python_source.resolution_session import SourceResolutionSession
    from sugar_source_tree.panic import SugarNotWritten

    from test_numpy_errstate_construction import _corpus, _open

    observed = {}
    for label, call in (("bare", "np.printoptions()"), ("kw", "np.printoptions(precision=3)")):
        (tmp_path / label).mkdir()
        root = _corpus(
            tmp_path / label,
            **{"e.py": f"import numpy as np\ndef f():\n    with {call}:\n        return 1\n"},
        )
        source_file = _open(
            root,
            "e.py",
            session=SourceResolutionSession(
                enrolled_distributions=frozenset({"tiny-corpus", "numpy"})
            ),
        )
        func = next(
            n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
        )
        try:
            func.sugar().desugar()
        except SugarNotWritten as exc:
            observed[label] = str(exc.observed)
        else:
            observed[label] = None
    assert "unspecialized source-call formal" not in str(observed["kw"])
    assert observed["kw"] == observed["bare"]
