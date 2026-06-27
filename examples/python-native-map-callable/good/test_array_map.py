def id(x):
    return x


def test_array_map_sugar():
    assert list(map(id, range(1, 6))) == [1, 2, 3, 4, 5]
