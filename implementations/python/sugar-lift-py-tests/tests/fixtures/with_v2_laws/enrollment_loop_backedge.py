class Boundary:
    pass


class Sugar:
    pass


class WithResourceSugar(Sugar):
    pass


def build():
    return Boundary()


table = {"anything": build}


def demand(lookup_key, cond, ready):
    chosen = table[lookup_key]
    while cond:
        if ready:
            return WithResourceSugar(carried)
        carried = chosen()
