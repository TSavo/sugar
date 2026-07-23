class BoundaryB:
    pass


class Sugar:
    pass


class WithResourceSugar(Sugar):
    pass


def build():
    return BoundaryB()


table = {"anything": build}


def demand(imported):
    lookup_key = imported
    chosen = table[lookup_key]
    return WithResourceSugar(chosen())
