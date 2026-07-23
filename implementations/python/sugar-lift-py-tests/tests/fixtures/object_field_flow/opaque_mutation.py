class Parcel:
    pass


def read_after_opaque_mutation(mutator):
    item = Parcel()
    item.payload = 7
    mutator(item)
    return item.payload


class Capsule:
    pass


def renamed_read_after_opaque_mutation(transform):
    vessel = Capsule()
    vessel.marker = 7
    transform(vessel)
    return vessel.marker
