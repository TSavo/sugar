from pandas.core.arrays.boolean import BooleanDtype


def test_boolean_dtype_repr_source_warrant():
    dtype = BooleanDtype()
    assert dtype.__repr__() == "BooleanDtype"
