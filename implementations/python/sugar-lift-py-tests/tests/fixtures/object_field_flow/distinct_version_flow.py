class Parcel:
    pass


def truthful():
    left = Parcel()
    right = Parcel()
    left_alias = left
    right_alias = right
    left.payload = 2
    right.payload = 5
    left_before = left_alias.payload
    right_before = right_alias.payload
    left_alias.payload = 11
    right_alias.payload = 17
    assert (left_before, right_before, left.payload, right.payload) == (2, 5, 11, 17)


def lying():
    left = Parcel()
    right = Parcel()
    left_alias = left
    right_alias = right
    left.payload = 2
    right.payload = 5
    left_before = left_alias.payload
    right_before = right_alias.payload
    left_alias.payload = 11
    right_alias.payload = 17
    assert (left_before, right_before, left.payload, right.payload) == (5, 2, 17, 11)


class Capsule:
    pass


def renamed_truthful():
    first = Capsule()
    second = Capsule()
    first_echo = first
    second_echo = second
    first.marker = 2
    second.marker = 5
    first_earlier = first_echo.marker
    second_earlier = second_echo.marker
    first_echo.marker = 11
    second_echo.marker = 17
    assert (first_earlier, second_earlier, first.marker, second.marker) == (
        2,
        5,
        11,
        17,
    )


def renamed_lying():
    first = Capsule()
    second = Capsule()
    first_echo = first
    second_echo = second
    first.marker = 2
    second.marker = 5
    first_earlier = first_echo.marker
    second_earlier = second_echo.marker
    first_echo.marker = 11
    second_echo.marker = 17
    assert (first_earlier, second_earlier, first.marker, second.marker) == (
        5,
        2,
        17,
        11,
    )
