class Payload:
    pass


class Box:
    pass


class Sugar:
    pass


class WithResourceSugar(Sugar):
    pass


def build():
    return Payload()


table = {"anything": build}


def demand(imported):
    chosen = table[imported]
    boxed = Box(chosen())
    WithResourceSugar()
    return boxed
