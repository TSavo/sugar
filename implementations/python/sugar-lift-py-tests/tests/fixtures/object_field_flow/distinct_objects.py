class Parcel:
    pass


def truthful():
    left = Parcel()
    right = Parcel()
    left.payload = 7
    right.payload = 11
    assert (left.payload, right.payload) == (7, 11)


def lying():
    left = Parcel()
    right = Parcel()
    left.payload = 7
    right.payload = 11
    assert (left.payload, right.payload) == (11, 11)


class Capsule:
    pass


def renamed_truthful():
    first = Capsule()
    second = Capsule()
    first.marker = 7
    second.marker = 11
    assert (first.marker, second.marker) == (7, 11)


def renamed_lying():
    first = Capsule()
    second = Capsule()
    first.marker = 7
    second.marker = 11
    assert (first.marker, second.marker) == (11, 11)
