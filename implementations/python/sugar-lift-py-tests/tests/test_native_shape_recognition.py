from sugar_lift_py_tests.factory.native_shape import (
    NativeShape,
    has_native_shape,
    recognize_native_call,
    recognizes_identity_decorator,
    recognizes_module_name,
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
