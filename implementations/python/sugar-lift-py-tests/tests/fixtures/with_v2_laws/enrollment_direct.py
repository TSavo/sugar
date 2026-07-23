class ProtocolResource:
    pass


class Sugar:
    pass


class WithResourceSugar(Sugar):
    pass


def make_payload():
    return ProtocolResource()


doors = {"anything": make_payload}


def demand(imported):
    targetSymbol = imported
    builder = doors[targetSymbol]
    return WithResourceSugar(builder())
