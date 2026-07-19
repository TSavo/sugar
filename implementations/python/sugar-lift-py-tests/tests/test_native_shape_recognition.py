from sugar_lift_py_tests.recognition.native_shape import (
    NativeShape,
    has_native_shape,
    recognize_native_call,
    recognize_native_decorator,
    recognizes_identity_decorator,
    recognizes_module_name,
    recognize_source_callable,
)


def test_registered_call_coordinates_resolve_to_semantic_shapes() -> None:
    assert recognize_native_call("numpy.add") is NativeShape.INTEGER_ADD
    assert has_native_shape("numpy.nditer", NativeShape.ITERATOR)
    assert has_native_shape("numpy.nditer", NativeShape.NEVER_SUPPRESSING_MANAGER)
    assert recognizes_identity_decorator(
        "pandas.api.extensions", "register_series_accessor"
    )


def test_similar_unregistered_coordinates_do_not_gain_native_behavior() -> None:
    assert recognize_native_call("project.add") is None
    assert not has_native_shape("project.nditer", NativeShape.ITERATOR)
    assert not recognizes_identity_decorator(
        "project.api.extensions", "register_series_accessor"
    )
    assert not recognizes_module_name("local_vendor")


def test_numpy_all_and_isnat_require_authenticated_coordinates() -> None:
    assert recognize_native_call("numpy.all") is NativeShape.NUMPY_ALL
    assert recognize_native_call("numpy.isnat") is NativeShape.NUMPY_ISNAT
    assert has_native_shape("numpy.all", NativeShape.NUMPY_ALL)
    assert has_native_shape("numpy.isnat", NativeShape.NUMPY_ISNAT)
    assert recognize_native_call("project.all") is None
    assert not has_native_shape("project.all", NativeShape.NUMPY_ALL)


def test_functools_wraps_is_an_authenticated_native_decorator_shape() -> None:
    assert (
        recognize_native_decorator("functools.wraps")
        is NativeShape.IMPLEMENTATION_PRESERVING_DECORATOR
    )
    assert recognize_native_decorator("project.wraps") is None
    assert recognize_native_decorator("wraps") is None


def test_source_callable_authentication_has_lying_unresolved_twin() -> None:
    class Resolved:
        name = "extractor"
        body = object()

    class Unresolved:
        name = "extractor"
        body = None

    assert (
        recognize_source_callable(Resolved())
        is NativeShape.SOURCE_AUTHENTICATED_CALLABLE
    )
    assert recognize_source_callable(Unresolved()) is None


def test_numpy_batch_coordinates_and_lying_twins() -> None:
    names = (
        "iter_goto1d", "npyiter_has_delayed_bufalloc", "npyiter_has_index",
        "numpy.ScalarType.index", "numpy.ediff1d", "numpy.finfo", "numpy.prod",
        "numpy.result_type", "numpy.__array_namespace__", "numpy.__eq__",
        "numpy.__le__", "numpy.__gt__", "numpy.__ge__", "numpy.__lt__",
        "numpy.__ne__", "uniform", "strip", "selectedrealkind", "pytest.approx", "op",
    )
    for name in names:
        assert recognize_native_call(name) is not None
        assert recognize_native_call(f"project.{name}") is None
