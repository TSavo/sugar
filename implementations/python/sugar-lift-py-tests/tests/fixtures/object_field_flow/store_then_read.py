class Parcel:
    pass


def truthful():
    item = Parcel()
    item.payload = 7
    assert item.payload == 7


def lying():
    item = Parcel()
    item.payload = 7
    assert item.payload == 8


class Capsule:
    pass


def renamed_truthful():
    vessel = Capsule()
    vessel.marker = 7
    assert vessel.marker == 7


def renamed_lying():
    vessel = Capsule()
    vessel.marker = 7
    assert vessel.marker == 8
