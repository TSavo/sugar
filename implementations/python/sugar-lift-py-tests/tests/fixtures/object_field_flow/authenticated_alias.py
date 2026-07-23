class Parcel:
    pass


def truthful():
    original = Parcel()
    alias = original
    original.payload = 7
    assert alias.payload == 7


def lying():
    original = Parcel()
    alias = original
    original.payload = 7
    assert alias.payload == 8


class Capsule:
    pass


def renamed_truthful():
    source = Capsule()
    echo = source
    source.marker = 7
    assert echo.marker == 7


def renamed_lying():
    source = Capsule()
    echo = source
    source.marker = 7
    assert echo.marker == 8
