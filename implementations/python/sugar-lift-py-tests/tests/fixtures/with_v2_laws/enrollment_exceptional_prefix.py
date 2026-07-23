class Boundary:
    pass


class Sugar:
    pass


class WithResourceSugar(Sugar):
    pass


class Boom(Exception):
    pass


def build():
    return Boundary()


table = {"anything": build}


def demand(lookup_key):
    chosen = table[lookup_key]
    try:
        carried = chosen()
        raise Boom()
    except Boom:
        return WithResourceSugar(carried)
