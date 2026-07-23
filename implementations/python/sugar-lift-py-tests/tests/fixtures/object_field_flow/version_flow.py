class Parcel:
    pass


def truthful():
    original = Parcel()
    original.payload = 3
    before = original.payload
    alias = original
    second_alias = alias
    alias.payload = 8
    after = second_alias.payload
    assert (before, after) == (3, 8)


def lying():
    original = Parcel()
    original.payload = 3
    before = original.payload
    alias = original
    second_alias = alias
    alias.payload = 8
    after = second_alias.payload
    assert (before, after) == (8, 3)


class Capsule:
    pass


def renamed_truthful():
    source = Capsule()
    source.marker = 3
    earlier = source.marker
    echo = source
    echo_again = echo
    echo.marker = 8
    later = echo_again.marker
    assert (earlier, later) == (3, 8)


def renamed_lying():
    source = Capsule()
    source.marker = 3
    earlier = source.marker
    echo = source
    echo_again = echo
    echo.marker = 8
    later = echo_again.marker
    assert (earlier, later) == (8, 3)
