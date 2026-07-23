def truthful():
    parcel = {}
    parcel[2] = 7
    assert parcel[2] == 7


def lying():
    parcel = {}
    parcel[2] = 7
    assert parcel[2] == 8


def renamed_truthful():
    capsule = {}
    capsule[2] = 7
    assert capsule[2] == 7


def renamed_lying():
    capsule = {}
    capsule[2] = 7
    assert capsule[2] == 8
