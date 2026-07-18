def A():
    left = [0, 0]
    right = [0, 0]
    left[0], right[1] = (2, 3)
    return left[0] + right[1]


def test_subscript_tuple_unpack():
    assert A() == 6
